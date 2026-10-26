---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    The two methods must be ALTERNATIVES, not two factors, and the wrong shape
    produces no error. Keycloak ships no flow offering a passkey beside the
    password form, so one must be authored - and the add-execution endpoint
    APPENDS, so an agent that adds the sub-flow before the top-level leaves
    silently ends up with the forms sub-flow ahead of auth-cookie. Making the
    passkey REQUIRED after the password, or putting it in a conditional
    sub-flow for users who have one, still "adds passkeys" but turns the login
    into password-then-passkey 2FA: a user with no passkey is stuck after a
    correct password, and that looks correct in the admin console. The
    zero-password recipe right next to this one removes the password form
    entirely, which is the opposite mistake. The WebAuthn passwordless policy
    is a separate block from the ordinary 2FA one, and its rpId defaults to
    empty - wrong values fail client-side inside the browser with nothing in
    the server log. Getting an existing user a first passkey without touching
    their password needs realm SMTP, which starts unconfigured. Verifying the
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
  - webauthn
  - passkey
  - password
  - authentication-flow
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

Acme's staff portal is getting passkeys:

> "Username and password with a passkey option. Staff who've set up a passkey should be able to sign in with just that. Everyone else keeps signing in with their password exactly as today — nobody gets locked out or asked for a second thing. One login page, either method."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme` with two staff accounts (`priya`, `marcus`) who currently sign in with a password and have no passkey, and a public browser client, `acme-portal`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`; the two staff accounts' existing passwords are in `/root/staff_credentials.txt`.

There is no real mail provider here. A local mail-capture server accepts whatever a realm sends and writes each message to `/var/mail-capture/` — connection details are in `/root/mail_server_details.txt`.

A headless Chromium browser with WebAuthn support is available at `/root/.cache/ms-playwright` (installed via the `playwright` Python package already present) — anything actually exercising a passkey ceremony (registering one, authenticating with one) needs a browser that can respond to the WebAuthn API, not a plain HTTP client.

Configure the `acme` realm so that all of the following hold, for a browser authorization-code login against `acme-portal`:

1. The login page for `acme-portal` offers the username/password form **and** a way to sign in with a passkey instead. Both methods live on that one login page and that one client.
2. A user with **no** passkey — `priya` — logs in with her existing password alone: the browser arrives back at `http://localhost:9999/callback` with an authorization code and the `state` the application sent, unchanged. Nothing further is asked of her after a correct password.
3. A wrong password is still rejected.
4. Starting from their current state, there is a way to get a user a registered passkey without changing, resetting, or emailing them a password — the realm's mail settings and Keycloak's required-action mechanism are the tools available. Once `marcus@acme.example` has one, completing the passkey ceremony with the same authenticator that registered it completes the login without entering a password, again arriving at the callback with a code and an unchanged `state`.
5. After enrolling a passkey, `marcus` can still log in with his password alone.
6. `priya` and `marcus` still exist, are enabled, and keep their password credentials. Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
