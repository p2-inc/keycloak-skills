---
name: securingAppsReactRest
description: >-
  Wire Keycloak login into a React SPA with oidc-spa, and register or repair the OIDC client the
  app needs, driven through the Keycloak Admin REST API. Use this whenever someone wants login
  added to a browser app - login/logout controls, route protection, reading the signed-in user -
  against a self-managed Keycloak realm. Covers the oidc-spa v10 builder API (which replaced the
  removed createReactOidc), why the registered redirect URI needs a trailing slash, why updating an
  existing client must be a read-merge-PUT rather than a hand-built body, and why web origins are a
  separate setting from redirect URIs that fails only in a real browser.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# React + Keycloak login — via the Admin REST API

## What this is

A browser-only React app logging users into Keycloak with authorization code + PKCE, using
[`oidc-spa`](https://docs.oidc-spa.dev/). The client is **public** — a browser bundle cannot hold a
secret, so there is none, and PKCE replaces it.

Two halves, both required: **the app's source**, and **the client registration in Keycloak**. A
correct app against a stale client does not log anyone in.

## Half 1: the app

**Verified against `oidc-spa` 10.2.11.** `oidcSpa` is a **builder**, not a config function.

`src/oidc.ts`:

```ts
import { oidcSpa } from "oidc-spa/react-spa";
import { z } from "zod";

export const {
    bootstrapOidc, useOidc, getOidc, withLoginEnforced, OidcInitializationGate
} = oidcSpa
    .withExpectedDecodedIdTokenShape({
        decodedIdTokenSchema: z.object({
            sub: z.string(),
            name: z.string().optional(),
            preferred_username: z.string().optional()
        })
    })
    .createUtils();

bootstrapOidc({
    implementation: "real",
    issuerUri: "http://localhost:8080/auth/realms/<realm>",   // INCLUDES /realms/<realm>
    clientId: "<client-id>"
});
```

`src/main.tsx` — the wrapper is `OidcInitializationGate`. **There is no `OidcProvider` in v10.**

```tsx
<OidcInitializationGate>
    <App />
</OidcInitializationGate>
```

Reading state, login, logout:

```tsx
const { isUserLoggedIn } = useOidc();
const { login } = useOidc({ assert: "user not logged in" });
const { decodedIdToken, logout } = useOidc({ assert: "user logged in" });
// <button onClick={() => login()}>   /   <button onClick={() => logout({ redirectTo: "home" })}>
```

Claims live on `decodedIdToken`. Access token for API calls:
`await (await getOidc()).getAccessToken()`.

> **If you remember a different API, you are remembering v8.** `createReactOidc` and the whole
> `oidc-spa/react` entry point were **removed in v9**. `createOidcProvider` / `createUseOidc` are
> v3-era. Importing any of them fails to resolve.

PKCE is automatic and cannot be disabled — the library enforces `S256`.

## Half 2: the client

```bash
BASE=http://localhost:8080/auth      # include the relative path if one is configured
REALM=<realm>                        # the app's realm — NOT master

ADMIN_TOKEN=$(curl -s -X POST "$BASE/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d grant_type=password \
  -d username=<admin-user> -d password=<admin-password> \
  | jq -r .access_token)
H="Authorization: Bearer $ADMIN_TOKEN"
```

`$REALM` is the app's realm, not `master` — you authenticate *as* a master admin and act *on* the
app's realm. The token is short-lived; a run that starts working then 401s has simply expired.

**Check what exists first.** `clientId` is not the UUID: `clientId` is the string in the app's
config; `id` is the server-generated UUID every `/clients/{uuid}` path needs.

```bash
ID=$(curl -s "$BASE/admin/realms/$REALM/clients?clientId=<client-id>" -H "$H" | jq -r '.[0].id')
```

Empty array → the client does not exist, create it with `POST /admin/realms/$REALM/clients`.
Otherwise you are updating one that does.

### Updating an existing client: read, merge, PUT

> ⚠️ **`PUT /admin/realms/{realm}/clients/{uuid}` takes the WHOLE client representation.** Top-level
> fields you omit are **blanked**, silently, with a `204 No Content` that looks like success. Send
> only `{"redirectUris": [...]}` and you have just wiped the client's name, its protocol mappers, its
> flow bindings, its scopes and its production web origins. There is no PATCH and no partial-update
> endpoint. Nothing merges this for you — that is your job here.

```bash
# 1. READ the current representation whole
curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" > /tmp/client.json

# 2. MERGE — append to the existing lists, don't replace them
jq '.redirectUris = (.redirectUris + ["http://localhost:5173/"] | unique)
  | .webOrigins   = (.webOrigins   + ["http://localhost:5173"]  | unique)
  | .publicClient = true
  | .standardFlowEnabled = true
  | .attributes["pkce.code.challenge.method"] = "S256"' \
  /tmp/client.json > /tmp/client-new.json

# 3. LOOK at what you are about to send. Anything you did not intend is a bug.
diff <(jq -S . /tmp/client.json) <(jq -S . /tmp/client-new.json)

# 4. PUT the whole thing back — expect 204
curl -s -o /dev/null -w '%{http_code}\n' -X PUT "$BASE/admin/realms/$REALM/clients/$ID" \
  -H "$H" -H 'Content-Type: application/json' --data-binary @/tmp/client-new.json
```

`/tmp/client.json` can contain the client secret for a confidential client — treat these temp files
as credential material and delete them afterwards.

**Never `DELETE` a live client to change an attribute.** It destroys its protocol mappers, role
mappings, secret and sessions. A rebuilt client can log a user in while having silently lost
configuration other systems depend on.

### Three things that decide whether this works

1. **The redirect URI ends with a trailing slash.** oidc-spa returns to the app's *base URL*, so a
   Vite app on port 5173 needs `http://localhost:5173/` registered — with the slash. Keycloak
   matches redirect URIs exactly and rejects the callback outright without it
   (`Invalid parameter: redirect_uri`, before the login form).

2. **Web origins are a SEPARATE setting from redirect URIs, and they fail differently.** The
   redirect URI authorizes where Keycloak sends the user *back*; the web origin authorizes the
   **CORS** origin of the browser's *token* call. Register only the redirect URI and login appears
   to succeed, then the token request is blocked in the browser — while every scripted, server-side
   test passes, because nothing in a script triggers a CORS preflight. Set `webOrigins` to the app's
   origin (`http://localhost:5173`, no trailing slash) or `"+"`.

3. **`attributes` merge; top-level fields replace.** Keycloak iterates only the attribute keys
   present in the payload, so you cannot delete an attribute by omitting it — send it explicitly as
   JSON `null`. Top-level fields behave the opposite way, which is what makes step 1 above
   non-negotiable.

## Verify

```bash
curl -s "$BASE/admin/realms/$REALM/clients/$ID" -H "$H" \
  | jq '{clientId, enabled, publicClient, standardFlowEnabled, redirectUris, webOrigins,
         pkce: .attributes["pkce.code.challenge.method"],
         mappers: [.protocolMappers[]?.name]}'
```

Confirm `mappers` still lists everything it listed before you started — that is the check that
separates an update from an accidental rebuild. Then run `npm run build`, and do a real browser
login: the token call succeeding is the half a scripted test cannot see.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid parameter: redirect_uri` before the login form | trailing slash missing | register `http://host:port/` |
| Login works, then a CORS error on the token call | `webOrigins` not set | add the origin, or `"+"` |
| `Cannot find module 'oidc-spa/react'` | v8 import on a v9/v10 install | use `oidc-spa/react-spa` |
| `decodedIdToken` undefined | read without `assert` | narrow with `assert: "user logged in"` |
| Config that existed before the change is gone | a partial `PUT` blanked it | always read-merge-`PUT`; restore from a pre-change `GET` if you have one |
| `401` on every call partway through | the admin token expired | re-mint it; it lasts minutes |
| `409 Conflict` on `POST /clients` | the `clientId` is taken | you are on the update path, not create |
