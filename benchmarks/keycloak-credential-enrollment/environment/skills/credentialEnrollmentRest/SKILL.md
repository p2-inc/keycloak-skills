---
name: credentialEnrollmentRest
description: >-
  Enroll a NEW credential on a user who ALREADY exists in a Keycloak realm - a
  TOTP authenticator, a passkey, a replacement password, recovery codes - via
  the raw Keycloak Admin REST API. Use whenever someone wants users to "set up
  2FA", "enroll in TOTP", "register an authenticator app", "set up my passkey",
  or asks how a user actually gets their first credential. Two variants, and
  the PREREQUISITE picks between them rather than preference: a required action
  set on the user reaches anyone who can already log in and needs no mail at
  all, while an emailed enrollment link is the only thing that reaches a user
  with no credential - and needs realm SMTP. Both are silently inert unless the
  action is registered AND enabled, which is the single most common cause of "I
  configured it and nothing happened". Not authoring or binding a login flow -
  this is the step that makes such a flow usable.
---

Getting a **new credential onto a user who already exists**: a passkey, a TOTP
authenticator, a replacement password, recovery codes. This is the step every
passwordless intent leaves dangling — a flow can be authored and bound perfectly and
still let nobody in, because no user has the credential it asks for.

Two variants, and the prerequisite is the thing that decides between them, not taste.

| | Variant A — required action on the user | Variant B — enrollment email |
|---|---|---|
| **Prerequisite** | The user can already log in (any working credential) | Realm SMTP configured, user has an email address |
| **Needs SMTP?** | **No** | Yes |
| **Works for a zero-credential user?** | No — nothing to log in with | **Yes** — the link is the authentication |
| **When they're prompted** | Next login, after authenticating, before returning to the app | Whenever they open the emailed link |
| **Mechanism** | `requiredActions` on the user representation | Action token (same as magic-link / password reset) |

Pick A when the user already has a password and you're adding a second or replacement
credential. Pick B when they have nothing, or you can't interrupt their next login.

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
```

## Shared prerequisite: the action must be REGISTERED **and** ENABLED

Do this before either variant. An action can be in three states, and two of them make
**both** variants silently inert — the API accepts everything and the user is simply never
prompted:

- **enabled** — actually runs.
- **registered but disabled** — present in the realm, does nothing.
- **available but not registered** — not usable at all.

```bash
# What is registered in this realm, and is it enabled?
curl -s "$BASE/admin/realms/$REALM/authentication/required-actions" -H "$H" \
  | jq '.[] | {alias, enabled, defaultAction}'

# What the server supports but this realm has not registered
curl -s "$BASE/admin/realms/$REALM/authentication/unregistered-required-actions" -H "$H"
```

Register (only if it appeared in the unregistered list), then enable:

```bash
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/register-required-action" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"providerId":"webauthn-register-passwordless","name":"webauthn-register-passwordless"}'

# Read-then-merge: this PUT REPLACES the representation, so send the whole object back.
curl -s "$BASE/admin/realms/$REALM/authentication/required-actions/webauthn-register-passwordless" -H "$H" \
  | jq '.enabled = true' \
  | curl -s -X PUT "$BASE/admin/realms/$REALM/authentication/required-actions/webauthn-register-passwordless" \
      -H "$H" -H 'Content-Type: application/json' -d @-
```

Enabling makes the action *usable* — including via an application-initiated action
(`kc_action`). It does not by itself demand the action from anyone. That's what the two
variants below do.

## Variant A — set the required action on the user

No email, no SMTP. The user is prompted at their **next login**, after they authenticate
and before they're returned to the app.

Keycloak's user PUT **replaces the whole representation** — sending just
`{"requiredActions":[...]}` blanks out email, names, attributes and group-independent
fields on that user. Always read-then-merge:

```bash
USER_ID=$(curl -s "$BASE/admin/realms/$REALM/users?username=<username>&exact=true" -H "$H" | jq -r '.[0].id')

# Read, append the action (deduped), PUT the whole object back.
curl -s "$BASE/admin/realms/$REALM/users/$USER_ID" -H "$H" \
  | jq '.requiredActions = ((.requiredActions // []) + ["webauthn-register-passwordless"] | unique)' \
  | curl -s -o /dev/null -w '%{http_code}\n' \
      -X PUT "$BASE/admin/realms/$REALM/users/$USER_ID" \
      -H "$H" -H 'Content-Type: application/json' -d @-
```

A `204` means stored, **not** that it will prompt — an alias that isn't enabled in the
realm is stored on the user verbatim and simply never fires. Read it back (below) and
confirm the alias also appears as `enabled` in the realm list above.

To apply this to **every** user, loop over `/users` — there is no bulk endpoint. To apply
it to users created **from now on** instead, set `defaultAction: true` on the action
itself (the same read-merge-PUT as the enable step). `defaultAction` is **not
retroactive** — it does nothing to accounts that already exist, which is the single most
common surprise here.

## Variant B — email an enrollment link

Needs no existing credential at all: the link is an **action token**, the same mechanism
behind magic-link login and password-reset mail. This is the correct way to bootstrap a
credential-less account — not setting a temporary password on the user's behalf.

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X PUT "$BASE/admin/realms/$REALM/users/$USER_ID/execute-actions-email\
?client_id=<client-id>&redirect_uri=<url-encoded-redirect-uri>&lifespan=43200" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '["webauthn-register-passwordless"]'
```

- The body is a **JSON array of aliases**, not an object.
- `client_id` + `redirect_uri` decide where the user lands afterwards. Omit them and the
  user completes the action on an "Your account has been updated" page with nowhere to go;
  `redirect_uri` must be a registered redirect URI of `client_id` or Keycloak rejects it.
- `lifespan` is seconds. **43200 (12h) is already the default**
  (`actionTokenGeneratedByAdminLifespan`), so passing that exact value changes nothing —
  set it only when you actually want a different window.
- A `204` means Keycloak **queued** the mail. It is not delivery confirmation, and
  unconfigured SMTP fails the same silent way it does for magic-link. Verify at the
  capture point / provider.

> **If you copied this curl out of the browser's DevTools**, strip it down. A "Copy as
> cURL" from the admin console carries `sec-ch-ua`, `user-agent`, `origin` and `priority`
> headers that are pure noise — and, more importantly, it carries **no `Authorization`
> header**, because in the browser it rode on the console's session cookie. Replayed from
> a script it 401s. It also usually loses `Content-Type: application/json`, without which
> the array body is rejected. Both are required above.

## Choosing the alias

Get exact spellings from the realm's own required-actions list — do not guess, and do not
normalize the casing. Keycloak's aliases are **inconsistently cased and matched exactly**:
stock actions are `SCREAMING_SNAKE` (`CONFIGURE_TOTP`, `UPDATE_PASSWORD`, `VERIFY_EMAIL`,
`UPDATE_PROFILE`, `CONFIGURE_RECOVERY_AUTHN_CODES`) while the WebAuthn ones are kebab-case
(`webauthn-register`, `webauthn-register-passwordless`).

The one that silently produces the wrong result:

| Alias | Enrolls | Use for |
|---|---|---|
| `webauthn-register-passwordless` | A **passwordless** credential | Passkeys — `admin:passwordless-passkey`, `admin:zero-password-login` |
| `webauthn-register` | A **two-factor** WebAuthn credential | WebAuthn as a second factor alongside a password |

These are separate credential types against separate realm policies. Enrolling
`webauthn-register` and then binding a passwordless flow gives a user who owns a security
key and still cannot log in — with nothing in the logs to explain it. Match the alias to
the flow you actually bound.

**There is no SMS action.** Stock Keycloak ships no SMS required action or authenticator,
and neither does Phase Two — verified against both sources, not assumed. It needs a
third-party or custom extension; say so plainly rather than substituting email OTP for it.

## Verifying it worked

Neither variant reports anything useful on success, so check the two things that actually
decide the outcome:

```bash
# 1. The action is pending on the user
curl -s "$BASE/admin/realms/$REALM/users/$USER_ID" -H "$H" | jq '.requiredActions'

# 2. It is enabled realm-wide (an un-enabled action never fires)
curl -s "$BASE/admin/realms/$REALM/authentication/required-actions" -H "$H" \
  | jq '.[] | select(.alias=="webauthn-register-passwordless") | {alias, enabled}'
```

Then drive it for real — configuration that looks right still fails at the ceremony:

- **Variant A**: log in as the user. After the password is accepted you should land on the
  action's own page (for WebAuthn, one carrying a `#registerWebAuthn` control) *before*
  the redirect back to the app. Completing it clears the entry from `requiredActions` —
  re-read the user and confirm the array is now empty.
- **Variant B**: open the emailed link. It leads through a "Perform the following
  action(s)" interstitial, then the same enrollment page.

A WebAuthn ceremony cannot be completed by a plain HTTP client — the key pair is generated
browser-side. Verifying it headlessly needs a real browser with a **CDP virtual
authenticator** (`WebAuthn.enable` + `WebAuthn.addVirtualAuthenticator`).

## Common errors

| Symptom | Cause |
|---|---|
| PUT returns 204, user is never prompted | The alias isn't `enabled` in the realm — the two states are indistinguishable from the user PUT alone |
| The user's email/name/attributes were wiped | Sent a partial body to the user PUT; it replaces the representation — read-then-merge |
| `execute-actions-email` 400s on the alias | Unknown or unregistered alias, or the body was an object instead of a JSON array |
| 204 from `execute-actions-email`, no mail arrives | Realm SMTP unconfigured or wrong — same silent trap as magic-link; check what actually left |
| Replayed DevTools curl returns 401 | The copied command had no `Authorization` header; it relied on the console's session cookie |
| `redirect_uri` rejected | Not a registered redirect URI for the supplied `client_id` |
| User enrolled a key but passwordless login still fails | Enrolled `webauthn-register` (2FA) where the bound flow wants `webauthn-register-passwordless` |
| Set `defaultAction`, existing users unaffected | Correct behaviour — `defaultAction` applies only to users created afterwards |
