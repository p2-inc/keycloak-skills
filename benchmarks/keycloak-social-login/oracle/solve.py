#!/usr/bin/env python3
"""Human-written oracle: wires up "Sign in with GitHub" on the acme realm.

Three pieces, all through the Admin REST API:

  1. The identity provider itself - a *built-in* social provider
     (providerId="github"), not a generic OIDC/SAML config. Keycloak already
     knows GitHub's OAuth endpoints; only the client ID/secret from the
     fixture file are needed.

  2. A username mapper. GitHub's own IdentityProvider class
     (org.keycloak.social.github.GitHubIdentityProvider) already sets the
     imported user's username from GitHub's "login" field automatically, with
     no mapper required - but the standard admin-console way to make that
     explicit and durable across sync modes is a Username Template Importer
     (identityProviderMapper "oidc-username-idp-mapper") with a template that
     names GitHub's actual field. Its factory default template is
     "${ALIAS}.${CLAIM.preferred_username}" - GitHub's raw profile JSON has no
     "preferred_username" field at all (see extractIdentityFromProfile in
     GitHubIdentityProvider.java: it reads "login", "name", and "email", full
     stop), so leaving the default in place resolves to an unresolved
     variable and Keycloak sets an *empty* username. The working template
     references "${CLAIM.login}" instead.

  3. An attribute mapper for the display name. GitHub's own compatible mapper
     type is "github-user-attribute-mapper"
     (org.keycloak.social.github.GitHubUserAttributeMapper, a subclass of
     AbstractJsonUserAttributeMapper) - NOT the generic OIDC claim mapper
     "oidc-user-attribute-idp-mapper" a copy-pasted Google/Auth0/generic-OIDC
     pattern would reach for. Its config keys are also different:
     "jsonField"/"userAttribute", not "claim"/"user.attribute". GitHub's
     profile JSON has one "name" field (the whole display name) and no
     "given_name"/"family_name" split, so it maps "name" -> "firstName".

No live brokered login is attempted or possible here: Keycloak's built-in
social providers point at hardcoded real vendor endpoints
(GitHubIdentityProvider.DEFAULT_AUTH_URL = "https://github.com/login/oauth/authorize"),
which cannot be redirected to a local fake IdP the way generic OIDC/SAML
providers can. In this no-network sandbox, the closest thing to "did this
really wire up" without ever contacting github.com is asking Keycloak's own
authorization endpoint, with kc_idp_hint pointing at this provider, what it
would redirect the browser to - Keycloak builds that redirect (and the
client_id embedded in it) entirely locally, before any network call to
GitHub would happen.
"""

import json
import pathlib
import sys
import urllib.parse

import requests

CREDS_PATH = "/root/admin_credentials.txt"
GITHUB_DETAILS_PATH = "/root/github_oauth_app_details.txt"
ALIAS = "github"
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


def create_github_idp(base_url, headers, realm, client_id, client_secret):
    rep = {
        "alias": ALIAS,
        "displayName": "GitHub",
        "providerId": "github",
        "enabled": True,
        "trustEmail": True,
        "storeToken": False,
        "linkOnly": False,
        "config": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "syncMode": "IMPORT",
        },
    }
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances",
        headers=headers,
        json=rep,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def add_username_mapper(base_url, headers, realm):
    """Username Template Importer, pointed at GitHub's real "login" field.

    The factory default template references "${CLAIM.preferred_username}" -
    an OIDC-standard claim GitHub never sends. Left at the default, this
    mapper would resolve to an unresolved variable and blank the username.
    """
    body = {
        "name": "github-username",
        "identityProviderAlias": ALIAS,
        "identityProviderMapper": "oidc-username-idp-mapper",
        "config": {
            "template": "${CLAIM.login}",
            "target": "LOCAL",
        },
    }
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances/{ALIAS}/mappers",
        headers=headers,
        json=body,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def add_firstname_mapper(base_url, headers, realm):
    """GitHub's own attribute mapper type, GitHub's own field name.

    GitHub's profile JSON has a single "name" field (full display name), not
    the OIDC-standard "given_name"/"family_name" split. The mapper type
    itself also differs from the generic OIDC one:
    "github-user-attribute-mapper", with "jsonField"/"userAttribute" config
    keys rather than "claim"/"user.attribute".
    """
    body = {
        "name": "github-firstname",
        "identityProviderAlias": ALIAS,
        "identityProviderMapper": "github-user-attribute-mapper",
        "config": {
            "syncMode": "INHERIT",
            "jsonField": "name",
            "userAttribute": "firstName",
        },
    }
    resp = requests.post(
        f"{base_url}/admin/realms/{realm}/identity-provider/instances/{ALIAS}/mappers",
        headers=headers,
        json=body,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()


def _relax_cookies(session):
    """Keycloak marks its auth cookies Secure with SameSite=None.

    A browser sends them anyway over http://localhost, treating it as a secure
    context; `requests` will not, and the follow-up hop then fails as
    cookie_not_found - a property of this script's HTTP client, not the realm.
    """
    for cookie in session.cookies:
        cookie.secure = False


def self_check(base_url, headers, realm, client_id, redirect_uri, github_client_id):
    """Ask Keycloak's own auth endpoint what it would do with kc_idp_hint.

    This never contacts github.com - Keycloak builds the redirect entirely
    from the realm's own IdP configuration before any outbound call happens.
    It is the strongest "is this really wired up" signal available without
    network access.
    """
    session = requests.Session()
    resp = session.get(
        f"{base_url}/realms/{realm}/protocol/openid-connect/auth",
        params={
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": redirect_uri,
            "state": "oracle-check",
            "kc_idp_hint": ALIAS,
        },
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    # Keycloak's first hop lands on its own local /broker/{alias}/login endpoint
    # (session bookkeeping, still entirely local); the actual redirect out to
    # GitHub is the hop after that. Follow same-origin hops until we either
    # leave localhost or run out of budget.
    location = resp.headers.get("Location", "")
    for _ in range(5):
        if resp.status_code not in (302, 303) or not location:
            raise RuntimeError(
                f"expected a chain of redirects ending at GitHub, got {resp.status_code}: "
                f"{location or resp.text[:200]}"
            )
        if not location.startswith("http://localhost:8080") and not location.startswith(base_url):
            break
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = resp.headers.get("Location", "")
    if not location.startswith("https://github.com/login/oauth/authorize"):
        raise RuntimeError(f"redirect chain did not end at GitHub's authorize endpoint: {location}")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    if query.get("client_id") != [github_client_id]:
        raise RuntimeError(
            f"redirect's client_id was {query.get('client_id')}, expected {[github_client_id]}"
        )
    expected_redirect = f"{base_url}/realms/{realm}/broker/{ALIAS}/endpoint"
    if query.get("redirect_uri") != [expected_redirect]:
        raise RuntimeError(
            f"redirect's redirect_uri was {query.get('redirect_uri')}, expected {[expected_redirect]}"
        )
    print(f"oracle self-check passed: kc_idp_hint={ALIAS} redirects to {location[:120]}...")


def main():
    creds = load_settings(CREDS_PATH)
    github = load_settings(GITHUB_DETAILS_PATH)
    base_url = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    client_id = creds["app_client_id"]
    redirect_uri = creds["app_redirect_uri"]
    github_client_id = github["github_client_id"]
    github_client_secret = github["github_client_secret"]

    admin_token = get_admin_token(
        base_url, creds["admin_realm"], creds["admin_username"], creds["admin_password"]
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    create_github_idp(base_url, headers, realm, github_client_id, github_client_secret)
    add_username_mapper(base_url, headers, realm)
    add_firstname_mapper(base_url, headers, realm)

    self_check(base_url, headers, realm, client_id, redirect_uri, github_client_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the caller
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" body={exc.response.text[:400]}"
        print(f"oracle failed: {exc}{detail}", file=sys.stderr)
        sys.exit(1)
