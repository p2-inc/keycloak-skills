# keycloak-idp-org-restrict-login Verifier Rubric

- `task_success`: federated login through the partner identity provider is restricted to members
  of the organization the application names in `account_hint`. Scored 1.0 only when every check
  below holds, 0.0 otherwise.
  - At least two organizations exist via `/realms/acme/orgs` (the keycloak-orgs surface, not
    Keycloak's native Organizations feature). Two are required so membership can actually be
    discriminated rather than merely asserted.
  - Exactly one identity provider exists, and it is **linked** to one of those organizations.
    The link is what makes it organization-owned; without it `ext-auth-org-add-user` and
    `ext-auth-org-note` no-op and the gate is inert.
  - The identity provider's `postBrokerLoginFlowAlias` names a flow containing an
    `ext-select-org` execution. The verifier resolves whatever alias is bound rather than
    assuming a name, since the atomic-flows extension hash-prefixes the flows it creates.
  - `jordan` authenticating at the partner provider with `account_hint` naming the **owning**
    organization completes with an authorization code at the redirect URI.
  - The same login with `account_hint` naming a **different real** organization he does not
    belong to is rejected (no code). This is the check that proves membership is inspected — a
    flow that merely requires *some* `account_hint` would pass every other check and fail this.
  - The same login with `account_hint` naming a **nonexistent** organization is rejected.
  - Realm `partner-idp` is untouched: still exactly the `jordan` account, `acme-broker` still a
    confidential client, and no identity providers added to it.
  - Exactly the `master`, `acme` and `partner-idp` realms exist.
