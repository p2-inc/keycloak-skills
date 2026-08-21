# keycloak-idp-federation-login Verifier Rubric

- `task_success`: the `acme` realm offers a plain, unconditional "log in with Contoso"
  button. Scored 1.0 only when every check below holds, 0.0 otherwise.
  - Exactly one identity provider exists, with `providerId: "oidc"` and `enabled: true`.
    The verifier discovers whatever alias the agent chose rather than assuming one.
  - `taylor` authenticating at Contoso's identity provider (forced via `kc_idp_hint`,
    with **no** `account_hint` at all) completes the browser authorization-code flow
    against `acme-portal` and lands on `http://localhost:9999/callback` with a `code`.
  - `morgan` — a second, unrelated Contoso staff member — can do the exact same thing.
    This is the check that actually distinguishes this task from its siblings
    (`keycloak-corporate-sso-login`, domain-routed; `keycloak-idp-org-restrict-login`,
    organization-membership-gated): if only one specific user can get through, or if
    login requires any `account_hint` / organization link, that is the wrong, adjacent
    capability — a plain login button must gate on nothing but valid Contoso credentials.
  - After `taylor`'s successful login, the brokered Keycloak user has `email`,
    `firstName`, and `lastName` populated from Contoso's `email`, `given_name`, and
    `family_name` claims respectively.
  - Realm `contoso-idp` is untouched: still exactly the `taylor` and `morgan` accounts,
    `acme-app` still a confidential client, and no identity providers added to it.
  - Exactly the `master`, `acme`, and `contoso-idp` realms exist.
