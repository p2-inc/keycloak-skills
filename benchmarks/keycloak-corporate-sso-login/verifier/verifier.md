---
document_version: "0.3"
verifier:
  name: keycloak-corporate-sso-login
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

The verifier reads no agent-produced files. It performs real browser
authorization-code logins against the `acme-portal` client, headlessly: fetch the login
page, submit an email address, and follow wherever Keycloak sends the browser — including
out to the customer's identity provider, through authentication there, and back to the
application's redirect URI.

Two client-side details are worth knowing, because they are properties of the test client
rather than of the realm:

- Keycloak marks its auth cookies `Secure` with `SameSite=None`. A browser sends them
  anyway over `http://localhost`, which it treats as a secure context; `requests` will
  not, and every form POST then fails as `cookie_not_found`. The helper clears the flag to
  reproduce browser behaviour.
- On the pinned image (Phase Two's Keycloak 26.8.2 with keycloak-orgs 0.199), discovery
  answers a correctly routed address with a `303` straight to the customer's authorization
  endpoint, whether or not that account has federated before. The helper also follows a
  redirect to acme's broker endpoint and a provider link on the page. Those are the shapes
  Keycloak's native organizations produced when this task ran stock Keycloak, and a link
  beside a password field is still rejected by test 1 on its own.

Both corporate accounts are exercised throughout, so a configuration that happens to work
for one hardcoded user does not pass.

What each test establishes:

1. `test_a_corporate_address_is_never_asked_for_an_acme_password` — parametrized over both
   corporate accounts: submitting the address yields a page with no password input. This
   is the core of the request; a realm that simply brokers the provider without
   domain-based discovery shows the password form here.
2. `test_a_corporate_address_is_routed_to_the_customer_idp` — the route actually reaches
   `/realms/contoso-idp/protocol/openid-connect/auth`, rather than merely omitting the
   password field.
3. `test_corporate_sso_login_completes_and_returns_a_code` — the full round trip:
   authenticate at the customer's IdP, come back through the broker, and arrive at
   `http://localhost:9999/callback` with an authorization code and the original `state`.
4. `test_corporate_users_are_federated_and_hold_no_local_password` — after those logins,
   each corporate address exists in `acme` with a non-empty federated identity and **no**
   `password` credential. This forecloses hand-creating local accounts, which would
   otherwise satisfy parts of tests 1–3.
5. `test_an_internal_address_still_logs_in_with_its_password` — `dana` is still offered a
   password field and still completes a login to a code. This is what fails for the
   obvious wrong answer: an identity-provider-redirector execution in a custom browser
   flow forwards *everyone* to the customer's IdP.
6. `test_the_customer_realm_is_unchanged` — `contoso-idp` still has exactly its two
   accounts, its `acme-broker` client is still confidential with the same whitelisted
   redirect URIs and the same client secret, and no identity providers were added to it.
   The customer operates that realm.
7. `test_only_the_expected_realms_exist` — exactly `master`, `acme` and `contoso-idp`.

Reward is all-or-nothing: `1` when every test passes, `0` otherwise. Measured on the
pinned image (build `26.8.2.1794965685`), each in a fresh container:

| Configuration | Fails |
|---|---|
| Untouched fixture | tests 1–4 |
| Organization holds the domain and the provider is linked, but no discovery flow is bound (the stock browser flow stays) | tests 1–4 |
| The organization holds no domains; the domain is sent only when linking the provider | tests 2–4 |
| The provider is never linked to the organization | tests 2–4 |
| An identity-provider-redirector execution with `defaultProvider` in a custom browser flow, no organization | tests 1–5 |
| `auth-password-form` ordered before `ext-auth-home-idp-discovery` in the forms sub-flow | nothing (reward 1) |
| The discovery execution without its config, so `forwardToLinkedIdp` stays `false` | nothing (reward 1) |

With no discovery flow bound, a Contoso address gets the stock username-and-password
form, and linking has hidden the provider's button, so there is no route at all. In the
two "tests 2–4" rows discovery runs and matches nothing, and a Contoso address gets a
`400` "Invalid username or password." page. That page has no password field, so test 1
passes; test 2 is what rejects them.

The two reward-1 rows are not verifier gaps: in both, the logins the verifier drives really
do work. `auth-password-form` is skipped until someone has been identified, so discovery's
username form still comes first. `forwardToLinkedIdp` only lets a user's existing federated links
take precedence over the organization's providers, which changes nothing with one provider
per organization: after the verifier had federated both Contoso users, both were still
forwarded at its default. The domain is never verified either (verification is a DNS TXT
challenge); discovery does not consult it unless the execution's config sets
`requireVerifiedDomain`.

Keycloak's native organizations are switched off on this image, as on every Phase Two
deployment, so `/admin/realms/acme/organizations` returns 404 and the native recipe
cannot be applied at all.

Artifacts copied to `/logs/verifier/`: `output.txt` (full pytest output), `ctrf.json`,
`services-readiness.txt`, `federated-users.txt`, and the rendered identity-first pages as
`identify-<address>.html` for reviewing failures.
