# benchmarks

Task definitions from [skillsbench](https://github.com/anthropics/skillsbench) used to evaluate the skills in [`plugins/`](../plugins/) against real sandboxed scenarios.

This directory is not part of the distributable plugin content — it's excluded from skillsaw linting (see [`.skillsaw.yaml`](../.skillsaw.yaml)) and isn't installed by `/plugin install`.

Each subdirectory is one benchmark task, copied from the skillsbench task tree (`environment/`, `oracle/`, `verifier/`, `task.md`). Per-run output (`jobs/`) is not copied here — it's execution history, not part of the task definition, and stays in the skillsbench working tree.

## Tasks

- [`keycloak-magic-link-login/`](keycloak-magic-link-login/) — provision magic-link passwordless login on a realm, correctly configuring outgoing mail and disabling silent account auto-creation. Exercises the `keycloak` skill's passwordless/magic-link guidance.
- [`keycloak-passwordless-passkey-login/`](keycloak-passwordless-passkey-login/) — provision passkey-only WebAuthn login (no password fallback), covering the WebAuthn passwordless policy, authoring/binding the flow, and the credential-bootstrap problem for zero-credential users. Exercises the `keycloak` skill's passwordless/passkey guidance (`admin:passwordless-passkey`).
