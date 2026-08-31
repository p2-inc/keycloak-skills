---
document_version: "0.1"
verifier:
  name: keycloak-org-restrict-login
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

The verifier reads no agent-produced files. The task fixes the exact `account_hint` value
("engineering") the application always sends - since the application never learns a
server-generated organization ID, this pins the only valid solution shape to
`match_by_org_name=true` with an organization literally named `engineering`; a flow
configured to match by ID cannot work for this app no matter how it's built, and the
verifier deliberately does not adapt to whatever the agent happened to configure - it
checks for exactly this shape and performs real browser authorization-code logins against
the `acme-portal` client with the literal `account_hint=engineering`, the same way the
real application would.

Three logins are driven:
- `priya` (seeded as a plain user with a password, membership added by the agent) with the
  correct `account_hint` for her organization - must succeed with an authorization code.
- `priya` with an `account_hint` that matches no real organization - must be rejected.
- `morgan` (seeded the same way, but never added to the organization) with the correct
  `account_hint` for the organization she is NOT a member of - must be rejected.

The third case is what actually proves this is a membership gate: a flow that merely
requires *some* account_hint value, without checking real membership, would pass the first
two checks but let `morgan` through on the third.

Finally, exactly `master` and the target realm must exist - nothing else should have been
created or removed.
