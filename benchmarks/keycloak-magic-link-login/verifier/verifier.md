---
document_version: "0.3"
verifier:
  name: keycloak-magic-link-login
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

The verifier reads no agent-produced files. Everything is checked by performing real
browser authorization-code logins against the `acme-portal` client, headlessly: fetch the
login page, submit an email address, and read what actually happened - the mail the
realm's mail-capture server received, and the realm's user list - because the login
page's response is identical by design whether or not the address is registered.

Both seeded accounts (`priya`, `marcus`) are exercised, so a configuration that happens to
work for one hardcoded user does not pass.

What each test establishes:

1. `test_a_known_address_receives_mail_with_no_password_prompt` — parametrized over both
   accounts. Submitting the address shows no password field, and mail is captured
   containing an `action-token` link. Fails while SMTP is unconfigured, since the
   authenticator's send call raises internally and is swallowed rather than surfaced.
2. `test_the_emailed_link_completes_login_and_preserves_state` — the captured link, opened
   with nothing else entered, ends at `http://localhost:9999/callback` carrying an
   authorization code and the original `state` value unchanged.
3. `test_an_unregistered_address_gets_the_same_response_as_a_registered_one` — the login
   page's status code for an address belonging to no account matches a registered one's.
   This is inherent to the authenticator (an anti-enumeration design choice), so it
   mainly guards against a configuration having broken it rather than something the
   agent could get subtly wrong.
4. `test_no_mail_or_account_is_created_for_an_unregistered_address` — the real
   discriminator. Behind that identical page response, the unregistered address must
   produce no captured mail and no new user. The `ext-magic-form` authenticator's
   "create user if none exists" setting defaults to `true`; left alone, an unregistered
   email silently gets an account and a login link with no visible sign anything
   happened. Verified as an isolated failure: with SMTP and the flow binding both correct
   but this one setting left at its default, exactly this test fails and every other test
   still passes.
5. `test_existing_accounts_still_exist_and_are_enabled` — `priya` and `marcus` remain,
   enabled.
6. `test_only_the_acme_realm_was_added` — exactly `master` and `acme` exist.

Reward is all-or-nothing: `1` when every test passes, `0` otherwise.

Artifacts copied to `/logs/verifier/`: `output.txt` (full pytest output), `ctrf.json`,
`services-readiness.txt`, and the rendered login-page responses as
`submit-<address>.html` for reviewing failures.
