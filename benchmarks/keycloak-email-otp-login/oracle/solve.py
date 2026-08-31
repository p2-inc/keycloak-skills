#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: passwordless login by an emailed one-time code.

Four steps, all against the Admin REST API, then a self-check that drives real logins.

  1. Realm SMTP settings, pointed at the local capture server. Unconfigured by
     default; without them the OTP send fails silently (the authenticator catches
     its own EmailException), so nothing is delivered and nothing surfaces as an error.

  2. Author an "email-otp-flow". Unlike magic-link - where the provider auto-creates
     a `magic link` flow on every realm - NOTHING auto-creates an email-OTP flow, so
     one has to be built. Shape:

         email-otp-flow (top level, basic-flow)
           auth-cookie                    ALTERNATIVE
           identity-provider-redirector   ALTERNATIVE
           Email OTP forms (sub-flow)     ALTERNATIVE
             ext-auth-username-auth-note  REQUIRED
             ext-email-otp                REQUIRED  (config: no user auto-create)

     Two things about that sub-flow are load-bearing:

     (a) ORDER. `ext-email-otp` reads the *attempted username* off the auth session
         (MagicLink.getAttemptedUsername) rather than collecting an address itself,
         so an identifier step must run first or there is no address to mail.

     (b) WHICH identifier authenticator. `ext-auth-username-auth-note`, NOT stock
         `auth-username-form`. Verified empirically against a live Keycloak: with
         `auth-username-form`, an unregistered address is rejected with "Invalid
         username or email." *before* ext-email-otp ever runs - a real account-
         enumeration leak, independent of ext-email-otp's own config. With
         `ext-auth-username-auth-note` the identifier is set without an existence
         check, control reaches ext-email-otp, and its own null-user handling is
         anti-enumeration-safe: identical code form, no mail, no error.

  3. Attach `ext-magic-create-nonexistent-user=false` to the ext-email-otp step.
     This is that authenticator's only config property, and it shares the key name
     with magic-link because the extension uses one constant for both. Note the
     runtime default here is already false (unlike ext-magic-form's true), so this
     is belt-and-braces rather than a fix - but it is what keeps requirement 3's
     "no new account" half true.

  4. Bind the flow as the realm's browserFlow.

  Self-check drives two real logins:
    - priya@acme-internal.example  -> code form, mail sent, code completes login
    - an unregistered address      -> SAME code form, and NO mail sent
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
KNOWN_EMAIL = "priya@acme-internal.example"
UNKNOWN_EMAIL = "oracle-ghost@acme-internal.example"
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
    # Order matters here - see the module docstring, point (a).
    for provider in ("ext-auth-username-auth-note", "ext-email-otp"):
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
        "ext-auth-username-auth-note": "REQUIRED",
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


def submit_identifier(base, realm, client_id, redirect_uri, email, state):
    """Returns (opener, html, page_id) after submitting the identifier."""
    opener = new_session()
    _, html, _ = http_get(opener, authorization_url(base, realm, client_id, redirect_uri, state))
    status, html, headers = http_post(opener, form_action(html), {"username": email})
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
    # --- registered address: no password prompt, mail out, code completes login ---
    since = time.time()
    state = "oracle-known"
    opener, html, pid = submit_identifier(base, realm, client_id, redirect_uri, KNOWN_EMAIL, state)
    if pid != "login-otp-form":
        raise RuntimeError(f"expected the OTP form for {KNOWN_EMAIL}, got page_id={pid!r}")
    if re.search(r'type="password"', html or "", re.I):
        raise RuntimeError("a password field appeared - this flow must never ask for one")

    record = None
    for _ in range(12):
        record = latest_capture_for(KNOWN_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    if record is None:
        raise RuntimeError(f"no mail captured for {KNOWN_EMAIL}; SMTP is likely misconfigured")

    code = extract_code(record)

    status, html, headers = http_post(opener, form_action(html), {"otp": code})
    location = follow_to_redirect_uri(
        opener, base, headers.get("Location", ""), redirect_uri
    )
    if not location.startswith(redirect_uri):
        raise RuntimeError(f"the code did not complete login; ended at {location[:200]!r}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned: {location[:200]}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state was not preserved: {query.get('state')}")

    # --- unregistered address: identical page, no mail, no account ---
    since2 = time.time()
    _, _, pid2 = submit_identifier(
        base, realm, client_id, redirect_uri, UNKNOWN_EMAIL, "oracle-unknown"
    )
    if pid2 != "login-otp-form":
        raise RuntimeError(
            f"unregistered address got page_id={pid2!r} instead of the same OTP form - "
            "this leaks which addresses have accounts"
        )
    time.sleep(1.5)
    if latest_capture_for(UNKNOWN_EMAIL, since2) is not None:
        raise RuntimeError(f"mail was sent for the unregistered address {UNKNOWN_EMAIL}")

    print(
        "oracle self-check passed: registered address logged in by emailed code with no password "
        "prompt; unregistered address got the identical form with no mail"
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
