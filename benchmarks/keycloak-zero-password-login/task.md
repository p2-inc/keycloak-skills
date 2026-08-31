---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    Two unrelated passwordless mechanisms have to coexist in one flow, and
    each has a different failure mode that produces no error. Keycloak ships
    no flow containing either step, so one must be authored - and the
    add-execution endpoint APPENDS, so an agent that adds the sub-flow before
    the top-level leaves silently ends up with the forms sub-flow ahead of
    auth-cookie. The two authenticators sit as ALTERNATIVE siblings, so
    whichever has the lower priority is the only one a user ever sees unless
    the other is reachable through "Try another way": get that order wrong and
    a user with no passkey lands on a ceremony they cannot complete. WebAuthn
    is built into Keycloak but ext-magic-form comes from an extension, so half
    the flow depends on a jar whose presence has to be checked rather than
    assumed. The WebAuthn passwordless policy is a separate block from the
    ordinary 2FA one, and its rpId defaults to empty - wrong values fail
    client-side inside the browser with nothing in the server log. Outgoing
    SMTP is unconfigured, and the magic-link authenticator deliberately shows
    the identical "check your email" response whether the address exists or
    not, so neither a missing mail server nor its create-user-if-none-exists
    default (which is TRUE, and in a zero-password flow turns the login page
    into open self-registration) is visible from the page. Verifying the
    passkey half at all requires a real browser with a virtual authenticator;
    the crypto exchange cannot be faked with curl.
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
  - passwordless
  - zero-password
  - webauthn
  - magic-link
  - passkey
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
  storage_mb: 12288
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's security team has a new requirement:

> "No more passwords. Staff sign in with a passkey — or, if they haven't set one up yet, we email them a link. Either way there is no password field, ever, for anyone. Marketing is calling it our *0 password required login flow*, so it had better be one flow, not two different login pages."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme` with two staff accounts (`priya`, `marcus`) that currently have no credentials of any kind, and a public browser client, `acme-portal`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

There is no real mail provider here. A local mail-capture server accepts whatever a realm sends and writes each message to `/var/mail-capture/` — connection details are in `/root/mail_server_details.txt`.

A headless Chromium browser with WebAuthn support is available at `/root/.cache/ms-playwright` (installed via the `playwright` Python package already present) — anything actually exercising a passkey ceremony (registering one, authenticating with one) needs a browser that can respond to the WebAuthn API, not a plain HTTP client.

Configure the `acme` realm so that all of the following hold, for a browser authorization-code login against `acme-portal`:

1. The login page for `acme-portal` never shows a password field, under any circumstance — not as a fallback, not as an alternative — and neither `priya` nor `marcus` ends up with a password credential.
2. **Both** passwordless methods work from that one login page: a user can log in with an emailed link, and a user who has a registered passkey can log in with the passkey. A solution where only one of the two works, or where they live on separate clients, does not meet the requirement.
3. Logging in with an emailed link completes for `priya@acme.example`: the browser arrives back at `http://localhost:9999/callback` with an authorization code and the `state` the application sent, unchanged.
4. Starting from their current (credential-less) state, there is a way to get a user a registered passkey without ever setting or emailing them a password — the realm's mail settings and Keycloak's required-action mechanism are the tools available. Once `marcus@acme.example` has one, completing the passkey ceremony with the same authenticator that registered it completes the login, again arriving at the callback with a code and an unchanged `state`.
5. Typing an email address that belongs to no existing account must not create an account and must not send that address any mail. Existing staff only.
6. Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
