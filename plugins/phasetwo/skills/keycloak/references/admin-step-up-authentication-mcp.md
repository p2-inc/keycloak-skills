<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Step-up authentication with two trust levels — via the Keycloak MCP server

## What this is, and what it isn't

One Keycloak session with two trust levels that expire **separately**:

- **Level 1 (`silver`)**: password-only, valid for the whole SSO session (typically 10 hours).
  Ordinary login and app browsing.
- **Level 2 (`gold`)**: password + one-time code (or another factor), valid for **5 minutes**, then
  the user drops back to `silver` without being logged out. Sensitive operations like payments.

A user already at `silver` who asks for `gold` gives **only the code**, not the password again.
One client can enforce `gold` always (`minimum.acr.value`); others ask per-request. This is
**not** a flat "every login is 2FA" policy (`admin:totp-second-factor`) and not an access-control
gate by organization (`admin:org-restrict-login` — step-up is about *trust*, not *who can log in*).

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm no matching flow already exists | `listAuthenticationFlows` |
| Create the top-level flow | `addFlow` |
| Create a nested level sub-flow | `addSubFlow` |
| Add an authenticator or condition to a flow | `addAuthenticator` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension) |
| Inspect the flow order | `listFlowExecutions` |
| Attach config to the level-1 and level-2 conditions | `setExecutionAuthenticatorConfig` |
| Bind the flow realm-wide or to one client | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Configure outgoing mail | `setSmtpSettings` |
| Configure OTP policy | `setOtpPolicy` |
| Set realm ACR → LoA map | `updateRealmAttributes` |
| Set client `minimum.acr.value` | `updateClientAttributes` |
| Look a user up when testing | `findUser` |

## Prerequisites

1. **Stock Keycloak, no extension required** for the core flow and conditions.
2. **`keycloak-atomic-auth-flows` extension** (optional, for one-shot `importAuthenticationFlow`).
   Without it, fall back to the component path below, which is the default and always available.

## Stage 1 — Establish identity and target realm

```
Call: whoAmI
```

Confirm your deployment and realm. Note the realm name for later steps.

## Stage 2 — Author the step-up flow

Call `listAuthenticationFlows` first to confirm no flow with the target alias already exists.

### Path A: One-shot import with the atomic-flows extension

```
Call: importAuthenticationFlow with:
  authenticationFlows: [
    {
      alias: "step-up-flow",
      providerId: "basic-flow",
      topLevel: true,
      builtIn: false,
      authenticationExecutions: [
        { providerId: "auth-cookie", requirement: "ALTERNATIVE", priority: 0 },
        { displayName: "Level 1", requirement: "ALTERNATIVE", priority: 1, 
          authenticationExecutions: [
            { providerId: "conditional-level-of-authentication", requirement: "REQUIRED", priority: 0 },
            { providerId: "auth-username-password-form", requirement: "REQUIRED", priority: 1 }
          ]
        },
        { displayName: "Level 2", requirement: "ALTERNATIVE", priority: 2,
          authenticationExecutions: [
            { providerId: "conditional-level-of-authentication", requirement: "REQUIRED", priority: 0 },
            { providerId: "auth-otp-form", requirement: "REQUIRED", priority: 1 }
          ]
        }
      ]
    }
  ],
  authenticatorConfig: [
    { alias: "level-1-config", 
      config: { "loa-condition-level": "1", "loa-max-age": "36000" } },
    { alias: "level-2-config",
      config: { "loa-condition-level": "2", "loa-max-age": "300" } }
  ],
  browserFlowBinding: "step-up-flow"
```

The extension hash-prefixes the alias — read it back from the response to get the actual name.
**If this returns 404, the extension isn't installed**; proceed to Path B instead.

### Path B: Component-by-component (always available, no extension)

Build the same structure using the component tools:

```
Call: addFlow with alias="step-up-flow", providerId="basic-flow", topLevel=true

Call: addAuthenticator (to step-up-flow):
  providerId="auth-cookie", requirement="ALTERNATIVE", priority=0

Call: addSubFlow (to step-up-flow):
  alias="Level 1", type="basic-flow", requirement="ALTERNATIVE", priority=1

Call: addSubFlow (to step-up-flow):
  alias="Level 2", type="basic-flow", requirement="ALTERNATIVE", priority=2

Call: addAuthenticator (to Level 1):
  providerId="conditional-level-of-authentication", requirement="REQUIRED", priority=0

Call: addAuthenticator (to Level 1):
  providerId="auth-username-password-form", requirement="REQUIRED", priority=1

Call: addAuthenticator (to Level 2):
  providerId="conditional-level-of-authentication", requirement="REQUIRED", priority=0

Call: addAuthenticator (to Level 2):
  providerId="auth-otp-form", requirement="REQUIRED", priority=1

Call: listFlowExecutions (for step-up-flow) to verify the order matches above
  (index should be: auth-cookie 0, Level 1 sub-flow 1, Level 2 sub-flow 2)
```

### Attaching condition configs

After the flow is created (whether by import or components), attach config to the two conditional
executions:

```
Call: listFlowExecutions (for level-1, filtered to conditional-level-of-authentication)
Call: setExecutionAuthenticatorConfig:
  executionId=<level-1-conditional-id>,
  config={ "loa-condition-level": "1", "loa-max-age": "36000" }

Call: listFlowExecutions (for level-2, filtered to conditional-level-of-authentication)
Call: setExecutionAuthenticatorConfig:
  executionId=<level-2-conditional-id>,
  config={ "loa-condition-level": "2", "loa-max-age": "300" }
```

**Important**: `setExecutionAuthenticatorConfig` needs the execution ID, not the flow. Get it from
`listFlowExecutions` on each sub-flow, filtered by `providerId == "conditional-level-of-authentication"`.

### Why the order is load-bearing

**The flow's first level sub-flow *always runs on a first login***, whatever trust level was
requested. If level 2 runs first, every new user must give an OTP before seeing the password form —
they have no password on file yet, and the flow hangs. Lowest level first ensures the minimal
authenticators run first. See [`flow-execution-order.md`](flow-execution-order.md) for the shape and
ordering rules shared across all flow-authoring intents.

## Stage 3 — Realm ACR → LoA map and OTP policy

```
Call: updateRealmAttributes with:
  attributes: {
    "acr.loa.map": { "silver": "1", "gold": "2" }
  }

Call: setOtpPolicy with:
  policy: {
    type: "totp",
    algorithm: "HmacSHA1",
    digits: 6,
    period: 30,
    activated: true,
    codeReusable: false
  }
```

The `acr.loa.map` maps ACR values like `silver` and `gold` to LoA integers for the flow condition.
The OTP policy sets the code generation (TOTP, 6 digits, 30-second window). `codeReusable: false`
means a code can be used only once in the 30-second window.

## Stage 4 — Realm mail settings

```
Call: setSmtpSettings with:
  smtpServer: {
    host: "<smtp-host>",
    port: "<smtp-port>",
    from: "<from-address>",
    auth: false,
    starttls: false,
    ssl: false
  }
```

Update the values to match your server. The level-2 OTP form needs SMTP to mail codes to users.

## Stage 5 — Bind the flow (if not done via `importAuthenticationFlow`)

If you used `importAuthenticationFlow` in Stage 2 Path A, the binding is already done. Otherwise:

```
Call: bindRealmAuthenticationFlow with:
  flowAlias: "step-up-flow",
  bindingName: "browser"
```

This makes the step-up flow the default for all clients in the realm. To bind to one client instead,
use `bindClientAuthenticationFlow` with `clientId` and `flowAlias`.

## Stage 6 — Enforce step-up on a sensitive client (optional)

To require users accessing a client like `acme-payments` to always be at level 2:

```
Call: updateClientAttributes with:
  clientId: "acme-payments",
  attributes: {
    "minimum.acr.value": "gold"
  }
```

The value `gold` must match a key in the ACR map from Stage 3.

## Application side: requesting a level and checking the token

### Asking for a level in a browser redirect

**Essential claim** (Keycloak returns `gold` or fails):

```
claims={"id_token":{"acr":{"essential":true,"values":["gold"]}}}
```

**Non-essential** (Keycloak tries `gold` but accepts lower if needed):

```
acr_values=gold
```

Both can be tampered with in the browser. To enforce `gold`, rely on `minimum.acr.value` in the
client (Stage 6) or check the ID token's `acr` claim (below).

### Checking the ID token

The token includes an `acr` claim with the user's current level:

```js
// keycloak-js
if (kc.tokenParsed?.acr !== 'gold') {
  // Not at level 2; offer step-up
  kc.login({ acr: { values: ['gold'], essential: true } });
} else {
  // Safe to proceed with the sensitive operation
}
```

For an `acr` of `0` (SSO session, no LoA checked, e.g., after a level-2 token expired), the user is
still logged in but the level is unknown. Applications should handle this like a missing `acr`.

## Behaviors worth knowing

1. **Levels are cumulative.** A user at level 2 automatically satisfies level 1. The condition at
   level 1 checks `current LoA < 1` and skips itself if already satisfied.

2. **Expiry is lazy.** A level is re-checked only when the next authentication request arrives.
   Tokens already issued at level 2 remain valid until they expire naturally (the token's
   `exp` timestamp). To force re-authentication, the application must request a new token (e.g.,
   via a login call or refresh).

3. **An access-token lifespan ≤ level-2 expiry is important.** If `loa-max-age` is 300 seconds
   (level 2's lock time) but the access token lasts 1 hour, a token issued at level 2 will remain
   valid for an hour even after the user drops back to level 1 after 5 minutes. Set the realm's
   access-token lifespan to match or be less than the level's `loa-max-age`. The default realm
   settings already have this right (access token ~5 min, level 2 = 300 s).

4. **`loa-max-age` of `0` means "every request."** Used for payments-style confirmation: every
   request for level 2 prompts for the code again, no caching. A `loa-max-age` of `300` gives
   the self-locking session (5-minute window, then back to level 1).

5. **An unmapped or too-high ACR is an error.** If the app asks for `acr=platinum` and the realm
   has no `platinum` key in its ACR map, Keycloak returns an error, not a downgrade to a lower
   level. Same if the requested ACR value is above every configured level.

6. **A level-2 timeout with no request for a level**: the user is still logged in at level 1
   (the `auth-cookie` path succeeds on the next request). `acr` becomes `0` (SSO session, no LoA
   checked). Applications must handle `acr` of `0` or `null` explicitly, not assume they are the
   same as level 1.

## Variant: different level-2 authenticator

The reference uses `auth-otp-form`, the stock OTP form. Some organizations prefer a PIN code from
a third-party authenticator. Use the same flow shape and order, but substitute the level-2
authenticator in Stage 2:

```
(In the Level 2 sub-flow's authenticationExecutions array, replace:)
{ providerId: "auth-otp-form", requirement: "REQUIRED", priority: 1 }

(With:)
{ providerId: "<alternative-authenticator>", requirement: "REQUIRED", priority: 1 }
```

The shape and order remain the same; only the authenticator changes.

## Verifying this actually works

Testing over HTTP, authorization-code flow against your client (or the default `admin-cli` for
test):

1. **No ACR requested** → password-only login → ID token has `"acr":"silver"`.

2. **Same browser, then ask for `gold` with essential claim** → the form shows **only** the OTP
   field (no password) → submit the OTP code → ID token has `"acr":"gold"`.

3. **Request `gold` again immediately** → no prompt (inside the 5 minutes) → redirects to the
   client → same ID token with `"acr":"gold"`.

4. **Fresh browser, ask for `gold`** → password form, then OTP form (user has no session yet) →
   OTP code → `"acr":"gold"`.

5. **Wrong OTP code at level 2** → rejected, no authorization code.

6. **Client has `minimum.acr.value=gold`**, no ACR requested in the redirect → login flow still
   demands the OTP (enforced by `minimum.acr.value`, not by the user's request).

7. **Ask for unmapped ACR** (e.g., `acr_values=platinum` when only `silver` and `gold` are
   mapped) → error, not a downgrade.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Level 2 is demanded on every first login | Level 2 runs before level 1 in the flow (order is wrong) | Call `listFlowExecutions` on the flow, confirm `Level 1` has a lower index/priority than `Level 2` |
| User at level 1 sees the password form when asking for level 2 | The condition's config is missing or wrong, or the level was set as ALTERNATIVE instead of REQUIRED | Verify level 1 and 2 sub-flows are REQUIRED; level 1/2 conditionals are REQUIRED; use `listFlowExecutions` + `setExecutionAuthenticatorConfig` to attach config |
| OTP code never arrives | Realm SMTP unconfigured; `setSmtpSettings` was not called or values are wrong | Verify SMTP: call `whoAmI`, read the realm attributes to confirm `smtpServer` is set |
| Client says `acr=0` or `null` after logging in | User logged in via `auth-cookie` (existing SSO session) with no LoA check | This is correct behavior: an SSO cookie has no LoA. Application must handle `acr: null` / `"0"` like a missing level, not assume it equals level 1 |
| `minimum.acr.value` doesn't enforce level 2 on a client | The attribute name is wrong or the flow binding is missing | Verify the client has the flow bound to `browser` via `bindClientAuthenticationFlow`, and has attribute `minimum.acr.value` set to `gold` (or whichever ACR value maps to level 2) |

## Additional resources

- [Keycloak Server Administration Guide: Creating a browser login flow with step-up
  mechanism](https://www.keycloak.org/docs/latest/server_admin/index.html#_step-up-flow)
- [Keycloak Server Administration Guide: ACR to Level of Authentication
  (LoA) Mapping](https://www.keycloak.org/docs/latest/server_admin/index.html#_mapping-acr-to-loa-realm)
- [Janua: Self-locking sessions in Keycloak with PIN step-up
  authentication](https://www.janua.fr/self-locking-sessions-in-keycloak-with-pin-step-up-authentication/)
