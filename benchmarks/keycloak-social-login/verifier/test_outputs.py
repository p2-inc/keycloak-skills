# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

This task is config-state-assertion only - see rubrics/verifier.md for why a
live brokered login against GitHub is neither attempted nor possible in a
no-network sandbox. Everything here is checked through the Admin REST API and
one call to Keycloak's own authorization endpoint (which builds a redirect
entirely from local realm configuration - no outbound call to github.com ever
happens, even though the Location header points at one).
"""

import pathlib
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
GITHUB_DETAILS_PATH = "/root/github_oauth_app_details.txt"
TIMEOUT = 30

# Claim/field names an agent might reach for by copying a standard-OIDC
# mapping pattern (Google/Auth0/generic OIDC) instead of GitHub's real ones.
WRONG_USERNAME_CLAIMS = {"preferred_username", "given_name", "sub", "email"}
WRONG_FIRSTNAME_FIELDS = {"given_name", "first_name"}


def _read_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


@pytest.fixture(scope="session")
def config():
    creds = _read_settings(ADMIN_CREDS_PATH)
    github = _read_settings(GITHUB_DETAILS_PATH)
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
        "github_client_id": github["github_client_id"],
        "github_client_secret": github["github_client_secret"],
    }


@pytest.fixture(scope="session")
def admin_headers(config):
    resp = requests.post(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": config["admin_username"],
            "password": config["admin_password"],
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"admin login failed ({resp.status_code}): {resp.text[:300]}"
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="session")
def github_idp(config, admin_headers):
    """Discover the created identity provider by providerId, not a hardcoded alias."""
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"listing identity providers failed: {resp.text[:300]}"
    idps = resp.json()
    github_idps = [idp for idp in idps if idp.get("providerId") == "github"]
    assert len(github_idps) == 1, (
        f"expected exactly one identity provider with providerId=github, found "
        f"{len(github_idps)}: {[ (i.get('alias'), i.get('providerId')) for i in idps ]}"
    )
    return github_idps[0]


def test_github_is_a_builtin_social_provider_and_enabled(github_idp):
    assert github_idp["providerId"] == "github", (
        f"providerId was {github_idp.get('providerId')!r}, expected the built-in "
        "'github' social provider, not a generic 'oidc'/'saml' configuration"
    )
    assert github_idp.get("enabled") is True, "the GitHub identity provider is not enabled"


def test_client_secret_is_never_returned_in_plaintext(config, admin_headers, github_idp):
    alias = github_idp["alias"]
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances/{alias}",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"fetching the IdP failed: {resp.text[:300]}"
    secret = resp.json().get("config", {}).get("clientSecret", "")
    assert config["github_client_secret"] not in secret, (
        "the fixture GitHub client secret was returned in plaintext by a GET; "
        "Keycloak redacts this by default, so something unusual leaked it"
    )


def _relax_cookies(session):
    """Keycloak marks its auth cookies Secure with SameSite=None.

    A browser sends them anyway over http://localhost, treating it as a secure
    context; `requests` will not, and the follow-up hop then fails as
    cookie_not_found - a property of this test client, not the realm.
    """
    for cookie in session.cookies:
        cookie.secure = False


def _follow_to_github_authorize(config, alias, state, limit=5):
    """Drive kc_idp_hint to its conclusion without ever leaving localhost.

    Keycloak's first hop lands on its own local /broker/{alias}/login endpoint
    (session bookkeeping, still entirely local); the actual redirect out to
    GitHub is the hop after that. Every hop here is a Location header
    Keycloak computes from local realm configuration - no request ever
    reaches github.com, even though the final Location names it.
    """
    session = requests.Session()
    resp = session.get(
        f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth",
        params={
            "client_id": config["client_id"],
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": config["redirect_uri"],
            "state": state,
            "kc_idp_hint": alias,
        },
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    location = resp.headers.get("Location", "")
    for _ in range(limit):
        assert resp.status_code in (302, 303) and location, (
            f"kc_idp_hint={alias} did not produce a redirect chain ending at GitHub "
            f"(got {resp.status_code}, Location={location!r}); the identity provider is "
            "not really wired up for browser login"
        )
        if not location.startswith(config["base"]) and not location.startswith(
            "http://localhost:8080"
        ):
            break
        resp = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = resp.headers.get("Location", "")
    assert location.startswith("https://github.com/login/oauth/authorize"), (
        f"expected the redirect chain to end at GitHub's real authorize endpoint, "
        f"got: {location[:200]}"
    )
    return location


def test_kc_idp_hint_redirects_to_github_with_the_right_client_id(config, admin_headers, github_idp):
    """The strongest wiring proof available without any network access."""
    alias = github_idp["alias"]
    location = _follow_to_github_authorize(config, alias, "verify-github-hint")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert query.get("client_id") == [config["github_client_id"]], (
        f"the redirect's client_id was {query.get('client_id')}, expected the fixture "
        f"GitHub OAuth App's client ID {config['github_client_id']!r}; the credentials "
        "from /root/github_oauth_app_details.txt were not wired into the identity provider"
    )
    return query


def test_redirect_uri_is_discoverable_and_correct(config, github_idp):
    """Requirement 3: the callback URI Keycloak needs registered on GitHub's side.

    Re-derives the standard {baseUrl}/realms/{realm}/broker/{alias}/endpoint shape
    and confirms it is exactly what Keycloak itself sends GitHub as redirect_uri -
    proof the shape is really in effect, not just documented.
    """
    alias = github_idp["alias"]
    expected = f"{config['base']}/realms/{config['realm']}/broker/{alias}/endpoint"
    location = _follow_to_github_authorize(config, alias, "verify-redirect-uri")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert query.get("redirect_uri") == [expected], (
        f"GitHub would be asked to send the browser back to {query.get('redirect_uri')}, "
        f"expected the standard broker endpoint shape {expected!r}"
    )


def _mappers(config, admin_headers, alias):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances/{alias}/mappers",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"listing IdP mappers failed: {resp.text[:300]}"
    return resp.json()


def test_username_is_mapped_from_githubs_login_field_not_an_oidc_standard_claim(
    config, admin_headers, github_idp
):
    """The real discriminator: GitHub sends 'login', never 'preferred_username'.

    An agent that copies the standard OIDC mapping pattern it may have just used
    for Google/Auth0/generic-OIDC providers will leave the Username Template
    Importer's default template ("${ALIAS}.${CLAIM.preferred_username}") in
    place, or otherwise reference an OIDC-standard claim GitHub never sends -
    which resolves to nothing and blanks the imported username.
    """
    alias = github_idp["alias"]
    mappers = _mappers(config, admin_headers, alias)

    username_mappers = [
        m for m in mappers if m.get("identityProviderMapper") == "oidc-username-idp-mapper"
    ]
    assert username_mappers, (
        "no Username Template Importer ('oidc-username-idp-mapper') mapper found on the "
        f"'{alias}' identity provider; found mapper types: "
        f"{[m.get('identityProviderMapper') for m in mappers]}"
    )

    templates = [m.get("config", {}).get("template", "") for m in username_mappers]
    matching = [t for t in templates if "CLAIM.login" in t]
    assert matching, (
        "no username mapper's template references GitHub's real 'login' field "
        f"(CLAIM.login); found template(s): {templates!r}. GitHub's OAuth profile has no "
        "'preferred_username' claim, so the factory-default template resolves to nothing."
    )
    for template in templates:
        for wrong_claim in WRONG_USERNAME_CLAIMS:
            assert f"CLAIM.{wrong_claim}" not in template, (
                f"username template {template!r} references '{wrong_claim}', an "
                "OIDC-standard claim name GitHub does not send; GitHub sends 'login'"
            )


def test_firstname_is_mapped_from_githubs_name_field_with_githubs_own_mapper_type(
    config, admin_headers, github_idp
):
    """The other half of the discriminator.

    GitHub's compatible attribute-mapper type is 'github-user-attribute-mapper'
    (config keys 'jsonField'/'userAttribute'), not the generic OIDC claim mapper
    'oidc-user-attribute-idp-mapper' (config keys 'claim'/'user.attribute') that a
    copy-pasted Google/Auth0 pattern would use. GitHub's profile JSON has one
    'name' field (the whole display name); it has no 'given_name'/'family_name'.
    """
    alias = github_idp["alias"]
    mappers = _mappers(config, admin_headers, alias)

    github_attr_mappers = [
        m for m in mappers if m.get("identityProviderMapper") == "github-user-attribute-mapper"
    ]
    assert github_attr_mappers, (
        "no 'github-user-attribute-mapper' mapper found; if an "
        "'oidc-user-attribute-idp-mapper' was used instead, it is the wrong mapper type for "
        f"GitHub and silently does nothing. Found mapper types: "
        f"{[m.get('identityProviderMapper') for m in mappers]}"
    )

    firstname_mappers = [
        m for m in github_attr_mappers if m.get("config", {}).get("userAttribute") == "firstName"
    ]
    assert firstname_mappers, (
        "no 'github-user-attribute-mapper' mapper targets the 'firstName' user attribute; "
        f"found configs: {[m.get('config') for m in github_attr_mappers]}"
    )

    json_fields = [m.get("config", {}).get("jsonField") for m in firstname_mappers]
    assert "name" in json_fields, (
        f"the mapper targeting firstName reads jsonField {json_fields!r}, expected 'name' "
        "(GitHub's actual display-name field); GitHub does not send 'given_name'"
    )
    for field in json_fields:
        assert field not in WRONG_FIRSTNAME_FIELDS, (
            f"the firstName mapper reads jsonField {field!r}, an OIDC-standard claim name "
            "GitHub does not send - GitHub sends the whole name in a field called 'name'"
        )


def test_only_master_and_acme_realms_exist(config, admin_headers):
    resp = requests.get(
        f"{config['base']}/admin/realms",
        headers=admin_headers,
        params={"briefRepresentation": "true"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
    )
