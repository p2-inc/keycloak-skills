# Zero-password login — passkey *or* magic link — via the Keycloak MCP server

## What this is

One browser flow offering **two passwordless methods side by side**, with no password
authenticator anywhere in it: a **passkey** (WebAuthn passwordless) for users who have one, and a
**magic link** for everyone else. Marketed as a "0 password required login flow" — that's the
brand name for this intent, not a separate feature.

This is not `admin:passwordless-passkey` and `admin:passwordless-magic-link` bolted together.
Combining them fixes the one problem neither solves alone:

> **The passkey bootstrap problem.** A brand-new user has zero credentials, so they cannot log in
> to register a passkey — there is nothing to log in *with*. Passkey-only deployments solve this
> by emailing every user a `webauthn-register-passwordless` link out of band. Here, **magic link
> *is* the bootstrap path**: a new user logs in with an emailed link, registers a passkey, and
> uses the passkey from then on. No per-user admin provisioning, and no password ever exists.

Say the trade-off out loud to whoever asked: the flow is only as strong as its **weakest** method.
A phishing-resistant passkey doesn't make the account phishing-resistant while a magic link to the
same inbox is still accepted. That's the deliberate cost of zero passwords plus self-service
onboarding. If the ask is genuinely "passkeys and nothing else", that's `admin:passwordless-passkey`.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm the magic-link extension is present | `listAuthenticationFlows` |
| Author the flow (and optionally bind it) | `importAuthenticationFlow` |
| Read back execution order | `listFlowExecutions` |
| Turn off create-on-demand | `setExecutionAuthenticatorConfig` |
| Passkey policy | `getWebAuthnPasswordlessPolicy` / `setWebAuthnPasswordlessPolicy` |
| Outgoing mail | `setSmtpSettings` (`getRealmSettings` to read back) |
| Bind the flow | `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` |
| Confirm bindings | `getAuthenticationBindings` |
| Optional: pre-seed a passkey | `findUser` → `sendRequiredActionEmail` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

> **Drive this through the MCP tools.** If a required tool is unavailable in this deployment, say
> so and stop. Do **not** silently substitute Admin REST calls — an unreported switch hides that
> the tooling is incomplete and leaves the user unable to reproduce what you did. Only fall back
> to `admin-zero-password-login.md`'s REST steps if the user confirms this is not a Phase Two realm.

## Step 1 — Confirm the magic-link extension is installed

WebAuthn is stock Keycloak. `ext-magic-form` is **not** — it comes from the p2-inc
[`keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link) provider jar. The provider
auto-creates a built-in `magic link` flow the moment it's installed, so `listAuthenticationFlows`
is the cheapest proof it's present.

No `magic link` flow means no jar: say so plainly and stop, rather than authoring a flow that
references an authenticator this server doesn't have. And do **not** offer the auto-created
`magic link` flow as the answer — it's magic link *only*, with no passkey path.

## Step 2 — Author the flow

`importAuthenticationFlow` takes the asset
[`../assets/zero-password-login.partial-import.json`](../assets/zero-password-login.partial-import.json)
and authors both flows in one call, applying `browserFlowBinding` / `clientFlowBinding` at the
same time. The shape it creates:

| Flow | Execution | Requirement | Priority |
|---|---|---|---|
| `Passwordless-or-magic-link` (top level) | `auth-cookie` | ALTERNATIVE | 0 |
| | `auth-spnego` | DISABLED | 1 |
| | `identity-provider-redirector` | ALTERNATIVE | 2 |
| | *forms sub-flow* | ALTERNATIVE | 3 |
| *forms sub-flow* | `ext-magic-form` | ALTERNATIVE | 2 |
| | `webauthn-authenticator-passwordless` | ALTERNATIVE | 3 |

**No password authenticator appears in either flow.** That absence is the point — confirm it with
`listFlowExecutions` rather than assuming, because a flow derived from the stock `browser` flow
inherits `auth-username-password-form` and quietly stops being passwordless.

**Two ALTERNATIVEs in the forms sub-flow is what offers a choice.** Keycloak renders the
lowest-priority one it can execute and exposes the other through the login page's **"Try another
way"** control. `ext-magic-form` is deliberately first: it works for *any* user, including one
with no credentials, so the default screen is never a dead end. Put the passkey first and a user
without one lands on a ceremony they can't complete.

Two mechanical notes:

- Despite the `.partial-import.json` filename, Keycloak's `partialImport` endpoint is exactly the
  one that **cannot** consume this — it has no authentication-flow handler and silently ignores
  them (HTTP 200, nothing created). `importAuthenticationFlow` targets the p2-inc atomic-flows
  endpoint instead. The tool strips `ifResourceExists` for you.
- The atomic endpoint **hash-prefixes the alias it creates**. Read the real alias back from the
  response and use that when binding — don't assume the asset's literal name.

### If the atomic-flows extension isn't installed

`importAuthenticationFlow` needs the [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension and 404s without it. Offer installing it first — one jar, one call instead of many. If
declined, the fallback **stays inside MCP — no raw REST, no credentials from the user**:

1. `createAuthenticationFlow(alias="Passwordless-or-magic-link")`
2. `addAuthenticationSubFlow(parentFlowAlias="Passwordless-or-magic-link", alias="Passwordless-or-magic-link forms", priority=3)`
3. `addAuthenticationExecution` four times on the top-level flow (`auth-cookie` priority 0,
   `auth-spnego` priority 1, `identity-provider-redirector` priority 2), and twice on the forms
   sub-flow (`ext-magic-form` priority 2, `webauthn-authenticator-passwordless` priority 3) —
   **matching the table above exactly**, and passing `priority` explicitly on every call, since
   both add-execution calls append when it's omitted.
4. `setExecutionRequirement` on each of the six — `ALTERNATIVE` for all but `auth-spnego`
   (`DISABLED`).
5. Bind with `bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow`.

`priority` in the body is honoured only from Keycloak 25 onward; on older versions add the
executions in this order anyway and repair with `raiseExecutionPriority`/`lowerExecutionPriority`.
Read the order back with `listFlowExecutions` before moving on — nothing errors on a wrong order.

### What the user actually sees (verified on Keycloak 26.0.7)

Driven end to end against a live realm, both halves completing real
authorization-code logins:

1. The first screen is the **magic-link form** — an address field and a Sign In
   button. No password field.
2. The passkey is **not on that screen.** It sits behind Keycloak's **"Try
   another way"** control, which is *not* a button: it's
   `<a id="try-another-way">` submitting a `#kc-select-try-another-way-form`
   whose only field is a hidden `tryAnotherWay` input. Matching
   `input[name=tryAnotherWay]` finds the hidden input and hangs forever.
3. That leads to a **credential-selection page** listing every alternative in
   the flow. Each entry is a
   `<div class="select-auth-box-parent" onclick="...requestSubmit()">` wrapping
   an `<h2>` label — again no button or anchor, so button/link selectors find
   nothing. The passkey entry is labelled **"Passkey"** ("Use your Passkey for
   passwordless sign in.").
4. Choosing it renders the WebAuthn control (`#authenticateWebAuthnButton`) and
   the ceremony completes.

**The wart to warn people about:** that selection page lists `auth-cookie` and
`identity-provider-redirector` as choices too, and they render as raw
**untranslated i18n keys** — literally `auth-cookie-display-name` and
`identity-provider-redirector-display-name`. Real users see those two strings
next to "Magic link" and "Passkey". Nothing is broken, but it looks broken. Fix
it by supplying those message keys in the realm's login theme, or by not leaving
both of those executions as bare ALTERNATIVEs at the top level. Check this
before declaring the flow done — it's the first thing anyone reviewing the login
page will point at.

The sub-flow's inherited alias and description (`...passwordless-or-password forms`, *"Username,
password, otp and other auth forms."*) are misleading leftovers from a copied browser flow —
there's no password step. The parent references the sub-flow **by alias**, so don't rename one
without the other.

## Step 3 — The WebAuthn passwordless policy

`setWebAuthnPasswordlessPolicy` writes the **passwordless** policy block, which is separate from
the realm's ordinary second-factor WebAuthn policy. The two arguments that decide whether this
works at all:

- **`rpId`** — the realm's serving hostname, no scheme/port/path. It defaults to empty, which
  falls back to the request's hostname at ceremony time; fine with exactly one hostname, but if
  the realm is reachable at more than one, an empty or mismatched value fails **client-side** with
  no useful server-side error. Set it to the hostname the browser actually navigates to.
- **`requireResidentKey: "Yes"`** — what lets a discoverable credential present itself with
  nothing typed first. Required for the passkey half to work without a username step.

`userVerificationRequirement` of `"preferred"` or `"required"` is the usual choice (a PIN or
biometric on the authenticator itself, not just presence). Call
`getWebAuthnPasswordlessPolicy` afterwards to confirm the values landed.

## Step 4 — Outgoing mail, or the magic-link half is inert

`setSmtpSettings` is not optional here. With SMTP unset the send fails and **the login page still
shows "check your email"** (see anti-enumeration below), so nothing surfaces the
misconfiguration. It's also required if you ever use `sendRequiredActionEmail`.

## Step 5 — Turn off create-on-demand (almost always)

`ext-magic-form`'s `ext-magic-create-nonexistent-user` config **defaults to `true`**. Left alone,
typing any email address — one belonging to nobody — silently provisions a new account and mails
*that* address a working login link. In a zero-password flow this is the entire authentication
boundary, so it matters more here than in a password-backed realm: it turns the login page into
open self-registration.

Find the `ext-magic-form` execution with `listFlowExecutions`, then
`setExecutionAuthenticatorConfig` with `{"ext-magic-create-nonexistent-user": "false"}`.

Turn it off whenever the request means "our existing staff/customers" rather than "let anyone in
by typing an email" — nearly always what "passwordless login for our users" means.

Other config on the same execution, all optional: `ext-magic-allow-token-reuse` (defaults to
reusable), `ext-magic-token-life-span` (seconds, default 86400), and
`ext-magic-update-profile-action` / `ext-magic-update-password-action` — the last of which is
actively counterproductive here, since an `UPDATE_PASSWORD` required action reintroduces the
password this flow exists to remove.

**Anti-enumeration means the page can never confirm this worked.** `ext-magic-form` deliberately
shows the identical "check your email" response for known and unknown addresses. The only way to
check is on the other side: for an address that should have neither, was mail sent, and was a user
created?

## Step 6 — Bind, and confirm

`bindRealmAuthenticationFlow` (realm-wide) or `bindClientAuthenticationFlow` (one client), then
`getAuthenticationBindings` to confirm — don't infer a binding from a successful-looking call.

## Optional — hand a user their first passkey directly

Magic link already covers bootstrap, so this is only for pre-seeding a passkey without a first
magic-link login: `findUser` for the user's id, then `sendRequiredActionEmail` with
`['webauthn-register-passwordless']`, plus `clientId` and `redirectUri` so completion lands
somewhere useful. Needs a verified email and SMTP already configured. There's no way to
pre-provision the credential from the admin side — the key pair is generated client-side during
the ceremony.

## Verifying this actually works

No tool reports "zero-password login is working". Configuration can look perfect and still fail at
the ceremony (a wrong `rpId` is the classic). **Both** methods have to be driven, and one of them
can't be driven by an HTTP client at all:

| Method | How to verify | Tooling |
|---|---|---|
| Magic link | Request a login, submit an address, read the captured mail, follow the link, expect a redirect to `redirect_uri` with a code | Plain HTTP client |
| Passkey | Register via `webauthn-register-passwordless`, then log in through the `#authenticateWebAuthnButton` control | **Real browser required** |

A passkey ceremony is `navigator.credentials.create()` / `.get()` — actual client-side
JavaScript. Scripting it needs a headless browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `addVirtualAuthenticator`, e.g. Playwright); no HTTP client can fake the
crypto exchange. If no browser is available, report the passkey half as **unverified** rather than
inferring it from configuration.

Also confirm the choice is actually offered — the login page should present the magic-link form
*and* a "Try another way" control leading to the passkey option. A flow where only one method is
reachable is the most likely wrong outcome, and it looks entirely correct in the admin console.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Login page shows a password field | The flow derives from stock `browser` — `auth-username-password-form` still present |
| Only the magic-link form, no way to reach the passkey | The passkey execution is missing, DISABLED, or not ALTERNATIVE at the same level as `ext-magic-form` |
| Passkey prompt appears first and blocks users with no passkey | Priorities inverted — `ext-magic-form` must be the lower of the two |
| Binding a flow alias 404s or binds nothing | The atomic endpoint hash-prefixed the alias — read it back from the import response |
| "Check your email" but nothing arrives | SMTP unset or wrong — the page looks identical either way |
| Typing an unknown email creates an account | `ext-magic-create-nonexistent-user` left at its `true` default |
| Passkey ceremony fails in the browser with no server-side error | `rpId` empty or not matching the browsed hostname |
| Passkey ceremony never offers a discoverable credential | `requireResidentKey` not `"Yes"` |
| No `magic link` flow on the realm at all | The `keycloak-magic-link` jar isn't installed on this server |
| Users are asked to set a password after logging in | `ext-magic-update-password-action` configured, or an `UPDATE_PASSWORD` required action |
| A required MCP tool is missing | Report it and stop; do not switch to REST unsolicited |
