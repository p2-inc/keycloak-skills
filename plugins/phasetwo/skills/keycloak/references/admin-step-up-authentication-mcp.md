<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Step-up authentication with ACR → Level of Authentication (LoA), self-locking sessions — via the Keycloak MCP server

## What this is, and what it isn't

One Keycloak session with **two trust levels** that expire separately:

| Level | Authentication | Session lifespan | Use case |
|---|---|---|---|
| **Level 1 (`silver`)** | Password only | Whole SSO session (10 h default) | General access |
| **Level 2 (`gold`)** | Password + one-time code | **5 minutes** | Sensitive actions (e.g., payments) |

A user with `silver` who opens a feature gated at `gold` gives **only the code**, not the password
again — the session upgrades to `gold` for 5 minutes, then drops back to `silver` without logging
out. This is the "self-locking session": the application stays usable but sensitive features lock.

The mechanism is Keycloak's stock **Conditional - Level Of Authentication** authenticator and **ACR
to LoA mapping**, no extension required. One client can be forced to `gold` even when the app
doesn't request it (using `minimum.acr.value`). Applications gate features on the `acr` claim in
the ID token, not on the request.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm no matching flow already exists | `listAuthenticationFlows` |
| Author the flow structure | `addFlow`, `addSubFlow`, `addAuthenticator` |
| Set requirements on executions | `setExecutionRequirement` |
| Attach condition config | `addAuthenticatorConfig` |
| Reorder if needed | `raiseExecutionPriority` / `lowerExecutionPriority` or `reorderFlowExecutions` |
| Set realm `acr.loa.map` and other realm fields | `updateRealm` |
| Bind to realm or client | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Set client-level `minimum.acr.value` | `updateClient` |
| Confirm bindings | `getAuthenticationBindings` |

## Prerequisite: none

This uses stock Keycloak authenticators and realm configuration only.

## Stage 1 — Establish identity and target realm

`whoAmI`; confirm the target deployment/realm and which client (if any) should be forced to `gold`.

## Stage 2 — Author the flow

The shape (verified live):

| Sub-flow | Execution | Requirement | Why |
|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | Resume existing SSO at current level. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | Federated login, not gated to a level. |
| top-level | *level forms sub-flow* | ALTERNATIVE | Forms when others don't apply. |
| forms | *Level 1 (silver) sub-flow* | ALTERNATIVE | ← **Lowest level first.** Runs on every first login. |
| Level 1 | `auth-username-password-form` | REQUIRED | Password collection and verification. |
| Level 1 | `conditional-level-of-authentication` | REQUIRED | Condition gates with `loa-condition-level=1` — always passes, so password alone works. |
| forms | *Level 2 (gold) sub-flow* | ALTERNATIVE | Requested after Level 1, or always (if client has `minimum.acr.value=gold`). |
| Level 2 | `conditional-level-of-authentication` | REQUIRED | Condition gates with `loa-condition-level=2` — gates the OTP step. |
| Level 2 | `auth-otp-form` | REQUIRED | Code prompt, only reached if condition above passes. |

**Three critical points:**

1. **Levels are ordered lowest first.** The first (Level 1) sub-flow runs on every first login; it
   must hold only the minimal authenticators and its condition. Level 2 first breaks every first
   login.

2. **Each level's condition is REQUIRED** (not CONDITIONAL on a leaf), contains the
   `conditional-level-of-authentication` check, and has distinct `loa-condition-level` values.

3. **Levels are cumulative**: Level 2 includes everything Level 1 requires. A level needing a
   *different* method is the "ACR to flow" client policy, out of scope here.

If the atomic-flows extension is installed and you want it: `importAuthenticationFlow` authors
and binds in one call. Otherwise, use the component path below (the default, always available):

```
addFlow → addSubFlow → addAuthenticator (per leaf, priority explicit) →
setExecutionRequirement → addAuthenticatorConfig on conditions → bind
```

**Component path:**

```bash
addFlow(alias="step-up-flow", type="basic-flow", topLevel=true)

# Top-level: leaves (session resume, federation)
addAuthenticator(flowAlias="step-up-flow", providerId="auth-cookie", requirement="ALTERNATIVE", priority=0)
addAuthenticator(flowAlias="step-up-flow", providerId="identity-provider-redirector", requirement="ALTERNATIVE", priority=10)

# Top-level: forms sub-flow container
addSubFlow(flowAlias="step-up-flow", alias="Step-up forms", type="basic-flow", requirement="ALTERNATIVE", priority=20)

# Forms sub-flow: Level 1 and Level 2 (both ALTERNATIVE, lowest first)
addSubFlow(flowAlias="Step-up forms", alias="Step-up level 1 (silver)", type="basic-flow", requirement="ALTERNATIVE", priority=0)
addSubFlow(flowAlias="Step-up forms", alias="Step-up level 2 (gold)", type="basic-flow", requirement="ALTERNATIVE", priority=10)

# Level 1: password (REQUIRED) + condition (REQUIRED)
addAuthenticator(flowAlias="Step-up level 1 (silver)", providerId="auth-username-password-form", requirement="REQUIRED", priority=0)
addAuthenticator(flowAlias="Step-up level 1 (silver)", providerId="conditional-level-of-authentication", requirement="REQUIRED", priority=10)

# Level 2: condition (REQUIRED) + OTP (REQUIRED)
addAuthenticator(flowAlias="Step-up level 2 (gold)", providerId="conditional-level-of-authentication", requirement="REQUIRED", priority=0)
addAuthenticator(flowAlias="Step-up level 2 (gold)", providerId="auth-otp-form", requirement="REQUIRED", priority=10)
```

**Key points:**
- Pass `priority` **and** `requirement` on every call; omitting `requirement` creates DISABLED steps
  that do nothing.
- Pass `priority` explicitly on both `addSubFlow` and `addAuthenticator` — they **append** without it,
  landing at `last sibling + 1`, so call order alone decides the result. Creating the forms sub-flow
  before `auth-cookie` puts it first.
- `addSubFlow` requires a `type` (here always `"basic-flow"`).

**Verify and repair:**

```bash
listFlowExecutions(flowAlias="step-up-flow")
```

Check the output's `index`, `level`, `priority`, and `requirement` columns match the table above.
The flow and sub-flows are separate sibling sets — fix each level independently. If the order is
wrong, repair with `raiseExecutionPriority` / `lowerExecutionPriority` (each swaps one execution
with one adjacent sibling) or `reorderFlowExecutions` (if available).

## Stage 3 — Attach condition config

Each `conditional-level-of-authentication` execution needs `loa-condition-level` (which level it
gates) and optionally `loa-max-age` (expiry in seconds).

```bash
# Level 1 condition: gates level 1 (password only), max age 36000 s (default, ~10 h).
# The time gates stepping UP from Level 1 to Level 2, not Level 1 itself.
listFlowExecutions(flowAlias="Step-up level 1 (silver)")  # to find the execution ID
addAuthenticatorConfig(
  executionId=<Level 1 condition ID>,
  alias="level1-condition",
  config={"loa-condition-level": "1", "loa-max-age": "36000"}
)

# Level 2 condition: gates level 2 (password + code), max age 300 s (5-minute self-lock).
listFlowExecutions(flowAlias="Step-up level 2 (gold)")  # to find the execution ID
addAuthenticatorConfig(
  executionId=<Level 2 condition ID>,
  alias="level2-condition",
  config={"loa-condition-level": "2", "loa-max-age": "300"}
)
```

## Stage 4 — ACR to LoA mapping

Set the realm attribute mapping ACR names to numeric levels.

```bash
updateRealm(realm=<realm>, attributes={"acr.loa.map": "{\"silver\":1,\"gold\":2}"})
```

A client can override with the same attribute; most deployments leave it on the realm.

## Stage 5 — Bind it

| Surface | Tool |
|---|---|
| Realm-wide | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias="step-up-flow")` |
| Single client | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias="step-up-flow")` |

Ask which the user wants — realm-wide affects every client, including admin and account consoles.
Verify with `getAuthenticationBindings` (pass `clientId` for a client-level binding — realm-level
values alone won't show it).

## Stage 6 — Enforce Level 2 on a specific client (optional)

If one client must **always** get Level 2 even when the app doesn't request it (e.g., a payments
gateway):

```bash
updateClient(clientId=<client>, attributes={"minimum.acr.value": "gold"})
```

This client now always gets `gold`; the app still sees `acr` in the token to act on.

## Stage 7 — Behaviors worth knowing

- **Expiry is lazy.** A level is re-checked only on the next authentication request; tokens already
  issued at `gold` stay valid until they expire naturally (usually 5 minutes for access tokens). The
  realm's access-token lifespan must be ≤ 300 s (Level 2's `loa-max-age`), which is already true by
  default on most deployments.

- **`loa-max-age` `0`** (not used here, but documented for variants) means "this authentication
  only": every request for the level prompts again, giving a payment-confirmation style flow.

- **A level that expired, with no level requested**: SSO still lets the user in, but `acr` is `0`
  (cookie-only). Applications must handle `acr` `0` as "re-authenticate to unlock features".

- **An essential `acr` that is unmapped or above every configured level is an error**, not a
  downgrade. The app saying `claims={"id_token":{"acr":{"essential":true,"values":["platinum"]}}}` where
  only `silver` and `gold` are mapped → Keycloak returns an error.

- **`acr_values` and `default.acr.values` can be rewritten by the user in the browser.** Only
  `minimum.acr.value` on the client, or the app checking `acr` in the token, enforces a level.

- **The realm's default `acr` client scope (with the `oidc-acr-mapper`) already delivers the `acr`
  claim** in the ID token — no extra mapper needed.

## Stage 8 — Verify by logging in, not by reading configuration

1. **No `acr` requested** → password only → ID token `acr` is `silver`.
2. **Same browser session, then `claims` asking for `gold` (essential)** → **only** the code form,
   no password form → enter the code → ID token `acr` is `gold`.
3. **`gold` again straight away** → no prompt (inside the 5 minutes) → `acr` `gold`.
4. **A fresh browser asking for `gold`** → password, then code → `gold`.
5. **A wrong code at the level-2 step** → no authorization code (authentication failed).
6. **`minimum.acr.value` set to `gold` on a client**, no `acr` requested → the code is demanded
   anyway.
7. **An essential `acr` of `platinum` (unmapped)** → an error, not a login.

## Common errors

- **First login always prompts for a code** — Level 2 (the code sub-flow) is before Level 1, or
  Level 1's condition is not the right one.
- **A fresh browser asking for `gold` does not show the password form first** — the Level 1 sub-flow
  is after Level 2, or missing entirely.
- **All users see the code form every login, even without asking** — `minimum.acr.value` is set on
  the realm or a client when it shouldn't be.
- **Level 2 code is demanded but there's no way to provide one** — the realm has no OTP policy, or
  the user has no OTP credential configured, or Level 2's condition is looking for the wrong level
  number.
- **Code prompt keeps appearing even after a correct code** — the level condition's `loa-max-age`
  is `0` (every login re-prompts) or expires very quickly, or no `acr.loa.map` is configured.
- **`acr` never appears in the ID token** — the realm's default `acr` client scope or its
  `oidc-acr-mapper` is missing or disabled.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
