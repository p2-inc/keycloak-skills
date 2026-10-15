---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: hard
  difficulty_explanation: >-
    Two trust levels in one session that expire separately. Level 1 (silver, password only)
    lasts the whole SSO session; level 2 (gold, password + TOTP code) lasts only 5 minutes
    before silently dropping back to silver without logging the user out. The flow shape is a
    CONDITIONAL sub-flow per level, ordered lowest level first - reversing that order demands
    level 2 on every first login regardless of what was requested. A client (acme-payments)
    must be pinned to always require gold via minimum.acr.value even when nothing is
    requested, while acr_values/default.acr.values (browser-rewritable) must not be mistaken
    for enforcement. An essential, unmapped acr value must produce an authentication error,
    not a silent downgrade. The realm's acr.loa.map and the level-2 loa-max-age are
    configuration that can't practically be exercised by waiting out a 5-minute timer in a
    verifier run, so they are checked directly.
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
  - loa
  - mfa
  - totp
  - authentication-flow
  - conditional-authenticator
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
  mcp_servers:
    - name: keycloak
      transport: http
      url: http://localhost:8090/mcp
      headers:
        Authorization: "Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6Imx2N1o4T1VPN1V0SlE3bU1XY01pM3lKVkFfbXJGRmFNQm84WU8zRE9BeWsiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwOi8vbG9jYWxob3N0OjgwODAvYXV0aC9yZWFsbXMvYWNtZSIsInN1YiI6Ijc3NGMzMWVjLTE2MDEtNTNlOS05ZjFkLWZiMTBkNjFlN2NhNyIsInR5cCI6IkJlYXJlciIsImF6cCI6Im1jcC1iZW5jaC1jbGkiLCJhY3IiOiIxIiwicmVhbG1fYWNjZXNzIjp7InJvbGVzIjpbImRlZmF1bHQtcm9sZXMtYWNtZSIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRpb24iXX0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbInZpZXctaWRlbnRpdHktcHJvdmlkZXJzIiwidmlldy1yZWFsbSIsIm1hbmFnZS1pZGVudGl0eS1wcm92aWRlcnMiLCJpbXBlcnNvbmF0aW9uIiwicmVhbG0tYWRtaW4iLCJjcmVhdGUtY2xpZW50IiwibWFuYWdlLXVzZXJzIiwicXVlcnktcmVhbG1zIiwidmlldy1hdXRob3JpemF0aW9uIiwicXVlcnktY2xpZW50cyIsInF1ZXJ5LXVzZXJzIiwibWFuYWdlLWV2ZW50cyIsIm1hbmFnZS1yZWFsbSIsInZpZXctZXZlbnRzIiwidmlldy11c2VzIiwidmlldy1jbGllbnRzIiwibWFuYWdlLWF1dGhvcml6YXRpb24iLCJtYW5hZ2UtY2xpZW50cyIsInF1ZXJ5LWdyb3VwcyJdfSwiYWNjb3VudCI6eyJyb2xlcyI6WyJtYW5hZ2UtYWNjb3VudCIsIm1hbmFnZS1hY2NvdW50LWxpbmtzIiwidmlldy1wcm9maWxlIl19fSwic2NvcGUiOiJwcm9maWxlIGVtYWlsIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5hbWUiOiJNQ1AgT3BlcmF0b3IiLCJwcmVmZXJyZWRfdXNlcm5hbWUiOiJtY3Atb3BlcmF0b3IiLCJnaXZlbl9uYW1lIjoiTUNQIiwiZmFtaWx5X25hbWUiOiJPcGVyYXRvciIsImVtYWlsIjoibWNwLW9wZXJhdG9yQGFjbWUuZXhhbXBsZSIsImlhdCI6MTc2NzIyNTYwMCwiZXhwIjo0ODU5NzQwODAwLCJqdGkiOiJza2lsbHNiZW5jaC1maXhlZC1tY3AtdG9rZW4ifQ.hthr7rjZpSB04KsoxUR06IRV7Vy4aGNAWA4uwjDhB6M5qs3WC9b8BuAH1RDtm76nxz8mz39T4NAgy-zjFbGkK9buj_hL53YpkATwkU2YETYwXHK_f6PoGcIYO-l4vaiIXrYjUo6LoXCCJX14naak_Wt7CtXYtWDyzdR6vr9HoTtIlZRsd3iXsLUNU_pam5bszEKcl0s7FJK4GRlmWcyQymA-WqNXFpgWhLSmZWAMXpFTTKLCvGr8yqSs0Hi260zfxgo8nnEQuIYA4iFV0MH0D8oMQH64iMUyyrTdxTXBMaWtVbWLvPup7h8zWJXWgg3Iab5pvNt1yxpdo2KW0AJjAg"
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Acme's security team wants step-up authentication for its internal tools:

> "Ordinary use should only need the password. But some actions are sensitive - we want to ask
> for a one-time code too in those moments, without making the user retype their password if
> they already have an active session. And once they've given the code, that elevated trust
> should expire after about 5 minutes - drop them back to password-level, don't log them out.
> One of our apps, the payments app, should always get the strong check, even if it doesn't
> explicitly ask for it."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme`.
It starts with the container and takes a few seconds to come up; `wait-for-services` blocks
until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

Realm `acme` has two public clients already registered:

- `acme-portal`, redirect URI `http://localhost:9999/callback` - the ordinary browser app.
- `acme-payments`, redirect URI `http://localhost:9998/callback` - the sensitive app that must
  always get the strong check.

It has two staff accounts, each with a verified email address and a password already on file:

- `priya` (`priya@acme-internal.example`), password `Priya!Pass1`. She has already registered
  an authenticator app: her TOTP credential is on file.
- `morgan` (`morgan@acme-internal.example`), password `Morgan!Pass1`. He has no authenticator.

Configure the `acme` realm so that all of the following hold, for browser authorization-code
logins:

1. A login against `acme-portal` with no level requested asks only for the password; the
   resulting ID token's `acr` claim is `silver`.
2. In that same browser session, a subsequent request against `acme-portal` asking for the
   `gold` level (as an essential claim) shows **only** a one-time-code prompt - never the
   password form again - and entering the current code completes the login with `acr` `gold`.
3. Asking for `gold` again right away, in that same browser session, needs no prompt at all;
   the login completes immediately with `acr` still `gold`.
4. A **fresh** browser session asking for `gold` from the very start shows the password form,
   then the code prompt, and completes with `acr` `gold`.
5. At that code prompt, a wrong one-time code is rejected and no authorization code is issued.
6. A login against `acme-payments` with no level requested at all is still asked for the code
   after the password - the client must always get `gold`, whether or not the request asks.
7. A login requesting an essential `acr` value of `platinum` (not mapped to any level) fails
   with an authentication error rather than logging the user in at some other level.
8. `priya` and `morgan` still exist, are enabled, and keep their original passwords. No realm
   other than `master` and `acme` exists.

TOTP codes are single-use; the same code cannot be submitted twice. The authenticator app
itself is mocked (priya's TOTP secret is seeded on her account so codes can be computed
directly), but Keycloak's authentication logic is real.
