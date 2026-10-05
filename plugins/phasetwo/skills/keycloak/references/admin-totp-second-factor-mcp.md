<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# admin:totp-second-factor (MCP)

Password login hardened with a TOTP code from an authenticator app as a **second factor**, for
**every** user, driven through the Keycloak MCP server.

This is **not passwordless**: the password remains required and gates the TOTP step. A wrong
password never reaches the code form. A user without an authenticator is sent through
`CONFIGURE_TOTP` enrolment straight after their password, and cannot finish logging in without
completing it.

## Step 0 — Is the MCP surface actually here?

**Do this before any tool call.** Check your tool list once, now, for:

`importAuthenticationFlow` · `bindClientAuthenticationFlow` · `bindRealmAuthenticationFlow` · `getAuthenticationBindings` · `listRequiredActions` · `enableRequiredAction` · `whoAmI`

- **All present** → say "Using the Keycloak MCP tools", then follow this skill as written.
- **Any missing** → say "Keycloak MCP tools unavailable in this session (missing: …) — using the Keycloak admin REST API instead", then **keep reading**. Every stage below still applies: the behaviour it configures is a property of Keycloak, not of the transport. Only the calls change — carry out each stage against the admin REST API with an admin token. If the sibling skill `admin-totp-second-factor` (REST) is loaded, use its exact REST recipes.

Decide once, here. Do not call an MCP tool to discover whether it exists, and do not alternate between the two paths afterwards.

## What this is, and what it isn't

Password stays. A correct password is **necessary but not sufficient** — after it, the user must
also enter a 6-digit TOTP code from an authenticator app.

Keycloak's built-in `browser` flow already contains an OTP step, but inside a **CONDITIONAL**
sub-flow: it asks for a code only from users who **already have** an OTP credential, and lets
everyone else in on the password alone. Every user using TOTP needs a flow in which
`auth-otp-form` is **REQUIRED**.

| | `admin:password-email-otp-mfa` (email OTP) | This doc (TOTP authenticator app) |
|---|---|---|
| Second factor | `ext-email-otp` (p2-inc extension, emails code) | `auth-otp-form` (stock Keycloak) |
| SMTP required | Yes | No |
| Enrolment | None: the code goes to the account's email | `CONFIGURE_TOTP` required action |

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---------|------|
| Identify caller / realm | `whoAmI` |
| Confirm no matching flow already exists | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension) |
| Inspect / adjust step priorities | `listFlowExecutions` / `raiseExecutionPriority` / `lowerExecutionPriority` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |
| Manage required actions | `listRequiredActions` / `enableRequiredAction` |
| Find a user | `findUser` |

## Stage 1 — Establish identity and target realm

`whoAmI`; confirm the target deployment/realm and which client should get password+TOTP.

## Stage 2 — Author the flow

Call `listAuthenticationFlows` first. Then `importAuthenticationFlow` (requires the
`keycloak-atomic-auth-flows` extension), with `flowJson`:

```json
{
  "authenticationFlows": [
    {
      "alias": "totp-second-factor",
      "description": "Password, then a TOTP code from an authenticator app.",
      "providerId": "basic-flow", "topLevel": true, "builtIn": false,
      "authenticationExecutions": [
        {"authenticator": "auth-cookie", "authenticatorFlow": false,
         "requirement": "ALTERNATIVE", "priority": 0, "userSetupAllowed": false},
        {"authenticator": "identity-provider-redirector", "authenticatorFlow": false,
         "requirement": "ALTERNATIVE", "priority": 1, "userSetupAllowed": false},
        {"authenticatorFlow": true, "flowAlias": "totp-second-factor forms",
         "requirement": "ALTERNATIVE", "priority": 2, "userSetupAllowed": false}
      ]
    },
    {
      "alias": "totp-second-factor forms",
      "description": "Password, then a TOTP code.",
      "providerId": "basic-flow", "topLevel": false, "builtIn": false,
      "authenticationExecutions": [
        {"authenticator": "auth-username-password-form", "authenticatorFlow": false,
         "requirement": "REQUIRED", "priority": 0, "userSetupAllowed": false},
        {"authenticator": "auth-otp-form", "authenticatorFlow": false,
         "requirement": "REQUIRED", "priority": 1, "userSetupAllowed": false}
      ]
    }
  ],
  "browserFlowBinding": "totp-second-factor"
}
```

| Execution | Requirement | Why |
|-----------|-------------|-----|
| `auth-cookie` | ALTERNATIVE | Keeps single sign-on: a user with a live session is not asked again. |
| *forms sub-flow* | ALTERNATIVE | Holds the two factors, so REQUIRED never sits beside ALTERNATIVE at one level (Keycloak then ignores the alternatives). |
| `auth-username-password-form` | REQUIRED | **The gate.** Validates the password before anything else runs. |
| `auth-otp-form` | REQUIRED | Reached only after a correct password. Checks the code, or sends a user with no authenticator to enrolment. |

- `browserFlowBinding` binds realm-wide. For one client, use
  `"clientFlowBinding": {"clientId": "<client-id>", "browserFlowBinding": "totp-second-factor"}`
  instead; that leaves the realm's `browserFlow` unchanged.
- The extension prefixes every alias with a generated hash. Read the real alias from the
  response; don't assume the one you sent.
- A 404 means the extension isn't installed. Offer it, and fall back to
  `admin-totp-second-factor.md`'s manual REST sequence only if the user declines.

## Stage 3 — Configure the realm OTP policy

No MCP tool sets it. Use the Admin REST API, with one read-modify-write of the realm (exact
command in `admin-totp-second-factor.md`, Stage 3):

```json
{
  "otpPolicyType": "totp",
  "otpPolicyAlgorithm": "HmacSHA1",
  "otpPolicyDigits": 6,
  "otpPolicyPeriod": 30,
  "otpPolicyLookAheadWindow": 1
}
```

## Stage 4 — Make sure `CONFIGURE_TOTP` is enabled

`CONFIGURE_TOTP` is the enrolment screen a user without an authenticator is sent to. It is
enabled in a new realm, but check:

1. `listRequiredActions` — find `CONFIGURE_TOTP`
2. If not enabled, `enableRequiredAction(alias="CONFIGURE_TOTP")` (this registers it first if
   the realm doesn't have it)

Enabling it does not demand it from anyone. The REQUIRED `auth-otp-form` does that, at each
user's next login.

## Stage 5 — Bind it (if not done via import)

| Surface | Tool |
|---------|------|
| Realm-wide | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias=<alias from the import response>)` |
| Single client | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias=<alias from the import response>)` |

Skip if already bound in the import payload. Ask which the user wants. Verify with
`getAuthenticationBindings`, passing `clientId` for a client-level binding and reading its
`effective` block.

## Stage 6 — Behaviors worth knowing

- **Brute-force/lockout on the password step is whatever the realm already has configured.**
  This flow doesn't change it.
- **TOTP enrolment is per user.** Each user completes `CONFIGURE_TOTP` once, scanning the QR
  code (or typing the key shown behind "Unable to scan?") into their authenticator app.
- **Time matters.** `otpPolicyLookAheadWindow: 1` accepts the code from the period on either side
  of the current one; larger clock skew than that rejects valid codes.
- **A code works once.** By default (`otpPolicyCodeReusable: false`) the same code can't be used
  twice.
- **Recovery codes are not configured here.** Keycloak supports them, but this flow doesn't
  enable them.

## Stage 7 — Verify by logging in, not by reading configuration

1. **Correct password, user with an authenticator** → the code form, not a login → the correct
   code → authorization code, `state` unchanged.
2. **Wrong password** → rejected, generic message; confirm **no code form appears**, which proves
   the password gates the code.
3. **Correct password + wrong code** → rejected at the code form.
4. **Correct password, user with no authenticator** → the enrolment screen, not a login →
   enter a valid first code → login completes and the account now has an `otp` credential.
   **This is the decisive check**: the stock flow lets this user straight in.

To drive these with an HTTP client: the enrolment form holds the secret in a hidden field
`totpSecret`, and the TOTP key is that value's UTF-8 bytes (RFC 6238; details and a code
generator in `admin-totp-second-factor.md`, Stage 6). Don't reset a real user's password to
test; use a throwaway test user.

## Common errors

- **A user without an authenticator logs in with the password alone** — the stock `browser` flow
  (conditional OTP) is still bound, or `auth-otp-form` is not REQUIRED.
- **Code form appears before the password, or a wrong password reaches it** — the sub-flow's
  priorities are reversed; check with `listFlowExecutions`.
- **User with no credential gets an error instead of enrolment** — `CONFIGURE_TOTP` is not
  enabled.
- **Valid code rejected** — clock skew, or the code was already used this period.
- **`importAuthenticationFlow` 404s** — the atomic-flows extension isn't installed; offer it, or
  use the manual REST path.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
