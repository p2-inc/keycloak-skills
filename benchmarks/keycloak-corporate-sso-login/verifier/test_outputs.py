# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by performing real browser authorization-code logins against
the `acme-portal` client, headlessly: fetch the login page, submit an email
address, and follow wherever Keycloak sends the browser. A corporate address has
to end up authenticating at the customer's identity provider and come back with a
code; an internal address has to still get a password form.

Both corporate accounts are exercised, so a configuration that happens to work
for one hardcoded user does not pass.
"""

import pathlib
import re
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
IDP_DETAILS_PATH = "/root/corporate_idp_details.txt"
CUSTOMER_REALM = "contoso-idp"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

# Seeded in environment/contoso-idp-realm.json. Acme holds no passwords for these.
CORPORATE_ACCOUNTS = {
    "jvega@contoso.example": "C0nt0so!Pass",
    "rkhan@contoso.example": "C0nt0so!Rk26",
}
# Seeded in environment/acme-realm.json.
INTERNAL_USERNAME = "dana@acme-internal.example"
INTERNAL_PASSWORD = "Ac1me!Internal"

CUSTOMER_AUTH_PATH = f"/realms/{CUSTOMER_REALM}/protocol/openid-connect/auth"


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
    idp = _read_settings(IDP_DETAILS_PATH)
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
        "email_domain": idp["email_domain"],
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


def _relax_cookies(session):
    """Keycloak marks its auth cookies Secure with SameSite=None.

    A browser sends them anyway over http://localhost, treating it as a secure
    context; `requests` will not. Clearing the flag reproduces what a browser
    does. Without it every form POST fails as `cookie_not_found`, which is a
    property of this test client and not of the realm being tested.
    """
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html, what):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _authorization_url(config, state):
    return (
        f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": config["client_id"],
                "response_type": "code",
                "scope": "openid email",
                "redirect_uri": config["redirect_uri"],
                "state": state,
                "nonce": f"nonce-{state}",
            }
        )
    )


def _identify(session, config, state, email):
    """Open the login page and submit an email address."""
    page = session.get(_authorization_url(config, state), timeout=TIMEOUT)
    assert page.status_code == 200, (
        f"the authorization endpoint returned {page.status_code}: {page.text[:200]}"
    )
    _relax_cookies(session)
    resp = session.post(
        _form_action(page.text, "login"),
        data={"username": email},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)
    return resp


def _follow_to_redirect_uri(session, location, redirect_uri, limit=8):
    for _ in range(limit):
        if not location:
            return None
        if location.startswith(redirect_uri):
            return location
        target = (
            location if location.startswith("http") else f"http://localhost:8080{location}"
        )
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "")
    return None


def _route_to_customer_idp(session, identified, limit=5):
    """Follow the SSO route to wherever it lands.

    Keycloak takes two different shapes here, both legitimate, so both are
    followed rather than only the one that happens to appear first:
      * a user not yet federated gets a page offering the provider as a link;
      * a user already federated gets a 302 straight at the broker endpoint,
        carrying a login_hint.
    Either way the broker endpoint then redirects on to the customer's IdP.
    """
    location = identified.headers.get("Location", "")
    if not location:
        link = re.search(r'href="([^"]*?/broker/[^"]*?/login[^"]*)"', identified.text or "")
        if link:
            location = link.group(1).replace("&amp;", "&")

    for _ in range(limit):
        if not location or CUSTOMER_AUTH_PATH in location:
            return location
        target = (
            location if location.startswith("http") else f"http://localhost:8080{location}"
        )
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        next_location = hop.headers.get("Location", "")
        if not next_location:
            link = re.search(
                r'href="([^"]*?/broker/[^"]*?/login[^"]*)"', hop.text or ""
            )
            next_location = link.group(1).replace("&amp;", "&") if link else ""
        location = next_location
    return location


@pytest.mark.parametrize("email", sorted(CORPORATE_ACCOUNTS))
def test_a_corporate_address_is_never_asked_for_an_acme_password(config, email):
    session = requests.Session()
    identified = _identify(session, config, "no-password", email)
    body = identified.text or ""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / f"identify-{email.replace('@', '-at-')}.html").write_text(body[:8000])

    assert 'type="password"' not in body, (
        f"{email} was shown an Acme password field. A corporate address must be "
        "sent to the customer's identity provider instead of being asked for a "
        "local password."
    )


@pytest.mark.parametrize("email", sorted(CORPORATE_ACCOUNTS))
def test_a_corporate_address_is_routed_to_the_customer_idp(config, email):
    session = requests.Session()
    identified = _identify(session, config, "routing", email)
    location = _route_to_customer_idp(session, identified)
    assert CUSTOMER_AUTH_PATH in (location or ""), (
        f"{email} was not routed to the customer's identity provider. Ended up "
        f"at {location[:200]!r}. Routing has to follow the email domain."
    )


@pytest.mark.parametrize("email", sorted(CORPORATE_ACCOUNTS))
def test_corporate_sso_login_completes_and_returns_a_code(config, email):
    """The full round trip: Acme -> customer IdP -> authenticate -> back to the app."""
    state = f"verify-{email.split('@')[0]}"
    session = requests.Session()

    identified = _identify(session, config, state, email)
    location = _route_to_customer_idp(session, identified)
    assert CUSTOMER_AUTH_PATH in (location or ""), (
        f"{email} never reached the customer's identity provider"
    )

    customer_page = session.get(location, timeout=TIMEOUT)
    assert customer_page.status_code == 200, (
        f"the customer's login page returned {customer_page.status_code}"
    )
    _relax_cookies(session)

    returned = session.post(
        _form_action(customer_page.text, "customer login"),
        data={
            "username": email,
            "password": CORPORATE_ACCOUNTS[email],
            "credentialId": "",
        },
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)

    final = _follow_to_redirect_uri(
        session, returned.headers.get("Location", ""), config["redirect_uri"]
    )
    assert final, (
        f"after authenticating at the customer's IdP, {email} never arrived back "
        f"at {config['redirect_uri']}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned: {final[:250]}"
    assert query.get("state") == [state], (
        f"state was not preserved: sent {state!r}, got {query.get('state')!r}"
    )


def test_corporate_users_are_federated_and_hold_no_local_password(config, admin_headers):
    """They must exist in acme linked to the provider, without a password here."""
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers,
        params={"max": 200},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user listing failed: {resp.text[:300]}"
    by_email = {u.get("email"): u for u in resp.json() if u.get("email")}

    summary = []
    for email in sorted(CORPORATE_ACCOUNTS):
        assert email in by_email, (
            f"no user with email {email} exists in the {config['realm']} realm "
            f"after a successful corporate login. Found: {sorted(by_email)}"
        )
        user = by_email[email]

        federated = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}"
            f"/users/{user['id']}/federated-identity",
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert federated.status_code == 200, (
            f"federated identity lookup for {email} failed: {federated.text[:200]}"
        )
        providers = [f.get("identityProvider") for f in federated.json()]
        assert providers, (
            f"{email} exists in {config['realm']} but is not linked to any "
            "identity provider, so the account was created locally rather than "
            "federated from the customer's IdP"
        )

        credentials = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}"
            f"/users/{user['id']}/credentials",
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert credentials.status_code == 200, (
            f"credential lookup for {email} failed: {credentials.text[:200]}"
        )
        types = [c.get("type") for c in credentials.json()]
        assert "password" not in types, (
            f"{email} holds a password in the {config['realm']} realm "
            f"(credentials: {types}). Acme must not hold passwords for the "
            "customer's staff."
        )
        summary.append(f"{email} federated={providers} credentials={types}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "federated-users.txt").write_text("\n".join(summary))


def test_an_internal_address_still_logs_in_with_its_password(config):
    """The password path must survive: identity-first, then password, then a code."""
    state = "verify-internal"
    session = requests.Session()

    identified = _identify(session, config, state, INTERNAL_USERNAME)
    body = identified.text or ""
    assert 'type="password"' in body, (
        f"{INTERNAL_USERNAME} was not offered a password field. Internal staff "
        "must still authenticate with the password they already have; a "
        "redirector that forwards everyone to the customer's IdP breaks this."
    )

    submitted = session.post(
        _form_action(body, "password"),
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
        session, submitted.headers.get("Location", ""), config["redirect_uri"]
    )
    assert final, (
        f"{INTERNAL_USERNAME} could not complete a password login; never reached "
        f"{config['redirect_uri']}"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, (
        f"no authorization code for the internal login: {final[:250]}"
    )


def test_the_customer_realm_is_unchanged(config, admin_headers):
    """contoso-idp belongs to the customer and had to be left alone."""
    base = config["base"]

    clients = requests.get(
        f"{base}/admin/realms/{CUSTOMER_REALM}/clients",
        headers=admin_headers,
        params={"clientId": "acme-broker"},
        timeout=TIMEOUT,
    )
    assert clients.status_code == 200, f"client lookup failed: {clients.text[:300]}"
    matches = [c for c in clients.json() if c.get("clientId") == "acme-broker"]
    assert len(matches) == 1, (
        f"expected the acme-broker client in {CUSTOMER_REALM}, found {len(matches)}"
    )
    broker = matches[0]
    assert broker.get("publicClient") is False, (
        "the customer's acme-broker client was changed to a public client"
    )
    assert broker.get("redirectUris") == [
        "http://localhost:8080/auth/realms/acme/broker/*"
    ], (
        f"the customer's whitelisted redirect URIs were changed to "
        f"{broker.get('redirectUris')}"
    )

    secret = requests.get(
        f"{base}/admin/realms/{CUSTOMER_REALM}/clients/{broker['id']}/client-secret",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert secret.status_code == 200, f"secret lookup failed: {secret.text[:200]}"
    assert secret.json().get("value") == "broker-secret-8f2a1c", (
        "the customer's client secret was rotated; that credential belongs to them"
    )

    users = requests.get(
        f"{base}/admin/realms/{CUSTOMER_REALM}/users",
        headers=admin_headers,
        params={"max": 200},
        timeout=TIMEOUT,
    )
    assert users.status_code == 200, f"user listing failed: {users.text[:300]}"
    usernames = {u["username"] for u in users.json()}
    assert usernames == {"jvega", "rkhan"}, (
        f"the customer realm's accounts are now {sorted(usernames)}; expected "
        "exactly jvega and rkhan"
    )

    idps = requests.get(
        f"{base}/admin/realms/{CUSTOMER_REALM}/identity-provider/instances",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert idps.status_code == 200, f"idp listing failed: {idps.text[:300]}"
    assert idps.json() == [], (
        f"identity providers were added to the customer's realm: "
        f"{[i.get('alias') for i in idps.json()]}"
    )


def test_only_the_expected_realms_exist(config, admin_headers):
    resp = requests.get(
        f"{config['base']}/admin/realms",
        headers=admin_headers,
        params={"briefRepresentation": "true"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"], CUSTOMER_REALM}, (
        f"realms are {sorted(names)}; expected exactly master, "
        f"{config['realm']} and {CUSTOMER_REALM}"
    )
