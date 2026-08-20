"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by driving real browser authorization-code logins against the
`acme-portal` client, headlessly. The verifier does NOT assume a particular flow alias or
authoring path - it discovers whatever browser flow is actually in effect for the client
(client-level override wins over the realm default, exactly as Keycloak resolves it).

The decisive check is the WRONG-password case. A solution that merely puts an emailed code
in front of a login will pass a happy-path test while leaving the password irrelevant -
anyone knowing the address would be emailed a code. Only a flow where the password step
runs first and gates the send satisfies the requirement, and the only way to prove that is
to confirm a wrong password produces NO mail at all. Verified against a live Keycloak
before being written here.
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

USERNAME = "priya"
USER_EMAIL = "priya@acme-internal.example"
CORRECT_PASSWORD = "Priya!Pass1"
WRONG_PASSWORD = "definitely-not-the-password"
SECOND_USERNAME = "morgan"
SECOND_EMAIL = "morgan@acme-internal.example"
UNKNOWN_USERNAME = "verify-ghost"


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


def _submit_credentials(config, username, password, state):
    """Submits Keycloak's combined username+password form."""
    opener = _new_session()
    status, html, _ = _get(opener, _authorization_url(config, state))
    assert status == 200, f"authorization endpoint returned {status}: {html[:200]}"
    status, html, headers = _post(
        opener, _form_action(html, "login"), {"username": username, "password": password}
    )
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


def test_flow_gates_email_otp_behind_a_password_step(config, bound_flow_executions):
    alias, executions = bound_flow_executions
    by_provider = {e.get("providerId"): e for e in executions if e.get("providerId")}

    assert "ext-email-otp" in by_provider, (
        f"the browser flow in effect ({alias!r}) has no ext-email-otp execution, so no emailed "
        f"code is ever issued. Found: {sorted(p for p in by_provider if p)}"
    )
    otp = by_provider["ext-email-otp"]
    assert otp.get("requirement") == "REQUIRED", (
        f"ext-email-otp is {otp.get('requirement')!r}, not REQUIRED - a second factor that can "
        "be skipped is not a second factor"
    )

    password_steps = [
        e for e in executions
        if e.get("providerId") in ("auth-username-password-form", "auth-password-form")
        and e.get("requirement") == "REQUIRED"
    ]
    assert password_steps, (
        "no REQUIRED password step exists in the bound flow. The password must remain required - "
        f"found executions: {sorted(p for p in by_provider if p)}"
    )
    password = password_steps[0]
    assert password.get("level") == otp.get("level") and password.get("index", 0) < otp.get("index", 0), (
        "the password step does not run before ext-email-otp in the same sub-flow "
        f"(password level/index={password.get('level')}/{password.get('index')}, "
        f"otp={otp.get('level')}/{otp.get('index')}). The password has to gate the code."
    )


def test_correct_password_gets_a_code_that_completes_login(config):
    since = time.time()
    state = "verify-correct-pw"
    opener, html, pid = _submit_credentials(config, USERNAME, CORRECT_PASSWORD, state)
    assert pid == "login-otp-form", (
        f"a correct password should lead to the emailed-code step; got page_id={pid!r}"
    )

    record = None
    for _ in range(12):
        record = _latest_capture_for(USER_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    assert record is not None, (
        f"no mail was captured for {USER_EMAIL} - the realm's SMTP settings are probably "
        "unconfigured or wrong (the authenticator swallows its own send failure)"
    )

    mail = record.read_text()
    code_match = re.search(r"\b(\d{6})\b", re.sub(r"Message-ID:.*", "", mail))
    assert code_match, f"no numeric one-time code found in the captured mail: {mail[:300]}"
    code = code_match.group(1)

    status, html, headers = _post(opener, _form_action(html, "code"), {"otp": code})
    final = _follow_to_redirect_uri(opener, config, headers.get("Location", ""))
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "correct-password-login.txt").write_text(f"final={final}\n")
    assert final.startswith(config["redirect_uri"]), (
        f"the emailed code did not complete the login; ended at {final[:250]!r}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned: {final[:250]}"
    assert query.get("state") == [state], f"state was not preserved: {query.get('state')}"


@pytest.fixture(scope="session")
def flow_is_live(config):
    """Guard for the negative tests below.

    On a realm where nothing was configured, "no mail was sent" is trivially true, so a
    bare negative assertion would pass vacuously. Confirm first that the CORRECT password
    really does reach the emailed-code step - only then does "the wrong password does not"
    carry any information.
    """
    _, _, pid = _submit_credentials(config, USERNAME, CORRECT_PASSWORD, "verify-liveness")
    assert pid == "login-otp-form", (
        "the emailed-code step is not reachable even with the correct password "
        f"(page_id={pid!r}), so the negative checks below would pass vacuously"
    )
    return True


def test_wrong_password_sends_no_mail_at_all(config, flow_is_live):
    """The decisive test: the password must gate the send, not merely precede it."""
    since = time.time()
    _, _, pid = _submit_credentials(config, USERNAME, WRONG_PASSWORD, "verify-wrong-pw")
    assert pid != "login-otp-form", (
        "a WRONG password reached the emailed-code step. The password is not gating the code, so "
        "anyone who knows a staff email address can have a login code sent to it."
    )
    time.sleep(1.5)
    assert _latest_capture_for(USER_EMAIL, since) is None, (
        f"mail was sent to {USER_EMAIL} despite a wrong password - knowing an address must not be "
        "enough to trigger a login code"
    )


def test_unknown_username_sends_no_mail(config, flow_is_live):
    since = time.time()
    _, _, pid = _submit_credentials(config, UNKNOWN_USERNAME, WRONG_PASSWORD, "verify-unknown")
    assert pid != "login-otp-form", f"unknown username {UNKNOWN_USERNAME!r} reached the code step"
    time.sleep(1.0)
    assert _latest_capture_for(f"{UNKNOWN_USERNAME}@acme-internal.example", since) is None, (
        "mail was sent for a username that has no account"
    )


def test_seeded_users_still_exist_with_passwords(config, admin_token):
    for email in (USER_EMAIL, SECOND_EMAIL):
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
