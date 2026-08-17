"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by actually performing a real WebAuthn ceremony against
the `acme-portal` client - registering a passkey via a headless browser with a
CDP virtual authenticator (the crypto exchange can't be faked with a plain
HTTP client the way magic-link's redirect-following could), then a fresh
login with that same passkey - and reading what actually happened, rather
than trusting realm configuration alone. The agent's job was to configure the
realm (SMTP, WebAuthn passwordless policy, an authored+bound flow, SMTP) so
that this chain works; the verifier drives the chain itself, the same way the
magic-link verifier submits the login form itself rather than requiring the
agent to have already logged in as the end user.

Both known accounts are exercised, so a configuration that happens to work
for one hardcoded user does not pass.
"""

import json
import pathlib
import re
import time
import urllib.parse

import pytest
import requests
from playwright.sync_api import sync_playwright

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
CAPTURE_DIR = pathlib.Path("/var/mail-capture")
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

# Seeded in environment/acme-realm.json - both start with zero credentials.
KNOWN_ACCOUNTS = ["priya@acme.example", "marcus@acme.example"]


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


def _find_user_id(config, admin_headers, username):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers,
        params={"username": username, "exact": "true"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user search failed: {resp.text[:300]}"
    matches = resp.json()
    assert matches, f"user {username} not found"
    return matches[0]["id"]


def _send_required_action_email(config, admin_headers, user_id):
    resp = requests.put(
        f"{config['base']}/admin/realms/{config['realm']}/users/{user_id}/execute-actions-email",
        headers=admin_headers,
        params={"client_id": config["client_id"], "redirect_uri": config["redirect_uri"]},
        json=["webauthn-register-passwordless"],
        timeout=TIMEOUT,
    )
    assert resp.status_code < 300, (
        f"execute-actions-email failed ({resp.status_code}): {resp.text[:300]}; "
        "the realm's SMTP settings are likely unconfigured or the required action "
        "isn't available"
    )


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    matches = sorted(CAPTURE_DIR.glob(f"*{marker}*.json"))
    for path in reversed(matches):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _wait_for_capture(email, since, attempts=15, delay=0.5):
    record = None
    for _ in range(attempts):
        record = _latest_capture_for(email, since)
        if record:
            return record
        time.sleep(delay)
    return record


def _extract_action_link(record):
    body_text = record.get("body_plain") or record.get("body_html") or ""
    match = re.search(r"(http://\S*action-token\?key=\S+)", body_text)
    assert match, f"no action-token link in the captured mail: {body_text[:200]}"
    return match.group(1).rstrip(".,)\r\n")


def _register_and_login(config, action_link, state, email):
    """Drives a real WebAuthn registration ceremony then a fresh login, using a
    headless browser with a CDP virtual authenticator (auto-approves both the
    'create' and 'get' ceremonies, standing in for a human touching a real
    passkey). Returns (final_redirect_url, saw_password_field).

    The task only requires no PASSWORD field, ever - it does not mandate a
    specific flow shape. A resident/discoverable credential (the oracle's
    approach) presents the WebAuthn control immediately with no username
    step; a non-resident credential needs a username first, which is an
    equally valid solution as long as that step never asks for a password.
    Handle both: try for the WebAuthn control directly, and if a username
    form appears instead, submit it and look again on the resulting page."""
    captured = {}
    saw_password = {"registration": False, "login": False}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
            "protocol": "ctap2", "transport": "internal", "hasResidentKey": True,
            "hasUserVerification": True, "isUserVerified": True,
            "automaticPresenceSimulation": True,
        }})

        def on_request(req):
            if req.url.startswith(config["redirect_uri"]):
                captured["final_url"] = req.url

        page.on("request", on_request)

        # Registration ceremony.
        page.goto(action_link, wait_until="networkidle", timeout=TIMEOUT * 1000)
        if 'type="password"' in page.content():
            saw_password["registration"] = True
        proceed = page.locator("a:has-text('Click here to proceed')")
        if proceed.count() > 0:
            proceed.first.click()
            page.wait_for_load_state("networkidle")
        if 'type="password"' in page.content():
            saw_password["registration"] = True
        register_btn = page.locator("#registerWebAuthn")
        assert register_btn.count() > 0, (
            f"no WebAuthn registration control found on {page.url}; "
            "the webauthn-register-passwordless required action may not be wired up"
        )
        register_btn.click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # Fresh authorization-code login, same context/authenticator.
        auth_url = (f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
                    + urllib.parse.urlencode({
                        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
                        "response_type": "code", "scope": "openid", "state": state,
                    }))
        page.goto(auth_url, wait_until="networkidle", timeout=TIMEOUT * 1000)
        if 'type="password"' in page.content():
            saw_password["login"] = True
        login_btn = page.locator("#authenticateWebAuthnButton")
        if login_btn.count() == 0:
            # No resident-key control yet - this may be a username-first
            # variant. Look for a username field; if there's one AND it's
            # not paired with a password field, submitting it is a valid
            # continuation of a passkey-only flow, not a fallback.
            username_input = page.locator("input[name='username']")
            assert username_input.count() > 0, (
                f"no WebAuthn login control and no username field found on {page.url}; "
                "the browser flow for acme-portal may not be bound to a passkey-only flow"
            )
            assert 'type="password"' not in page.content(), (
                f"a username step on {page.url} was paired with a password field; "
                "passkey-only login must never offer a password fallback"
            )
            username_input.fill(email)
            submit_btn = page.locator("button[type=submit], input[type=submit]")
            assert submit_btn.count() > 0, f"no submit control found on {page.url}"
            submit_btn.first.click()
            page.wait_for_load_state("networkidle")
            if 'type="password"' in page.content():
                saw_password["login"] = True
            login_btn = page.locator("#authenticateWebAuthnButton")
        assert login_btn.count() > 0, (
            f"no WebAuthn login control found on {page.url}; the browser flow "
            "for acme-portal may not be bound to a passkey-only flow"
        )
        login_btn.click()
        page.wait_for_timeout(2500)

        browser.close()

    return captured.get("final_url"), saw_password


@pytest.mark.parametrize("email", KNOWN_ACCOUNTS)
def test_registration_and_login_never_show_a_password_field(config, admin_headers, email):
    username = email.split("@")[0]
    user_id = _find_user_id(config, admin_headers, username)
    since = time.time()
    _send_required_action_email(config, admin_headers, user_id)

    record = _wait_for_capture(email, since)
    assert record is not None, (
        f"no mail was captured for {email} after requesting the "
        "webauthn-register-passwordless action; the realm's outgoing mail "
        "settings are likely unconfigured"
    )
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    action_link = _extract_action_link(record)

    state = f"verify-passkey-{username}"
    final_url, saw_password = _register_and_login(config, action_link, state, email)

    assert not saw_password["registration"], (
        f"{email} was shown a password field during passkey registration; "
        "passkey-only login must never offer a password fallback"
    )
    assert not saw_password["login"], (
        f"{email} was shown a password field during login; "
        "passkey-only login must never offer a password fallback"
    )
    assert final_url, (
        f"the passkey login for {email} never reached {config['redirect_uri']}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    assert "code" in query, f"no authorization code returned for {email}: {final_url[:250]}"
    assert query.get("state") == [state], (
        f"state was not preserved for {email}: sent {state!r}, got {query.get('state')!r}"
    )


def test_no_credential_has_no_password_fallback(config):
    """Before any passkey exists, a login attempt must still never fall back
    to a password form - there is no fallback at all, by design."""
    state = "verify-no-credential-yet"
    auth_url = (f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
                + urllib.parse.urlencode({
                    "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
                    "response_type": "code", "scope": "openid", "state": state,
                }))
    resp = requests.get(auth_url, timeout=TIMEOUT)
    assert resp.status_code == 200, f"authorization endpoint returned {resp.status_code}"
    assert 'type="password"' not in resp.text, (
        "the login page fell back to a password field with no registered passkey; "
        "passkey-only login must never offer a password fallback, with or "
        "without a registered credential"
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
