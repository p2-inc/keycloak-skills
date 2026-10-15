---
name: stepUpAuthenticationMcp
description: >-
  step-up-authentication
---

# Step-up authentication: ACR → LoA, self-locking sessions — via MCP

Same outcome as [`admin-step-up-authentication.md`](admin-step-up-authentication.md); read that
file for the flow shape, ACR → LoA mapping, application side, the please-openit PIN variant, the
traps, and verification steps — they aren't duplicated here. This file is the MCP tool mapping onto
that same shape. Also read [`flow-execution-order.md`](flow-execution-order.md) before authoring:
the two level sub-flows here are CONDITIONAL, and their relative order (level 1 before level 2) is
load-bearing in exactly the way that file warns about.

## Tools

| Step | Tool |
|---|---|
| Top-level flow | `addFlow` |
| `auth-cookie`, `identity-provider-redirector` | `addAuthenticator` (ALTERNATIVE, with `priority`) |
| "Step-up forms" sub-flow | `addSubFlow` (ALTERNATIVE, with `priority`) |
| "Levels" sub-flow | `addSubFlow` (REQUIRED, with `priority`) |
| "Level 1" / "Level 2" CONDITIONAL sub-flows + their condition | `addConditional` — builds the CONDITIONAL-sub-flow-plus-condition shape in one call; still pass `priority` so Level 1 lands before Level 2 |
| `auth-username-password-form` inside Level 1, `auth-otp-form` inside Level 2 | `addAuthenticator` (REQUIRED) |
| The condition's config (`loa-condition-level`, `loa-max-age`) | `addAuthenticatorConfig` |
| Verify order and shape | `listFlowExecutions` |
| Repair order | `raiseExecutionPriority` / `lowerExecutionPriority`, or `reorderFlowExecutions` where present |
| ACR → LoA map, client `minimum.acr.value` | `updateRealm` / `updateClient` (both expose a raw attributes map; there is no dedicated step-up tool) |
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |

Confirm `addConditional`, `addAuthenticatorConfig`, and `listFlowExecutions` are present before
starting — the component path in `references/README.md`'s "Authoring flows" section is the default
even on MCP, since no single tool authors this whole shape in one call. If the server also exposes
`importAuthenticationFlow` (the keycloak-atomic-auth-flows extension), a hand-authored
`*.partial-import.json` of the shape in `admin-step-up-authentication.md` works the same way the
other intents' assets do and avoids the order-repair step entirely, since the import carries the
asset's own `priority` values.

## Build order

1. `addFlow` — the top-level flow.
2. `addAuthenticator` × 2 — `auth-cookie`, `identity-provider-redirector`, both ALTERNATIVE,
   `priority` 0 and 10.
3. `addSubFlow` — "Step-up forms", ALTERNATIVE, `priority` 20.
4. `addSubFlow` — "Levels", REQUIRED, nested inside "Step-up forms".
5. `addConditional` — "Level 1", nested inside "Levels", `priority` 0, with its condition
   (`conditional-level-of-authentication`, `loa-condition-level=1`, `loa-max-age=36000`).
6. `addAuthenticator` — `auth-username-password-form`, REQUIRED, inside "Level 1".
7. `addConditional` — "Level 2", nested inside "Levels", `priority` 10 — **after** Level 1; getting
   this order backwards demands the OTP step on every first login (see the shared reference file's
   "traps" for why).
8. `addAuthenticator` — `auth-otp-form`, REQUIRED, inside "Level 2".
9. `addAuthenticatorConfig` on each level's condition execution with its own `loa-condition-level`
   / `loa-max-age` — the two conditions are separate executions sharing a providerId, so match each
   one within its own sub-flow, not by providerId alone.
10. `listFlowExecutions` — verify the whole tree: every level bucket-pure, Level 1 before Level 2.
    Repair with `raiseExecutionPriority`/`lowerExecutionPriority` if not.
11. `updateRealm` — set `attributes["acr.loa.map"]` to the JSON string `{"silver":1,"gold":2}`.
12. `updateClient` on the client that must always step up (e.g. `acme-payments`) — set
    `attributes["minimum.acr.value"]` to `"gold"`.
13. `bindRealmAuthenticationFlow` (or `bindClientAuthenticationFlow` for a single client) to the new
    flow's alias/id.

Verify with real logins exactly as in the shared reference file's "Verifying this actually works" —
config read-back alone doesn't catch an order mistake.
