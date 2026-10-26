---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    The request is stated the way a customer states it, so the first difficulty
    is recognising what "corporate SSO" means mechanically: route a user to an
    external identity provider chosen from the domain of the email they typed,
    while everyone else still gets a password form. Brokering an OIDC provider
    is the easy half. The hard half is that vanilla Keycloak has exactly one
    way to select a provider by email domain, and it is not in the
    authentication-flow editor where someone would look for it - it needs the
    realm's organization support switched on, an organization holding the
    domain as a *verified* domain, and the identity provider linked to that
    organization. Configure the provider without that link and the login page
    simply shows an SSO button to everybody; mark the domain unverified and
    discovery silently never matches. A redirector execution in a custom flow,
    the obvious-looking answer, sends every user to the provider and breaks
    password login for internal staff.
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
  - sso
  - identity-brokering
  - oidc
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

Acme's head of IT has asked for one thing:

> "I want corporate SSO login."

Contoso Ltd is Acme's first enterprise customer. Contoso's staff should reach Acme's portal by signing in with their own company credentials, at their own identity provider — Acme never holds their passwords. Acme's own internal staff must keep signing in with the passwords they already have.

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the container and takes a few seconds to come up; `wait-for-services` blocks until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

- Realm `acme` is Acme's own realm. It has one browser application registered, the public client `acme-portal`, whose redirect URI is `http://localhost:9999/callback`. It also has one internal account, `dana` / `dana@acme-internal.example`, who signs in with a password.
- Realm `contoso-idp` stands in for Contoso's identity provider, which Contoso operates. The federation details their IT team supplied — endpoints, client ID, client secret, and the email domain their staff use — are in `/root/corporate_idp_details.txt`. Treat that realm as belonging to the customer: do not change anything inside it.

Configure the `acme` realm so that all of the following hold, in a browser authorization-code login against `acme-portal`:

1. Someone who enters an email address at Contoso's domain on Acme's login page is never asked for an Acme password. They are sent to Contoso's identity provider to authenticate.
2. When they authenticate successfully there, they arrive back at `http://localhost:9999/callback` with an authorization code, and the `state` value the application sent is returned unchanged.
3. They then exist as a user in the `acme` realm whose account is linked to that identity provider, holding no password of their own in `acme`.
4. Someone who enters an email address at any other domain — including `dana@acme-internal.example` — is still asked for a password, and can still complete the login with the password they already have.
5. Realm `contoso-idp` is unchanged, and no realm other than `master`, `acme` and `contoso-idp` exists.
