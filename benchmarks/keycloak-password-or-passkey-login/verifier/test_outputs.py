# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

This task asks for ONE login flow offering TWO first-factor methods - the
existing username/password, or a passkey - either of which logs a user in on
its own. The verifier drives every path for real rather than trusting realm
configuration:

  * the password path over plain HTTP - POST the login form, require a real
    authorization code back at the client's redirect_uri - for a user who has
    NO passkey. This is the decisive check: if the passkey step were REQUIRED
    after the password (2FA) instead of an ALTERNATIVE to it, this user would be
    stopped after a correct password and never reach the callback;

  * a wrong password, which must still be rejected;

  * the passkey path through a headless browser with a CDP virtual
    authenticator - register a credential via an execute-actions email, then
    log in with it, never filling in the password form; and

  * the password path again for the user who now HAS a passkey, which must
    still work on its own (a conditional "passkey for those who have one"
    second factor fails here).

Deliberately shape-agnostic. Nothing here asserts a flow alias, a sub-flow
name, an execution priority, or which binding surface (realm-wide vs. the
client's authenticationFlowBindingOverrides) was used. Every assertion is
about observable login behaviour. The tests share state through Keycloak and
run in file order: the passkey is enrolled before the last password check.
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
STAFF_CREDS_PATH = "/root/staff_credentials.txt"
CAPTURE_DIR = pathlib.Path("/var/mail-capture")
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

# Seeded in environment/acme-realm.json: both sign in with a password today and
# neither has a passkey. priya never gets one; marcus is enrolled by the test.
PASSWORD_ONLY_USER = "priya"
PASSKEY_USER = "marcus"
PASSKEY_EMAIL = "marcus@acme.example"


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
    staff = _read_settings(STAFF_CREDS_PATH)
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
        "passwords": {"priya": staff["priya_password"], "marcus": staff["marcus_password"]},
    }


@pytest.fixture(scope="session")
def admin_headers(config):
    resp = requests.post(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": config["admin_username"], "password": config["admin_password"]},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"admin login failed ({resp.status_code}): {resp.text[:300]}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _relax_cookies(session):
    """Keycloak marks AUTH_SESSION_ID / KC_RESTART Secure; SameSite=None.
    Browsers send them over http://localhost anyway (loopback is a secure
    context); requests will not, and every form POST then 400s with
    "Cookie not found."."""
    for cookie in session.cookies:
        cookie.secure = False


def _authorization_url(config, state):
    return (f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
            + urllib.parse.urlencode({
                "client_id": config["client_id"], "response_type": "code",
                "scope": "openid email", "redirect_uri": config["redirect_uri"],
                "state": state, "nonce": f"nonce-{state}"}))


def _form_action(html, what):
    match = (re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', html or "", re.I)
             or re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I))
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _password_login(config, username, password, state):
    """POST the login form. Returns (callback_url_or_None, last_html)."""
    session = requests.Session()
    page = session.get(_authorization_url(config, state), timeout=TIMEOUT)
    assert page.status_code == 200, (
        f"the authorization endpoint returned {page.status_code}: {page.text[:200]}")
    _relax_cookies(session)
    assert 'type="password"' in page.text, (
        "the login page shows no password field; this task KEEPS username/password as one "
        "of the two methods")
    resp = session.post(_form_action(page.text, "login"),
                        data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    for _ in range(10):
        if resp.status_code not in (301, 302, 303, 307, 308):
            return None, resp.text
        location = resp.headers.get("Location", "")
        if location.startswith(config["redirect_uri"]):
            return location, ""
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
    return None, resp.text


def _assert_code(final, state, what, config):
    assert final and final.startswith(config["redirect_uri"]), (
        f"{what} never reached {config['redirect_uri']}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"{what}: no authorization code returned: {final[:250]}"
    assert query.get("state") == [state], (
        f"{what}: state was not preserved: sent {state!r}, got {query.get('state')!r}")


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    for path in reversed(sorted(CAPTURE_DIR.glob(f"*{marker}*.json"))):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _wait_for_capture(email, since, attempts=20, delay=0.5):
    for _ in range(attempts):
        record = _latest_capture_for(email, since)
        if record:
            return record
        time.sleep(delay)
    return None


def _extract_link(record, pattern):
    body = record.get("body_plain") or record.get("body_html") or ""
    match = re.search(pattern, body)
    assert match, f"no link in the captured mail: {body[:200]}"
    return match.group(1).rstrip(".,)>\r\n").replace("&amp;", "&")


def _find_user_id(config, admin_headers, username):
    resp = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                        headers=admin_headers, params={"username": username, "exact": "true"},
                        timeout=TIMEOUT)
    assert resp.status_code == 200, f"user search failed: {resp.text[:300]}"
    matches = resp.json()
    assert matches, f"user {username} not found"
    return matches[0]["id"]


def _credential_types(config, admin_headers, username):
    user_id = _find_user_id(config, admin_headers, username)
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users/{user_id}/credentials",
        headers=admin_headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"credential listing failed: {resp.text[:300]}"
    return {c.get("type") for c in resp.json()}


# ------------------------------------------------------------- the login page

def test_the_login_page_offers_the_password_and_another_way(config):
    """Both methods have to be reachable from the one page: the password form,
    and a control leading to the passkey."""
    resp = requests.get(_authorization_url(config, "verify-login-page"), timeout=TIMEOUT)
    assert resp.status_code == 200, f"authorization endpoint returned {resp.status_code}"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "login-page.html").write_text(resp.text[:20000])
    assert 'type="password"' in resp.text, (
        "the login page shows no password field; username/password must remain one of the "
        "two methods - a zero-password recipe applied here removes it")
    assert ("try-another-way" in resp.text or "authenticateWebAuthnButton" in resp.text), (
        "the login page offers no way to reach the passkey (no 'Try another way' control and "
        "no passkey button); the passkey authenticator is missing from the bound flow, or is "
        "not an ALTERNATIVE beside the password form")


# --------------------------------------------------------------- password path

def test_password_alone_logs_in_a_user_without_a_passkey(config, admin_headers):
    """The decisive check. priya has a password and no passkey: a correct password
    must complete the login by itself. If the passkey step were REQUIRED after the
    password - 2FA instead of an alternative - she would be stopped here."""
    assert not ({"webauthn-passwordless", "webauthn"} & _credential_types(
        config, admin_headers, PASSWORD_ONLY_USER)), (
        f"{PASSWORD_ONLY_USER} has a passkey; this check needs a password-only user")
    state = "verify-password-only"
    final, html = _password_login(config, PASSWORD_ONLY_USER,
                                  config["passwords"][PASSWORD_ONLY_USER], state)
    if not final:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "password-only-after-submit.html").write_text(html[:20000])
    assert final, (
        f"a correct password for {PASSWORD_ONLY_USER} (who has no passkey) did not complete "
        "the login. The passkey is probably REQUIRED after the password - making this "
        "password-THEN-passkey 2FA - instead of an ALTERNATIVE to it")
    _assert_code(final, state, f"{PASSWORD_ONLY_USER}'s password login", config)


def test_a_wrong_password_is_rejected(config):
    final, html = _password_login(config, PASSWORD_ONLY_USER, "definitely-not-her-password",
                                  "verify-wrong-password")
    assert final is None, "a wrong password reached the client callback"
    assert 'type="password"' in html, (
        "after a wrong password the login form was not shown again")


# ---------------------------------------------------------------- passkey path


def _reach_passkey_control(page, trail):
    """Get from the rendered login page to the WebAuthn control: directly, or via
    Keycloak's "Try another way" anchor and the credential-selection page.
    Shape-agnostic: either order of the two alternatives is a valid solution.
    Markup verified against Keycloak 26.0.7 (see keycloak-zero-password-login)."""
    if page.locator("#authenticateWebAuthnButton").count():
        return
    another = page.locator("#try-another-way")
    if not another.count():
        another = page.locator("a:has-text('Try Another Way'), a:has-text('Try another way')")
    if another.count():
        another.first.click()
    elif page.locator("#kc-select-try-another-way-form").count():
        page.evaluate("document.forms['kc-select-try-another-way-form'].requestSubmit()")
    else:
        return
    page.wait_for_load_state("networkidle")
    trail.append(page.url)
    if page.locator("#authenticateWebAuthnButton").count():
        return
    for label in ("Passkey", "Security Key", "WebAuthn"):
        option = page.locator(f"div.select-auth-box-parent:has-text('{label}')")
        if not option.count():
            option = page.locator(f"li:has-text('{label}') div.select-auth-box-parent")
        if option.count():
            option.first.click()
            page.wait_for_load_state("networkidle")
            trail.append(page.url)
            return


def test_passkey_logs_in_without_the_password(config, admin_headers):
    """Enrol a passkey for marcus without touching his password (an execute-actions
    email), then log in with it through a real browser - never filling in the
    password form - and require a code back at the callback."""
    user_id = _find_user_id(config, admin_headers, PASSKEY_USER)
    since = time.time()
    resp = requests.put(
        f"{config['base']}/admin/realms/{config['realm']}/users/{user_id}/execute-actions-email",
        headers=admin_headers,
        params={"client_id": config["client_id"], "redirect_uri": config["redirect_uri"]},
        json=["webauthn-register-passwordless"], timeout=TIMEOUT)
    assert resp.status_code < 300, (
        f"execute-actions-email failed ({resp.status_code}): {resp.text[:300]}; the realm's "
        "SMTP settings are likely unconfigured, or webauthn-register-passwordless is "
        "unavailable because the WebAuthn passwordless policy was never set")
    record = _wait_for_capture(PASSKEY_EMAIL, since)
    assert record is not None, (
        f"no mail captured for {PASSKEY_EMAIL} after requesting webauthn-register-passwordless; "
        "realm SMTP is likely unconfigured")
    action_link = _extract_link(record, r"(http://\S*action-token\?key=\S+)")

    state = "verify-passkey"
    captured, trail = {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
            "protocol": "ctap2", "transport": "internal", "hasResidentKey": True,
            "hasUserVerification": True, "isUserVerified": True,
            "automaticPresenceSimulation": True}})
        page.on("request", lambda req: req.url.startswith(config["redirect_uri"])
                and captured.__setitem__("final_url", req.url))

        page.goto(action_link, wait_until="networkidle", timeout=TIMEOUT * 1000)
        proceed = page.locator("a:has-text('Click here to proceed')")
        if proceed.count():
            proceed.first.click()
            page.wait_for_load_state("networkidle")
        register_btn = page.locator("#registerWebAuthn")
        assert register_btn.count(), (
            f"no WebAuthn registration control on {page.url}; the "
            "webauthn-register-passwordless required action may not be available")
        register_btn.click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # A fresh login, with no session left from the registration: the passkey
        # ceremony, not an SSO cookie, has to be what completes it.
        context.clear_cookies()
        captured.pop("final_url", None)
        page.goto(_authorization_url(config, state), wait_until="networkidle",
                  timeout=TIMEOUT * 1000)
        trail.append(page.url)
        _reach_passkey_control(page, trail)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "passkey-login-trail.txt").write_text("\n".join(trail))
        (ARTIFACT_DIR / "passkey-login-final.html").write_text(page.content()[:20000])
        login_btn = page.locator("#authenticateWebAuthnButton")
        assert login_btn.count(), (
            f"the passkey login control never became reachable from the login page "
            f"(pages visited: {trail})")
        login_btn.click()
        page.wait_for_timeout(2500)
        browser.close()

    _assert_code(captured.get("final_url"), state, f"{PASSKEY_USER}'s passkey login", config)


def test_password_alone_still_logs_in_a_user_who_has_a_passkey(config, admin_headers):
    """After enrolling a passkey, marcus's password must still log him in on its
    own. A conditional sub-flow that demands the passkey from users who have one
    (passkey as second factor) fails here."""
    assert {"webauthn-passwordless"} & _credential_types(config, admin_headers, PASSKEY_USER), (
        f"{PASSKEY_USER} has no passkey credential; the passkey test above must have failed")
    state = "verify-password-with-passkey"
    final, html = _password_login(config, PASSKEY_USER, config["passwords"][PASSKEY_USER], state)
    if not final:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "password-with-passkey-after-submit.html").write_text(html[:20000])
    assert final, (
        f"{PASSKEY_USER}'s correct password did not complete the login once he had a passkey; "
        "the passkey is being demanded as a second factor instead of offered as an alternative")
    _assert_code(final, state, f"{PASSKEY_USER}'s password login", config)


# ------------------------------------------------------------- no collateral

def test_existing_accounts_still_exist_are_enabled_and_keep_their_password(config, admin_headers):
    resp = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                        headers=admin_headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"user listing failed: {resp.text[:300]}"
    by_username = {u["username"]: u for u in resp.json()}
    for username in (PASSWORD_ONLY_USER, PASSKEY_USER):
        assert username in by_username, f"the {username} account is gone"
        assert by_username[username].get("enabled") is True, f"the {username} account is disabled"
        assert "password" in _credential_types(config, admin_headers, username), (
            f"{username}'s password credential was removed; this task adds a passkey option, "
            "it does not take passwords away")


def test_only_the_acme_realm_was_added(config, admin_headers):
    resp = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                        params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}")
