"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by driving real browser authorization-code logins against the
`acme-portal` client, headlessly. The verifier does NOT assume a particular flow alias or
authoring path - it discovers whatever browser flow is actually in effect for the client
(client-level override wins over the realm default, exactly as Keycloak resolves it) and
inspects that. Any correctly-shaped flow passes regardless of how it was built.

The behaviours asserted here were each confirmed against a live Keycloak before being
written, not inferred from documentation:

  * A registered address reaches Keycloak's `login-otp-form` page with NO password field,
    receives a real email containing a numeric code, and that code completes the login.
  * An UNREGISTERED address reaches the identical page and receives NO mail. This is the
    check that distinguishes a correct solution from the intuitive-but-leaky one: with
    stock `auth-username-form` as the identifier step, an unknown address is rejected with
    "Invalid username or email." before `ext-email-otp` ever runs, leaking which addresses
    have accounts. Only an identifier-only step reaches ext-email-otp's own
    anti-enumeration-safe handling.
"""

import http.cookiejar
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
CAPTURE_DIR = "/var/mail-capture"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

KNOWN_EMAIL = "priya@acme-internal.example"
SECOND_KNOWN_EMAIL = "morgan@acme-internal.example"
UNKNOWN_EMAIL = "verify-ghost@acme-internal.example"


def _read_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
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


def _admin_get(config, token, path):
    req = urllib.request.Request(f"{config['base']}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


@pytest.fixture(scope="session")
def admin_token(config):
    data = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": config["admin_username"],
            "password": config["admin_password"],
        }
    ).encode()
    req = urllib.request.Request(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data=data,
        method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())["access_token"]


# --- session plumbing ------------------------------------------------------
#
# AUTH_SESSION_ID / KC_RESTART are `Secure; SameSite=None`. A browser sends them over
# http://localhost anyway (loopback is a secure context); http.cookiejar will not unless
# told to, and the first POST then 400s on the CSRF/session check.


class _AllowSecureOverHttp(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _new_session():
    jar = http.cookiejar.CookieJar(policy=_AllowSecureOverHttp(rfc2965=False))
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())


def _get(opener, url):
    try:
        r = opener.open(urllib.request.Request(url), timeout=TIMEOUT)
        return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _post(opener, url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = opener.open(req, timeout=TIMEOUT)
        return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def _page_id(html):
    m = re.search(r'data-page-id="([^"]+)"', html or "")
    return m.group(1) if m else None


def _form_action(html, what):
    m = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert m, f"no form to submit on the {what} page"
    return m.group(1).replace("&amp;", "&")


def _authorization_url(config, state):
    params = urllib.parse.urlencode(
        {
            "client_id": config["client_id"],
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": config["redirect_uri"],
            "state": state,
        }
    )
    return f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?{params}"


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    directory = pathlib.Path(CAPTURE_DIR)
    if not directory.exists():
        return None
    for path in sorted(directory.glob(f"*{marker}*"))[::-1]:
        stamp = re.match(r"(\d+)-", path.name)
        if stamp and int(stamp.group(1)) >= int(since * 1000):
            return path
    return None


def _follow_to_redirect_uri(opener, config, location, limit=8):
    for _ in range(limit):
        if not location or location.startswith(config["redirect_uri"]):
            return location
        target = location if location.startswith("http") else f"{config['base']}{location}"
        _, _, headers = _get(opener, target)
        location = headers.get("Location", "")
    return location


def _submit_identifier(config, email, state):
    opener = _new_session()
    status, html, _ = _get(opener, _authorization_url(config, state))
    assert status == 200, f"authorization endpoint returned {status}: {html[:200]}"
    status, html, headers = _post(opener, _form_action(html, "identifier"), {"username": email})
    if status in (302, 303):
        location = headers.get("Location", "")
        # A redirect straight to the app means the login COMPLETED at this step - do not
        # follow it (nothing listens on the callback, which would surface as an opaque
        # "Connection refused"). Report it so callers can assert on it explicitly.
        if location.startswith(config["redirect_uri"]):
            return opener, html, "COMPLETED_WITHOUT_FURTHER_STEPS"
        _, html, _ = _get(opener, location)
    return opener, html, _page_id(html)


# --- structural check ------------------------------------------------------


def _effective_browser_flow(config, token):
    """The browser flow actually in effect for the app client: a client-level override
    (which stores a flow ID) wins over the realm default (which stores an alias)."""
    clients = _admin_get(
        config, token,
        f"/admin/realms/{config['realm']}/clients?clientId={urllib.parse.quote(config['client_id'])}",
    )
    assert clients, f"the seeded client {config['client_id']!r} no longer exists"
    override_id = (clients[0].get("authenticationFlowBindingOverrides") or {}).get("browser")

    flows = _admin_get(config, token, f"/admin/realms/{config['realm']}/authentication/flows")
    if override_id:
        alias = {f.get("id"): f.get("alias") for f in flows}.get(override_id)
        assert alias, f"client override points at flow id {override_id!r} which does not exist"
        return alias
    realm_rep = _admin_get(config, token, f"/admin/realms/{config['realm']}")
    return realm_rep.get("browserFlow")


@pytest.fixture(scope="session")
def bound_flow_executions(config, admin_token):
    alias = _effective_browser_flow(config, admin_token)
    assert alias, (
        f"no browser flow is in effect for {config['client_id']} - neither a client-level "
        "override nor the realm's browserFlow is set"
    )
    executions = _admin_get(
        config, admin_token,
        f"/admin/realms/{config['realm']}/authentication/flows/{urllib.parse.quote(alias)}/executions",
    )
    return alias, executions


def test_flow_uses_email_otp_after_an_identifier_step(config, bound_flow_executions):
    alias, executions = bound_flow_executions
    by_provider = {e.get("providerId"): e for e in executions if e.get("providerId")}

    assert "ext-email-otp" in by_provider, (
        f"the browser flow in effect ({alias!r}) has no ext-email-otp execution, so no emailed "
        f"code is ever issued. Found: {sorted(p for p in by_provider if p)}"
    )
    otp = by_provider["ext-email-otp"]
    assert otp.get("requirement") == "REQUIRED", (
        f"ext-email-otp is {otp.get('requirement')!r}, not REQUIRED - an ALTERNATIVE or DISABLED "
        "code step can be bypassed entirely"
    )

    # Some identifier-collecting step must run before it, at the same nesting level.
    earlier_siblings = [
        e for e in executions
        if e.get("providerId")
        and e.get("level") == otp.get("level")
        and e.get("index", 0) < otp.get("index", 0)
    ]
    assert earlier_siblings, (
        "no execution runs before ext-email-otp in its sub-flow. It reads the attempted "
        "username off the auth session rather than collecting an address itself, so with no "
        "identifier step ahead of it there is nothing to mail."
    )


def test_no_password_is_ever_requested(config):
    """This must be passwordless: no password input at any point for a registered address."""
    _, html, pid = _submit_identifier(config, KNOWN_EMAIL, "verify-nopassword")
    assert pid == "login-otp-form", (
        f"submitting a registered address should reach the emailed-code form; got page_id={pid!r}"
    )
    assert not re.search(r'type="password"', html or "", re.I), (
        "a password field appeared in the login flow - the requirement is that staff are never "
        "asked for a password"
    )


def test_registered_address_gets_a_code_that_completes_login(config):
    since = time.time()
    state = "verify-known"
    opener, html, pid = _submit_identifier(config, KNOWN_EMAIL, state)
    assert pid == "login-otp-form", f"expected the code form, got page_id={pid!r}"

    record = None
    for _ in range(12):
        record = _latest_capture_for(KNOWN_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    assert record is not None, (
        f"no mail was captured for {KNOWN_EMAIL} - the realm's SMTP settings are probably "
        "unconfigured or wrong (the authenticator swallows its own send failure)"
    )

    # The capture server writes JSON, not .eml, and its `received_at` is a float whose
    # fractional part is six digits - so a naive \b\d{6}\b over the WHOLE file returns the
    # timestamp instead of the code, submits a wrong OTP, and fails with a misleading
    # "the emailed code did not complete the login". Parse the JSON and read only the body.
    raw = record.read_text()
    try:
        record_json = json.loads(raw)
        body = record_json.get("body_plain") or record_json.get("body_html") or ""
    except json.JSONDecodeError:
        body = re.sub(r"Message-ID:.*", "", raw)
    code_match = re.search(r"Code:\s*(\d{4,10})", body) or re.search(r"\b(\d{6})\b", body)
    assert code_match, f"no numeric one-time code found in the captured mail body: {body[:300]}"
    code = code_match.group(1)

    status, html, headers = _post(opener, _form_action(html, "code"), {"otp": code})
    final = _follow_to_redirect_uri(opener, config, headers.get("Location", ""))
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "known-address-login.txt").write_text(f"final={final}\n")
    assert final.startswith(config["redirect_uri"]), (
        f"the emailed code did not complete the login; ended at {final[:250]!r}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned: {final[:250]}"
    assert query.get("state") == [state], f"state was not preserved: {query.get('state')}"


@pytest.fixture(scope="session")
def flow_is_live(config):
    """Guard: on an unconfigured realm "no mail sent" is trivially true, so confirm the
    registered path actually reaches the code form before asserting the negative."""
    _, _, pid = _submit_identifier(config, KNOWN_EMAIL, "verify-liveness")
    assert pid == "login-otp-form", (
        f"the emailed-code step is not reachable for a registered address (page_id={pid!r}), "
        "so the negative check below would pass vacuously"
    )
    return True


def test_unregistered_address_is_indistinguishable_and_gets_no_mail(config, flow_is_live):
    since = time.time()
    _, html, pid = _submit_identifier(config, UNKNOWN_EMAIL, "verify-unknown")
    assert pid == "login-otp-form", (
        f"an unregistered address reached page_id={pid!r} instead of the same code form a "
        "registered address gets. The login must not reveal which addresses have accounts - "
        "stock auth-username-form rejects unknown addresses up front ('Invalid username or "
        "email') and leaks exactly this; an identifier-only step does not."
    )
    time.sleep(1.5)
    assert _latest_capture_for(UNKNOWN_EMAIL, since) is None, (
        f"mail was sent for {UNKNOWN_EMAIL}, which has no account"
    )


def test_no_account_created_for_the_unregistered_address(config, admin_token):
    users = _admin_get(
        config, admin_token,
        f"/admin/realms/{config['realm']}/users?search={urllib.parse.quote(UNKNOWN_EMAIL)}",
    )
    assert not users, (
        f"an account was created for {UNKNOWN_EMAIL} - ext-email-otp's "
        "ext-magic-create-nonexistent-user must not be enabled"
    )


def test_seeded_users_still_exist_and_are_enabled(config, admin_token):
    for email in (KNOWN_EMAIL, SECOND_KNOWN_EMAIL):
        users = _admin_get(
            config, admin_token,
            f"/admin/realms/{config['realm']}/users?email={urllib.parse.quote(email)}&exact=true",
        )
        assert users, f"the seeded account {email} no longer exists"
        assert users[0].get("enabled") is True, f"the seeded account {email} was disabled"


def test_only_the_expected_realms_exist(config, admin_token):
    realms = _admin_get(config, admin_token, "/admin/realms?briefRepresentation=true")
    names = {r["realm"] for r in realms}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
    )
