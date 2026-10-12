---
schema_version: '1.3'
metadata:
  author_name: Razvan Tufisi
  author_email: rtufisi@phasetwo.io
  difficulty: medium
  difficulty_explanation: >-
    The user wants TOTP from an authenticator app as a second factor after password, not
    instead of it. Keycloak's built-in `auth-otp-form` authenticator provides this, but it
    must be placed AFTER `auth-username-password-form` in a REQUIRED sequence so the password
    genuinely gates the TOTP step. The subtle trap is ordering: swapping the steps or using
    ALTERNATIVE instead of REQUIRED produces a flow that looks like MFA but allows bypass.
    Additionally, users without TOTP credentials must be sent through enrollment via the
    `CONFIGURE_TOTP` required action, and the realm OTP policy must be configured. Unlike
    email-OTP variants, no SMTP is required, but TOTP requires per-user credential storage
    and time-based code verification that must be tested with real TOTP computation.
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
  - mfa
  - two-factor
  - totp
  - authenticator-app
  - authentication-flow
  - otp-policy
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

Acme's security team wants TOTP-based two-factor authentication for the internal tools portal:

> "Passwords stay, but after entering the right password, staff must enter a 6-digit code from
> an authenticator app like Google Authenticator or Authy. Anyone who hasn't set one up yet
> should be forced to enroll at their next login."

A Keycloak identity server runs at `http://localhost:8080/auth`, serving a realm named `acme`.
It starts with the container and takes a few seconds to come up; `wait-for-services` blocks
until it answers. Admin REST API credentials are in `/root/admin_credentials.txt`.

Realm `acme` has one browser application registered, the public client `acme-portal`, whose
redirect URI is `http://localhost:9999/callback`. It has two staff accounts, each with a
verified email address and a password already on file:

- `priya` (`priya@acme-internal.example`), password `Priya!Pass1`. She has already registered
  an authenticator app: her TOTP credential is on file.
- `morgan` (`morgan@acme-internal.example`), password `Morgan!Pass1`. He has no authenticator
  yet.

Configure the `acme` realm so that all of the following hold, for a browser
authorization-code login against `acme-portal`:

1. `priya` signing in with her **correct** password reaches a TOTP code prompt; the password
   alone does not log her in.
2. Entering the current 6-digit code from her authenticator app then completes the login:
   the browser arrives back at `http://localhost:9999/callback` with an authorization code,
   and the `state` value the application sent is returned unchanged.
3. The password genuinely gates the TOTP step: a **wrong** password never reaches the code
   prompt (only the standard password error is shown).
4. A correct password followed by a **wrong** code is rejected at the code prompt and does not
   complete the login.
5. TOTP is required for **everyone**: `morgan`, who has no authenticator, must not be let in on
   his password. His correct password leads to the TOTP enrolment screen, and once he enrols
   an authenticator there (entering its first code), the login completes and he has a TOTP
   credential on file.
6. The realm OTP policy uses 6-digit codes with a 30-second period (TOTP, not HOTP).
7. Every other realm on the server is untouched, and no realm other than `master` and `acme`
   exists.
