---
name: passwordlessMagicLinkLogin
description: >-
  Turn on passwordless login by emailed link ("magic link") in Keycloak, using the
  real p2-inc keycloak-magic-link provider. Use this whenever someone wants
  "passwordless login", "log in with a magic link", "email people a login link instead
  of a password", or "let users sign in without a password" — even if they only say
  "passwordless". Covers the built-in "magic link" flow the provider auto-creates on
  every realm (no custom flow authoring needed, only binding it), the realm SMTP
  settings it depends on, the anti-enumeration behaviour that makes registered and
  unregistered addresses look identical from the login page, and the
  create-user-if-none-exists setting that silently provisions an account for anyone's
  email unless turned off. Not WebAuthn/passkey passwordless (a different mechanism —
  see bindingAuthenticationFlow's Passwordless-or-password), and not a one-time
  password sent as a code to type in (that is ext-email-otp, a sibling authenticator
  in the same provider, not covered here).
---

# Passwordless login by magic link

## What "magic link" actually is

The user clicks a link, does not enter a password, and is signed in. Mechanically:
Keycloak mints a signed, time-limited action token, embeds it in a URL, and emails
that URL. Opening the link authenticates the same way any other action-token flow
does (email verification, password reset) — it is not a bespoke security model, and
that is worth saying if anyone asks whether it is "as secure" as a password: it is
exactly as strong as email delivery and the token's own lifespan.

## Check the provider is actually installed, first

This capability comes from the **p2-inc `keycloak-magic-link` provider**
(`io.phasetwo.keycloak.magic.auth.magic.MagicLinkAuthenticatorFactory`, provider id
`ext-magic-form`), dropped into Keycloak's `providers/` directory. It is not part of
stock Keycloak. Confirm it before doing anything else:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" | jq -r '.[].alias'
```

If **`magic link`** is in that list, the provider is present — proceed below. If it is
not, no amount of realm configuration will produce it: the jar has to be installed
and Keycloak restarted first, and that is outside what an Admin REST session can do.
Say so plainly rather than trying to hand-build a flow around `ext-magic-form` when
the provider offering that authenticator does not exist on this server.

## The flow already exists — bind it, don't build it

The moment the provider is present, Keycloak **auto-creates a built-in `magic link`
flow on every realm**, including realms created after the provider was installed.
This is the detail that makes the task look harder than it is: there is no custom
flow to author, only a binding to make.

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"

# Bind realm-wide...
curl -s "$BASE/admin/realms/$REALM" -H "$H" > /tmp/realm.json
# set "browserFlow": "magic link" in /tmp/realm.json, then PUT it back
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/realm.json

# ...or to one client only, via authenticationFlowBindingOverrides on the client,
# if only one application should go passwordless rather than the whole realm.
```

Only bind it where it belongs. Binding realm-wide switches every application's
password login off in favour of email; a client-level override is the right choice
when just one app should go passwordless while everything else keeps password login.

## Realm mail settings — required, and it fails silently without them

The authenticator sends through Keycloak's own configured mail sender. A realm ships
with **no SMTP settings at all**, and the send call catches its own failure
internally — nothing surfaces to the caller. The login page still shows its normal
"check your email" response either way, so a missing SMTP configuration looks
identical to a working one until you check whether mail actually left.

```json
{
  "smtpServer": {
    "host": "smtp.example.com",
    "port": "587",
    "from": "noreply@example.com",
    "auth": "true",
    "user": "...",
    "password": "...",
    "starttls": "true",
    "ssl": "false"
  }
}
```

PUT the whole realm representation with this set — a realm PUT that omits fields
resets them, so read first.

**Verify by checking what actually left**, not by trusting a `204`. If you have no
real mail provider to point at (a test/sandbox setting), a minimal SMTP-protocol
capture server is enough — Keycloak does not care that nothing downstream is a real
mailbox, only that something answers on the configured host and port.

## The trap: anyone's email creates an account, by default

`ext-magic-form`'s own config carries a "create user if none exists" setting
(`ext-magic-create-nonexistent-user`), and **it defaults to `true`.** Left alone,
typing any email address on the login page — one belonging to nobody — silently
provisions a brand-new account and emails *that* address a working login link. There
is no error, no warning, and no visible difference in what the page shows.

```bash
# Read the flow's executions to find the ext-magic-form execution's id:
curl -s "$BASE/admin/realms/$REALM/authentication/flows/magic%20link/executions" -H "$H" \
  | jq '.[] | select(.providerId=="ext-magic-form") | {id, authenticationConfig}'

# Attach (POST) or update (PUT to /authentication/config/{id}) its config:
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/$EXEC_ID/config" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "magic-link-existing-accounts-only",
    "config": {"ext-magic-create-nonexistent-user": "false"}
  }'
```

Turn this off whenever the request implies "our existing staff/customers", not "let
anyone create an account by typing an email" — which is almost always the intent
behind "passwordless login for our users."

Other config on the same execution, all optional: `ext-magic-update-profile-action`
/ `ext-magic-update-password-action` (required actions to add on a newly created
user — only relevant if create-on-demand is intentionally left on),
`ext-magic-allow-token-reuse` (whether the link can be clicked more than once before
it expires; defaults to reusable), `ext-magic-token-life-span` (seconds, defaults to
86400 = 1 day).

## Why registered and unregistered addresses look the same — on purpose

The authenticator deliberately shows the identical "check your email" response
whichever case applies, to avoid letting a login page be used to enumerate which
addresses are registered. This means the *page response* can never be the check for
whether create-on-demand is off — it looks correct either way. The only way to tell
is checking what happened on the *other* side: was mail sent, and did a user get
created, for an address that should have neither.

## Verifying the whole thing works

Drive an actual login rather than trusting configuration alone — nothing here has a
status endpoint that says "passwordless is working."

1. Submit a known address on the client's login page. Expect no password field.
2. Confirm mail actually arrived (real inbox, or your capture point) containing a
   link with `login-actions/action-token` in it.
3. Open that link with nothing else entered. Expect the browser to land back at the
   application's redirect URI with an authorization code.
4. Submit an address belonging to no account. Expect the *same* page response as
   step 1 — and confirm, out of band, that no mail went out and no user was created.

Two client-side details, if scripting this rather than clicking through it:

- Keycloak's auth cookies are `Secure; SameSite=None`. A browser sends them over
  `http://localhost` anyway (loopback is a secure context); most HTTP client
  libraries will not, and every form POST then fails as `cookie_not_found`. Clear the
  flag on each response.
- The action-token URL is exactly what a normal login-flow redirect produces — follow
  it the same way you would any other redirect chain, including through
  `required-action` hops, until it reaches the application's `redirect_uri`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| No "magic link" flow on the realm at all | The provider jar isn't installed on this server |
| "Check your email" shown, but no mail arrives, for anyone | Realm SMTP settings are unconfigured or wrong |
| An unregistered address gets a working login link | `ext-magic-create-nonexistent-user` left at its default `true` |
| Login page behaves differently for known vs. unknown addresses | Something downstream (a custom flow, a proxy) broke the built-in anti-enumeration behaviour — this is not stock; investigate what changed it |
| Link works but only once | `ext-magic-allow-token-reuse` is false — expected if that's the intent, otherwise flip it |
| Existing password login broke everywhere | The flow was bound realm-wide when only one client should have gone passwordless |
