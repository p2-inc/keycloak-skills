#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: TOTP as a REQUIRED second factor after the password, for everyone.

  TOTP-second-factor (top level)
    auth-cookie                     ALTERNATIVE  priority 0
    auth-spnego                     DISABLED     priority 1
    identity-provider-redirector    ALTERNATIVE  priority 2
    <forms sub-flow>                ALTERNATIVE  priority 3
      auth-username-password-form   REQUIRED     priority 0
      auth-otp-form                 REQUIRED     priority 1

Why REQUIRED and not Keycloak's default conditional OTP: the default browser flow only asks
users who already HAVE an OTP credential, so anyone without one walks in on a password. With
auth-otp-form REQUIRED, a user who has no credential is given the CONFIGURE_TOTP required
action instead - the enrolment page - which is why that action must be enabled.

Four pieces, all through the Admin REST API:
  1. the realm OTP policy, set explicitly (TOTP, 6 digits, 30 s, HmacSHA1);
  2. the CONFIGURE_TOTP required action, enabled;
  3. the flow above, every add call sending priority explicitly (the add-execution endpoint
     APPENDS otherwise; honoured from Keycloak 25, this sandbox runs 26.0.7);
  4. the flow bound to acme-portal.

Then drives the paths over plain HTTP. priya's authenticator is mocked: her OTP credential is
seeded in the realm fixture with a known secret, so her codes are computed here. morgan is
only checked to land on enrolment - he is NOT enrolled, because the verifier enrolls him.
"""

import hashlib
import hmac
import html as htmllib
import pathlib
import re
import struct
import sys
import time
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
FLOW_ALIAS = "TOTP-second-factor"
SUB_ALIAS = "TOTP-second-factor forms"
TIMEOUT = 30
PRIYA, PRIYA_PASSWORD, PRIYA_TOTP_SECRET = "priya", "Priya!Pass1", "AcmePriyaTotp2026Sec"
MORGAN, MORGAN_PASSWORD = "morgan", "Morgan!Pass1"
PASSWORD_FORM, OTP_FORM, ENROL_FORM = "kc-form-login", "kc-otp-login-form", "kc-totp-settings-form"


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def q(alias):
    return urllib.parse.quote(alias, safe="")


def get_admin_token(base, admin_realm, username, password):
    resp = requests.post(f"{base}/realms/{admin_realm}/protocol/openid-connect/token",
                         data={"grant_type": "password", "client_id": "admin-cli",
                               "username": username, "password": password}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["access_token"]


# --------------------------------------------------------------- configuration


def set_otp_policy(base, realm, token):
    rep = requests.get(f"{base}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    rep.update({"otpPolicyType": "totp", "otpPolicyDigits": 6, "otpPolicyPeriod": 30,
                "otpPolicyAlgorithm": "HmacSHA1"})
    requests.put(f"{base}/admin/realms/{realm}", headers=auth(token), json=rep,
                 timeout=TIMEOUT).raise_for_status()


def enable_configure_totp(base, realm, token):
    url = f"{base}/admin/realms/{realm}/authentication/required-actions/CONFIGURE_TOTP"
    action = requests.get(url, headers=auth(token), timeout=TIMEOUT)
    action.raise_for_status()
    rep = action.json()
    if not rep.get("enabled"):
        rep["enabled"] = True
        requests.put(url, headers=auth(token), json=rep, timeout=TIMEOUT).raise_for_status()


def create_flow(base, realm, token):
    flows_url = f"{base}/admin/realms/{realm}/authentication/flows"
    resp = requests.post(flows_url, headers=auth(token), json={
        "alias": FLOW_ALIAS, "providerId": "basic-flow", "topLevel": True, "builtIn": False},
        timeout=TIMEOUT)
    if resp.status_code not in (201, 409):
        resp.raise_for_status()

    def executions(alias):
        return requests.get(f"{flows_url}/{q(alias)}/executions", headers=auth(token),
                            timeout=TIMEOUT).json()

    existing = {e.get("providerId") or e.get("displayName") for e in executions(FLOW_ALIAS)}
    if SUB_ALIAS not in existing:
        resp = requests.post(f"{flows_url}/{q(FLOW_ALIAS)}/executions/flow", headers=auth(token),
                             json={"alias": SUB_ALIAS, "provider": "basic-flow",
                                   "type": "basic-flow", "priority": 3}, timeout=TIMEOUT)
        if resp.status_code not in (201, 409):
            resp.raise_for_status()
    top = [("auth-cookie", "ALTERNATIVE", 0), ("auth-spnego", "DISABLED", 1),
           ("identity-provider-redirector", "ALTERNATIVE", 2)]
    for provider, _req, priority in top:
        if provider not in existing:
            requests.post(f"{flows_url}/{q(FLOW_ALIAS)}/executions/execution", headers=auth(token),
                          json={"provider": provider, "priority": priority},
                          timeout=TIMEOUT).raise_for_status()
    sub_existing = {e.get("providerId") for e in executions(SUB_ALIAS)}
    sub = [("auth-username-password-form", "REQUIRED", 0), ("auth-otp-form", "REQUIRED", 1)]
    for provider, _req, priority in sub:
        if provider not in sub_existing:
            requests.post(f"{flows_url}/{q(SUB_ALIAS)}/executions/execution", headers=auth(token),
                          json={"provider": provider, "priority": priority},
                          timeout=TIMEOUT).raise_for_status()

    wanted = {p: r for p, r, _ in top + sub}
    wanted[SUB_ALIAS] = "ALTERNATIVE"
    for alias in (FLOW_ALIAS, SUB_ALIAS):
        for exe in executions(alias):
            key = exe.get("providerId") or exe.get("displayName")
            if key in wanted and exe["requirement"] != wanted[key]:
                requests.put(f"{flows_url}/{q(alias)}/executions", headers=auth(token),
                             json={"id": exe["id"], "requirement": wanted[key]},
                             timeout=TIMEOUT).raise_for_status()
    return next(f["id"] for f in requests.get(flows_url, headers=auth(token), timeout=TIMEOUT).json()
                if f["alias"] == FLOW_ALIAS)


def bind_client_flow(base, realm, token, client_id, flow_id):
    client = requests.get(f"{base}/admin/realms/{realm}/clients", params={"clientId": client_id},
                          headers=auth(token), timeout=TIMEOUT).json()[0]
    client["authenticationFlowBindingOverrides"] = {"browser": flow_id}
    requests.put(f"{base}/admin/realms/{realm}/clients/{client['id']}", headers=auth(token),
                 json=client, timeout=TIMEOUT).raise_for_status()


# ---------------------------------------------------------------- driving logins


def totp(secret, at=None, digits=6, period=30):
    counter = int((time.time() if at is None else at) // period)
    mac = hmac.new(secret.encode("utf-8"), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF)
               % (10 ** digits)).zfill(digits)


def relax(session):
    for cookie in session.cookies:
        cookie.secure = False


def form_tag(html, form_id):
    for match in re.finditer(r"<form\b[^>]*>", html or "", re.I):
        if f'id="{form_id}"' in match.group(0):
            return match.group(0)
    return None


def form_action(html, form_id):
    action = re.search(r'action="([^"]+)"', form_tag(html, form_id) or "")
    return htmllib.unescape(action.group(1)) if action else None


def hidden_value(html, name):
    tag = re.search(rf'<input\b[^>]*name="{re.escape(name)}"[^>]*>', html or "", re.I)
    value = re.search(r'value="([^"]*)"', tag.group(0)) if tag else None
    return htmllib.unescape(value.group(1)) if value else None


def describe(html):
    page_id = re.search(r'data-page-id="([^"]+)"', html or "")
    form = re.search(r"<form\b.*?</form>", html or "", re.I | re.S)
    return (f"page_id={page_id.group(1) if page_id else None!r}, "
            f"form={(form.group(0) if form else (html or '')[:400])[:1500]!r}")


def follow(session, resp, redirect_uri):
    for _ in range(10):
        relax(session)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if location.startswith(redirect_uri):
                return "callback", location
            resp = session.get(urllib.parse.urljoin(resp.url, location), timeout=TIMEOUT,
                               allow_redirects=False)
            continue
        return "page", resp.text
    return "page", resp.text


def login_page(base, realm, client_id, redirect_uri, state):
    session = requests.Session()
    url = (f"{base}/realms/{realm}/protocol/openid-connect/auth?"
           + urllib.parse.urlencode({"client_id": client_id, "response_type": "code",
                                     "scope": "openid", "redirect_uri": redirect_uri,
                                     "state": state}))
    kind, html = follow(session, session.get(url, timeout=TIMEOUT, allow_redirects=False),
                        redirect_uri)
    if kind != "page" or not form_tag(html, PASSWORD_FORM):
        raise RuntimeError(f"no username/password form on the login page: {describe(html)}")
    return session, html


def password_step(session, html, username, password, redirect_uri):
    resp = session.post(form_action(html, PASSWORD_FORM),
                        data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    return follow(session, resp, redirect_uri)


def otp_step(session, html, code, redirect_uri):
    data = {"otp": code}
    if hidden_value(html, "selectedCredentialId"):
        data["selectedCredentialId"] = hidden_value(html, "selectedCredentialId")
    resp = session.post(form_action(html, OTP_FORM), data=data, timeout=TIMEOUT,
                        allow_redirects=False)
    return follow(session, resp, redirect_uri)


def self_check(base, realm, client_id, redirect_uri):
    args = (base, realm, client_id, redirect_uri)

    # priya: password -> code form -> correct code -> callback
    state = "oracle-password-and-code"
    session, html = login_page(*args, state)
    kind, value = password_step(session, html, PRIYA, PRIYA_PASSWORD, redirect_uri)
    if kind != "page" or not form_tag(value, OTP_FORM):
        raise RuntimeError(f"priya's password did not lead to the TOTP form: {describe(value)}")
    kind, value = otp_step(session, value, totp(PRIYA_TOTP_SECRET), redirect_uri)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query) if kind == "callback" else {}
    if "code" not in query or query.get("state") != [state]:
        raise RuntimeError(f"password + correct code did not log priya in: {describe(value)}")
    print("  priya: password + TOTP code -> logged in, code+state verified")

    # priya: password + wrong code -> rejected
    session, html = login_page(*args, "oracle-wrong-code")
    kind, value = password_step(session, html, PRIYA, PRIYA_PASSWORD, redirect_uri)
    now = time.time()
    taken = {totp(PRIYA_TOTP_SECRET, at=now + d * 30) for d in (-2, -1, 0, 1, 2)}
    bad = next(c for c in ("000000", "111111", "123456") if c not in taken)
    kind, value = otp_step(session, value, bad, redirect_uri)
    if kind == "callback":
        raise RuntimeError("a wrong TOTP code logged priya in")
    print("  priya: password + wrong code -> rejected")

    # priya: wrong password -> never the code form
    session, html = login_page(*args, "oracle-wrong-password")
    kind, value = password_step(session, html, PRIYA, "not-her-password", redirect_uri)
    if kind == "callback" or form_tag(value, OTP_FORM):
        raise RuntimeError(f"a wrong password got past the password step: {describe(value)}")
    print("  priya: wrong password -> stopped at the password form")

    # morgan: password -> enrolment page (NOT completed: the verifier enrolls him)
    session, html = login_page(*args, "oracle-enrolment-required")
    kind, value = password_step(session, html, MORGAN, MORGAN_PASSWORD, redirect_uri)
    if kind != "page" or not form_tag(value, ENROL_FORM) or not hidden_value(value, "totpSecret"):
        raise RuntimeError(f"morgan's password did not lead to TOTP enrolment: {describe(value)}")
    print("  morgan: password -> TOTP enrolment page (left unenrolled for the verifier)")


def main():
    creds = load_settings(CREDS_PATH)
    base, realm = creds["keycloak_base_url"].rstrip("/"), creds["target_realm"]
    client_id, redirect_uri = creds["app_client_id"], creds["app_redirect_uri"]
    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"],
                            creds["admin_password"])

    print("Setting the realm OTP policy (TOTP, 6 digits, 30 s, HmacSHA1)...")
    set_otp_policy(base, realm, token)
    print("Enabling the CONFIGURE_TOTP required action...")
    enable_configure_totp(base, realm, token)
    print(f"Authoring '{FLOW_ALIAS}' (password REQUIRED, then auth-otp-form REQUIRED)...")
    flow_id = create_flow(base, realm, token)
    print("Binding the flow to acme-portal...")
    bind_client_flow(base, realm, token, client_id, flow_id)
    print("Driving the logins...")
    self_check(base, realm, client_id, redirect_uri)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ORACLE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
