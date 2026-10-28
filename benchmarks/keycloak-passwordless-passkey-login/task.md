---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    Unlike magic-link login, passkey-only login has no bootstrap-free path: a
    user with zero credentials cannot "just click a link" the way magic-link's
    anti-enumeration design allows, because registering a WebAuthn credential
    is itself an authenticated action that needs some prior proof of identity.
    The realistic bootstrap is an admin-triggered required-action email (the
    same mail-delivery dependency as magic-link, plus an extra required-action
    wiring step), and the login flow itself must be authored, not just bound -
    Keycloak ships no built-in "passkey only, no password" flow the way it
    ships a built-in magic-link flow, so the default browser flow's username +
    password step must be removed entirely rather than merely deprioritized,
    or a fallback path silently remains. Getting the realm's WebAuthn
    passwordless policy fields wrong (relying party ID mismatched to the
    serving origin, resident-key/user-verification requirements misconfigured)
    produces a ceremony that fails in the browser with no useful server-side
    error, only a generic exception during the client-side crypto exchange.
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
  - passkey
  - webauthn
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
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCBtY3A6cmVhZCBtY3A6d3JpdGUiLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwibmFtZSI6Ik1DUCBPcGVyYXRvciIsInByZWZlcnJlZF91c2VybmFtZSI6Im1jcC1vcGVyYXRvciIsImdpdmVuX25hbWUiOiJNQ1AiLCJmYW1pbHlfbmFtZSI6Ik9wZXJhdG9yIiwiZW1haWwiOiJtY3Atb3BlcmF0b3JAYWNtZS5leGFtcGxlIiwiaWF0IjoxNzY3MjI1NjAwLCJleHAiOjQ4NTk3NDA4MDAsImp0aSI6InNraWxsc2JlbmNoLWZpeGVkLW1jcC10b2tlbiJ9.ZMkk2DVTDKpIPRLB46ndrsb_ndX_B4JauLPoBwKxsESm0XW9X_eNpYy-Tq7WPPqxWr6nQjORW_8F-szATRQysMQZbCpel9GBeOeJOv0Hn01Sm10sYVUGo5flc4XE-IJ5ftbgLlLN453uw3Zdpni6dTpFTa4Yw-vj1ElAPc-VYcDY3jJxXxbPagaZpfyCgIUQudqK0vnOS48oK-C2FV72SV2pWehkyTNeI4ifA3B5ZfSEk39unb1OxMwYDcpJHEp2eLSnZIJEGbzzcxr4zbuR6Xbs6T_ZftrqX21uk-ORt_hJ35JwXoZavLpXSXmqu1_g8nT3jtETMocl1XbeiYC80Q"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's security team has a new requirement:

> "No more passwords. Staff sign in with a passkey, full stop — no password field, ever, for anyone."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme` with two staff accounts (`priya`, `marcus`) that currently have no credentials of any kind, and a public browser client, `acme-portal`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

There is no real mail provider here. A local mail-capture server accepts whatever a realm sends and writes each message to `/var/mail-capture/` — connection details are in `/root/mail_server_details.txt`.

A headless Chromium browser with WebAuthn support is available at `/root/.cache/ms-playwright` (installed via the `playwright` Python package already present) — anything actually exercising a passkey ceremony (registering one, authenticating with one) needs a browser that can respond to the WebAuthn API, not a plain HTTP client.

Configure the `acme` realm so that all of the following hold, for a browser authorization-code login against `acme-portal`:

1. Neither `priya@acme.example` nor `marcus@acme.example` has a password credential, and the login page for `acme-portal` never shows a password field, under any circumstance — not as a fallback, not as an alternative.
2. Starting from their current (credential-less) state, there is a way to get each of `priya` and `marcus` a registered passkey without ever setting or emailing them a password — the realm's configured mail settings and Keycloak's required-action mechanism are the tools available for this.
3. Once `priya` has a registered passkey, opening the login page for `acme-portal`, entering `priya@acme.example`, and completing the passkey ceremony with the same authenticator that registered it completes the login: the browser arrives back at `http://localhost:9999/callback` with an authorization code, and the `state` value the application sent is returned unchanged.
4. Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
