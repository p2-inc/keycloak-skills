#!/usr/bin/env python3

# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Human-written oracle: portal tiles into one specific app, IdP-initiated.

The whole task lives on the two **clients**, not on the two identity providers. A SAML
identity provider has no IdP-initiated settings at all (verified by enumerating every
getter on `SAMLIdentityProviderConfig`); `saml_idp_initiated_sso_url_name` and
`saml_idp_initiated_sso_relay_state` are client attributes. The IdP's only contribution
is its `alias` appearing in the endpoint URL:

    {base}/realms/{realm}/broker/{alias}/endpoint/clients/{urlName}

Two clients, two different recipes:

  acme-reports (SAML)  just set `saml_idp_initiated_sso_url_name`. The fixture already
                       has `saml_assertion_consumer_url_post`, so Keycloak's binding
                       priority picks POST to the ACS - correct for a SAML app.

  acme-portal (OIDC)   set `saml_idp_initiated_sso_url_name`, and then force the REDIRECT
                       branch, because a plain OIDC web app cannot consume an incoming
                       SAML POST body but can harmlessly ignore query params on a GET.
                       `SamlService.getUrlAndBindingForIdpInitiatedSso` is strict priority:
                         1. saml_assertion_consumer_url_post  -> POST
                         2. else client managementUrl (REST `adminUrl`) -> POST
                         3. else saml_assertion_consumer_url_redirect -> REDIRECT (GET)
                         4. else INVALID_REDIRECT_URI
                       ...and then `SamlProtocol.isPostBinding()` is
                       `POST.equals(clientNote(SAML_BINDING)) || forcePostBinding()`, so
                       `saml.force.post.binding=true` silently overrides a REDIRECT choice
                       from case 3. So reaching case 3 means clearing 1 and 2 AND setting
                       forcePostBinding false. Three settings, any one of which silently
                       re-forces POST.

Client updates go read-merge-PUT: Keycloak's client update is a full-representation PUT,
so PUTting a hand-built partial blanks every field it omits.

Finally the oracle self-checks with the same mock vendor the verifier uses - Okta-flavoured
AND Entra-flavoured tiles into BOTH clients - and only exits 0 if every delivery had the
right shape. A configuration that merely "logs someone in" is not enough.
"""

import pathlib
import sys

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mock_idp import VENDORS, deliver_tile, tile_endpoint  # noqa: E402

CREDS_PATH = "/root/admin_credentials.txt"
TIMEOUT = 30

PORTAL_URL_NAME = "acme-portal-tile"
REPORTS_URL_NAME = "acme-reports-tile"


def load_settings(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def get_admin_token(base, admin_realm, username, password):
    r = requests.post(
        f"{base}/realms/{admin_realm}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli",
              "username": username, "password": password},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def fetch_client(base, realm, token, client_id):
    r = requests.get(f"{base}/admin/realms/{realm}/clients",
                     headers=auth(token), params={"clientId": client_id},
                     timeout=TIMEOUT)
    r.raise_for_status()
    matches = [c for c in r.json() if c.get("clientId") == client_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {client_id!r} client, found {len(matches)}")
    # The list representation is already the full one for clients, but re-read the
    # single resource so the merge below is against exactly what Keycloak would return.
    detail = requests.get(f"{base}/admin/realms/{realm}/clients/{matches[0]['id']}",
                          headers=auth(token), timeout=TIMEOUT)
    detail.raise_for_status()
    return detail.json()


def put_client(base, realm, token, representation):
    r = requests.put(
        f"{base}/admin/realms/{realm}/clients/{representation['id']}",
        headers={**auth(token), "Content-Type": "application/json"},
        json=representation, timeout=TIMEOUT)
    r.raise_for_status()


def configure_saml_target(base, realm, token, client_id, url_name):
    """SAML client: the url name is the only thing missing. POST binding is right here."""
    rep = fetch_client(base, realm, token, client_id)
    attributes = dict(rep.get("attributes") or {})
    attributes["saml_idp_initiated_sso_url_name"] = url_name
    rep["attributes"] = attributes
    put_client(base, realm, token, rep)


def configure_oidc_target(base, realm, token, client_id, url_name, main_page):
    """OIDC client: url name PLUS forcing Keycloak's REDIRECT branch, which means
    clearing the two attributes that outrank it and the flag that overrides it."""
    rep = fetch_client(base, realm, token, client_id)
    attributes = dict(rep.get("attributes") or {})
    attributes["saml_idp_initiated_sso_url_name"] = url_name
    attributes["saml_assertion_consumer_url_redirect"] = main_page
    attributes["saml_assertion_consumer_url_post"] = ""
    attributes["saml.force.post.binding"] = "false"
    rep["attributes"] = attributes
    rep["adminUrl"] = ""
    put_client(base, realm, token, rep)


def expect(delivery, kind, target_prefix, what):
    if delivery.kind != kind or not (delivery.target or "").startswith(target_prefix):
        raise RuntimeError(
            f"{what}: expected a {kind} delivery to {target_prefix!r}, got {delivery.summary()}")
    if not delivery.saml_response:
        raise RuntimeError(f"{what}: delivery carried no SAMLResponse - {delivery.summary()}")


def main():
    creds = load_settings(CREDS_PATH)
    base = creds["keycloak_base_url"].rstrip("/")
    realm = creds["target_realm"]
    portal = creds["oidc_client_id"]
    portal_main = creds["oidc_client_main_page"]
    reports = creds["saml_client_id"]
    reports_acs = creds["saml_client_acs_url"]

    token = get_admin_token(base, creds["admin_realm"], creds["admin_username"],
                            creds["admin_password"])

    print(f"Enabling IdP-initiated SSO on the SAML client {reports!r} "
          f"(urlName={REPORTS_URL_NAME!r}, POST binding to its ACS)...")
    configure_saml_target(base, realm, token, reports, REPORTS_URL_NAME)

    print(f"Enabling IdP-initiated SSO on the OIDC client {portal!r} "
          f"(urlName={PORTAL_URL_NAME!r}, forcing the REDIRECT branch to {portal_main!r})...")
    configure_oidc_target(base, realm, token, portal, PORTAL_URL_NAME, portal_main)

    print("\nSelf-check: firing mock portal tiles from both vendors into both clients.")
    for vendor in ("okta", "entra"):
        alias = VENDORS[vendor]["alias"]

        print(f"  [{vendor}] tile -> {portal} (OIDC): "
              f"{tile_endpoint(base, realm, alias, PORTAL_URL_NAME)}")
        d = deliver_tile(base, realm, PORTAL_URL_NAME, vendor)
        expect(d, "redirect", portal_main, f"{vendor} tile into the OIDC client")
        print(f"        {d.status} redirect (GET) -> {d.target[:110]}")

        print(f"  [{vendor}] tile -> {reports} (SAML): "
              f"{tile_endpoint(base, realm, alias, REPORTS_URL_NAME)}")
        d = deliver_tile(base, realm, REPORTS_URL_NAME, vendor)
        expect(d, "post", reports_acs, f"{vendor} tile into the SAML client")
        print(f"        auto-POST form -> {d.target}")

    print("\nSelf-check: a bogus RelayState must not be able to route the user elsewhere.")
    d = deliver_tile(base, realm, PORTAL_URL_NAME, "okta", relay_state=reports)
    expect(d, "redirect", portal_main,
           "tile into the OIDC client with RelayState naming the other client")
    print(f"        still landed in {portal}: {d.target[:110]}")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" body={exc.response.text[:400]}"
        print(f"oracle failed: {exc}{detail}", file=sys.stderr)
        sys.exit(1)
