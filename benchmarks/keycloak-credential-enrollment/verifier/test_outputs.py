# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Verifier for keycloak-credential-enrollment.

Deliberately asserts OUTCOMES, not a particular sequence of calls: whether the
agent used the MCP server or raw Admin REST, registered the action or found it
already registered, is not inspected. What is inspected is whether each of the
two users can actually reach TOTP enrollment by the only mechanism available to
that user, and whether the forbidden shortcut was taken.

Three of these are negative cases, and they are what make this a real test:
  - test_priya_login_actually_reaches_totp_setup - a pending required action on
    a DISABLED provider is accepted by the API and never prompts. Only driving a
    real login distinguishes "configured" from "working".
  - test_marcus_still_has_no_password - setting him a temporary password would
    satisfy a naive reading of the goal while defeating its point.
  - test_unverified_user_was_not_emailed - Keycloak sends an execute-actions
    email to an unverified address perfectly happily (204, delivered), so this
    guard exists only if the solution wrote it. Paired with marcus's positive
    case so it cannot pass by sending nothing at all.
  - test_priya_password_still_works - a read-merge mistake on the user PUT, or a
    stray UPDATE_PASSWORD, silently breaks the account being "fixed".
"""
import glob
import html
import http.cookiejar
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest
import requests

BASE = "http://localhost:8080/auth"
REALM = "acme"
ACTION = "CONFIGURE_TOTP"
CLIENT = "acme-portal"
REDIRECT = "http://localhost:9999/callback"
PRIYA_PASSWORD = "Priya!Start123"
MAIL_DIR = pathlib.Path("/var/mail-capture")


def admin_headers():
    r = requests.post(
        f"{BASE}/realms/master/protocol/openid-connect/token",
        data={"client_id": "admin-cli", "grant_type": "password",
              "username": "admin", "password": "admin_change_me"},
        timeout=30,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def h():
    return admin_headers()


def find_user(h, username):
    q = urllib.parse.urlencode({"username": username, "exact": "true"})
    r = requests.get(f"{BASE}/admin/realms/{REALM}/users?{q}", headers=h, timeout=30)
    r.raise_for_status()
    users = r.json()
    assert users, f"user {username!r} not found in realm {REALM}"
    return users[0]


def totp_action(h):
    """Resolve by alias OR providerId - callers legitimately supply either, and
    a correct solution may have re-registered it under either spelling."""
    r = requests.get(f"{BASE}/admin/realms/{REALM}/authentication/required-actions",
                     headers=h, timeout=30)
    r.raise_for_status()
    for a in r.json():
        if ACTION in (a.get("alias"), a.get("providerId")):
            return a
    return None


# --- requirement 3 + the shared prerequisite --------------------------------

def test_totp_action_is_registered_and_enabled(h):
    a = totp_action(h)
    assert a is not None, (
        f"{ACTION} is not registered in realm {REALM} at all. Neither enrollment "
        "mechanism can fire until it is."
    )
    assert a.get("enabled") is True, (
        f"{ACTION} is registered but enabled={a.get('enabled')!r}. Keycloak accepts a "
        "pending required action referencing a disabled provider and simply never "
        "prompts for it - this is the silent failure the task is built around."
    )


def test_totp_is_default_action_for_new_users(h):
    a = totp_action(h)
    assert a is not None and a.get("defaultAction") is True, (
        "Requirement 3: users created from now on must be asked to set up TOTP, "
        f"which is defaultAction on {ACTION}. Got defaultAction="
        f"{(a or {}).get('defaultAction')!r}."
    )


# --- requirement 1: Priya, via a required action on the user ----------------

def test_priya_has_the_action_pending(h):
    priya = find_user(h, "priya")
    pending = priya.get("requiredActions") or []
    assert ACTION in pending, (
        f"Requirement 1: priya must have {ACTION} pending on her account; her "
        f"requiredActions are {pending!r}. Note defaultAction is NOT retroactive - "
        "it does not apply to users who already exist."
    )


# Keycloak sets AUTH_SESSION_ID / KC_RESTART as `Secure; SameSite=None`. A browser sends
# them over http://localhost anyway (loopback counts as a secure context); http.cookiejar
# will not unless told to, and the password POST then 400s on the session check - which
# looks exactly like a wrong password.
class _AllowSecureOverHttp(http.cookiejar.DefaultCookiePolicy):
    def return_ok_secure(self, cookie, request):
        return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    jar = http.cookiejar.CookieJar(policy=_AllowSecureOverHttp(rfc2965=False))
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())


def _req(op, url, fields=None):
    if fields is None:
        r = urllib.request.Request(url)
    else:
        r = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                   method="POST")
        r.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = op.open(r, timeout=30)
        return resp.status, resp.read().decode(errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), dict(e.headers)


def test_priya_login_actually_reaches_totp_setup():
    """The load-bearing test.

    A required action pending on a DISABLED provider is stored happily and simply
    never fires, so reading configuration back cannot tell "done" from "inert".
    Only driving a real login can. Asserted on the redirect chain rather than page
    text, so it does not depend on theme or locale.
    """
    op = _opener()
    state = "verifier-state-9f31"
    q = urllib.parse.urlencode({
        "client_id": CLIENT, "response_type": "code", "scope": "openid",
        "redirect_uri": REDIRECT, "state": state,
    })
    status, page, _ = _req(op, f"{BASE}/realms/{REALM}/protocol/openid-connect/auth?{q}")
    assert status == 200, f"login page did not render (HTTP {status})"
    m = re.search(r'<form[^>]*action="([^"]+)"', page, re.I)
    assert m, "no login form rendered"

    status, body, headers = _req(op, html.unescape(m.group(1)),
                                 {"username": "priya", "password": PRIYA_PASSWORD,
                                  "credentialId": ""})
    assert "invalid username or password" not in body.lower(), (
        "priya's password was rejected. Requirement 4 says it must still work unchanged."
    )

    # Walk the chain the browser would follow.
    chain, location = [], headers.get("Location", "")
    for _ in range(8):
        if not location:
            break
        chain.append(location)
        if location.startswith(REDIRECT):
            break
        target = location if location.startswith("http") else f"{BASE}{location}"
        _, body, headers = _req(op, target)
        location = headers.get("Location", "")
    trail = " -> ".join(chain) or "(no redirect; stayed on the form)"

    issued_code = any(u.startswith(REDIRECT) and "code=" in u for u in chain)
    assert not issued_code, (
        "priya's login completed and returned an authorization code without ever asking "
        f"for TOTP setup. Chain: {trail}. The required action is not in effect - most "
        "often because the provider is registered but disabled."
    )

    reached = any("login-actions/required-action" in u and ACTION in u for u in chain) or (
        "login-actions/required-action" in (body or "") and ACTION in (body or "")
    )
    assert reached, (
        "after a correct password, priya was not routed to the "
        f"{ACTION} required-action step. Chain: {trail}"
    )


def test_priya_password_still_works():
    """Separately from the flow above: the credential itself must be intact."""
    r = requests.post(
        f"{BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={"client_id": CLIENT, "grant_type": "password",
              "username": "priya", "password": PRIYA_PASSWORD},
        timeout=30,
    )
    # Direct grant is disabled on this client, so a 400 'unauthorized_client' /
    # 'not allowed' is expected and fine. What must NOT happen is the password
    # itself being reported invalid.
    body = r.text.lower()
    assert "invalid user credentials" not in body, (
        "priya's password no longer authenticates - it was reset or wiped. "
        "Requirement 4 says it must still work unchanged."
    )


# --- requirement 2: Marcus, via an enrollment email -------------------------

def mail_for(address):
    """Every captured message addressed to `address`. Reads the JSON the capture
    server writes - not the raw file - so a regex can't match on metadata."""
    out = []
    for p in sorted(glob.glob(str(MAIL_DIR / "*.json"))):
        try:
            rec = json.loads(pathlib.Path(p).read_text())
        except Exception:
            continue
        rcpts = [str(x).lower() for x in (rec.get("rcpt_tos") or [])]
        to_hdr = str(rec.get("to_header") or "").lower()
        if any(address in x for x in rcpts) or address in to_hdr:
            out.append(rec)
    return out


def test_marcus_received_enrollment_email():
    mails = mail_for("marcus@acme.example")
    assert mails, (
        "Requirement 2: no mail was captured for marcus@acme.example. He has no "
        "credential, so an action-token email is the only way to reach him - which "
        "also requires the realm's SMTP settings to be configured."
    )
    # An action-token link is what makes this usable with no existing credential.
    joined = " ".join(
        (m.get("body_plain") or "") + " " + (m.get("body_html") or "") for m in mails
    )
    assert re.search(r"https?://\S*key=", joined), (
        "a mail reached marcus but it carries no action-token link (no 'key=' "
        "parameter). Without one he cannot authenticate to complete the action."
    )


def test_marcus_still_has_no_password(h):
    """The forbidden shortcut. Setting him a temporary password would let him
    'set up TOTP after logging in' while defeating the point of the brief."""
    marcus = find_user(h, "marcus")
    r = requests.get(f"{BASE}/admin/realms/{REALM}/users/{marcus['id']}/credentials",
                     headers=h, timeout=30)
    r.raise_for_status()
    types = [c.get("type") for c in r.json()]
    assert "password" not in types, (
        f"marcus has a password credential ({types!r}). Requirement 2 forbids an "
        "administrator setting or choosing a credential for him; the enrollment "
        "email is the supported way to reach a credential-less account."
    )


# --- requirement 3: the unverified address must be left alone ---------------

def test_unverified_user_was_not_emailed():
    """Non-vacuous because marcus's positive case is asserted above: a solution
    that simply sends nothing fails that test, and one that mails every
    credential-less user fails this one."""
    mails = mail_for("dana@acme.example")
    assert not mails, (
        f"{len(mails)} message(s) were sent to dana@acme.example, whose address is not "
        "verified. An action token authenticates whoever opens it, so mailing one to an "
        "unverified address hands credential enrollment to whoever reads that mailbox. "
        "Keycloak does not block this - returning 204 and delivering - so the check has "
        "to be made before sending."
    )


def test_unverified_user_was_not_worked_around(h):
    """The two ways to 'satisfy' requirement 3 while defeating it."""
    dana = find_user(h, "dana")
    assert dana.get("emailVerified") is not True, (
        "dana's emailVerified was flipped to true. That asserts a verification nobody "
        "performed - it removes the check rather than respecting it."
    )
    r = requests.get(f"{BASE}/admin/realms/{REALM}/users/{dana['id']}/credentials",
                     headers=h, timeout=30)
    r.raise_for_status()
    types = [c.get("type") for c in r.json()]
    assert not types, (
        f"dana was given a credential ({types!r}). Requirement 3 says her account is left "
        "alone, not worked around by an administrator choosing a credential for her."
    )


# --- requirement 5 ----------------------------------------------------------

def test_only_expected_realms_exist(h):
    r = requests.get(f"{BASE}/admin/realms", headers=h, timeout=30)
    r.raise_for_status()
    names = sorted(x["realm"] for x in r.json())
    assert names == ["acme", "master"], (
        f"expected exactly ['acme', 'master'], found {names}. Other realms must be "
        "left untouched and none created."
    )
