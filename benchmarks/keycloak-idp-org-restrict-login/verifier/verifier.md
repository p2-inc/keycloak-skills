---
document_version: "0.1"
verifier:
  name: keycloak-idp-org-restrict-login
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

The verifier reads no agent-produced files. It drives real brokered authorization-code logins
against the `acme-portal` client, headlessly: force the redirect to the partner identity provider
with `kc_idp_hint`, authenticate there as `jordan`, and follow the round trip back — carrying
`account_hint` on the original authorization request the way a real application would.

It discovers rather than assumes: which organization owns the identity provider (by inspecting
the org/IdP links), and which flow alias is bound as `postBrokerLoginFlowAlias` (the atomic-flows
extension hash-prefixes the flows it creates). Any correct configuration passes regardless of the
names chosen.

Three logins are driven:
- `account_hint` naming the **owning** organization — must complete with an authorization code.
  `ext-auth-org-add-user` makes the arriving user a member of that organization, so the gate
  should let them through.
- `account_hint` naming a **different real** organization the user is not a member of — must be
  rejected.
- `account_hint` naming an organization that does not exist — must be rejected.

The middle case is what actually proves this is a membership gate: a post-broker flow that merely
requires *some* `account_hint`, without inspecting real membership, passes the first and third
and fails the second.

Finally the partner realm must be untouched, and exactly `master`, `acme` and `partner-idp` must
exist.
