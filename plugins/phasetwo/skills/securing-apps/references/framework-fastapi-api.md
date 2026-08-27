# FastAPI — bearer-JWT resource server with PyJWT, and a `require_role` dependency for Keycloak's nested claims

## What this is

Wiring for a FastAPI service that accepts `Authorization: Bearer <jwt>`, verifies it against your
realm's JWKS with PyJWT's `PyJWKClient`, and exposes a role guard that reads Keycloak's roles from
where Keycloak actually puts them.

No login UI, no session cookie, no redirect. If the same app also logs users in from a browser, that
is `app:add-login`, not this file.

**Verified 2026-08-27 against `PyJWT 2.13.0` (requires Python >= 3.9) and FastAPI 0.141.1.**
Signatures, defaults and exception names below were read from the PyJWT API reference and the
current `jwt/api_jwt.py` source, not from memory.

The rules that are identical in every language — issuer matching, `aud` vs `azp`, JWKS caching and
rotation, algorithm pinning, clock skew, local verification vs introspection — live in
[pattern-token-validation.md](pattern-token-validation.md). Read it alongside this file. Nothing
there is repeated here.

---

## There was never a Keycloak Python adapter

Unlike Java and Node, Keycloak has never shipped an official Python adapter — so there is nothing
removed or deprecated to migrate off, and no upstream library to prefer. Anything you find named
`python-keycloak`, `flask-oidc` or similar is third-party. This file uses **PyJWT**, which is the
library FastAPI's own security documentation uses.

| If you see this in the project | Note |
|---|---|
| `python-jose` | third-party and slow-moving — latest release `3.5.0`, uploaded 2025-05-28 (checked 2026-08-27). It works; PyJWT is the more actively maintained default and the one FastAPI's own docs use. Not urgent to replace. |
| `python-keycloak` | third-party wrapper; convenient for Admin REST calls, unnecessary for bearer validation |
| `jwt.decode(token, options={"verify_signature": False})` | **not authentication** — parsing attacker-controlled JSON. Replace immediately. |
| `PyJWKClient` constructed inside the request handler | a JWKS round trip per request; move it to module scope |

---

## Step 1: The dependency

```bash
pip install "pyjwt[crypto]"
```

**The `[crypto]` extra is not optional.** It pulls in `cryptography>=3.4.0` (verified from PyJWT's
metadata: `provides_extra: ['crypto']`). Plain `pip install pyjwt` installs PyJWT without any
asymmetric-key support, and every RS256 verification then fails with
`InvalidAlgorithmError: Algorithm 'RS256' could not be found` — which reads like a configuration
problem and is actually a missing dependency.

In `pyproject.toml`:

```toml
dependencies = [
  "fastapi>=0.141",
  "pyjwt[crypto]>=2.13",
  "uvicorn[standard]",
]
```

or `requirements.txt`:

```
fastapi>=0.141
pyjwt[crypto]>=2.13
uvicorn[standard]
```

---

## Step 2: The configuration

Environment variables, read once at import:

```bash
KEYCLOAK_ISSUER=https://auth.example.com/realms/acme
KEYCLOAK_AUDIENCE=my-api
```

`KEYCLOAK_ISSUER` is your realm's issuer — scheme, host, port, path, realm name, **no trailing
slash**. Replace `auth.example.com` with your Keycloak hostname and `acme` with your realm name. On
Phase Two this is the `issuer` returned by `createOidcClient`. `KEYCLOAK_AUDIENCE` is your API's
audience value — read the audience warning in Step 3 before you set it.

---

## Step 3: Verify the token

`app/auth.py`:

```python
import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from typing import Annotated, Any

ISSUER = os.environ["KEYCLOAK_ISSUER"]          # KeyError at import if unset — deliberate
AUDIENCE = os.environ["KEYCLOAK_AUDIENCE"]
ALGORITHMS = ["RS256"]

# Built ONCE, at import. Building it per request defeats the cache.
_jwks_client = PyJWKClient(
    f"{ISSUER}/protocol/openid-connect/certs",
    cache_jwk_set=True,     # default True  — cache the whole JWKS response
    lifespan=300,           # default 300 s — TTL of that cache
    timeout=30,             # default 30 s  — HTTP timeout on the JWKS fetch
    max_cached_keys=16,     # default 16
)

bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, Any]:
    """Verify the bearer token and return its VERIFIED claims."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            issuer=ISSUER,
            audience=AUDIENCE,
            leeway=60,                       # seconds of clock skew
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        # Log the reason. NEVER log the token: it is a live credential.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc


Claims = Annotated[dict[str, Any], Depends(verify_token)]
```

Every argument is doing work, and each maps to a rule in
[pattern-token-validation.md](pattern-token-validation.md):

| Argument | Verified default | Why it is set explicitly |
|---|---|---|
| `algorithms` | `None` — **decode raises without it** | pins to `RS256`; blocks algorithm confusion |
| `issuer` | `None` — **`iss` unchecked if omitted** | a token from any other realm is otherwise accepted |
| `audience` | `None` — **but see the trap below** | a token minted for another client is otherwise accepted |
| `leeway` | `0` | 60 s is conventional; 0 causes intermittent failures across hosts |
| `options={"require": [...]}` | `[]` | a claim that is absent is not "valid", it is missing |
| `cache_jwk_set` | `True` | stated so nobody assumes fetching is per-request |
| `lifespan` | `300` s | how long the cached JWKS is reused |
| `timeout` | `30` s | a hung JWKS fetch otherwise hangs the request |

`get_signing_key_from_jwt` reads the token's `kid` header, matches it against the cached JWK set, and
refetches when it does not match — that is how key rotation is survived. It returns a `PyJWK`; the
usable key is `signing_key.key`.

**`PyJWKClient` must be module-level.** Constructed inside the dependency it builds a fresh, empty
cache on every request — a JWKS round trip per API call, and Keycloak becomes a hard dependency of
your p99. This is the most common performance mistake in this file.

**Never build the JWKS URL from the token's `iss`.** The attacker supplies the token; if you fetch
keys from the issuer the token names, they supply the keys too. `ISSUER` comes from the environment.

### The audience trap that is specific to PyJWT

`verify_aud` defaults to on. And PyJWT's `_validate_aud` does this, verified from source:

> if `audience is None` and the token **has** a non-empty `aud` claim → `raise InvalidAudienceError("Invalid audience")`

Keycloak access tokens carry `aud: account` by default. So the obvious-looking call — `jwt.decode(...)`
with `issuer=` but no `audience=` — fails on **every** Keycloak token with `Invalid audience`, and it
looks like the token is broken.

There are two responses, and only one is correct:

| Response | Result |
|---|---|
| Add an **audience mapper** on the client in Keycloak so tokens carry `aud: my-api`, then pass `audience="my-api"` | correct. This is realm configuration and belongs to the `keycloak` skill; name it as a prerequisite. |
| Set `options={"verify_aud": False}` | **disables the audience check entirely** — your API now accepts any valid token from the realm, including one issued to a low-trust public client for a different app |

If you genuinely cannot add the mapper yet, the least-bad interim is to pass `audience="account"`
(matching what Keycloak actually issues) **and** check `azp` yourself against an allowlist of client
IDs permitted to call this API:

```python
ALLOWED_AZP = {"my-web-app", "my-mobile-app"}

if claims.get("azp") not in ALLOWED_AZP:
    raise HTTPException(status_code=403, detail="client not permitted")
```

That is weaker than a real `aud` — `azp` says who *obtained* the token, not who it was *for* — but it
is a check, and `verify_aud: False` is not. The full reasoning is in
[pattern-token-validation.md](pattern-token-validation.md).

The mirror-image failure: if you pass `audience="my-api"` and the token has **no** `aud` claim at
all, PyJWT raises `MissingRequiredClaimError: Token is missing the "aud" claim` — different
exception, same root cause of a missing mapper.

---

## Step 4: The role dependency — the part everything else depends on

**This is why this file exists.** Keycloak does not put roles in `scope`. It puts them in
`realm_access.roles` and `resource_access.<client-id>.roles`:

```json
{
  "realm_access":    { "roles": ["admin", "user"] },
  "resource_access": { "my-api": { "roles": ["reader"] } },
  "scope":           "openid profile email"
}
```

Any guard that reads `claims["scope"].split()` gets `["openid","profile","email"]` and denies every
role check — on a token that verified perfectly. That is a 403 on a good token.

```python
CLIENT_ID = AUDIENCE   # your API's client id — the resource_access key


def roles_of(claims: dict[str, Any]) -> set[str]:
    """Realm roles + this API's client roles, from VERIFIED claims."""
    realm = claims.get("realm_access", {}).get("roles", [])
    client = claims.get("resource_access", {}).get(CLIENT_ID, {}).get("roles", [])
    return set(realm) | set(client)


def require_role(*allowed: str):
    """FastAPI dependency: deny unless the caller holds at least one of `allowed`."""
    def _guard(claims: Claims) -> dict[str, Any]:
        if not roles_of(claims) & set(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient role",
            )
        return claims

    return _guard
```

- **`.get(..., {})` on every hop.** `realm_access` is absent from a token whose user has no realm
  roles, and `resource_access` is absent when no client role applies. `claims["realm_access"]["roles"]`
  raises `KeyError` there, which FastAPI turns into a **500** — an authorization *outcome* reported as
  a server fault.
- **`require_role` is a factory, not a dependency.** Call it: `Depends(require_role("admin"))`. Passing
  the function itself — `Depends(require_role)` — makes FastAPI try to inject `*allowed`, and you get a
  startup-time dependency-resolution error rather than a working guard.
- **It depends on `Claims`, so `verify_token` always runs first.** There is no ordering to get wrong,
  unlike middleware-based frameworks — the dependency graph enforces it.
- **`resource_access` is keyed by client ID.** That key is a literal string you must supply. Client
  roles only appear in the token when that client is in the token's audience; if `resource_access` has
  no key for your API at all, that is a Keycloak mapper problem, not a bug here.
- **403, not 401.** The caller authenticated fine and is simply not allowed. A 401 tells a client to
  go re-authenticate, which will not help.

---

## Step 5: Use it

```python
from fastapi import APIRouter, Depends, FastAPI

app = FastAPI()
router = APIRouter(prefix="/api")


@app.get("/health")                                    # no dependency — deliberately open
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/reports")
def list_reports(claims: Claims) -> dict[str, str]:
    return {"user": claims.get("preferred_username", claims["sub"])}


@router.delete("/reports/{report_id}", dependencies=[Depends(require_role("admin", "editor"))])
def delete_report(report_id: str) -> None:
    ...


app.include_router(router)
```

Use `dependencies=[...]` on the decorator when the handler does not need the claims, and
`claims: Annotated[dict, Depends(require_role("admin"))]` when it does. To protect a whole router,
put it on the router itself — this is safer than remembering per route:

```python
router = APIRouter(prefix="/api", dependencies=[Depends(verify_token)])
```

---

## Verify

**1. No token is rejected:**

```bash
curl -i http://localhost:8000/api/reports
# expect: HTTP/1.1 401 and  WWW-Authenticate: Bearer
```

With `HTTPBearer(auto_error=False)` plus the explicit `None` check above you get a 401. Leaving
`auto_error=True` (the default) also produces a 401 but with FastAPI's own message and no control
over the `WWW-Authenticate` header — which is why this file sets it to `False`.

**2. A garbage token is rejected** — proves you are verifying, not decoding:

```bash
curl -i -H "Authorization: Bearer not.a.token" http://localhost:8000/api/reports
# expect: HTTP/1.1 401
```

**3. A real token is accepted:**

```bash
TOKEN=$(curl -s -d 'client_id=my-api' -d 'client_secret=…' -d 'grant_type=client_credentials' \
  https://auth.example.com/realms/acme/protocol/openid-connect/token | jq -r .access_token)

curl -i -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/reports
```

**4. Confirm the roles are where you think.** Add a temporary route — this is the check that catches
the whole class of bug this file is about:

```python
@router.get("/whoami")
def whoami(claims: Claims) -> dict[str, Any]:
    return {"sub": claims["sub"], "roles": sorted(roles_of(claims))}
```

You want `["admin","user"]`. `[]` means the claims are not in the token — decode it and look:

```bash
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{iss, aud, azp, realm_access, resource_access}'
```

If `realm_access.roles` is missing from the token itself, stop editing Python — it is a role-mapper
problem in the realm, which is the `keycloak` skill's territory.

**5. Confirm the JWKS is cached.** Watch Keycloak's access log while you make ten API calls. You
should see **one** request to `/protocol/openid-connect/certs`, not ten. Ten means `PyJWKClient` is
being constructed inside the dependency.

**6. See the real reason for a 401.** The handler above deliberately returns a generic `detail`.
While debugging, log `repr(exc)` in the `except` block — `InvalidAudienceError` and `InvalidIssuerError`
look identical from outside and are completely different problems. Take it back out before
production, and never log the token.

---

## Troubleshooting

| Symptom | PyJWT exception | Cause | Fix |
|---|---|---|---|
| 401 on every request, even a fresh token | `InvalidAudienceError: Invalid audience` | **`audience=None` while the token carries `aud: account`** | add an audience mapper in Keycloak and pass `audience`; do **not** set `verify_aud: False` |
| 401 on every request | `MissingRequiredClaimError: Token is missing the "aud" claim` | you passed `audience=` but the client has no audience mapper | add the mapper in Keycloak |
| 401 on every request | `InvalidIssuerError` | issuer mismatch — usually Keycloak behind a proxy issuing its internal hostname | fix Keycloak's hostname config, not the API; see [pattern-token-validation.md](pattern-token-validation.md) |
| 401 after some minutes | `ExpiredSignatureError` | genuinely expired, or host clock drift | check NTP before widening `leeway` |
| 401 with a valid-looking token | `InvalidSignatureError` | token from a different realm, or tampered | compare `iss` in the token to `KEYCLOAK_ISSUER` |
| 401 on every request from a clean install | `InvalidAlgorithmError: Algorithm 'RS256' could not be found` | **`cryptography` missing** — you installed `pyjwt` without `[crypto]` | `pip install "pyjwt[crypto]"` |
| `DecodeError: It is required that you pass in a value for the "algorithms" argument` | `DecodeError` | `algorithms=` omitted | pass `algorithms=["RS256"]` |
| 401 / 500 at startup or first request | `PyJWKClientConnectionError` | Keycloak unreachable from the API host | curl `{ISSUER}/protocol/openid-connect/certs` from that host |
| 401 right after a key rotation, recovers on its own | `PyJWKClientError: Unable to find a signing key that matches` | cached JWKS predates the rotation | expected; `lifespan` bounds it |
| **403 on a token that authenticates fine** | — | **the guard read `scope` instead of `realm_access.roles`** | Step 4 — this is the headline bug |
| `/api/whoami` returns `roles: []` | — | claims absent from the token | decode it; if `realm_access` is missing it is a Keycloak mapper problem |
| 500, `KeyError: 'realm_access'` | — | subscripting instead of `.get(..., {})` | use the chained `.get` form |
| Startup error naming `allowed` as an unresolvable dependency | — | `Depends(require_role)` instead of `Depends(require_role("admin"))` | call the factory |
| Latency spike; one JWKS fetch per request | — | `PyJWKClient` constructed inside the dependency | move it to module scope |
| Endpoint reachable with no token | — | the route has no `Depends(verify_token)` and is not on a guarded router | put the dependency on the `APIRouter` |
| `KeyError: 'KEYCLOAK_ISSUER'` at import | — | env var not set | intentional: fail at startup, not per request |
