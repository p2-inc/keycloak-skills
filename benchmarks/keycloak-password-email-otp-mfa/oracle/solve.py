#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: password login with an emailed one-time code as a SECOND factor.

Same extension as the passwordless email-OTP task, but a deliberately different first
step - and that single substitution is the whole point of this task.

  1. Realm SMTP settings, pointed at the local capture server (unconfigured by default;
     a failed send is swallowed internally, so nothing surfaces as an error).

  2. Author an "email-otp-flow":

         email-otp-flow (top level, basic-flow)
           auth-cookie                    ALTERNATIVE
           identity-provider-redirector   ALTERNATIVE
           Email OTP forms (sub-flow)     ALTERNATIVE
             auth-username-password-form  REQUIRED   <-- the gate (stock Keycloak)
             ext-email-otp                REQUIRED   (config: no user auto-create)

     `auth-username-password-form` is the RIGHT choice here and the WRONG choice in the
     passwordless task next door. Here it validates the password before anything else
     runs, so the emailed code is only ever issued to someone who already proved the
     password. Substituting an identifier-only step (as the passwordless flow correctly
     uses) would still log a real user in with a code, while silently making the password
     irrelevant - anyone knowing the address would receive a code.

  3. Attach `ext-magic-create-nonexistent-user=false` to the ext-email-otp step (its only
     config property; the key name is shared with magic-link because the extension uses a
     single constant for both).

  4. Bind the flow as the realm's browserFlow.

  Self-check drives three real logins, verified against a live Keycloak:
    - priya + CORRECT password -> code form, mail sent, code completes login
    - priya + WRONG password   -> rejected at the password step, NO mail sent at all
    - unknown username         -> same generic rejection, NO mail sent
  The wrong-password case is what actually proves this is two-factor rather than
  email-OTP with a decorative password field.
"""


import glob
import http.cookiejar
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CREDS_PATH = "/root/admin_credentials.txt"
CAPTURE_DIR = "/var/mail-capture"
FLOW = "email-otp-flow"
SUBFLOW = "Email OTP forms"
USERNAME = "priya"
USER_EMAIL = "priya@acme-internal.example"
CORRECT_PASSWORD = "Priya!Pass1"
WRONG_PASSWORD = "definitely-not-the-password"
UNKNOWN_USERNAME = "oracle-ghost"
TIMEOUT = 30


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


# --- admin REST helpers -----------------------------------------------------


def admin_request(base, token, method, path, payload=None, expect=(200, 201, 204)):
    url = f"{base}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode()
            if r.status not in expect:
                raise RuntimeError(f"{method} {path} -> {r.status}: {body[:300]}")
            return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code not in expect:
            raise RuntimeError(f"{method} {path} -> {e.code}: {body[:300]}")
        return e.code, body


def get_admin_token(base, realm, user, password):
    data = urllib.parse.urlencode(
        {"grant_type": "password", "client_id": "admin-cli", "username": user, "password": password}
    ).encode()
    req = urllib.request.Request(
        f"{base}/realms/{realm}/protocol/openid-connect/token", data=data, method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())["access_token"]


def configure_smtp(base, token, realm):
    _, body = admin_request(base, token, "GET", f"/admin/realms/{realm}")
    rep = json.loads(body)
    rep["smtpServer"] = {
        "host": "localhost",
        "port": "1025",
        "from": "noreply@acme.example",
        "auth": "false",
        "ssl": "false",
        "starttls": "false",
    }
    admin_request(base, token, "PUT", f"/admin/realms/{realm}", rep)


def author_flow(base, token, realm):
    admin_request(
        base, token, "POST", f"/admin/realms/{realm}/authentication/flows",
        {"alias": FLOW, "providerId": "basic-flow", "topLevel": True, "builtIn": False},
    )
    admin_request(
        base, token, "POST",
        f"/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW)}/executions/flow",
        {"alias": SUBFLOW, "provider": "basic-flow", "type": "basic-flow"},
    )
    for provider in ("auth-cookie", "identity-provider-redirector"):
        admin_request(
            base, token, "POST",
            f"/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW)}/executions/execution",
            {"provider": provider},
        )
    # The password form must come FIRST - it is the gate. See the module docstring.
    for provider in ("auth-username-password-form", "ext-email-otp"):
        admin_request(
            base, token, "POST",
            f"/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(SUBFLOW)}/executions/execution",
            {"provider": provider},
        )

    _, body = admin_request(
        base, token, "GET",
        f"/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW)}/executions",
    )
    executions = json.loads(body)
    wanted = {
        SUBFLOW: "ALTERNATIVE",
        "auth-cookie": "ALTERNATIVE",
        "identity-provider-redirector": "ALTERNATIVE",
        "auth-username-password-form": "REQUIRED",
        "ext-email-otp": "REQUIRED",
    }
    otp_execution_id = None
    for execution in executions:
        key = execution.get("providerId") or execution.get("displayName")
        if key == "ext-email-otp":
            otp_execution_id = execution["id"]
        requirement = wanted.get(key)
        if requirement and execution.get("requirement") != requirement:
            admin_request(
                base, token, "PUT",
                f"/admin/realms/{realm}/authentication/flows/{urllib.parse.quote(FLOW)}/executions",
                {"id": execution["id"], "requirement": requirement},
            )
    if otp_execution_id is None:
        raise RuntimeError("ext-email-otp execution not found after authoring the flow")

    admin_request(
        base, token, "POST",
        f"/admin/realms/{realm}/authentication/executions/{otp_execution_id}/config",
        {"alias": "email-otp-config", "config": {"ext-magic-create-nonexistent-user": "false"}},
    )


def bind_flow(base, token, realm):
    _, body = admin_request(base, token, "GET", f"/admin/realms/{realm}")
    rep = json.loads(body)
    rep["browserFlow"] = FLOW
    admin_request(base, token, "PUT", f"/admin/realms/{realm}", rep)


# --- driving real logins ---------------------------------------------------
#
# Keycloak marks AUTH_SESSION_ID / KC_RESTART as `Secure; SameSite=None`. A browser
# sends them over http://localhost anyway (loopback counts as a secure context);
# http.cookiejar will NOT unless told to, and the very first POST then 400s on the
# CSRF/session check. Hence the policy override below.


class _AllowSecureOverHttp(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def new_session():
    jar = http.cookiejar.CookieJar(policy=_AllowSecureOverHttp(rfc2965=False))
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())


def http_get(opener, url):
    try:
        r = opener.open(urllib.request.Request(url), timeout=TIMEOUT)
        return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def http_post(opener, url, fields):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        r = opener.open(req, timeout=TIMEOUT)
        return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


def page_id(html):
    m = re.search(r'data-page-id="([^"]+)"', html or "")
    return m.group(1) if m else None


def form_action(html):
    m = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    if not m:
        raise RuntimeError("no form on the page")
    return m.group(1).replace("&amp;", "&")


def latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    for path in sorted(pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*")) [::-1]:
        stamp = re.match(r"(\d+)-", path.name)
        if stamp and int(stamp.group(1)) >= int(since * 1000):
            return path
    return None


def authorization_url(base, realm, client_id, redirect_uri, state):
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{base}/realms/{realm}/protocol/openid-connect/auth?{params}"


def submit_credentials(base, realm, client_id, redirect_uri, username, password, state):
    """Submits Keycloak's combined username+password form. Returns (opener, html, page_id)."""
    opener = new_session()
    _, html, _ = http_get(opener, authorization_url(base, realm, client_id, redirect_uri, state))
    status, html, headers = http_post(
        opener, form_action(html), {"username": username, "password": password}
    )
    if status in (302, 303):
        location = headers.get("Location", "")
        # Redirect straight to the app = login already complete; do not follow it (nothing
        # listens on the callback inside the sandbox, which surfaces as Connection refused).
        if location.startswith(redirect_uri):
            return opener, html, "COMPLETED_WITHOUT_FURTHER_STEPS"
        _, html, _ = http_get(opener, location)
    return opener, html, page_id(html)


def follow_to_redirect_uri(opener, base, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location or location.startswith(redirect_uri):
            return location
        target = location if location.startswith("http") else f"{base}{location}"
        _, _, headers = http_get(opener, target)
        location = headers.get("Location", "")
    return location


def extract_code(record_path):
    """Pull the one-time code out of a captured message.

    The capture server writes one JSON document per message (not a raw .eml), and that
    JSON carries a float `received_at` whose fractional part is six digits - so a naive
    \\b\\d{6}\\b over the whole file happily returns the timestamp instead of the code.
    Parse the JSON and read only the body fields.
    """
    raw = record_path.read_text()
    try:
        record = json.loads(raw)
        body = record.get("body_plain") or record.get("body_html") or ""
    except json.JSONDecodeError:
        body = raw  # raw-RFC822 fallback
    match = re.search(r"Code:\s*(\d{4,10})", body) or re.search(r"\b(\d{6})\b", body)
    if not match:
        raise RuntimeError(f"no one-time code found in captured mail body: {body[:300]}")
    return match.group(1)


def self_check(base, realm, client_id, redirect_uri):
    # --- correct password: reaches the code step, mail out, code completes login ---
    since = time.time()
    state = "oracle-correct-pw"
    opener, html, pid = submit_credentials(
        base, realm, client_id, redirect_uri, USERNAME, CORRECT_PASSWORD, state
    )
    if pid != "login-otp-form":
        raise RuntimeError(
            f"a correct password should have reached the OTP form, got page_id={pid!r}"
        )

    record = None
    for _ in range(12):
        record = latest_capture_for(USER_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    if record is None:
        raise RuntimeError(f"no mail captured for {USER_EMAIL}; SMTP is likely misconfigured")

    code = extract_code(record)

    status, html, headers = http_post(opener, form_action(html), {"otp": code})
    location = follow_to_redirect_uri(opener, base, headers.get("Location", ""), redirect_uri)
    if not location.startswith(redirect_uri):
        raise RuntimeError(f"the code did not complete login; ended at {location[:200]!r}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned: {location[:200]}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state was not preserved: {query.get('state')}")

    # --- WRONG password: must be rejected BEFORE any code is sent ---
    since2 = time.time()
    _, _, pid2 = submit_credentials(
        base, realm, client_id, redirect_uri, USERNAME, WRONG_PASSWORD, "oracle-wrong-pw"
    )
    if pid2 == "login-otp-form":
        raise RuntimeError(
            "a WRONG password reached the OTP form - the password is not gating the code, "
            "so knowing the address alone is enough to be emailed one"
        )
    time.sleep(1.5)
    if latest_capture_for(USER_EMAIL, since2) is not None:
        raise RuntimeError(
            "mail was sent despite a wrong password - the password must gate the send"
        )

    # --- unknown username: same treatment, no mail ---
    since3 = time.time()
    _, _, pid3 = submit_credentials(
        base, realm, client_id, redirect_uri, UNKNOWN_USERNAME, WRONG_PASSWORD, "oracle-unknown"
    )
    if pid3 == "login-otp-form":
        raise RuntimeError(f"unknown username {UNKNOWN_USERNAME!r} reached the OTP form")
    time.sleep(1.0)
    if latest_capture_for(f"{UNKNOWN_USERNAME}@acme-internal.example", since3) is not None:
        raise RuntimeError("mail was sent for an unknown username")

    print(
        "oracle self-check passed: correct password -> emailed code -> login completed; "
        "wrong password and unknown user both rejected with no mail sent"
    )


def main():
    creds = load_settings(CREDS_PATH)
    base = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print("Configuring realm SMTP settings (local capture server)...")
    configure_smtp(base, token, realm)

    print(f"Authoring {FLOW!r} (identifier step -> ext-email-otp)...")
    author_flow(base, token, realm)

    print(f"Binding {FLOW!r} as the realm's browser flow...")
    bind_flow(base, token, realm)

    print("Driving logins...")
    self_check(base, realm, client_id, redirect_uri)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"oracle failed: {exc}", file=sys.stderr)
        sys.exit(1)
