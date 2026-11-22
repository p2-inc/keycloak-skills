<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Token verification, done right

Loaded for **every** `app:protect-api` request, alongside the framework file. The framework files
carry wiring — which dependency, which config key, where the filter goes. This file carries the
rules that are identical in every language, and that are wrong more often than any other code an
integrator writes.

Read this before accepting a validation snippet from memory. Most published examples skip at least
one check below.

## The checks, in order

A token is acceptable only if **all** of these hold. Skipping any one of the first four is a real
vulnerability, not a hardening opportunity.

| # | Check | What goes wrong without it |
|---|---|---|
| 1 | **Signature** verifies against the realm's published JWKS | anyone can mint a token |
| 2 | **Algorithm** is pinned to what the realm actually uses (`RS256`) | `alg: none` and HMAC-confusion attacks, where the attacker signs with the public key as an HMAC secret |
| 3 | **`iss`** exactly equals the realm's issuer | a token from *any other realm* — including one the attacker controls — is accepted |
| 4 | **`aud`** (or `azp`, see below) names this API | a token minted for a different, possibly untrusted, client is accepted. This is the most commonly skipped check. |
| 5 | **`exp`** / **`nbf`** with small allowed skew | expired tokens keep working |
| 6 | **`typ`** is `Bearer` where the framework exposes it | an ID token or refresh token used where an access token belongs |

### On issuer

`iss` must match **character for character** — scheme, host, port, path, realm name. It does not get
normalized. The most common production failure is a Keycloak behind a proxy that issues tokens for
its internal hostname while the API expects the public one, or the reverse:

```
token iss:  http://keycloak:8080/realms/acme      ← container-internal
API expects https://auth.example.com/realms/acme  ← public
```

Both are "correct"; they simply disagree. Fix it at the Keycloak end by setting the hostname
properly so it issues the public issuer everywhere, **not** by relaxing the check in the API.

Never take the issuer *from the token* and use it to fetch the JWKS. That is the whole attack: the
attacker supplies both. The issuer must be configured.

### On audience — the check everyone skips

Keycloak does **not** put a useful `aud` in access tokens by default. Out of the box a token often
carries `aud: account`, which tells your API nothing. Two ways to get this right:

1. **Preferred** — add an *audience mapper* to the client (or a shared client scope) so tokens
   destined for your API carry `aud: my-api`. Then validate `aud == "my-api"`. This is realm
   configuration, so it belongs to the `keycloak` skill; say that it is a prerequisite rather than
   working around it.
2. **Fallback** — validate `azp` (authorized party) against the set of client IDs allowed to call
   this API. Weaker, because `azp` says who *obtained* the token, not who it was *for*, but far
   better than no check.

An API that validates neither `aud` nor `azp` accepts any valid token from the realm — including one
issued to a low-trust public client for an entirely different app.

## JWKS: fetch, cache, and rotate

The realm publishes its signing keys at:

```
{issuer}/protocol/openid-connect/certs
```

Discoverable from `{issuer}/.well-known/openid-configuration` (`jwks_uri`). Prefer discovery over
hardcoding the path — most libraries do it for you.

Rules:

- **Cache the key set.** Fetching per request adds a network round trip to every call and turns your
  IdP into a hard dependency of every request. Most libraries cache automatically; confirm rather than
  assume.
- **Refetch on unknown `kid`, with a cooldown.** Keys rotate. A token whose `kid` is not in the cache
  should trigger exactly one refetch, rate-limited — otherwise an attacker sends garbage `kid`s and
  turns your API into a DoS amplifier against Keycloak.
- **Never disable TLS verification** on the JWKS fetch. It is the root of trust for everything above.
- **Never pin a single public key** in config. It works until the first rotation, then every request
  fails at once.

## Local verification vs introspection

| | Local (verify the JWT) | Introspection (`POST /token/introspect`) |
|---|---|---|
| Cost | no network call per request | a network call per request |
| Revocation | not visible until `exp` | immediate |
| Needs credentials | no | yes — client id + secret |

**Default to local verification.** Introspection is right when tokens must be revocable instantly
(high-value operations, admin APIs) or when tokens are opaque rather than JWTs. If revocation
matters but per-request introspection is too expensive, shorten token lifetimes instead — that is a
realm setting, and a tuning conversation rather than an architecture change.

## Clock skew

Allow a small tolerance — **60 seconds is conventional**, and most libraries default there. Larger
values extend the life of every expired token by that amount. If validation fails intermittently
across hosts, check NTP before widening the window; a machine minutes out of sync is a real bug that
a bigger skew allowance only hides.

## Roles are not where you expect them

Keycloak puts roles in nested claims, not in `scope`:

```json
{
  "realm_access":    { "roles": ["admin", "user"] },
  "resource_access": { "my-api": { "roles": ["reader"] } }
}
```

Most frameworks' default converters read `scope` (or `scp`) and find nothing, so every role check
denies while the token is perfectly valid. Each `framework-*-api.md` file shows the converter for
its own stack — that mapping is framework-specific and stays there. What is universal:

- **Realm roles** (`realm_access.roles`) apply across the realm.
- **Client roles** (`resource_access.<client-id>.roles`) are scoped to one client, and only appear
  when that client is in the token's audience.
- A role missing from the token is usually a *mapper* problem in Keycloak, not a bug in the API.

## Identify the user by `sub`, never by username or email

Once the token is valid, something has to say *which* user it is. Use **`sub`** — the only claim
Keycloak guarantees is stable and unique for the life of the account.

| Claim | Safe to authorize on? | Why |
|---|---|---|
| `sub` | **yes** | immutable, unique, never reassigned |
| `preferred_username` | **no** | an admin can rename a user, and a freed username can be taken by someone else |
| `email` | **no** | changeable, and not necessarily verified — check `email_verified` before trusting it even for display |
| `name`, `given_name` | **no** | free text |

The failure this prevents is quiet and severe: scope a row lookup or an ownership check by
`preferred_username`, rename that user, and the check now resolves to a different person — or to a
new account that has claimed the freed username. Nothing errors.

```java
// wrong — data scoped by a claim that can change under you
service.forUser(jwt.getClaim("preferred_username"));
// right
service.forUser(jwt.getClaim("sub"));
```

Displaying a username is fine. Deciding what someone may *see or do* on one is not. If a framework
lets you set a "principal name" claim (Spring's `principalClaimName`, Quarkus's
`principal-claim`), treat that as a **display and logging** setting and keep authorization keyed on
`sub`.

Storing `sub` as your local user key also survives a rename, which username-keyed rows do not.

## DPoP-bound tokens

A browser app can bind its access token to a key pair it holds (DPoP, RFC 9449; Keycloak supports it officially from 26.4, and `oidc-spa` turns it on with one option). The token then carries a `cnf.jkt` claim, the thumbprint of the client's public key, and every request arrives as:

```
Authorization: DPoP <access_token>
DPoP: <proof JWT, signed by the client's key: htm, htu, iat, jti, ath>
```

A stolen token is useless without the private key, but only if every API that receives it checks the proof. The client side has **no per-host opt-out**: in `oidc-spa` v10 DPoP is on or off per client instance (`disableDPoP`), and when it's on every request carrying the token uses the `DPoP` scheme. So **every resource server that receives the token must be ready before the app enables it.** One unready API means 401s or CORS failures in production.

An API is ready when:

| Requirement | Why |
|---|---|
| It accepts `Authorization: DPoP <token>`, and accepts `typ: DPoP` on the token where it checks `typ` | most middleware only parses `Bearer` and rejects the rest |
| It verifies the proof (RFC 9449 §4.3): `typ: dpop+jwt`, an asymmetric `alg`, a valid signature by the embedded `jwk`, `htm` and `htu` matching this request, a fresh `iat`, an unused `jti`, `ath` equal to the base64url SHA-256 of the access token, and the `jwk` thumbprint equal to the token's `cnf.jkt` | each check closes a replay or substitution path |
| It **rejects a DPoP-bound token** (one with `cnf.jkt`) sent as `Bearer`, or sent with no proof | otherwise the binding protects nothing: a thief just downgrades the scheme |
| It verifies each proof **once per request** | replay protection records the proof's `jti`. Authenticating twice within one request — a filter plus a sub-resource, or nested auth calls — makes the second check see a replay and fail with a 401 |
| Its CORS preflight allows the `DPoP` request header | the browser won't send it otherwise. Keycloak's own endpoints already allow it; a custom CORS allowlist or an API gateway's `allow_headers` usually doesn't |
| Any gateway in front understands DPoP | a gateway's built-in JWT authorizer typically only parses `Bearer`; it needs a custom authorizer, with caching off since every request carries a new proof |

Two operational limits to plan for:

- **Header size.** The proof adds roughly a kilobyte to every request, on top of an access token that may already be large (many roles or groups). API gateways enforce hard limits on the request line plus headers — around 10 KB on some managed gateways. Measure the worst-case user's request against every hop.
- **Client clock skew.** Servers accept a proof only if its `iat` is within a short window of their own clock (Keycloak's default proof lifetime is 10 seconds, plus its allowed skew). A user whose device clock is minutes off fails every proof-checked request even though login worked. Log the rejection reason so this is diagnosable, and compare the proof's `iat` with the response's `Date` header.

## Never do these

- Decode without verifying. `jwt.decode(token)` with verification disabled is not authentication;
  it is parsing attacker-controlled JSON.
- Trust any claim from an unverified token — including `iss`, to decide how to verify it.
- Accept `alg: none`, or leave the accepted algorithm list open.
- Log the raw token. It is a live credential until it expires; logs get shipped, indexed, and read.
- Validate on the client. A browser check is UX, not security. The API validates independently, every
  time, regardless of what the frontend already checked.
