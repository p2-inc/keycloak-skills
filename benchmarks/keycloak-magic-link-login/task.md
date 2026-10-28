---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    Keycloak auto-creates a built-in "magic link" flow the moment the magic-link
    provider is present, which makes the task look like pure realm configuration
    rather than flow authoring - but two of its defaults point the wrong way for
    this request, and neither failure is visible from the login page, which
    shows the identical "check your email" response whether the address is
    known or not (a deliberate anti-enumeration choice in the authenticator
    itself). Outgoing SMTP is unconfigured, so nothing is delivered until the
    realm's mail settings are set correctly. And the authenticator's own
    "create user if none exists" setting defaults to true, so leaving it alone
    silently provisions a new account for any email a visitor types - the login
    page gives no hint this happened, and the only way to notice is checking
    whether mail went out and whether a user was created for an address that
    was never registered.
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
  - magic-link
  - smtp
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
  # baked into environment/acme-realm.json (a deliberately fixed, non-random
  # signing key, so every container boot publishes the same JWKS and this same
  # token stays valid), scoped only to the throwaway acme realm this task
  # creates fresh each run. See verifier.md for why a static token was required
  # here rather than one minted per session.
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCBtY3A6cmVhZCBtY3A6d3JpdGUiLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwibmFtZSI6Ik1DUCBPcGVyYXRvciIsInByZWZlcnJlZF91c2VybmFtZSI6Im1jcC1vcGVyYXRvciIsImdpdmVuX25hbWUiOiJNQ1AiLCJmYW1pbHlfbmFtZSI6Ik9wZXJhdG9yIiwiZW1haWwiOiJtY3Atb3BlcmF0b3JAYWNtZS5leGFtcGxlIiwiaWF0IjoxNzY3MjI1NjAwLCJleHAiOjQ4NTk3NDA4MDAsImp0aSI6InNraWxsc2JlbmNoLWZpeGVkLW1jcC10b2tlbiJ9.ZMkk2DVTDKpIPRLB46ndrsb_ndX_B4JauLPoBwKxsESm0XW9X_eNpYy-Tq7WPPqxWr6nQjORW_8F-szATRQysMQZbCpel9GBeOeJOv0Hn01Sm10sYVUGo5flc4XE-IJ5ftbgLlLN453uw3Zdpni6dTpFTa4Yw-vj1ElAPc-VYcDY3jJxXxbPagaZpfyCgIUQudqK0vnOS48oK-C2FV72SV2pWehkyTNeI4ifA3B5ZfSEk39unb1OxMwYDcpJHEp2eLSnZIJEGbzzcxr4zbuR6Xbs6T_ZftrqX21uk-ORt_hJ35JwXoZavLpXSXmqu1_g8nT3jtETMocl1XbeiYC80Q"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's support team keeps getting the same complaint: staff forget their passwords. IT's answer is:

> "I want passwordless login — email people a link instead of asking for a password."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme` with two staff accounts (`priya`, `marcus`), each with a password on file, and a public browser client, `acme-portal`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

There is no real mail provider here. A local mail-capture server accepts whatever a realm sends and writes each message to `/var/mail-capture/` — connection details are in `/root/mail_server_details.txt`.

Configure the `acme` realm so that all of the following hold, for a browser authorization-code login against `acme-portal`:

1. Someone who enters `priya@acme.example` or `marcus@acme.example` on the login page is never asked for a password. Instead, a real email goes out through the realm's configured mail settings, containing a link.
2. Opening that link, with nothing else entered, completes the login: the browser arrives back at `http://localhost:9999/callback` with an authorization code, and the `state` value the application sent is returned unchanged.
3. Someone who enters an email address that belongs to no existing account gets the same response as anyone else — the login page must not reveal whether an address is registered. But behind that identical response, nothing observable may happen for an unregistered address: no mail may be sent for it, and no new account may be created.
4. Every other realm on the server is untouched, and no realm other than `master` and `acme` exists.
