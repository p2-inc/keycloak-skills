#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: gives the acme realm corporate SSO for Contoso staff.

"Corporate SSO login" means: pick an identity provider from the domain of the
email the user typed, send them there, and leave everyone else on the password
form. This task runs Phase Two's Keycloak image, so the oracle takes the path the
shipped `admin:corporate-sso` references teach, through two extensions the image
bundles (keycloak-orgs and keycloak-atomic-auth-flows):

  1. Broker Contoso's OIDC provider (stock Admin REST).
  2. Create an organization that holds Contoso's email domain:
     POST /realms/acme/orgs. That is keycloak-orgs. Keycloak's native
     /admin/realms/acme/organizations does not exist here: native organizations
     are switched off, as on every Phase Two deployment.
  3. Link the provider to that organization:
     POST /realms/acme/orgs/{id}/idps/link.
  4. Author the `homeIdp` browser flow from the skill's asset and bind it
     realm-wide, in one call: POST /admin/realms/acme/authentication-flow/import
     with home-idp.partial-import.json, minus `ifResourceExists` (a
     partialImport field the import endpoint rejects), plus `browserFlowBinding`.

The flow's `ext-auth-home-idp-discovery` execution asks for the email address,
finds the organization whose own domain list holds its domain, and forwards to
the provider linked to that organization. Every other address falls through to
`auth-password-form`.

Discovery reads the organization's domains, not the `domains` sent on the link.
Those land on the provider as `home.idp.discovery.domains` and matter only when
the realm allows several providers per organization. The oracle sends the domain
on both, as the reference does. Neither is verified: discovery ignores
verification unless the execution's config sets `requireVerifiedDomain`, and the
asset does not. The asset also sets `forwardToLinkedIdp=true`, which only lets a
user's existing federated links take precedence. With one provider per
organization it changes nothing: at its default of false, a returning user is
still forwarded (measured).

The obvious-looking alternative, an identity-provider-redirector execution in a
custom browser flow, forwards *everyone* to the provider and so breaks password
login for internal staff.

Finishes by driving the logins end to end the way the verifier does, so a realm
that is configured but does not actually route anyone fails here rather than
looking like a passing oracle. The corporate login runs twice for the same
person, because discovery looks a returning user up before it routes them.

The functions are importable, so a negative scenario can replay these steps
with one change.
"""

import json
import pathlib
import re
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
IDP_DETAILS_PATH = "/root/corporate_idp_details.txt"
# A verbatim copy of plugins/phasetwo/skills/keycloak/assets/home-idp.partial-import.json.
FLOW_ASSET_PATH = pathlib.Path(__file__).parent / "home-idp.partial-import.json"
IDP_ALIAS = "contoso-sso"
ORG_NAME = "contoso"
CORP_USERNAME = "jvega@contoso.example"
CORP_PASSWORD = "C0nt0so!Pass"
INTERNAL_USERNAME = "dana@acme-internal.example"
INTERNAL_PASSWORD = "Ac1me!Internal"
CUSTOMER_AUTH_PATH = "/realms/contoso-idp/protocol/openid-connect/auth"
DISCOVERY_AUTHENTICATOR = "ext-auth-home-idp-discovery"
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


def create_identity_provider(base_url, headers, realm, idp):
    """Broker Contoso's OIDC provider using the credentials they issued.

    `syncMode` and `postBrokerLoginFlowAlias` are left out: linking the provider
    to the organization (step 3) overwrites both.
    """
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances",
        headers=headers,
        json={
            "alias": IDP_ALIAS,
            "displayName": "Contoso SSO",
            "providerId": "oidc",
            "enabled": True,
            # Contoso vouches for their own users' email addresses, so accept
            # them without a verification round trip.
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
                "useJwksUrl": "true",
            },
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def create_organization(base_url, headers, realm, domains):
    """Create the organization in keycloak-orgs, holding Contoso's email domain.

    These are the domains discovery matches. The representation takes `domains`
    as plain strings; the native shape `[{"name": ...}]` is still answered 201,
    with the objects' keys and values flattened into garbage domains, so the
    domains are read back rather than trusted. `alias`, `enabled` and
    `description` do not exist here and are rejected with a 400.
    """
    body = {"name": ORG_NAME, "displayName": "Contoso Ltd"}
    if domains:
        body["domains"] = list(domains)
    resp = requests.post(
        f"{base_url}/realms/{realm}/orgs", headers=headers, json=body, timeout=TIMEOUT
    )
    resp.raise_for_status()

    org_id = resp.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1]
    if not org_id or org_id == "orgs":
        listing = requests.get(
            f"{base_url}/realms/{realm}/orgs", headers=headers, timeout=TIMEOUT
        )
        listing.raise_for_status()
        matches = [o for o in listing.json() if o.get("name") == ORG_NAME]
        if len(matches) != 1:
            raise RuntimeError(f"expected one {ORG_NAME} organization, found {len(matches)}")
        org_id = matches[0]["id"]

    org = requests.get(
        f"{base_url}/realms/{realm}/orgs/{org_id}", headers=headers, timeout=TIMEOUT
    )
    org.raise_for_status()
    held = sorted(org.json().get("domains") or [])
    if held != sorted(domains or []):
        raise RuntimeError(f"the organization holds {held}, expected {sorted(domains or [])}")
    return org_id


def link_idp_to_organization(base_url, headers, realm, org_id, domains):
    """Make the provider the organization's identity provider.

    Note the `/link` suffix: `POST .../idps` without it creates a new provider
    owned by the organization instead of adopting an existing one. Linking sets
    `home.idp.discovery.org` on the provider to the organization's id, which is
    how discovery gets from the organization to the provider. It also forces
    `hideOnLogin` to true: the provider is reached by domain, not by a button.
    """
    body = {"alias": IDP_ALIAS}
    if domains:
        body["domains"] = list(domains)
    resp = requests.post(
        f"{base_url}/realms/{realm}/orgs/{org_id}/idps/link",
        headers=headers,
        json=body,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    linked = requests.get(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances/{IDP_ALIAS}",
        headers=headers,
        timeout=TIMEOUT,
    )
    linked.raise_for_status()
    owner = (linked.json().get("config") or {}).get("home.idp.discovery.org")
    if owner != org_id:
        raise RuntimeError(
            f"{IDP_ALIAS} is not linked to the organization: home.idp.discovery.org={owner!r}"
        )


def load_flow_asset():
    return json.loads(FLOW_ASSET_PATH.read_text())


def import_and_bind_flow(base_url, headers, realm, asset):
    """Author the asset's flow and bind it as the realm's browser flow, in one call.

    Keycloak's own partialImport endpoint is not an option: it has no handler for
    authentication flows and ignores them (200 OK, nothing created). The
    keycloak-atomic-auth-flows endpoint authors the flow and applies the binding
    together. It hash-prefixes the aliases it creates, including the binding
    value, so the binding names the asset's own alias and the real one is read
    back afterwards.
    """
    payload = dict(asset)
    # A partialImport field; the import endpoint rejects unknown fields with a 400.
    payload.pop("ifResourceExists", None)
    top_level = [f for f in payload["authenticationFlows"] if f.get("topLevel")]
    if len(top_level) != 1:
        raise RuntimeError(f"expected one top-level flow in the asset, found {len(top_level)}")
    payload["browserFlowBinding"] = top_level[0]["alias"]

    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/authentication-flow/import",
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )
    if resp.status_code == 404:
        raise RuntimeError(
            "the keycloak-atomic-auth-flows extension is not installed "
            "(404 from /authentication-flow/import)"
        )
    resp.raise_for_status()

    bound = requests.get(
        f"{base_url}/admin/realms/{realm}", headers=headers, timeout=TIMEOUT
    ).json().get("browserFlow")
    if not bound or bound == "browser":
        raise RuntimeError(f"browserFlow was not bound to the imported flow (got {bound!r})")
    return bound


def bound_flow_has_discovery(base_url, headers, realm, flow_alias):
    """True when the bound flow runs ext-auth-home-idp-discovery anywhere in it."""
    resp = requests.get(
        f"{base_url}/admin/realms/{realm}/authentication/flows/"
        f"{urllib.parse.quote(flow_alias, safe='')}/executions",
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return any(e.get("providerId") == DISCOVERY_AUTHENTICATOR for e in resp.json())


# --- the browser flow, driven headlessly -----------------------------------


def _relax_cookies(session):
    """Keycloak marks its auth cookies Secure with SameSite=None.

    A browser sends them anyway over http://localhost, which it treats as a
    secure context; `requests` will not. Clearing the flag reproduces the
    browser's behaviour, without which every POST fails as `cookie_not_found`.
    """
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html):
    match = re.search(r'<form[^>]*action="([^"]+)"', html, re.I)
    if not match:
        raise RuntimeError("no form on the page")
    return match.group(1).replace("&amp;", "&")


def _authorization_url(base_url, realm, client_id, redirect_uri, state):
    return f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid email",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": f"nonce-{state}",
        }
    )


def _follow_to_redirect_uri(session, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location:
            return None
        if location.startswith(redirect_uri):
            return location
        target = location if location.startswith("http") else f"http://localhost:8080{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    return None


def corporate_login(base_url, realm, client_id, redirect_uri, state):
    """Type a Contoso email, expect to be sent out to Contoso, log in there.

    Discovery answers the submitted address with a 303 straight to Contoso's
    authorization endpoint, whose `redirect_uri` is acme's broker endpoint for
    the linked provider. No page is shown in between, whether or not the person
    has federated before. (Native organizations went through acme's
    /broker/{alias}/login first; that hop is followed too if it appears.)
    """
    session = requests.Session()
    page = session.get(
        _authorization_url(base_url, realm, client_id, redirect_uri, state), timeout=TIMEOUT
    )
    _relax_cookies(session)

    identified = session.post(
        _form_action(page.text),
        data={"username": CORP_USERNAME},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    if 'type="password"' in (identified.text or ""):
        raise RuntimeError(f"a Contoso address was asked for an Acme password ({state})")

    location = identified.headers.get("Location", "")
    if identified.status_code not in (302, 303) or not location:
        raise RuntimeError(
            f"a Contoso address was not redirected ({state}): status "
            f"{identified.status_code}, Location {location[:200]!r}"
        )
    for _ in range(5):
        if CUSTOMER_AUTH_PATH in location:
            break
        target = location if location.startswith("http") else f"http://localhost:8080{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    if CUSTOMER_AUTH_PATH not in location:
        raise RuntimeError(f"was not routed to the customer's IdP; went to {location[:200]}")
    comes_back_to = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get(
        "redirect_uri", [""]
    )[0]
    if not comes_back_to.endswith(f"/realms/{realm}/broker/{IDP_ALIAS}/endpoint"):
        raise RuntimeError(
            f"routed to the customer's IdP, but not through {IDP_ALIAS}: "
            f"redirect_uri={comes_back_to!r}"
        )

    corp_page = session.get(location, timeout=TIMEOUT)
    _relax_cookies(session)
    returned = session.post(
        _form_action(corp_page.text),
        data={"username": CORP_USERNAME, "password": CORP_PASSWORD, "credentialId": ""},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)

    final = _follow_to_redirect_uri(
        session, returned.headers.get("Location", ""), redirect_uri
    )
    if not final:
        raise RuntimeError(f"the corporate login never came back to the application ({state})")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code returned: {final[:200]}")
    if query.get("state") != [state]:
        raise RuntimeError(f"state was not preserved: {query.get('state')}")


def internal_login(base_url, realm, client_id, redirect_uri):
    """Type an internal email, expect a password form, and complete it."""
    state = "oracle-internal"
    session = requests.Session()
    page = session.get(
        _authorization_url(base_url, realm, client_id, redirect_uri, state), timeout=TIMEOUT
    )
    _relax_cookies(session)

    identified = session.post(
        _form_action(page.text),
        data={"username": INTERNAL_USERNAME},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    if 'type="password"' not in (identified.text or ""):
        raise RuntimeError("an internal address was not offered a password form")

    submitted = session.post(
        _form_action(identified.text),
        data={
            "username": INTERNAL_USERNAME,
            "password": INTERNAL_PASSWORD,
            "credentialId": "",
        },
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)

    final = _follow_to_redirect_uri(
        session, submitted.headers.get("Location", ""), redirect_uri
    )
    if not final:
        raise RuntimeError("the internal password login never reached the application")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    if "code" not in query:
        raise RuntimeError(f"no authorization code for the internal login: {final[:200]}")


def setup():
    """Read the task's settings and get an admin token. Returns (context, headers)."""
    creds = load_settings(CREDS_PATH)
    idp = load_settings(IDP_DETAILS_PATH)
    context = {
        "base_url": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
        "domain": idp["email_domain"],
        "idp": idp,
    }
    token = get_admin_token(
        context["base_url"],
        creds["admin_realm"],
        creds["admin_username"],
        creds["admin_password"],
    )
    return context, {"Authorization": f"Bearer {token}"}


def main():
    ctx, headers = setup()
    base_url, realm = ctx["base_url"], ctx["realm"]

    create_identity_provider(base_url, headers, realm, ctx["idp"])
    org_id = create_organization(base_url, headers, realm, [ctx["domain"]])
    link_idp_to_organization(base_url, headers, realm, org_id, [ctx["domain"]])
    flow = import_and_bind_flow(base_url, headers, realm, load_flow_asset())
    if not bound_flow_has_discovery(base_url, headers, realm, flow):
        raise RuntimeError(f"the bound flow {flow!r} has no {DISCOVERY_AUTHENTICATOR} execution")
    print(f"bound browser flow: {flow!r}")

    login = (base_url, realm, ctx["client_id"], ctx["redirect_uri"])
    corporate_login(*login, state="oracle-corp-first")
    corporate_login(*login, state="oracle-corp-returning")
    internal_login(*login)

    print(
        "oracle self-check passed: a contoso.example address is routed to the "
        "customer's IdP and returns with a code, on its first login and again "
        "once federated, and an internal address still logs in with its password"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" body={exc.response.text[:400]}"
        print(f"oracle failed: {exc}{detail}", file=sys.stderr)
        sys.exit(1)
