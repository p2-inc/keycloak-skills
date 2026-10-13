<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Step-up authentication with two trust levels — via raw Admin REST

## What this is, and what it isn't

One Keycloak session with two trust levels that expire **separately**:

- **Level 1 (`silver`)**: password-only, valid for the whole SSO session (typically 10 hours).
  Ordinary login and app browsing.
- **Level 2 (`gold`)**: password + one-time code (or another factor), valid for **5 minutes**, then
  the user drops back to `silver` without being logged out. Sensitive operations like payments.

A user already at `silver` who asks for `gold` gives **only the code**, not the password again.
One client can enforce `gold` always (`minimum.acr.value`); others ask per-request. This is
**not** a flat "every login is 2FA" policy (`admin:totp-second-factor`) and not an access-control
gate by organization (`admin:org-restrict-login` — step-up is about *trust*, not *who can log in*).

Verified against Keycloak 26, the stock browser flow's conditional structure, and the Server
Administration Guide sections on "Creating a browser login flow with step-up mechanism" and "ACR
to Level of Authentication (LoA) Mapping".

## Tools this skill drives (raw Admin REST)

| Purpose | Endpoint |
|---|---|
| Identify caller | `GET /master/protocol/openid-connect/token` (mint `$ADMIN_TOKEN` from admin-cli) |
| Confirm the realm exists | `GET /admin/realms/{realm}` |
| List existing flows | `GET /admin/realms/{realm}/authentication/flows` |
| Create a top-level flow | `POST /admin/realms/{realm}/authentication/flows` |
| Create a sub-flow under a flow | `POST /admin/realms/{realm}/authentication/flows/{flow}/executions/flow` |
| Add an authenticator to a flow | `POST /admin/realms/{realm}/authentication/flows/{flow}/executions/execution` |
| List the flow's executions and their order | `GET /admin/realms/{realm}/authentication/flows/{flow}/executions` |
| Set an execution's requirement | `PUT /admin/realms/{realm}/authentication/flows/{flow}/executions` |
| Attach config to an execution | `POST /admin/realms/{realm}/authentication/executions/{id}/config` |
| Bind the flow realm-wide | `PUT /admin/realms/{realm}` (set `browserFlow` to the flow alias) |
| Bind to one client | `PUT /admin/realms/{realm}/clients/{id}` (set `authenticationFlowBindingOverrides.browser` to the flow ID) |
| Configure outgoing mail | `PUT /admin/realms/{realm}` (set `smtpServer`) |
| Realm ACR → LoA map | `PUT /admin/realms/{realm}` (set `attributes.acr.loa.map`) |
| Client enforcement | `PUT /admin/realms/{realm}/clients/{id}` (set `attributes.minimum.acr.value`) |
| Set OTP policy | `PUT /admin/realms/{realm}` (set `otpPolicy`) |

## Prerequisite: stock Keycloak, no extension required

The flow uses only stock authenticators: `auth-cookie`, `auth-username-password-form`,
`auth-otp-form`, and `conditional-level-of-authentication`. No extension or custom jar is needed.

## Stage 1 — Mint an admin token and target the realm

```bash
BASE=http://localhost:8080/auth
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>

# Confirm the realm exists and collect current state for later modification
curl -s "$BASE/admin/realms/$REALM" -H "$H" | jq -c '{id, name}'
```

```bash
REALM_DATA=$(curl -s "$BASE/admin/realms/$REALM" -H "$H")
echo "$REALM_DATA" \
  | jq '.attributes."acr.loa.map" = {"silver":"1","gold":"2"}' \
  | curl -s -o /dev/null -w 'realm acr map: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
# 204 = success
```

This preserves all existing realm attributes and only modifies the ACR map.

## Stage 3 — Author the step-up flow

The shape, **verified live**:

| Level | Sub-flow | Execution | Requirement | Why |
|---|---|---|---|---|
| — | top-level | `auth-cookie` | ALTERNATIVE | An existing SSO session still works. |
| — | top-level | *Level sub-flow* | ALTERNATIVE | Entered for step-up requests or first login. |
| Level 1 | Level 1 sub-flow | Conditional - LoA (level 1) | REQUIRED | Gateway: runs *only* if current LoA < 1. |
| Level 1 | Level 1 sub-flow | `auth-username-password-form` | REQUIRED | Password authenticator for level 1. |
| Level 2 | Level 2 sub-flow | Conditional - LoA (level 2) | REQUIRED | Gateway: runs *only* if current LoA < 2. |
| Level 2 | Level 2 sub-flow | `auth-otp-form` | REQUIRED | OTP form (user already authed at level 1 gets only the code form). |

**The levels must be ordered lowest-first**. Level 1 must run before level 2, otherwise level 2 is
demanded on every first login.

```bash
FLOW='step-up-flow'

# 1. Create the top-level flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

# 2. Add auth-cookie at top level, priority 0 (the first alternative path)
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-cookie","priority":0}'

# 3. Create level 1 sub-flow, priority 1
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"Level 1","provider":"basic-flow","type":"basic-flow","priority":1}'

# 4. Create level 2 sub-flow, priority 2 (MUST come after level 1)
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"Level 2","provider":"basic-flow","type":"basic-flow","priority":2}'

# 5. Add conditional + password to level 1 sub-flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 1" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":0}'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 1" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-username-password-form","priority":1}'

# 6. Add conditional + OTP to level 2 sub-flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 2" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":0}'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 2" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-otp-form","priority":1}'

# 7. Set requirements
set_req() {
  F=$(jq -rn --arg f "$1" '$f|@uri')
  EXECS=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H")
  echo "$EXECS" \
    | jq --arg k "$2" --arg r "$3" '(.[] | select((.providerId // .displayName) == $k) | .requirement) = $r' \
    | curl -s -o /dev/null -w "$2 -> $3: %{http_code}\n" -X PUT \
        "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H" \
        -H 'Content-Type: application/json' --data-binary @-
}
set_req "$FLOW" auth-cookie ALTERNATIVE
set_req "$FLOW" "Level 1" ALTERNATIVE
set_req "$FLOW" "Level 2" ALTERNATIVE
set_req "Level 1" conditional-level-of-authentication REQUIRED
set_req "Level 1" auth-username-password-form REQUIRED
set_req "Level 2" conditional-level-of-authentication REQUIRED
set_req "Level 2" auth-otp-form REQUIRED
# Each PUT should answer 204.

# 8. Attach config to the level 1 conditional execution
L1_COND_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 1" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | select(.providerId == "conditional-level-of-authentication") | .id')
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/$L1_COND_ID/config" -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"alias":"level-1-config","config":{"loa-condition-level":"1","loa-max-age":"36000"}}'
# 201 = attached

# 9. Attach config to the level 2 conditional execution
L2_COND_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 2" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | select(.providerId == "conditional-level-of-authentication") | .id')
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/executions/$L2_COND_ID/config" -H "$H" \
  -H 'Content-Type: application/json' \
  -d '{"alias":"level-2-config","config":{"loa-condition-level":"2","loa-max-age":"300"}}'
# 201 = attached

# 10. Verify the order
echo "=== Flow order (should be: auth-cookie, Level 1, Level 2) ==="
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

### Why the order is load-bearing

**The flow's first level sub-flow *always runs on a first login***, whatever trust level was
requested. If level 2 runs first, every new user must give an OTP before seeing the password form —
they have no password on file yet, and the flow hangs. Lowest level first ensures the minimal
authenticators run first.

### Why each execution's `priority` matters

`executions/execution` and `executions/flow` **append** when no `priority` is passed. Without it,
calls build the flow in call order, not in intended order, and a sub-flow created before the
top-level leaves may land *first*. Pass `priority` on every add, then read the order back to verify
(see step 10 above).

On Keycloak 25+, `priority` in the body is honoured. On 24 and older, it is ignored; use
`POST .../authentication/executions/<exec-id>/raise-priority` and
`POST .../authentication/executions/<exec-id>/lower-priority` to re-order after creation.

## Stage 4 — Realm mail settings and OTP policy

The level-2 OTP form needs SMTP (to mail a code) and the realm's OTP policy (for code generation).

```bash
# Read the current realm, add/modify mail and OTP settings, and write back.
# (A PUT that omits fields resets them — always read-modify-write.)
curl -s "$BASE/admin/realms/$REALM" -H "$H" \
  | jq '.smtpServer = {host: "<smtp-host>", port: "<smtp-port>", from: "<from-address>",
                       auth: "false", starttls: "false", ssl: "false"} |
       .otpPolicy = {type: "totp", algorithm: "HmacSHA1", digits: 6, period: 30, 
                     activated: true, codeReusable: false}' \
  | curl -s -o /dev/null -w 'realm smtp+otp: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
# 204 = success
```

Update the SMTP values to match your server. `codeReusable: false` means a code can be used only once
in the 30-second window; this is correct for a one-time code system.

## Stage 5 — Bind the flow realm-wide or to a specific client

**Realm-wide**: affects all clients including admin and account consoles.

```bash
curl -s -o /dev/null -w 'realm binding: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' -d "{\"browserFlow\":\"$FLOW\"}"
# 204 = success
```

**One client**: find the client's ID and flow ID, then bind.

```bash
FLOW_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  | jq -r --arg a "$FLOW" '.[] | select(.alias == $a) | .id')
CLIENT_ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" \
  | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CLIENT_ID" -H "$H" \
  | jq --arg f "$FLOW_ID" '.authenticationFlowBindingOverrides.browser = $f' \
  | curl -s -o /dev/null -w 'client binding: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$CLIENT_ID" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
# 204 = success
```

## Stage 6 — Enforce step-up on a sensitive client (optional)

To require users accessing a client like `acme-payments` to always be at level 2:

```bash
PAYMENTS_CLIENT=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=acme-payments" -H "$H" \
  | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$PAYMENTS_CLIENT" -H "$H" \
  | jq '.attributes."minimum.acr.value" = "gold"' \
  | curl -s -o /dev/null -w 'client enforcement: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$PAYMENTS_CLIENT" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
# 204 = success
```

This value `gold` must match a key in the ACR map from Stage 2.

## Application side: requesting a level and checking the token

### Asking for a level in a browser redirect

**Essential claim** (Keycloak returns `gold` or fails):

```
claims={"id_token":{"acr":{"essential":true,"values":["gold"]}}}
```

**Non-essential** (Keycloak tries `gold` but accepts lower if needed):

```
acr_values=gold
```

Both can be tampered with in the browser. To enforce `gold`, rely on `minimum.acr.value` in the
client (Stage 6) or check the ID token's `acr` claim (below).

### Checking the ID token

The token includes an `acr` claim with the user's current level:

```js
// keycloak-js
if (kc.tokenParsed?.acr !== 'gold') {
  // Not at level 2; offer step-up
  kc.login({ acr: { values: ['gold'], essential: true } });
} else {
  // Safe to proceed with the sensitive operation
}
```

For an `acr` of `0` (SSO session, no LoA checked, e.g., after a level-2 token expired), the user is
still logged in but the level is unknown. Applications should handle this like a missing `acr`.

## Behaviors worth knowing

1. **Levels are cumulative.** A user at level 2 automatically satisfies level 1. The condition at
   level 1 checks `current LoA < 1` and skips itself if already satisfied.

2. **Expiry is lazy.** A level is re-checked only when the next authentication request arrives.
   Tokens already issued at level 2 remain valid until they expire naturally (the token's
   `exp` timestamp). To force re-authentication, the application must request a new token (e.g.,
   via a login call or refresh).

3. **An access-token lifespan ≤ level-2 expiry is important.** If `loa-max-age` is 300 seconds
   (level 2's lock time) but the access token lasts 1 hour, a token issued at level 2 will remain
   valid for an hour even after the user drops back to level 1 after 5 minutes. Set the realm's
   access-token lifespan to match or be less than the level's `loa-max-age`. The default realm
   settings already have this right (access token ~5 min, level 2 = 300 s).

4. **`loa-max-age` of `0` means "every request."** Used for payments-style confirmation: every
   request for level 2 prompts for the code again, no caching. A `loa-max-age` of `300` gives
   the self-locking session (5-minute window, then back to level 1).

5. **An unmapped or too-high ACR is an error.** If the app asks for `acr=platinum` and the realm
   has no `platinum` key in its ACR map, Keycloak returns an error, not a downgrade to a lower
   level. Same if the requested ACR value is above every configured level.

6. **A level-2 timeout with no request for a level**: the user is still logged in at level 1
   (the `auth-cookie` path succeeds on the next request). `acr` becomes `0` (SSO session, no LoA
   checked). Applications must handle `acr` of `0` or `null` explicitly, not assume they are the
   same as level 1.

## Variant: different level-2 authenticator

The reference uses `auth-otp-form`, the stock OTP form. Some organizations prefer a PIN code from
a third-party authenticator. Use the same flow shape and order, but substitute the level-2
authenticator. Set the `provider` field to your authenticator's ID (e.g., `pin-code-authenticator`
for the please-openit PIN Code Authenticator):

```bash
# Example: replace auth-otp-form with a PIN code authenticator
# Change "pin-code-authenticator" to your provider's ID
LEVEL2_PROVIDER="pin-code-authenticator"
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "Level 2" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"provider\":\"$LEVEL2_PROVIDER\",\"priority\":1}"
```

The shape and order remain the same; only the authenticator changes.

## Verifying this actually works

Testing over HTTP, authorization-code flow against your client (or the default `admin-cli` for
test):

1. **No ACR requested** → password-only login → ID token has `"acr":"silver"`.

2. **Same browser, then ask for `gold` with essential claim** → the form shows **only** the OTP
   field (no password) → submit the OTP code → ID token has `"acr":"gold"`.

3. **Request `gold` again immediately** → no prompt (inside the 5 minutes) → redirects to the
   client → same ID token with `"acr":"gold"`.

4. **Fresh browser, ask for `gold`** → password form, then OTP form (user has no session yet) →
   OTP code → `"acr":"gold"`.

5. **Wrong OTP code at level 2** → rejected, no authorization code.

6. **Client has `minimum.acr.value=gold`**, no ACR requested in the redirect → login flow still
   demands the OTP (enforced by `minimum.acr.value`, not by the user's request).

7. **Ask for unmapped ACR** (e.g., `acr_values=platinum` when only `silver` and `gold` are
   mapped) → error, not a downgrade.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Level 2 is demanded on every first login | Level 2 runs before level 1 in the flow (order is wrong) | Verify flow order: `GET .../authentication/flows/{flow}/executions`, confirm `Level 1` has a lower `priority` than `Level 2` |
| User at level 1 sees the password form when asking for level 2 | The condition's `loa-max-age` config is missing or wrong, or the level was set as ALTERNATIVE instead of REQUIRED | Verify level 1 and 2 sub-flows are REQUIRED; level 1/2 conditionals are REQUIRED; conditionals have config with `loa-condition-level` and `loa-max-age` |
| OTP code never arrives | Realm SMTP unconfigured; `smtpServer` is missing `host`, `port`, or `from` | Verify SMTP settings: `GET /admin/realms/{realm}` and check `smtpServer` |
| Client says `acr=0` or `null` after logging in | User logged in via `auth-cookie` (existing SSO session) with no LoA check | This is correct behavior: an SSO cookie has no LoA. Application must handle `acr: null` / `"0"` like a missing level, not assume it equals level 1 |
| `minimum.acr.value` doesn't enforce level 2 on a client | The attribute name is wrong or the flow binding is missing | Verify the client has the flow bound to `browser`, and has attribute `minimum.acr.value` set to `gold` (or whichever ACR value maps to level 2) |

## Additional resources

- [Keycloak Server Administration Guide: Creating a browser login flow with step-up
  mechanism](https://www.keycloak.org/docs/latest/server_admin/index.html#_step-up-flow)
- [Keycloak Server Administration Guide: ACR to Level of Authentication
  (LoA) Mapping](https://www.keycloak.org/docs/latest/server_admin/index.html#_mapping-acr-to-loa-realm)
- [Janua: Self-locking sessions in Keycloak with PIN step-up
  authentication](https://www.janua.fr/self-locking-sessions-in-keycloak-with-pin-step-up-authentication/)
