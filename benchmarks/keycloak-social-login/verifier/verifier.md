---
document_version: "0.1"
verifier:
  name: keycloak-social-login
  default_strategy: deterministic
  strategies:
    deterministic:
      type: script
      command: ./test.sh
  rubric:
    combine: weighted_mean
    dimensions:
      task_success: {weight: 1.0, source: deterministic}
  outputs:
    reward_json: /logs/verifier/reward.json
    details_json: /logs/verifier/reward-details.json
    aggregate_policy:
      method: weighted_mean
      metrics:
        task_success: 1.0
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

## verifier intent

This task is **config-state-assertion only**. Keycloak's built-in social identity providers
(`google`, `github`, `microsoft`, `facebook`, ...) are hardcoded in Keycloak's own Java source to
real vendor endpoints — `GitHubIdentityProvider.DEFAULT_AUTH_URL =
"https://github.com/login/oauth/authorize"` is a Java constant, not a configurable URL the way a
generic OIDC/SAML provider's endpoints are. There is no way to point `providerId="github"` at a
local fake IdP, and this sandbox runs with `network_mode: no-network`. So unlike most identity-
provider tasks in this repo, no live end-to-end brokered login is attempted here — that is a
deliberate, documented scope limitation, not an oversight. See `rubrics/verifier.md` for the same
note.

What each test establishes:

1. `test_github_is_a_builtin_social_provider_and_enabled` — discovers the identity provider by
   `providerId == "github"` (never a hardcoded alias) and checks it's the real built-in social
   provider, enabled. Fails if an agent built a generic `oidc`/`saml` IdP pointed at GitHub's
   endpoints by hand instead of using the built-in provider.
2. `test_client_secret_is_never_returned_in_plaintext` — a cheap sanity check that nothing
   unusual leaked the fixture secret; Keycloak redacts `clientSecret` on `GET` by default.
3. `test_kc_idp_hint_redirects_to_github_with_the_right_client_id` — the load-bearing "is this
   really wired up" check available without network access. Keycloak's own authorization
   endpoint, given `kc_idp_hint=<alias>`, builds a redirect (302 or 303) to GitHub's real authorize
   endpoint *entirely from local realm configuration* — no request to `github.com` is made by
   asking for this, even though the `Location` header names it. Asserts the redirect's
   `client_id` query parameter matches the fixture GitHub OAuth App's client ID, proving the
   fixture credentials were actually wired into the identity provider's `config`, not just that
   *some* IdP exists.
4. `test_redirect_uri_is_discoverable_and_correct` — the callback URI Keycloak needs registered
   on GitHub's side follows the standard, derivable
   `{baseUrl}/realms/acme/broker/{alias}/endpoint` shape (already exercised as the redirect's
   own `redirect_uri` parameter in test 3).
5. `test_username_is_mapped_from_githubs_login_field_not_an_oidc_standard_claim` — the first half
   of the real discriminator. Requires a `oidc-username-idp-mapper` (Username Template Importer)
   mapper whose template references GitHub's actual `login` field (`${CLAIM.login}`). Explicitly
   fails if the template instead references an OIDC-standard claim
   (`preferred_username` — the mapper's own factory default — `given_name`, `sub`, `email`) that
   GitHub's OAuth profile JSON never contains
   (`org.keycloak.social.github.GitHubIdentityProvider.extractIdentityFromProfile` reads exactly
   `login`, `name`, and `email` — nothing else). Left at the factory default, this mapper
   resolves to an unresolved template variable and blanks the imported username.
6. `test_firstname_is_mapped_from_githubs_name_field_with_githubs_own_mapper_type` — the second
   half. Requires a `github-user-attribute-mapper` mapper (GitHub's own compatible attribute
   mapper, `org.keycloak.social.github.GitHubUserAttributeMapper`) — not the generic
   `oidc-user-attribute-idp-mapper` a copy-pasted Google/Auth0/generic-OIDC pattern would reach
   for, which is not even a compatible mapper type for GitHub's provider — mapping the `jsonField`
   `name` to the `userAttribute` `firstName`. Fails clearly, naming the wrong claim/mapper type
   found, if an agent assumed `given_name`/`first_name` exist on GitHub the way they do on a
   standard OIDC userinfo response.
7. `test_only_master_and_acme_realms_exist` — no incidental extra realm was created.

Reward is all-or-nothing: `1` when every test passes, `0` otherwise.

Artifacts copied to `/logs/verifier/`: `output.txt` (full pytest output), `ctrf.json`, and
`services-readiness.txt`.
