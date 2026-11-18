---
schema_version: '1.3'
# Runs Phase Two's Keycloak image: quay.io/phasetwo/phasetwo-keycloak build
# 26.8.2.1794965685, pinned by digest in environment/Dockerfile. It bundles
# keycloak-orgs 0.199 and keycloak-atomic-auth-flows 0.4. Keycloak's native
# organizations are switched off (KC_FEATURES_DISABLED=organization), as on
# every Phase Two deployment. So the task exercises the path the shipped
# admin:corporate-sso references teach: a keycloak-orgs organization holding the
# domain (/realms/acme/orgs), the provider linked to it (.../idps/link), and the
# homeIdp browser flow with ext-auth-home-idp-discovery, imported through
# keycloak-atomic-auth-flows.
#
# Results are comparable only with other runs on this image. Until 2026-11-18
# the task ran stock upstream Keycloak with native organizations: 26.0.7, then
# 26.8.2 (keycloak-skills PR #48). Native organizations, which Phase Two never
# enables, route from the stock browser flow, so no flow had to be authored; on
# 26.8 the organization's domain also had to be routed to the provider with
# auto-redirect. Here the native API returns 404, and routing needs a flow.
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    The request is stated the way a customer states it, so the first difficulty
    is recognising what "corporate SSO" means mechanically: route a user to an
    external identity provider chosen from the domain of the email they typed,
    while everyone else still gets a password form. Brokering an OIDC provider
    is the easy half. On Phase Two's Keycloak the hard half takes three more
    pieces, from the keycloak-orgs extension, and none of them reports that it
    is missing. An organization has to hold the customer's email domain, and
    organizations live at /realms/{realm}/orgs: Keycloak's own organizations
    API, the one its documentation describes, is switched off here and returns
    404. The provider has to be linked to that organization. And the realm has
    to be bound to a browser flow that runs ext-auth-home-idp-discovery. The
    stock browser flow discovers nothing, so a realm that stops after the link
    shows Contoso staff a plain password form, with no button either, because
    linking hides the provider. Discovery matches the organization's own
    domains, so a domain passed only when linking the provider routes nobody.
    Keycloak's partialImport answers a flow with 200 OK and creates nothing;
    the flow has to be built execution by execution or through the
    keycloak-atomic-auth-flows import endpoint. A redirector execution in a
    custom flow, the obvious-looking answer, sends every user to the provider
    and breaks password login for internal staff.
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
  # Its deployment-scoped tools (organizations, linking, flow import) reach acme
  # through environment/deployment_token_proxy.py, as in the other MCP tasks.
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
