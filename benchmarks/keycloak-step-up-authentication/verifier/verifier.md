---
document_version: "0.1"
verifier:
  name: keycloak-step-up-authentication
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

# keycloak-step-up-authentication Verifier Rubric

- `task_success`: the `acme` realm implements step-up authentication - two ACR levels
  (`silver`=1, `gold`=2) in one session, expiring separately, with `acme-payments` always
  forced to `gold`. Scored 1.0 only when every check below holds, 0.0 otherwise. The
  authenticator app is mocked: priya's TOTP credential is seeded with a known secret and her
  codes are computed by the verifier (RFC 6238); Keycloak itself is real.
  - No `acr` requested against `acme-portal` → password only → ID token `acr` is `silver`.
  - Same browser session, then an essential `acr=gold` request → only the code form (no
    password form again) → the code → ID token `acr` is `gold`.
  - Requesting `gold` again immediately, same session → no prompt at all → `acr` stays `gold`.
  - A fresh browser session requesting `gold` from the start → password, then code → `gold`.
  - A wrong code at the code prompt → rejected, no authorization code issued.
  - `acme-payments` with no `acr` requested at all → the code is still demanded after the
    password → `acr` is `gold`.
  - An essential, unmapped `acr` (`platinum`) → an authentication error, never a silent login
    at some other level.
  - priya and morgan still exist, are enabled, and keep their original passwords.
  - Exactly the `master` and `acme` realms exist.
