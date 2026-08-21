---
document_version: "0.3"
verifier:
  name: keycloak-passwordless-passkey-login
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
# keycloak-passwordless-passkey-login Verifier Rubric

- `task_success`: the `acme` realm lets `priya` and `marcus` log in with a WebAuthn
  passkey and never shows a password field, with or without a registered credential.
  Scored 1.0 only when every check below holds, 0.0 otherwise.
  - Starting from zero credentials, requesting the `webauthn-register-passwordless`
    required action produces captured mail with an action-token link.
  - Opening that link and completing a real WebAuthn registration ceremony (a headless
    browser with a CDP virtual authenticator) never shows a password field.
  - A fresh authorization-code login using that same passkey never shows a password
    field, and returns the browser to `http://localhost:9999/callback` carrying an
    authorization code, with the `state` the application sent returned unchanged.
  - A login attempt with no registered credential at all still never falls back to a
    password field.
  - `priya` and `marcus` both still exist and are enabled.
  - Exactly the `master` and `acme` realms exist.
