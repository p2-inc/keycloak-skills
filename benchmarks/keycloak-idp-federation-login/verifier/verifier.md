---
document_version: "0.1"
verifier:
  name: keycloak-idp-federation-login
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

The verifier reads no agent-produced files. It drives real brokered authorization-code
logins against the `acme-portal` client, headlessly: force the redirect to Contoso's
identity provider with `kc_idp_hint`, authenticate there as a real Contoso staff member,
and follow the round trip back to `http://localhost:9999/callback`.

It discovers rather than assumes: the identity provider's alias, whatever the agent chose.
Any correct configuration passes regardless of the alias chosen.

Two logins are driven, for two DIFFERENT, unrelated Contoso staff (`taylor` and `morgan`),
with no `account_hint` at all:

- `taylor` — must complete with an authorization code.
- `morgan` — must ALSO complete with an authorization code.

Requiring both to succeed, with no hint of any kind on the authorization request, is what
actually distinguishes this task from its two siblings in this repo:
`keycloak-corporate-sso-login` (routes by email domain via organization "verified domains")
and `keycloak-idp-org-restrict-login` (gates the brokered login on organization membership
via a custom post-broker flow). A setup that only lets one specific user through, or that
requires an `account_hint` / organization link to succeed at all, is one of those adjacent
capabilities, not this one — and would fail this verifier.

Then, after `taylor`'s login, the verifier confirms Contoso's `email`, `given_name`, and
`family_name` claims actually landed on the brokered Keycloak user as `email`, `firstName`,
and `lastName`.

Finally realm `contoso-idp` must be untouched, and exactly `master`, `acme`, and
`contoso-idp` must exist.
