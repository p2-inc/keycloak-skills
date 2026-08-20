---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    This reads like two separate, already-documented tasks stacked together
    ("passwordless login" plus "restrict to an organization"), but neither of
    Keycloak's two obvious flows covers both: the built-in magic-link flow has no
    organization check, and the organization-aware flow (`ext-select-org`) gates a
    password form, not a magic-link send. The only correct answer is a custom flow
    that runs the org check BEFORE any email goes out - reversing that order would
    still "work" in the sense that a non-member is eventually turned away, but it
    would leak a working magic-link email to someone the org gate should have
    silently ignored, and reaching that conclusion requires understanding WHY the
    execution order in Keycloak's authentication-flow model matters, not just that
    an org-check step exists somewhere in the flow. As with the plain org-restrict
    task, the gate is account_hint-gated (necessary but not sufficient on its own),
    and the obvious verification - "does a valid member get in?" - is not enough:
    a flow that requires some account_hint value but never checks real membership,
    or one that sends mail unconditionally before checking, passes a shallow test
    while failing the actual requirement.
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
  - organizations
  - access-control
  - authentication-flow
  - passwordless
  - magic-link
  - smtp
verifier:
  type: test-script
  timeout_sec: 420.0
agent:
  timeout_sec: 1800.0
sandbox:
  network_mode: no-network
  os: linux
  cpus: 2
  memory_mb: 4096
  storage_mb: 10240
  # Prebuilt environment image: bench references it directly and SKIPS the docker
  # build step entirely (see benchflow sandbox/docker.py `_validate_definition` -
  # with docker_image set, no environment/Dockerfile is required at all). This is
  # why there is no Dockerfile in this task: running the client should not rebuild
  # a ~550MB Keycloak image.
  #
  # The recipe that produces this image lives in image/Dockerfile alongside this
  # task - it is documentation and a rebuild path, NOT part of the test environment.
  # To refresh: build image/ and push the tag below.
  docker_image: quay.io/phasetwo/skillsbench-keycloak-magic-link-org-restrict-login:latest
  # The keycloak-MCP-server jar runs in-container against the acme realm below.
  # The bearer token is a fixture, not a secret: it is signed with a private key
  # baked into environment/acme-realm.json (the same fixed, non-random signing
  # key used by the other MCP-wired tasks in this repo), so every container
  # boot publishes the same JWKS and this same token stays valid.
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VycyIsInZpZXctY2xpZW50cyIsIm1hbmFnZS1hdXRob3JpemF0aW9uIiwibWFuYWdlLWNsaWVudHMiLCJxdWVyeS1ncm91cHMiXX0sImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyIsInZpZXctcHJvZmlsZSJdfX0sInNjb3BlIjoicHJvZmlsZSBlbWFpbCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJuYW1lIjoiTUNQIE9wZXJhdG9yIiwicHJlZmVycmVkX3VzZXJuYW1lIjoibWNwLW9wZXJhdG9yIiwiZ2l2ZW5fbmFtZSI6Ik1DUCIsImZhbWlseV9uYW1lIjoiT3BlcmF0b3IiLCJlbWFpbCI6Im1jcC1vcGVyYXRvckBhY21lLmV4YW1wbGUiLCJpYXQiOjE3NjcyMjU2MDAsImV4cCI6NDg1OTc0MDgwMCwianRpIjoic2tpbGxzYmVuY2gtZml4ZWQtbWNwLXRva2VuIn0.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

Acme's security team has a new requirement, layered on top of a request IT already made:

> "Staff should log in with a magic link instead of a password — but only engineering staff
> should be able to sign in to the internal tools portal at all. Everyone else's link should
> just not work."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme`.
It starts with the container and takes a few seconds to come up; `wait-for-services` blocks
until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

Realm `acme` has one browser application registered, the public client `acme-portal`, whose
redirect URI is `http://localhost:9999/callback`. It has two staff accounts, both with a
verified email address on file:

- `priya` (`priya@acme-internal.example`) — she is engineering staff and should be let in.
- `morgan` (`morgan@acme-internal.example`) — he is not engineering staff and should be turned
  away.

Neither account belongs to any organization yet, and no organization exists yet. There is no
real mail provider here — a local mail-capture server accepts whatever the realm sends and
writes each message to `/var/mail-capture/`; connection details are in
`/root/mail_server_details.txt`.

The application will send a real login request to `acme-portal` carrying
`account_hint=engineering` (the value it will use to mean "the engineering team") — it will not
send `prompt=select_account`, and this is the only signal available to distinguish "let this
person in" from "turn this person away."

Configure the `acme` realm so that all of the following hold, for a browser authorization-code
login against `acme-portal` carrying `account_hint=engineering`, where the person entering their
email is never asked for a password at any point:

1. `priya` entering her email address receives a real email, through the realm's configured
   mail settings, containing a login link. Opening that link, with nothing else entered,
   completes the login: the browser arrives back at `http://localhost:9999/callback` with an
   authorization code.
2. `morgan` entering his email address does **not** receive any email at all — the security
   requirement is "his link should just not work," and the strongest, correct reading of that is
   that no link is ever sent to him in the first place, not merely that a link he somehow
   obtained would fail if used.
3. A login carrying an `account_hint` that matches no real organization at all does not produce
   any email either, for anyone — including `priya` — the gate must actually check membership in
   a real, specific organization, not merely require the presence of any `account_hint` value.
4. Every other realm on the server is untouched, and no realm other than `master` and `acme`
   exists.
