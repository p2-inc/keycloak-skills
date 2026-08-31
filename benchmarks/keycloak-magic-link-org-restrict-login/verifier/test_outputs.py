# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Everything is checked by performing real browser authorization-code logins against the
`acme-portal` client, headlessly, submitting only an email address (no password, ever) on
whatever the flow's first form is, using `account_hint` on the authorization request the
same way a real application would. The verifier does not assume which specific flow alias
or exact authoring path the agent used - it discovers what's actually bound to the client
and inspects its executions, so any correctly-shaped custom flow passes regardless of how
it was authored (importAuthenticationFlow, a manual create-flow/add-execution sequence, or
anything else that produces the right runtime behavior).

`priya` and `morgan` are seeded in environment/acme-realm.json with verified emails and no
organization membership. The agent is expected to have created exactly one organization and
added `priya` (not `morgan`) as a member, configured realm SMTP, authored a custom flow
containing ext-auth-username-auth-note -> ext-select-org -> ext-magic-form IN THAT ORDER, and
bound it as the realm's browser flow.

The behavior actually driven here was empirically confirmed against the real
keycloak-atomic-auth-flows-authored asset (not assumed): submitting an identifier reaches
Keycloak's stock "login-view-email" page directly (no separate redirect for the org check)
when the org check passes, or the stock "login-error" page when it does not - the org check
happens transparently within a single POST, with no visible difference in page structure
between "the org check hasn't run yet" and "the org check passed" until the terminal page.
"""

import glob
import json
import pathlib
import re
import time
import urllib.parse

import pytest
import requests

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
CAPTURE_DIR = "/var/mail-capture"
TIMEOUT = 30

MEMBER_USERNAME = "priya"
MEMBER_EMAIL = "priya@acme-internal.example"
NONMEMBER_USERNAME = "morgan"
NONMEMBER_EMAIL = "morgan@acme-internal.example"

# The literal value the application in this task's prompt commits to sending as
# account_hint. Same reasoning as keycloak-org-restrict-login: the app never learns or
# sends a server-generated organization ID, so this fixes the only valid solution shape
# to match_by_org_name=true with an organization literally named "engineering".
ACCOUNT_HINT = "engineering"


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
    assert resp.status_code == 200, f"admin login failed ({resp.status_code}): {resp.text[:300]}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(scope="session")
def the_organization(config, admin_headers):
    """The organization the agent should have created, via the real p2-inc keycloak-orgs
    REST API (NOT Keycloak's native organizations)."""
    resp = requests.get(
        f"{config['base']}/realms/{config['realm']}/orgs", headers=admin_headers, timeout=TIMEOUT,
    )
    assert resp.status_code == 200, (
        f"listing organizations failed ({resp.status_code}): {resp.text[:300]}. The "
        "keycloak-orgs extension's REST surface (/realms/{realm}/orgs) must be reachable - "
        "confirm an organization was actually created there, not via Keycloak's native "
        "(unrelated) Organizations feature."
    )
    orgs = resp.json()
    assert len(orgs) == 1, f"expected exactly one organization to exist, found {len(orgs)}: {[o.get('name') for o in orgs]}"
    org = orgs[0]
    assert org.get("name") == ACCOUNT_HINT, (
        f"the organization is named {org.get('name')!r}, but the application always sends "
        f"account_hint={ACCOUNT_HINT!r}. Since the application never learns a "
        f"server-generated organization ID, the organization's name has to be exactly "
        f"{ACCOUNT_HINT!r} for match_by_org_name matching to ever succeed."
    )
    return org


def _find_user_id(config, admin_headers, username):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/users",
        headers=admin_headers, params={"username": username, "exact": "true"}, timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"user lookup for {username} failed: {resp.text[:300]}"
    matches = resp.json()
    assert matches, f"expected the seeded user {username!r} to still exist"
    return matches[0]["id"]


def test_member_added_nonmember_left_out(config, admin_headers, the_organization):
    org_id = the_organization["id"]
    member_id = _find_user_id(config, admin_headers, MEMBER_USERNAME)
    nonmember_id = _find_user_id(config, admin_headers, NONMEMBER_USERNAME)

    member_check = requests.get(
        f"{config['base']}/realms/{config['realm']}/orgs/{org_id}/members/{member_id}",
        headers=admin_headers, timeout=TIMEOUT,
    )
    assert member_check.status_code == 204, f"{MEMBER_USERNAME} is not a member of the {ACCOUNT_HINT!r} organization"

    nonmember_check = requests.get(
        f"{config['base']}/realms/{config['realm']}/orgs/{org_id}/members/{nonmember_id}",
        headers=admin_headers, timeout=TIMEOUT,
    )
    assert nonmember_check.status_code == 404, (
        f"{NONMEMBER_USERNAME} was added as a member of the {ACCOUNT_HINT!r} organization - "
        "the negative test case requires a genuine non-member"
    )


def _effective_browser_flow_alias(config, admin_headers):
    """Same resolution order Keycloak itself uses: a client-level override on
    `acme-portal` wins over the realm-wide default."""
    clients = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/clients",
        headers=admin_headers, params={"clientId": config["client_id"]}, timeout=TIMEOUT,
    )
    assert clients.status_code == 200, f"client lookup failed: {clients.text[:300]}"
    matches = clients.json()
    assert matches, f"the seeded client {config['client_id']!r} no longer exists"
    override_id = (matches[0].get("authenticationFlowBindingOverrides") or {}).get("browser")

    flows = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/authentication/flows",
        headers=admin_headers, timeout=TIMEOUT,
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


def _authenticator_config(config, admin_headers, config_id):
    resp = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/authentication/config/{config_id}",
        headers=admin_headers, timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"could not read authenticator config {config_id}: {resp.text[:300]}"
    return resp.json().get("config", {})


@pytest.fixture(scope="session")
def flow_shape(config, admin_headers, the_organization):
    """Confirm the flow actually in effect for the client contains
    ext-auth-username-auth-note -> ext-select-org -> ext-magic-form, IN THAT RELATIVE
    ORDER (the load-bearing property: the org check must run before the send), with the
    two configs this task depends on: match_by_org_name=true and
    ext-magic-create-nonexistent-user=false.

    Executions may live directly on the bound flow or inside a nested sub-flow (the
    natural shape when a cookie/IdP alternative sits alongside a forms sub-flow, as in
    the reference asset) - /executions returns the whole tree, so this walks it flat by
    priority within each parent rather than assuming a specific nesting depth.
    """
    flow_alias = _effective_browser_flow_alias(config, admin_headers)
    assert flow_alias, (
        f"no browser flow is in effect for {config['client_id']} - neither a client-level "
        "override nor a realm browserFlow is set"
    )

    executions = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}"
        f"/authentication/flows/{urllib.parse.quote(flow_alias)}/executions",
        headers=admin_headers, timeout=TIMEOUT,
    )
    assert executions.status_code == 200, (
        f"could not list executions of bound flow {flow_alias!r}: {executions.text[:300]}"
    )
    tree = executions.json()

    by_provider = {}
    for execution in tree:
        provider = execution.get("providerId")
        if provider in ("ext-auth-username-auth-note", "ext-select-org", "ext-magic-form"):
            by_provider[provider] = execution

    missing = {"ext-auth-username-auth-note", "ext-select-org", "ext-magic-form"} - by_provider.keys()
    assert not missing, (
        f"the flow bound as {flow_alias!r} is missing execution(s) {sorted(missing)} - a "
        "magic-link login gated by organization membership needs all three: an identifier "
        "step to establish the user in context, the org gate, and the magic-link send"
    )

    note_level = by_provider["ext-auth-username-auth-note"].get("level")
    select_level = by_provider["ext-select-org"].get("level")
    magic_level = by_provider["ext-magic-form"].get("level")
    note_index = by_provider["ext-auth-username-auth-note"].get("index")
    select_index = by_provider["ext-select-org"].get("index")
    magic_index = by_provider["ext-magic-form"].get("index")
    assert note_level == select_level == magic_level, (
        "the three executions are not siblings within the same sub-flow "
        f"(levels: note={note_level}, select-org={select_level}, magic-form={magic_level}) - "
        "they must run in a single sequential path for ordering to be meaningful"
    )
    assert note_index < select_index < magic_index, (
        "the executions are not in the required order (ext-auth-username-auth-note, then "
        "ext-select-org, then ext-magic-form) - the org check must run BEFORE the magic-link "
        f"send, not after or interleaved. Found indices: note={note_index}, "
        f"select-org={select_index}, magic-form={magic_index}"
    )

    for provider in ("ext-select-org", "ext-magic-form", "ext-auth-username-auth-note"):
        assert by_provider[provider].get("requirement") == "REQUIRED", (
            f"{provider} must be REQUIRED, not {by_provider[provider].get('requirement')!r} - "
            "an ALTERNATIVE org check or magic-link step could be bypassed entirely"
        )

    select_config_id = by_provider["ext-select-org"].get("authenticationConfig")
    assert select_config_id, "ext-select-org has no authenticatorConfig attached - match_by_org_name must be set explicitly"
    select_config = _authenticator_config(config, admin_headers, select_config_id)
    match_by_name = str(select_config.get("match_by_org_name", "")).lower() == "true"
    assert match_by_name, (
        "ext-select-org is configured with match_by_org_name=false (matching by ID). The "
        "application only ever sends the literal string 'engineering' as account_hint, "
        "never a server-generated organization ID, so this cannot work."
    )

    magic_config_id = by_provider["ext-magic-form"].get("authenticationConfig")
    if magic_config_id:
        magic_config = _authenticator_config(config, admin_headers, magic_config_id)
        creates_users = str(magic_config.get("ext-magic-create-nonexistent-user", "true")).lower() == "true"
        assert not creates_users, (
            "ext-magic-form is configured (or left at its factory default) with "
            "ext-magic-create-nonexistent-user=true - this is not itself checked by the "
            "login tests below, but it means an unlisted address routed through a "
            "member's account_hint would still get an account silently provisioned"
        )

    return True


def _relax_cookies(session):
    for cookie in session.cookies:
        cookie.secure = False


def _form_action(html, what):
    match = re.search(r'<form[^>]*action="([^"]+)"', html or "", re.I)
    assert match, f"no form to submit on the {what} page"
    return match.group(1).replace("&amp;", "&")


def _page_id(html):
    match = re.search(r'data-page-id="([^"]+)"', html or "")
    return match.group(1) if match else None


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


def _latest_capture_for(email, since):
    marker = email.replace("@", "-at-")
    matches = sorted(pathlib.Path(CAPTURE_DIR).glob(f"*{marker}*.json"))
    for path in reversed(matches):
        record = json.loads(path.read_text())
        if record["received_at"] >= since:
            return record
    return None


def _follow_to_redirect_uri(session, config, location, limit=8):
    for _ in range(limit):
        if not location or location.startswith(config["redirect_uri"]):
            return location
        target = location if location.startswith("http") else f"{config['base']}{location}"
        hop = session.get(target, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)
        location = hop.headers.get("Location", "") or ""
    return location


def _submit_identifier(config, email, account_hint, state):
    """Submits the email on whatever form the flow's first step renders. Returns
    (session, page_id_or_None_if_redirected, location_if_redirected)."""
    session = requests.Session()
    page = session.get(_authorization_url(config, state, account_hint), timeout=TIMEOUT)
    assert page.status_code == 200, f"authorization endpoint returned {page.status_code}: {page.text[:200]}"
    _relax_cookies(session)

    submitted = session.post(
        _form_action(page.text, "identifier"), data={"username": email}, timeout=TIMEOUT, allow_redirects=False,
    )
    _relax_cookies(session)

    if submitted.status_code in (302, 303):
        location = _follow_to_redirect_uri(session, config, submitted.headers.get("Location", ""))
        if location.startswith(config["redirect_uri"]):
            return session, None, location
        submitted = session.get(location, timeout=TIMEOUT, allow_redirects=False)
        _relax_cookies(session)

    return session, _page_id(submitted.text), None


def test_member_with_correct_hint_gets_mail_and_completes(config, flow_shape):
    since = time.time()
    session, page_id, location = _submit_identifier(config, MEMBER_EMAIL, ACCOUNT_HINT, "verify-member-correct")
    assert page_id == "login-view-email", (
        f"{MEMBER_USERNAME} is a member of the {ACCOUNT_HINT!r} organization and the "
        f"application sent the correct account_hint, but submitting the email did not reach "
        f"the magic-link 'check your email' page (page_id={page_id!r}, location={location!r})"
    )

    record = None
    for _ in range(10):
        record = _latest_capture_for(MEMBER_EMAIL, since)
        if record:
            break
        time.sleep(0.5)
    assert record is not None, f"no mail was captured for {MEMBER_EMAIL} - realm SMTP is likely misconfigured"

    body = record.get("body_plain") or record.get("body_html") or ""
    link_match = re.search(r"(http://\S*action-token\S*)", body)
    assert link_match, f"no action-token link found in captured mail: {body[:200]}"
    link = link_match.group(1).rstrip(".,)")

    opened = session.get(link, timeout=TIMEOUT, allow_redirects=False)
    _relax_cookies(session)
    final = _follow_to_redirect_uri(session, config, opened.headers.get("Location", ""))
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "member-correct-hint.txt").write_text(f"final={final}\n")
    assert final.startswith(config["redirect_uri"]), f"the magic link never returned to {config['redirect_uri']}: {final!r}"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
    assert "code" in query, f"no authorization code returned: {final[:250]!r}"


def test_nonmember_with_correct_hint_gets_no_mail(config, flow_shape):
    since = time.time()
    session, page_id, location = _submit_identifier(config, NONMEMBER_EMAIL, ACCOUNT_HINT, "verify-nonmember")
    assert page_id != "login-view-email" and location is None, (
        f"{NONMEMBER_USERNAME} is NOT a member of the {ACCOUNT_HINT!r} organization but "
        f"reached the magic-link 'check your email' page anyway (page_id={page_id!r}, "
        f"location={location!r}) - this is a membership gate; only members of the hinted "
        "organization may ever receive a login link"
    )

    time.sleep(1.5)
    record = _latest_capture_for(NONMEMBER_EMAIL, since)
    assert record is None, (
        f"mail was sent to {NONMEMBER_EMAIL} despite {NONMEMBER_USERNAME} not being a member "
        f"of the {ACCOUNT_HINT!r} organization - the org check must run BEFORE the send, not "
        "merely reject the completed login afterward"
    )


def test_member_with_bogus_hint_gets_no_mail(config, flow_shape):
    since = time.time()
    bogus_hint = f"not-a-real-org-{ACCOUNT_HINT}"
    session, page_id, location = _submit_identifier(config, MEMBER_EMAIL, bogus_hint, "verify-bogus-org")
    assert page_id != "login-view-email" and location is None, (
        f"{MEMBER_USERNAME} reached the magic-link page using a nonsense account_hint "
        f"({bogus_hint!r}) that matches no real organization. The gate must reject this, not "
        "just pass through any login attempt regardless of account_hint."
    )

    time.sleep(1.5)
    record = _latest_capture_for(MEMBER_EMAIL, since)
    assert record is None, (
        f"mail was sent to {MEMBER_EMAIL} despite an account_hint ({bogus_hint!r}) matching no "
        "real organization - this proves the gate checks the SPECIFIC hinted organization's "
        "membership, not merely 'is a member of something'"
    )


def test_only_the_expected_realms_exist(config, admin_headers):
    resp = requests.get(
        f"{config['base']}/admin/realms", headers=admin_headers, params={"briefRepresentation": "true"}, timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"realm listing failed: {resp.text[:300]}"
    names = {r["realm"] for r in resp.json()}
    assert names == {"master", config["realm"]}, f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
