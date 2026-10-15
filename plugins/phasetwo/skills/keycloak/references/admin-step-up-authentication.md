<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Step-up authentication: ACR → LoA, self-locking sessions — via raw Admin REST

## What this is, and what it isn't

One Keycloak session, **two trust levels that expire separately**:

| Level | ACR | Authenticators | Lasts |
|---|---|---|---|
| 1 | `silver` | `auth-username-password-form` | the whole SSO session (10 h) |
| 2 | `gold` | password (already satisfied) + `auth-otp-form` | 5 minutes, then drops back to `silver` **without logging the user out** |

This is **not** `admin:password-email-otp-mfa` or `admin:totp-second-factor`: those make *every*
login two-factor, with no levels, and nothing ever expires back to a weaker state. Here, ordinary
use never sees the second factor; only a request that explicitly asks for `gold` does, and a user
who already holds `silver` is asked for **only the code** — the password step is satisfied already
and is never repeated. Dropping from `gold` back to `silver` after 5 minutes is the Janua article's
"self-locking session": the session locks itself back down without any logout.

See [`flow-execution-order.md`](flow-execution-order.md) before authoring — this flow's two levels
are CONDITIONAL sub-flows, and **order inside the level sub-flow is load-bearing**: level 1 must be
first, or the engine demands level 2 on every first login regardless of what was asked for.

## The authenticator: `conditional-level-of-authentication`

Stock Keycloak (no extension), provider id `conditional-level-of-authentication`, display name
"Condition - Level Of Authentication". Config keys:

- `loa-condition-level` — the level (an integer: `1`, `2`, …) this condition tests for.
- `loa-max-age` — seconds; if the current session's ACR was established within this many seconds,
  the condition is already satisfied and the level's own steps are skipped. Default `36000` (10h).
  `0` means "always re-prompt" (a payments-style confirmation every time).

```bash
BASE=http://localhost:8080/auth
ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
REALM=<realm>

curl -s "$BASE/admin/realms/$REALM/authentication/authenticator-providers" -H "$H" \
  | jq -r '.[] | select(.id=="conditional-level-of-authentication")'
```

## The flow shape

```
<top-level flow>                              ALTERNATIVE level
├── auth-cookie                                 ALTERNATIVE
├── identity-provider-redirector                 ALTERNATIVE
└── Step-up forms                                ALTERNATIVE   ← sub-flow
    └── Levels                                    REQUIRED      ← sub-flow holding the levels
        ├── Level 1                                CONDITIONAL  ← sub-flow, FIRST
        │   ├── conditional-level-of-authentication  REQUIRED (loa-condition-level=1, loa-max-age=36000)
        │   └── auth-username-password-form           REQUIRED
        └── Level 2                                CONDITIONAL  ← sub-flow, SECOND
            ├── conditional-level-of-authentication  REQUIRED (loa-condition-level=2, loa-max-age=300)
            └── auth-otp-form                          REQUIRED
```

**Level 1 must come before Level 2** in the "Levels" sub-flow. `conditional-level-of-authentication`
answers "has the session already reached at least this level, recently enough" — on a brand-new
session nothing has been reached yet, so the *first* level sub-flow in the list always runs. If
Level 2 is listed first, a plain first login (no `acr` requested at all) is asked for the OTP code
before any password exists for it to follow — demanding level 2 on every first login, the opposite
of what step-up means. Keeping Level 1 first and Level 2 second means a plain login only ever
climbs as high as what's actually requested, one level at a time.

Each level's own sub-flow is CONDITIONAL (occupies the required bucket, per
`flow-execution-order.md`) and must contain its condition plus that level's authenticators, all
REQUIRED — a flat ALTERNATIVE/REQUIRED mix at any of these levels silently erases siblings.

### Author it (manual sequence — stock Keycloak, no extension)

```bash
FLOW='step-up-flow'
FORMS='Step-up forms'
LEVELS='Levels'
LVL1='Level 1'
LVL2='Level 2'

curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows" -H "$H" \
  -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FLOW\",\"providerId\":\"basic-flow\",\"topLevel\":true,\"builtIn\":false}"

enc() { jq -rn --arg f "$1" '$f|@uri'; }

# Top level: auth-cookie, identity-provider-redirector, then the forms sub-flow.
i=0
for p in auth-cookie identity-provider-redirector; do
  curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$FLOW")/executions/execution" \
    -H "$H" -H 'Content-Type: application/json' -d "{\"provider\":\"$p\",\"priority\":$((i*10))}"
  i=$((i+1))
done
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$FLOW")/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$FORMS\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":20}"

# Forms sub-flow: one REQUIRED child, the Levels sub-flow.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$FORMS")/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$LEVELS\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":0}"

# Levels sub-flow: Level 1 THEN Level 2 — order is load-bearing, see above.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LEVELS")/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$LVL1\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":0}"
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LEVELS")/executions/flow" \
  -H "$H" -H 'Content-Type: application/json' \
  -d "{\"alias\":\"$LVL2\",\"provider\":\"basic-flow\",\"type\":\"basic-flow\",\"priority\":10}"

# Level 1: condition (level=1, max-age=36000), then the password form.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LVL1")/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":0}'
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LVL1")/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-username-password-form","priority":10}'

# Level 2: condition (level=2, max-age=300), then the OTP form.
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LVL2")/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"conditional-level-of-authentication","priority":0}'
curl -s -X POST "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$LVL2")/executions/execution" \
  -H "$H" -H 'Content-Type: application/json' \
  -d '{"provider":"auth-otp-form","priority":10}'

# New executions start DISABLED and the add calls ignore "requirement". Set each with
# the execution's whole row (PUT also writes priority — send it back, see
# flow-execution-order.md).
set_req() {  # <flow alias> <providerId or sub-flow alias> <requirement>
  F=$(enc "$1")
  curl -s "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H" \
    | jq -c --arg k "$2" --arg r "$3" '.[] | select((.providerId // .displayName) == $k) | .requirement = $r' \
    | curl -s -o /dev/null -w "$2 -> $3: %{http_code}\n" -X PUT \
        "$BASE/admin/realms/$REALM/authentication/flows/$F/executions" -H "$H" \
        -H 'Content-Type: application/json' --data-binary @-
}
set_req "$FLOW" auth-cookie ALTERNATIVE
set_req "$FLOW" identity-provider-redirector ALTERNATIVE
set_req "$FLOW" "$FORMS" ALTERNATIVE
set_req "$FORMS" "$LEVELS" REQUIRED
set_req "$LEVELS" "$LVL1" CONDITIONAL
set_req "$LEVELS" "$LVL2" CONDITIONAL
set_req "$LVL1" conditional-level-of-authentication REQUIRED
set_req "$LVL1" auth-username-password-form REQUIRED
set_req "$LVL2" conditional-level-of-authentication REQUIRED
set_req "$LVL2" auth-otp-form REQUIRED

# Attach the per-level config to EACH condition execution — the two conditions are
# different executions even though they share a providerId, so match within each sub-flow.
attach_loa_config() {  # <sub-flow alias> <level> <max-age> <config-alias>
  EID=$(curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$1")/executions" -H "$H" \
    | jq -r '.[] | select(.providerId == "conditional-level-of-authentication") | .id')
  curl -s -o /dev/null -w "$4: %{http_code}\n" -X POST \
    "$BASE/admin/realms/$REALM/authentication/executions/$EID/config" -H "$H" \
    -H 'Content-Type: application/json' \
    -d "{\"alias\":\"$4\",\"config\":{\"loa-condition-level\":\"$2\",\"loa-max-age\":\"$3\"}}"
}
attach_loa_config "$LVL1" 1 36000 loa-level-1
attach_loa_config "$LVL2" 2 300 loa-level-2
```

Read the whole tree back and check every level is bucket-pure and in order before moving on:

```bash
curl -s "$BASE/admin/realms/$REALM/authentication/flows/$(enc "$FLOW")/executions" -H "$H" \
  | jq -r '.[] | "\(.index) lvl=\(.level) pri=\(.priority) \(.requirement) \(.providerId // .displayName)"'
```

## ACR → LoA mapping

Realm attribute `acr.loa.map`, a JSON object as a **string** inside `attributes`:

```bash
curl -s "$BASE/admin/realms/$REALM" -H "$H" \
  | jq '.attributes["acr.loa.map"] = "{\"silver\":1,\"gold\":2}"' \
  | curl -s -o /dev/null -w 'acr.loa.map: %{http_code}\n' -X PUT "$BASE/admin/realms/$REALM" -H "$H" \
      -H 'Content-Type: application/json' --data-binary @-
```

The realm's default `acr` client scope must carry the `acr loa level` mapper
(provider id `oidc-acr-mapper`) for the `acr` claim to appear in tokens at all — check it's present
on `acr` under `client-scopes`, since a realm created before this mapper existed may be missing it.

A client can override the map with the same attribute on the client, but the guide's own advice is
to keep it on the realm — one map, used by every client, is easier to keep straight than per-client
divergence.

## Pin a client to always require `gold`

Client attribute `minimum.acr.value` is **enforced** by Keycloak — unlike `default.acr.values`
(below), a client with this set gets the level even when the request asks for nothing at all:

```bash
CID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=acme-payments" -H "$H" | jq -r '.[0].id')
curl -s "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
  | jq '.attributes["minimum.acr.value"] = "gold"' \
  | curl -s -o /dev/null -w 'minimum.acr.value: %{http_code}\n' -X PUT \
      "$BASE/admin/realms/$REALM/clients/$CID" -H "$H" \
      -H 'Content-Type: application/json' --data-binary @-
```

`default.acr.values` (also a client attribute) is only a **default** sent when the request names
none — the user can override it in the browser, so it enforces nothing. `minimum.acr.value` is
what actually gates the client.

## Asking for a level, from the application

Not covered by this file beyond quoting the shape — the application side is `securing-apps`'
territory, but the shapes are:

```
# essential: Keycloak returns one of the listed values or fails outright
?claims={"id_token":{"acr":{"essential":true,"values":["gold"]}}}

# non-essential: a softer hint, Keycloak may ignore it
&acr_values=gold
```

The resulting ID token carries the level actually reached in its `acr` claim (`silver`, `gold`, or
`0` if nothing was ever established — see traps below).

## Level 2 variant: a PIN instead of a TOTP code

The Janua self-locking-session article uses a PIN from the third-party
[please-openit PIN Code Authenticator](https://github.com/pleaseopenit/keycloak-pin-code) as
Level 2's authenticator instead of stock `auth-otp-form`. The flow shape is identical — only the
authenticator inside Level 2's CONDITIONAL sub-flow changes (its provider id, in place of
`auth-otp-form`). Mention it as an option when a PIN fits the product better than a TOTP code; this
file documents the stock `auth-otp-form` path and doesn't depend on that extension being installed.

## Traps

1. **Level 1 must be first in the "Levels" sub-flow.** See "The flow shape" above — getting this
   backwards demands level 2 on every first login.
2. **`acr_values`/`default.acr.values` are rewritable by the browser; `minimum.acr.value` and the
   application's own check of the `acr` claim are what actually enforce a level.**
3. **Expiry is lazy, not a timer.** A level is only re-checked on the *next* authentication request
   that reaches this flow; a token already issued at `gold` stays valid until it expires on its own.
   Keep the access-token lifespan ≤ the level-2 `loa-max-age` (300s) or a stale token outlives the
   self-lock.
4. **`loa-max-age: 0`** means "this authentication only" — every request for that level re-prompts,
   useful for a payment-confirmation step rather than a 5-minute window.
5. **A user with no level requested, whose session's level has expired, still gets into SSO** —
   `acr` comes back `0` (cookie-only, no level reached this request). Applications must handle `0`
   as "nothing was established", not as an error.
6. **An essential `acr` that is unmapped or above every configured level is an authentication
   error**, not a silent downgrade to the nearest level.
7. **Levels are cumulative.** Level 2 includes level 1's requirements; it is not an alternate method.
   A *different* method per ACR (not "more of the same") is a client policy ("ACR to flow"), out of
   scope here.

## Verifying this actually works

1. No `acr` requested → only the password form → ID token `acr` is `silver`.
2. Same browser session, now request `gold` (essential) → **only** the OTP code form (no password
   form again) → correct code → ID token `acr` is `gold`.
3. Request `gold` again immediately → no prompt at all (within `loa-max-age`) → `acr` stays `gold`.
4. A fresh browser session requesting `gold` from the start → password, then code → `gold`.
5. A wrong code at the level-2 step → rejected, no authorization code issued.
6. The client pinned with `minimum.acr.value=gold` → the code is demanded even with no `acr`
   requested at all.
7. An essential `acr` above every mapped level, or unmapped entirely → an authentication error.
8. Configuration check: realm `acr.loa.map` has `silver`→1, `gold`→2; access-token lifespan ≤ 300s;
   level 2's `loa-max-age` is `300`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Level 2 is demanded on a plain first login with no `acr` requested | Level 2's sub-flow is listed before Level 1's inside "Levels" |
| `gold` never downgrades back to `silver` after 5 minutes | Access-token lifespan is longer than `loa-max-age`; the stale token is still valid |
| `acr` claim missing from the token entirely | The realm's default `acr` client scope is missing the `oidc-acr-mapper` ("acr loa level") mapper |
| `acme-payments` lets a login through at `silver` | `minimum.acr.value` not set, or set via `default.acr.values` instead (a default, not an enforcement) |
| An unmapped essential `acr` value logs the user in anyway at some level | Not expected Keycloak behavior — check nothing custom is downgrading instead of erroring |
