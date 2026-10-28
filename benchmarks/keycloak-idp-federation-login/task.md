---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    The mechanical steps are the easy, well-documented half: broker an OIDC provider,
    add three attribute mappers, done. The trap is that this repo has two sibling
    identity-brokering tasks that look superficially similar and use the exact same
    admin toolchain - keycloak-corporate-sso-login (route to the IdP by the email
    domain the user types, via organization "verified domains") and
    keycloak-idp-org-restrict-login (gate a brokered login on organization
    membership via a custom post-broker flow and account_hint). An agent that has
    just solved either of those, or that pattern-matches "identity provider" to
    "organizations", reaches reflexively for an account_hint requirement or an
    organization link here - and produces a configuration that looks done (the IdP
    exists, a real user can log in) but fails the actual requirement: a plain login
    button must let in ANY valid Contoso account, with nothing tied to organization
    membership and nothing auto-routed by email domain. Proving that requires testing
    with two different, unrelated users and no hint of any kind, not just "a valid
    user with valid credentials gets in" - which passes even on the wrong,
    over-restricted setup.
  category: cybersecurity
  secondary_category: software-engineering
  subcategory: identity-access-management
  category_confidence: high
  task_type:
  - implementation
  modality:
  - json
  interface:
  - terminal
  skill_type:
  - domain-procedure
  - tool-workflow
  tags:
  - keycloak
  - identity-brokering
  - oidc
  - attribute-mapping
verifier:
  type: test-script
  timeout_sec: 420.0
agent:
  timeout_sec: 1800.0
sandbox:
  network_mode: no-network
  build_timeout_sec: 1800.0
  os: linux
  cpus: 2
  memory_mb: 4096
  storage_mb: 10240
  # The keycloak-MCP-server jar runs in-container against the acme realm below.
  # The bearer token is a fixture, not a secret: it is signed with a private key
  # baked into environment/acme-realm.json (the same fixed, non-random signing
  # key used by the other MCP-wired tasks in this repo), so every container
  # boot publishes the same JWKS and this same token stays valid.
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCBtY3A6cmVhZCBtY3A6d3JpdGUiLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwibmFtZSI6Ik1DUCBPcGVyYXRvciIsInByZWZlcnJlZF91c2VybmFtZSI6Im1jcC1vcGVyYXRvciIsImdpdmVuX25hbWUiOiJNQ1AiLCJmYW1pbHlfbmFtZSI6Ik9wZXJhdG9yIiwiZW1haWwiOiJtY3Atb3BlcmF0b3JAYWNtZS5leGFtcGxlIiwiaWF0IjoxNzY3MjI1NjAwLCJleHAiOjQ4NTk3NDA4MDAsImp0aSI6InNraWxsc2JlbmNoLWZpeGVkLW1jcC10b2tlbiJ9.ZMkk2DVTDKpIPRLB46ndrsb_ndX_B4JauLPoBwKxsESm0XW9X_eNpYy-Tq7WPPqxWr6nQjORW_8F-szATRQysMQZbCpel9GBeOeJOv0Hn01Sm10sYVUGo5flc4XE-IJ5ftbgLlLN453uw3Zdpni6dTpFTa4Yw-vj1ElAPc-VYcDY3jJxXxbPagaZpfyCgIUQudqK0vnOS48oK-C2FV72SV2pWehkyTNeI4ifA3B5ZfSEk39unb1OxMwYDcpJHEp2eLSnZIJEGbzzcxr4zbuR6Xbs6T_ZftrqX21uk-ORt_hJ35JwXoZavLpXSXmqu1_g8nT3jtETMocl1XbeiYC80Q"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme wants to let a partner company, Contoso, log in to Acme's app using Contoso's own
identity provider — a plain login button on Acme's login page.

> "Contoso's IT team already registered our app as an OIDC client in their identity
> system and handed over a client ID, client secret, and their issuer URL. Any of
> their staff with a valid Contoso account should be able to sign in — this has
> nothing to do with organizations or teams, and we're not routing people there by
> email domain. Just a normal 'log in with Contoso' button."

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

- Realm `acme` is Acme's own realm. It has one browser application registered, the public client `acme-portal`, whose redirect URI is `http://localhost:9999/callback`. It has no identity provider yet.
- Realm `contoso-idp` stands in for Contoso's own identity provider, which Contoso operates — treat it as belonging to a separate company; do not change anything inside it. It holds two staff accounts who are otherwise unrelated to each other, `taylor` and `morgan`. The federation details Contoso's IT team supplied — endpoints, client ID, client secret — are in `/root/contoso_idp_details.txt`, along with both staff members' credentials.

Configure the `acme` realm so that, for a browser authorization-code login against `acme-portal`:

1. Contoso is added as an identity provider a user can choose to log in with.
2. Both `taylor` and `morgan` — two unrelated Contoso staff, neither singled out — can complete a login and land back at `http://localhost:9999/callback` with an authorization code. There must be **no** hidden per-user or per-organization gate: if the setup requires any `account_hint` or organization membership to succeed, or if it only lets one of the two through, that's the wrong capability — this is a plain login button, not an organization-restricted or domain-routed one.
3. Contoso's `email`, `given_name`, and `family_name` claims land on the brokered Keycloak user as `email`, `firstName`, and `lastName` respectively.
4. Realm `contoso-idp` is unchanged, and no realm other than `master`, `acme`, and `contoso-idp` exists.
