---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    Two separate traps, both about trusting a copy-pasted OIDC-standard pattern rather
    than the specific vendor's real shape. First, a scope trap: Keycloak's built-in
    social providers (google, github, microsoft, ...) are hardcoded in Keycloak's own
    Java source to real vendor endpoints - GitHubIdentityProvider.DEFAULT_AUTH_URL is a
    Java constant pointing at https://github.com, not a configurable URL the way a
    generic OIDC/SAML provider's endpoints are - so there is no way to redirect this
    provider at a local fake IdP, and this task is deliberately config-state-assertion
    only rather than a live end-to-end login, in a no-network sandbox where one could
    not be driven anyway. Second, and the actual scored trap: GitHub's OAuth profile
    response does not use OIDC-standard claim names. It returns a single "name" field
    and a separate "login" field for the username - there is no "given_name" or
    "family_name". An agent that has just wired up an OIDC-standard mapping (for
    Google, Auth0, or a generic OIDC intent) and reaches for the same
    given_name/family_name/preferred_username pattern here - or the generic
    "oidc-user-attribute-idp-mapper" mapper type instead of GitHub's own
    "github-user-attribute-mapper" - will produce a configuration that looks complete
    (an IdP exists, mappers exist) but silently maps nothing, because none of those
    fields exist in what GitHub actually sends.
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
  - social-login
  - identity-brokering
  - github
  - oauth2
verifier:
  type: test-script
  timeout_sec: 300.0
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
  # boot publishes the same JWKS and this same token stays valid, scoped only
  # to the throwaway acme realm this task creates fresh each run.
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

Acme wants a "Sign in with GitHub" button on its login page — a plain consumer social login, not a
company's own enterprise identity provider.

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme`. It
starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it
answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

- Realm `acme` has one public browser client, `acme-portal`, whose redirect URI is
  `http://localhost:9999/callback`. It has no identity providers configured yet.
- Acme's engineering team already registered a GitHub OAuth App and handed over the Client ID and
  Client Secret in `/root/github_oauth_app_details.txt`.

Configure the `acme` realm so that:

1. GitHub is available as a login option, as a built-in social identity provider (not a generic
   OIDC/SAML configuration hand-built to point at GitHub's endpoints).
2. The GitHub OAuth App's Client ID and Client Secret from the fixture file are wired into it.
3. The redirect (callback) URI Keycloak needs registered on GitHub's side is discoverable — an
   admin should be able to find it without guessing.
4. GitHub's actual claim names are mapped onto the Keycloak user correctly: GitHub's `login` field
   becomes the user's username, and GitHub's `name` field becomes the user's `firstName`
   attribute. Do not assume `given_name`/`family_name` exist — GitHub's OAuth profile response
   does not send them.

Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
