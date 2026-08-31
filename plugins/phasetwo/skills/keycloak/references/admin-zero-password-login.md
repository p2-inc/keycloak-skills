# Zero-password login — passkey *or* magic link — via raw Admin REST

## What this is

One browser flow offering **two passwordless methods side by side**, with no password
authenticator anywhere in it: a **passkey** (WebAuthn passwordless) for users who have one, and a
**magic link** for everyone else. Marketed as a "0 password required login flow" — take that
phrasing as the brand name for this intent, not as a separate feature.

This is not simply `admin:passwordless-passkey` and `admin:passwordless-magic-link` bolted
together. Combining them fixes the one problem neither solves alone:

> **The passkey bootstrap problem.** A brand-new user has zero credentials, so they cannot log in
> to register a passkey — there is nothing to log in *with*. Passkey-only deployments solve this
> by emailing every user a `webauthn-register-passwordless` required-action link out of band.
> Here, **magic link *is* the bootstrap path**: a new user logs in with an emailed link, then
> registers a passkey from their account, and uses the passkey from then on. No admin-side
> per-user provisioning step, and no password ever exists.

Consequence worth stating to whoever asked: this flow is only as strong as its **weakest**
method. A phishing-resistant passkey does not make the account phishing-resistant while a magic
link to the same inbox is still accepted. That is the deliberate trade for zero passwords and
self-service onboarding — say so rather than letting "we use passkeys" imply more than it does.
If the ask is genuinely "passkeys and nothing else", that's `admin:passwordless-passkey`.

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
# Self-managed Keycloak: mint $ADMIN_TOKEN from the built-in admin-cli client in `master`
# (skip if you already have a token). Does NOT apply to Phase Two hosted deployments — there
# is no self-service admin REST credential of any kind there (confirmed with Phase Two).
# Without MCP, use the dashboard instead; raw REST is a dead end here, not a fallback.
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
FLOW='Passwordless-or-magic-link'
SUB='Passwordless-or-magic-link passwordless-or-password forms'
```

## Prerequisite: the keycloak-magic-link extension

WebAuthn is stock Keycloak. `ext-magic-form` is **not** — it comes from the p2-inc
[`keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link) provider jar. Check before
authoring anything, because the flow is useless with one of its two halves missing:

```bash
# The provider auto-creates a built-in "magic link" flow the moment it is installed.
# Seeing it in this list is the cheapest proof the jar is present.
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" | jq -r '.[].alias'
```

If there's no `magic link` flow, the jar isn't installed — say so plainly and stop rather than
authoring a flow that references an authenticator this server doesn't have. Do **not** bind the
auto-created `magic link` flow as the answer to this request: it offers magic link *only*, with
no passkey path.

## The flow shape, and why this order

From [`../assets/zero-password-login.partial-import.json`](../assets/zero-password-login.partial-import.json):

| Flow | Execution | Requirement | Priority |
|---|---|---|---|
| `Passwordless-or-magic-link` (top level) | `auth-cookie` | ALTERNATIVE | 0 |
| | `auth-spnego` | DISABLED | 1 |
| | `identity-provider-redirector` | ALTERNATIVE | 2 |
| | *forms sub-flow* | ALTERNATIVE | 3 |
| *forms sub-flow* | `ext-magic-form` | ALTERNATIVE | 2 |
| | `webauthn-authenticator-passwordless` | ALTERNATIVE | 3 |

**There is no password authenticator in either flow.** That absence is the whole point — verify
it explicitly after authoring, because a flow built by copying the stock `browser` flow inherits
`auth-username-password-form` and quietly stops being passwordless:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -e 'any(.[]; .providerId | test("password")) | not' \
  && echo "OK: no password authenticator in this flow"
```

**Two ALTERNATIVEs in the forms sub-flow is what offers a choice.** Keycloak renders the
lowest-priority one it can execute and exposes the other through the login page's **"Try another
way"** control. `ext-magic-form` is deliberately first: it works for *any* user, including one
with no credentials at all, so the default screen is never a dead end. Put
`webauthn-authenticator-passwordless` first instead and a user with no passkey lands on a
ceremony they cannot complete and has to discover "Try another way" to get anywhere.

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

The sub-flow's alias and description (`...passwordless-or-password forms`, *"Username, password,
otp and other auth forms."*) are inherited leftovers from a copied browser flow. They are
misleading — there is no password step — but the parent references the sub-flow **by alias**, so
don't rename one without the other.

## Authoring the flow

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors **and** binds in one call | **One call** | The p2-inc `keycloak-atomic-auth-flows`<!-- relink https://github.com/p2-inc/keycloak-atomic-auth-flows when public --> extension |
| Manual sequence: create flow → create sub-flow → add each execution → set requirements → attach config → bind | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** No handler for authentication flows: HTTP 200, `added: 0`, nothing created, no error. The admin console's "Partial import" and `kcadm.sh create partialImport` fail the same way. |

Despite the asset's `.partial-import.json` filename, `partialImport` is exactly the endpoint that
cannot consume it. **Strip `ifResourceExists` before sending it to the atomic endpoint** — that
payload rejects unknown fields with a 400 — and read the created alias back from the response,
since the extension hash-prefixes it.

```bash
jq 'del(.ifResourceExists)' ../assets/zero-password-login.partial-import.json > /tmp/flow.json
curl -s -X POST "$BASE/admin/realms/$REALM/authentication-flow/import?force=false" \
  -H "$H" -H 'Content-Type: application/json' --data-binary @/tmp/flow.json
```

### If taking the manual path, order is load-bearing

`executions/execution` and `executions/flow` **append**: with no `priority` in the body the server
assigns `last sibling + 1`, so order is just the order the calls were made in. Creating the
sub-flow before the top-level leaves puts the sub-flow at priority 0 — ahead of `auth-cookie` —
and users holding a live session get re-prompted. Send `priority` explicitly:

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$SUB" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"ext-magic-form","priority":2}'
```

`priority` in the body is honoured only from **Keycloak 25** onward (added 2024-05-29); on 24 and
older it is ignored and calls append regardless. There, add executions in the intended order and
repair with `POST .../authentication/executions/<exec-id>/raise-priority`, which swaps an
execution with one adjacent sibling per call. Then read the order back and check it:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

## The realm's WebAuthn PASSWORDLESS policy

A **separate policy block** from the realm's ordinary second-factor WebAuthn policy — don't
confuse the two field prefixes. Read the realm representation first (a realm PUT that omits
fields resets them), set the passwordless-prefixed fields, then PUT the whole thing back:

```json
{
  "webAuthnPolicyPasswordlessRpEntityName": "Acme Portal",
  "webAuthnPolicyPasswordlessRpId": "localhost",
  "webAuthnPolicyPasswordlessRequireResidentKey": "Yes",
  "webAuthnPolicyPasswordlessUserVerificationRequirement": "preferred"
}
```

**`webAuthnPolicyPasswordlessRpId` is the field that breaks things if wrong.** It defaults to
empty, falling back to the request's hostname at ceremony time — fine with exactly one hostname,
but if the realm is reachable at more than one, an empty or mismatched `rpId` fails
**client-side** with no useful server-side error. Set it to the hostname the browser actually
navigates to.

`webAuthnPolicyPasswordlessRequireResidentKey: "Yes"` is what lets a discoverable credential
present itself with nothing typed first — required for the passkey half to work without a
username step.

## Realm mail settings — required, and they fail silently

The magic-link half sends email. With SMTP unset the send fails and **the login page still shows
"check your email"** (see anti-enumeration below), so nothing surfaces the misconfiguration:

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" > /tmp/realm.json
# set smtpServer {host, port, from, ssl/starttls, auth/user/password} and PUT the whole rep back
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/realm.json
```

SMTP is needed for the passkey half too, if you ever send a
`webauthn-register-passwordless` required-action email (below).

## The trap: anyone's email creates an account, by default

`ext-magic-form`'s `ext-magic-create-nonexistent-user` config **defaults to `true`**. Left alone,
typing any email address — one belonging to nobody — silently provisions a new account and mails
*that* address a working login link. In a zero-password flow this is the entire authentication
boundary, so it matters more here than in a password-backed realm: it turns the login page into
open self-registration.

```bash
EXEC_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$SUB" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | select(.providerId=="ext-magic-form") | .id')

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/$EXEC_ID/config" \
  -H "$H" -H 'Content-Type: application/json' -d '{
    "alias": "zero-password-existing-accounts-only",
    "config": {"ext-magic-create-nonexistent-user": "false"}
  }'
```

Turn it off whenever the request means "our existing staff/customers" rather than "let anyone in
by typing an email" — which is nearly always what "passwordless login for our users" means.

Other config on the same execution, all optional: `ext-magic-allow-token-reuse` (defaults to
reusable), `ext-magic-token-life-span` (seconds, default 86400), and
`ext-magic-update-profile-action` / `ext-magic-update-password-action` — the last of which is
actively counterproductive here, since adding an `UPDATE_PASSWORD` required action reintroduces
the password this flow exists to remove.

**Anti-enumeration means the page can never confirm this worked.** `ext-magic-form` deliberately
shows the identical "check your email" response for known and unknown addresses. The only way to
check is on the other side: for an address that should have neither, was mail sent, and was a
user created?

## Bind it

Realm-wide via the realm representation's `browserFlow` (read-modify-write — a PUT that omits
fields resets them), or per-client via the client's `authenticationFlowBindingOverrides`. The
atomic import path can apply `browserFlowBinding` / `clientFlowBinding` in the same call that
authors the flow.

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" | jq '.browserFlow'   # confirm it stuck
```

## Optional: hand a user their first passkey directly

Magic link already covers bootstrap, so this is only for pre-seeding a passkey without a first
magic-link login:

```bash
curl -s -X PUT "$BASE/admin/realms/$REALM/users/<user-id>/execute-actions-email\
?client_id=<client-id>&redirect_uri=<url-encoded-redirect-uri>" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '["webauthn-register-passwordless"]'
```

Needs a verified email on the user and realm SMTP configured. There is no way to pre-provision a
credential from the admin side alone — the key pair is generated client-side during the ceremony.

## Verifying this actually works

No endpoint reports "zero-password login is working". Configuration can look perfect and still
fail at the ceremony (a wrong `rpId` is the classic). **Both** methods have to be driven, and one
of them cannot be driven by curl:

| Method | How to verify | Tooling |
|---|---|---|
| Magic link | Request a login, submit an address, read the captured mail, follow the link, expect a redirect to `redirect_uri` with a code | Plain HTTP client |
| Passkey | Register via `webauthn-register-passwordless`, then log in through the `#authenticateWebAuthnButton` control | **Real browser required** |

A passkey ceremony is `navigator.credentials.create()` / `.get()` — actual client-side
JavaScript. Scripting it needs a headless browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `addVirtualAuthenticator`, e.g. Playwright); a plain HTTP client cannot fake
the crypto exchange. If no browser is available in the environment, say that the passkey half is
**unverified** rather than inferring it from configuration.

Also confirm the choice is actually offered — the login page should present the magic-link form
*and* a "Try another way" control leading to the passkey option. A flow where only one method is
reachable is the most likely wrong outcome here, and it looks entirely correct in the admin
console.

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send them
  over `http://localhost` anyway (loopback is a secure context); most HTTP client libraries will
  not, and every form POST then returns `400` *"Cookie not found."* Clear the flag on each
  response (`cookie.secure = False` in Python `requests`).
- A user who has completed a passkey registration and one who hasn't are shown different things
  by the same flow. Test both, or a check passes for one population and fails for the other.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `400` "Unrecognized field \"ifResourceExists\"" | Asset sent to the atomic endpoint unstripped — `jq 'del(.ifResourceExists)'` first |
| `partialImport` returns 200 but no flow exists | Expected: it has no authentication-flow handler. Use the atomic endpoint or the manual sequence |
| Login page shows a password field | The flow was built by copying stock `browser` — strip `auth-username-password-form` |
| Only the magic-link form, no way to reach the passkey | The passkey execution is missing, DISABLED, or not ALTERNATIVE at the same level as `ext-magic-form` |
| Passkey prompt appears first and blocks users with no passkey | Priorities inverted — `ext-magic-form` must be the lower priority of the two |
| Users with a live session are re-prompted | `auth-cookie` is not first in the top-level flow (the manual path appends) |
| "Check your email" but nothing arrives | Realm SMTP unset or wrong — the page looks identical either way |
| Typing an unknown email creates an account | `ext-magic-create-nonexistent-user` left at its `true` default |
| Passkey ceremony fails in the browser with no server-side error | `webAuthnPolicyPasswordlessRpId` empty or not matching the browsed hostname |
| Passkey ceremony never offers a discoverable credential | `webAuthnPolicyPasswordlessRequireResidentKey` not `"Yes"` |
| No `magic link` flow on the realm at all | The `keycloak-magic-link` jar isn't installed on this server |
| Users are asked to set a password after logging in | `ext-magic-update-password-action` configured, or an `UPDATE_PASSWORD` required action on the realm/user |
