# Common errors, across every framework

Loaded on every intent. These failures are identical whether the app is React or Spring Boot, so
they live here once rather than in twelve framework files.

Work down the table — the symptom is usually enough to identify the cause without instrumenting
anything.

| Symptom | Almost always | Fix |
|---|---|---|
| `Invalid redirect_uri` on a Keycloak error page, **before** the login form | the URI the app sent isn't registered, character for character | compare scheme, host, port, path, trailing slash |
| Login works, then a **CORS error** on the token call | `webOrigins` missing or wrong on the client | add the exact origin, or `"+"` |
| API returns **401** with a token that looks fine | `iss` or `aud` mismatch | decode the token, compare claims against the API's configured issuer and audience |
| API returns **403** for a user who has the role | roles read from the wrong claim | Keycloak puts them in `realm_access.roles`, not `scope` |
| Works in a script, breaks in the browser | a CORS/web-origin problem the script never triggers | test in a real browser before believing a green scripted test |
| Works locally, breaks in Docker/Kubernetes | `localhost` vs container hostname in the issuer | see "Two hostnames" below |
| Intermittent `token expired` across hosts | clock drift | check NTP before widening skew tolerance |
| Redirect loop between app and Keycloak | the app doesn't recognise its own callback, so it restarts login | check the callback route is registered and reachable |

---

## Invalid redirect_uri

Matching is **exact** and not normalized. All of these are *different* URIs to Keycloak:

```
http://localhost:3000/callback
http://localhost:3000/callback/          ← trailing slash
http://127.0.0.1:3000/callback           ← different host
https://localhost:3000/callback          ← different scheme
http://localhost:3001/callback           ← different port
```

Read the actual `redirect_uri` query parameter out of the URL bar on the Keycloak error page. That is
what the app sent — compare it to what is registered rather than to what you expected the app to send.

Wildcards (`https://app.example.com/*`) work but widen the client. Fine for local development;
avoid in production, and never `*` alone.

## CORS on the token endpoint

The tell: login completes, the browser returns to the app, and the console shows a blocked request to
`/protocol/openid-connect/token`.

**Redirect URIs and web origins are separate settings.** Registering the redirect URI does not
authorize the origin. The redirect is a browser *navigation* (no CORS involved); the token exchange
is an XHR/fetch from JS (CORS fully involved).

This is why a scripted, server-side test passes while the real app fails — nothing in a script
triggers a CORS preflight. Set both, and verify in a browser.

## 401 with a token that looks valid

Decode it (`jwt.io`, or `cut -d. -f2 | base64 -d`) and compare three things against the API's config:

- **`iss`** — must match exactly, including realm name and port
- **`aud`** — must name this API; Keycloak's default `aud: account` names nothing useful
- **`exp`** — is it actually still valid

Reading the token is faster than adding logging. If `iss` differs only by hostname, jump to the next
section.

## Two hostnames for one Keycloak

The most common environment-specific failure, and it looks like a code bug:

```
Browser reaches Keycloak at:  http://localhost:8080      (published port)
API reaches Keycloak at:      http://keycloak:8080       (container network)
Token says:                   iss: http://localhost:8080/realms/acme
API is configured with:       http://keycloak:8080/realms/acme   ← mismatch → 401
```

Both hostnames are correct for their caller. The token carries only one.

**Fix at the Keycloak end, not in the API.** Set Keycloak's hostname so it issues one canonical
public issuer for everyone, and make the API reach it by that name too (a container-network alias, or
DNS that resolves inside and outside). Relaxing the issuer check in the API removes the protection
that makes the check worth having.

## Roles are missing from the token

Two different causes, and they need different fixes:

1. **The claim is there, the code reads the wrong place.** Decode the token: if `realm_access.roles`
   is populated, the API's authority converter is at fault. Framework-specific — see the
   `framework-*-api.md` file.
2. **The claim is genuinely absent.** Client roles (`resource_access.<client>.roles`) only appear
   when that client is in the token's audience, and a missing realm role means the user doesn't hold
   it or no mapper emits it. That is realm configuration — the `keycloak` skill, not this one.

## Public client asking for a secret

If a library config wants a `clientSecret` for a browser SPA or mobile app, the client type is wrong.
Public clients have no secret and use PKCE. Putting a secret in a browser bundle or a mobile binary
publishes it — see `pattern-integration-decision.md`.

## Silent-renew / iframe failures

Symptoms: the session drops after a few minutes, or the console shows an iframe blocked by
`X-Frame-Options` or a third-party-cookie warning.

Modern browsers block third-party cookies, which breaks the traditional hidden-iframe silent renew
when Keycloak is on a different site than the app. Options, in order of preference: use refresh
tokens in memory (the default in current libraries), put Keycloak on the same site as the app, or
accept a full redirect on renewal. Do not disable browser security to make the iframe work.
