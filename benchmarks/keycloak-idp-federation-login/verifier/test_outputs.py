# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by driving real brokered authorization-code logins against the
`acme-portal` client, headlessly: force the redirect to Contoso's identity provider
with `kc_idp_hint`, authenticate there as a real Contoso staff member, and follow the
round trip back to `http://localhost:9999/callback`.

The distinguishing check for this task (as opposed to its sibling tasks in this repo,
keycloak-corporate-sso-login and keycloak-idp-org-restrict-login) is that this is a
PLAIN login button: no account_hint, no organization membership, no domain routing.
BOTH taylor and morgan - two unrelated Contoso staff, neither singled out - must be
able to complete a login with nothing but valid Contoso credentials. If a setup only
lets one of them through, or requires an account_hint / organization link to succeed,
that is the wrong (adjacent) capability, not this one.

The verifier does not assume which alias the agent chose for the identity provider -
it discovers the single identity provider actually created and drives logins against it.
"""

import pathlib
import urllib.parse
import re

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
CONTOSO_REALM = "contoso-idp"
TIMEOUT = 30

# The same two Contoso staff accounts the fixture realm ships with.
TAYLOR = ("taylor", "C0nt0soT4ylor!", "taylor@contoso.example", "Taylor", "Nguyen")
MORGAN = ("morgan", "C0nt0soM0rgan!", "morgan@contoso.example", "Morgan", "Alvarez")


def _read_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


@pytest.fixture(scope="session")
def config():
    c = _read_settings(ADMIN_CREDS_PATH)
    return {
        "base": c["keycloak_base_url"].rstrip("/"),
        "realm": c["target_realm"],
        "admin_realm": c["admin_realm"],
        "admin_username": c["admin_username"],
        "admin_password": c["admin_password"],
        "client_id": c["app_client_id"],
        "redirect_uri": c["app_redirect_uri"],
    }


@pytest.fixture(scope="session")
def admin_headers(config):
    r = requests.post(
        f"{config['base']}/realms/{config['admin_realm']}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": config["admin_username"], "password": config["admin_password"]},
        timeout=TIMEOUT)
    assert r.status_code == 200, f"admin login failed ({r.status_code}): {r.text[:300]}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def the_idp(config, admin_headers):
    r = requests.get(f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances",
                     headers=admin_headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"idp listing failed: {r.text[:300]}"
    idps = r.json()
    assert len(idps) == 1, (
        f"expected exactly one identity provider brokering Contoso, found {len(idps)}: "
        f"{[i.get('alias') for i in idps]}"
    )
    return idps[0]


def _relax(session):
    for c in session.cookies:
        c.secure = False


def _form_action(html, what):
    m = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert m, f"no form to submit on the {what} page"
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


def _brokered_login(config, idp_alias, username, password, state):
    """Returns (got_code, final_location). No account_hint at all - a plain button."""
    s = requests.Session()
    url = f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?" + \
        urllib.parse.urlencode({
            "client_id": config["client_id"], "response_type": "code", "scope": "openid",
            "redirect_uri": config["redirect_uri"], "state": state,
            "kc_idp_hint": idp_alias,
        })
    page = _hop(s, url, config["base"])
    assert f"/realms/{CONTOSO_REALM}/" in page.url, (
        f"kc_idp_hint={idp_alias!r} did not reach Contoso's login page; ended at "
        f"{page.url[:200]!r}. The identity provider has to broker {CONTOSO_REALM}."
    )

    posted = s.post(_form_action(page.text, "contoso login"),
                    data={"username": username, "password": password, "credentialId": ""},
                    timeout=TIMEOUT, allow_redirects=False)
    _relax(s)

    loc = posted.headers.get("Location", "") or ""
    for _ in range(10):
        if not loc or loc.startswith(config["redirect_uri"]):
            break
        target = loc if loc.startswith("http") else f"{config['base']}{loc}"
        hop = s.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax(s)
        nxt = hop.headers.get("Location", "") or ""
        if not nxt and hop.status_code == 200:
            return False, target
        loc = nxt

    if not loc.startswith(config["redirect_uri"]):
        return False, loc
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    return ("code" in q), loc


def test_taylor_can_log_in_with_no_hint_at_all(config, the_idp):
    """This is the key distinguishing assertion for this task: a plain login button,
    no account_hint, no org membership check."""
    username, password, *_ = TAYLOR
    ok, final = _brokered_login(config, the_idp["alias"], username, password, "verify-taylor")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "taylor-login.txt").write_text(f"final={final}\n")
    assert ok, (
        f"{username} authenticated at Contoso's identity provider with valid credentials and "
        f"should have completed the login with an authorization code. Ended at {final[:250]!r}. "
        "If this fails while some other user succeeds, the setup is gating on something beyond "
        "valid Contoso credentials (an account_hint or organization membership requirement), "
        "which is the wrong, adjacent capability for a plain login button."
    )


def test_morgan_can_also_log_in_with_no_hint_at_all(config, the_idp):
    """A second, unrelated Contoso staff member must ALSO get through - proving there is no
    hidden per-user gate. If only one of taylor/morgan can log in, something is
    (incorrectly) singling out a specific user rather than trusting the IdP generally."""
    username, password, *_ = MORGAN
    ok, final = _brokered_login(config, the_idp["alias"], username, password, "verify-morgan")
    assert ok, (
        f"{username} authenticated at Contoso's identity provider with valid credentials and "
        f"should have completed the login with an authorization code, the same as any other "
        f"Contoso staff member. Ended at {final[:250]!r}."
    )


def test_claims_are_mapped_onto_the_brokered_user(config, admin_headers):
    """After a successful taylor login (driven by the test above), Contoso's email,
    given_name, and family_name claims must have landed on the brokered Keycloak user."""
    username, _, email, first, last = TAYLOR
    r = requests.get(f"{config['base']}/admin/realms/{config['realm']}/users",
                     headers=admin_headers, params={"username": username, "exact": "true"},
                     timeout=TIMEOUT)
    assert r.status_code == 200, f"user lookup failed: {r.text[:300]}"
    matches = r.json()
    assert len(matches) == 1, (
        f"expected exactly one brokered Keycloak user for {username!r}, found {len(matches)}"
    )
    u = matches[0]
    assert u.get("email") == email, f"email={u.get('email')!r}, expected {email!r}"
    assert u.get("firstName") == first, (
        f"firstName={u.get('firstName')!r}, expected {first!r} (from Contoso's given_name claim)"
    )
    assert u.get("lastName") == last, (
        f"lastName={u.get('lastName')!r}, expected {last!r} (from Contoso's family_name claim)"
    )


def test_idp_config_is_sane(the_idp):
    assert the_idp.get("providerId") == "oidc", (
        f"identity provider {the_idp.get('alias')!r} has providerId={the_idp.get('providerId')!r}, "
        "expected 'oidc'"
    )
    assert the_idp.get("enabled") is True, (
        f"identity provider {the_idp.get('alias')!r} is not enabled - the login button would "
        "never appear"
    )


def test_the_contoso_realm_is_unchanged(config, admin_headers):
    """contoso-idp belongs to the customer and had to be left alone."""
    base = config["base"]
    clients = requests.get(f"{base}/admin/realms/{CONTOSO_REALM}/clients",
                           headers=admin_headers, params={"clientId": "acme-app"}, timeout=TIMEOUT)
    assert clients.status_code == 200, f"client lookup failed: {clients.text[:300]}"
    matches = [c for c in clients.json() if c.get("clientId") == "acme-app"]
    assert len(matches) == 1, f"expected the acme-app client in {CONTOSO_REALM}"
    assert matches[0].get("publicClient") is False, (
        "Contoso's acme-app client was changed to a public client"
    )

    users = requests.get(f"{base}/admin/realms/{CONTOSO_REALM}/users",
                         headers=admin_headers, params={"max": 200}, timeout=TIMEOUT)
    assert users.status_code == 200, f"user listing failed: {users.text[:300]}"
    assert {u["username"] for u in users.json()} == {"taylor", "morgan"}, (
        "Contoso's own accounts changed; expected exactly taylor and morgan"
    )

    idps = requests.get(f"{base}/admin/realms/{CONTOSO_REALM}/identity-provider/instances",
                        headers=admin_headers, timeout=TIMEOUT)
    assert idps.status_code == 200
    assert idps.json() == [], "identity providers were added to Contoso's own realm"


def test_only_the_expected_realms_exist(config, admin_headers):
    r = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                     params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert r.status_code == 200, f"realm listing failed: {r.text[:300]}"
    names = {x["realm"] for x in r.json()}
    assert names == {"master", config["realm"], CONTOSO_REALM}, (
        f"realms are {sorted(names)}; expected exactly master, {config['realm']} and {CONTOSO_REALM}"
    )
