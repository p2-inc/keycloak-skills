"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by driving real brokered authorization-code logins against the
`acme-portal` client, headlessly: force the redirect to the partner IdP with
`kc_idp_hint`, authenticate there as `jordan`, and follow the round trip back, carrying
`account_hint` on the original authorization request the way a real application would.

The discriminator this task is about: `jordan` ends up a member of whichever organization
*owns* the identity provider (the post-broker flow's `ext-auth-org-add-user` adds him), and
`ext-select-org` then matches `account_hint` against his real memberships. So a hint naming
the owning organization must succeed, and a hint naming a different real organization -
one he was never added to - must be rejected.

The verifier does not assume which organization the agent chose as the owner, nor the
flow's alias (the atomic-flows extension hash-prefixes it). It discovers both, then asserts
behaviour.
"""

import pathlib
import re
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
PARTNER_REALM = "partner-idp"
IDP_USERNAME = "jordan"
IDP_PASSWORD = "P4rtner!Pass"
TIMEOUT = 30


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
def organizations(config, admin_headers):
    """Organizations must come from the keycloak-orgs surface, not Keycloak's native one."""
    r = requests.get(f"{config['base']}/realms/{config['realm']}/orgs",
                     headers=admin_headers, timeout=TIMEOUT)
    assert r.status_code == 200, (
        f"listing organizations failed ({r.status_code}): {r.text[:300]}. The keycloak-orgs "
        "extension's REST surface (/realms/{realm}/orgs) must be reachable - organizations "
        "have to be created there, not via Keycloak's native Organizations feature."
    )
    orgs = r.json()
    assert len(orgs) >= 2, (
        f"expected at least two organizations (one owning the IdP, one the user is NOT a "
        f"member of, so membership can actually be discriminated), found {len(orgs)}: "
        f"{[o.get('name') for o in orgs]}"
    )
    return orgs


@pytest.fixture(scope="session")
def the_idp(config, admin_headers):
    r = requests.get(f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances",
                     headers=admin_headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"idp listing failed: {r.text[:300]}"
    idps = r.json()
    assert len(idps) == 1, (
        f"expected exactly one identity provider brokering the partner realm, found "
        f"{len(idps)}: {[i.get('alias') for i in idps]}"
    )
    return idps[0]


@pytest.fixture(scope="session")
def owning_org(config, admin_headers, organizations, the_idp):
    """The organization the IdP is linked to - the one brokered users get added to."""
    alias = the_idp["alias"]
    owner = None
    for org in organizations:
        linked = requests.get(
            f"{config['base']}/realms/{config['realm']}/orgs/{org['id']}/idps",
            headers=admin_headers, timeout=TIMEOUT)
        if linked.status_code != 200:
            continue
        if alias in {i.get("alias") for i in linked.json()}:
            owner = org
            break
    assert owner, (
        f"identity provider {alias!r} is not linked to any organization. Linking is what makes "
        "it organization-owned; without it the post-broker authenticators "
        "(ext-auth-org-note, ext-auth-org-add-user) have no organization to act on and the "
        "gate is inert."
    )
    return owner


@pytest.fixture(scope="session")
def non_owning_org(organizations, owning_org):
    other = [o for o in organizations if o["id"] != owning_org["id"]]
    assert other, "need a second organization the user is not a member of"
    return other[0]


@pytest.fixture(scope="session")
def post_broker_flow_bound(config, admin_headers, the_idp):
    """A post-broker flow containing ext-select-org must be bound to the IdP.

    Keycloak's stock post-broker flow does not contain ext-select-org, so without a custom
    one account_hint is never evaluated after the IdP round-trip.
    """
    alias = the_idp.get("postBrokerLoginFlowAlias")
    assert alias, (
        f"no postBrokerLoginFlowAlias is bound on {the_idp['alias']!r}. The organization gate "
        "runs *after* the IdP round-trip, so it has to be bound as the identity provider's "
        "post-broker login flow - not as the realm or client browser flow."
    )
    execs = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}"
        f"/authentication/flows/{urllib.parse.quote(alias)}/executions",
        headers=admin_headers, timeout=TIMEOUT)
    assert execs.status_code == 200, f"could not list executions of {alias!r}: {execs.text[:300]}"
    providers = {e.get("providerId") for e in execs.json()}
    assert "ext-select-org" in providers, (
        f"the bound post-broker flow {alias!r} has no ext-select-org execution (found: "
        f"{sorted(p for p in providers if p)}). Keycloak's stock post-broker flow does not "
        "include it, which is exactly why a custom flow has to be authored and bound."
    )
    return alias


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


def _brokered_login(config, idp_alias, account_hint, state):
    """Returns (got_code, final_location). kc_idp_hint isolates the post-broker gate."""
    s = requests.Session()
    url = f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?" + \
        urllib.parse.urlencode({
            "client_id": config["client_id"], "response_type": "code", "scope": "openid",
            "redirect_uri": config["redirect_uri"], "state": state,
            "kc_idp_hint": idp_alias, "account_hint": account_hint,
        })
    page = _hop(s, url, config["base"])
    assert f"/realms/{PARTNER_REALM}/" in page.url, (
        f"kc_idp_hint={idp_alias!r} did not reach the partner realm's login page; ended at "
        f"{page.url[:200]!r}. The identity provider has to broker {PARTNER_REALM}."
    )

    posted = s.post(_form_action(page.text, "partner login"),
                    data={"username": IDP_USERNAME, "password": IDP_PASSWORD, "credentialId": ""},
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
            return False, target      # terminal page (e.g. invalidOrganizationError)
        loc = nxt

    if not loc.startswith(config["redirect_uri"]):
        return False, loc
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    return ("code" in q), loc


def test_member_of_the_owning_org_completes_login(
        config, the_idp, owning_org, post_broker_flow_bound):
    ok, final = _brokered_login(config, the_idp["alias"], owning_org["name"], "verify-member")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "member-login.txt").write_text(f"org={owning_org['name']}\nfinal={final}\n")
    assert ok, (
        f"{IDP_USERNAME} logged in through the identity provider owned by "
        f"{owning_org['name']!r} and account_hint named that same organization, so the login "
        f"had to complete with an authorization code. Ended at {final[:250]!r}."
    )


def test_non_member_of_the_hinted_org_is_rejected(
        config, the_idp, non_owning_org, post_broker_flow_bound):
    ok, final = _brokered_login(config, the_idp["alias"], non_owning_org["name"], "verify-nonmember")
    assert not ok, (
        f"{IDP_USERNAME} completed login with account_hint={non_owning_org['name']!r}, an "
        "organization he is not a member of (the identity provider is owned by a different "
        "one). This is a membership gate - it must reject that, not wave through any login "
        f"that merely carries some account_hint. Ended at {final[:250]!r}."
    )


def test_nonexistent_org_hint_is_rejected(config, the_idp, post_broker_flow_bound):
    ok, final = _brokered_login(config, the_idp["alias"], "no-such-org-xyz", "verify-bogus")
    assert not ok, (
        "login completed with account_hint naming an organization that does not exist at all. "
        f"Ended at {final[:250]!r}."
    )


def test_the_partner_realm_is_unchanged(config, admin_headers):
    """partner-idp belongs to the customer and had to be left alone."""
    base = config["base"]
    clients = requests.get(f"{base}/admin/realms/{PARTNER_REALM}/clients",
                           headers=admin_headers, params={"clientId": "acme-broker"}, timeout=TIMEOUT)
    assert clients.status_code == 200, f"client lookup failed: {clients.text[:300]}"
    matches = [c for c in clients.json() if c.get("clientId") == "acme-broker"]
    assert len(matches) == 1, f"expected the acme-broker client in {PARTNER_REALM}"
    assert matches[0].get("publicClient") is False, (
        "the partner's acme-broker client was changed to a public client"
    )

    users = requests.get(f"{base}/admin/realms/{PARTNER_REALM}/users",
                         headers=admin_headers, params={"max": 200}, timeout=TIMEOUT)
    assert users.status_code == 200, f"user listing failed: {users.text[:300]}"
    assert {u["username"] for u in users.json()} == {IDP_USERNAME}, (
        f"the partner realm's accounts changed; expected exactly {IDP_USERNAME}"
    )

    idps = requests.get(f"{base}/admin/realms/{PARTNER_REALM}/identity-provider/instances",
                        headers=admin_headers, timeout=TIMEOUT)
    assert idps.status_code == 200
    assert idps.json() == [], "identity providers were added to the partner's realm"


def test_only_the_expected_realms_exist(config, admin_headers):
    r = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                     params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert r.status_code == 200, f"realm listing failed: {r.text[:300]}"
    names = {x["realm"] for x in r.json()}
    assert names == {"master", config["realm"], PARTNER_REALM}, (
        f"realms are {sorted(names)}; expected exactly master, {config['realm']} and {PARTNER_REALM}"
    )
