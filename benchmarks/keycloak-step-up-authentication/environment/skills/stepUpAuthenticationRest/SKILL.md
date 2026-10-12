---
name: stepUpAuthenticationRest
description: >-
  step-up-authentication
---

# Step-up authentication with ACR → Level of Authentication (LoA), self-locking sessions — via raw Admin REST

## What this is, and what it isn't

One Keycloak session with **two trust levels** that expire separately:

| Level | Authentication | Session lifespan | Use case |
|---|---|---|---|
| **Level 1 (`silver`)** | Password only | Whole SSO session (10 h default) | General access |
| **Level 2 (`gold`)** | Password + one-time code | **5 minutes** | Sensitive actions (e.g., payments) |

A user with `silver` who opens a feature gated at `gold` gives **only the code**, not the password
again — the session upgrades to `gold` for 5 minutes, then drops back to `silver` without logging
out. This is the "self-locking session": the application stays usable but sensitive features lock.

The mechanism is Keycloak's stock **Conditional - Level Of Authentication** authenticator and **ACR
to LoA mapping**, no extension required. One client can be forced to `gold` even when the app
doesn't request it (using `minimum.acr.value`). Applications gate features on the `acr` claim in
the ID token, not on the request.

## Prerequisite: none

This uses stock Keycloak authenticators and realm configuration only.

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
```

## Stage 1 — Author the flow

The shape (verified live):

| Sub-flow | Execution | Requirement | Why it's here |
|---|---|---|---|
| top-level | `auth-cookie` | ALTERNATIVE | Resume an existing SSO session at its current level. |
| top-level | `identity-provider-redirector` | ALTERNATIVE | Federated login bypasses forms; not gated to a level. |
| top-level | *level forms sub-flow* | ALTERNATIVE | Taken when neither of the above applies. |
| forms | *Level 1 (silver) sub-flow* | ALTERNATIVE | ← **Lowest level first.** First login always starts at Level 1. |
| Level 1 | `auth-username-password-form` | REQUIRED | Collects and verifies the password. |
| Level 1 | `conditional-level-of-authentication` (condition) | REQUIRED | No code needed for Level 1; gate always passes, so password alone is acceptable. |
| forms | *Level 2 (gold) sub-flow* | ALTERNATIVE | ← Requested after Level 1, or never (if `minimum.acr.value` is `gold`). |
| Level 2 | `conditional-level-of-authentication` (condition) | REQUIRED | Code required for Level 2; fails if the user lacks a code or enters it wrong. |
| Level 2 | `auth-otp-form` | REQUIRED | Prompts for a code; only reached if the condition above passes. |

**The three critical points:**

1. **Levels are ordered lowest first.** The first (Level 1 / `silver`) sub-flow runs on every first
   login. It must hold only the minimal authenticators and the condition that gates it; a Level 2
   gating step first would break every first login.

2. **Each level's condition must be REQUIRED**, not CONDITIONAL, and must contain the
   `conditional-level-of-authentication` check. For Level 1, that check always passes (no code
   needed). For Level 2, it gates the OTP step.

3. **Levels are cumulative**: Level 2 includes everything Level 1 requires. A level that needs a
   *different* method (not a variant of the same password/code pair) is the "ACR to flow" client
   policy instead — out of scope here.

Stock Keycloak has no built-in flow with this shape, so author it manually with `POST`. Atomic
import is not available for steps — use it only for the realm config below (ACR → LoA mapping).

```bash
FLOW='step-up-flow'
LEVEL1_SUB='Step-up level 1 (silver)'
LEVEL2_SUB='Step-up level 2 (gold)'
FORMS_SUB='Step-up forms'

# Top-level flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

# Top-level: two ALTERNATIVE leaves (session resume, federation)
i=0
for p in auth-cookie identity-provider-redirector; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\",\"priority\":$i}"
  i=$((i+10))
done

# Top-level: forms sub-flow
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FORMS_SUB\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":20}"

# Forms sub-flow: Level 1 and Level 2 as ALTERNATIVE sub-flows
i=0
for level_alias in "$LEVEL1_SUB" "$LEVEL2_SUB"; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FORMS_SUB" '$f|@uri')/executions/flow" \
    -H "$H" -H 'Content-Type: application/json' \
    -d "{\"alias\":\"$level_alias\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":$i}"
  i=$((i+10))
done

# Level 1: password + level condition (condition gates with level=1)
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL1_SUB" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-username-password-form","priority":0}'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL1_SUB" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":10}'

# Level 2: level condition (gates to level=2) + OTP form
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL2_SUB" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":0}'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL2_SUB" '$f|@uri')/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-otp-form","priority":10}'

# Set requirements: shape must be all-ALTERNATIVE at top, all-REQUIRED/CONDITIONAL inside sub-flows.
# At the top level: auth-cookie, identity-provider-redirector, and forms sub-flow are ALTERNATIVE.
set_req() {  # <flow alias> <provider or sub-flow displayName> <requirement>
  F=$(jq -rn --arg f "$1" '$f|@uri')
  curl -s "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H" \
    | jq -c --arg k "$2" --arg r "$3" '.[] | select((.providerId // .displayName) == $k) | .requirement = $r' \
    | curl -s -o /dev/null -w "$2 -> $3: %{http_code}\n" -X PUT \
        "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H" \
        -H 'Content-Type: application/json' --data-binary @-
}

# Top level: all ALTERNATIVE
set_req "$FLOW" auth-cookie ALTERNATIVE
set_req "$FLOW" identity-provider-redirector ALTERNATIVE
set_req "$FLOW" "$FORMS_SUB" ALTERNATIVE

# Forms: all ALTERNATIVE (both level sub-flows)
set_req "$FORMS_SUB" "$LEVEL1_SUB" ALTERNATIVE
set_req "$FORMS_SUB" "$LEVEL2_SUB" ALTERNATIVE

# Level 1: all REQUIRED
set_req "$LEVEL1_SUB" auth-username-password-form REQUIRED
set_req "$LEVEL1_SUB" conditional-level-of-authentication REQUIRED

# Level 2: all REQUIRED
set_req "$LEVEL2_SUB" conditional-level-of-authentication REQUIRED
set_req "$LEVEL2_SUB" auth-otp-form REQUIRED
```

Verify the order:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$FLOW" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

Expected output (indices 0–8):

```
0 lvl=0 pri=0 ALTERNATIVE auth-cookie
1 lvl=0 pri=10 ALTERNATIVE identity-provider-redirector
2 lvl=0 pri=20 ALTERNATIVE Step-up forms
3 lvl=1 pri=0 ALTERNATIVE Step-up level 1 (silver)
4 lvl=2 pri=0 REQUIRED auth-username-password-form
5 lvl=2 pri=10 REQUIRED conditional-level-of-authentication
6 lvl=1 pri=10 ALTERNATIVE Step-up level 2 (gold)
7 lvl=2 pri=0 REQUIRED conditional-level-of-authentication
8 lvl=2 pri=10 REQUIRED auth-otp-form
```

## Stage 2 — Attach level conditions and their parameters

Each `conditional-level-of-authentication` execution needs config specifying which level it gates.

```bash
# Level 1 condition: loa-condition-level = 1 (no time limit for the password level itself, but
# loa-max-age gates stepping up to Level 2, defaulting to 36000 s = 10 h).
LEVEL1_COND_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL1_SUB" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | select(.providerId == "conditional-level-of-authentication") | .id')
curl -s -o /dev/null -w 'Level 1 condition config: %{http_code}\n' -X POST "$BASE/admin/realms/$REALM/authentication/executions/$LEVEL1_COND_ID/config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"level1-condition","config":{"loa-condition-level":"1","loa-max-age":"36000"}}'

# Level 2 condition: loa-condition-level = 2, loa-max-age = 300 (5 minutes self-lock).
LEVEL2_COND_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(jq -rn --arg f "$LEVEL2_SUB" '$f|@uri')/executions" -H "$H" \
  | jq -r '.[] | select(.providerId == "conditional-level-of-authentication") | .id')
curl -s -o /dev/null -w 'Level 2 condition config: %{http_code}\n' -X POST "$BASE/admin/realms/$REALM/authentication/executions/$LEVEL2_COND_ID/config" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"alias":"level2-condition","config":{"loa-condition-level":"2","loa-max-age":"300"}}'
```

Both return HTTP 201.

## Stage 3 — ACR to LoA mapping

Map realm-level ACR names to numeric levels. This is where `silver` → 1 and `gold` → 2 come from.

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" \
  | jq '.["acr.loa.map"] = {"silver":1,"gold":2}' \
  | curl -s -o /dev/null -w 'acr.loa.map: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
      -H 'Content-Type: application/json' --data-binary @-
```

Returns HTTP 204.

A client can override with the same attribute; most deployments leave it on the realm.

## Stage 4 — Bind it

```bash
# Realm-wide: browserFlow takes the flow's ALIAS.
curl -s -o /dev/null -w 'realm: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
  -H 'Content-Type: application/json' -d "{\"browserFlow\":\"$FLOW\"}"

# OR one client: authenticationFlowBindingOverrides.browser takes the flow's ID, not its alias.
FLOW_ID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  | jq -r --arg a "$FLOW" '.[] | select(.alias == $a) | .id')
CID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
  | jq --arg f "$FLOW_ID" '.authenticationFlowBindingOverrides.browser = $f' \
  | curl -s -o /dev/null -w 'client: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$CID" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
```

Ask which the user wants — realm-wide affects every client, including admin and account consoles.

## Stage 5 — Enforce Level 2 on a specific client (optional)

If one client must **always** get Level 2 even when the app doesn't request it (e.g., a payments
gateway), bind `minimum.acr.value`:

```bash
CID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=acme-payments" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
  | jq '.attributes.["minimum.acr.value"] = "gold"' \
  | curl -s -o /dev/null -w 'minimum.acr.value: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$CID" \
      -H "$H" -H 'Content-Type: application/json' --data-binary @-
```

Returns HTTP 204. This client now always gets `gold`; the app still sees `acr` in the token to act on.

## Stage 6 — Behaviors worth knowing

- **Expiry is lazy.** A level is re-checked only on the next authentication request; tokens already
  issued at `gold` stay valid until they expire naturally (usually 5 minutes for access tokens). The
  realm's access-token lifespan must be ≤ 300 s (Level 2's `loa-max-age`), which is already true by
  default on most deployments.

- **`loa-max-age` `0`** (not used here, but documented for variants) means "this authentication
  only": every request for the level prompts again, giving a payment-confirmation style flow.

- **A level that expired, with no level requested**: SSO still lets the user in, but `acr` is `0`
  (cookie-only). Applications must handle `acr` `0` as "re-authenticate to unlock features".

- **An essential `acr` that is unmapped or above every configured level is an error**, not a
  downgrade. The app saying `claims={"id_token":{"acr":{"essential":true,"values":["platinum"]}}}` where
  only `silver` and `gold` are mapped → Keycloak returns an error.

- **`acr_values` and `default.acr.values` can be rewritten by the user in the browser.** Only
  `minimum.acr.value` on the client, or the app checking `acr` in the token, enforces a level.

- **The realm's default `acr` client scope (with the `oidc-acr-mapper`) already delivers the `acr`
  claim** in the ID token — no extra mapper needed.

## Stage 7 — Verify by logging in, not by reading configuration

1. **No `acr` requested** → password only → ID token `acr` is `silver`.
2. **Same browser session, then `claims` asking for `gold` (essential)** → **only** the code form,
   no password form → enter the code → ID token `acr` is `gold`.
3. **`gold` again straight away** → no prompt (inside the 5 minutes) → `acr` `gold`.
4. **A fresh browser asking for `gold`** → password, then code → `gold`.
5. **A wrong code at the level-2 step** → no authorization code (authentication failed).
6. **`minimum.acr.value` set to `gold` on a client**, no `acr` requested → the code is demanded
   anyway.
7. **An essential `acr` of `platinum` (unmapped)** → an error, not a login.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| First login always prompts for a code | Level 2 (the code sub-flow) is before Level 1, or Level 1's condition is not the right one |
| A fresh browser asking for `gold` does not show the password form first | The Level 1 sub-flow is after Level 2, or missing entirely |
| All users see the code form every login, even without asking for it | `minimum.acr.value` is set on the realm or a client when it shouldn't be |
| Level 2 code is demanded but there's no way to provide one | The realm has no OTP policy or the user has no OTP credential configured — or the Level 2 sub-flow condition is looking for the wrong level number |
| Code prompt keeps appearing even after a correct code | The level condition's `loa-max-age` is `0` (every login re-prompts) or expires very quickly — or no `acr.loa.map` is configured |
| `acr` never appears in the ID token | The realm's default `acr` client scope or its `oidc-acr-mapper` is missing/disabled |
