#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: a plain "log in with Contoso" button.

This is the simplest of the three sibling identity-brokering tasks in this repo. It is
NOT keycloak-corporate-sso-login (which routes by email domain, using organization
"verified domains" and Home IdP Discovery) and NOT keycloak-idp-org-restrict-login
(which gates a brokered login on organization membership via a custom post-broker
flow). Here the button is unconditional: broker Contoso's OIDC provider, map three
claims onto the brokered user, and ANY valid Contoso account gets in. There is no
organization, no account_hint, no post-broker flow, no domain check.

Three pieces, all through stock Keycloak Admin REST:

  1. An OIDC identity provider brokering the contoso-idp realm.
  2. Three oidc-user-attribute-idp-mapper attribute mappers: email->email,
     given_name->firstName, family_name->lastName.
  3. Drive real brokered logins for BOTH taylor and morgan - two unrelated Contoso
     staff, neither singled out - to confirm neither needs any special membership or
     hint to get through, and that the mapped attributes actually land.
"""

import json
import pathlib
import re
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
IDP_DETAILS_PATH = "/root/contoso_idp_details.txt"

IDP_ALIAS = "contoso-sso"
CONTOSO_REALM = "contoso-idp"
USERS = [
    ("taylor", "C0nt0soT4ylor!", "taylor@contoso.example", "Taylor", "Nguyen"),
    ("morgan", "C0nt0soM0rgan!", "morgan@contoso.example", "Morgan", "Alvarez"),
]
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


def create_idp(base_url, realm, token, idp):
    r = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances",
        headers=auth(token),
        json={
            "alias": IDP_ALIAS,
            "displayName": "Log in with Contoso",
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


def add_mapper(base_url, realm, token, name, claim, user_attribute):
    r = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances/{IDP_ALIAS}/mappers",
        headers=auth(token),
        json={
            "name": name,
            "identityProviderAlias": IDP_ALIAS,
            "identityProviderMapper": "oidc-user-attribute-idp-mapper",
            "config": {
                "syncMode": "INHERIT",
                "claim": claim,
                "user.attribute": user_attribute,
            },
        },
        timeout=TIMEOUT)
    r.raise_for_status()


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


def brokered_login(base_url, realm, client_id, redirect_uri, username, password, state):
    """Log in at Contoso's identity provider via kc_idp_hint. No account_hint at all -
    this is the point: a plain login button, nothing tied to organization membership.
    Returns True if the app got an authorization code.
    """
    s = requests.Session()
    url = f"{base_url}/realms/{realm}/protocol/openid-connect/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "scope": "openid",
        "redirect_uri": redirect_uri, "state": state,
        "kc_idp_hint": IDP_ALIAS,
    })
    page = _hop(s, url, base_url)

    if f"/realms/{CONTOSO_REALM}/" not in page.url:
        raise RuntimeError(f"kc_idp_hint did not reach {CONTOSO_REALM}; at {page.url[:160]}")

    posted = s.post(_form_action(page.text, "contoso login"),
                    data={"username": username, "password": password, "credentialId": ""},
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
            break
        loc = nxt

    if not loc.startswith(redirect_uri):
        return False
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    return "code" in q


def check_attributes(base_url, realm, token, username, email, first, last):
    r = requests.get(f"{base_url}/admin/realms/{realm}/users",
                     headers=auth(token), params={"username": username, "exact": "true"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    matches = r.json()
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one brokered user for {username!r}, found {len(matches)}")
    u = matches[0]
    if u.get("email") != email:
        raise RuntimeError(f"{username}: email={u.get('email')!r}, expected {email!r}")
    if u.get("firstName") != first:
        raise RuntimeError(f"{username}: firstName={u.get('firstName')!r}, expected {first!r}")
    if u.get("lastName") != last:
        raise RuntimeError(f"{username}: lastName={u.get('lastName')!r}, expected {last!r}")


def main():
    creds = load_settings(CREDS_PATH)
    idp = load_settings(IDP_DETAILS_PATH)
    base = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]

    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"], creds["admin_password"])

    print(f"Brokering Contoso's identity provider as {IDP_ALIAS!r}...")
    create_idp(base, realm, token, idp)

    print("Adding attribute mappers (email, given_name->firstName, family_name->lastName)...")
    add_mapper(base, realm, token, "email", "email", "email")
    add_mapper(base, realm, token, "firstName", "given_name", "firstName")
    add_mapper(base, realm, token, "lastName", "family_name", "lastName")

    print("Driving brokered logins for both Contoso staff (no account_hint at all)...")
    for username, password, email, first, last in USERS:
        state = f"oracle-{username}"
        if not brokered_login(base, realm, client_id, redirect_uri, username, password, state):
            raise RuntimeError(f"{username} should have been able to log in with a plain login button")
        print(f"  {username}: login succeeded (expected)")
        check_attributes(base, realm, token, username, email, first, last)
        print(f"  {username}: attributes mapped correctly")

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
