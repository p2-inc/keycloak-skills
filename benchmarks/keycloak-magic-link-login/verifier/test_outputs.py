# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by performing real browser authorization-code logins
against the `acme-portal` client, headlessly: fetch the login page, submit an
email address, and read what actually happened - the captured mail, the realm's
user list - rather than trusting the page response, which is identical on
purpose whether or not the address is registered.

Both known accounts are exercised, so a configuration that happens to work for
one hardcoded user does not pass.
"""

import json
import pathlib
import re
import time
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
CAPTURE_DIR = pathlib.Path("/var/mail-capture")
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

# Seeded in environment/acme-realm.json.
KNOWN_ACCOUNTS = ["priya@acme.example", "marcus@acme.example"]
UNKNOWN_EMAIL = "verifier-ghost@acme.example"


def _read_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session")
def config():
    creds = _read_settings(ADMIN_CREDS_PATH)
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
    }


@pytest.fixture(scope="session")
def admin_headers(config):
    resp = requests.post(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": config["admin_username"],
            "password": config["admin_password"],
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"admin login failed ({resp.status_code}): {resp.text[:300]}"
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _relax_cookies(session):
    """Keycloak marks its auth cookies Secure with SameSite=None.

    A browser sends them anyway over http://localhost, treating it as a secure
    context; `requests` will not, and every form POST otherwise fails as
    `cookie_not_found`, which is a property of this test client, not the realm.
    """
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html, what):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _authorization_url(config, state):
    return (
        f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": config["client_id"],
                "response_type": "code",
                "scope": "openid email",
                "redirect_uri": config["redirect_uri"],
                "state": state,
                "nonce": f"nonce-{state}",
            }
        )
    )


def _submit_email(config, email, state):
    session = requests.Session()
    page = session.get(_authorization_url(config, state), timeout=TIMEOUT)
    assert page.status_code == 200, (
        f"the authorization endpoint returned {page.status_code}: {page.text[:200]}"
    )
    _relax_cookies(session)
    resp = session.post(
        _form_action(page.text, "login"),
        data={"username": email},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    return session, resp


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    matches = sorted(CAPTURE_DIR.glob(f"*{marker}*.json"))
    for path in reversed(matches):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _wait_for_capture(email, since, attempts=10, delay=0.5):
    record = None
    for _ in range(attempts):
        record = _latest_capture_for(email, since)
        if record:
            return record
        time.sleep(delay)
    return record


def _follow_to_redirect_uri(session, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location or location.startswith(redirect_uri):
            return location
        target = (
            location if location.startswith("http") else f"http://localhost:8080{location}"
        )
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    return location


def _user_exists(config, admin_headers, search):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers,
        params={"search": search},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user search failed: {resp.text[:300]}"
    return len(resp.json()) > 0


@pytest.mark.parametrize("email", KNOWN_ACCOUNTS)
def test_a_known_address_receives_mail_with_no_password_prompt(config, email):
    since = time.time()
    _, resp = _submit_email(config, email, f"verify-mail-{email.split('@')[0]}")
    body = resp.text or ""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / f"submit-{email.replace('@', '-at-')}.html").write_text(body[:8000])

    assert 'type="password"' not in body, (
        f"{email} was shown a password field; login must be by emailed link only"
    )

    record = _wait_for_capture(email, since)
    assert record is not None, (
        f"no mail was captured for {email} after submitting it on the login page; "
        "the realm's outgoing mail settings are likely unconfigured"
    )
    body_text = record.get("body_plain") or record.get("body_html") or ""
    assert "action-token" in body_text, (
        f"the captured mail to {email} has no action-token link: {body_text[:200]}"
    )


@pytest.mark.parametrize("email", KNOWN_ACCOUNTS)
def test_the_emailed_link_completes_login_and_preserves_state(config, email):
    state = f"verify-login-{email.split('@')[0]}"
    since = time.time()
    session, resp = _submit_email(config, email, state)
    assert resp.status_code == 200, f"submitting {email} failed: {resp.status_code}"

    record = _wait_for_capture(email, since)
    assert record is not None, f"no mail captured for {email}"
    body_text = record.get("body_plain") or record.get("body_html") or ""
    link_match = re.search(r"(http://\S*action-token\S*)", body_text)
    assert link_match, f"no action-token link in the captured mail: {body_text[:200]}"
    link = link_match.group(1).rstrip(".,)")

    opened = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    final = _follow_to_redirect_uri(
        session, opened.headers.get("Location", ""), config["redirect_uri"]
    )
    assert final and final.startswith(config["redirect_uri"]), (
        f"opening the magic link for {email} never reached "
        f"{config['redirect_uri']}; ended at {final!r}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned for {email}: {final[:250]}"
    assert query.get("state") == [state], (
        f"state was not preserved for {email}: sent {state!r}, got {query.get('state')!r}"
    )


def test_an_unregistered_address_gets_the_same_response_as_a_registered_one(config):
    """The login page must not leak whether an address is registered."""
    state_known = "verify-parity-known"
    state_unknown = "verify-parity-unknown"
    _, known_resp = _submit_email(config, KNOWN_ACCOUNTS[0], state_known)
    _, unknown_resp = _submit_email(config, UNKNOWN_EMAIL, state_unknown)

    assert unknown_resp.status_code == known_resp.status_code, (
        f"an unregistered address got status {unknown_resp.status_code} while a "
        f"registered one got {known_resp.status_code}; the response must not "
        "differ by registration status"
    )


def test_no_mail_or_account_is_created_for_an_unregistered_address(config, admin_headers):
    """Behind the identical page response, nothing observable may happen."""
    since = time.time()
    _submit_email(config, UNKNOWN_EMAIL, "verify-unknown-effects")
    time.sleep(2)

    assert _latest_capture_for(UNKNOWN_EMAIL, since) is None, (
        f"mail was sent to {UNKNOWN_EMAIL}, which belongs to no existing account; "
        "the magic-link authenticator's create-user-if-none-exists setting must "
        "be turned off"
    )
    assert not _user_exists(config, admin_headers, UNKNOWN_EMAIL), (
        f"a new account was created for {UNKNOWN_EMAIL} after it was typed on the "
        "login page; only existing accounts may use this login path"
    )


def test_existing_accounts_still_exist_and_are_enabled(config, admin_headers):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user listing failed: {resp.text[:300]}"
    by_username = {u["username"]: u for u in resp.json()}
    for username in ("priya", "marcus"):
        assert username in by_username, f"the {username} account is gone"
        assert by_username[username].get("enabled") is True, (
            f"the {username} account is disabled"
        )


def test_only_the_acme_realm_was_added(config, admin_headers):
    resp = requests.get(
        f"{config['base']}/admin/realms",
        headers=admin_headers,
        params={"briefRepresentation": "true"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
    )
