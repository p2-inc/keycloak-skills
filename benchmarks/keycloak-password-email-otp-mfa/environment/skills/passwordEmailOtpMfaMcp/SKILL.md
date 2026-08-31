---
name: passwordEmailOtpMfaMcp
description: >-
  Harden existing password login with a one-time code emailed as a SECOND factor, on a Phase
  Two hosted Keycloak, driven through the Keycloak MCP server. Use this for "2FA by email",
  "MFA by email", "require a code after the password", or "email-based two-factor". The
  password stays required and gates the code - a wrong password must never send mail. Not
  passwordless email OTP (a different flow that removes the password), and not WebAuthn or
  TOTP as a second factor.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# passwordEmailOtpMfaMcp

## What this is, and what it isn't

Password stays. A correct password is **necessary but not sufficient** — after it, the user must
also enter a 6-digit code emailed to their account. Not passwordless: traditional login hardened
with a second factor, using a *different* first step than `admin-email-otp-login-mcp.md`'s fully
passwordless flow:

| | `admin:email-otp-login` (passwordless) | This doc (password + OTP, two-factor) |
|---|---|---|
| First step | `ext-auth-username-auth-note` (identifier only) | `auth-username-password-form` (stock Keycloak — validates the password) |
| Getting the emailed code requires... | Just typing a known email address | Knowing the account's **password** |
| Security model | Possession of the inbox is the only factor | Password + inbox |

Both use `ext-email-otp` as the second execution and both need realm SMTP; only the first step
differs, and that's the entire point.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm no matching flow already exists | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension) |
| Inspect / adjust the `ext-email-otp` step's config | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Configure outgoing mail | `setSmtpSettings` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |
| Look a user up when testing | `findUser` |

## Prerequisite: the keycloak-magic-link extension

Same as plain email OTP: `ext-email-otp` comes from
**[p2-inc `keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link)**, not stock
Keycloak. If unavailable, say so and stop rather than substituting Keycloak's own OTP.

## Stage 1 — Establish identity and target realm

`whoAmI`; confirm the target deployment/realm and which client should get password+OTP.

## Stage 2 — Author the flow

Call `listAuthenticationFlows` first. Then `importAuthenticationFlow` with the arrays from
[`../assets/username-password-email-otp-flow.partial-import.json`](../assets/username-password-email-otp-flow.partial-import.json),
plus the binding:

```json
{
  "authenticationFlows": [ /* from the asset */ ],
  "authenticatorConfig": [ /* from the asset */ ],
  "browserFlowBinding": "email-otp-flow"
}
```

**This is the one place `auth-username-password-form` is the *right* identifier step** — the
opposite of plain email OTP, where the same authenticator would wrongly demand a password in a
flow meant to have none. Here demanding the password is the entire point:

| Execution | Requirement | Why |
|---|---|---|
| `auth-username-password-form` | REQUIRED | **The gate.** Stock Keycloak; validates the password before anything else runs. |
| `ext-email-otp` | REQUIRED | Only reached after a correct password. Generates the code, mails it, verifies the input. |

**Verified live, not just from source** — three real logins against a running deployment:

| Attempt | Result |
|---|---|
| Correct password | Reaches the OTP form; a real code is emailed |
| **Wrong** password | Rejected with `"Invalid username or password."` — **the OTP step is never reached, no mail sent** |
| Unknown username | Same generic message as wrong password — no separate signal |

The wrong-password row is what proves this is genuinely two-factor: knowing the email address is
worthless without the password, since the code is never sent until the password step succeeds.

The extension hash-prefixes the created alias — read it back from the response rather than
assuming. A 404 means the atomic-flows extension isn't installed; offer it and fall back to
`admin-password-email-otp-mfa.md`'s manual REST sequence only if declined.

## Stage 3 — The one config option

Same shared key as plain email OTP: `ext-magic-create-nonexistent-user`. It matters less here — a
user needs a password to reach this step at all — but leave it at its safe `false` default
unless there's a specific reason for this flow to create accounts. Use
`setExecutionAuthenticatorConfig` to change it, finding the execution with `listFlowExecutions`.

## Stage 4 — Realm mail settings

`setSmtpSettings`. Same silent-failure trap as every magic-link-family flow — verify by checking
what actually left, not by trusting success.

## Stage 5 — Bind it

| Surface | Tool |
|---|---|
| Realm-wide | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias=...)` |
| Single client | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias=...)` |

Skip if already bound in the import payload. Ask which the user wants. Verify with
`getAuthenticationBindings`, passing `clientId` for a client-level binding — the realm-level
values alone won't show it.

## Stage 6 — Behaviors worth knowing

- **The password step's brute-force/lockout behavior is whatever the realm already has
  configured** — this flow doesn't need the separate brute-force decision the fully-passwordless
  variant does, since the password step already gates guessing before OTP is ever reached.
- **This doesn't change password reset/recovery** — it only adds a second factor on top of
  existing password login.
- **A fresh test user with no name on file** can pick up `VERIFY_PROFILE`, interrupting right
  after a correct code with an unrelated profile screen — not a flow bug.
- Everything else about `ext-email-otp` (no independent TTL, auth-session-note caching,
  built-in resend) is identical to the passwordless variant — see `admin-email-otp-login-mcp.md`.

## Stage 7 — Verify by logging in, not by reading configuration

1. Correct username + correct password → OTP form → real emailed code → authorization code,
   `state` unchanged.
2. Correct username + **wrong** password → rejected immediately, generic message; confirm **no
   mail was sent** — proves the password gates the OTP rather than merely preceding it.
3. Unknown username → same generic rejection as (2), no separate signal.

## Common errors

- **OTP email never arrives even after a correct password** — realm SMTP unconfigured (Stage 4).
- **A wrong password still reaches the OTP form** — the flow was authored with the wrong
  identifier step (e.g. `ext-auth-username-auth-note`, which doesn't check a password at all)
  instead of `auth-username-password-form`.
- **Unknown users get a different error than wrong-password users** — not stock behavior; check
  nothing custom sits in front of the combined form.
- **`ext-email-otp` not offered** — the `keycloak-magic-link` extension isn't installed.
- **A fresh test user hits an unrelated profile screen after the correct code** —
  `VERIFY_PROFILE`, not a flow bug.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.