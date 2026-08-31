#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: gates FEDERATED (brokered) login on organization membership.

This is the post-broker counterpart to keycloak-org-restrict-login. That task gates a
local password login through the realm's *browser* flow. This one gates a login that
happens at an external identity provider, using a **post broker login** flow bound to
the IdP itself - a different binding surface, different authenticators, different trap.

Five pieces, all through the real p2-inc keycloak-orgs extension's REST API
(/realms/{realm}/orgs - NOT Keycloak's native Organizations feature, which Phase Two
never enables):

  1. Two organizations in acme: "engineering" and "finance".
  2. An OIDC identity provider brokering the partner's realm.
  3. **Link the IdP to "engineering"** - this is what makes it an *organization-owned*
     IdP. Every authenticator in the post-broker flow keys off that ownership:
     ext-auth-org-note and ext-auth-org-add-user both no-op on an unlinked IdP.
  4. Author "post org broker login select organization" and bind it as the IdP's
     **postBrokerLoginFlowAlias**. Keycloak's stock post-broker flow does NOT contain
     ext-select-org, so without this custom flow account_hint is never evaluated after
     the IdP round-trip and the gate silently does nothing.
  5. Drive real brokered logins and confirm the gate discriminates on membership.

Why the two outcomes differ: ext-auth-org-add-user adds the brokered user to the
organization that owns the IdP (engineering). ext-select-org then matches account_hint
against the user's actual memberships. So account_hint=engineering matches, and
account_hint=finance - a real organization jordan was never added to - does not.
"""

import json
import pathlib
import re
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
IDP_DETAILS_PATH = "/root/partner_idp_details.txt"
FLOW_ASSET_PATH = pathlib.Path(__file__).parent / "post-org-broker-login-select-organization.partial-import.json"

IDP_ALIAS = "partner-sso"
OWNING_ORG = "engineering"      # the IdP is linked to this one
OTHER_ORG = "finance"           # exists, but jordan is never a member
IDP_USERNAME = "jordan"
IDP_PASSWORD = "P4rtner!Pass"
PARTNER_REALM = "partner-idp"
TIMEOUT = 30


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def get_admin_token(base_url, admin_realm, username, password):
    r = requests.post(
        f"{base_url}/realms/{admin_realm}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": username, "password": password},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_org(base_url, realm, token, name):
    """keycloak-orgs surface. Note: no `enabled` field - the extension's Organization
    representation rejects unknown fields outright with a 400."""
    r = requests.post(f"{base_url}/realms/{realm}/orgs", headers=auth(token),
                      json={"name": name}, timeout=TIMEOUT)
    r.raise_for_status()
    loc = r.headers.get("Location", "")
    if loc:
        return loc.rstrip("/").rsplit("/", 1)[-1]
    listing = requests.get(f"{base_url}/realms/{realm}/orgs", headers=auth(token), timeout=TIMEOUT)
    listing.raise_for_status()
    m = [o for o in listing.json() if o.get("name") == name]
    if len(m) != 1:
        raise RuntimeError(f"expected one {name!r} org, found {len(m)}")
    return m[0]["id"]


def create_idp(base_url, realm, token, idp):
    r = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances",
        headers=auth(token),
        json={
            "alias": IDP_ALIAS,
            "displayName": "Partner SSO",
            "providerId": "oidc",
            "enabled": True,
            "trustEmail": True,
            "storeToken": False,
            "linkOnly": False,
            "config": {
                "clientId": idp["client_id"],
                "clientSecret": idp["client_secret"],
                "clientAuthMethod": idp["client_authentication"],
                "authorizationUrl": idp["authorization_endpoint"],
                "tokenUrl": idp["token_endpoint"],
                "userInfoUrl": idp["userinfo_endpoint"],
                "jwksUrl": idp["jwks_uri"],
                "issuer": idp["issuer"],
                "defaultScope": idp["scopes"],
                "syncMode": "IMPORT",
                "useJwksUrl": "true",
            },
        },
        timeout=TIMEOUT)
    r.raise_for_status()


def link_idp_to_org(base_url, realm, token, org_id):
    """Makes the IdP *organization-owned*. Without this the post-broker authenticators
    have no organization to act on and the whole gate is inert."""
    r = requests.post(
        f"{base_url}/realms/{realm}/orgs/{org_id}/idps/link",
        headers={**auth(token), "Content-Type": "application/json"},
        json={"alias": IDP_ALIAS}, timeout=TIMEOUT)
    if r.status_code >= 300:
        r.raise_for_status()


def import_and_bind_flow(base_url, realm, token):
    """Author the post-broker flow and bind it to the IdP.

    Uses the keycloak-atomic-auth-flows extension's endpoint, which authors the flow and
    applies bindings in one call. Keycloak's own partialImport endpoint is NOT an option:
    it has no handler for authentication flows and silently ignores them.
    """
    rep = json.loads(FLOW_ASSET_PATH.read_text())
    # `ifResourceExists` is a partialImport field; AuthenticationFlowPayload rejects
    # unknown fields outright (400). The atomic endpoint uses ?force= instead.
    rep.pop("ifResourceExists", None)
    # IdpFlowPayload = {alias, firstLoginFlowBinding, postLoginFlowBinding}. Pass the flow's
    # ORIGINAL alias: the extension hash-prefixes both the flow it creates and this binding
    # value, so they line up. The IdP alias itself is passed through unprefixed.
    flow_alias = rep["authenticationFlows"][0]["alias"]
    rep["idpFlowBindings"] = [{"alias": IDP_ALIAS, "postLoginFlowBinding": flow_alias}]
    r = requests.post(f"{base_url}/admin/realms/{realm}/authentication-flow/import?force=false",
                      headers=auth(token), json=rep, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json() if r.content else {}

    # The extension hash-prefixes the alias it creates; read the real one back and make
    # sure it actually landed on the IdP rather than assuming the requested name stuck.
    idp = requests.get(f"{base_url}/admin/realms/{realm}/identity-provider/instances/{IDP_ALIAS}",
                       headers=auth(token), timeout=TIMEOUT).json()
    bound = idp.get("postBrokerLoginFlowAlias")
    if not bound:
        raise RuntimeError(f"postBrokerLoginFlowAlias not set on {IDP_ALIAS}; import returned {body}")
    print(f"  bound post-broker flow: {bound!r}")
    return bound


# --- driving a real brokered login, headlessly over plain HTTP ------------------


def _relax(session):
    for c in session.cookies:
        c.secure = False


def _form_action(html, what):
    m = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    if not m:
        raise RuntimeError(f"no form on the {what} page")
    return m.group(1).replace("&amp;", "&")


def _hop(session, url, base_url, limit=12):
    """Follow redirects manually, clearing the Secure flag after every response.

    Keycloak marks AUTH_SESSION_ID / KC_RESTART as Secure; a browser sends them over
    http://localhost anyway (loopback is a secure context) but `requests` will not, so
    letting requests auto-follow silently loses the session mid-chain and the broker
    endpoint dead-ends. Returns the final response.
    """
    for _ in range(limit):
        r = session.get(url, timeout=TIMEOUT, allow_redirects=False)
        _relax(session)
        loc = r.headers.get("Location", "")
        if not loc:
            return r
        url = loc if loc.startswith("http") else f"{base_url}{loc}"
    return r


def brokered_login(base_url, realm, client_id, redirect_uri, account_hint, state):
    """Log in at the partner IdP, carrying account_hint through the round trip.

    kc_idp_hint forces the redirect straight to the broker so this exercises the
    post-broker gate specifically, without also depending on home-IdP domain discovery.
    Returns True if the app got an authorization code.
    """
    s = requests.Session()
    url = f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "scope": "openid",
        "redirect_uri": redirect_uri, "state": state,
        "kc_idp_hint": IDP_ALIAS, "account_hint": account_hint,
    })
    page = _hop(s, url, base_url)

    # kc_idp_hint lands us on the partner realm's own login form.
    if f"/realms/{PARTNER_REALM}/" not in page.url:
        raise RuntimeError(f"kc_idp_hint did not reach {PARTNER_REALM}; at {page.url[:160]}")

    posted = s.post(_form_action(page.text, "partner login"),
                    data={"username": IDP_USERNAME, "password": IDP_PASSWORD, "credentialId": ""},
                    timeout=TIMEOUT, allow_redirects=False)
    _relax(s)

    loc = posted.headers.get("Location", "") or ""
    for _ in range(10):
        if not loc or loc.startswith(redirect_uri):
            break
        target = loc if loc.startswith("http") else f"{base_url}{loc}"
        hop = s.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax(s)
        nxt = hop.headers.get("Location", "") or ""
        if not nxt and hop.status_code == 200:
            # an error page (e.g. invalidOrganizationError) ends the chain
            break
        loc = nxt

    if not loc.startswith(redirect_uri):
        return False
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    return "code" in q


def main():
    creds = load_settings(CREDS_PATH)
    idp = load_settings(IDP_DETAILS_PATH)
    base = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print(f"Creating organizations {OWNING_ORG!r} and {OTHER_ORG!r}...")
    owning_id = create_org(base, realm, token, OWNING_ORG)
    create_org(base, realm, token, OTHER_ORG)

    print(f"Brokering the partner IdP as {IDP_ALIAS!r}...")
    create_idp(base, realm, token, idp)

    print(f"Linking {IDP_ALIAS!r} to {OWNING_ORG!r} (makes it organization-owned)...")
    link_idp_to_org(base, realm, token, owning_id)

    print("Authoring + binding the post-broker flow...")
    import_and_bind_flow(base, realm, token)

    print("Driving brokered logins...")
    if not brokered_login(base, realm, client_id, redirect_uri, OWNING_ORG, "oracle-member"):
        raise RuntimeError(f"{IDP_USERNAME} + account_hint={OWNING_ORG!r} should have succeeded")
    print(f"  account_hint={OWNING_ORG!r} (member): succeeded (expected)")

    if brokered_login(base, realm, client_id, redirect_uri, OTHER_ORG, "oracle-nonmember"):
        raise RuntimeError(f"{IDP_USERNAME} is not a member of {OTHER_ORG!r} and should NOT have succeeded")
    print(f"  account_hint={OTHER_ORG!r} (not a member): rejected (expected)")

    if brokered_login(base, realm, client_id, redirect_uri, "no-such-org", "oracle-bogus"):
        raise RuntimeError("a nonexistent organization should NOT have succeeded")
    print("  account_hint='no-such-org' (nonexistent): rejected (expected)")

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
