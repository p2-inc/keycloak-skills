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

## verifier intent

The verifier drives real browser authorization-code logins against `acme-portal` and
`acme-payments`, computing TOTP codes from the pre-configured secrets (RFC 6238,
HMAC-SHA1 over secret UTF-8 bytes, 6 digits, 30 s period), and reading `acr` claims
from the returned ID tokens.

It tests the full session lifecycle:

1. **Fresh login to `acme-portal` with no `acr` requested** — `priya` logs in with password
   only, no code prompt → ID token `acr` is `silver`.

2. **Same browser session, step-up to `gold` with essential claim** — within 5 minutes, ask
   for `gold` as an essential ACR claim → **only the code form appears**, no password form
   → enter code → authorization code returned → ID token `acr` is `gold`.

3. **Immediate re-use of `gold` within 5 minutes** — no prompt (cache hit) → authorization
   code returned → `acr` still `gold`.

4. **Fresh browser, step-up to `gold` on first login** — `morgan` requests `gold` on initial
   login → password form first, then code form → both completed → ID token `acr` is `gold`.

5. **Wrong code at the level-2 step** — incorrect TOTP code entry → authentication fails →
   no authorization code returned.

6. **`acme-payments` with no `acr` requested** — forced to `gold` by `minimum.acr.value` →
   code prompt appears anyway → code entered → `acr` is `gold`.

7. **Unmapped ACR as essential** — request an unmapped level (e.g., `platinum`) as essential
   → Keycloak returns an error, not a login.

8. **Configuration validation** — realm `acr.loa.map` maps `silver` to 1 and `gold` to 2;
   level-2 condition's `loa-max-age` is 300 seconds; access-token lifespan is ≤ 300 s;
   both users still exist and keep their original passwords; only `master` and `acme`
   realms exist.

All page checks quote the page ID and `<form>` HTML when they fail.
