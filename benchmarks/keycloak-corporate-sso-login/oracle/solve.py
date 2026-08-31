#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: gives the acme realm corporate SSO for Contoso staff.

"Corporate SSO login" means: pick an identity provider from the domain of the
email the user typed, send them there, and leave everyone else on the password
form. Brokering the provider is the straightforward part. Selecting it *by email
domain* has exactly one vanilla mechanism, and it is not in the authentication
flow editor:

  1. The realm's organization support has to be switched on.
  2. An organization has to hold the customer's email domain, marked *verified*.
     An unverified domain is stored happily and never matches.
  3. The identity provider has to be linked to that organization. Without the
     link the provider still works, but the login page just shows an SSO button
     to every visitor - there is no domain-based routing at all.

The obvious-looking alternative, an identity-provider-redirector execution in a
custom browser flow, forwards *everyone* to the provider and so breaks password
login for internal staff.

Finishes by driving both logins end to end the way the verifier does, so a realm
that is configured but does not actually route anyone fails here rather than
looking like a passing oracle.
"""

import pathlib
import re
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
IDP_DETAILS_PATH = "/root/corporate_idp_details.txt"
IDP_ALIAS = "contoso-sso"
ORG_NAME = "contoso"
CORP_USERNAME = "jvega@contoso.example"
CORP_PASSWORD = "C0nt0so!Pass"
INTERNAL_USERNAME = "dana@acme-internal.example"
INTERNAL_PASSWORD = "Ac1me!Internal"
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


def enable_organizations(base_url, headers, realm):
    """Organization support is a realm switch, off by default."""
    current = requests.get(
        f"{base_url}/admin/realms/{realm}", headers=headers, timeout=TIMEOUT
    )
    current.raise_for_status()
    representation = current.json()
    representation["organizationsEnabled"] = True
    resp = requests.put(
        f"{base_url}/admin/realms/{realm}",
        headers=headers,
        json=representation,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    check = requests.get(
        f"{base_url}/admin/realms/{realm}", headers=headers, timeout=TIMEOUT
    ).json()
    if not check.get("organizationsEnabled"):
        raise RuntimeError("organizationsEnabled did not stick on the realm")


def create_identity_provider(base_url, headers, realm, idp):
    """Broker Contoso's OIDC provider using the credentials they issued."""
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
                "syncMode": "IMPORT",
                "useJwksUrl": "true",
            },
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def create_organization_with_domain(base_url, headers, realm, domain):
    """The domain has to be marked verified, or discovery never matches it."""
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/organizations",
        headers=headers,
        json={
            "name": ORG_NAME,
            "alias": ORG_NAME,
            "enabled": True,
            "description": "Contoso Ltd - federated enterprise customer",
            "domains": [{"name": domain, "verified": True}],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    listing = requests.get(
        f"{base_url}/admin/realms/{realm}/organizations", headers=headers, timeout=TIMEOUT
    )
    listing.raise_for_status()
    matches = [o for o in listing.json() if o.get("name") == ORG_NAME]
    if len(matches) != 1:
        raise RuntimeError(f"expected one {ORG_NAME} organization, found {len(matches)}")
    return matches[0]["id"]


def link_idp_to_organization(base_url, headers, realm, org_id):
    """The link is what turns a plain broker into domain-based routing.

    The body is a bare JSON string holding the provider alias, not an object.
    """
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/organizations/{org_id}/identity-providers",
        headers={**headers, "Content-Type": "application/json"},
        data=f'"{IDP_ALIAS}"',
        timeout=TIMEOUT,
    )
    resp.raise_for_status()

    linked = requests.get(
        f"{base_url}/admin/realms/{realm}/organizations/{org_id}/identity-providers",
        headers=headers,
        timeout=TIMEOUT,
    )
    linked.raise_for_status()
    if IDP_ALIAS not in {i.get("alias") for i in linked.json()}:
        raise RuntimeError(f"{IDP_ALIAS} is not linked to the organization")


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


def corporate_login(base_url, realm, client_id, redirect_uri):
    """Type a Contoso email, expect to be routed out to Contoso, log in there."""
    state = "oracle-corp"
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
        raise RuntimeError("a Contoso address was asked for an Acme password")

    link = re.search(r'href="([^"]*?/broker/[^"]*?/login[^"]*)"', identified.text or "")
    location = identified.headers.get("Location", "")
    if link:
        url = link.group(1).replace("&amp;", "&")
        url = url if url.startswith("http") else f"http://localhost:8080{url}"
        hop = session.get(url, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    if "/realms/contoso-idp/protocol/openid-connect/auth" not in location:
        raise RuntimeError(f"was not routed to the customer's IdP; went to {location[:200]}")

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
        raise RuntimeError("the corporate login never came back to the application")
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


def main():
    creds = load_settings(CREDS_PATH)
    idp = load_settings(IDP_DETAILS_PATH)
    base_url = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    admin_token = get_admin_token(
        base_url,
        creds["admin_realm"],
        creds["admin_username"],
        creds["admin_password"],
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    enable_organizations(base_url, headers, realm)
    create_identity_provider(base_url, headers, realm, idp)
    org_id = create_organization_with_domain(base_url, headers, realm, idp["email_domain"])
    link_idp_to_organization(base_url, headers, realm, org_id)

    corporate_login(base_url, realm, client_id, redirect_uri)
    internal_login(base_url, realm, client_id, redirect_uri)

    print(
        "oracle self-check passed: a contoso.example address is routed to the "
        "customer's IdP and returns with a code, and an internal address still "
        "logs in with its password"
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
