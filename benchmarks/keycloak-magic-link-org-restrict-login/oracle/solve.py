#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: magic-link login restricted to one organization's members.

Combines two mechanisms that are each documented separately elsewhere in this repo
(admin-passwordless-magic-link.md and admin-org-restrict-login.md), via a single custom
flow, all through the real p2-inc keycloak-orgs and keycloak-magic-link extensions:

  1. Create an organization ("engineering") via POST .../orgs. The name has to be
     exactly "engineering" because that's the literal account_hint value the
     application in this task sends - only match_by_org_name=true can work here,
     since the application never learns or sends a server-generated organization id.
  2. Add `priya` as a member via PUT .../orgs/{orgId}/members/{userId}. `morgan` is
     deliberately left NOT a member - the negative case below depends on that.
  3. Realm SMTP settings, pointed at the local mail-capture server. Unconfigured by
     default; without them the magic-link send silently fails.
  4. Author "Select organization magic link" AND bind it as the realm's browser flow,
     in ONE atomic call, via the p2-inc keycloak-atomic-auth-flows extension
     (POST /admin/realms/{realm}/authentication-flow/import). Keycloak's own
     partialImport endpoint cannot do this: it has no handler for authentication
     flows, so an authenticationFlows array sent to it is silently ignored (200 OK,
     added: 0, nothing created).

     The flow's forms sub-flow, in REQUIRED order, is load-bearing:
       ext-auth-username-auth-note (setUserInContext=true)
         -> ext-select-org (match_by_org_name=true)
         -> ext-magic-form (ext-magic-create-nonexistent-user=false)
     Collecting the identifier and setting it in context BEFORE the org check runs
     is what lets the org check run BEFORE any mail is sent - putting ext-magic-form
     first would send mail regardless of membership.

  5. Drive three real logins and confirm, against the actual behavior of these two
     extensions together (verified empirically, not assumed):
       - priya + account_hint=engineering (her own org)         -> a single POST of
         her email reaches the built-in "check your email" page (login-view-email)
         in the SAME response - no separate org-check redirect step. Mail is sent;
         opening its action-token link completes login with an authorization code.
       - morgan + account_hint=engineering (not a member)        -> the SAME POST
         instead reaches Keycloak's generic error page (login-error, "We are
         sorry...") - ext-select-org fails closed before ext-magic-form ever runs,
         so NO mail is sent at all. This is the proof that non-members never even
         receive a link, not merely that their link doesn't work.
       - priya + an account_hint matching no real organization    -> same
         login-error rejection, even for a genuine member - proving the gate checks
         real membership in the HINTED organization, not just "is a member of
         something" or "some account_hint was present".
"""

import json
import pathlib
import re
import sys
import time
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
FLOW_ASSET_PATH = pathlib.Path(__file__).parent / "select-organization-magic-link.partial-import.json"
ORG_NAME = "engineering"
FLOW_ALIAS = "Select organization magic link"
CAPTURE_DIR = "/var/mail-capture"
MEMBER_USERNAME = "priya"
MEMBER_EMAIL = "priya@acme-internal.example"
NONMEMBER_USERNAME = "morgan"
NONMEMBER_EMAIL = "morgan@acme-internal.example"
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


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_organization(base_url, realm, token, name):
    resp = requests.post(
        f"{base_url}/realms/{realm}/orgs", headers=auth(token), json={"name": name}, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    location = resp.headers.get("Location", "")
    org_id = location.rstrip("/").rsplit("/", 1)[-1] if location else None
    if not org_id:
        listing = requests.get(f"{base_url}/realms/{realm}/orgs", headers=auth(token), timeout=TIMEOUT)
        listing.raise_for_status()
        matches = [o for o in listing.json() if o.get("name") == name]
        if len(matches) != 1:
            raise RuntimeError(f"expected one {name!r} organization, found {len(matches)}")
        org_id = matches[0]["id"]
    return org_id


def find_user_id(base_url, realm, token, username):
    resp = requests.get(
        f"{base_url}/admin/realms/{realm}/users?username={username}&exact=true",
        headers=auth(token), timeout=TIMEOUT,
    )
    resp.raise_for_status()
    matches = resp.json()
    if not matches:
        raise RuntimeError(f"user {username} not found")
    return matches[0]["id"]


def add_member(base_url, realm, token, org_id, user_id):
    resp = requests.put(
        f"{base_url}/realms/{realm}/orgs/{org_id}/members/{user_id}", headers=auth(token), timeout=TIMEOUT,
    )
    if resp.status_code not in (201, 204):
        resp.raise_for_status()
    check = requests.get(
        f"{base_url}/realms/{realm}/orgs/{org_id}/members/{user_id}", headers=auth(token), timeout=TIMEOUT,
    )
    if check.status_code != 204:
        raise RuntimeError(f"membership for {user_id} in org {org_id} did not stick")


def configure_smtp(base_url, realm, token):
    """Point outgoing mail at the local capture server - same trap as plain
    magic-link: a realm ships with no SMTP settings, and the send call catches its
    own failure internally, so a missing configuration fails silently."""
    current = requests.get(f"{base_url}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT)
    current.raise_for_status()
    representation = current.json()
    representation["smtpServer"] = {
        "host": "localhost", "port": "1025", "from": "noreply@acme.example",
        "auth": "false", "ssl": "false", "starttls": "false",
    }
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}", headers=auth(token), json=representation, timeout=TIMEOUT,
    )
    resp.raise_for_status()


def import_and_bind_flow(base_url, realm, token):
    """Author "Select organization magic link" AND bind it, in one atomic call, via
    the p2-inc keycloak-atomic-auth-flows extension. See module docstring for why
    Keycloak's own partialImport endpoint cannot do this instead.

    The extension prefixes every alias with a hash of the payload's configs, so the
    flow that actually gets created is NOT named what the asset says - the binding is
    applied by the extension itself (browserFlowBinding below), so the real name only
    has to be read back for confirmation, not reconstructed.
    """
    asset = json.loads(FLOW_ASSET_PATH.read_text())
    payload = {
        "authenticationFlows": asset["authenticationFlows"],
        "authenticatorConfig": asset["authenticatorConfig"],
        "browserFlowBinding": FLOW_ALIAS,
    }
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication-flow/import",
        headers=auth(token), json=payload, timeout=TIMEOUT,
    )
    if resp.status_code == 404:
        raise RuntimeError(
            "the keycloak-atomic-auth-flows extension is not installed on this Keycloak "
            "(404 from /authentication-flow/import) - flow authoring is not possible"
        )
    resp.raise_for_status()

    bound = requests.get(
        f"{base_url}/admin/realms/{realm}", headers=auth(token), timeout=TIMEOUT
    ).json().get("browserFlow")
    if not bound or bound == "browser":
        raise RuntimeError(f"browserFlow was not bound to the imported flow (got {bound!r})")
    return bound


# --- driving real logins, headlessly over plain HTTP ------------------------


def _relax_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    if not match:
        raise RuntimeError("no login form on the page")
    return match.group(1).replace("&amp;", "&")


def _page_id(html):
    match = re.search(r'data-page-id="([^"]+)"', html or "")
    return match.group(1) if match else None


def _authorization_url(base_url, realm, client_id, redirect_uri, state, account_hint):
    params = {
        "client_id": client_id, "response_type": "code", "scope": "openid",
        "redirect_uri": redirect_uri, "state": state, "account_hint": account_hint,
    }
    return f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    matches = sorted(pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*.json"))
    for path in reversed(matches):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _follow_to_redirect_uri(session, base_url, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location or location.startswith(redirect_uri):
            return location
        target = location if location.startswith("http") else f"{base_url}{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    return location


def attempt_login(base_url, realm, client_id, redirect_uri, email, account_hint, state):
    """Submits the identifier on the flow's single username-collection step
    (ext-auth-username-auth-note), then - within the SAME response, empirically
    confirmed, no separate redirect for the org check - lands on one of two pages:

      - "login-view-email" (Keycloak's stock magic-link "check your email" page):
        the org check passed, and ext-magic-form has queued the send. Returns
        ("mail-sent", session) so the caller can wait for the capture and open it.
      - "login-error" ("We are sorry..."): ext-select-org rejected before
        ext-magic-form ever ran. Returns ("rejected", None) - no mail was sent, not
        merely that the account_hint check happens later.

    Any other outcome (a 500, an unexpected page) raises, since neither is a
    documented behavior of this flow.
    """
    session = requests.Session()
    page = session.get(
        _authorization_url(base_url, realm, client_id, redirect_uri, state, account_hint), timeout=TIMEOUT,
    )
    _relax_cookies(session)

    action = _form_action(page.text)
    resp = session.post(action, data={"username": email}, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)

    if resp.status_code in (302, 303):
        # A cookie/IdP alternative could in principle skip straight through; not
        # exercised by this task's fixture (no existing SSO session, no IdP).
        location = _follow_to_redirect_uri(session, base_url, resp.headers.get("Location", ""), redirect_uri)
        if location.startswith(redirect_uri):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            return ("code", "code" in query), session
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)

    page_id = _page_id(resp.text)
    if page_id == "login-error":
        return ("rejected", None), session
    if page_id == "login-view-email":
        return ("mail-sent", None), session
    raise RuntimeError(f"unexpected page after submitting identifier: page_id={page_id!r}")


def complete_magic_link(session, base_url, redirect_uri, email, since):
    record = None
    for _ in range(10):
        record = _latest_capture_for(email, since)
        if record:
            break
        time.sleep(0.5)
    if record is None:
        raise RuntimeError(f"no mail captured for {email}; SMTP is likely misconfigured")

    body = record.get("body_plain") or record.get("body_html") or ""
    link_match = re.search(r"(http://\S*action-token\S*)", body)
    if not link_match:
        raise RuntimeError(f"no action-token link found in captured mail: {body[:200]}")
    link = link_match.group(1).rstrip(".,)")

    opened = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    final = _follow_to_redirect_uri(session, base_url, opened.headers.get("Location", ""), redirect_uri)
    if not final or not final.startswith(redirect_uri):
        raise RuntimeError(f"the magic link never returned to {redirect_uri}: {final!r}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned: {final[:200]}")
    return query


def main():
    creds = load_settings(CREDS_PATH)
    base_url = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base_url, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print(f"Creating organization {ORG_NAME!r}...")
    org_id = create_organization(base_url, realm, token, ORG_NAME)

    print(f"Adding {MEMBER_USERNAME} as a member (leaving {NONMEMBER_USERNAME} out)...")
    member_id = find_user_id(base_url, realm, token, MEMBER_USERNAME)
    add_member(base_url, realm, token, org_id, member_id)

    print("Configuring realm SMTP settings (local capture server)...")
    configure_smtp(base_url, realm, token)

    print(f"Authoring {FLOW_ALIAS!r} and binding it as the realm's browser flow (one atomic call)...")
    bound_alias = import_and_bind_flow(base_url, realm, token)
    print(f"  bound browserFlow = {bound_alias!r} (hash-prefixed by the extension)")

    print("Driving logins...")

    since = time.time()
    (outcome, _), session = attempt_login(
        base_url, realm, client_id, redirect_uri, MEMBER_EMAIL, ORG_NAME, "oracle-member-correct-org",
    )
    if outcome != "mail-sent":
        raise RuntimeError(f"{MEMBER_USERNAME} + correct org {ORG_NAME!r} should have reached the mail-sent page, got {outcome!r}")
    query = complete_magic_link(session, base_url, redirect_uri, MEMBER_EMAIL, since)
    print(f"  {MEMBER_USERNAME} + account_hint={ORG_NAME!r}: mail sent, link completed, code={query.get('code') is not None} (expected)")

    since2 = time.time()
    (outcome, _), _ = attempt_login(
        base_url, realm, client_id, redirect_uri, MEMBER_EMAIL, "not-a-real-org", "oracle-member-wrong-org",
    )
    if outcome != "rejected":
        raise RuntimeError(f"{MEMBER_USERNAME} + a non-existent org should have been rejected, got {outcome!r}")
    if _latest_capture_for(MEMBER_EMAIL, since2) is not None:
        raise RuntimeError(f"mail was sent to {MEMBER_EMAIL} despite an account_hint matching no real organization")
    print(f"  {MEMBER_USERNAME} + account_hint='not-a-real-org': rejected, no mail sent (expected)")

    since3 = time.time()
    (outcome, _), _ = attempt_login(
        base_url, realm, client_id, redirect_uri, NONMEMBER_EMAIL, ORG_NAME, "oracle-nonmember-real-org",
    )
    if outcome != "rejected":
        raise RuntimeError(f"{NONMEMBER_USERNAME} is not a member of {ORG_NAME!r} and should have been rejected, got {outcome!r}")
    if _latest_capture_for(NONMEMBER_EMAIL, since3) is not None:
        raise RuntimeError(f"mail was sent to {NONMEMBER_EMAIL} despite not being a member of {ORG_NAME!r}")
    print(f"  {NONMEMBER_USERNAME} (non-member) + account_hint={ORG_NAME!r}: rejected, no mail sent (expected)")

    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" body={exc.response.text[:400]}"
        print(f"oracle failed: {exc}{detail}", file=sys.stderr)
        sys.exit(1)
