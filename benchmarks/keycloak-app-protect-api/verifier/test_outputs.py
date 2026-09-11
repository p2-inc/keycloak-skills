# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Verifier for keycloak-app-protect-api.

Asserts on live HTTP behavior of the built app, never on source text: what
matters is what the API accepts and refuses, not how the code was arranged.

The decisive pair is admin-route authorization:
  - alice (has realm role inventory-admin) -> 200 on /api/admin/audit
  - bob   (authenticated, no role)         -> 403 on /api/admin/audit
The first fails when the default SCOPE_-based authorities converter was left in
place (the single most common Keycloak+Spring bug: valid token, every check
denied). The second fails when the gate was faked open or roles were granted
to everyone. Neither can pass vacuously: both users' tokens are minted live
from the fixture realm first, and a liveness test fails loudly if that breaks.

Negatives that must 401: no token, garbage, a re-signed token whose payload
claims the admin role (signature check), and a structurally identical token
from the acme-evil twin realm (issuer + signing-key check).

The over-locking guard: /healthz stays public - monitoring probes it with no
token and must keep getting 200.
"""

import base64
import json

import pytest
import requests

KC = "http://localhost:8080/auth"
API = "http://localhost:8085"
CLIENT_ID = "inventory-cli"


def _password_token(realm: str, username: str, password: str) -> str:
    r = requests.post(
        f"{KC}/realms/{realm}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": username,
            "password": password,
        },
        timeout=15,
    )
    assert r.status_code == 200, (
        f"fixture liveness: could not mint a token for {username}@{realm}: "
        f"{r.status_code} {r.text[:300]}"
    )
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def alice_token() -> str:
    return _password_token("acme", "alice", "alice-pass-1")


@pytest.fixture(scope="module")
def bob_token() -> str:
    return _password_token("acme", "bob", "bob-pass-1")


@pytest.fixture(scope="module")
def evil_alice_token() -> str:
    return _password_token("acme-evil", "alice", "alice-pass-1")


def _get(path: str, token: str | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.get(f"{API}{path}", headers=headers, timeout=15)


# --- fixture liveness -------------------------------------------------------


def test_fixture_tokens_mint_and_carry_expected_roles(alice_token, bob_token):
    """Liveness gate for every negative below: the realm mints tokens, and the
    role split between alice and bob is what the task promised. If this fails,
    nothing else in this file means anything."""

    def claims(tok: str) -> dict:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))

    alice_roles = claims(alice_token).get("realm_access", {}).get("roles", [])
    bob_roles = claims(bob_token).get("realm_access", {}).get("roles", [])
    assert "inventory-admin" in alice_roles, f"alice lacks inventory-admin: {alice_roles}"
    assert "inventory-admin" not in bob_roles, f"bob unexpectedly has inventory-admin: {bob_roles}"


# --- the over-locking guard -------------------------------------------------


def test_healthz_stays_public():
    r = _get("/healthz")
    assert r.status_code == 200, (
        f"/healthz must stay unauthenticated for monitoring, got {r.status_code}"
    )


# --- 401 negatives ----------------------------------------------------------


def test_items_without_token_is_401():
    r = _get("/api/items")
    assert r.status_code == 401, f"unauthenticated /api/items must 401, got {r.status_code}"


def test_admin_without_token_is_401():
    r = _get("/api/admin/audit")
    assert r.status_code == 401, f"unauthenticated /api/admin/audit must 401, got {r.status_code}"


def test_garbage_token_is_401():
    r = _get("/api/items", token="not-a-jwt-at-all")
    assert r.status_code == 401, f"garbage bearer token must 401, got {r.status_code}"


def test_forged_admin_claim_is_401(bob_token):
    """bob's real token, payload doctored to claim inventory-admin, signature
    left as-was: the classic escalation attempt. Only signature verification
    stops it - a decoder that trusts the payload returns 200 here."""
    header, payload, signature = bob_token.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    claims.setdefault("realm_access", {})["roles"] = ["inventory-admin"]
    doctored = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    )
    forged = f"{header}.{doctored}.{signature}"
    r = _get("/api/admin/audit", token=forged)
    assert r.status_code == 401, f"tampered token must 401, got {r.status_code}"


def test_foreign_realm_token_is_401(evil_alice_token):
    """acme-evil's alice: same username, same password, same client id, same
    role name - different issuer, different signing keys. Structurally the
    token is indistinguishable; only issuer/signature validation rejects it."""
    r = _get("/api/items", token=evil_alice_token)
    assert r.status_code == 401, f"foreign-realm token on /api/items must 401, got {r.status_code}"
    r = _get("/api/admin/audit", token=evil_alice_token)
    assert r.status_code == 401, f"foreign-realm token on /api/admin/audit must 401, got {r.status_code}"


# --- positive + authorization split ----------------------------------------


def test_valid_user_reads_items(bob_token):
    r = _get("/api/items", token=bob_token)
    assert r.status_code == 200, f"authenticated /api/items must 200, got {r.status_code}"
    skus = {item.get("sku") for item in r.json()}
    assert "ACME-001" in skus, f"unexpected /api/items body: {r.text[:300]}"


def test_non_admin_gets_403_on_audit(bob_token):
    """403, specifically: authentication succeeded, authorization denied.
    A 401 here means the token was rejected outright - a different bug."""
    r = _get("/api/admin/audit", token=bob_token)
    assert r.status_code == 403, (
        f"authenticated non-admin on /api/admin/audit must 403, got {r.status_code}"
    )


def test_admin_reads_audit(alice_token):
    """THE role-mapping assertion. With the default authorities converter the
    token verifies, alice is authenticated, and this returns 403 - because
    realm_access.roles was never mapped and hasRole never matches."""
    r = _get("/api/admin/audit", token=alice_token)
    assert r.status_code == 200, (
        f"inventory-admin on /api/admin/audit must 200, got {r.status_code} - "
        "if this is 403 while the same token passes /api/items, the realm-role "
        "converter is missing and authorities are still SCOPE_-shaped"
    )
    assert any(row.get("who") == "alice" for row in r.json()), (
        f"unexpected audit body: {r.text[:300]}"
    )
