# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by performing real browser authorization-code logins against
the `acme-portal` client, headlessly, using `account_hint` on the authorization
request the same way a real application would. The verifier does not assume which
of the two valid solution shapes the agent picked (matching an organization's NAME
or its ID via `ext-select-org`'s `match_by_org_name` config) - it discovers which one
is actually configured and drives account_hint accordingly, so either correct
approach passes.

`priya` and `morgan` are seeded in environment/acme-realm.json with passwords and no
organization membership. The agent is expected to have created exactly one
organization and added `priya` (not `morgan`) as a member, authored a custom flow
using `ext-select-org`, and bound it as the realm's browser flow.
"""

import pathlib
import re
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

MEMBER_USERNAME = "priya"
MEMBER_PASSWORD = "Priya!Pass1"
NONMEMBER_USERNAME = "morgan"
NONMEMBER_PASSWORD = "Morgan!Pass1"


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
    return {
        "base": creds["keycloak_base_url"].rstrip("/"),
        "realm": creds["target_realm"],
        "admin_realm": creds["admin_realm"],
        "admin_username": creds["admin_username"],
        "admin_password": creds["admin_password"],
        "client_id": creds["app_client_id"],
        "redirect_uri": creds["app_redirect_uri"],
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


def _find_user_id(config, admin_headers, username):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers,
        params={"username": username, "exact": "true"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user lookup for {username} failed: {resp.text[:300]}"
    matches = resp.json()
    assert matches, f"expected the seeded user {username!r} to still exist"
    return matches[0]["id"]


# The literal value the application in this task's prompt commits to sending as
# account_hint. The app never learns or sends a server-generated organization ID,
# so this fixes the only valid solution shape to match_by_org_name=true with an
# organization literally named "engineering" - a flow configured to match by ID
# instead cannot work for this app no matter how it's set up, and the tests below
# deliberately do NOT adapt to whatever the agent happened to build (that would
# let a by-ID solution pass verification while failing the actual scenario).
ACCOUNT_HINT = "engineering"


@pytest.fixture(scope="session")
def the_organization(config, admin_headers):
    """The organization the agent should have created, via the real p2-inc
    keycloak-orgs REST API (NOT Keycloak's native organizations)."""
    resp = requests.get(
        f"{config['base']}/realms/{config['realm']}/orgs",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"listing organizations failed ({resp.status_code}): {resp.text[:300]}. "
        "The keycloak-orgs extension's REST surface (/realms/{realm}/orgs) must be "
        "reachable - confirm an organization was actually created there, not via "
        "Keycloak's native (unrelated) Organizations feature."
    )
    orgs = resp.json()
    assert len(orgs) == 1, (
        f"expected exactly one organization to exist, found {len(orgs)}: "
        f"{[o.get('name') for o in orgs]}"
    )
    org = orgs[0]
    assert org.get("name") == ACCOUNT_HINT, (
        f"the organization is named {org.get('name')!r}, but the application always "
        f"sends account_hint={ACCOUNT_HINT!r}. Since the application never learns a "
        "server-generated organization ID, the organization's name has to be exactly "
        f"{ACCOUNT_HINT!r} for match_by_org_name matching to ever succeed."
    )
    return org


def _effective_browser_flow_alias(config, admin_headers):
    """The browser flow actually in effect for the app client.

    Two equally valid bindings satisfy this task, and the verifier must accept
    either rather than assuming one:
      * a client-level override on `acme-portal`
        (authenticationFlowBindingOverrides.browser, which holds a flow **id**), or
      * the realm-wide default (realm.browserFlow, which holds a flow **alias**).
    The client override wins when both are present, exactly as Keycloak resolves it.

    Note the flow does NOT have to be a newly-authored one: this Keycloak ships a
    built-in `Org Browser Flow` that already contains ext-select-org, so configuring
    and binding that is a legitimate solution too.
    """
    clients = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/clients",
        headers=admin_headers,
        params={"clientId": config["client_id"]},
        timeout=TIMEOUT,
    )
    assert clients.status_code == 200, f"client lookup failed: {clients.text[:300]}"
    matches = clients.json()
    assert matches, f"the seeded client {config['client_id']!r} no longer exists"
    override_id = (matches[0].get("authenticationFlowBindingOverrides") or {}).get("browser")

    flows = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/authentication/flows",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert flows.status_code == 200, f"flow listing failed: {flows.text[:300]}"
    if override_id:
        by_id = {f.get("id"): f.get("alias") for f in flows.json()}
        alias = by_id.get(override_id)
        assert alias, (
            f"{config['client_id']} has a browser-flow override pointing at flow id "
            f"{override_id!r}, but no flow with that id exists"
        )
        return alias

    realm_rep = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}", headers=admin_headers, timeout=TIMEOUT
    ).json()
    return realm_rep.get("browserFlow")


@pytest.fixture(scope="session")
def match_by_org_name_configured(config, admin_headers, the_organization):
    """Confirm the ext-select-org step in the flow actually in effect for the client
    is configured to match by NAME - the only mode that can work given the fixed
    account_hint value above."""
    flow_alias = _effective_browser_flow_alias(config, admin_headers)
    assert flow_alias, (
        f"no browser flow is in effect for {config['client_id']} - neither a client-level "
        "override nor a realm browserFlow is set"
    )

    executions = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}"
        f"/authentication/flows/{urllib.parse.quote(flow_alias)}/executions",
        headers=admin_headers,
        timeout=TIMEOUT,
    )
    assert executions.status_code == 200, (
        f"could not list executions of bound flow {flow_alias!r}: {executions.text[:300]}"
    )
    match_by_name = None
    for execution in executions.json():
        if execution.get("providerId") != "ext-select-org":
            continue
        config_id = execution.get("authenticationConfig")
        assert config_id, (
            "the ext-select-org execution has no authenticatorConfig attached - "
            "match_by_org_name must be set explicitly"
        )
        cfg = requests.get(
            f"{config['base']}/admin/realms/{config['realm']}/authentication/config/{config_id}",
            headers=admin_headers,
            timeout=TIMEOUT,
        ).json()
        match_by_name = str(cfg.get("config", {}).get("match_by_org_name", "")).lower() == "true"
        break
    # /executions returns the whole tree recursively (level 0 sub-flows, level 1+
    # their executions), so a sub-flow-nested ext-select-org is found by this loop.
    assert match_by_name is not None, (
        f"no ext-select-org execution found anywhere in the bound flow {flow_alias!r}"
    )
    assert match_by_name, (
        "ext-select-org is configured with match_by_org_name=false (matching by ID). "
        "The application only ever sends the literal string 'engineering' as "
        "account_hint, never a server-generated organization ID, so this cannot work - "
        "match_by_org_name must be true."
    )
    return True


def _relax_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html, what):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _authorization_url(config, state, account_hint):
    return (
        f"{config['base']}/realms/{config['realm']}/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": config["client_id"],
                "response_type": "code",
                "scope": "openid",
                "redirect_uri": config["redirect_uri"],
                "state": state,
                "account_hint": account_hint,
            }
        )
    )


def _attempt_login(config, username, password, account_hint, state):
    session = requests.Session()
    page = session.get(_authorization_url(config, state, account_hint), timeout=TIMEOUT)
    assert page.status_code == 200, (
        f"authorization endpoint returned {page.status_code}: {page.text[:200]}"
    )
    _relax_cookies(session)

    submitted = session.post(
        _form_action(page.text, "login"),
        data={"username": username, "password": password, "credentialId": ""},
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    _relax_cookies(session)

    location = submitted.headers.get("Location", "") or ""
    for _ in range(8):
        if not location or location.startswith(config["redirect_uri"]):
            break
        target = location if location.startswith("http") else f"{config['base']}{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "") or ""

    if not location.startswith(config["redirect_uri"]):
        return False, location
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return "code" in query, location


def test_member_with_correct_org_hint_succeeds(
    config, admin_headers, the_organization, match_by_org_name_configured
):
    ok, final = _attempt_login(
        config, MEMBER_USERNAME, MEMBER_PASSWORD, ACCOUNT_HINT, "verify-member-correct-org"
    )
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "member-correct-org.txt").write_text(f"final={final}\n")
    assert ok, (
        f"{MEMBER_USERNAME} is a member of the {ACCOUNT_HINT!r} organization and the "
        f"application sent the correct account_hint ({ACCOUNT_HINT!r}), but the login "
        f"did not complete with an authorization code. Ended at {final[:250]!r}."
    )


def test_member_with_wrong_org_hint_is_rejected(config, the_organization, match_by_org_name_configured):
    bogus_hint = f"not-a-real-org-{ACCOUNT_HINT}"
    ok, final = _attempt_login(
        config, MEMBER_USERNAME, MEMBER_PASSWORD, bogus_hint, "verify-member-wrong-org"
    )
    assert not ok, (
        f"{MEMBER_USERNAME} logged in successfully with a nonsense account_hint "
        f"({bogus_hint!r}) that matches no real organization. The gate must reject "
        "this, not just pass through any login attempt regardless of account_hint."
    )


def test_nonmember_with_correct_org_hint_is_rejected(config, the_organization, match_by_org_name_configured):
    ok, final = _attempt_login(
        config, NONMEMBER_USERNAME, NONMEMBER_PASSWORD, ACCOUNT_HINT, "verify-nonmember"
    )
    assert not ok, (
        f"{NONMEMBER_USERNAME} is NOT a member of the {ACCOUNT_HINT!r} organization but "
        f"completed login anyway with account_hint={ACCOUNT_HINT!r}. This is a "
        "membership gate - only members of the hinted organization may complete "
        f"login through it. Ended at {final[:250]!r}."
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
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
    )
