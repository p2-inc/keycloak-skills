"""Pytest-based verifier. Run by BenchFlow after the agent completes.

This task asks for ONE login flow offering TWO passwordless methods, so the
verifier drives BOTH for real rather than trusting realm configuration:

  * the magic-link half over plain HTTP - submit an address on the login page,
    read the captured mail, follow the link, and require a real authorization
    code back at the client's redirect_uri; and

  * the passkey half through a headless browser with a CDP virtual
    authenticator - register a credential, then log in with it. The crypto
    exchange cannot be faked with an HTTP client the way a magic link's plain
    redirect-following can.

Both are driven against the SAME client, because "one flow, two methods" is
the actual requirement: a solution that wires up only one of them, or wires
them into two different clients, is not what was asked for.

Deliberately shape-agnostic. Nothing here asserts a flow alias, a sub-flow
name, an execution priority, or which binding surface (realm-wide vs. the
client's authenticationFlowBindingOverrides) was used. The atomic-flows
extension hash-prefixes aliases it creates, and binding realm-wide is an
equally valid reading of the request - so every assertion is about observable
login behaviour instead.
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

# Seeded in environment/acme-realm.json - both start with zero credentials, so
# neither can log in at all until one of the two methods is working.
MAGIC_LINK_ACCOUNT = "priya@acme.example"
PASSKEY_ACCOUNT = "marcus@acme.example"
UNKNOWN_EMAIL = "nobody@acme.example"


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
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _submit_email(config, email, state):
    session = requests.Session()
    page = session.get(_authorization_url(config, state), timeout=TIMEOUT)
    assert page.status_code == 200, (
        f"the authorization endpoint returned {page.status_code}: {page.text[:200]}")
    _relax_cookies(session)
    resp = session.post(_form_action(page.text, "login"), data={"username": email},
                        timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    return session, resp


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


def _body_text(record):
    return record.get("body_plain") or record.get("body_html") or ""


def _extract_link(record, pattern=r"(http://\S+)"):
    match = re.search(pattern, _body_text(record))
    assert match, f"no link in the captured mail: {_body_text(record)[:200]}"
    return match.group(1).rstrip(".,)>\r\n").replace("&amp;", "&")


def _follow_to_redirect_uri(session, location, redirect_uri, hops=10):
    for _ in range(hops):
        if not location:
            return None
        if location.startswith(redirect_uri):
            return location
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        if resp.status_code not in (301, 302, 303, 307, 308):
            return resp.url if resp.url.startswith(redirect_uri) else None
        location = resp.headers.get("Location", "")
    return None


def _user_exists(config, admin_headers, email):
    resp = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                        headers=admin_headers, params={"email": email, "exact": "true"},
                        timeout=TIMEOUT)
    assert resp.status_code == 200, f"user search failed: {resp.text[:300]}"
    return bool(resp.json())


def _find_user_id(config, admin_headers, username):
    resp = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                        headers=admin_headers, params={"username": username, "exact": "true"},
                        timeout=TIMEOUT)
    assert resp.status_code == 200, f"user search failed: {resp.text[:300]}"
    matches = resp.json()
    assert matches, f"user {username} not found"
    return matches[0]["id"]


# ---------------------------------------------------------------- no password

def test_the_login_page_never_offers_a_password(config):
    """The whole point of the brand: no password anywhere, before any
    credential of either kind exists."""
    resp = requests.get(_authorization_url(config, "verify-no-password"), timeout=TIMEOUT)
    assert resp.status_code == 200, f"authorization endpoint returned {resp.status_code}"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "login-page.html").write_text(resp.text[:20000])
    assert 'type="password"' not in resp.text, (
        "the login page shows a password field; a zero-password flow must never "
        "offer one - a flow copied from the stock `browser` flow keeps "
        "auth-username-password-form unless it is explicitly removed")


# --------------------------------------------------------------- magic link

def test_magic_link_login_completes(config):
    """Half one: an emailed link must complete a real authorization-code login."""
    state = "verify-magic-link"
    since = time.time()
    session, resp = _submit_email(config, MAGIC_LINK_ACCOUNT, state)
    assert resp.status_code in (200, 302), (
        f"submitting {MAGIC_LINK_ACCOUNT} returned {resp.status_code}")

    record = _wait_for_capture(MAGIC_LINK_ACCOUNT, since)
    assert record is not None, (
        f"no mail was captured for {MAGIC_LINK_ACCOUNT} after submitting it on the "
        "login page. Either the magic-link method is not wired into the bound flow, "
        "or the realm's outgoing mail settings are unconfigured - the page shows "
        "'check your email' either way, by design")

    link = _extract_link(record, r"(http://\S*login-actions\S+)")
    opened = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    final = _follow_to_redirect_uri(session, opened.headers.get("Location", ""),
                                   config["redirect_uri"])
    assert final and final.startswith(config["redirect_uri"]), (
        f"opening the emailed link for {MAGIC_LINK_ACCOUNT} never reached "
        f"{config['redirect_uri']}; ended at {final!r}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned: {final[:250]}"
    assert query.get("state") == [state], (
        f"state was not preserved: sent {state!r}, got {query.get('state')!r}")


def test_no_mail_or_account_is_created_for_an_unregistered_address(config, admin_headers):
    """ext-magic-create-nonexistent-user defaults to TRUE. In a zero-password
    flow that default turns the login page into open self-registration, since
    the emailed link is the entire authentication boundary."""
    since = time.time()
    _submit_email(config, UNKNOWN_EMAIL, "verify-unknown-effects")
    time.sleep(2)

    assert _latest_capture_for(UNKNOWN_EMAIL, since) is None, (
        f"mail was sent to {UNKNOWN_EMAIL}, which belongs to no existing account; "
        "ext-magic-create-nonexistent-user must be turned off")
    assert not _user_exists(config, admin_headers, UNKNOWN_EMAIL), (
        f"an account was created for {UNKNOWN_EMAIL} after it was typed on the login "
        "page; in a zero-password flow that makes the login page open registration")


# ------------------------------------------------------------------- passkey


def _reach_passkey_control(page, artifact_dir=None, trail=None):
    """Get from the rendered login page to the WebAuthn control.

    ext-magic-form is the lower-priority ALTERNATIVE, so Keycloak renders its
    form first and puts the passkey behind "Try another way". That control is
    NOT a button: Keycloak 26 renders

        <form id="kc-select-try-another-way-form" method="post">
          <input type="hidden" name="tryAnotherWay" value="on"/>
          <a id="try-another-way" href="javascript:...requestSubmit()">

    so the visible thing to click is the anchor - matching name='tryAnotherWay'
    finds only the hidden input and hangs. Verified against Keycloak 26.0.7.
    """
    def note():
        if trail is not None:
            trail.append(page.url)

    if page.locator("#authenticateWebAuthnButton").count():
        return

    another = page.locator("#try-another-way")
    if not another.count():
        another = page.locator("a:has-text('Try Another Way'), a:has-text('Try another way')")
    if not another.count():
        # Last resort: submit the form directly if it exists at all.
        if page.locator("#kc-select-try-another-way-form").count():
            page.evaluate("document.forms['kc-select-try-another-way-form'].requestSubmit()")
        else:
            raise RuntimeError(
                f"on {page.url} the login page offered neither the passkey control nor a "
                "'Try another way' control, so the passkey method is unreachable")
    else:
        another.first.click()
    page.wait_for_load_state("networkidle")
    note()

    if page.locator("#authenticateWebAuthnButton").count():
        return

    # Credential-selection page. Keycloak 26 renders each choice as a
    # <li> holding a hidden-input form plus a clickable
    # <div class="... select-auth-box-parent" onclick="...requestSubmit()">
    # wrapping an <h2> label - so there is no button or anchor to click, and
    # button/a selectors find nothing. Verified against Keycloak 26.0.7, where
    # the passkey entry is labelled "Passkey".
    for label in ("Passkey", "Security Key", "WebAuthn"):
        option = page.locator(f"div.select-auth-box-parent:has-text('{label}')")
        if not option.count():
            option = page.locator(f"li:has-text('{label}') div.select-auth-box-parent")
        if option.count():
            option.first.click()
            page.wait_for_load_state("networkidle")
            note()
            break

    if not page.locator("#authenticateWebAuthnButton").count() and artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "select-credential.html").write_text(page.content()[:20000])


def _register_passkey_then_login(config, action_link, state):
    """Registers a credential via a real ceremony, then logs in with it.

    Shape-agnostic about how the passkey is reached on the login page. With
    ext-magic-form as the lower-priority alternative the magic-link form
    renders first and the passkey sits behind Keycloak's "Try another way"
    control; with the priorities the other way round the passkey control is
    immediate. Either is a valid reading of "one flow, two methods", so try
    the direct control first and fall back to the selection UI.
    """
    captured = {}
    saw_password = {"registration": False, "login": False}
    trail = []

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

        def on_request(req):
            if req.url.startswith(config["redirect_uri"]):
                captured["final_url"] = req.url

        page.on("request", on_request)

        # --- registration ceremony
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
            f"no WebAuthn registration control on {page.url}; the "
            "webauthn-register-passwordless required action may not be available")
        register_btn.click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # --- fresh login with that credential
        page.goto(_authorization_url(config, state), wait_until="networkidle",
                  timeout=TIMEOUT * 1000)
        trail.append(page.url)
        if 'type="password"' in page.content():
            saw_password["login"] = True

        _reach_passkey_control(page, ARTIFACT_DIR, trail)
        if 'type="password"' in page.content():
            saw_password["login"] = True

        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "passkey-login-trail.txt").write_text("\n".join(trail))
        (ARTIFACT_DIR / "passkey-login-final.html").write_text(page.content()[:20000])

        login_btn = page.locator("#authenticateWebAuthnButton")
        assert login_btn.count() > 0, (
            f"the passkey login control never became reachable (pages visited: {trail})")
        login_btn.click()
        page.wait_for_timeout(2500)
        browser.close()

    return captured.get("final_url"), saw_password


def test_passkey_login_completes(config, admin_headers):
    """Half two: a registered passkey must complete a real authorization-code
    login through the same client, with no password at any step."""
    username = PASSKEY_ACCOUNT.split("@")[0]
    user_id = _find_user_id(config, admin_headers, username)
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

    record = _wait_for_capture(PASSKEY_ACCOUNT, since)
    assert record is not None, (
        f"no mail captured for {PASSKEY_ACCOUNT} after requesting the "
        "webauthn-register-passwordless action; realm SMTP is likely unconfigured")
    action_link = _extract_link(record, r"(http://\S*action-token\?key=\S+)")

    state = "verify-passkey"
    final_url, saw_password = _register_passkey_then_login(config, action_link, state)

    assert not saw_password["registration"], (
        "a password field appeared during passkey registration")
    assert not saw_password["login"], (
        "a password field appeared during passkey login")
    assert final_url, f"the passkey login never reached {config['redirect_uri']}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    assert "code" in query, f"no authorization code returned: {final_url[:250]}"
    assert query.get("state") == [state], (
        f"state was not preserved: sent {state!r}, got {query.get('state')!r}")


# ------------------------------------------------------------- no collateral

def test_existing_accounts_still_exist_and_are_enabled(config, admin_headers):
    resp = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                        headers=admin_headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"user listing failed: {resp.text[:300]}"
    by_username = {u["username"]: u for u in resp.json()}
    for username in ("priya", "marcus"):
        assert username in by_username, f"the {username} account is gone"
        assert by_username[username].get("enabled") is True, f"the {username} account is disabled"


def test_no_password_credential_was_created(config, admin_headers):
    """A "0 password required" realm must not have quietly grown passwords."""
    for username in ("priya", "marcus"):
        user_id = _find_user_id(config, admin_headers, username)
        resp = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}/users/{user_id}/credentials",
            headers=admin_headers, timeout=TIMEOUT)
        assert resp.status_code == 200, f"credential listing failed: {resp.text[:300]}"
        kinds = {c.get("type") for c in resp.json()}
        assert "password" not in kinds, (
            f"{username} has a password credential ({sorted(kinds)}); this flow is "
            "supposed to remove passwords, not add them")


def test_only_the_acme_realm_was_added(config, admin_headers):
    resp = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                        params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}")
