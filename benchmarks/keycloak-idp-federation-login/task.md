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
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

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
