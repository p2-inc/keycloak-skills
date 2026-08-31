#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: a "0 password required" login flow for the acme realm.

One browser flow offering TWO passwordless methods side by side, with no
password authenticator anywhere in it:

  Passwordless-or-magic-link (top level)
    auth-cookie                          ALTERNATIVE  priority 0
    auth-spnego                          DISABLED     priority 1
    identity-provider-redirector         ALTERNATIVE  priority 2
    <forms sub-flow>                     ALTERNATIVE  priority 3
      ext-magic-form                     ALTERNATIVE  priority 2
      webauthn-authenticator-passwordless ALTERNATIVE  priority 3

Five pieces, all through the Admin REST API:

  1. Confirm the keycloak-magic-link extension is present at all - the built-in
     "magic link" flow it auto-creates is the cheapest proof. WebAuthn is stock
     Keycloak; ext-magic-form is not.

  2. The realm's WebAuthn PASSWORDLESS policy (a separate policy block from the
     ordinary 2FA WebAuthn policy) - rpId must match the hostname the browser
     actually navigates to ("localhost"), or the ceremony fails client-side
     with no useful server error.

  3. The two flows above. Execution order is load-bearing and the add-execution
     endpoint APPENDS: with no "priority" in the body the server assigns
     (last sibling + 1), so creating the sub-flow before the top-level leaves
     would put the sub-flow at priority 0, ahead of auth-cookie. Every add call
     here sends priority explicitly (honoured from Keycloak 25 onward; this
     sandbox runs 26.0.7).

     ext-magic-form is deliberately the LOWER priority of the two alternatives:
     it works for a user with no credentials at all, so the default screen is
     never a dead end. The passkey is reached via "Try another way".

  4. Realm SMTP, or the magic-link half is inert - and the login page still
     says "check your email" either way, so nothing surfaces the failure.

  5. ext-magic-create-nonexistent-user=false. It defaults to TRUE, which in a
     zero-password flow means the login page is open self-registration: typing
     any address provisions an account and mails it a working login link.

Finishes by driving BOTH methods for real, since neither is verifiable from
configuration alone:
  - magic link over plain HTTP (submit address -> read captured mail -> follow
    link -> authorization code), and
  - a passkey through a headless browser with a CDP virtual authenticator (the
    crypto exchange can't be faked with a curl call), reached from the same
    login page via "Try another way".
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
FLOW_ALIAS = "Passwordless-or-magic-link"
SUB_ALIAS = "Passwordless-or-magic-link passwordless-or-password forms"
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


def require_magic_link_extension(base_url, realm, token):
    """The provider auto-creates a built-in 'magic link' flow when installed."""
    flows = requests.get(f"{base_url}/admin/realms/{realm}/authentication/flows",
                         headers=auth(token), timeout=TIMEOUT).json()
    aliases = {f["alias"] for f in flows}
    if "magic link" not in aliases:
        raise RuntimeError(
            "keycloak-magic-link extension not installed (no built-in 'magic link' flow); "
            "ext-magic-form is unavailable and half this flow cannot be authored")


def set_webauthn_passwordless_policy(base_url, realm, token):
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


def create_flows(base_url, realm, token):
    """Author both flows, sending priority explicitly on every add call."""
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
    # ext-magic-form FIRST: it works for a user with no credentials, so the
    # default screen is never a dead end for someone with no passkey yet.
    sub_leaves = [("ext-magic-form", "ALTERNATIVE", 2),
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
                resp = requests.put(
                    f"{base_url}/admin/realms/{realm}/authentication/flows/{q(alias)}/executions",
                    headers=auth(token),
                    json={"id": exe["id"], "requirement": wanted[key]}, timeout=TIMEOUT)
                resp.raise_for_status()

    return next(f["id"] for f in requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows",
        headers=auth(token), timeout=TIMEOUT).json() if f["alias"] == FLOW_ALIAS)


def disable_create_nonexistent_user(base_url, realm, token):
    executions = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{q(SUB_ALIAS)}/executions",
        headers=auth(token), timeout=TIMEOUT).json()
    exe = next(e for e in executions if e.get("providerId") == "ext-magic-form")
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication/executions/{exe['id']}/config",
        headers=auth(token),
        json={"alias": "zero-password-existing-accounts-only",
              "config": {"ext-magic-create-nonexistent-user": "false"}},
        timeout=TIMEOUT)
    if resp.status_code not in (201, 409):
        resp.raise_for_status()


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


def magic_link_login(client_id, redirect_uri, email):
    """The magic-link half, over plain HTTP - no browser needed."""
    session = requests.Session()
    state = f"oracle-magic-{email.split('@')[0]}"
    resp = session.get(auth_url(client_id, redirect_uri, state), timeout=TIMEOUT)
    resp.raise_for_status()
    for cookie in session.cookies:
        cookie.secure = False
    if 'type="password"' in resp.text:
        raise RuntimeError("password field present on the login page")

    action = re.search(r'action="([^"]+)"', resp.text)
    if not action:
        raise RuntimeError("no form action on the magic-link login page")
    form_url = action.group(1).replace("&amp;", "&")

    resp = session.post(form_url, data={"email": email, "username": email},
                        timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()

    record = wait_for_capture(email)
    if record is None:
        raise RuntimeError(f"no captured mail for {email} - SMTP not configured?")
    match = re.search(r"(http://localhost:8080\S*?login-actions\S+)", record["body_plain"])
    if not match:
        match = re.search(r"(http://localhost:8080\S+)", record["body_plain"])
    if not match:
        raise RuntimeError(f"no login link in captured mail for {email}")
    link = match.group(1).strip().rstrip(">").replace("&amp;", "&")

    resp = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    hops = 0
    while resp.status_code in (301, 302, 303, 307, 308) and hops < 10:
        for cookie in session.cookies:
            cookie.secure = False
        location = resp.headers["Location"]
        if location.startswith(redirect_uri):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            if "code" not in query:
                raise RuntimeError(f"magic-link login returned no code for {email}: {location}")
            if query.get("state") != [state]:
                raise RuntimeError(f"magic-link state not preserved for {email}")
            print(f"  {email}: magic-link login completed, code+state verified")
            return
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        hops += 1
    raise RuntimeError(f"magic-link login for {email} never reached {redirect_uri} "
                       f"(last status {resp.status_code})")



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


def passkey_register_and_login(client_id, redirect_uri, email):
    """The passkey half - needs a real browser with a CDP virtual authenticator."""
    record = wait_for_capture(email)
    if record is None:
        raise RuntimeError(f"no captured mail for {email}")
    match = re.search(r"(http://localhost:8080\S+action-token\?key=\S+)", record["body_plain"])
    if not match:
        raise RuntimeError(f"no action-token link in captured mail for {email}")
    action_link = match.group(1).strip()

    captured = {}
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
        if 'type="password"' in page.content():
            raise RuntimeError("password field shown during passkey registration")
        page.locator("#registerWebAuthn").click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # Fresh login. ext-magic-form is the lower-priority alternative, so it
        # renders first; the passkey is reached through "Try another way".
        state = f"oracle-passkey-{email.split('@')[0]}"
        page.goto(auth_url(client_id, redirect_uri, state), wait_until="networkidle")
        if 'type="password"' in page.content():
            raise RuntimeError("password field shown on the login page")

        _reach_passkey_control(page)

        if not page.locator("#authenticateWebAuthnButton").count():
            raise RuntimeError("passkey login control never became reachable")
        page.locator("#authenticateWebAuthnButton").click()
        page.wait_for_timeout(2000)
        browser.close()

    final_url = captured.get("final_url")
    if not final_url:
        raise RuntimeError(f"passkey login for {email} never reached {redirect_uri}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned for {email}: {final_url}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state not preserved for {email}")
    print(f"  {email}: passkey registered and login completed, code+state verified")


def main():
    creds = load_settings(CREDS_PATH)
    base_url = creds["keycloak_base_url"]
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base_url, creds["admin_realm"],
                            creds["admin_username"], creds["admin_password"])

    print("Confirming the keycloak-magic-link extension is installed...")
    require_magic_link_extension(base_url, realm, token)

    print("Setting WebAuthn passwordless policy and realm SMTP...")
    set_webauthn_passwordless_policy(base_url, realm, token)

    print(f"Authoring '{FLOW_ALIAS}' (+ forms sub-flow) with explicit priorities...")
    flow_id = create_flows(base_url, realm, token)

    print("Turning off ext-magic-create-nonexistent-user...")
    disable_create_nonexistent_user(base_url, realm, token)

    print("Binding the flow to the acme-portal client...")
    bind_client_flow(base_url, realm, token, client_id, flow_id)

    print("Driving the magic-link half over plain HTTP...")
    magic_link_login(client_id, redirect_uri, "priya@acme.example")

    print("Bootstrapping a passkey for marcus, then driving the passkey half...")
    user_id = find_user(base_url, realm, token, "marcus")
    send_required_action_email(base_url, realm, token, user_id, client_id, redirect_uri)
    passkey_register_and_login(client_id, redirect_uri, "marcus@acme.example")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ORACLE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
