<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-step-up-authentication Verifier Rubric

- `task_success`: step-up authentication is fully configured and functional. Scored 1.0 only
  when every check below holds, 0.0 otherwise.
  - **Flow structure**: exactly one browser authentication flow is bound to the realm or
    clients. The flow contains two trust-level sub-flows ordered lowest-first: Level 1
    (silver) before Level 2 (gold). Each level is an ALTERNATIVE sibling. Within each
    level, all executions are REQUIRED or CONDITIONAL (never mixed). Level-1 executions
    are `auth-username-password-form` (REQUIRED) and `conditional-level-of-authentication`
    (REQUIRED). Level-2 executions are `conditional-level-of-authentication` (REQUIRED)
    and `auth-otp-form` (REQUIRED).
  - **Condition config**: each `conditional-level-of-authentication` execution has
    `loa-condition-level` matching its level (1 for silver, 2 for gold). Level-2's
    condition has `loa-max-age` set to 300 seconds.
  - **ACR mapping**: realm attribute `acr.loa.map` is `{"silver":1,"gold":2}`.
  - **Payment client enforcement**: `acme-payments` client has
    `attributes["minimum.acr.value"]` set to `gold`.
  - **Fresh login to `acme-portal`, no `acr` requested**: `priya` completes a browser
    authorization-code login (password only, no code) against `acme-portal` → authorization
    code returned → ID token `acr` claim is `silver`.
  - **Same session, step-up with essential `gold`**: within the same browser session (no
    logout), request `gold` as an essential ACR claim → only the code form appears (no
    password form) → enter a valid TOTP code for `priya` → authorization code returned →
    ID token `acr` is `gold`.
  - **Re-use of `gold` within 5 minutes**: immediately request `gold` again (same session) →
    no authentication prompts (cache hit) → authorization code returned → `acr` still
    `gold`.
  - **Fresh browser, `gold` on first login**: `morgan` (different user, fresh browser)
    requests `gold` on initial login → password form appears first → code form appears
    after password validation → both completed with valid credentials/code → authorization
    code returned → ID token `acr` is `gold`.
  - **Wrong code at level-2 step**: attempt `morgan`'s login again with an incorrect TOTP
    code → authentication fails → no authorization code.
  - **Forced `gold` on `acme-payments`**: request authorization-code flow against
    `acme-payments` with no `acr` parameter at all → code form still appears (forced by
    `minimum.acr.value`) → enter code → authorization code returned → `acr` is `gold`.
  - **Unmapped essential `acr`**: request an unmapped ACR (e.g., `platinum`) as essential →
    Keycloak returns an error, not a successful login.
  - **User passwords unchanged**: `priya` can log in with her original password
    (`Pr1y@Acme2026`); `morgan` can log in with his original password (`M0rg@n2026`).
  - **Only `master` and `acme` realms exist**: no extra realms created.
