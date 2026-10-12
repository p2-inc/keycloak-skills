---
document_version: "0.1"
verifier:
  name: keycloak-totp-second-factor
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

# keycloak-totp-second-factor Verifier Rubric

- `task_success`: the `acme` realm requires TOTP as a second factor after the password, for
  every user, on `acme-portal`. Scored 1.0 only when every check below holds, 0.0 otherwise.
  The authenticator app is mocked: priya's TOTP credential is seeded with a known secret and
  her codes are computed by the verifier (RFC 6238); Keycloak itself is real.
  - priya's correct password alone does not log her in; it leads to the TOTP code form.
  - Her password plus the current code returns to `http://localhost:9999/callback` with an
    authorization code and the original `state`.
  - Her correct password plus a wrong code is rejected at the code form.
  - A wrong password never reaches the code form.
  - morgan (no authenticator) is not let in on his password: it leads to TOTP enrolment, and
    completing enrolment with a valid first code logs him in and leaves an OTP credential on
    his account. This is the decisive check - Keycloak's default conditional-OTP flow lets
    him straight in.
  - The realm OTP policy is TOTP, 6 digits, 30 seconds.
  - priya and morgan still exist, are enabled, and keep their passwords.
  - Exactly the `master` and `acme` realms exist.
