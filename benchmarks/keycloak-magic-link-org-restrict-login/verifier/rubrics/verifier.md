<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-magic-link-org-restrict-login Verifier Rubric

- `task_success`: magic-link login through `acme-portal` only ever emails a link to members
  of one organization, created via the real p2-inc `keycloak-orgs` extension. The application
  always sends the literal `account_hint=engineering` and never a server-generated
  organization ID, so the only valid solution is an organization named exactly `engineering`
  with `match_by_org_name=true` - the verifier does not adapt to any other configuration the
  agent might have built instead. Scored 1.0 only when every check below holds, 0.0 otherwise.
  - Exactly one organization exists (via `/realms/acme/orgs`, not Keycloak's native
    Organizations feature), named exactly `engineering`.
  - The seeded user `priya` is a member of it; the seeded user `morgan` is not.
  - The flow **actually in effect for `acme-portal`** (client-level override or realm-wide,
    with the client override taking precedence exactly as Keycloak resolves it) contains
    `ext-auth-username-auth-note`, `ext-select-org`, and `ext-magic-form` as sibling
    executions (same nesting level), all `REQUIRED`, **in that exact relative order**. The
    order is load-bearing: putting `ext-magic-form` before `ext-select-org` would still
    eventually reject a non-member, but only after already emailing them a working link -
    exactly the failure mode this task is designed to catch.
  - `ext-select-org`'s attached config has `match_by_org_name=true`.
  - `priya` submitting her email address (no password, at any point) with
    `account_hint=engineering` reaches the magic-link "check your email" page, a real email is
    captured for her, and opening its action-token link returns an authorization code.
  - `morgan` submitting his email address with `account_hint=engineering` does **not** reach
    the "check your email" page, and - the check that actually proves the send is gated, not
    just the login - **no email is captured for him at all**.
  - `priya` submitting her email address with an `account_hint` that matches no real
    organization also produces no captured email - this is what proves the gate checks
    membership in the specific hinted organization, not merely the presence of some
    `account_hint` value.
  - Exactly the `master` and `acme` realms exist.
