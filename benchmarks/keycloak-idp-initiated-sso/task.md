---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    Four traps, and the happy path steps over all of them. (1) Every setting that
    matters lives on the CLIENT, not on the identity provider - which is where almost
    everyone looks first, because the request is phrased entirely in terms of Okta and
    Entra. A SAML identity provider in Keycloak has no IdP-initiated settings at all
    (verified by enumerating every getter on SAMLIdentityProviderConfig); the provider
    contributes nothing but its alias in the endpoint URL. (2) The OIDC target needs
    Keycloak's REDIRECT branch, and reaching it means clearing TWO other attributes
    that silently outrank it - saml_assertion_consumer_url_post, then the client's
    adminUrl (labeled "Master SAML Processing URL", not the similarly-named "Home
    URL"/baseUrl) - plus a saml.force.post.binding flag that silently overrides the
    choice afterwards at response-build time. Any one of the three left set sends an
    HTML auto-POST form at a web app that cannot read a POST body. (3) RelayState looks
    exactly like the routing mechanism - Okta even has a "Default RelayState" field -
    but on this code path Keycloak never reads the inbound value; routing is 100% the
    urlName path segment, so one vendor-side tile serves exactly one client. (4) The
    obvious success check - "a tile logs someone in" - passes even when the delivery
    shape is wrong for an OIDC app, because Keycloak happily builds a SAML response for
    an OIDC client and the SSO cookie is set either way. Only inspecting HOW the browser
    was delivered catches it. There is also an asymmetry worth knowing: the direct
    /protocol/saml/clients/{urlName} endpoint enforces a client-protocol check and the
    broker /broker/{alias}/endpoint/clients/{urlName} one does not - which is the only
    reason an OIDC app can be a tile target at all.
    SANDBOX SIMPLIFICATION: both partner identity providers are configured with
    validateSignature=false and wantAssertionsSigned=false, and the mock vendor that the
    oracle and verifier use POSTs an UNSIGNED SAML response. There is no real Okta or
    Entra tenant and the sandbox is no-network, so signing is deliberately off. This is
    sanctioned and documented (see verifier/rubrics/verifier.md), not an oversight, and
    it is orthogonal to everything measured: which client the tile lands in, and in what
    delivery shape.
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
  - saml
  - idp-initiated-sso
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
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme has two applications registered in realm `acme`:

- `acme-portal` — an **OIDC** browser client. Its main page is `http://localhost:9999/`.
- `acme-reports` — a **SAML** client. Its assertion consumer service is
  `http://localhost:9998/saml/acs`.

Two partner identity providers are already federated into the realm as SAML identity
providers — `okta-sso` and `entra-sso` — and staff already log in through them normally.

Now Acme wants **portal tiles**:

> "When someone clicks our app's tile in Okta's dashboard, or in Entra's My Apps, they
> should land *inside that specific app*, already logged in — without the app having
> started anything."

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the
container and takes a few seconds to come up; `wait-for-services` blocks until it answers.
Admin REST API credentials, and both applications' URLs, are in
`/root/admin_credentials.txt`.

Wire realm `acme` so that, for an unsolicited SAML response arriving from either provider:

1. A tile can target `acme-reports` (the SAML app) and land the user in it.
2. A tile can target `acme-portal` (the OIDC app) and land the user in it — delivered as a
   plain browser **redirect (GET) to the app's main page**, because a plain OIDC web app
   cannot consume an incoming SAML POST body.
3. Which app the user lands in must be decided by the tile's target URL, **not** by any
   relay-state value the provider happens to send.
4. Nothing else about the two identity providers changes, and no realm other than `master`
   and `acme` exists.

The user `taylor` already has a federated identity link at both providers, so a brokered
login for them completes without any account-linking step.

> Note on the sandbox: the two identity providers are configured with signature validation
> off (`validateSignature=false`, `wantAssertionsSigned=false`), because there is no real
> Okta or Entra tenant here and the environment has no network — the responses used to
> exercise the tiles are unsigned. That is a deliberate simplification of the sandbox, not
> part of what you are being asked to configure; leave the providers alone.
