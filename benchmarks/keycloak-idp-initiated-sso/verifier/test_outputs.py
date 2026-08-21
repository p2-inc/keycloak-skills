"""Pytest-based verifier. Run by BenchFlow after the agent completes.

Nothing is read from agent-produced files. Every assertion comes from firing real portal
tiles at Keycloak: a mock Okta / Entra ID identity provider hand-builds an *unsolicited*
(no `InResponseTo`) SAML response and POSTs it at the broker's IdP-initiated endpoint,

    POST {base}/realms/acme/broker/{alias}/endpoint/clients/{urlName}

then the redirect chain is followed to see **where** and **how** the browser was finally
delivered. See `mock_idp.py`.

The verifier discovers the `{urlName}` values the agent chose by reading them back off the
two clients' attributes - nothing about the names is hardcoded.

**Signature validation is deliberately off** on both fixture identity providers
(`validateSignature=false`, `wantAssertionsSigned=false`). The sandbox is `no-network` and
there is no real Okta or Entra tenant, so the mock's assertion is unsigned. This is a
sanctioned simplification, documented in `task.md` and `rubrics/verifier.md`; it is
orthogonal to everything measured here (which client the tile lands in, and in what
delivery shape).

The decisive check is the OIDC-target *delivery shape*. A tile that "logs someone in"
passes a naive happy-path test even when Keycloak auto-POSTs a SAML form at an OIDC app
that cannot read it. So the OIDC target must be delivered as a plain 302/303 GET redirect
to the app's main page, and explicitly NOT as an HTML auto-POST form.
"""

import pathlib
import sys

import pytest
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mock_idp import VENDORS, deliver_tile, delivered_audiences, tile_endpoint  # noqa: E402

ADMIN_CREDS_PATH = "/root/admin_credentials.txt"
ARTIFACT_DIR = pathlib.Path("/logs/verifier")
TIMEOUT = 30

URL_NAME_ATTR = "saml_idp_initiated_sso_url_name"
# Any one of these, if set, makes Keycloak deliver by POST instead of REDIRECT.
# saml_assertion_consumer_url_post and adminUrl outrank the redirect URL in
# SamlService.getUrlAndBindingForIdpInitiatedSso; saml.force.post.binding overrides the
# choice afterwards in SamlProtocol.isPostBinding().
POST_FORCING = (
    ("attribute", "saml_assertion_consumer_url_post"),
    ("field", "adminUrl"),
    ("attribute", "saml.force.post.binding"),
)


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
        "portal": c["oidc_client_id"],
        "portal_main": c["oidc_client_main_page"],
        "reports": c["saml_client_id"],
        "reports_acs": c["saml_client_acs_url"],
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


def _client(config, admin_headers, client_id):
    r = requests.get(f"{config['base']}/admin/realms/{config['realm']}/clients",
                     headers=admin_headers, params={"clientId": client_id},
                     timeout=TIMEOUT)
    assert r.status_code == 200, f"client lookup failed: {r.text[:300]}"
    matches = [c for c in r.json() if c.get("clientId") == client_id]
    assert len(matches) == 1, (
        f"expected exactly one {client_id!r} client in realm {config['realm']!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


@pytest.fixture(scope="session")
def portal_client(config, admin_headers):
    return _client(config, admin_headers, config["portal"])


@pytest.fixture(scope="session")
def reports_client(config, admin_headers):
    return _client(config, admin_headers, config["reports"])


def _url_name(client, client_id, what):
    """Discover whatever urlName the agent chose - nothing here is hardcoded."""
    value = (client.get("attributes") or {}).get(URL_NAME_ATTR) or ""
    assert value.strip(), (
        f"client {client_id!r} ({what}) has no {URL_NAME_ATTR!r} attribute, so Keycloak's "
        f"IdP-initiated endpoint cannot resolve a tile to it at all "
        f"(SAMLEndpoint.samlIdpInitiatedSSO resolves the target client by matching exactly "
        f"that attribute). Attributes present: "
        f"{sorted((client.get('attributes') or {}).keys())}"
    )
    return value.strip()


@pytest.fixture(scope="session")
def portal_url_name(config, portal_client):
    return _url_name(portal_client, config["portal"], "the OIDC app")


@pytest.fixture(scope="session")
def reports_url_name(config, reports_client):
    return _url_name(reports_client, config["reports"], "the SAML app")


def _post_forcing_report(client):
    found = []
    attributes = client.get("attributes") or {}
    for where, name in POST_FORCING:
        value = (attributes.get(name) if where == "attribute" else client.get(name)) or ""
        value = str(value).strip()
        if not value or value.lower() == "false":
            continue
        label = name if where == "attribute" else f"{name} (Master SAML Processing URL)"
        found.append(f"{label}={value!r}")
    return found


# --- 1. the trap: delivery shape for the OIDC target ---------------------------------


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_oidc_target_is_delivered_by_redirect_not_post(config, portal_url_name,
                                                       portal_client, vendor):
    """A tile aimed at the OIDC app must arrive as a plain browser GET.

    This is the assertion the happy path cannot make. A configuration copied from the SAML
    recipe still "logs the user in" - but delivers an HTML auto-POST form carrying a SAML
    assertion to an OIDC app that has no way to consume a POST body.
    """
    alias = VENDORS[vendor]["alias"]
    delivery = deliver_tile(config["base"], config["realm"], portal_url_name, vendor)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / f"tile-{vendor}-oidc.txt").write_text(
        f"{tile_endpoint(config['base'], config['realm'], alias, portal_url_name)}\n"
        f"{delivery.summary(2000)}\n")

    forcing = _post_forcing_report(portal_client)
    forcing_note = (
        " POST-forcing settings still present on the client: " + ", ".join(forcing) + "."
        if forcing else
        " No POST-forcing setting is present on the client, so the failure is elsewhere."
    )

    assert delivery.kind != "post", (
        f"the {vendor} tile into {config['portal']!r} was delivered as an HTML auto-POST "
        f"form to {delivery.target!r}. {config['portal']} is a plain OIDC web app: it "
        f"cannot consume an incoming SAML POST body, so this has to be a browser redirect "
        f"(GET) to its main page instead.{forcing_note} Keycloak's binding priority is "
        f"saml_assertion_consumer_url_post > adminUrl > saml_assertion_consumer_url_redirect, "
        f"and saml.force.post.binding=true overrides the result afterwards."
    )
    assert delivery.kind == "redirect", (
        f"the {vendor} tile into {config['portal']!r} never reached the app: "
        f"{delivery.summary()}"
    )
    assert delivery.status in (302, 303), (
        f"expected a 302/303 browser redirect, got {delivery.status}: {delivery.summary()}"
    )
    assert (delivery.target or "").startswith(config["portal_main"]), (
        f"the {vendor} tile redirected to {delivery.target!r}, not to "
        f"{config['portal']}'s main page {config['portal_main']!r}"
    )
    assert config["portal"] in delivered_audiences(delivery), (
        f"the delivered SAML response names audiences "
        f"{delivered_audiences(delivery)}, not {config['portal']!r} - the tile resolved to "
        f"the wrong client"
    )


# --- 2. delivery shape for the SAML target -------------------------------------------


@pytest.mark.parametrize("vendor", sorted(VENDORS))
def test_saml_target_is_delivered_by_post_to_its_acs(config, reports_url_name, vendor):
    """POST binding IS correct for a SAML app - it can read the assertion."""
    alias = VENDORS[vendor]["alias"]
    delivery = deliver_tile(config["base"], config["realm"], reports_url_name, vendor)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / f"tile-{vendor}-saml.txt").write_text(
        f"{tile_endpoint(config['base'], config['realm'], alias, reports_url_name)}\n"
        f"{delivery.summary(2000)}\n")

    assert delivery.kind == "post", (
        f"the {vendor} tile into the SAML client {config['reports']!r} should have been "
        f"delivered by POST binding to its assertion consumer service "
        f"{config['reports_acs']!r}; got {delivery.summary()}"
    )
    assert delivery.target == config["reports_acs"], (
        f"delivered to {delivery.target!r}, expected {config['reports_acs']!r}"
    )
    assert delivery.saml_response, "the POST carried no SAMLResponse form field"
    assert config["reports"] in delivered_audiences(delivery), (
        f"the delivered SAML response names audiences {delivered_audiences(delivery)}, "
        f"not {config['reports']!r} - the tile resolved to the wrong client"
    )


# --- 3. RelayState cannot route ------------------------------------------------------


def test_relay_state_cannot_route_to_a_different_client(config, portal_url_name):
    """Which app the tile lands in is the {urlName} path segment, full stop.

    `SAMLEndpoint.handleLoginResponse` takes the clientId branch and never reads the
    inbound RelayState; `samlIdpInitiatedSSO` passes null on. So a provider sending
    RelayState=<the other client's id> must change nothing.
    """
    delivery = deliver_tile(config["base"], config["realm"], portal_url_name, "okta",
                            relay_state=config["reports"])
    assert delivery.kind == "redirect", (
        f"a tile with RelayState={config['reports']!r} broke the delivery into "
        f"{config['portal']!r}: {delivery.summary()}"
    )
    assert (delivery.target or "").startswith(config["portal_main"]), (
        f"a tile whose RelayState named {config['reports']!r} landed at "
        f"{delivery.target!r}. Routing must be decided by the tile's target URL "
        f"({portal_url_name!r}), never by a relay-state value the provider happens to send."
    )
    assert config["portal"] in delivered_audiences(delivery), (
        f"RelayState={config['reports']!r} changed which client the response was built "
        f"for: audiences {delivered_audiences(delivery)}"
    )


# --- 4. the protocol-check asymmetry -------------------------------------------------


def test_direct_saml_endpoint_rejects_the_oidc_client(config, portal_url_name):
    """`SamlService.idpInitiatedSSO` calls isClientProtocolCorrect(); the broker path does
    not. That asymmetry is the whole reason an OIDC app can be a tile target at all."""
    direct = f"{config['base']}/realms/{config['realm']}/protocol/saml/clients/{portal_url_name}"
    r = requests.get(direct, timeout=TIMEOUT, allow_redirects=False)
    assert r.status_code == 400, (
        f"the direct, non-broker endpoint {direct} returned {r.status_code}; it must reject "
        f"an OIDC client with 400 'Wrong client protocol.'"
    )
    assert "Wrong client protocol" in r.text, (
        f"the direct endpoint rejected {config['portal']!r}, but not with the expected "
        f"'Wrong client protocol.' error; body: {r.text[:300]!r}"
    )

    # ...and the broker path, same urlName, resolves and delivers. (Whether the delivery
    # SHAPE is right is the OIDC-target test's job, not this one's - this test is only
    # about the protocol check being present on one endpoint and absent on the other.)
    delivery = deliver_tile(config["base"], config["realm"], portal_url_name, "okta")
    assert delivery.kind in ("redirect", "post"), (
        f"the broker path for the same urlName {portal_url_name!r} should resolve and "
        f"deliver where the direct path is refused on protocol: {delivery.summary()}"
    )
    assert config["portal"] in delivered_audiences(delivery), (
        f"the broker path resolved {portal_url_name!r} to something other than "
        f"{config['portal']!r}: audiences {delivered_audiences(delivery)}"
    )


# --- 5. the fixture was left alone ---------------------------------------------------


def test_both_identity_providers_are_untouched(config, admin_headers):
    r = requests.get(
        f"{config['base']}/admin/realms/{config['realm']}/identity-provider/instances",
        headers=admin_headers, timeout=TIMEOUT)
    assert r.status_code == 200, f"idp listing failed: {r.text[:300]}"
    by_alias = {i["alias"]: i for i in r.json()}
    for alias in sorted({v["alias"] for v in VENDORS.values()}):
        assert alias in by_alias, (
            f"identity provider {alias!r} is gone; the two partner providers were already "
            f"federated and nothing about them was supposed to change. Present: "
            f"{sorted(by_alias)}"
        )
        idp = by_alias[alias]
        assert idp.get("providerId") == "saml", (
            f"{alias!r} now has providerId={idp.get('providerId')!r}, expected 'saml'"
        )
        assert idp.get("enabled") is True, f"{alias!r} was disabled"


def test_only_the_expected_realms_exist(config, admin_headers):
    r = requests.get(f"{config['base']}/admin/realms", headers=admin_headers,
                     params={"briefRepresentation": "true"}, timeout=TIMEOUT)
    assert r.status_code == 200, f"realm listing failed: {r.text[:300]}"
    names = {x["realm"] for x in r.json()}
    assert names == {"master", config["realm"]}, (
        f"realms are {sorted(names)}; expected exactly master and {config['realm']}"
    )
