# Passkey-only passwordless login — via raw Admin REST

## What makes this different from magic-link

Both are "passwordless", but mechanically they're not close. Magic-link authenticates by
proving control of an email inbox (open the link, you're in) — Keycloak ships that flow
built-in, and the whole ceremony is a signed URL a plain HTTP client can follow. A passkey
authenticates by a real public-key cryptographic exchange between the browser and an
authenticator (a phone, a hardware key, a platform credential like Face ID) — Keycloak
ships **no** built-in flow for this, and completing a login or registration ceremony
requires actual client-side JavaScript talking to the WebAuthn API. Verifying this worked
needs a real browser, not a curl call.

```bash
BASE=http://localhost:8080/auth       # include the relative path if one is configured
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
FLOW='Passkey Only'
```

## The realm's WebAuthn PASSWORDLESS policy

This is a **separate policy block** from the realm's ordinary (second-factor) WebAuthn
policy — don't confuse the two field prefixes. Read the realm representation first (a
realm PUT that omits fields resets them), set the passwordless-prefixed fields, then PUT
the whole thing back:

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" > /tmp/realm.json
```

```json
{
  "webAuthnPolicyPasswordlessRpEntityName": "Acme Portal",
  "webAuthnPolicyPasswordlessRpId": "localhost",
  "webAuthnPolicyPasswordlessRequireResidentKey": "Yes",
  "webAuthnPolicyPasswordlessUserVerificationRequirement": "preferred"
}
```

```bash
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/realm.json
```

The field that actually breaks things if wrong: **`webAuthnPolicyPasswordlessRpId`**. It
defaults to empty, which falls back to the request's own hostname at ceremony time — fine
if every client reaches this realm through exactly one hostname, but if the realm is
reachable at more than one, an empty or mismatched `rpId` produces a ceremony that fails
**client-side**, with no useful server-side error (just a generic JS/browser exception).
Set it explicitly to the hostname the browser will actually navigate to.

For passkey-only (no username typed first, no password fallback),
`webAuthnPolicyPasswordlessRequireResidentKey="Yes"` is what lets a resident/discoverable
credential present itself without the user typing anything first.
`webAuthnPolicyPasswordlessUserVerificationRequirement` of `"preferred"` or `"required"` is
the usual choice (a PIN or biometric check on the authenticator itself, not just presence).

## Author the flow — Keycloak ships no built-in one

Unlike magic-link, there is no auto-created flow to bind here — one has to be authored. Two
paths do that, and a third that looks obvious does not work at all:

| Path | Cost | Requires |
|---|---|---|
| `POST /admin/realms/{realm}/authentication-flow/import?force={bool}` — authors the flow **and** applies bindings (`browserFlowBinding`, `clientFlowBinding`) in one call | **One call** | The [p2-inc keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension installed on the target Keycloak |
| The manual sequence below — create flow → add each execution → set each requirement → attach config → bind | Many calls, easy to get subtly wrong | Nothing beyond stock Admin REST |
| ~~`POST /admin/realms/{realm}/partialImport`~~ | — | **Does not work.** It has no handler for authentication flows and silently ignores them: HTTP 200, `added: 0`, no error, nothing created. The admin console's "Partial import" action and `kcadm.sh create partialImport` fail the same way. |

**Offer the extension when it isn't installed** (it 404s clearly) — one jar collapses the whole
sequence into a single call that also binds. The manual path below is perfectly legitimate if the
user can't add it; just say upfront that it's substantially more calls. Note the extension
hash-prefixes the alias it creates, so read the real name back rather than assuming the one you
supplied.

If taking the manual path, confirm none already exists, then build one from an empty shell:

```bash
# 1. Confirm no existing flow already does this.
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" | jq -r '.[].alias'

# 2. Create an empty top-level flow. 409 if it already exists — check executions next
#    rather than assuming a fresh create always succeeds.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

# 3. Check what executions already exist before adding any — this endpoint does NOT
#    dedupe: POSTing the same provider twice appends a second execution rather than
#    409ing, and the flow may already have both (e.g. pre-authored via realm import).
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H"

# 4. auth-cookie ALTERNATIVE at the top level, and the passkey step REQUIRED inside its
#    own ALTERNATIVE sub-flow. The sub-flow is NOT decoration: a REQUIRED step and an
#    ALTERNATIVE step at the SAME level make Keycloak erase the alternative bucket
#    (DefaultAuthenticationFlow.fillListsOfExecutions -> alternativeList.clear()), so a
#    bare two-leaf flow silently never runs auth-cookie at all. See
#    flow-execution-order.md's "Shape" section.
# These calls APPEND: with no "priority" the server assigns (last sibling + 1), so the
# order is simply the order you call them in. Send it explicitly - auth-cookie must be
# first, so an existing SSO session is consulted before the passkey step runs.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' -d '{"provider":"auth-cookie","priority":0}'
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"Passkey Only forms","provider":"basic-flow","type":"basic-flow","priority":1}'
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/Passkey%20Only%20forms/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' -d '{"provider":"webauthn-authenticator-passwordless","priority":0}'

# 5. List executions again to get each one's own id, then set requirements:
#    auth-cookie                        -> ALTERNATIVE  (top level)
#    Passkey Only forms (the sub-flow)  -> ALTERNATIVE  (top level stays all-ALTERNATIVE)
#    webauthn-authenticator-passwordless -> REQUIRED    (alone on its own level - this is
#      what makes it "no password, ever", not just deprioritized)
curl -s -X PUT "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" \
  -H "$H" -H 'Content-Type: application/json' -d '{"id":"<auth-cookie-execution-id>","requirement":"ALTERNATIVE","priority":0}'
curl -s -X PUT "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" \
  -H "$H" -H 'Content-Type: application/json' -d '{"id":"<sub-flow-execution-id>","requirement":"ALTERNATIVE","priority":1}'
curl -s -X PUT "$BASE/admin/realms/$REALM/authentication/flows/Passkey%20Only%20forms/executions" \
  -H "$H" -H 'Content-Type: application/json' -d '{"id":"<webauthn-execution-id>","requirement":"REQUIRED","priority":0}'
```

Resulting shape — note the top level is **all-ALTERNATIVE**:

```
Passkey Only                              (top level)
├── auth-cookie                            ALTERNATIVE
└── Passkey Only forms                     ALTERNATIVE   (sub-flow)
    └── webauthn-authenticator-passwordless REQUIRED
```

Then confirm the order actually landed — nothing errors if it didn't:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) pri=\(.priority) \(.requirement) \(.providerId)"'
```

`priority` in the body is honoured only from **Keycloak 25** onward (added 2024-05-29); on 24 and
older it is ignored and calls append regardless. There, add them in order and repair with
`POST .../authentication/executions/<exec-id>/raise-priority`, which swaps an execution with one
adjacent sibling per call. The `authentication-flow/import` path carries its own `priority`
values, so it gets this right for free.

**Do not add a Username Password Form, and do not add it to a copy of the stock `browser`
flow without stripping that step out first** — a copied `browser` flow keeps Kerberos, the
IdP redirector, and (critically) the password form as ALTERNATIVE steps, which defeats "no
password, ever." Building the flow from an empty shell with exactly these two executions is
simpler and avoids that trap entirely.

## Bind it

```bash
# Client-level: only one application goes passkey-only, others keep password login.
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  | jq -r --arg f "$FLOW" '.[] | select(.alias==$f) | .id'   # note the flow's own id

curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" > /tmp/client.json
# set client["authenticationFlowBindingOverrides"]["browser"] = "<flow-id>" in /tmp/client.json
curl -s -X PUT "$BASE/admin/realms/$REALM/clients/<client-internal-id>" -H "$H" \
  -H 'Content-Type: application/json' --data-binary @/tmp/client.json

# Realm-wide instead: set "browserFlow": "<flow-alias>" on the realm representation
# the same way magic-link's realm-wide bind does — affects every client, including
# admin/account consoles, which usually should keep their own login path.
```

Ask which the user actually wants before binding — realm-wide affects every client.

## Realm mail settings — required for credential bootstrap, and it fails silently

Same dependency and same silent-failure trap as magic-link: a realm ships with **no SMTP
settings at all**, and the send call catches its own failure internally — nothing surfaces
to the caller.

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

PUT the whole realm representation with this set (read-modify-write, same as the policy
step above). **Verify by checking what actually left**, not by trusting a `204` — if
there's no real mail provider to point at (a test/sandbox setting), a minimal
SMTP-protocol capture server is enough.

## The bootstrap problem: getting a FIRST passkey with no password

This is the piece with no analog in a password-based world. A brand-new or
previously-password-only user has **zero credentials**. They cannot "just log in" to
register a passkey, because there's nothing to log in *with* yet — and unlike magic-link's
anti-enumeration design (identical response either way), there's no equivalent
bootstrap-free path for a cryptographic ceremony.

```bash
# Look up the user's id first if only given a username/email.
curl -s "$BASE/admin/realms/$REALM/users?username=<username>&exact=true" -H "$H"

# Action-token-authenticated link — the same underlying mechanism magic-link login
# itself uses — so it needs no password and no pre-existing credential.
curl -s -X PUT "$BASE/admin/realms/$REALM/users/<user-id>/execute-actions-email\
?client_id=<client-id>&redirect_uri=<url-encoded-redirect-uri>" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '["webauthn-register-passwordless"]'
```

Requires the user to have a verified email address, and realm SMTP already configured
(above). Do this for every user who needs a first passkey — there is no way to
pre-provision a credential from the admin side alone; the actual key pair is generated
client-side during the ceremony.

## Verifying this actually works

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
3. **No password, ever**: check the actual page content at both steps 1 and 2 — and also
   for a login attempt with NO registered credential at all — never contains a password
   input.

A real user has no way to script `navigator.credentials.create/get()` — verifying this
programmatically needs a real browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `WebAuthn.addVirtualAuthenticator` with
`hasResidentKey/hasUserVerification/isUserVerified: true`, `automaticPresenceSimulation:
true`), the standard technique for testing WebAuthn flows headlessly — there is no way to
fake this exchange with a plain HTTP client.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Ceremony fails immediately in the browser, generic error, nothing useful server-side | `webAuthnPolicyPasswordlessRpId` mismatched to the actual serving hostname |
| `execute-actions-email` returns success but nothing arrives | Realm SMTP settings are unconfigured or wrong — same trap as magic-link |
| Login page still shows a password field | The bound flow still has a Username Password Form execution somewhere (often from copying `browser` instead of building fresh) |
| No `#registerWebAuthn` / `#authenticateWebAuthnButton` control on the page | The required action isn't wired up, or the flow isn't actually bound to the client being tested |
| `POST .../executions/execution` appears to duplicate a step | The endpoint doesn't dedupe — check existing executions before adding, don't assume a fresh flow |
