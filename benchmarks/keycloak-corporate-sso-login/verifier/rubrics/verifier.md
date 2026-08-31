<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-corporate-sso-login Verifier Rubric

- `task_success`: the `acme` realm sends the customer's staff to the customer's identity
  provider based on their email domain, and leaves everyone else on password login. Scored
  1.0 only when every check below holds, 0.0 otherwise.
  - Submitting `jvega@contoso.example` or `rkhan@contoso.example` on acme's login page
    returns a page with no password input.
  - The resulting SSO route reaches
    `/realms/contoso-idp/protocol/openid-connect/auth`.
  - Authenticating at that provider returns the browser to
    `http://localhost:9999/callback` carrying an authorization code, with the `state` the
    application sent returned unchanged.
  - Both corporate addresses then exist as users in `acme`, each with a non-empty
    federated identity and no `password` credential.
  - `dana@acme-internal.example` is still shown a password field and still completes a
    login that ends at the redirect URI with a code.
  - Realm `contoso-idp` still contains exactly `jvega` and `rkhan`; its `acme-broker`
    client is still confidential, with redirect URIs
    `["http://localhost:8080/auth/realms/acme/broker/*"]` and client secret
    `broker-secret-8f2a1c`; and it has no identity providers.
  - Exactly the `master`, `acme` and `contoso-idp` realms exist.
