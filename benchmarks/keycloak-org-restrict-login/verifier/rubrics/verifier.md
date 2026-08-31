<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-org-restrict-login Verifier Rubric

- `task_success`: login through `acme-portal` is restricted to members of one
  organization, created via the real p2-inc `keycloak-orgs` extension. The application
  always sends the literal `account_hint=engineering` and never a server-generated
  organization ID, so the only valid solution is an organization named exactly
  `engineering` with `match_by_org_name=true` - the verifier does not adapt to any other
  configuration the agent might have built instead. Scored 1.0 only when every check
  below holds, 0.0 otherwise.
  - Exactly one organization exists (via `/realms/acme/orgs`, not Keycloak's native
    Organizations feature), named exactly `engineering`.
  - The seeded user `priya` is a member of it; the seeded user `morgan` is not.
  - The browser flow **actually in effect for `acme-portal`** contains an
    `ext-select-org` execution with `match_by_org_name=true`. Either binding surface is
    accepted — a client-level override on `acme-portal`
    (`authenticationFlowBindingOverrides.browser`) or the realm-wide `browserFlow` — with
    the client override taking precedence, exactly as Keycloak resolves it. The flow does
    **not** have to be newly authored: this Keycloak ships a built-in `Org Browser Flow`
    already containing `ext-select-org`, so configuring and binding that is equally valid.
  - `priya` logging in with `account_hint=engineering` completes with an authorization
    code.
  - `priya` logging in with an `account_hint` that matches no real organization is
    rejected (no authorization code).
  - `morgan` logging in with `account_hint=engineering` is rejected (no authorization
    code) - this is what proves membership is actually being checked, not just the
    presence of some `account_hint` value.
  - Exactly the `master` and `acme` realms exist.
