---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    Two traps, both invisible to a happy-path check. First, the client already exists
    and is stale, so the correct move is to UPDATE it - Keycloak's client PUT replaces
    the whole representation, so a hand-built body (or a delete-and-re-create) silently
    destroys the acme-department protocol mapper the fixture ships. An agent that
    reaches for "create the client" produces a working login on a client that has lost
    configuration nobody asked it to touch. Second, and the actual scored trap:
    redirect URIs and web origins are separate settings, and only the first fails
    loudly. The fixture ships webOrigins empty. Fixing only redirectUris yields a
    client that passes every scripted, server-side login - nothing in a script triggers
    a CORS preflight - and fails only in a real browser, at the token call, after login
    appears to have succeeded. The verifier therefore drives the token endpoint with an
    Origin header and asserts the CORS response header, rather than reading config back
    and calling it done. A third, library-specific detail decides whether the login
    round-trip works at all: oidc-spa redirects to the app's base URL, so the redirect
    URI it needs registered ends with a trailing slash, which is not the shape most
    OIDC examples show.
  category: cybersecurity
  secondary_category: software-engineering
  subcategory: identity-access-management
  category_confidence: high
  task_type:
  - implementation
  modality:
  - json
  - code
  interface:
  - terminal
  skill_type:
  - domain-procedure
  - tool-workflow
  tags:
  - keycloak
  - oidc
  - spa
  - react
  - pkce
  - client-registration
  - cors
verifier:
  type: test-script
  timeout_sec: 600.0
agent:
  timeout_sec: 1800.0
sandbox:
  network_mode: no-network
  build_timeout_sec: 2400.0
  os: linux
  cpus: 2
  memory_mb: 4096
  storage_mb: 12288
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

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's customer portal is a React single-page app. It has no login yet, and the team wants users to
sign in against Acme's own Keycloak.

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme`. It
starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it
answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

The app lives at `/app/frontend` - a Vite + React + TypeScript skeleton with no authentication code
in it. Its dependencies are already installed in `node_modules` and **the sandbox has no network**,
so work with what is installed rather than trying to add packages. `npm run build` works today and
must still work when you are done. In development this app is served by Vite on
**`http://localhost:5173`**.

Realm `acme` already has the browser client the portal is supposed to use, `acme-portal`. It was
registered a long time ago for an older deployment and its settings have not kept up - it is not
currently usable from the Vite dev server. It also carries realm configuration that other systems
depend on, so whatever you do, the client must come out the other side with everything it already
had still intact.

There is one user in the realm you can log in as: `portal-user` / `portal-pass-1`.

Deliver:

1. The React app at `/app/frontend` logs users in against the `acme` realm - a login control that
   sends the user to Keycloak, a logout control, and at least one view that renders something from
   the signed-in user's identity token. Use a library that is already installed.
2. `npm run build` in `/app/frontend` still exits 0.
3. A user who starts at `http://localhost:5173` can complete a full browser login against
   `acme-portal` and get back to the app with tokens - including the browser-side token request
   the app makes after Keycloak redirects it back.
4. `acme-portal` keeps every piece of configuration it already had.

Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
