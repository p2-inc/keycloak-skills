---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    The token verifies and the user is authenticated - and every authorization check still
    fails. Spring Security's default JwtGrantedAuthoritiesConverter reads the `scope` claim
    and prefixes SCOPE_; Keycloak puts roles in `realm_access.roles`, which the default
    never touches. A configuration that only sets issuer-uri therefore passes every
    401-shaped check (no token, garbage token, tampered token, foreign-realm token) and
    /api/items works for everyone - but the role-gated endpoint returns 403 to the admin
    who is supposed to reach it. The decisive assertion is the pair: the admin user gets
    200 on the role-gated route AND the non-admin gets 403 on it - the first fails without
    a realm-role converter, the second fails if the converter grants too much or the gate
    is faked open. Two more traps are guarded: locking down everything including /healthz
    (the fixture's monitoring contract says it must stay public - an unauthenticated 200
    is asserted), and setting the `audiences` property without an audience mapper on the
    Keycloak client, which rejects every token including valid ones - the fixture realm
    deliberately ships no audience mapper, so the correct configuration omits that
    property. A second realm on the same server, with the same usernames, passwords, role
    and - deliberately - the same signing key, supplies the foreign-token negative: a
    token whose signature validates against the API's JWKS but whose issuer is wrong must
    still 401. Sharing the key is what makes `jwk-set-uri` (signature-only, issuer
    unchecked) a detectable wrong answer instead of one the signature check covers for.
  category: cybersecurity
  secondary_category: software-engineering
  subcategory: identity-access-management
  category_confidence: high
  task_type:
  - implementation
  modality:
  - code
  interface:
  - terminal
  skill_type:
  - domain-procedure
  tags:
  - keycloak
  - oidc
  - jwt
  - spring-boot
  - resource-server
  - bearer-token
  - role-mapping
verifier:
  type: test-script
  timeout_sec: 900.0
agent:
  timeout_sec: 1800.0
sandbox:
  network_mode: no-network
  build_timeout_sec: 2400.0
  os: linux
  cpus: 2
  memory_mb: 6144
  storage_mb: 12288
  # No mcp_servers block, deliberately. This task's whole scored surface is app-side
  # token validation against stock upstream Keycloak; the realm fixture ships fully
  # provisioned (users, role, direct-grant client) and the correct solution performs
  # zero Keycloak admin writes. The securing-apps skill itself states "Tooling affects
  # only client registration - never the app's library or wiring", so an MCP arm and a
  # REST arm would measure the same thing twice. This also keeps the image free of the
  # ECR-hosted MCP server build stage.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's inventory API is a Spring Boot service. It currently answers to anyone: a previous
developer opened security up "temporarily" to unblock a demo, and it shipped that way.
The team wants it protected with bearer JWTs issued by Acme's own Keycloak.

A Keycloak identity server runs at `http://localhost:8080/auth`. It starts with the
container and takes a few seconds to come up; `wait-for-services` blocks until it answers.
Admin REST API credentials are in `/root/admin_credentials.txt`. The server hosts more
than one realm; Acme's is `acme`.

The API lives at `/app/api` - a Maven + Spring Boot project. It runs on port **8085**
(`mvn` is installed; the local Maven repository is already populated and **the sandbox has
no network**, so work with the dependencies already declared and cached rather than adding
new ones). `mvn -o -DskipTests package` works today and must still work when you are done.

The realm `acme` has a realm role `inventory-admin` and two users you can test with, both
usable through the public `inventory-cli` client's direct-access grant:

- `alice` / `alice-pass-1` - has the `inventory-admin` realm role
- `bob` / `bob-pass-1` - has no realm roles

Deliver, in the code at `/app/api`:

1. Every `/api/**` endpoint requires a valid bearer JWT issued by the `acme` realm.
   Requests with no token, a malformed or tampered token, or a token from any other
   issuer are rejected with 401.
2. `GET /api/items` works for any authenticated `acme` user.
3. `GET /api/admin/audit` works **only** for users holding the `inventory-admin` realm
   role. An authenticated user without it gets 403 - not 401, and not the data.
4. `GET /healthz` stays public. The monitoring system probes it unauthenticated and must
   keep getting a 200.
5. `mvn -o -DskipTests package` in `/app/api` still exits 0.

The realm's configuration is not yours to change: the correct solution touches only the
application. Every realm on the server is left exactly as you found it.
