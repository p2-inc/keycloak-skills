# Passkey-only passwordless login — via the Keycloak MCP server

## What makes this different from magic-link

Both are "passwordless", but mechanically they're not close. Magic-link authenticates by
proving control of an email inbox (open the link, you're in) — Keycloak ships that flow
built-in, and the whole ceremony is a signed URL a plain HTTP client can follow. A passkey
authenticates by a real public-key cryptographic exchange between the browser and an
authenticator (a phone, a hardware key, a platform credential like Face ID) — Keycloak
ships **no** built-in flow for this, and completing a login or registration ceremony
requires actual client-side JavaScript talking to the WebAuthn API. Verifying this worked
needs a real browser, not a curl call.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| See what flows exist (confirm no passkey-only flow already present) | `listAuthenticationFlows` |
| Read the realm's current WebAuthn PASSWORDLESS policy | `getWebAuthnPasswordlessPolicy` |
| Set that policy (relying-party id, resident-key/attestation/user-verification requirements) | `setWebAuthnPasswordlessPolicy` |
| Configure outgoing mail — required for the credential-bootstrap email | `setSmtpSettings` |
| Find a user by username/email, and see if they already have a credential | `findUser` |
| Email a user a link to register a passkey, without a password | `sendRequiredActionEmail` |
| Bind the authored flow to one client | `bindClientAuthenticationFlow` |
| Bind the authored flow realm-wide | `bindRealmAuthenticationFlow` |
| Verify bindings after binding | `getAuthenticationBindings` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call below.
`setWebAuthnPasswordlessPolicy`, `findUser`, and `sendRequiredActionEmail` are newer
additions to the MCP server, added specifically to cover this flow — if any are missing
from the tool list, that gap is real; say so and fall back to
`admin-passwordless-passkey.md`'s REST instructions for whichever piece is missing.

## Stage 1 — Establish identity and target realm

1. Call `whoAmI`; tell the user who they are and which realm the token came from.
2. Confirm the target **deployment/realm** and the client that should go passkey-only.

## Stage 2 — Set the WebAuthn PASSWORDLESS policy

Call `getWebAuthnPasswordlessPolicy` first — note what's already set before changing it.
Then call `setWebAuthnPasswordlessPolicy`. The one field that actually breaks things if
wrong: **`rpId`**. It defaults to empty, which falls back to the request's own hostname
at ceremony time — fine if every client reaches this realm through exactly one hostname,
but if the realm is reachable at more than one, an empty or mismatched `rpId` produces a
ceremony that fails **client-side**, with no useful server-side error (just a generic
JS/browser exception). Set it explicitly to the hostname the browser will actually
navigate to.

For passkey-only (no username typed first, no password fallback), also set
`requireResidentKey="Yes"` — a resident/discoverable credential is what lets the
authenticator present itself without the user typing anything first.
`userVerificationRequirement="preferred"` or `"required"` is the usual choice (a PIN or
biometric check on the authenticator itself, not just presence).

## Stage 3 — Author the flow

Confirm with `listAuthenticationFlows` that no existing flow already does this (there is
no built-in one).

**If the [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows)
extension is installed**, `importAuthenticationFlow` authors the whole flow — and binds it —
in a single call; prefer that over the manual sequence below, and offer installing the
extension if it 404s. (Keycloak's own `partialImport` endpoint is *not* an alternative: it has
no handler for authentication flows and silently ignores them — HTTP 200, nothing created.)

Otherwise, the component path — **still entirely through MCP tools**, no raw REST and no
credentials needed from the user:

1. `addFlow(alias="Passkey Only")` — a bare top-level flow; leaf authenticators
   work fine on it directly, no sub-flow needed.
2. `addAuthenticator(flowAlias="Passkey Only", provider="auth-cookie", priority=0)`
3. `addAuthenticator(flowAlias="Passkey Only", provider="webauthn-authenticator-passwordless", priority=1)`

   **Pass `priority` explicitly on both** — the call appends when it's omitted, at
   `(last sibling's priority + 1)`, so call order alone decides the outcome. `priority` in the
   body is honoured only from Keycloak 25 onward; on older versions add them in this order anyway
   and repair with `raiseExecutionPriority`/`lowerExecutionPriority` if it lands wrong.
4. `listFlowExecutions(flowAlias="Passkey Only")` to get each execution's own id, then
   `setExecutionRequirement` twice:
   - `auth-cookie` → `ALTERNATIVE` (an existing SSO session still works)
   - `webauthn-authenticator-passwordless` → `REQUIRED` (the only path otherwise — this is what
     makes it "no password, ever," not just deprioritized)

Read the order back with `listFlowExecutions` before moving on — nothing errors on a wrong order.

**Do not add a Username Password Form, and do not add it to a copy of the stock
`browser` flow without stripping that step out first** — a copied `browser` flow keeps
Kerberos, the IdP redirector, and (critically) the password form as ALTERNATIVE steps,
which defeats "no password, ever." Building the flow from an empty shell with exactly
these two executions is simpler and avoids that trap entirely.

## Stage 4 — Bind it

Same two surfaces as `bindingAuthenticationFlow`'s Stage 3:

| Surface | When to use it | Tool |
|---|---|---|
| Single client | Only one application goes passkey-only | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias="Passkey Only")` |
| Realm-wide | Every client should go passkey-only | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias="Passkey Only")` |

Ask which the user actually wants — realm-wide affects every client, including admin
consoles, which usually should keep their own login path.

## Stage 5 — The bootstrap problem: getting a FIRST passkey with no password

This is the piece with no analog in a password-based world. A brand-new or
previously-password-only user has **zero credentials**. They cannot "just log in" to
register a passkey, because there's nothing to log in *with* yet — and unlike
magic-link's anti-enumeration design (identical response either way), there's no
equivalent bootstrap-free path for a cryptographic ceremony.

The mechanism: `sendRequiredActionEmail(userId, actions=["webauthn-register-passwordless"], clientId, redirectUri)`.
This is an **action-token-authenticated** link — the same underlying mechanism magic-link
login itself uses — so it needs no password and no pre-existing credential. Requires:
- The realm's SMTP settings already configured (`setSmtpSettings`) — same dependency and
  same silent-failure trap as magic-link: unconfigured mail looks identical to configured
  mail until you check what actually left.
- The user has a verified email address.
- Look up the user's id first with `findUser` if only given a username/email.

Do this for every user who needs a first passkey. There is no way to pre-provision a
credential from the admin side alone — the actual key pair is generated client-side
during the ceremony.

## Stage 6 — Verifying this actually works

Nothing here has a status endpoint that says "passkeys are working" — configuration can
look perfect and still fail at the ceremony itself (a wrong `rpId` is the classic way).
Verify by actually driving both ceremonies:

1. **Registration**: open the required-action email's link. It leads through a "Perform
   the following action(s)" interstitial (click through), landing on a page with a
   `#registerWebAuthn` button/input that triggers `navigator.credentials.create()` via
   the page's own JS. Completing it shows "Your account has been updated."
2. **Login**: a fresh authorization-code request to the bound client's realm shows a
   "Passkey login" page with an `#authenticateWebAuthnButton` control triggering
   `navigator.credentials.get()`. Completing it redirects to the app's `redirect_uri`
   with an authorization code and the original `state` unchanged.
3. **No password, ever**: check the actual page content at both steps 1 and 2 — and
   also for a login attempt with NO registered credential at all — never contains a
   password input. This is the structural guarantee the flow's REQUIRED-only WebAuthn
   step provides; confirm it behaviorally too.

A real user has no way to script `navigator.credentials.create/get()` — verifying this
programmatically needs a real browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `WebAuthn.addVirtualAuthenticator` with
`hasResidentKey/hasUserVerification/isUserVerified: true`, `automaticPresenceSimulation:
true`), the standard technique for testing WebAuthn flows headlessly — there is no way to
fake this exchange with a plain HTTP client.

## Common errors

- **Ceremony fails immediately in the browser, generic error, nothing useful server-side**
  — almost always `rpId` mismatched to the actual serving hostname. Re-check Stage 2.
- **`sendRequiredActionEmail` succeeds (`success:true`) but nothing arrives** — that only
  confirms Keycloak queued the send; check the realm's actual mail settings and the
  capture point / provider, the same trap as magic-link.
- **Login page still shows a password field** — the bound flow still has a Username
  Password Form execution somewhere (often from copying `browser` instead of building
  fresh) — re-check Stage 3's flow contents, don't assume ALTERNATIVE-vs-REQUIRED is
  enough if the step exists at all.
- **No `#registerWebAuthn` / `#authenticateWebAuthnButton` control on the page** — the
  required action isn't wired up, or the flow isn't actually bound to the client being
  tested; re-check Stage 4's binding with `getAuthenticationBindings`.
