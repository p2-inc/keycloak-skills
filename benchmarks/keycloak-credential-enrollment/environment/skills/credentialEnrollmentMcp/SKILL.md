---
name: credentialEnrollmentMcp
description: >-
  Enroll a NEW credential on a user who ALREADY exists in a Keycloak realm - a
  TOTP authenticator, a passkey, a replacement password, recovery codes -
  driven through the Keycloak MCP server's tools where they exist, with the
  genuine gaps covered by documented REST recipes. Use whenever someone wants
  users to "set up 2FA", "enroll in TOTP", "register an authenticator app",
  "set up my passkey", or asks how a user actually gets their first credential.
  Two variants, and the PREREQUISITE picks between them rather than preference:
  a required action set on the user reaches anyone who can already log in and
  needs no mail at all, while an emailed enrollment link is the only thing that
  reaches a user with no credential - and needs realm SMTP AND a verified email
  address, because the link authenticates whoever opens it. Both are silently
  inert unless the action is registered AND enabled, which is the single most
  common cause of "I configured it and nothing happened". Not authoring or
  binding a login flow - this is the step that makes such a flow usable.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

Getting a **new credential onto a user who already exists**: a passkey, a TOTP
authenticator, a replacement password, recovery codes. This is the step every passwordless
intent leaves dangling — a flow can be authored and bound perfectly and still let nobody
in, because no user has the credential it asks for.

Two variants, and the prerequisite decides between them, not taste.

| | Variant A — required action on the user | Variant B — enrollment email |
|---|---|---|
| **Prerequisite** | The user can already log in (any working credential) | Realm SMTP configured, **and a VERIFIED email address** |
| **Needs SMTP?** | **No** | Yes |
| **Works for a zero-credential user?** | No — nothing to log in with | **Yes** — the link is the authentication |
| **When they're prompted** | Next login, after authenticating, before returning to the app | Whenever they open the emailed link |
| **MCP support** | **None — no tool sets this. Use REST.** | `sendRequiredActionEmail` |

## Tools this skill drives

| Purpose | Tool |
|---|---|
| Identify caller / realm | `whoAmI` |
| See which actions exist and whether they're actually live | `listRequiredActions` |
| Register + enable an action (does both) | `enableRequiredAction` |
| Read/tune an action's own config, where it has any | `setRequiredActionConfig` |
| Demand the action of **newly created** users | `setDefaultRequiredAction` |
| Find the user's id | `findUser` — but see the `hasCredentials` warning below |
| **Variant B** — email an enrollment link | `sendRequiredActionEmail` |
| Configure outgoing mail (Variant B only) | `setSmtpSettings` |

Capture **`deploymentId`** and **`deploymentRealm`** and reuse them on every call.

## Variant A has no MCP path — this is a real gap, not a missing lookup

**No tool on this server can put a required action on an existing user.** Verified against
the server's own source, not inferred: `updateUser` accepts only `email`, `firstName`,
`lastName`, `enabled` and `emailVerified`, and the field name `requiredActions` appears
nowhere in the codebase at all.

The near-miss that will look like the answer and isn't: `setDefaultRequiredAction`. It sets
`defaultAction` on the *action*, which applies to users created **afterwards**. It is not
retroactive and does nothing whatsoever to an account that already exists.

**Do not trust `findUser`'s `hasCredentials` to pick the variant — it reports `false` for
everyone.** The tool derives it from the `credentials` field of a user *search* result, and
Keycloak's search endpoint never populates that field; verified against Keycloak 26, a user who
demonstrably holds a password comes back from `GET /users?username=...` with no `credentials` key
at all. So the one field that looks like it answers "which variant applies here" answers "no
credentials" for every user, which would push every user onto the email variant — including users
who should never have been mailed. Read the dedicated endpoint instead:

```bash
GET /admin/realms/{realm}/users/{id}/credentials   ->  [] means genuinely no credential
```

The same applies to `emailVerified`, which no tool surfaces either. Both checks are one small REST
call each; make them rather than guessing.

So for Variant A, say plainly that this one step needs the Admin REST API and follow
the Admin REST API: a read-merge-`PUT` of the user's `requiredActions` — a
read-merge-`PUT` on `/admin/realms/{realm}/users/{id}`. Everything else on this page still
runs through MCP. Don't silently substitute Variant B (it needs SMTP the deployment may not
have) or fall back to setting a password — `setUserPassword`'s own description warns against
exactly that.

## Stage 1 — Establish identity and target

1. `whoAmI` — tell the user who they are and which realm the token came from.
2. Confirm the target deployment/realm, and which credential is being enrolled.

## Stage 2 — Make the action live (both variants)

An action has three states, and two of them make **both** variants silently inert — every
call succeeds and the user is simply never prompted. `listRequiredActions` is built to
report them separately for exactly this reason:

- `enabled` — actually runs.
- `registeredButDisabled` — present, does nothing.
- `availableButNotRegistered` — not usable at all.

Call `listRequiredActions` first. It is also the authoritative source for the **exact
alias** the later calls need — take the spelling from here rather than typing one from
memory.

If the action isn't under `enabled`, call
`enableRequiredAction(alias="webauthn-register-passwordless")`. It registers first when
needed, so it handles both broken states in one call; `enabled=false` turns one off.

Enabling makes the action *usable* — including via an application-initiated action
(`kc_action`). It does not by itself demand the action from anyone.

## Stage 3 — Variant B: email an enrollment link

Needs no existing credential: the link is an **action token**, the same mechanism behind
magic-link login and password-reset mail. This is the correct way to bootstrap a
credential-less account rather than an admin choosing a password on the user's behalf.

1. `findUser(username=...)` → the user's id. Its `hasCredentials` field also tells you
   whether this account is genuinely credential-less.
2. `setSmtpSettings` if the realm has no mail configured yet.
3. `sendRequiredActionEmail(userId, actions=["webauthn-register-passwordless"], clientId, redirectUri)`.

> **Send only to a VERIFIED address. Nothing in the stack stops you.** `sendRequiredActionEmail`'s
> own description says the user should have a verified email, but neither the tool nor Keycloak
> enforces it: verified live against Keycloak 26, `execute-actions-email` to a user with
> `emailVerified: false` returns **204 and delivers the message**.
>
> It matters because of what the link *is*. The action token authenticates whoever opens it — that
> is exactly why it works for a credential-less account. Mailing it to an address nobody has proven
> the account holder controls hands credential enrollment, and with it the account, to whoever
> reads that mailbox.
>
> If `emailVerified` is false, **stop and say so**. Get the address confirmed through a channel you
> already trust first. Don't prepend `VERIFY_EMAIL` to the same call and call it handled — both
> actions ride the same token, so the same unverified reader completes both. And don't set
> `emailVerified: true` via `updateUser` to clear the check; that asserts a verification nobody
> performed.

`clientId` + `redirectUri` decide where the user lands afterwards — supply both, or they
finish on a page with nowhere to go. `redirectUri` must be a registered redirect URI of
that client.

`success:true` means Keycloak **queued** the mail. It is not delivery confirmation, and
unconfigured SMTP fails the same silent way it does for magic-link — the tool says so in
its own `nextStep`. Verify at the capture point or provider.

**No custom link lifetime over MCP.** `sendRequiredActionEmail` exposes no `lifespan`
argument (confirmed in the server's REST client — it passes only `client_id`,
`redirect_uri` and the actions body), so links use the realm default
`actionTokenGeneratedByAdminLifespan`, 12 hours. A different window needs the Admin REST
`?lifespan=` query parameter. Second real gap on this page; name it rather than quietly
accepting the default.

## Related lever — demand it of NEW users

`setDefaultRequiredAction(alias=...)` makes every **newly created** user get the action.
Useful alongside either variant, and the natural way to stop this problem recurring. Two
things it will not do: it does not touch existing users, and it is inert while the action
is disabled — the tool checks that second case and warns rather than reporting a success
that does nothing.

## Choosing the alias

Take exact spellings from `listRequiredActions`. Keycloak's aliases are **inconsistently
cased and matched exactly**: stock actions are `SCREAMING_SNAKE` (`CONFIGURE_TOTP`,
`UPDATE_PASSWORD`, `VERIFY_EMAIL`, `UPDATE_PROFILE`,
`CONFIGURE_RECOVERY_AUTHN_CODES`) while the WebAuthn ones are kebab-case.

The pair that silently produces the wrong result:

| Alias | Enrolls | Use for |
|---|---|---|
| `webauthn-register-passwordless` | A **passwordless** credential | Passkeys — `admin:passwordless-passkey`, `admin:zero-password-login` |
| `webauthn-register` | A **two-factor** WebAuthn credential | WebAuthn as a second factor alongside a password |

Separate credential types, separate realm policies. Enrolling `webauthn-register` and then
binding a passwordless flow gives a user who owns a security key and still cannot log in,
with nothing in the logs to explain it. Match the alias to the flow actually bound.

**There is no SMS action.** Stock Keycloak ships no SMS required action or authenticator,
and neither does Phase Two — verified against both sources, not assumed. It needs a
third-party or custom extension; say so plainly rather than substituting email OTP for it.

## Verifying it worked

Neither variant reports anything conclusive, so check the two things that decide the
outcome:

1. `listRequiredActions` — the alias appears under **`enabled`**, not one of the other two
   buckets.
2. The action is pending on the user. There is no MCP tool that reads a user's
   `requiredActions` (`findUser` returns id/username/email/enabled/`hasCredentials` only),
   so confirm this behaviourally by logging in, or over REST.

Then drive it for real — configuration that looks right still fails at the ceremony:

- **Variant A**: log in as the user; the action's own page (for WebAuthn, one carrying a
  `#registerWebAuthn` control) should appear after authentication and before the redirect
  back to the app.
- **Variant B**: open the emailed link — a "Perform the following action(s)" interstitial,
  then the same enrollment page.

A WebAuthn ceremony cannot be completed by a plain HTTP client; the key pair is generated
browser-side. Headless verification needs a real browser with a **CDP virtual
authenticator** (`WebAuthn.enable` + `WebAuthn.addVirtualAuthenticator`).

## Common errors

- **Everything succeeded, the user is never prompted** — the alias is under
  `registeredButDisabled` or `availableButNotRegistered`. `enableRequiredAction` fixes
  both; `listRequiredActions` is what tells them apart.
- **`setDefaultRequiredAction` succeeded, existing users unaffected** — correct behaviour,
  not a bug. Existing users need Variant A (REST) or Variant B.
- **`sendRequiredActionEmail` returns `success:true`, no mail arrives** — that confirms
  only that Keycloak queued it; check realm SMTP and the capture point.
- **`redirectUri` rejected** — not a registered redirect URI for the supplied `clientId`.
- **User enrolled a key but passwordless login still fails** — enrolled
  `webauthn-register` (2FA) where the bound flow wants `webauthn-register-passwordless`.
- **Looking for a tool to set a required action on one existing user** — there isn't one.
  See "Variant A has no MCP path" above; use the Admin REST API rather than improvising.
- **`findUser` says `hasCredentials: false` for a user who clearly has a password** — it is
  derived from a field Keycloak's user search never populates, so it is `false` for everyone.
  Read `GET /admin/realms/{realm}/users/{id}/credentials` instead.
- **Enrollment mail reached an unverified address** — nothing blocks that; check `emailVerified`
  before every send.
