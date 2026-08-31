---
document_version: "0.1"
verifier:
  name: keycloak-password-email-otp-mfa
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

The verifier reads no agent-produced files. It discovers whichever browser flow is actually in
effect for `acme-portal` - a client-level override wins over the realm default, exactly as
Keycloak resolves it - and inspects that, so any correctly-shaped flow passes regardless of how
it was authored (`importAuthenticationFlow`, a manual REST sequence, or the admin console).

The behavioural checks:

- A **correct** password reaches the emailed-code step, a real email arrives with a numeric code,
  and submitting it returns to the app's `redirect_uri` with an authorization code and the
  original `state`.
- A **wrong** password must produce **no mail at all**. This is the decisive check: a solution
  that merely places a code step in front of a login passes a happy-path test while leaving the
  password irrelevant, since anyone knowing the address would be emailed a code. Only a flow
  where the password step runs first and gates the send satisfies the requirement.
- An **unknown** username likewise produces no mail.
- Structurally, the bound flow must contain a REQUIRED password step (`auth-username-password-form`)
  running *before* a REQUIRED `ext-email-otp` at the same nesting level.

Every behaviour asserted here was confirmed against a live Keycloak before being written into
the verifier, not inferred from documentation.

### Guarding against vacuous passes

The negative assertions ("no mail was sent") are trivially true on a realm where nothing works
at all, so they are gated behind a `flow_is_live` fixture that first proves the positive path
reaches the emailed-code step. Without that guard, a completely unconfigured realm scored
partial credit on exactly the checks meant to catch a wrong solution. Confirmed by running the
suite against an untouched realm: the substantive tests now fail or error, and only the
"nothing was destroyed" checks pass.
