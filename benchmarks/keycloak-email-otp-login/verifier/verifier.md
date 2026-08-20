---
document_version: "0.1"
verifier:
  name: keycloak-email-otp-login
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

## verifier intent

The verifier reads no agent-produced files. It discovers whichever browser flow is actually in
effect for `acme-portal` - a client-level override wins over the realm default, exactly as
Keycloak resolves it - and inspects that, so any correctly-shaped flow passes regardless of how
it was authored (`importAuthenticationFlow`, a manual REST sequence, or the admin console).

The behavioural checks:

- A **registered** address reaches Keycloak's `login-otp-form` with **no password field**
  anywhere in the flow, a real email arrives containing a numeric code, and submitting that code
  returns to the app's `redirect_uri` with an authorization code and the original `state`.
- An **unregistered** address reaches the *identical* page and receives **no mail**, and no
  account is created for it. This is the check that separates a correct solution from the
  intuitive-but-leaky one: with stock `auth-username-form` as the identifier step, an unknown
  address is rejected up front with "Invalid username or email" *before* `ext-email-otp` ever
  runs, leaking which addresses have accounts. Only an identifier-only step reaches
  `ext-email-otp`'s own anti-enumeration-safe handling.
- Structurally, the bound flow must contain a REQUIRED `ext-email-otp` with some identifier step
  ahead of it at the same nesting level (it reads the attempted username off the auth session
  rather than collecting an address itself).

Every behaviour asserted here was confirmed against a live Keycloak before being written into
the verifier, not inferred from documentation.

### Guarding against vacuous passes

The negative assertions ("no mail was sent") are trivially true on a realm where nothing works
at all, so they are gated behind a `flow_is_live` fixture that first proves the positive path
reaches the emailed-code step. Without that guard, a completely unconfigured realm scored
partial credit on exactly the checks meant to catch a wrong solution. Confirmed by running the
suite against an untouched realm: the substantive tests now fail or error, and only the
"nothing was destroyed" checks pass.
