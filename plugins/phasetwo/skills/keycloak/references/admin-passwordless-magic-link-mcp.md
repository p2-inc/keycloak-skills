# Passwordless login by magic link — via the Keycloak MCP server

## What "magic link" actually is

The user clicks a link, does not enter a password, and is signed in. Mechanically:
Keycloak mints a signed, time-limited action token, embeds it in a URL, and emails
that URL. Opening the link authenticates the same way any other action-token flow
does (email verification, password reset) — it is not a bespoke security model, and
that is worth saying if anyone asks whether it is "as secure" as a password: it is
exactly as strong as email delivery and the token's own lifespan.

## Tools this skill drives (Keycloak MCP server)

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| Confirm the provider is installed (the `magic link` flow exists) | `listAuthenticationFlows` |
| Check current realm settings, including whether SMTP is already configured | `getRealmSettings` |
| Configure outgoing mail — required, and fails silently without it | `setSmtpSettings` |
| List a flow's steps, and read each step's current config | `listFlowExecutions` |
| Set (or create) an authenticator step's config — this is how the anti-enumeration trap gets closed | `setExecutionAuthenticatorConfig` |
| Bind the flow realm-wide | `bindRealmAuthenticationFlow` |
| Bind the flow to one client only | `bindClientAuthenticationFlow` |
| Verify realm-level bindings after binding | `getAuthenticationBindings` |

Capture **`deploymentId`** and **`deploymentRealm`** (from `createClusterDeployment`) and reuse them on
every call below. `setSmtpSettings`, `listFlowExecutions`, and `setExecutionAuthenticatorConfig` are
newer additions to the MCP server specifically to make this flow driveable end-to-end without dropping
to raw REST — if any of the three are missing from the tool list, that gap is real (not a skill error);
say so and fall back to admin-passwordless-magic-link.md's REST instructions for whichever piece is missing.

## Stage 1 — Establish identity and target realm

1. Call `whoAmI`; tell the user who they are and which realm the token came from.
2. Confirm the target **deployment/realm**: ask for its `deploymentId` and `deploymentRealm` (name).

## Stage 2 — Confirm the provider is actually installed

Call `listAuthenticationFlows`. If **`magic link`** is in the result, the p2-inc
`keycloak-magic-link` provider (`io.phasetwo.keycloak.magic.auth.magic.MagicLinkAuthenticatorFactory`,
provider id `ext-magic-form`) is present and Keycloak auto-created this built-in flow — proceed below.

If it is **not** in the list, no amount of realm configuration will produce it: the jar has to be
installed on the Keycloak server and it has to restart, and that is outside anything an MCP tool call
can do. Say so plainly rather than trying to hand-build a flow around `ext-magic-form` when the provider
offering that authenticator does not exist on this deployment.

## Stage 3 — The flow already exists — bind it, don't build it

There is no custom flow to author here, only a binding to make — but **do the SMTP and anti-enumeration
configuration (Stages 4–5) before binding**, so the flow is never live with unconfigured mail or the
create-on-demand trap still open.

Two binding surfaces, same choice as `bindingAuthenticationFlow`'s Stage 3:

| Surface | When to use it | Tool |
|---|---|---|
| Realm-wide | Every client should go passwordless | `bindRealmAuthenticationFlow(bindingType="browser", flowAlias="magic link")` |
| Single client | Only one application goes passwordless; everything else keeps password login | `bindClientAuthenticationFlow(clientId=..., bindingType="browser", flowAlias="magic link")` |

Ask which the user actually wants before calling either — binding realm-wide switches off password
login for every client in the realm.

## Stage 4 — Realm mail settings — required, and it fails silently without them

The authenticator sends through Keycloak's own configured mail sender. A realm ships with **no SMTP
settings at all**, and the send call catches its own failure internally — nothing surfaces to the
caller. The login page still shows its normal "check your email" response either way, so a missing SMTP
configuration looks identical to a working one until you check whether mail actually left.

1. Call `getRealmSettings` first — check `smtpConfigured`. If `true`, tell the user what's already set
   (host/port/from/auth/starttls/ssl are all echoed back; the password never is) before changing
   anything, rather than silently overwriting a working config.
2. Call `setSmtpSettings(host, port, from, ...)`. `host`, `port`, and `from` are required; everything
   else (`fromDisplayName`, `authEnabled`, `username`, `password`, `starttls`, `ssl`) is optional and
   merged into whatever's already set.
3. **Verify by checking what actually left**, not by trusting `success:true` — that only confirms the
   realm accepted the representation, not that mail delivery works. If there's no real mail provider to
   point at (a test/sandbox setting), a minimal SMTP-protocol capture server on the given host/port is
   enough — Keycloak does not care that nothing downstream is a real mailbox, only that something
   answers on the configured host and port.

## Stage 5 — The trap: anyone's email creates an account, by default

`ext-magic-form`'s own config carries a "create user if none exists" setting
(`ext-magic-create-nonexistent-user`), and **it defaults to `true`.** Left alone, typing any email
address on the login page — one belonging to nobody — silently provisions a brand-new account and
emails *that* address a working login link. There is no error, no warning, and no visible difference in
what the page shows.

1. Call `listFlowExecutions(flowAlias="magic link")`. Find the entry whose
   `authenticatorProviderId` is `ext-magic-form` — note its current `config` (empty if never set).
2. Call `setExecutionAuthenticatorConfig(flowAlias="magic link", authenticatorProviderId="ext-magic-form", config={"ext-magic-create-nonexistent-user": "false"})`.
   This one call handles both cases (creating a new config if the execution has none yet, or merging into
   an existing one) — no need to branch on whether a config already exists.
3. Re-run `listFlowExecutions` to confirm the `config` field now shows `ext-magic-create-nonexistent-user: "false"`.

Turn this off whenever the request implies "our existing staff/customers", not "let anyone create an
account by typing an email" — which is almost always the intent behind "passwordless login for our
users."

Other config keys on the same execution, all optional, set the same way (merge additional key/value
pairs into the same `config` map): `ext-magic-update-profile-action` / `ext-magic-update-password-action`
(required actions to add on a newly created user — only relevant if create-on-demand is intentionally
left on), `ext-magic-allow-token-reuse` (whether the link can be clicked more than once before it
expires; defaults to reusable), `ext-magic-token-life-span` (seconds, defaults to 86400 = 1 day).

## Stage 6 — Why registered and unregistered addresses look the same — on purpose

The authenticator deliberately shows the identical "check your email" response whichever case applies,
to avoid letting a login page be used to enumerate which addresses are registered. This means the *page
response* can never be the check for whether create-on-demand is off — it looks correct either way. The
only way to tell is checking what happened on the *other* side: was mail sent, and did a user get
created, for an address that should have neither. No MCP tool inspects mail delivery or user-creation
side effects directly — that has to be checked out of band (the realm's mail capture point / provider,
and a user list before/after).

## Stage 7 — Bind, then verify

1. Now bind the flow (Stage 3's tool call), having already closed the SMTP and anti-enumeration gaps.
2. Call `getAuthenticationBindings` to confirm the realm-level (or `bindClientAuthenticationFlow`'s
   client-level) binding took effect.
3. Drive an actual login rather than trusting configuration alone — nothing here has a status endpoint
   that says "passwordless is working":
   - Submit a known address on the client's login page. Expect no password field.
   - Confirm mail actually arrived (real inbox, or the capture point) containing a link with
     `login-actions/action-token` in it.
   - Open that link with nothing else entered. Expect the browser to land back at the application's
     redirect URI with an authorization code.
   - Submit an address belonging to no account. Expect the *same* page response as the first login —
     and confirm, out of band, that no mail went out and no user was created.

Two client-side details, if scripting this rather than clicking through it:

- Keycloak's auth cookies are `Secure; SameSite=None`. A browser sends them over `http://localhost`
  anyway (loopback is a secure context); most HTTP client libraries will not, and every form POST then
  fails as `cookie_not_found`. Clear the flag on each response.
- The action-token URL is exactly what a normal login-flow redirect produces — follow it the same way
  you would any other redirect chain, including through `required-action` hops, until it reaches the
  application's `redirect_uri`.

## Common errors

- **`listAuthenticationFlows` doesn't include `magic link`** — the provider jar isn't installed on this
  server; no MCP call fixes that.
- **`bindRealmAuthenticationFlow` / `bindClientAuthenticationFlow` fails "No top-level flow named..."**
  — shouldn't happen for `magic link` if Stage 2 confirmed it exists; re-run `listAuthenticationFlows` to
  check for a typo in the alias.
- **`setExecutionAuthenticatorConfig` fails "No execution with authenticator providerId..."** — the
  `flowAlias` given doesn't contain an `ext-magic-form` step; re-run `listFlowExecutions` on the actual
  flow alias in use (it should be `"magic link"` unless the realm renamed or cloned it).
- **"Check your email" shown, but no mail arrives, for anyone** — realm SMTP settings are unconfigured
  or wrong; re-check with `getRealmSettings`'s `smtpConfigured`/`smtpHost`/`smtpPort` fields.
- **An unregistered address gets a working login link** — `ext-magic-create-nonexistent-user` left at
  its default `true`; re-run Stage 5.
- **Existing password login broke everywhere** — the flow was bound realm-wide when only one client
  should have gone passwordless; use `bindClientAuthenticationFlow` instead, scoped to that one `clientId`.
