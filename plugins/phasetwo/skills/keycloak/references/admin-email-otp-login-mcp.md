# Passwordless login by emailed one-time code (email OTP) — via the Keycloak MCP server

## What this is, and what it isn't

The user types an identifier, receives a **6-digit numeric code by email**, and types it in to
finish logging in. No password, ever. This is the sibling mechanism
`admin-passwordless-magic-link-mcp.md` explicitly excludes ("a one-time code typed in — a sibling
authenticator, not covered here"):

| | Magic link | Email OTP (this doc) |
|---|---|---|
| What arrives | A signed action-token **link** to click | A **6-digit code** to type |
| Authenticator | `ext-magic-form` | `ext-email-otp` |
| Built-in flow ships with the provider? | Yes (`magic link`, auto-created) | **No — must be authored** |

Both come from the same `keycloak-magic-link` extension and both need realm SMTP.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm no email-OTP flow already exists | `listAuthenticationFlows` |
| Author the flow **and bind it**, in one call | `importAuthenticationFlow` (needs the atomic-flows extension) |
| Inspect / adjust the `ext-email-otp` step's config | `listFlowExecutions` / `setExecutionAuthenticatorConfig` |
| Configure outgoing mail | `setSmtpSettings` |
| Turn on brute-force protection (see Stage 5 — it matters here) | `setBruteForceProtection` |
| Bind an already-existing flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |
| Look a user up when testing | `findUser` |

## Prerequisite: the keycloak-magic-link extension

`ext-email-otp` comes from **[p2-inc `keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link)**
— the same jar that provides `ext-magic-form` — not from stock Keycloak. Phase Two's own
distribution bundles it. Keycloak's built-in OTP authenticators are TOTP/HOTP against an
authenticator app, which is a different mechanism requiring device enrollment; there is no stock
equivalent to email OTP. If the authenticator isn't available on the target, say so and stop
rather than substituting TOTP.

## Stage 1 — Establish identity and target realm

Call `whoAmI`; tell the user who they are and which realm the token came from. Confirm the target
deployment/realm and which client should use email OTP.

## Stage 2 — Author the flow (no built-in one exists)

Call `listAuthenticationFlows` first. Unlike magic-link — where the provider auto-creates a
`magic link` flow on every realm — **nothing auto-creates an email-OTP flow**, so expect to author
one.

Call `importAuthenticationFlow` with the arrays from
[`../assets/email-otp-flow.partial-import.json`](../assets/email-otp-flow.partial-import.json),
plus the binding in the same payload:

```json
{
  "authenticationFlows": [ /* from the asset */ ],
  "authenticatorConfig": [ /* from the asset */ ],
  "browserFlowBinding": "email-otp-flow"
}
```

For one client instead of realm-wide, use `clientFlowBinding: {clientId, browserFlowBinding}`.
The extension hash-prefixes the alias it creates, so read the real one back from the response
rather than assuming. A 404 means the atomic-flows extension isn't installed — offer installing
it first. **If declined, the fallback stays inside MCP — no raw REST, no credentials from the
user**: `createAuthenticationFlow` → `addAuthenticationSubFlow` for the forms sub-flow →
`addAuthenticationExecution` for `auth-cookie`, `identity-provider-redirector`,
`ext-auth-username-auth-note`, `ext-email-otp` (**in that order**, `priority` passed explicitly
on every call — both add calls append when it's omitted) → `setExecutionRequirement` on each →
`setExecutionAuthenticatorConfig` on `ext-email-otp` for the option below → bind. Read the order
back with `listFlowExecutions` before calling it done.

**The execution order inside the forms sub-flow is load-bearing, and so is WHICH authenticator
collects the identifier** — verify both if authoring by hand rather than from the asset:

| Execution | Requirement | Why this authenticator, and why this position |
|---|---|---|
| `ext-auth-username-auth-note` | REQUIRED | `ext-email-otp` reads the *attempted username* off the auth session rather than collecting an address itself, so an identifier step must run first. Use this authenticator specifically (p2-inc `keycloak-orgs`), **not** stock `auth-username-form` — see Stage 3's anti-enumeration note for why the choice is load-bearing, not cosmetic. |
| `ext-email-otp` | REQUIRED | Generates the code, mails it, renders the code form, verifies the input. |

Putting `ext-email-otp` first, or omitting the identifier step entirely, yields a silent no-email
outcome rather than an error.

## Stage 3 — The identifier-step choice decides anti-enumeration, and the one config option

**Verified empirically, not just from source — this is the trap that survives even a correct
reading of the authenticator code**, because the leak comes from a different authenticator
entirely:

- Identifier step = stock `auth-username-form` → an unregistered address gets
  **"Invalid username or email."** on the spot, before `ext-email-otp` ever runs. Real
  enumeration, regardless of `ext-email-otp`'s own config.
- Identifier step = `ext-auth-username-auth-note` (Stage 2's choice) → an unregistered address
  reaches `ext-email-otp`, whose null-user handling *is* anti-enumeration-safe with force-create
  off: identical code-form response, no email, no error.

So "unregistered address gets an identical response" only holds for the specific authenticator
combination this asset uses — don't assume it for any email-OTP flow you didn't author this way.

`ext-email-otp` has exactly **one** configurable property beyond the identifier-step choice
above, and it is the same key magic-link uses (a shared constant in the extension), which is why
it reads oddly here: `ext-magic-create-nonexistent-user`.

**Its default differs from magic-link's, in the safe direction.** Verified in the extension's
source: `ext-magic-form` defaults it to `true` (silently provisioning an account for any address
typed — the trap the magic-link references warn about), while `ext-email-otp` defaults it to
**`false`**. So there is nothing to remember to turn off here; the asset sets it explicitly as
documentation. Set it to `"true"` only if self-registration by OTP is genuinely wanted (and note
that also reopens the enumeration question, since a match will now always exist).

To change it later, use `setExecutionAuthenticatorConfig` on the `ext-email-otp` execution — find
it with `listFlowExecutions` first.

Nothing else is tunable. The code is always a 6-digit numeric string, with no configurable
length, alphabet, or separate TTL.

## Stage 4 — Realm mail settings

`setSmtpSettings`. Same silent-failure trap as magic-link: a realm ships with no SMTP settings and
a failed send is swallowed internally, so an unconfigured realm looks identical to a working one
from the caller's side. Verify by checking what actually left (a capture point in test contexts),
not by trusting a success response.

## Stage 5 — Turn on brute-force protection (specific to this mechanism)

A wrong code is raised as an `INVALID_CREDENTIALS` failure challenge, so the realm's brute-force
settings are what actually govern guessing. Realms ship with brute-force **off**, and a 6-digit
code with unlimited attempts is weak — call `setBruteForceProtection` when standing this up, and
ask whether lockout should be temporary (auto-recovering) or permanent.

## Stage 6 — Bind it

| Surface | Tool |
|---|---|
| Realm-wide | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias=...)` |
| Single client | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias=...)` |

Skip this if you already bound in the import payload. Ask which the user wants — realm-wide
affects every client including the admin and account consoles. Verify with
`getAuthenticationBindings`, passing the `clientId` when the binding was client-level (a
client override does not change the realm's `browserFlow`, so the realm-level values alone will
still show the untouched default).

## Stage 7 — Behaviors worth knowing before you're asked

Verified empirically against a live deployment, not just from source:

- **Anti-enumeration depends on Stage 2's identifier-step choice.** With
  `ext-auth-username-auth-note`, an unregistered address gets the identical code-form response —
  no email, no error, and "I never got a code" becomes indistinguishable from "that address has
  no account," by design.
- **New users need a name on file.** A user with no `firstName`/`lastName` can pick up a
  `VERIFY_PROFILE` required action, interrupting the flow right after a correct code with an
  unrelated profile screen. Not specific to email OTP, but easy to mistake for a flow bug while
  testing.
- **Refreshing does not resend.** The code lives in an auth-session note and the send is skipped
  whenever that note is set.
- **There is a built-in resend** (a `resend` form parameter clears the note and issues a fresh
  code); the bundled `otp-form.ftl` exposes it.
- **No independent expiry.** The code has no TTL of its own — it lives as long as the
  authentication session. Shorten the realm's login timeouts for a tighter window.
- **Success marks the email verified** (`emailVerified=true`), since possession was just proven.
  Useful, but it does mutate the user.

## Stage 8 — Verify by logging in, not by reading configuration

1. A **registered** address: identifier form → code form → the emailed 6-digit code completes
   login with an authorization code and the original `state`.
2. A **wrong** code: rejected with an invalid-code message (and counted toward brute force).
3. An **unregistered** address: the code form still appears (given `ext-auth-username-auth-note`
   as the identifier step), but confirm **no mail was sent** and **no user was created**.

## Common errors

- **Code form appears, no email ever arrives** — realm SMTP unconfigured or wrong (Stage 4); the
  failure is swallowed.
- **Unregistered address gets "Invalid username or email" instead of the code form** — the
  identifier step is stock `auth-username-form`; swap it for `ext-auth-username-auth-note`.
- **Nothing to send to** — the identifier step is missing or ordered after `ext-email-otp`
  (Stage 2).
- **Unexpected new accounts** — `ext-magic-create-nonexistent-user` was set to `"true"`.
- **A fresh test user hits an unrelated profile-completion screen right after the correct code** —
  `VERIFY_PROFILE` required action from a missing name on the user, not a flow bug.
- **Codes guessable indefinitely** — brute-force protection still off (Stage 5).
- **`ext-email-otp` unavailable** — the `keycloak-magic-link` extension isn't installed; report it
  rather than substituting Keycloak's TOTP.
- **A required MCP tool is missing** — report it and stop; do not switch to REST unsolicited.
