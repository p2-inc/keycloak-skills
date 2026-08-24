#!/usr/bin/env python3
"""Human-written oracle: turns on passkey-only passwordless login for the acme realm.

Four pieces, all through the Admin REST API:

  1. The realm's WebAuthn PASSWORDLESS policy (a separate policy block from
     the ordinary 2FA WebAuthn policy) - rpId must match the hostname the
     browser actually navigates to (here, "localhost"), or the ceremony fails
     client-side with no useful server error.

  2. A brand-new top-level "Passkey Only" flow. Unlike magic-link, Keycloak
     ships NO built-in flow containing the WebAuthn passwordless step - it
     has to be authored:

         Passkey Only                              (top level, all ALTERNATIVE)
         |-- auth-cookie                            ALTERNATIVE
         `-- Passkey Only forms                     ALTERNATIVE  (sub-flow)
             `-- webauthn-authenticator-passwordless REQUIRED

     The sub-flow is load-bearing. Keycloak discards a level's ALTERNATIVE
     bucket entirely when that level also holds a REQUIRED execution, so
     auth-cookie ALTERNATIVE beside the passkey step REQUIRED would mean
     auth-cookie never runs - SSO resume silently dead, full WebAuthn ceremony
     on every request. Wrapping the passkey step keeps the top level
     bucket-pure. REQUIRED and alone inside the sub-flow is what makes this
     "no password, ever", not just "password deprioritized".

  3. Binding that flow to the acme-portal client (client-level, not
     realm-wide, so other realm clients like the admin/account consoles keep
     their normal password login).

  4. Getting each credential-less user a registered passkey WITHOUT a
     password: realm SMTP settings (same dependency as magic-link) plus
     execute-actions-email with the webauthn-register-passwordless required
     action - an action-token-authenticated link, the same mechanism
     magic-link itself uses, needing no prior credential at all.

Finishes by driving the whole thing the way the verifier does: register a
passkey via a real WebAuthn ceremony (a headless browser with a CDP virtual
authenticator - the crypto exchange can't be faked with a curl call), then a
fresh login with that passkey, confirming a real authorization code and
unchanged state.
"""

import json
import pathlib
import re
import sys
import urllib.parse

import requests
from playwright.sync_api import sync_playwright

CREDS_PATH = "/root/admin_credentials.txt"
FLOW_ALIAS = "Passkey Only"
FORMS_ALIAS = "Passkey Only forms"
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


def get_admin_token(base_url, admin_realm, username, password):
    resp = requests.post(
        f"{base_url}/realms/{admin_realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def set_webauthn_passwordless_policy(base_url, realm, token):
    rep = requests.get(f"{base_url}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    rep["webAuthnPolicyPasswordlessRpEntityName"] = "Acme Portal"
    rep["webAuthnPolicyPasswordlessRpId"] = "localhost"
    rep["webAuthnPolicyPasswordlessRequireResidentKey"] = "Yes"
    rep["webAuthnPolicyPasswordlessUserVerificationRequirement"] = "preferred"
    resp = requests.put(f"{base_url}/admin/realms/{realm}", headers=auth(token), json=rep, timeout=TIMEOUT)
    resp.raise_for_status()


def set_smtp_settings(base_url, realm, token):
    rep = requests.get(f"{base_url}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT).json()
    rep["smtpServer"] = {
        "host": "localhost", "port": "1025", "from": "no-reply@acme.example",
        "auth": "false", "starttls": "false", "ssl": "false",
    }
    resp = requests.put(f"{base_url}/admin/realms/{realm}", headers=auth(token), json=rep, timeout=TIMEOUT)
    resp.raise_for_status()


def _set_requirements(base_url, realm, token, flow_alias, wanted_by_key):
    """Set requirements on one flow's direct children, preserving each one's priority."""
    executions = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(flow_alias)}/executions",
        headers=auth(token), timeout=TIMEOUT,
    ).json()
    for exe in executions:
        if exe.get("level", 0) != 0:
            continue
        key = exe.get("providerId") or exe.get("displayName")
        wanted = wanted_by_key.get(key)
        if not wanted or exe.get("requirement") == wanted:
            continue
        body = {"id": exe["id"], "requirement": wanted}
        if isinstance(exe.get("priority"), int):
            body["priority"] = exe["priority"]
        resp = requests.put(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(flow_alias)}/executions",
            headers=auth(token), json=body, timeout=TIMEOUT,
        )
        resp.raise_for_status()


def create_passkey_only_flow(base_url, realm, token):
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication/flows", headers=auth(token),
        json={"alias": FLOW_ALIAS, "providerId": "basic-flow", "topLevel": True, "builtIn": False},
        timeout=TIMEOUT,
    )
    if resp.status_code not in (201, 409):
        resp.raise_for_status()

    # Keycloak's add-execution-by-provider endpoint does NOT dedupe - POSTing
    # the same provider twice appends a second execution rather than 409ing.
    # The flow may already have both executions (e.g. pre-authored via realm
    # import), so check what's actually there before adding anything.
    executions = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW_ALIAS)}/executions",
        headers=auth(token), timeout=TIMEOUT,
    ).json()
    existing = {exe.get("providerId") or exe.get("displayName") for exe in executions}

    # auth-cookie sits at the top level; the passkey step goes in its own sub-flow.
    #
    # The sub-flow is NOT cosmetic. Keycloak buckets a level's children into required
    # (REQUIRED + CONDITIONAL) and alternative (ALTERNATIVE), and if BOTH buckets are
    # non-empty it discards the alternative one outright:
    #
    #   DefaultAuthenticationFlow.fillListsOfExecutions:
    #     if (!requiredList.isEmpty() && !alternativeList.isEmpty()) { ... alternativeList.clear(); }
    #
    # So a bare top-level flow holding auth-cookie ALTERNATIVE beside
    # webauthn-authenticator-passwordless REQUIRED silently never runs auth-cookie:
    # SSO session resume is dead and every authorization request re-runs the full
    # WebAuthn ceremony. Only a server-log WARN reports it. Wrapping the passkey step
    # keeps the top level all-ALTERNATIVE, which is what makes the cookie branch live.
    if "auth-cookie" not in existing:
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW_ALIAS)}/executions/execution",
            headers=auth(token), json={"provider": "auth-cookie", "priority": 0}, timeout=TIMEOUT,
        )
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    if FORMS_ALIAS not in existing:
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW_ALIAS)}/executions/flow",
            headers=auth(token),
            json={"alias": FORMS_ALIAS, "provider": "basic-flow", "type": "basic-flow", "priority": 1},
            timeout=TIMEOUT,
        )
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    sub_executions = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FORMS_ALIAS)}/executions",
        headers=auth(token), timeout=TIMEOUT,
    ).json()
    if "webauthn-authenticator-passwordless" not in {e.get("providerId") for e in sub_executions}:
        resp = requests.post(
            f"{base_url}/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FORMS_ALIAS)}/executions/execution",
            headers=auth(token),
            json={"provider": "webauthn-authenticator-passwordless", "priority": 0}, timeout=TIMEOUT,
        )
        if resp.status_code not in (201, 409):
            resp.raise_for_status()

    # Top level: auth-cookie and the sub-flow are BOTH ALTERNATIVE (bucket-pure).
    # Inside the sub-flow: the passkey step is REQUIRED and alone, so it is the only
    # way through that branch - which is what makes this "no password, ever".
    #
    # Keycloak's update endpoint takes the whole execution representation and priority
    # is a primitive int on it, so a body omitting priority resets it to 0. Send the
    # execution's current priority back with the requirement.
    _set_requirements(base_url, realm, token, FLOW_ALIAS, {
        "auth-cookie": "ALTERNATIVE",
        FORMS_ALIAS: "ALTERNATIVE",
    })
    _set_requirements(base_url, realm, token, FORMS_ALIAS, {
        "webauthn-authenticator-passwordless": "REQUIRED",
    })

    return next(f["id"] for f in requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows", headers=auth(token), timeout=TIMEOUT
    ).json() if f["alias"] == FLOW_ALIAS)


def bind_client_flow(base_url, realm, token, client_id, flow_id):
    client = requests.get(
        f"{base_url}/admin/realms/{realm}/clients?clientId={client_id}", headers=auth(token), timeout=TIMEOUT
    ).json()[0]
    client["authenticationFlowBindingOverrides"] = {"browser": flow_id}
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}/clients/{client['id']}", headers=auth(token), json=client, timeout=TIMEOUT
    )
    resp.raise_for_status()


def find_user(base_url, realm, token, username):
    matches = requests.get(
        f"{base_url}/admin/realms/{realm}/users?username={username}&exact=true",
        headers=auth(token), timeout=TIMEOUT,
    ).json()
    if not matches:
        raise RuntimeError(f"user {username} not found")
    return matches[0]["id"]


def send_required_action_email(base_url, realm, token, user_id, client_id, redirect_uri):
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}/users/{user_id}/execute-actions-email"
        f"?client_id={client_id}&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}",
        headers=auth(token), json=["webauthn-register-passwordless"], timeout=TIMEOUT,
    )
    resp.raise_for_status()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def wait_for_capture(email_marker, attempts=10, delay=0.5):
    import time
    marker = email_marker.replace("@", "-at-")
    for _ in range(attempts):
        files = sorted(
            pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if files:
            return json.loads(files[0].read_text())
        time.sleep(delay)
    return None


def register_and_login(client_id, redirect_uri, email):
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

        # Registration ceremony.
        page.goto(action_link, wait_until="networkidle")
        page.locator("a:has-text('Click here to proceed')").first.click()
        page.wait_for_load_state("networkidle")
        registration_body = page.inner_text("body")
        if 'type="password"' in page.content():
            raise RuntimeError("password field shown during passkey registration")
        page.locator("#registerWebAuthn").click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle")

        # Fresh authorization-code login, same browser context/authenticator.
        state = f"oracle-verify-{email.split('@')[0]}"
        auth_url = (f"http://localhost:8080/auth/realms/acme/protocol/openid-connect/auth?"
                    + urllib.parse.urlencode({
                        "client_id": client_id, "redirect_uri": redirect_uri,
                        "response_type": "code", "scope": "openid", "state": state,
                    }))
        page.goto(auth_url, wait_until="networkidle")
        if 'type="password"' in page.content():
            raise RuntimeError("password field shown during passkey login")
        page.locator("#authenticateWebAuthnButton").click()
        page.wait_for_timeout(2000)

        browser.close()

    final_url = captured.get("final_url")
    if not final_url:
        raise RuntimeError(f"login for {email} never reached {redirect_uri}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned for {email}: {final_url}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state not preserved for {email}: sent {state!r}, got {query.get('state')!r}")
    print(f"  {email}: passkey registered and login completed, code+state verified")


def main():
    creds = load_settings(CREDS_PATH)
    base_url = creds["keycloak_base_url"]
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base_url, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print("Setting WebAuthn passwordless policy...")
    set_webauthn_passwordless_policy(base_url, realm, token)

    print("Setting SMTP settings...")
    set_smtp_settings(base_url, realm, token)

    print("Creating and binding 'Passkey Only' flow...")
    flow_id = create_passkey_only_flow(base_url, realm, token)
    bind_client_flow(base_url, realm, token, client_id, flow_id)

    for username, email in (("priya", "priya@acme.example"), ("marcus", "marcus@acme.example")):
        print(f"Bootstrapping passkey for {username}...")
        user_id = find_user(base_url, realm, token, username)
        send_required_action_email(base_url, realm, token, user_id, client_id, redirect_uri)

    print("Driving real WebAuthn ceremonies (registration + login)...")
    for email in ("priya@acme.example", "marcus@acme.example"):
        register_and_login(client_id, redirect_uri, email)

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ORACLE FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
