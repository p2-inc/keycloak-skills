# benchmarks

Task definitions from [skillsbench](https://github.com/anthropics/skillsbench) used to evaluate the skills in [`plugins/`](../plugins/) against real sandboxed scenarios.

This directory is not part of the distributable plugin content — it's excluded from skillsaw linting (see [`.skillsaw.yaml`](../.skillsaw.yaml)) and isn't installed by `/plugin install`.

Each subdirectory is one benchmark task, copied from the skillsbench task tree (`environment/`, `oracle/`, `verifier/`, `task.md`). Per-run output (`jobs/`) is not copied here — it's execution history, not part of the task definition, and stays in the skillsbench working tree.

## Tasks

- [`keycloak-magic-link-login/`](keycloak-magic-link-login/) — provision magic-link passwordless login on a realm, correctly configuring outgoing mail and disabling silent account auto-creation. Exercises the `keycloak` skill's passwordless/magic-link guidance.
- [`keycloak-passwordless-passkey-login/`](keycloak-passwordless-passkey-login/) — provision passkey-only WebAuthn login (no password fallback), covering the WebAuthn passwordless policy, authoring/binding the flow, and the credential-bootstrap problem for zero-credential users. Exercises the `keycloak` skill's passwordless/passkey guidance (`admin:passwordless-passkey`).
- [`keycloak-corporate-sso-login/`](keycloak-corporate-sso-login/) — route a customer's staff to their own identity provider by email domain while internal staff keep password login. Exercises the `admin:corporate-sso` intent (MCP and REST variants).
- [`keycloak-org-restrict-login/`](keycloak-org-restrict-login/) — restrict *local password* login to members of one organization via `ext-select-org` in the browser flow, gated on `account_hint`. Exercises the `admin:org-restrict-login` intent (MCP and REST variants).
- [`keycloak-idp-org-restrict-login/`](keycloak-idp-org-restrict-login/) — gate a *federated* login on organization membership: broker a partner IdP, link it to an organization, and bind a post-broker flow containing `ext-select-org` so `account_hint` decides who gets in. Exercises the `admin:idp-org-restrict-login` intent (MCP and REST variants).
- [`keycloak-magic-link-org-restrict-login/`](keycloak-magic-link-org-restrict-login/) — combine passwordless magic-link login with an organization-membership gate: a custom flow (`ext-auth-username-auth-note` → `ext-select-org` → `ext-magic-form`, in that load-bearing order) so the org check runs *before* any login email is sent — a non-member must receive no mail at all, not merely fail to complete login. Exercises the `admin:passwordless-magic-link-org-restrict` intent (MCP and REST variants), and specifically tests whether the router correctly detects this combined scenario rather than routing to plain magic-link or plain org-restrict alone.
