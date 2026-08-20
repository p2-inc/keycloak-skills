---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    The gate runs *after* an external identity provider has already authenticated the
    user, so it lives on a binding surface most people never touch: the identity
    provider's own postBrokerLoginFlowAlias, not the realm or client browser flow.
    Keycloak ships a stock post-broker flow, but it does not contain ext-select-org -
    bind that one and account_hint is simply never evaluated, so every login succeeds
    and the configuration looks done. The organization gate is also inert unless the
    identity provider is *linked* to an organization: ext-auth-org-add-user and
    ext-auth-org-note both key off that ownership and silently no-op without it, which
    means a setup can have the right flow bound and still gate nothing. Finally the
    obvious check - "a valid user with valid credentials gets in" - passes even when
    membership is never inspected, so proving the gate works at all requires a user who
    is genuinely not a member of the hinted organization.

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
  - organizations
  - identity-brokering
  - post-broker-login
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

Acme has just onboarded Partner Industries as a federated customer.

> "Partner staff sign in with their own company account. But our app serves several teams, and a person should only get in when they actually belong to the team the app is asking for."

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

- Realm `acme` is Acme's own realm. It has one browser application registered, the public client `acme-portal`, whose redirect URI is `http://localhost:9999/callback`. It has no organizations and no identity provider yet.
- Realm `partner-idp` stands in for Partner Industries' own identity provider, which they operate. It holds one staff account, `jordan` / `P4rtner!Pass`. The federation details their IT team supplied — endpoints, client ID, client secret — are in `/root/partner_idp_details.txt`. Treat that realm as belonging to the customer: do not change anything inside it.

Acme's portal sends the team it wants as `account_hint=<team>` on the authorization request, and forces the partner provider with `kc_idp_hint=<your idp alias>`.

Configure the `acme` realm so that, for a browser authorization-code login against `acme-portal`:

1. Two teams exist as organizations. Partner Industries' identity provider belongs to one of them — call it the *owning* team — so staff arriving through it are recognised as that team's members.
2. `jordan` authenticating at the partner provider with `account_hint` naming the owning team arrives back at `http://localhost:9999/callback` with an authorization code.
3. `jordan` authenticating the same way, but with `account_hint` naming the *other* team — one he does not belong to — does **not** receive an authorization code.
4. The same holds for an `account_hint` naming a team that does not exist at all.
5. Realm `partner-idp` is unchanged, and no realm other than `master`, `acme` and `partner-idp` exists.
