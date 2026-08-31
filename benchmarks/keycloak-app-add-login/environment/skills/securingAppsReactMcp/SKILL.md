---
name: securingAppsReactMcp
description: >-
  Wire Keycloak login into a React SPA with oidc-spa, and register or repair the OIDC client the
  app needs, driven through the Keycloak MCP server's tools. Use this whenever someone wants login
  added to a browser app - login/logout controls, route protection, reading the signed-in user -
  against a Keycloak realm. Covers the oidc-spa v10 builder API (which replaced the removed
  createReactOidc), why the registered redirect URI needs a trailing slash, why updating an
  existing client must be a merge rather than a rebuild, and why web origins are a separate
  setting from redirect URIs that fails only in a real browser.
---

<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# React + Keycloak login — via the Keycloak MCP server

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

Tools: `listClients` to see what exists, `createOidcClient` for a new one, `updateOidcClient` to
repair one that already exists. Capture `deploymentId` and `deploymentRealm` and reuse them.

**Check first, with `listClients`.** If the app's client already exists, you are updating it.

```
updateOidcClient(deploymentId, deploymentRealm,
                 clientId     = "<client-id>",
                 redirectUris = "<full intended list>",
                 webOrigins   = "<full intended list>")
```

Three things that decide whether this works:

1. **The redirect URI ends with a trailing slash.** oidc-spa returns to the app's *base URL*, so a
   Vite app on port 5173 needs `http://localhost:5173/` registered — with the slash. Keycloak
   matches redirect URIs exactly and rejects the callback outright without it
   (`Invalid parameter: redirect_uri`, before the login form).

2. **Web origins are a SEPARATE setting from redirect URIs, and they fail differently.** The
   redirect URI authorizes where Keycloak sends the user *back*; the web origin authorizes the
   **CORS** origin of the browser's *token* call. Register only the redirect URI and login appears
   to succeed, then the token request is blocked in the browser — while every scripted,
   server-side test passes, because nothing in a script triggers a CORS preflight. Set
   `webOrigins` to the app's origin (`http://localhost:5173`, no trailing slash) or `"+"`.

3. **Both lists REPLACE, they do not append.** Read the current values from `listClients` first and
   send the full intended list, or you drop whatever was already registered.

**Never `deleteClient` a live client to change an attribute.** Deleting and re-creating destroys
its protocol mappers, role mappings, secret and sessions — a rebuilt client can log a user in while
having silently lost configuration other systems depend on. `updateOidcClient` merges: it reads the
current representation and changes only what you pass, because Keycloak's underlying PUT replaces
the whole client.

Also confirm the client is `public` with standard flow enabled, and that PKCE is required
(`S256`).

## Verify

1. `npm run build` exits 0.
2. `listClients` shows the client enabled, public, with both the redirect URI and the web origin.
3. A real browser login from the app's origin completes **and** the token call succeeds — that last
   part is the half a scripted test cannot see.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid parameter: redirect_uri` before the login form | trailing slash missing | register `http://host:port/` |
| Login works, then a CORS error on the token call | `webOrigins` not set | add the origin, or `"+"` |
| `Cannot find module 'oidc-spa/react'` | v8 import on a v9/v10 install | use `oidc-spa/react-spa` |
| `decodedIdToken` undefined | read without `assert` | narrow with `assert: "user logged in"` |
| Config that existed before the change is gone | client was rebuilt, not updated | `updateOidcClient`, never delete-and-re-create |
