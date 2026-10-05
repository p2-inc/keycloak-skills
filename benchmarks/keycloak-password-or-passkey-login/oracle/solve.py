#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: username/password OR passkey as alternative first factors.

One browser flow offering TWO first-factor methods side by side, either of which
logs the user in on its own:

  Password-or-passkey (top level)
    auth-cookie                          ALTERNATIVE  priority 0
    auth-spnego                          DISABLED     priority 1
    identity-provider-redirector         ALTERNATIVE  priority 2
    <forms sub-flow>                     ALTERNATIVE  priority 3
      auth-username-password-form        ALTERNATIVE  priority 2
      webauthn-authenticator-passwordless ALTERNATIVE  priority 3

This is keycloak-zero-password-login's shape with ext-magic-form swapped for the
stock password form - so, unlike that task, everything here is stock Keycloak.

Four pieces, all through the Admin REST API:

  1. The realm's WebAuthn PASSWORDLESS policy (a separate policy block from the
     ordinary 2FA WebAuthn policy) - rpId must match the hostname the browser
     actually navigates to ("localhost"), or the ceremony fails client-side
     with no useful server error. Plus realm SMTP: an existing user's first
     passkey is delivered by an execute-actions email.

  2. The flow above. Execution order is load-bearing and the add-execution
     endpoint APPENDS, so every add call sends priority explicitly (honoured
     from Keycloak 25 onward; this sandbox runs 26.0.7).

     Both leaves are ALTERNATIVE. That is the whole point: if the passkey step
     were REQUIRED (or a conditional sub-flow), this would be password-THEN-
     passkey 2FA and a user without a passkey could not finish logging in.
     The password form is the lower priority of the two, so it renders first -
     everyone has a password today - and the passkey is behind "Try another way".

  3. Bind it to acme-portal.

  4. Enrol a passkey for marcus without touching his password: an
     execute-actions email carrying webauthn-register-passwordless.

Finishes by driving every path for real, since none is verifiable from
configuration alone:
  - priya (password, no passkey) logs in with the password alone,
  - a wrong password is rejected,
  - marcus logs in with his passkey through a headless browser with a CDP
    virtual authenticator, never filling in the password form, and
  - marcus can still log in with his password after enrolling a passkey.
"""

import json
import pathlib
import re
import sys
import time
import urllib.parse

import requests
from playwright.sync_api import sync_playwright

CREDS_PATH = "/root/admin_credentials.txt"
STAFF_PATH = "/root/staff_credentials.txt"
FLOW_ALIAS = "Password-or-passkey"
SUB_ALIAS = "Password-or-passkey forms"
CAPTURE_DIR = "/var/mail-capture"
TIMEOUT = 30


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def get_admin_token(base_url, admin_realm, username, password):
    resp = requests.post(
        f"{base_url}/realms/{admin_realm}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": username, "password": password},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def q(alias):
    return urllib.parse.quote(alias, safe="")


def set_webauthn_passwordless_policy_and_smtp(base_url, realm, token):
    rep = requests.get(f"{base_url}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    rep["webAuthnPolicyPasswordlessRpEntityName"] = "Acme Portal"
    rep["webAuthnPolicyPasswordlessRpId"] = "localhost"
    rep["webAuthnPolicyPasswordlessRequireResidentKey"] = "Yes"
    rep["webAuthnPolicyPasswordlessUserVerificationRequirement"] = "preferred"
    rep["smtpServer"] = {
        "host": "localhost", "port": "1025", "from": "no-reply@acme.example",
        "auth": "false", "starttls": "false", "ssl": "false",
    }
    resp = requests.put(f"{base_url}/admin/realms/{realm}", headers=auth(token), json=rep, timeout=TIMEOUT)
    resp.raise_for_status()


def create_flow(base_url, realm, token):
    """Author the flow, sending priority explicitly on every add call."""
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication/flows", headers=auth(token),
        json={"alias": FLOW_ALIAS, "providerId": "basic-flow", "topLevel": True, "builtIn": False},
        timeout=TIMEOUT)
    if resp.status_code not in (201, 409):
        resp.raise_for_status()

    existing = {e.get("providerId") or e.get("displayName") for e in requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{q(FLOW_ALIAS)}/executions",
        headers=auth(token), timeout=TIMEOUT).json()}

    # The sub-flow is created AS an execution of the parent. Priority 3 keeps it
    # behind the three leaves below rather than at the front.
    if SUB_ALIAS not in existing:
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{q(FLOW_ALIAS)}/executions/flow",
            headers=auth(token),
            json={"alias": SUB_ALIAS, "provider": "basic-flow", "type": "basic-flow", "priority": 3},
            timeout=TIMEOUT)
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    top_leaves = [("auth-cookie", "ALTERNATIVE", 0),
                  ("auth-spnego", "DISABLED", 1),
                  ("identity-provider-redirector", "ALTERNATIVE", 2)]
    for provider, _requirement, priority in top_leaves:
        if provider in existing:
            continue
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{q(FLOW_ALIAS)}/executions/execution",
            headers=auth(token), json={"provider": provider, "priority": priority}, timeout=TIMEOUT)
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    sub_existing = {e.get("providerId") for e in requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{q(SUB_ALIAS)}/executions",
        headers=auth(token), timeout=TIMEOUT).json()}
    # The password form FIRST: every staff account has a password today, so the
    # default screen is never a dead end; the passkey is behind "Try another way".
    sub_leaves = [("auth-username-password-form", "ALTERNATIVE", 2),
                  ("webauthn-authenticator-passwordless", "ALTERNATIVE", 3)]
    for provider, _requirement, priority in sub_leaves:
        if provider in sub_existing:
            continue
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{q(SUB_ALIAS)}/executions/execution",
            headers=auth(token), json={"provider": provider, "priority": priority}, timeout=TIMEOUT)
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    wanted = {p: r for p, r, _ in top_leaves + sub_leaves}
    wanted[SUB_ALIAS] = "ALTERNATIVE"
    for alias in (FLOW_ALIAS, SUB_ALIAS):
        for exe in requests.get(
                f"{base_url}/admin/realms/{realm}/authentication/flows/{q(alias)}/executions",
                headers=auth(token), timeout=TIMEOUT).json():
            key = exe.get("providerId") or exe.get("displayName")
            if key in wanted and exe["requirement"] != wanted[key]:
                # Send the whole row back: this PUT also writes "priority", so a body
                # of just id+requirement would reset it to 0 and scramble the order.
                resp = requests.put(
                    f"{base_url}/admin/realms/{realm}/authentication/flows/{q(alias)}/executions",
                    headers=auth(token),
                    json={**exe, "requirement": wanted[key]}, timeout=TIMEOUT)
                resp.raise_for_status()

    return next(f["id"] for f in requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows",
        headers=auth(token), timeout=TIMEOUT).json() if f["alias"] == FLOW_ALIAS)


def bind_client_flow(base_url, realm, token, client_id, flow_id):
    client = requests.get(f"{base_url}/admin/realms/{realm}/clients?clientId={client_id}",
                          headers=auth(token), timeout=TIMEOUT).json()[0]
    client["authenticationFlowBindingOverrides"] = {"browser": flow_id}
    resp = requests.put(f"{base_url}/admin/realms/{realm}/clients/{client['id']}",
                        headers=auth(token), json=client, timeout=TIMEOUT)
    resp.raise_for_status()


def find_user(base_url, realm, token, username):
    matches = requests.get(
        f"{base_url}/admin/realms/{realm}/users?username={username}&exact=true",
        headers=auth(token), timeout=TIMEOUT).json()
    if not matches:
        raise RuntimeError(f"user {username} not found")
    return matches[0]["id"]


def send_required_action_email(base_url, realm, token, user_id, client_id, redirect_uri):
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}/users/{user_id}/execute-actions-email"
        f"?client_id={client_id}&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}",
        headers=auth(token), json=["webauthn-register-passwordless"], timeout=TIMEOUT)
    resp.raise_for_status()


def wait_for_capture(email_marker, attempts=20, delay=0.5):
    marker = email_marker.replace("@", "-at-")
    for _ in range(attempts):
        files = sorted(pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return json.loads(files[0].read_text())
        time.sleep(delay)
    return None


def auth_url(client_id, redirect_uri, state):
    return ("http://localhost:8080/auth/realms/acme/protocol/openid-connect/auth?"
            + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": redirect_uri,
                                      "response_type": "code", "scope": "openid", "state": state}))


def password_login(client_id, redirect_uri, username, password, state):
    """The password half, over plain HTTP. Returns the callback URL, or None if
    the login did not reach the client (e.g. the password was rejected, or the
    flow demanded something more after it)."""
    session = requests.Session()
    resp = session.get(auth_url(client_id, redirect_uri, state), timeout=TIMEOUT)
    resp.raise_for_status()
    for cookie in session.cookies:
        cookie.secure = False
    if 'type="password"' not in resp.text:
        raise RuntimeError("the login page offers no password field")
    action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', resp.text) \
        or re.search(r'action="([^"]+)"', resp.text)
    if not action:
        raise RuntimeError("no form action on the login page")
    form_url = action.group(1).replace("&amp;", "&")

    resp = session.post(form_url, data={"username": username, "password": password},
                        timeout=TIMEOUT, allow_redirects=False)
    hops = 0
    while resp.status_code in (301, 302, 303, 307, 308) and hops < 10:
        for cookie in session.cookies:
            cookie.secure = False
        location = resp.headers["Location"]
        if location.startswith(redirect_uri):
            return location
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        hops += 1
    return None


def require_code(location, state, what):
    if not location:
        raise RuntimeError(f"{what}: never reached the client callback")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if "code" not in query:
        raise RuntimeError(f"{what}: no authorization code: {location}")
    if query.get("state") != [state]:
        raise RuntimeError(f"{what}: state not preserved")


def _reach_passkey_control(page):
    """Get from the rendered login page to the WebAuthn control.

    The password form is the lower-priority ALTERNATIVE, so Keycloak renders it
    first and puts the passkey behind "Try another way" - an <a id="try-another-way">
    that submits a hidden form, then a credential-selection page whose entries are
    clickable <div class="select-auth-box-parent"> elements. Verified against
    Keycloak 26.0.7 (same markup as keycloak-zero-password-login).
    """
    if page.locator("#authenticateWebAuthnButton").count():
        return

    another = page.locator("#try-another-way")
    if not another.count():
        another = page.locator("a:has-text('Try Another Way'), a:has-text('Try another way')")
    if not another.count():
        if page.locator("#kc-select-try-another-way-form").count():
            page.evaluate("document.forms['kc-select-try-another-way-form'].requestSubmit()")
        else:
            raise RuntimeError(
                f"on {page.url} the login page offered neither the passkey control nor a "
                "'Try another way' control, so the passkey method is unreachable")
    else:
        another.first.click()
    page.wait_for_load_state("networkidle")

    if page.locator("#authenticateWebAuthnButton").count():
        return

    for label in ("Passkey", "Security Key", "WebAuthn"):
        option = page.locator(f"div.select-auth-box-parent:has-text('{label}')")
        if not option.count():
            option = page.locator(f"li:has-text('{label}') div.select-auth-box-parent")
        if option.count():
            option.first.click()
            page.wait_for_load_state("networkidle")
            break


def passkey_register_and_login(client_id, redirect_uri, email):
    """Register a passkey from the action-token link, then log in with it -
    in a real browser with a CDP virtual authenticator, never touching the
    password form."""
    record = wait_for_capture(email)
    if record is None:
        raise RuntimeError(f"no captured mail for {email}")
    match = re.search(r"(http://localhost:8080\S+action-token\?key=\S+)", record["body_plain"])
    if not match:
        raise RuntimeError(f"no action-token link in captured mail for {email}")
    action_link = match.group(1).strip()

    captured = {}
    state = f"oracle-passkey-{email.split('@')[0]}"
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
            if req.url.startswith(redirect_uri):
                captured["final_url"] = req.url

        page.on("request", on_request)

        # Registration ceremony, reached by the action-token link.
        page.goto(action_link, wait_until="networkidle")
        proceed = page.locator("a:has-text('Click here to proceed')")
        if proceed.count():
            proceed.first.click()
            page.wait_for_load_state("networkidle")
        page.locator("#registerWebAuthn").click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # Fresh login. Drop any session the registration left behind, so the
        # passkey ceremony - not an SSO cookie - is what completes this login.
        # The credential lives in the virtual authenticator, not in cookies.
        context.clear_cookies()
        captured.pop("final_url", None)
        page.goto(auth_url(client_id, redirect_uri, state), wait_until="networkidle")
        _reach_passkey_control(page)

        if not page.locator("#authenticateWebAuthnButton").count():
            raise RuntimeError("passkey login control never became reachable")
        page.locator("#authenticateWebAuthnButton").click()
        page.wait_for_timeout(2000)
        browser.close()

    require_code(captured.get("final_url"), state, f"{email} passkey login")
    print(f"  {email}: passkey registered and login completed without a password, code+state verified")


def main():
    creds = load_settings(CREDS_PATH)
    staff = load_settings(STAFF_PATH)
    base_url = creds["keycloak_base_url"]
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base_url, creds["admin_realm"],
                            creds["admin_username"], creds["admin_password"])

    print("Setting the WebAuthn passwordless policy and realm SMTP...")
    set_webauthn_passwordless_policy_and_smtp(base_url, realm, token)

    print(f"Authoring '{FLOW_ALIAS}' (+ forms sub-flow) with explicit priorities...")
    flow_id = create_flow(base_url, realm, token)

    print("Binding the flow to the acme-portal client...")
    bind_client_flow(base_url, realm, token, client_id, flow_id)

    print("priya (password, no passkey) logs in with the password alone...")
    state = "oracle-password-priya"
    require_code(password_login(client_id, redirect_uri, staff["priya_username"],
                                staff["priya_password"], state), state, "priya password login")
    print("  priya: password login completed, code+state verified")

    print("A wrong password is rejected...")
    if password_login(client_id, redirect_uri, staff["priya_username"], "not-her-password",
                      "oracle-wrong-password"):
        raise RuntimeError("a wrong password reached the client callback")
    print("  wrong password: no callback, as expected")

    print("Enrolling a passkey for marcus by execute-actions email, then logging in with it...")
    user_id = find_user(base_url, realm, token, staff["marcus_username"])
    send_required_action_email(base_url, realm, token, user_id, client_id, redirect_uri)
    passkey_register_and_login(client_id, redirect_uri, "marcus@acme.example")

    print("marcus still logs in with his password after enrolling a passkey...")
    state = "oracle-password-marcus"
    require_code(password_login(client_id, redirect_uri, staff["marcus_username"],
                                staff["marcus_password"], state), state, "marcus password login")
    print("  marcus: password login completed, code+state verified")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ORACLE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
