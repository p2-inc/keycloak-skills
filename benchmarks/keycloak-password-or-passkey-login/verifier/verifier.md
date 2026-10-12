---
document_version: "0.3"
verifier:
  name: keycloak-password-or-passkey-login
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

# keycloak-password-or-passkey-login Verifier Rubric

- `task_success`: the `acme` realm offers username/password OR a passkey as alternative
  first factors on one login page for `acme-portal`. Scored 1.0 only when every check below
  holds, 0.0 otherwise.
  - The login page shows the password form and a control leading to the passkey option.
  - `priya` (password, no passkey) completes an authorization-code login with her password
    alone, returning to `http://localhost:9999/callback` with a code and the original `state`.
  - A wrong password is rejected: no callback, the login form is shown again.
  - Requesting `webauthn-register-passwordless` for `marcus` by execute-actions email produces
    captured mail with an action-token link; a real WebAuthn registration (headless browser, CDP
    virtual authenticator) followed by a fresh login with that passkey - never filling in the
    password form - returns to the callback with a code and the original `state`.
  - `marcus`, now holding a passkey, still completes a login with his password alone.
  - `priya` and `marcus` still exist, are enabled, and keep their password credentials.
  - Exactly the `master` and `acme` realms exist.
