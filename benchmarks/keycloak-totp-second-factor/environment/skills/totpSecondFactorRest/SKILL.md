---
name: totpSecondFactorRest
description: >-
  totp-second-factor
---

# admin:totp-second-factor (REST)

Password login hardened with a TOTP code from an authenticator app as a **second factor**.

This is **not passwordless**: the password remains required and gates the TOTP step. A wrong password never reaches the OTP form. Users without an OTP credential are sent through `CONFIGURE_TOTP` enrollment at their next login.

Compared to `admin:password-email-otp-mfa`, this uses:
- `auth-otp-form` (stock Keycloak built-in) instead of `ext-email-otp` (p2-inc extension)
- No SMTP required — the secret is shown on-screen during enrollment
- Realm OTP policy controls the algorithm, digits, and period

## Prerequisites

- Keycloak Admin REST API access
- Optional: `keycloak-atomic-auth-flows` extension for `importAuthenticationFlow`; otherwise use manual component-by-component authoring

## Stage 1 — Verify no matching flow exists

List authentication flows and check that no `totp-second-factor` (or your chosen alias) already exists.

```
GET /admin/realms/{realm}/authentication/flows
```

## Stage 2 — Author the flow

### Option A: Atomic import (with extension)

`PUT /admin/realms/{realm}/authentication-flows/import` with this payload:

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

The `browserFlowBinding` makes this the realm's default browser flow in one call.

### Option B: Manual component authoring

Without the extension, build the flow step by step:

1. **Create the flow:**
   ```
   POST /admin/realms/{realm}/authentication/flows
   ```
   ```json
   {
     "alias": "totp-second-factor",
     "description": "Browser flow with password + TOTP second factor",
     "providerId": "basic-flow",
     "topLevel": true,
     "builtIn": false
   }
   ```

2. **Add the password form execution:**
   ```
   POST /admin/realms/{realm}/authentication/flows/totp-second-factor/executions/execution
   ```
   ```json
   {
     "provider": "auth-username-password-form"
   }
   ```
   Then set requirement to `REQUIRED` via `PUT /admin/realms/{realm}/authentication/flows/totp-second-factor/executions/{executionId}`.

3. **Add the OTP form execution:**
   ```
   POST /admin/realms/{realm}/authentication/flows/totp-second-factor/executions/execution
   ```
   ```json
   {
     "provider": "auth-otp-form"
   }
   ```
   Set requirement to `REQUIRED`.

4. **Set execution priorities** (Keycloak 25+) or use `raiseExecutionPriority`/`lowerExecutionPriority` to ensure `auth-username-password-form` runs before `auth-otp-form`.

## Stage 3 — Configure realm OTP policy

Set the realm's OTP policy to define TOTP behavior:

```
PUT /admin/realms/{realm}
```

```json
{
  "otpPolicyType": "totp",
  "otpPolicyAlgorithm": "HmacSHA1",
  "otpPolicyDigits": 6,
  "otpPolicyInitialCounter": 0,
  "otpPolicyLookAheadWindow": 1,
  "otpPolicyPeriod": 30,
  "otpSupportedApplications": ["FreeOTP", "Google Authenticator", "Microsoft Authenticator"]
}
```

## Stage 4 — Enable the CONFIGURE_TOTP required action

Ensure `CONFIGURE_TOTP` is enabled so users without credentials are forced to enroll:

```
GET /admin/realms/{realm}/authentication/required-actions
```

Find `CONFIGURE_TOTP` and verify `enabled` is `true`. If not:

```
PUT /admin/realms/{realm}/authentication/required-actions/CONFIGURE_TOTP
```

```json
{
  "alias": "CONFIGURE_TOTP",
  "name": "Configure OTP",
  "providerId": "CONFIGURE_TOTP",
  "enabled": true,
  "defaultAction": false,
  "priority": 10,
  "config": {}
}
```

## Stage 5 — Bind the flow (if not done via import)

If you used Option B:

```
PUT /admin/realms/{realm}
```

```json
{
  "browserFlow": "totp-second-factor"
}
```

Or bind to a specific client:

```
PUT /admin/realms/{realm}/clients/{client-id}
```

```json
{
  "authenticationFlowBindingOverrides": {
    "browser": "totp-second-factor"
  }
}
```

## Stage 6 — Verification

Verify the flow end-to-end with real TOTP codes:

| Scenario | Expected Result |
|----------|-----------------|
| Correct password + correct TOTP code | Login succeeds, authorization code issued |
| Correct password + wrong TOTP code | Rejected at OTP form, no login |
| Wrong password | Rejected at password form, never reaches OTP step |
| Correct password, user has no TOTP credential | Redirected to `CONFIGURE_TOTP` enrollment, then completes login |

To compute a correct TOTP code for testing:
1. Complete `CONFIGURE_TOTP` for a test user
2. Extract the TOTP secret (base32) from the enrollment QR code
3. Generate current-period TOTP using the secret, algorithm (HmacSHA1), digits (6), and period (30s)

## Key differences from email-OTP MFA

| Aspect | Email OTP (`admin:password-email-otp-mfa`) | TOTP (`admin:totp-second-factor`) |
|--------|--------------------------------------------|-----------------------------------|
| Second factor | `ext-email-otp` (p2-inc extension) | `auth-otp-form` (stock Keycloak) |
| SMTP required | Yes | No |
| Code delivery | Email sent after password verification | Generated locally from stored secret |
| Enrollment | Automatic on first use | Explicit `CONFIGURE_TOTP` required action |
| Offline capable | No | Yes (time-based, no server contact needed) |
