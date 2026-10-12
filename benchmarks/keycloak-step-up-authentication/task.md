---
schema_version: '1.3'
metadata:
  author_name: Phase Two
  author_email: support@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    Step-up authentication is the most complex login flow in this repo: two trust levels
    with separate expirations, a realm-wide ACR to LoA mapping, per-level conditions with
    config keys that gate execution flow, and application-side token inspection. The
    mechanical risk is high — level order is reversed by a single misplaced priority, and
    the condition config keys are not guessable from Keycloak's UI. Behavioral risk is
    also high: the verifier must check not just "a login completed" but "the right form
    appeared at the right time" (password first on first login; code-only on step-up;
    neither on re-use within 5 minutes) and token-claim facts that only reading the JWT
    reveals. The task also pulls in the full session lifecycle: a user upgrading from
    silver to gold, then gold expiring back to silver, all within one SSO session.
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
  - step-up-authentication
  - acr
  - level-of-authentication
  - mfa
  - self-locking-sessions
verifier:
  type: test-script
  timeout_sec: 600.0
agent:
  timeout_sec: 1800.0
sandbox:
  network_mode: no-network
  build_timeout_sec: 1800.0
  os: linux
  cpus: 2
  memory_mb: 4096
  storage_mb: 10240
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme wants to protect its payments system with step-up authentication: one Keycloak session
with two trust levels that expire separately.

> "Our staff can log in with a password for general work — that's Level 1, `silver`, valid
> for the whole 10-hour session. But when they open the payments page, we want to ask them
> for a one-time code from their authenticator app. If they already have a `silver` session,
> they give only the code — not the password again. That upgrades them to Level 2, `gold`,
> for 5 minutes. After 5 minutes with no activity on the payments page, they drop back to
> `silver` and have to code-in again if they go back to payments. It's a self-locking
> session."

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

- Realm `acme` is Acme's realm. It has two browser applications registered: `acme-portal` (the
  general staff app, redirect URI `http://localhost:9999/callback`) and `acme-payments` (the
  payments gateway, redirect URI `http://localhost:9998/callback`). Both are public OIDC clients.
- Realm `acme` also has two users: `priya` and `morgan`. Each has a password (`Pr1y@Acme2026`
  and `M0rg@n2026` respectively) and a TOTP secret pre-configured in the realm import so the
  verifier can compute their one-time codes without driving the UI.

Configure the `acme` realm so that:

1. One authentication flow with two trust levels exists and is bound to the realm or to one or
   both clients.
   - **Level 1 (`silver`)**: password only, valid for the whole SSO session (10 hours).
   - **Level 2 (`gold`)**: password + one-time code, valid for 5 minutes only.
   - The flow shape is correct: lowest level first; each level a separate sub-flow; level
     conditions REQUIRED (not CONDITIONAL); levels are ALTERNATIVE siblings.

2. A realm attribute `acr.loa.map` maps `{"silver":1,"gold":2}`.

3. The `acme-payments` client is forced to always get `gold` (via `minimum.acr.value`) — even
   if the app doesn't request it, a payment gateway gets the code prompt.

4. Both `priya` and `morgan` can still log in with their passwords and complete TOTP code
   entry. Their passwords are unchanged from the realm import.

5. Realm `acme` has exactly one browser authentication flow bound and configured as above.
   No realm other than `master` and `acme` exists.
