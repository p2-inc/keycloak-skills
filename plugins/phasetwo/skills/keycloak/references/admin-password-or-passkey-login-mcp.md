<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Username/password OR passkey login — alternative first-factor methods via MCP

## What this is

One browser flow offering **two alternative first-factor authentication methods side by side**:
traditional **username and password** for users who prefer it or haven't set up a passkey yet,
and **passkey (WebAuthn passwordless)** for users who want passwordless authentication. The user
chooses either path at login time through Keycloak's "Try another way" mechanism.

This is neither `admin:passwordless-passkey` (password removed entirely) nor
`admin:zero-password-login` (magic link replaces password). Here the **password remains a valid,
fully supported path** — the passkey is an *additional* option, not a replacement. This is the
"password with passkey option" pattern: keep existing password infrastructure while offering
passkey as a modern alternative.

Say the trade-off: supporting both methods means the account security is bounded by the weakest
credential type registered. A user with *both* a password and a passkey can log in via either.
Accounts with only a password remain subject to password risks; accounts with a passkey gain
phishing resistance but only if the user actually uses it.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Author the flow (and optionally bind it) | `importAuthenticationFlow` |
| Read back execution order | `listFlowExecutions` |
| Passkey policy | `getWebAuthnPasswordlessPolicy` / `setWebAuthnPasswordlessPolicy` |
| Optional: pre-seed a passkey for a user | `findUser` → `sendRequiredActionEmail` |
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

> **Drive this through the MCP tools.** If a required tool is unavailable in this deployment, say
> so and stop. Do **not** silently substitute Admin REST calls.

## Step 1 — Author the flow

`importAuthenticationFlow` is the one-shot path when the [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension is present. The flow shape to create:

| Flow | Execution | Requirement | Priority |
|---|---|---|---|
| `Password-or-passkey` (top level) | `auth-cookie` | ALTERNATIVE | 0 |
| | `auth-spnego` | DISABLED | 1 |
| | `identity-provider-redirector` | ALTERNATIVE | 2 |
| | *forms sub-flow* | ALTERNATIVE | 3 |
| *forms sub-flow* | `auth-username-password-form` | ALTERNATIVE | 2 |
| | `webauthn-authenticator-passwordless` | ALTERNATIVE | 3 |

**Two ALTERNATIVEs in the forms sub-flow offers the choice.** Keycloak renders the
lowest-priority execution it can execute and exposes alternatives through the **"Try another
way"** control. `auth-username-password-form` is deliberately first (lower priority): it works
for *any* user with a password, ensuring the default screen is never a dead end. The passkey
authenticator sits behind "Try another way."

`webauthn-authenticator-passwordless` (priority 3) is the **passwordless** WebAuthn authenticator —
do not confuse it with `webauthn-authenticator` (the second-factor variant). The passwordless
variant allows username-less authentication with discoverable credentials.

### Without the atomic-flows extension

`importAuthenticationFlow` 404s without the extension. Offer it as the one-shot path, but
document the manual component sequence:

1. `addFlow(alias="Password-or-passkey")`
2. `addSubFlow(parentFlowAlias="Password-or-passkey", alias="Password-or-passkey forms", priority=3)`
3. `addAuthenticator` on the top-level flow: `auth-cookie` priority 0, `auth-spnego` priority 1,
   `identity-provider-redirector` priority 2
4. `addAuthenticator` on the forms sub-flow: `auth-username-password-form` priority 2,
   `webauthn-authenticator-passwordless` priority 3
5. `setExecutionRequirement` — ALTERNATIVE for all except `auth-spnego` (DISABLED)
6. `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow`

Pass `priority` explicitly on every call. Read the order back with `listFlowExecutions` before
binding — nothing errors on a wrong order.

## Step 2 — The WebAuthn passwordless policy

`setWebAuthnPasswordlessPolicy` configures the **passwordless** WebAuthn policy (separate from
the realm's ordinary second-factor WebAuthn policy). Critical fields:

- **`rpId`** — the realm's serving hostname, no scheme/port/path. If the realm is reachable at
  multiple hostnames, an empty or mismatched value fails client-side with no server error. Set
  it to the hostname browsers actually navigate to.
- **`requireResidentKey: "Yes"`** — required for passwordless/discoverable credentials to work
  without a username entry step.

`userVerificationRequirement` of `"preferred"` or `"required"` is recommended.

Call `getWebAuthnPasswordlessPolicy` after setting to confirm values landed.

## Step 3 — Bind and confirm

`bindRealmAuthenticationFlow` (realm-wide) or `bindClientAuthenticationFlow` (specific client),
then `getAuthenticationBindings` to verify.

## Step 4 — Verifying this actually works

No tool reports "password-or-passkey login is working". Configuration can look perfect and
still fail at the ceremony (a wrong `rpId` is the classic). **Both** methods have to be driven,
and one of them can't be driven by an HTTP client at all:

| Method | How to verify | Tooling |
|---|---|---|
| Password | Start an authorization-code login, POST username + password to the form's `action` URL, expect a `302` to `redirect_uri` carrying a `code` | Plain HTTP client |
| Passkey | Register via `webauthn-register-passwordless`, then log in through "Try another way" → the `#authenticateWebAuthnButton` control, expect the same `302` with a `code` — **without entering a password** | **Real browser required** |

A passkey ceremony is `navigator.credentials.create()` / `.get()` — actual client-side
JavaScript. Scripting it needs a headless browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `addVirtualAuthenticator`, e.g. Playwright); no HTTP client can fake the
crypto exchange. If no browser is available, report the passkey half as **unverified** rather
than inferring it from configuration.

The decisive check is that the two methods are **alternatives, not two factors**:

- A user with **no** passkey must complete login with the password alone. If the passkey step is
  `REQUIRED` (or the password form is), this flow is password-then-passkey 2FA, and this user is
  stuck after a correct password — the most likely wrong outcome here, and it looks entirely
  correct in the admin console.
- A user **with** a passkey must complete login without typing a password.
- A wrong password must still be rejected — no `code`, the form re-renders with an error. A
  passkey path does not make the password optional for users who choose it.

Also confirm the choice is actually offered: the login page should present the username/password
form *and* a "Try another way" control leading to the passkey option. If only one is reachable,
read the order and requirements back with `listFlowExecutions`; mixing `ALTERNATIVE` with
`REQUIRED` at the same level makes Keycloak ignore the alternatives (see
[`flow-execution-order.md`](flow-execution-order.md)).

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send them
  over `http://localhost` anyway (loopback is a secure context); most HTTP client libraries will
  not, and every form POST then returns `400` *"Cookie not found."* Clear the flag on each
  response (`cookie.secure = False` in Python `requests`).
- A user who has completed a passkey registration and one who hasn't are shown different things
  by the same flow. Test both populations, or a check passes for one and fails for the other.

## Optional — bootstrap passkey enrollment

For users who want to transition from password to passkey: `findUser` → `sendRequiredActionEmail`
with `webauthn-register-passwordless`. That sends an action-token email, so **realm SMTP must be
configured** first, or the call succeeds and no mail arrives. A user who can already sign in with
a password can instead be given the required action on their account directly, with no mail — see
`admin:credential-enrollment` for which mechanism fits which user.
