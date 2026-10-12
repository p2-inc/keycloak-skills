---
name: totpSecondFactorRest
description: >-
  Require TOTP from an authenticator app as a second factor after the password, for every
  user, via raw Admin REST. Use whenever someone wants "2FA with an authenticator app", "TOTP", "Google
  Authenticator codes after the password", or MFA that every account must use. Covers
  authoring and binding a flow whose forms sub-flow makes auth-username-password-form and
  auth-otp-form both REQUIRED (and why the stock browser flow's conditional OTP lets users
  without an authenticator in), the realm OTP policy, CONFIGURE_TOTP enrolment, and verifying
  logins with codes computed from the enrolment secret. Not email OTP
  (admin:password-email-otp-mfa) and not passkeys.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# admin:totp-second-factor (REST)

Password login hardened with a TOTP code from an authenticator app as a **second factor**, for
**every** user.

This is **not passwordless**: the password remains required and gates the TOTP step. A wrong
password never reaches the code form. A user without an authenticator is sent through
`CONFIGURE_TOTP` enrolment straight after their password, and cannot finish logging in without
completing it.

Compared to `admin:password-email-otp-mfa`, this uses:
- `auth-otp-form` (stock Keycloak) instead of `ext-email-otp` (p2-inc extension)
- No SMTP: the secret is shown on screen during enrolment
- The realm OTP policy for the algorithm, digits and period

```bash
BASE=http://localhost:8080/auth
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
J='Content-Type: application/json'
REALM=<realm>
FLOW='totp-second-factor'
SUB='totp-second-factor forms'
q() { jq -rn --arg f "$1" '$f|@uri'; }
```

## Why the stock browser flow is not enough

Keycloak's built-in `browser` flow already contains an OTP step, but inside a **CONDITIONAL**
sub-flow (`condition-user-configured` + `auth-otp-form`): it asks for a code only from users who
**already have** an OTP credential. Everyone else logs in with the password alone. Enabling
`CONFIGURE_TOTP` does not change that. "Every user must use TOTP" needs a flow in which
`auth-otp-form` is **REQUIRED**, unconditionally.

## The flow shape

| Flow | Execution | Requirement | Priority |
|---|---|---|---|
| `totp-second-factor` (top level) | `auth-cookie` | ALTERNATIVE | 0 |
| | `identity-provider-redirector` | ALTERNATIVE | 1 |
| | *forms sub-flow* | ALTERNATIVE | 2 |
| *forms sub-flow* | `auth-username-password-form` | REQUIRED | 0 |
| | `auth-otp-form` | REQUIRED | 1 |

- `auth-cookie` first keeps single sign-on: a user with a live session is not asked again.
- The password and the code are **REQUIRED siblings inside their own sub-flow**. Putting them
  next to `auth-cookie` at the top level mixes REQUIRED with ALTERNATIVE, and Keycloak then
  ignores the alternatives (see [`flow-execution-order.md`](flow-execution-order.md)).
- `auth-otp-form` comes after the password, so a wrong password never reaches it.

## Stage 1 — Check no matching flow exists

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" | jq -r '.[].alias'
```

## Stage 2 — Author the flow

### Option A: atomic import (only with the extension)

`POST /admin/realms/{realm}/authentication-flow/import?force={bool}` exists only with the p2-inc
[keycloak-atomic-auth-flows](https://github.com/p2-inc/keycloak-atomic-auth-flows) extension. It
authors the flow and applies the binding in one call. A `404` means the extension is not
installed: use Option B.

```bash
cat > /tmp/totp-second-factor.json << 'EOF'
{
  "authenticationFlows": [
    {
      "alias": "totp-second-factor",
      "description": "Password, then a TOTP code from an authenticator app.",
      "providerId": "basic-flow", "topLevel": true, "builtIn": false,
      "authenticationExecutions": [
        {"authenticator": "auth-cookie", "authenticatorFlow": false,
         "requirement": "ALTERNATIVE", "priority": 0, "userSetupAllowed": false},
        {"authenticator": "identity-provider-redirector", "authenticatorFlow": false,
         "requirement": "ALTERNATIVE", "priority": 1, "userSetupAllowed": false},
        {"authenticatorFlow": true, "flowAlias": "totp-second-factor forms",
         "requirement": "ALTERNATIVE", "priority": 2, "userSetupAllowed": false}
      ]
    },
    {
      "alias": "totp-second-factor forms",
      "description": "Password, then a TOTP code.",
      "providerId": "basic-flow", "topLevel": false, "builtIn": false,
      "authenticationExecutions": [
        {"authenticator": "auth-username-password-form", "authenticatorFlow": false,
         "requirement": "REQUIRED", "priority": 0, "userSetupAllowed": false},
        {"authenticator": "auth-otp-form", "authenticatorFlow": false,
         "requirement": "REQUIRED", "priority": 1, "userSetupAllowed": false}
      ]
    }
  ],
  "browserFlowBinding": "totp-second-factor"
}
EOF
curl -s -X POST "$BASE/admin/realms/$REALM/authentication-flow/import?force=false" \
  -H "$H" -H "$J" --data-binary @/tmp/totp-second-factor.json
```

- `browserFlowBinding` binds the flow realm-wide. For one client instead, replace it with
  `"clientFlowBinding": {"clientId": "<client-id>", "browserFlowBinding": "totp-second-factor"}`.
- The extension prefixes every alias with a generated hash. Read the real alias from the
  response; don't assume the one you sent.
- Importing identical content again returns `409`. Pass `force=true` to replace it in place.

### Option B: manual authoring (stock Keycloak)

```bash
# 1. Top-level flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" -H "$J" \
  -d '{"alias":"totp-second-factor","description":"Password, then a TOTP code","providerId":"basic-flow","topLevel":true,"builtIn":false}'

# 2. Leaves of the top-level flow. The add call APPENDS unless priority is sent.
for p in auth-cookie:0 identity-provider-redirector:1; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions/execution" -H "$H" -H "$J" \
    -d "{\"provider\":\"${p%%:*}\",\"priority\":${p##*:}}"
done

# 3. The forms sub-flow is created AS an execution of the parent, in one call. Do NOT create
#    it first with POST /authentication/flows: that makes a second, top-level flow with the
#    same alias, this call then answers 409 Conflict, and the orphan stays behind.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions/flow" -H "$H" -H "$J" \
  -d '{"alias":"totp-second-factor forms","description":"Password, then a TOTP code","provider":"basic-flow","type":"basic-flow","priority":2}'

# 4. Leaves of the forms sub-flow: the password first, then the code.
for p in auth-username-password-form:0 auth-otp-form:1; do
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
set_req "$SUB" auth-username-password-form REQUIRED
set_req "$SUB" auth-otp-form REQUIRED
# Each PUT answers 204.

# 6. Read the whole tree back; level, position and requirement must match the table above.
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(q "$FLOW")/executions" -H "$H" \
  | jq -r '.[] | "\(.level) \(.index) prio=\(.priority) \(.providerId // .displayName) \(.requirement)"'
```

## Stage 3 — Configure the realm OTP policy

One read-modify-write of the realm:

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" \
  | jq '. + {otpPolicyType: "totp", otpPolicyAlgorithm: "HmacSHA1", otpPolicyDigits: 6,
             otpPolicyPeriod: 30, otpPolicyLookAheadWindow: 1}' \
  | curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" -H "$J" --data-binary @-
```

`otpPolicyLookAheadWindow: 1` also accepts the code from the period on either side of the
current one, which tolerates small clock skew. By default a code cannot be used twice
(`otpPolicyCodeReusable: false`).

## Stage 4 — Make sure `CONFIGURE_TOTP` is enabled

`CONFIGURE_TOTP` is the enrolment screen a user without an authenticator is sent to. It is
registered and enabled in a new realm, but check, and enable it if needed with a
read-modify-write that keeps its other fields:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/required-actions/CONFIGURE_TOTP" -H "$H" \
  | jq '.enabled = true' \
  | curl -s -o /dev/null -w '%{http_code}\n' -X PUT \
      "$BASE/admin/realms/$REALM/authentication/required-actions/CONFIGURE_TOTP" -H "$H" -H "$J" --data-binary @-
```

## Stage 5 — Bind the flow (Option B only)

```bash
# Realm-wide: browserFlow takes the flow's ALIAS
curl -s -X PUT "$BASE/admin/realms/$REALM" -H "$H" -H "$J" -d '{"browserFlow":"totp-second-factor"}'

# Or one client: authenticationFlowBindingOverrides takes the flow's ID, not its alias
FLOW_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  | jq -r --arg a "$FLOW" '.[] | select(.alias == $a) | .id')
CID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
  | jq --arg f "$FLOW_ID" '.authenticationFlowBindingOverrides.browser = $f' \
  | curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" -H "$J" --data-binary @-
```

## Stage 6 — Verify by logging in, not by reading configuration

| Scenario | Expected result |
|---|---|
| Correct password, user has an authenticator | The code form, not a login |
| Correct password + correct code | `302` to `redirect_uri` with a `code` and the original `state` |
| Correct password + wrong code | Rejected at the code form; no `code` |
| Wrong password | Rejected at the password form; the code form never appears |
| Correct password, user has **no** authenticator | The enrolment screen, not a login. Completing it with a valid first code logs the user in and leaves an `otp` credential on the account. **This is the decisive check**: the stock flow lets this user straight in. |

All of it can be driven with a plain HTTP client. What the pages contain (Keycloak 26):

- **Code form:** `data-page-id="login-login-otp"`, form `kc-otp-login-form`, code field `otp`.
- **Enrolment screen:** `data-page-id="login-login-config-totp"`, form `kc-totp-settings-form`.
  It holds the secret in a hidden field `totpSecret`. Submit `totp` (the first code),
  `totpSecret` (sent back unchanged) and optionally `userLabel`.
- **Computing a code:** the TOTP key is the **UTF-8 bytes of `totpSecret`** as it appears in the
  hidden field. The key behind the page's "Unable to scan?" link (`mode=manual`, element
  `kc-totp-secret-key`, in groups of four) is the base32 encoding of those same bytes, and so is
  the `secret=` the QR code carries. Don't base32-decode `totpSecret` itself.

  ```python
  import hashlib, hmac, struct, time
  def totp(secret, digits=6, period=30):
      digest = hmac.new(secret.encode(), struct.pack(">Q", int(time.time()) // period), hashlib.sha1).digest()
      offset = digest[-1] & 0x0F
      return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)
  ```

- Because a code can't be reused, wait for the next 30-second period between two logins by the
  same user.
- Keycloak sets `AUTH_SESSION_ID` and `KC_RESTART` as `Secure; SameSite=None`. Most HTTP client
  libraries will not send them over `http://localhost`, and every form POST then returns `400`
  *"Cookie not found."* Clear the flag on each response (`cookie.secure = False` in Python
  `requests`).
- To test, don't reset a real user's password. If you don't have it, use a throwaway test user.

## Common errors

- **A user without an authenticator logs in with the password alone:** the stock `browser`
  flow (conditional OTP) is still bound, or `auth-otp-form` is CONDITIONAL or ALTERNATIVE
  rather than REQUIRED.
- **The code form appears before the password, or a wrong password reaches it:** the
  sub-flow's priorities are reversed. Read the tree back (Stage 2, step 6).
- **A valid code is rejected:** clock skew; the code was already used once this period; or it
  was computed from a base32-decoded `totpSecret`.
- **`409` adding the sub-flow:** a flow with that alias already exists, usually an orphan
  from creating it with `POST /authentication/flows`. Delete it and add the sub-flow with
  `executions/flow`.
- **A `PUT` on `executions/{id}` fails:** requirements are set with `PUT` on the
  `executions` collection (Stage 2, step 5).

## Key differences from email-OTP MFA

| Aspect | Email OTP (`admin:password-email-otp-mfa`) | TOTP (`admin:totp-second-factor`) |
|---|---|---|
| Second factor | `ext-email-otp` (p2-inc extension) | `auth-otp-form` (stock Keycloak) |
| SMTP required | Yes | No |
| Code delivery | Email sent after the password | Generated by the user's authenticator app |
| Enrolment | None: the code goes to the account's email | `CONFIGURE_TOTP` required action |
