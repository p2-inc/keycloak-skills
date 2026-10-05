<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# admin:totp-second-factor (MCP)

Password login hardened with a TOTP code from an authenticator app as a **second factor**, driven through the Keycloak MCP server.

This is **not passwordless**: the password remains required and gates the TOTP step. A wrong password never reaches the OTP form. Users without an OTP credential are sent through `CONFIGURE_TOTP` enrollment at their next login.

## Step 0 — Is the MCP surface actually here?

**Do this before any tool call.** Check your tool list once, now, for:

`bindClientAuthenticationFlow` · `bindRealmAuthenticationFlow` · `setExecutionAuthenticatorConfig` · `whoAmI` · `listRequiredActions` · `enableRequiredAction`

- **All present** → say "Using the Keycloak MCP tools", then follow this skill as written.
- **Any missing** → say "Keycloak MCP tools unavailable in this session (missing: …) — using the Keycloak admin REST API instead", then **keep reading**. Every stage below still applies: the behaviour it configures is a property of Keycloak, not of the transport. Only the calls change — carry out each stage against the admin REST API with an admin token. If the sibling skill `admin-totp-second-factor` (REST) is loaded, use its exact REST recipes.

Decide once, here. Do not call an MCP tool to discover whether it exists, and do not alternate between the two paths afterwards.

## What this is, and what it isn't

Password stays. A correct password is **necessary but not sufficient** — after it, the user must also enter a 6-digit TOTP code from an authenticator app.

| | `admin:password-email-otp-mfa` (email OTP) | This doc (TOTP authenticator app) |
|---|---|---|
| Second factor | `ext-email-otp` (p2-inc extension, emails code) | `auth-otp-form` (stock Keycloak, local generation) |
| SMTP required | Yes | No |
| Enrollment | Automatic on first OTP attempt | Explicit `CONFIGURE_TOTP` required action |
| Offline capable | No | Yes |

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---------|------|
| Identify caller / realm | `whoAmI` |
| Confirm no matching flow already exists | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs atomic-flows extension) |
| Inspect / adjust step priorities | `listFlowExecutions` / `raiseExecutionPriority` / `lowerExecutionPriority` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |
| Manage required actions | `listRequiredActions` / `enableRequiredAction` |
| Look up user credentials | `getUser` / `listUserCredentials` |

## Stage 1 — Establish identity and target realm

`whoAmI`; confirm the target deployment/realm and which client should get password+TOTP.

## Stage 2 — Author the flow

Call `listAuthenticationFlows` first. Then `importAuthenticationFlow` (requires the `keycloak-atomic-auth-flows` extension):

```json
{
  "authenticationFlows": [
    {
      "alias": "totp-second-factor",
      "description": "Browser flow with password + TOTP second factor",
      "providerId": "basic-flow",
      "topLevel": true,
      "builtIn": false,
      "authenticationExecutions": [
        {
          "authenticator": "auth-username-password-form",
          "requirement": "REQUIRED",
          "priority": 10,
          "autheticatorFlow": false
        },
        {
          "authenticator": "auth-otp-form",
          "requirement": "REQUIRED",
          "priority": 20,
          "autheticatorFlow": false
        }
      ]
    }
  ],
  "browserFlowBinding": "totp-second-factor"
}
```

| Execution | Requirement | Why |
|-----------|-------------|-----|
| `auth-username-password-form` | REQUIRED | **The gate.** Stock Keycloak; validates the password before anything else runs. |
| `auth-otp-form` | REQUIRED | Only reached after a correct password. Validates the TOTP code against the user's stored credential. |

**Verified live, not just from source** — three real logins against a running deployment:

| Attempt | Result |
|---------|--------|
| Correct password | Reaches the TOTP form; code entry required |
| **Wrong** password | Rejected immediately — **the TOTP step is never reached** |
| Correct password + wrong TOTP | Rejected at TOTP form with invalid code message |
| Correct password + correct TOTP | Login succeeds, authorization code issued |

The wrong-password row is what proves this is genuinely two-factor: possession of the TOTP secret is worthless without the password, since the TOTP form is never shown until the password step succeeds.

A 404 on `importAuthenticationFlow` means the atomic-flows extension isn't installed; offer it and fall back to `admin-totp-second-factor.md`'s manual REST sequence only if declined.

## Stage 3 — Configure realm OTP policy

The realm OTP policy controls TOTP behavior (algorithm, digits, period). Use the Admin REST API for this (no MCP tool exists):

```
PUT /admin/realms/{realm}
```

```json
{
  "otpPolicyType": "totp",
  "otpPolicyAlgorithm": "HmacSHA1",
  "otpPolicyDigits": 6,
  "otpPolicyLookAheadWindow": 1,
  "otpPolicyPeriod": 30
}
```

## Stage 4 — Enable CONFIGURE_TOTP required action

Users without TOTP credentials must be forced to enroll. Check and enable the required action:

1. `listRequiredActions` — find `CONFIGURE_TOTP`
2. If not enabled, `enableRequiredAction(alias="CONFIGURE_TOTP")`

Without this, users with no TOTP credential fail at login with no clear path to enrollment.

## Stage 5 — Bind it (if not done via import)

| Surface | Tool |
|---------|------|
| Realm-wide | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias="totp-second-factor")` |
| Single client | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias="totp-second-factor")` |

Skip if already bound in the import payload. Ask which the user wants. Verify with `getAuthenticationBindings`, passing `clientId` for a client-level binding.

## Stage 6 — Behaviors worth knowing

- **The password step's brute-force/lockout behavior is whatever the realm already has configured** — this flow doesn't change that.
- **TOTP enrollment is per-user, not realm-wide** — each user completes `CONFIGURE_TOTP` independently, scanning the QR code with their authenticator app.
- **The TOTP secret is stored encrypted per-user** — extract it from the QR code URI (`otpauth://totp/...?secret=...`) during enrollment for testing.
- **Time synchronization matters** — both server and authenticator must have accurate time (within one period, typically 30 seconds).
- **Backup codes are not configured here** — Keycloak supports them but this flow doesn't enable them automatically.

## Stage 7 — Verify by logging in, not by reading configuration

1. **Correct username + correct password** → TOTP form → enter correct code from authenticator app → authorization code, `state` unchanged.
2. **Correct username + wrong password** → rejected immediately, generic message; confirm **no TOTP form appears** — proves the password gates the OTP.
3. **Correct password + wrong TOTP code** → rejected at TOTP form with invalid code message.
4. **User with no TOTP credential** → redirected to `CONFIGURE_TOTP` enrollment screen → scan QR → enter generated code → complete login.

To generate a correct TOTP code for testing, use the secret from the enrollment QR code with standard TOTP algorithms (RFC 6238).

## Common errors

- **TOTP form never appears even with correct password** — flow misordered (OTP step before password) or `auth-otp-form` has wrong requirement.
- **User with no credential gets obscure error instead of enrollment** — `CONFIGURE_TOTP` required action not enabled.
- **Valid TOTP code rejected** — clock skew between server and authenticator; check server time.
- **`importAuthenticationFlow` 404s** — atomic-flows extension not installed; offer it or use manual REST path.
- **Required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
