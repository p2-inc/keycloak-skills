#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: restricts login to members of one organization.

Five steps, all through the real p2-inc keycloak-orgs extension's REST API
(NOT Keycloak's native Organizations feature - Phase Two's product never
enables that; see docs/note-keycloak-organizations-feature.md in
p2-inc/keycloak-orgs):

  1. Create an organization ("engineering") via POST .../orgs. The name has to be
     exactly "engineering" because that's the literal account_hint value the
     application in this task sends - only match_by_org_name=true (matching by
     NAME) can possibly work here, since the application never learns or sends
     a server-generated organization ID.
  2. Add `priya` as a member via PUT .../orgs/{orgId}/members/{userId}.
     `morgan` is deliberately left NOT a member - the negative case below
     depends on that.
  3+4. Author "Org Browser Flow by Org Name" AND bind it as the realm's browser
     flow, in ONE atomic call, via the p2-inc keycloak-atomic-auth-flows
     extension (POST /admin/realms/{realm}/authentication-flow/import).
     Keycloak's own partialImport endpoint cannot do this: it has no handler
     for authentication flows at all, so an authenticationFlows array sent to
     it is silently ignored (200 OK, added: 0, nothing created). The bundled
     asset's ext-select-org config has match_by_org_name=true, so account_hint
     is treated as the organization's NAME, not its ID.
  5. Drive three real logins and confirm:
       - priya + account_hint=engineering (her own org, by name)   -> succeeds
       - priya + account_hint=some-other-org (a non-member org) -> rejected
       - morgan + account_hint=engineering (not a member of it)    -> rejected
     A login with neither account_hint nor prompt=select_account is NOT
     exercised here - AuthenticationFlowTools' own tools already document
     that this flow only gates logins that carry one of those two request
     parameters; this task is about the gate itself, not that separate trap.
"""

import json
import pathlib
import re
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
FLOW_ASSET_PATH = pathlib.Path(__file__).parent / "org-browser-flow-by-org-name.partial-import.json"
ORG_NAME = "engineering"
FLOW_ALIAS = "Org Browser Flow by Org Name"
MEMBER_USERNAME = "priya"
MEMBER_PASSWORD = "Priya!Pass1"
NONMEMBER_USERNAME = "morgan"
NONMEMBER_PASSWORD = "Morgan!Pass1"
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
    """Step 1: create the organization via the real keycloak-orgs REST API."""
    resp = requests.post(
        f"{base_url}/realms/{realm}/orgs",
        headers=auth(token),
        json={"name": name},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    location = resp.headers.get("Location", "")
    org_id = location.rstrip("/").rsplit("/", 1)[-1] if location else None
    if not org_id:
        # Fall back to listing if the Location header wasn't informative.
        listing = requests.get(
            f"{base_url}/realms/{realm}/orgs", headers=auth(token), timeout=TIMEOUT
        )
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
    """Step 2: PUT .../orgs/{orgId}/members/{userId} - the real membership call."""
    resp = requests.put(
        f"{base_url}/realms/{realm}/orgs/{org_id}/members/{user_id}",
        headers=auth(token), timeout=TIMEOUT,
    )
    if resp.status_code not in (201, 204):
        resp.raise_for_status()

    check = requests.get(
        f"{base_url}/realms/{realm}/orgs/{org_id}/members/{user_id}",
        headers=auth(token), timeout=TIMEOUT,
    )
    if check.status_code != 204:
        raise RuntimeError(f"membership for {user_id} in org {org_id} did not stick")


def import_and_bind_flow(base_url, realm, token):
    """Steps 3 AND 4, in one atomic call, via the p2-inc keycloak-atomic-auth-flows
    extension: POST /admin/realms/{realm}/authentication-flow/import.

    Keycloak's own partialImport endpoint is NOT usable here - it has no handler
    for authentication flows at all (only clients, roles, identity providers, IdP
    mappers, groups and users), so an authenticationFlows array sent to it is
    silently ignored: 200 OK, added: 0, no error, nothing created.

    The extension prefixes every alias with a hash of the payload's configs, so the
    flow that actually gets created is NOT named what the asset says. The binding is
    applied by the extension itself (browserFlowBinding below), so the prefixed name
    never has to be reconstructed here - but it does have to be read back rather than
    assumed, which is what the return value is for.
    """
    asset = json.loads(FLOW_ASSET_PATH.read_text())
    payload = {
        "authenticationFlows": asset["authenticationFlows"],
        "authenticatorConfig": asset["authenticatorConfig"],
        # Bind it realm-wide in the same call.
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


def _authorization_url(base_url, realm, client_id, redirect_uri, state, account_hint):
    params = {
        "client_id": client_id, "response_type": "code", "scope": "openid",
        "redirect_uri": redirect_uri, "state": state, "account_hint": account_hint,
    }
    return f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)


def attempt_login(base_url, realm, client_id, redirect_uri, username, password, account_hint, state):
    session = requests.Session()
    page = session.get(
        _authorization_url(base_url, realm, client_id, redirect_uri, state, account_hint),
        timeout=TIMEOUT,
    )
    _relax_cookies(session)

    submitted = session.post(
        _form_action(page.text),
        data={"username": username, "password": password, "credentialId": ""},
        timeout=TIMEOUT, allow_redirects=False,
    )
    _relax_cookies(session)

    location = submitted.headers.get("Location", "") or ""
    for _ in range(8):
        if not location or location.startswith(redirect_uri):
            break
        target = location if location.startswith("http") else f"{base_url}{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "") or ""

    if location.startswith(redirect_uri):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        return "code" in query
    return False


def main():
    creds = load_settings(CREDS_PATH)
    base_url = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(
        base_url, creds["admin_realm"], creds["admin_username"], creds["admin_password"]
    )

    print(f"Creating organization {ORG_NAME!r}...")
    org_id = create_organization(base_url, realm, token, ORG_NAME)

    print(f"Adding {MEMBER_USERNAME} as a member (leaving {NONMEMBER_USERNAME} out)...")
    member_id = find_user_id(base_url, realm, token, MEMBER_USERNAME)
    add_member(base_url, realm, token, org_id, member_id)

    print(f"Authoring {FLOW_ALIAS!r} and binding it as the realm's browser flow (one atomic call)...")
    bound_alias = import_and_bind_flow(base_url, realm, token)
    print(f"  bound browserFlow = {bound_alias!r} (hash-prefixed by the extension)")

    print("Driving logins...")
    ok = attempt_login(base_url, realm, client_id, redirect_uri,
                        MEMBER_USERNAME, MEMBER_PASSWORD, ORG_NAME, "oracle-member-correct-org")
    if not ok:
        raise RuntimeError(f"{MEMBER_USERNAME} + correct org {ORG_NAME!r} should have succeeded")
    print(f"  {MEMBER_USERNAME} + account_hint={ORG_NAME!r}: succeeded (expected)")

    ok = attempt_login(base_url, realm, client_id, redirect_uri,
                        MEMBER_USERNAME, MEMBER_PASSWORD, "some-other-org", "oracle-member-wrong-org")
    if ok:
        raise RuntimeError(f"{MEMBER_USERNAME} + a non-existent org should NOT have succeeded")
    print(f"  {MEMBER_USERNAME} + account_hint='some-other-org': rejected (expected)")

    ok = attempt_login(base_url, realm, client_id, redirect_uri,
                        NONMEMBER_USERNAME, NONMEMBER_PASSWORD, ORG_NAME, "oracle-nonmember-real-org")
    if ok:
        raise RuntimeError(f"{NONMEMBER_USERNAME} is not a member of {ORG_NAME!r} and should NOT have succeeded")
    print(f"  {NONMEMBER_USERNAME} (non-member) + account_hint={ORG_NAME!r}: rejected (expected)")

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
