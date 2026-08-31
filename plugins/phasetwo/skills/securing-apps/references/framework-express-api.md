<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Express — bearer-JWT resource server with `jose`, and role middleware for Keycloak's nested claims

## What this is

Wiring for an Express service that accepts `Authorization: Bearer <jwt>`, verifies it against your
realm's JWKS with `jose`, and exposes a role guard that reads Keycloak's roles from where Keycloak
actually puts them.

No login UI, no session cookie, no redirect. If the same app also logs users in from a browser, that
is `app:add-login`, not this file.

**Verified 2026-08-27 against `jose@6.2.10` (published 2026-08-21) and Express 5.2.1.** Option names,
defaults and error codes below were read out of the published `jose` 6.2.10 tarball and its API docs,
not from memory.

The rules that are identical in every language — issuer matching, `aud` vs `azp`, JWKS caching and
rotation, algorithm pinning, clock skew, local verification vs introspection — live in
[pattern-token-validation.md](pattern-token-validation.md). Read it alongside this file. Nothing
there is repeated here.

---

## It replaces `keycloak-connect`, which is deprecated

`keycloak-connect` is Keycloak's own Node adapter. It is **deprecated**: last publish `26.1.1` on
**2025-01-28**, and Keycloak's team stated plainly it went unmaintained for lack of Node capacity.
It still installs — npm does not carry a deprecation flag on it — so nothing warns you. It is a dead
end regardless: it predates modern Express, it wants a `keycloak.json`, and its `Keycloak.middleware()`
/ `keycloak.protect()` model assumes a session store even for pure bearer APIs.

### Why this file diverges from Keycloak's own recommendation

Keycloak's deprecation notice points migrators at **`openid-client`**. That advice is right for the
case it was written about — an app that *obtains* tokens: authorization-code flow, PKCE, discovery,
refresh, logout, Passport integration. It is certified, framework-agnostic, and the correct answer
for `app:add-login`.

A resource server does none of that. It never talks to the token endpoint, holds no client secret,
and performs no flow. It receives a token someone else obtained and checks whether it is good. That
is one function.

`openid-client@6.8.7` declares `jose@^6.2.8` as a direct dependency — the validation you need is
`jose`, wrapped in a client library you would not use. Both are the same author. Depending on
`openid-client` for a bearer-only API means carrying the entire OAuth client surface, plus
`oauth4webapi`, to call through to `jose` anyway.

So: **`openid-client` when the service obtains tokens; `jose` when it only validates them.** If your
service does both — validates inbound tokens *and* fetches its own for downstream calls — use
`openid-client` for the outbound half and keep `jose` for the inbound half, or let `openid-client`
serve both.

| If you see this in the project | It is | Do this |
|---|---|---|
| `keycloak-connect`, `keycloak.json`, `Keycloak.middleware()` | deprecated, last publish Jan 2025 | remove it; follow this file |
| `express-jwt` + `jwks-rsa` | a working, maintained combination (`jwks-rsa@4.1.0`, published 2026-06-19) | **leave it alone if it works.** `jose` does the same job in one dependency; that is not a reason to rewrite. Do apply Step 3's option checklist to it — `express-jwt` also leaves `audience` and `issuer` unchecked when you omit them. |
| `jsonwebtoken` with a hardcoded public key | breaks at the first key rotation | replace with the JWKS setup below |
| `jwt.decode(token)` with no verification | **not authentication** — parsing attacker-controlled JSON | replace immediately |

---

## Step 1: The dependency

```bash
npm install jose
```

One dependency, zero transitive dependencies. `jose` is ESM-first (`"type": "module"`). If your
project is CommonJS, `require('jose')` works only on Node `^20.19.0 || ^22.12.0 || >= 23.0.0`, where
`require(esm)` is enabled by default — otherwise you get `ERR_REQUIRE_ESM` and need `await import('jose')`
or `"type": "module"` in your `package.json`.

`jose` uses the Web Crypto and Fetch globals, both of which are built into supported Node versions.
No `node-fetch`, no `jsonwebtoken`, no `jwks-rsa`.

---

## Step 2: The configuration

Environment variables, read once at startup:

```bash
KEYCLOAK_ISSUER=https://auth.example.com/realms/acme
KEYCLOAK_AUDIENCE=my-api
```

`KEYCLOAK_ISSUER` is your realm's issuer — scheme, host, port, path, realm name, **no trailing
slash**. Replace `auth.example.com` with your Keycloak hostname and `acme` with your realm name. On
Phase Two this is the `issuer` returned by `createOidcClient`. `KEYCLOAK_AUDIENCE` is your API's
audience value — see the note under Step 3.

---

## Step 3: Verify the token

`src/auth.js`:

```js
import { createRemoteJWKSet, jwtVerify } from 'jose'

const ISSUER = process.env.KEYCLOAK_ISSUER
const AUDIENCE = process.env.KEYCLOAK_AUDIENCE

if (!ISSUER) throw new Error('KEYCLOAK_ISSUER is not set')

// Built ONCE, at module load. Building it per request defeats the cache.
const JWKS = createRemoteJWKSet(new URL(`${ISSUER}/protocol/openid-connect/certs`), {
  cacheMaxAge: 600_000,      // 10 min — default; max age of a successful fetch
  cooldownDuration: 30_000,  // 30 s  — default; floor between refetches on unknown kid
  timeoutDuration: 5_000,    // 5 s   — default; abort a hung JWKS fetch
})

export async function verifyAccessToken(token) {
  const { payload, protectedHeader } = await jwtVerify(token, JWKS, {
    issuer: ISSUER,
    audience: AUDIENCE,
    algorithms: ['RS256'],
    clockTolerance: 60,        // seconds
    requiredClaims: ['sub', 'exp'],
  })
  return { payload, protectedHeader }
}
```

Every one of those options is doing work, and each maps to a rule in
[pattern-token-validation.md](pattern-token-validation.md):

| Option | Verified default | Why it is set explicitly |
|---|---|---|
| `issuer` | none — **unchecked if omitted** | a token from any other realm is otherwise accepted |
| `audience` | none — **unchecked if omitted** | a token minted for another client is otherwise accepted |
| `algorithms` | none — any algorithm the key supports | pins to `RS256`; blocks algorithm confusion |
| `clockTolerance` | `0` | 60 s is conventional; leaving it at 0 causes intermittent failures across hosts |
| `requiredClaims` | none | a claim that is absent is not "valid", it is missing |
| `cacheMaxAge` | `600000` ms | stated so nobody assumes it is per-request |
| `cooldownDuration` | `30000` ms | rate-limits refetch on unknown `kid`; without it a garbage-`kid` flood becomes a DoS against Keycloak |
| `timeoutDuration` | `5000` ms | a hung JWKS fetch otherwise hangs every request behind it |

**`createRemoteJWKSet` must be module-level.** Called inside the handler it constructs a fresh,
empty cache on every request — a JWKS round trip per API call, and Keycloak becomes a hard dependency
of your p99. This is the most common performance mistake in this file.

**Never build the JWKS URL from `payload.iss`.** The attacker supplies the token; if you fetch keys
from the issuer the token names, they supply the keys too. `ISSUER` comes from config.

**On `audience`:** Keycloak does not put a useful `aud` in access tokens by default — you need an
audience mapper on the client, which is realm configuration and belongs to the `keycloak` skill.
Setting `audience` before that mapper exists rejects **every** token with
`ERR_JWT_CLAIM_VALIDATION_FAILED`. Add the mapper first, then the option. If you cannot, drop
`audience` and check `payload.azp` against an allowlist instead — weaker, but far better than
nothing, and the reasoning is in [pattern-token-validation.md](pattern-token-validation.md).

---

## Step 4: The authentication middleware

```js
import { errors } from 'jose'
import { verifyAccessToken } from './auth.js'

export async function requireAuth(req, res, next) {
  const header = req.headers.authorization
  if (!header?.startsWith('Bearer ')) {
    res.set('WWW-Authenticate', 'Bearer')
    return res.status(401).json({ error: 'missing bearer token' })
  }

  try {
    const { payload } = await verifyAccessToken(header.slice(7))
    req.auth = payload          // the VERIFIED payload — nothing else may write here
    return next()
  } catch (err) {
    // Log the reason. NEVER log the token itself: it is a live credential.
    const code = err instanceof errors.JOSEError ? err.code : 'ERR_UNKNOWN'
    req.log?.warn({ code, message: err.message }, 'token rejected')
    res.set('WWW-Authenticate', `Bearer error="invalid_token"`)
    return res.status(401).json({ error: 'invalid token' })
  }
}
```

Two things:

- **Attach only the verified payload.** `req.auth` is set from `jwtVerify`'s return value and from
  nowhere else. Never populate it from `decodeJwt()`, from a header, or from a query parameter.
- **Return 401 with a generic body.** The `err.message` from `jose` tells you which check failed;
  that belongs in your logs, not in the response, where it tells an attacker which check to work on.

Express 5 propagates rejected promises from async middleware to the error handler automatically, so
the `try/catch` is for shaping the response, not for preventing an unhandled rejection. On Express 4
the `try/catch` is **mandatory** — without it the request hangs until it times out.

---

## Step 5: The role guard — the part everything else depends on

**This is why this file exists.** Keycloak does not put roles in `scope`. It puts them in
`realm_access.roles` and `resource_access.<client-id>.roles`:

```json
{
  "realm_access":    { "roles": ["admin", "user"] },
  "resource_access": { "my-api": { "roles": ["reader"] } },
  "scope":           "openid profile email"
}
```

Any guard that reads `payload.scope` and splits on spaces gets `["openid","profile","email"]` and
denies every role check — on a token that verified perfectly. That is a 403 on a good token.

```js
const CLIENT_ID = process.env.KEYCLOAK_AUDIENCE   // your API's client id

/** Realm roles + this API's client roles, from a VERIFIED payload. */
export function rolesOf(payload) {
  const realm = payload?.realm_access?.roles ?? []
  const client = payload?.resource_access?.[CLIENT_ID]?.roles ?? []
  return [...new Set([...realm, ...client])]
}

/** Deny unless the caller has at least one of `allowed`. */
export function requireRole(...allowed) {
  return (req, res, next) => {
    if (!req.auth) {
      // requireAuth did not run before this guard — fail closed, loudly.
      return res.status(500).json({ error: 'requireRole used without requireAuth' })
    }
    const held = rolesOf(req.auth)
    if (!allowed.some((role) => held.includes(role))) {
      return res.status(403).json({ error: 'insufficient role' })
    }
    return next()
  }
}
```

- **Optional chaining on every hop.** `realm_access` is absent from a token whose user has no realm
  roles. `payload.realm_access.roles` throws a `TypeError` there, which Express turns into a 500 —
  an authorization *outcome* reported as a server fault.
- **`requireRole` fails closed when `req.auth` is missing** rather than treating "no auth" as "no
  roles" and falling through to a 403. Ordering it before `requireAuth` is a wiring bug, and it
  should read as one.
- **`resource_access` is keyed by client ID.** That key is a literal string you must supply. Client
  roles only appear in the token when that client is in the token's audience; if `resource_access`
  has no key for your API at all, that is a Keycloak mapper problem, not a bug here.
- **403, not 401.** The caller authenticated fine and is simply not allowed. A 401 tells a client to
  go re-authenticate, which will not help and produces a redirect loop in browser clients.

---

## Step 6: Wire it up

```js
import express from 'express'
import { requireAuth, requireRole } from './auth-middleware.js'

const app = express()
app.use(express.json())

app.get('/health', (req, res) => res.json({ ok: true }))   // BEFORE requireAuth

app.use('/api', requireAuth)

app.get('/api/reports', (req, res) => res.json({ user: req.auth.preferred_username }))
app.delete('/api/reports/:id', requireRole('admin', 'editor'), (req, res) => res.status(204).end())

app.listen(3000)
```

**Order is the whole game.** `app.use('/api', requireAuth)` protects only paths under `/api`. Any
route registered *before* that line is unprotected regardless of its path, and adding a new route
above it silently opens it. Put `/health` above deliberately; put everything else below.

---

## Verify

**1. No token is rejected:**

```bash
curl -i http://localhost:3000/api/reports
# expect: HTTP/1.1 401 and  WWW-Authenticate: Bearer
```

**2. A garbage token is rejected** — proves you are verifying, not decoding:

```bash
curl -i -H "Authorization: Bearer not.a.token" http://localhost:3000/api/reports
# expect: HTTP/1.1 401
```

**3. A real token is accepted:**

```bash
TOKEN=$(curl -s -d 'client_id=my-api' -d 'client_secret=…' -d 'grant_type=client_credentials' \
  https://auth.example.com/realms/acme/protocol/openid-connect/token | jq -r .access_token)

curl -i -H "Authorization: Bearer $TOKEN" http://localhost:3000/api/reports
```

**4. Confirm the roles are where you think.** Add a temporary route — this is the check that catches
the whole class of bug this file is about:

```js
app.get('/api/whoami', (req, res) =>
  res.json({ sub: req.auth.sub, roles: rolesOf(req.auth) }))
```

You want `["admin","user"]`. `[]` means the claims are not in the token — decode it and look:

```bash
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{iss, aud, azp, realm_access, resource_access}'
```

If `realm_access.roles` is missing from the token itself, stop editing JavaScript — it is a
role-mapper problem in the realm, which is the `keycloak` skill's territory.

**5. Confirm the JWKS is cached.** Watch Keycloak's access log, or count outbound requests, while
you make ten API calls. You should see **one** request to `/protocol/openid-connect/certs`, not ten.
Ten means `createRemoteJWKSet` is inside the handler.

---

## Troubleshooting

| Symptom | `jose` error code | Cause | Fix |
|---|---|---|---|
| 401 on every request, even a fresh token | `ERR_JWT_CLAIM_VALIDATION_FAILED` (`claim: 'aud'`) | `audience` set but no audience mapper on the client | add the mapper in Keycloak, or drop `audience` and check `azp` |
| 401 on every request | `ERR_JWT_CLAIM_VALIDATION_FAILED` (`claim: 'iss'`) | issuer mismatch — usually Keycloak behind a proxy issuing its internal hostname | fix Keycloak's hostname config, not the API; see [pattern-token-validation.md](pattern-token-validation.md) |
| 401 after some minutes | `ERR_JWT_EXPIRED` | genuinely expired, or host clock drift | check NTP before widening `clockTolerance` |
| 401, works after a restart | `ERR_JWKS_NO_MATCHING_KEY` | keys rotated and the cooldown has not elapsed | expected and self-healing; do not shorten `cooldownDuration` below 30 s |
| 401 intermittently under load | `ERR_JWKS_TIMEOUT` | Keycloak slow or unreachable | raise `timeoutDuration`; check network path from the API host |
| 401 with a token that looks fine | `ERR_JOSE_ALG_NOT_ALLOWED` | realm signs with something other than `RS256` | check `alg` in the token header; widen `algorithms` to exactly what the realm uses — never to "any" |
| 401 | `ERR_JWS_SIGNATURE_VERIFICATION_FAILED` | token from a different realm, or tampered | compare `iss` in the token to `KEYCLOAK_ISSUER` |
| **403 on a token that authenticates fine** | — | **the guard read `scope` instead of `realm_access.roles`** | Step 5 — this is the headline bug |
| `/api/whoami` returns `roles: []` | — | claims absent from the token | decode it; if `realm_access` is missing it is a Keycloak mapper problem |
| 500, `Cannot read properties of undefined (reading 'roles')` | — | missing optional chaining on `realm_access` | use `payload?.realm_access?.roles ?? []` |
| Requests hang, no response | — | async middleware throwing on Express 4 with no `try/catch` | add the `try/catch`, or upgrade to Express 5 |
| Latency spike; one JWKS fetch per request | — | `createRemoteJWKSet` called inside the handler | move it to module scope |
| `ERR_REQUIRE_ESM` on `require('jose')` | — | `jose` is ESM-only | `"type": "module"`, or Node `^20.19.0 \|\| ^22.12.0 \|\| >=23`, or `await import('jose')` |
| A route is reachable without a token | — | it is registered above `app.use('/api', requireAuth)` | move it below, or mount the guard earlier |
| `requireRole used without requireAuth` (500) | — | guard ordered before the authenticator | put `requireAuth` first |
| `keycloak-connect` "works" but sessions behave oddly | — | deprecated adapter, last publish Jan 2025 | migrate to this file |
