---
name: passwordOrPasskeyLoginRest
description: >-
  Configure username/password OR a passkey as alternative first-factor methods on one
  Keycloak login page, via raw Admin REST. Use whenever someone wants "username and password with
  a passkeys option", "password or passkey", "keep passwords but add passkeys", or a login
  where either method alone signs the user in. Covers authoring and binding the flow with
  auth-username-password-form and webauthn-authenticator-passwordless as ALTERNATIVE siblings
  (and why a REQUIRED or conditional passkey step silently makes it 2FA), the realm's WebAuthn
  PASSWORDLESS policy block, enrolling an existing user's first passkey, and verifying both
  paths end to end. Not zero-password login (no password anywhere) and not WebAuthn as a
  second factor.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Username/password OR passkey login — alternative first-factor methods via REST

## What this is

One browser flow offering **two alternative first-factor authentication methods side by side**:
traditional **username and password**, and **passkey (WebAuthn passwordless)**. The user chooses
either path at login time. Unlike `admin:zero-password-login`, the password is **not removed** —
it remains a fully supported authentication path. Unlike `admin:passwordless-passkey`, the
password is **not eliminated** — passkey is an *additional* option.

This is the "password with passkey option" pattern for gradual migration: keep existing password
infrastructure while offering passkey as a modern alternative.

Security note: accounts support both credential types. The presence of a passkey does not prevent
password login, and vice versa. User security depends on which credential they actually use.

```bash
BASE=http://localhost:8080/auth
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>
FLOW='Password-or-passkey'
SUB='Password-or-passkey forms'
```

## The flow shape

| Flow | Execution | Requirement | Priority |
|---|---|---|---|
| `Password-or-passkey` (top level) | `auth-cookie` | ALTERNATIVE | 0 |
| | `auth-spnego` | DISABLED | 1 |
| | `identity-provider-redirector` | ALTERNATIVE | 2 |
| | *forms sub-flow* | ALTERNATIVE | 3 |
| *forms sub-flow* | `auth-username-password-form` | ALTERNATIVE | 2 |
| | `webauthn-authenticator-passwordless` | ALTERNATIVE | 3 |

**Key points:**
- `auth-username-password-form` (stock Keycloak) provides the password path
- `webauthn-authenticator-passwordless` (stock Keycloak) provides the passkey path — **not**
  `webauthn-authenticator` (that's the second-factor variant)
- Both are ALTERNATIVE in the same forms sub-flow, creating the "either/or" choice

## Authoring via atomic import (only with the extension)

`POST /admin/realms/{realm}/authentication-flow/import` with the p2-inc keycloak-atomic-auth-flows
extension authors the whole flow in one call. Stock Keycloak has no such endpoint: a `404` here
means the extension is not installed, so use [manual authoring](#manual-authoring-no-extension)
instead.

Strip `ifResourceExists` from the payload (the extension rejects unknown fields), and read the
generated alias back from the response (the extension hash-prefixes aliases):

```bash
cat > /tmp/password-or-passkey.json << 'EOF'
{
  "flowAlias": "Password-or-passkey",
  "description": "Browser flow with password or passkey as alternative first factors",
  "providerId": "basic-flow",
  "topLevel": true,
  "builtIn": false,
  "authenticationExecutions": [
    {
      "authenticator": "auth-cookie",
      "requirement": "ALTERNATIVE",
      "priority": 0,
      "autheticatorFlow": false,
      "userSetupAllowed": false
    },
    {
      "authenticator": "auth-spnego",
      "requirement": "DISABLED",
      "priority": 1,
      "autheticatorFlow": false,
      "userSetupAllowed": false
    },
    {
      "authenticator": "identity-provider-redirector",
      "requirement": "ALTERNATIVE",
      "priority": 2,
      "autheticatorFlow": false,
      "userSetupAllowed": false
    },
    {
      "requirement": "ALTERNATIVE",
      "priority": 3,
      "autheticatorFlow": true,
      "flowAlias": "Password-or-passkey forms",
      "userSetupAllowed": false
    }
  ],
  "nestedFlows": [
    {
      "flowAlias": "Password-or-passkey forms",
      "description": "Username/password or passkey forms",
      "providerId": "basic-flow",
      "topLevel": false,
      "builtIn": false,
      "authenticationExecutions": [
        {
          "authenticator": "auth-username-password-form",
          "requirement": "ALTERNATIVE",
          "priority": 2,
          "autheticatorFlow": false,
          "userSetupAllowed": false
        },
        {
          "authenticator": "webauthn-authenticator-passwordless",
          "requirement": "ALTERNATIVE",
          "priority": 3,
          "autheticatorFlow": false,
          "userSetupAllowed": false
        }
      ]
    }
  ]
}
EOF

curl -s -X POST "$BASE/admin/realms/$REALM/authentication-flow/import?force=false" \
  -H "$H" -H 'Content-Type: application/json' --data-binary @/tmp/password-or-passkey.json
```

## Manual authoring (no extension)

Stock Admin REST, in this order. `q` URL-encodes an alias (the sub-flow's contains a space).

```bash
q() { jq -rn --arg f "$1" '$f|@uri'; }
J='Content-Type: application/json'

# 1. Top-level flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" -H "$J" \
  -d '{"alias":"Password-or-passkey","description":"Browser flow with password or passkey","providerId":"basic-flow","topLevel":true,"builtIn":false}'

# 2. The forms sub-flow is created AS an execution of the parent, in one call. Do NOT
#    create it first with POST /authentication/flows: that makes a second, top-level flow
#    with the same alias, this call then answers 409 Conflict, and the orphan stays behind.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions/flow" -H "$H" -H "$J" \
  -d '{"alias":"Password-or-passkey forms","description":"Username/password or passkey forms","provider":"basic-flow","type":"basic-flow","priority":3}'

# 3. Leaves of the top-level flow. The add call APPENDS unless priority is sent.
for p in auth-cookie:0 auth-spnego:1 identity-provider-redirector:2; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions/execution" -H "$H" -H "$J" \
    -d "{\"provider\":\"${p%%:*}\",\"priority\":${p##*:}}"
done

# 4. Leaves of the forms sub-flow: the password form first, so it is the page users see.
for p in auth-username-password-form:2 webauthn-authenticator-passwordless:3; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(q "$SUB")/executions/execution" -H "$H" -H "$J" \
    -d "{\"provider\":\"${p%%:*}\",\"priority\":${p##*:}}"
done

# 5. Set requirements. New executions start DISABLED, and the add calls ignore a
#    "requirement" field. Change one with PUT on the flow's executions COLLECTION
#    (not executions/{id}), sending the execution's WHOLE row back with only the
#    requirement changed: the PUT also writes "priority", so a body of just
#    {"id","requirement"} resets the priority to 0 and scrambles the order. A
#    sub-flow's own row has no providerId; it is matched by its displayName (the alias).
set_req() {  # <flow alias> <providerId or sub-flow alias> <requirement>
  curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(q "$1")/executions" -H "$H" \
    | jq -c --arg k "$2" --arg r "$3" '.[] | select((.providerId // .displayName) == $k) | .requirement = $r' \
    | curl -s -o /dev/null -w "$2 -> $3: %{http_code}\n" -X PUT \
        "$BASE/admin/realms/$REALM/authentication/flows/$(q "$1")/executions" -H "$H" -H "$J" --data-binary @-
}
set_req "$FLOW" auth-cookie ALTERNATIVE
set_req "$FLOW" identity-provider-redirector ALTERNATIVE
set_req "$FLOW" "$SUB" ALTERNATIVE
set_req "$SUB" auth-username-password-form ALTERNATIVE
set_req "$SUB" webauthn-authenticator-passwordless ALTERNATIVE
# auth-spnego stays DISABLED.  Each PUT answers 204.

# 6. Read the whole tree back; level, position and requirement must match the table above
#    before binding (top level: auth-cookie, auth-spnego, identity-provider-redirector, forms).
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions" -H "$H" \
  | jq -r '.[] | "\(.level) \(.index) prio=\(.priority) \(.providerId // .displayName) \(.requirement)"'
```

## WebAuthn passwordless policy and realm SMTP

The passwordless policy is a **separate** block from the realm's second-factor WebAuthn policy.
Set it, and the realm's outgoing mail, with one read-modify-write of the realm:

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" \
  | jq '. + {
      webAuthnPolicyPasswordlessRpEntityName: "Acme Portal",
      webAuthnPolicyPasswordlessRpId: "localhost",
      webAuthnPolicyPasswordlessRequireResidentKey: "Yes",
      webAuthnPolicyPasswordlessUserVerificationRequirement: "preferred",
      smtpServer: {host: "<smtp-host>", port: "<smtp-port>", from: "<from-address>",
                   auth: "false", starttls: "false", ssl: "false"}
    }' \
  | curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" -H "$J" --data-binary @-
```

- **`rpId`**: hostname only, no scheme/port. Must match what browsers navigate to.
- **`requireResidentKey: "Yes"`**: required for passwordless/discoverable credentials.
- **`smtpServer`**: an existing user's first passkey usually arrives by an execute-actions email
  (below), and Keycloak refuses to send one without a sender: `500` *"No sender address configured
  in the realm settings for emails"*. Take host, port, sender and the auth/TLS flags from the
  mail server you were given; every value is a string. Skip it only when no user will be enrolled
  by email.

## Binding

```bash
# Realm-wide: browserFlow takes the flow's ALIAS
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" -H "$J" \
  -d '{"browserFlow":"Password-or-passkey"}'

# Or one client: authenticationFlowBindingOverrides (plural) takes the flow's ID, not its alias
FLOW_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  | jq -r --arg a "$FLOW" '.[] | select(.alias == $a) | .id')
CID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
  | jq --arg f "$FLOW_ID" '.authenticationFlowBindingOverrides.browser = $f' \
  | curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" -H "$J" --data-binary @-
```

## Verifying this actually works

No endpoint reports "password-or-passkey login is working". Configuration can look perfect and
still fail at the ceremony (a wrong `rpId` is the classic). **Both** methods have to be driven,
and one of them can't be driven by an HTTP client at all:

| Method | How to verify | Tooling |
|---|---|---|
| Password | Start an authorization-code login, POST username + password to the form's `action` URL, expect a `302` to `redirect_uri` carrying a `code` | Plain HTTP client |
| Passkey | Register via `webauthn-register-passwordless`, then log in through "Try another way" → the `#authenticateWebAuthnButton` control, expect the same `302` with a `code` — **without entering a password** | **Real browser required** |

A passkey ceremony is `navigator.credentials.create()` / `.get()` — actual client-side
JavaScript. Scripting it needs a headless browser with a **CDP virtual authenticator**
(`WebAuthn.enable` + `addVirtualAuthenticator`, e.g. Playwright); no HTTP client can fake the
crypto exchange. If no browser is available, report the passkey half as **unverified** rather
than inferring it from configuration.

The decisive check is that the two methods are **alternatives, not two factors**:

- A user with **no** passkey must complete login with the password alone. If the passkey step is
  `REQUIRED` (or the password form is), this flow is password-then-passkey 2FA, and this user is
  stuck after a correct password — the most likely wrong outcome here, and it looks entirely
  correct in the admin console.
- A user **with** a passkey must complete login without typing a password.
- A wrong password must still be rejected — no `code`, the form re-renders with an error. A
  passkey path does not make the password optional for users who choose it.

Also confirm the choice is actually offered: the login page should present the username/password
form *and* a "Try another way" control leading to the passkey option. If only one is reachable,
read the order and requirements back with `listFlowExecutions`; mixing `ALTERNATIVE` with
`REQUIRED` at the same level makes Keycloak ignore the alternatives (see
[`flow-execution-order.md`](flow-execution-order.md)).

Two client-side details that otherwise cost an afternoon:

- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Browsers send them
  over `http://localhost` anyway (loopback is a secure context); most HTTP client libraries will
  not, and every form POST then returns `400` *"Cookie not found."* Clear the flag on each
  response (`cookie.secure = False` in Python `requests`).
- A user who has completed a passkey registration and one who hasn't are shown different things
  by the same flow. Test both populations, or a check passes for one and fails for the other.

The passkey half needs a user who has a passkey. To give an existing user one, see
`admin:credential-enrollment`: a required action on the account (no mail involved) for a user who
can already sign in with a password, or an execute-actions email with
`webauthn-register-passwordless` — which needs the realm SMTP above:

```bash
UID_=$(curl -s "$BASE/admin/realms/$REALM/users?username=<username>&exact=true" -H "$H" | jq -r '.[0].id')
curl -s -o /dev/null -w '%{http_code}\n' -X PUT -H "$H" -H "$J" \
  "$BASE/admin/realms/$REALM/users/$UID_/execute-actions-email?client_id=<client-id>&redirect_uri=<url-encoded-redirect-uri>" \
  -d '["webauthn-register-passwordless"]'
# 204 = sent. The user completes the registration in a browser from the emailed link.
```
