<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Password login with emailed one-time code as a second factor — via raw Admin REST

## What this is, and what it isn't

Password stays. A correct password is **necessary but not sufficient** — after it, the user must
also enter a 6-digit code emailed to their account. This is **not** passwordless: it is
traditional login hardened with a second factor, and it uses a *different* first step than
`admin-email-otp-login.md`'s fully passwordless flow:

| | `admin:email-otp-login` (passwordless) | This doc (password + OTP, two-factor) |
|---|---|---|
| First step | `ext-auth-username-auth-note` (identifier only, no password) | `auth-username-password-form` (stock Keycloak — validates the password) |
| Getting the emailed code requires... | Just typing a known email address | Knowing the account's **password** |
| Security model | Possession of the inbox is the only factor | Password (something you know) + inbox (something you have) |

Both use `ext-email-otp` as the second execution and both need realm SMTP; only the first step
differs, and that difference is the entire point of this flow.

## Prerequisite: the keycloak-magic-link extension

Same as email-otp: `ext-email-otp` comes from
**[p2-inc `keycloak-magic-link`](https://github.com/p2-inc/keycloak-magic-link)**, not stock
Keycloak.

```bash
BASE=http://localhost:8080/auth
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

curl -s "$BASE/admin/realms/$REALM/authentication/authenticator-providers" -H "$H" \
  | jq -r '.[] | select(.id=="ext-email-otp")'
```

Empty output means it isn't installed — say so and stop.

## Author the flow

The shape, from
[`../assets/username-password-email-otp-flow.partial-import.json`](../assets/username-password-email-otp-flow.partial-import.json)
— **verified live**, including the negative cases, not just read from source:

| Sub-flow | Execution | Requirement | Why it's here |
|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | An existing SSO session still works. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | A federated path bypasses the forms sub-flow. |
| top-level | *forms sub-flow* | ALTERNATIVE | Taken when neither of the above applies. |
| forms | `auth-username-password-form` | REQUIRED | **The gate.** Stock Keycloak; validates the password before anything else runs. |
| forms | `ext-email-otp` | REQUIRED | Only reached after a correct password. Generates the code, mails it, verifies the input. |

This is the one place where `auth-username-password-form` is the *right* identifier-collection
step — the opposite of `admin-email-otp-login.md`'s guidance, where the same authenticator would
be wrong. There, the goal is a passwordless flow and `auth-username-password-form` would demand a
password that shouldn't exist as a requirement; here, demanding the password **is** the point.

Confirmed by driving real logins against a live deployment:

| Attempt | Result |
|---|---|
| Correct username + correct password | Reaches the OTP form; a real code is emailed |
| Correct username + **wrong** password | Rejected at the password step with `"Invalid username or password."` — **the OTP step is never reached and no mail is sent** |
| Unknown username | Same generic `"Invalid username or password."` — Keycloak's standard behavior for the combined username+password form gives no separate signal for "no such user" vs. "wrong password" |

The middle row is what actually proves this is two-factor rather than "email OTP with a password
field bolted on for show": knowing the account's email address is worthless without the password,
because the code is never sent until the password step succeeds.

Authoring paths, same two-plus-one-that-doesn't-work as the passwordless variant:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors and binds in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension |
| Manual sequence: create flow → sub-flow → add each execution → set requirements → attach config → bind | Many calls | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work** for authentication flows: HTTP 200, `added: 0`, nothing created. |

```bash
FLOW='email-otp-flow'
SUB='Email OTP forms'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$SUB\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":2}"

# Pass priority explicitly - these calls otherwise APPEND, and the sub-flow created
# above would sit at priority 0, ahead of the two leaves. Order matters: see the table.
i=0
for p in auth-cookie identity-provider-redirector; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\",\"priority\":$i}"
  i=$((i+1))
done
i=0
for p in auth-username-password-form ext-email-otp; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$SUB" '$f|@uri')/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\",\"priority\":$i}"
  i=$((i+1))
done
# List executions of both flows, PUT requirements (top-level ALTERNATIVE x3, forms REQUIRED x2),
# then attach config to ext-email-otp (below) and bind.
```

### The manual path silently loses this order

`executions/execution` and `executions/flow` **append**: with no `priority` in the body the
server assigns `last sibling's priority + 1`, so the resulting order is just the order the calls
were made in. Creating the sub-flow before the top-level leaves puts the sub-flow at priority 0 —
*first* — and the table above inverted. Nothing errors; the console looks right.

Send `priority` explicitly on every add call, then **read the order back and check it**:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

`priority` in the body is honoured only from **Keycloak 25** onward (added 2024-05-29); on 24 and
older it is ignored and calls append regardless. There, add them in the intended order and repair
with `POST .../authentication/executions/<exec-id>/raise-priority`, which swaps an execution with
one adjacent sibling per call.

The `authentication-flow/import` path carries the asset's own `priority` values, so the extension
path gets ordering right for free — this hazard is the manual sequence's alone.

## The one config option

Same shared key as plain email OTP:

```json
{ "alias": "email-otp-config", "config": { "ext-magic-create-nonexistent-user": "false" } }
```

It matters less here than in the passwordless case (a user has to already have a password to
reach this step at all, so force-create rarely has anything to do), but leave it at its safe
default unless there's a specific reason for this flow to create accounts.

## Realm mail settings

Same trap as every other magic-link-family flow: no SMTP configured by default, and a failed
send is swallowed silently. Verify by checking what actually left, not by trusting a `204`.

## Bind it

```bash
# Realm-wide: "browserFlow": "email-otp-flow" on the realm representation.
# Single client: the client's authenticationFlowBindingOverrides.browser -> the flow's id.
```

Ask which the user wants — realm-wide affects every client including admin/account consoles.

## Behaviors worth knowing

- **The password step is standard Keycloak, so its brute-force/lockout behavior is whatever the
  realm already has configured** — this flow doesn't need a separate brute-force decision the
  way the fully-passwordless email-OTP flow does, since the password step already gates guessing
  before the OTP is ever reached. Still confirm the realm's brute-force settings are on if that
  matters generally.
- **No separate "forgot password" bypass is introduced here.** This flow adds a second factor on
  top of existing password login; it does not change how the password itself is reset or
  recovered.
- **A fresh test user with no name on file** can pick up `VERIFY_PROFILE`, interrupting
  right after a correct OTP with an unrelated profile screen — not a flow bug.
- Everything else about `ext-email-otp` (no independent code TTL, code cached in an auth-session
  note, built-in resend) is identical to the passwordless variant — see
  `admin-email-otp-login.md` for those details rather than duplicating them here.

## Verifying this actually works

1. Correct username + correct password → OTP form appears, a real code is emailed.
2. Submit the emailed code → returns to the app's `redirect_uri` with an authorization code,
   `state` unchanged.
3. Correct username + **wrong** password → rejected immediately, generic message, **confirm no
   mail was sent** — this is what proves the password gates the OTP rather than merely preceding
   it cosmetically.
4. Unknown username → same generic rejection as (3), no separate signal.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| OTP email never arrives even after a correct password | Realm SMTP unconfigured or wrong — the send failure is swallowed |
| A wrong password still reaches the OTP form | The flow was authored with the wrong identifier step (e.g. `ext-auth-username-auth-note`, which doesn't check a password at all) instead of `auth-username-password-form` |
| Unknown users get a different error than wrong-password users | Not the behavior of the stock combined form — check nothing custom was layered in front of it |
| `ext-email-otp` not offered when adding an execution | The `keycloak-magic-link` extension isn't installed |
| A fresh test user hits an unrelated profile-completion screen after a correct code | `VERIFY_PROFILE` required action from a missing name on the user — not a flow bug |
