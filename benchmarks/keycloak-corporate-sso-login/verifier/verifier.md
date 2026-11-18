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
- On the pinned Keycloak (26.8.2), a correctly routed address gets a `303` straight at the
  broker endpoint whether or not that account has federated before. The helper also follows
  a provider link on the page: Keycloak 26.7 and older offered a not-yet-federated user only
  that link, and 26.8 shows it as a button beside the password field when the domain is
  not routed with auto-redirect. Test 1 rejects that second case on its own.

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

Reward is all-or-nothing: `1` when every test passes, `0` otherwise. Measured on Keycloak
26.8.2, each in a fresh container:

| Configuration | Fails |
|---|---|
| Untouched fixture | tests 1–4 |
| Organizations on, organization holds the domain, provider linked, domain not routed (the pre-26.8 recipe) | test 1 |
| Domain routed to the provider without auto-redirect | test 1 |
| Provider never linked to the organization, so the domain cannot be routed to it | test 1 |
| Pre-26.8 routing keys (`kc.org.domain`, `kc.org.broker.redirect.mode.email-matches`) on the provider's config | test 1 |
| The oracle's configuration, then organization support switched off | tests 1–4 |
| An identity-provider-redirector execution in a custom browser flow | tests 1–5 |
| The oracle's configuration with the domain left unverified | nothing (reward 1) |

In the four "test 1" rows the login page still offers the provider as a button beside
the password field, so tests 2–4 follow it and pass. Test 1 is what rejects them.
Whether the domain is marked `verified` changes nothing: Keycloak does not consult the
flag when routing.

Artifacts copied to `/logs/verifier/`: `output.txt` (full pytest output), `ctrf.json`,
`services-readiness.txt`, `federated-users.txt`, and the rendered identity-first pages as
`identify-<address>.html` for reviewing failures.
