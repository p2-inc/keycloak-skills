---
name: emailOtpLoginRest
description: >-
  Turn on passwordless login by a one-time code emailed to the user, on a self-managed
  Keycloak running the p2-inc keycloak-magic-link extension, using the Admin REST API only
  (no MCP server). Use this for "email OTP", "email a one-time code", "6-digit login code
  by email", or "passwordless login with a code instead of a link". Covers authoring the
  flow (none ships auto-created), the load-bearing identifier-step choice that decides
  whether the realm leaks which addresses have accounts, realm SMTP, and why brute-force
  protection matters for a 6-digit code. Not Keycloak's TOTP/HOTP authenticator apps, and
  not magic link (a clicked link rather than a typed code).
---

# emailOtpLoginRest

## What this is, and what it isn't

The user types an identifier, receives a **6-digit numeric code by email**, and types that code in
to finish logging in. No password, ever. This is the sibling mechanism that
`admin-passwordless-magic-link.md` explicitly says it does *not* cover ("a one-time code typed in
— a sibling authenticator, not covered here"):

| | Magic link | Email OTP (this doc) |
|---|---|---|
| What arrives by email | A signed action-token **link** to click | A **6-digit code** to type |
| Authenticator | `ext-magic-form` | `ext-email-otp` |
| Built-in flow ships with the provider? | Yes (`magic link`, auto-created) | **No — a flow must be authored** |
| Works if the mail client rewrites links | Fragile | Unaffected (nothing to click) |

Both come from the same extension, and both need realm SMTP.

## Prerequisite: the keycloak-magic-link extension

`ext-email-otp` is provided by **[p2-inc `keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link)**
(the same jar that provides `ext-magic-form`), not by stock Keycloak. Phase Two's own Keycloak
distribution bundles it. Confirm it's present before anything else:

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>

curl -s "$BASE/admin/realms/$REALM/authentication/authenticator-providers" -H "$H" \
  | jq -r '.[] | select(.id=="ext-email-otp")'
```

Empty output means the extension isn't installed — say so and stop. There is no stock-Keycloak
equivalent (Keycloak's own OTP authenticators are TOTP/HOTP against a registered authenticator
app, a different mechanism requiring device enrollment).

## Author the flow — no built-in one exists

Unlike magic-link (where the provider auto-creates a `magic link` flow on every realm), **nothing
auto-creates an email-OTP flow**. Confirm none exists, then author one.

The shape, from [`../assets/email-otp-flow.partial-import.json`](../assets/email-otp-flow.partial-import.json):

| Sub-flow | Execution | Requirement | Why it's here, and why in this position |
|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | An existing SSO session still works. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | A federated path bypasses the forms sub-flow. |
| top-level | *forms sub-flow* | ALTERNATIVE | Taken when neither of the above applies. |
| forms | `ext-auth-username-auth-note` | REQUIRED | **Load-bearing, and the choice here matters.** `ext-email-otp` reads the *attempted username* off the auth session (`MagicLink.getAttemptedUsername`) rather than collecting an address itself, so an identifier step must run first. Use `ext-auth-username-auth-note` (p2-inc `keycloak-orgs`) here, **not** stock `auth-username-form` — see the anti-enumeration section below for why this choice is not cosmetic. |
| forms | `ext-email-otp` | REQUIRED | Generates the code, mails it, renders the code form, and verifies the input. |

**Do not put `ext-email-otp` first, and do not drop the identifier step** — that combination
produces a silent no-email outcome rather than an error.

Two authoring paths, and one that does not work:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow **and** binds it in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension |
| Manual sequence: create flow → create sub-flow → add each execution → set requirements → attach config → bind | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, `added: 0`, nothing created, no error. |

Offer the extension when it isn't installed (it 404s clearly). Strip `ifResourceExists` from the
asset before sending — the atomic payload rejects unknown fields — and read the created alias back
from the response, since the extension hash-prefixes it.

Manual path, if that's the choice:

```bash
FLOW='email-otp-flow'
SUB='Email OTP forms'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

# The sub-flow is created AS an execution of the parent.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$SUB\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\"}"

for p in auth-cookie identity-provider-redirector; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\"}"
done
for p in ext-auth-username-auth-note ext-email-otp; do   # order matters, see the table above
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$SUB" '$f|@uri')/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\"}"
done

# List executions of both flows to get ids, then PUT requirements:
#   top-level: all three ALTERNATIVE      forms: both REQUIRED
# Finally attach the config to the ext-email-otp execution (see next section).
```

## The identifier-step choice: this is where anti-enumeration is actually decided

**Verified empirically, not just from source** — this is the trap that's easy to get wrong even
having read the authenticator code correctly, because the leak comes from a *different*
authenticator entirely:

- Wiring the identifier step as stock **`auth-username-form`** makes an unregistered address
  return **"Invalid username or email."** on the spot, before `ext-email-otp` ever runs. That's a
  real enumeration leak — the response genuinely differs for a registered vs. unregistered
  address — and it happens regardless of `ext-email-otp`'s own force-create setting, because the
  rejection happens one step earlier.
- Wiring it as **`ext-auth-username-auth-note`** (the p2-inc `keycloak-orgs` authenticator used
  for exactly this purpose elsewhere in this router) sets the attempted username without
  validating existence, and control reaches `ext-email-otp`, whose own null-user handling *is*
  anti-enumeration-safe: with force-create off, an unmatched address renders the identical code
  form with no email sent and no error.

So "an unregistered address gets an identical response" is **not automatically true of email
OTP** — it depends entirely on which authenticator collects the identifier, and the answer for
the asset in this repo is `ext-auth-username-auth-note`. If you ever see this flow authored with
`auth-username-form` instead (including in fixtures that predate this correction), treat the
enumeration leak as real and swap the authenticator rather than assuming the "same as magic-link"
behavior applies.

## The one config option — and how it differs from magic-link

`ext-email-otp` has exactly **one** configurable property, and it is the *same key* magic-link
uses (a shared constant in the extension), which is why it looks out of place:

```json
{ "alias": "email-otp-config", "config": { "ext-magic-create-nonexistent-user": "false" } }
```

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/<ext-email-otp-exec-id>/config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"email-otp-config","config":{"ext-magic-create-nonexistent-user":"false"}}'
```

**The default differs from magic-link's, in the safe direction.** Verified in the extension's
source: `ext-magic-form` defaults this to `true` (which silently provisions an account for any
address typed — the trap `admin-passwordless-magic-link.md` warns about), whereas
`ext-email-otp` defaults it to **`false`**. So for email OTP you do *not* have to remember to
turn it off. Setting it explicitly, as the asset does, is documentation rather than a fix — but
do set it to `true` deliberately if self-registration-by-OTP is actually wanted (note that doing
so also reopens the enumeration question above, since a match will now always exist).

Nothing else is configurable. In particular the code itself is **not** tunable: it is always a
6-digit numeric string (`SecretGenerator.DIGITS`), with no length, alphabet, or separate TTL
setting.

## Realm mail settings — required, and it fails silently

Same dependency and same trap as magic-link: a realm ships with **no SMTP settings at all**, and
a failed send is swallowed internally. Read-modify-write the realm representation (a PUT that
omits fields resets them):

```json
{
  "smtpServer": {
    "host": "smtp.example.com", "port": "587", "from": "noreply@example.com",
    "auth": "true", "user": "...", "password": "...", "starttls": "true", "ssl": "false"
  }
}
```

Verify by checking what actually left, not by trusting a `204`.

## Bind it

```bash
# Realm-wide: set "browserFlow": "email-otp-flow" on the realm representation.
# Single client: set the client's authenticationFlowBindingOverrides.browser to the flow's ID
#               (an id, not an alias — resolve it from /authentication/flows first).
```

Ask which the user wants — realm-wide affects every client including the admin and account
consoles, which usually should keep their own login path.

## Behaviors worth knowing before you're asked about them

All verified empirically against a live deployment, not just from source:

- **Anti-enumeration depends on the identifier step — see the section above.** With
  `ext-auth-username-auth-note`, an unregistered address gets the identical code-form response,
  no email, no error. It also means "I never got a code" is indistinguishable from "that address
  has no account" — by design, once the right identifier step is used.
- **Refreshing the page does not resend.** The code lives in an auth-session note
  (`user-auth-note-otp-code`) and the send is skipped whenever that note is already set.
- **There is a built-in resend.** Posting a `resend` form parameter clears the note and issues a
  fresh code. The bundled `otp-form.ftl` exposes this.
- **No independent code expiry.** The code has no TTL of its own; it lives as long as the
  authentication session does. Shorten the realm's login timeouts if you need a tighter window.
- **Wrong codes feed brute-force protection.** A mismatch is reported as
  `LOGIN_ERROR`/`invalid_code` and raised as an `INVALID_CREDENTIALS` failure challenge, so the
  realm's brute-force settings actually govern guessing attempts. Realms ship with brute-force
  **off** — a 6-digit code with unlimited attempts is weak, so turn it on when using this flow.
- **Success marks the email verified.** Completing an email-OTP login sets `emailVerified=true`
  on the user, since possession of the address was just proven. Useful, but be aware it mutates
  the user.
- **New users need a name on file.** A user created without `firstName`/`lastName` can pick up a
  `VERIFY_PROFILE` required action, which interrupts the flow with an unrelated profile-completion
  screen right after a correct code. Not specific to email OTP, but easy to mistake for a flow bug
  when testing against a freshly created user.

## Verifying this actually works

Configuration alone proves nothing — drive a real login:

1. Start an authorization-code request against the bound client. The identifier form appears;
   submit a **registered** address. The code form (`otp-form.ftl`) appears, and an email arrives
   with a 6-digit code.
2. Submit the emailed code → the browser returns to the app's `redirect_uri` with an authorization
   code, `state` unchanged.
3. Submit a **wrong** code → rejected with an invalid-code message, and the attempt counts toward
   brute force if enabled.
4. Repeat step 1 with an **unregistered** address → the code form still appears (identical
   response, assuming `ext-auth-username-auth-note` is the identifier step), but confirm **no
   mail was sent** and **no user was created**.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Code form appears but no email ever arrives, for any address | Realm SMTP unconfigured or wrong — the send failure is swallowed |
| Unregistered address gets "Invalid username or email" instead of the code form | The identifier step is stock `auth-username-form`, which validates existence up front — swap it for `ext-auth-username-auth-note` |
| No email, and the flow seems to skip straight to the code form with nothing to send to | The identifier step is missing or ordered *after* `ext-email-otp`, so there is no attempted username to mail |
| A brand-new account appears for an address nobody registered | `ext-magic-create-nonexistent-user` was set to `"true"` |
| Codes accepted indefinitely on repeated guesses | Realm brute-force protection is off (the default) |
| `ext-email-otp` not offered when adding an execution | The `keycloak-magic-link` extension isn't installed on this Keycloak |
| A refresh doesn't produce a new code | Expected — use the form's resend control; the code is cached in an auth-session note |
| A fresh test user hits an unrelated profile-completion screen right after the correct code | `VERIFY_PROFILE` required action from a missing name on the user — not a flow bug |