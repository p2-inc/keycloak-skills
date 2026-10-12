# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

The task asks for TOTP as a REQUIRED second factor after the password, for every user.
Everything is driven for real against Keycloak over plain HTTP - a TOTP code is just a
form field, so no browser is needed. The only thing mocked is the authenticator app:

  * priya's authenticator is seeded in the realm fixture with a known TOTP secret, so the
    verifier computes her codes exactly as a phone app would (RFC 6238, HMAC-SHA1 over the
    secret's bytes). Nothing has to be read off an enrolment page for her.
  * morgan has no authenticator. His enrolment page is read only for the one value Keycloak
    renders for that purpose: the hidden `totpSecret` input of `kc-totp-settings-form`.

The decisive check is morgan's: Keycloak's DEFAULT browser flow already asks a user who has
an OTP credential (priya) for a code, through its conditional OTP sub-flow - so priya's tests
alone would pass on an unconfigured realm. What the default flow does NOT do is stop a user
who has no authenticator: it lets morgan in on his password. Requiring TOTP for everyone means
morgan's correct password must lead to enrolment, never straight to the application.

Deliberately shape-agnostic. Nothing here asserts a flow alias, an execution order, a
requirement value or which binding surface was used. Pages are recognised by the form ids
Keycloak's own login templates render (kc-form-login, kc-otp-login-form,
kc-totp-settings-form), and every page check quotes the page's <form> when it fails. The
tests share state through Keycloak and run in file order: morgan is enrolled last.
"""

import hashlib
import hmac
import html as htmllib
import pathlib
import re
import struct
import time
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

# Seeded in environment/acme-realm.json (and stated in task.md).
ENROLLED_USER, ENROLLED_PASSWORD = "priya", "Priya!Pass1"
UNENROLLED_USER, UNENROLLED_PASSWORD = "morgan", "Morgan!Pass1"
WRONG_PASSWORD = "definitely-not-the-password"
# The mocked authenticator: the TOTP secret of priya's pre-registered OTP credential.
PRIYA_TOTP_SECRET = "AcmePriyaTotp2026Sec"

PASSWORD_FORM, OTP_FORM, ENROL_FORM = "kc-form-login", "kc-otp-login-form", "kc-totp-settings-form"


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


# --------------------------------------------------------------------- TOTP


def totp(secret, at=None, digits=6, period=30, algorithm="HmacSHA1"):
    """RFC 6238 over the secret's raw bytes - what Keycloak validates against."""
    digest = {"HmacSHA1": hashlib.sha1, "HmacSHA256": hashlib.sha256,
              "HmacSHA512": hashlib.sha512}[algorithm]
    counter = int((time.time() if at is None else at) // period)
    mac = hmac.new(secret.encode("utf-8"), struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    value = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(value).zfill(digits)


def fresh_code(secret, period=30, **kw):
    """A code from a period no earlier caller (the oracle) can have used: Keycloak refuses
    to accept the same code twice, so wait for the next period to begin."""
    time.sleep(period - (time.time() % period) + 1)
    return totp(secret, period=period, **kw)


def wrong_code(secret, **kw):
    """A 6-digit code that is valid for no period in Keycloak's look-around window."""
    now = time.time()
    taken = {totp(secret, at=now + d * 30, **kw) for d in (-2, -1, 0, 1, 2)}
    return next(c for c in ("000000", "111111", "123456", "999999") if c not in taken)


# --------------------------------------------------------------------- HTTP


def _relax(session):
    """Keycloak marks AUTH_SESSION_ID / KC_RESTART Secure; SameSite=None. Browsers send them
    over http://localhost anyway; requests will not, and every form POST then 400s with
    "Cookie not found."."""
    for cookie in session.cookies:
        cookie.secure = False


def _auth_url(config, state):
    return (f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
            + urllib.parse.urlencode({"client_id": config["client_id"], "response_type": "code",
                                      "scope": "openid", "redirect_uri": config["redirect_uri"],
                                      "state": state}))


def _form_tag(html, form_id):
    for match in re.finditer(r"<form\b[^>]*>", html or "", re.I):
        if f'id="{form_id}"' in match.group(0):
            return match.group(0)
    return None


def _form_action(html, form_id):
    tag = _form_tag(html, form_id)
    action = re.search(r'action="([^"]+)"', tag or "")
    return htmllib.unescape(action.group(1)) if action else None


def _hidden_value(html, name):
    tag = re.search(rf'<input\b[^>]*name="{re.escape(name)}"[^>]*>', html or "", re.I)
    value = re.search(r'value="([^"]*)"', tag.group(0)) if tag else None
    return htmllib.unescape(value.group(1)) if value else None


def _describe(html):
    """The page's identity and its <form> - quoted in every page-check failure."""
    page_id = re.search(r'data-page-id="([^"]+)"', html or "")
    forms = re.findall(r'<form\b[^>]*\bid="([^"]+)"', html or "")
    form = re.search(r"<form\b.*?</form>", html or "", re.I | re.S)
    return (f"page_id={page_id.group(1) if page_id else None!r}, forms={forms}, "
            f"form={(form.group(0) if form else (html or '')[:400])[:1500]!r}")


def _follow(session, resp, config):
    """Follow redirects until the client callback (returned as ("callback", url)) or a page
    (returned as ("page", html))."""
    for _ in range(10):
        _relax(session)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith(config["redirect_uri"]):
                return "callback", location
            resp = session.get(urllib.parse.urljoin(resp.url, location), timeout=TIMEOUT,
                               allow_redirects=False)
            continue
        return "page", resp.text
    return "page", resp.text


def _start(config, state):
    session = requests.Session()
    resp = session.get(_auth_url(config, state), timeout=TIMEOUT, allow_redirects=False)
    kind, html = _follow(session, resp, config)
    assert kind == "page" and _form_tag(html, PASSWORD_FORM), (
        f"the login page for {config['client_id']} is not Keycloak's username/password form: "
        f"{_describe(html if kind == 'page' else '')}")
    return session, html


def _submit_password(config, session, html, username, password):
    resp = session.post(_form_action(html, PASSWORD_FORM),
                        data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    return _follow(session, resp, config)


def _submit_otp(config, session, html, code):
    data = {"otp": code}
    selected = _hidden_value(html, "selectedCredentialId")
    if selected:
        data["selectedCredentialId"] = selected
    resp = session.post(_form_action(html, OTP_FORM), data=data, timeout=TIMEOUT,
                        allow_redirects=False)
    return _follow(session, resp, config)


def _assert_callback(kind, value, state, what):
    assert kind == "callback", f"{what} did not reach the application callback: {_describe(value)}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    assert "code" in query, f"{what}: no authorization code returned: {value[:250]}"
    assert query.get("state") == [state], (
        f"{what}: state was not preserved: sent {state!r}, got {query.get('state')!r}")


def _save(name, html):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / name).write_text((html or "")[:20000])


# ---------------------------------------------------------- the enrolled user


def test_a_correct_password_alone_does_not_log_in_an_enrolled_user(config):
    """priya's correct password must lead to the TOTP code prompt, not into the app."""
    session, html = _start(config, "verify-password-alone")
    kind, value = _submit_password(config, session, html, ENROLLED_USER, ENROLLED_PASSWORD)
    assert kind == "page", "priya's correct password alone completed the login - no second factor"
    _save("after-correct-password.html", value)
    assert _form_tag(value, OTP_FORM), (
        f"after priya's correct password the page is not the TOTP code form: {_describe(value)}")


def test_password_and_a_correct_code_log_in(config):
    """The happy path: password, then the current code from priya's authenticator."""
    state = "verify-password-and-code"
    session, html = _start(config, state)
    kind, value = _submit_password(config, session, html, ENROLLED_USER, ENROLLED_PASSWORD)
    assert kind == "page" and _form_tag(value, OTP_FORM), (
        f"priya's correct password did not lead to the TOTP code form: {_describe(value)}")
    kind, value = _submit_otp(config, session, value, fresh_code(PRIYA_TOTP_SECRET))
    _assert_callback(kind, value, state, "password + correct TOTP code")


def test_a_correct_password_and_a_wrong_code_are_rejected(config):
    session, html = _start(config, "verify-wrong-code")
    kind, value = _submit_password(config, session, html, ENROLLED_USER, ENROLLED_PASSWORD)
    assert kind == "page" and _form_tag(value, OTP_FORM), (
        f"priya's correct password did not lead to the TOTP code form: {_describe(value)}")
    kind, value = _submit_otp(config, session, value, wrong_code(PRIYA_TOTP_SECRET))
    assert kind == "page", "a WRONG TOTP code completed the login"
    assert _form_tag(value, OTP_FORM), (
        f"after a wrong code the TOTP form was not shown again: {_describe(value)}")


def test_a_wrong_password_never_reaches_the_code_step(config):
    """The password genuinely gates the TOTP step: a wrong password gets the password error,
    never the code prompt."""
    session, html = _start(config, "verify-wrong-password")
    kind, value = _submit_password(config, session, html, ENROLLED_USER, WRONG_PASSWORD)
    assert kind == "page", "a WRONG password completed the login"
    assert not _form_tag(value, OTP_FORM), (
        f"a WRONG password reached the TOTP code form: {_describe(value)}")
    assert _form_tag(value, PASSWORD_FORM), (
        f"after a wrong password the password form was not shown again: {_describe(value)}")


# --------------------------------------------------------- the unenrolled user


def test_a_user_without_an_authenticator_is_made_to_enrol(config):
    """The decisive check. morgan has no TOTP credential: his correct password must lead to
    the enrolment page. Keycloak's default flow lets him straight in instead."""
    session, html = _start(config, "verify-enrolment-required")
    kind, value = _submit_password(config, session, html, UNENROLLED_USER, UNENROLLED_PASSWORD)
    assert kind == "page", (
        "morgan, who has no authenticator, was logged in on his password alone - TOTP is not "
        "required for everyone (this is what Keycloak's default conditional-OTP flow does)")
    _save("unenrolled-after-password.html", value)
    assert _form_tag(value, ENROL_FORM) and _hidden_value(value, "totpSecret"), (
        f"after morgan's correct password the page is not TOTP enrolment: {_describe(value)}")


def test_enrolling_completes_the_login_and_registers_the_authenticator(config, admin_headers):
    """morgan scans (reads totpSecret), enters the first code, and is logged in; afterwards
    he has an OTP credential."""
    state = "verify-enrolment"
    session, html = _start(config, state)
    kind, value = _submit_password(config, session, html, UNENROLLED_USER, UNENROLLED_PASSWORD)
    assert kind == "page" and _form_tag(value, ENROL_FORM), (
        f"morgan's correct password did not lead to TOTP enrolment: {_describe(value)}")
    secret = _hidden_value(value, "totpSecret")
    assert secret, f"the enrolment form carries no totpSecret: {_describe(value)}"
    realm = requests.get(f"{config['base']}/admin/realms/{config['realm']}",
                         headers=admin_headers, timeout=TIMEOUT).json()
    code = totp(secret, digits=int(realm.get("otpPolicyDigits", 6)),
                period=int(realm.get("otpPolicyPeriod", 30)),
                algorithm=realm.get("otpPolicyAlgorithm", "HmacSHA1"))
    data = {"totp": code, "totpSecret": secret, "userLabel": "verifier"}
    mode = _hidden_value(value, "mode")
    if mode:
        data["mode"] = mode
    resp = session.post(_form_action(value, ENROL_FORM), data=data, timeout=TIMEOUT,
                        allow_redirects=False)
    kind, value = _follow(session, resp, config)
    _assert_callback(kind, value, state, "TOTP enrolment")
    users = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                         headers=admin_headers, params={"username": UNENROLLED_USER,
                                                        "exact": "true"}, timeout=TIMEOUT).json()
    creds = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users/{users[0]['id']}/credentials",
        headers=admin_headers, timeout=TIMEOUT).json()
    assert "otp" in {c.get("type") for c in creds}, (
        f"morgan completed enrolment but has no OTP credential: {sorted(c.get('type') for c in creds)}")


# ------------------------------------------------------------- no collateral


def test_the_realm_otp_policy_is_totp_with_6_digits_and_30_seconds(config, admin_headers):
    realm = requests.get(f"{config['base']}/admin/realms/{config['realm']}",
                         headers=admin_headers, timeout=TIMEOUT).json()
    assert realm.get("otpPolicyType", "totp") == "totp", f"otpPolicyType={realm.get('otpPolicyType')!r}"
    assert int(realm.get("otpPolicyDigits", 6)) == 6, f"otpPolicyDigits={realm.get('otpPolicyDigits')!r}"
    assert int(realm.get("otpPolicyPeriod", 30)) == 30, f"otpPolicyPeriod={realm.get('otpPolicyPeriod')!r}"


def test_both_accounts_still_exist_are_enabled_and_keep_their_password(config, admin_headers):
    for username in (ENROLLED_USER, UNENROLLED_USER):
        users = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                             headers=admin_headers, params={"username": username, "exact": "true"},
                             timeout=TIMEOUT).json()
        assert users, f"the {username} account is gone"
        assert users[0].get("enabled") is True, f"the {username} account is disabled"
        creds = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}/users/{users[0]['id']}/credentials",
            headers=admin_headers, timeout=TIMEOUT).json()
        assert "password" in {c.get("type") for c in creds}, f"{username}'s password was removed"


def test_only_the_acme_realm_was_added(config, admin_headers):
    resp = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                        params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}")
