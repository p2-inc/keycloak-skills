<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Vue SPA — login, logout and route protection with `keycloak-js`

## What this is

A browser-only Vue 3 app (Vite, Vue Router) logging users into Keycloak with authorization code +
PKCE. The client is **public** — no secret ever reaches the bundle.

**Vue uses `keycloak-js`.** This is the right answer for Vue, not a fallback: `keycloak-js` is
Keycloak's own client library, actively maintained in its own repository, and it is framework-
agnostic by design — you wire it into Vue's reactivity in about forty lines and own the result.

**Verified against `keycloak-js` 26.2.4** (npm `latest`, published 2026-04-22), with Vue 3.5 and Vue
Router 5. The types below come from the published `lib/keycloak.d.ts`.

### "Decoupled from the Keycloak server release cycle" does not mean deprecated

You will read that phrase in the Keycloak 26.1.0 release notes and it misleads almost everyone.
What actually happened: the adapter moved **out of the Keycloak monorepo into its own repository**
(`keycloak/keycloak-js`) and got **independent SemVer versioning**, so it can ship on its own
schedule instead of waiting for a server release. It was deliberately given a version number ahead
of the server's to signal the split. Releases have continued steadily since —
26.2.1 (2025-10-09), 26.2.2 (2025-12-11), 26.2.3 (2026-02-04), 26.2.4 (2026-04-22).

What **is** deprecated is a different package: `keycloak-connect`, the Node.js server adapter. And
what was **removed** in Keycloak 25.0.0 is the family of Java adapters. Neither is `keycloak-js`.

### Why not `oidc-spa`

`oidc-spa` is Phase Two's house choice for React, Angular and vanilla SPAs, but **it has no Vue
adapter.** Verified against 10.2.11: the package's `exports` map lists `./angular`, `./react-spa`,
`./nuxt-spa` and `./react-tanstack-start` — there is no `./vue`. The v10 documentation has no Vue
page and no Vue example.

You *can* use the framework-agnostic core (`createOidc` from `oidc-spa/core`) in a Vue app — it is
plain TypeScript with no framework assumptions. The honest framing is that **you write the Vue
bindings yourself**: the reactive store, the router guard, the interceptor. That is the same amount
of glue this file writes for `keycloak-js`, minus a library Keycloak itself maintains. It is not
parity with the Angular or React adapters, and nobody should describe it that way. If you want it,
follow [`framework-spa-js.md`](framework-spa-js.md) and drop the result into a Vue composable.

There is also a middle path: `oidc-spa` ships a **`keycloak-js` polyfill** at `oidc-spa/keycloak-js`
that is close to a drop-in replacement for the code below — see the end of this file.

## Install

```bash
npm install keycloak-js
```

No peer dependencies, no build plugin. `keycloak-js` 26.2.4 is **ESM-only** (`"type": "module"`,
`exports` with no CommonJS entry) — fine under Vite, but a CJS test runner or an old bundler will
fail to resolve it.

## Step 1: The Keycloak client

A public client. See [`client-registration-mcp.md`](client-registration-mcp.md) or
[`client-registration.md`](client-registration.md) for the calls; what this framework needs:

| Setting | Value |
|---|---|
| Client authentication | **off** (public) |
| Standard flow | **on** |
| Valid redirect URIs | `http://localhost:5173/*` — **`keycloak-js` needs a wildcard** unless you pin `redirectUri` |
| Valid redirect URIs (also) | `http://localhost:5173/silent-check-sso.html` if you use silent check-SSO |
| Web origins | the app's origin, e.g. `http://localhost:5173` |

> ⚠️ **Why the wildcard.** `keycloak-js` computes its redirect URI as
> `options.redirectUri || this.redirectUri || location.href` — the page the user was on. So an app
> with client-side routes redirects back to `/orders`, `/settings`, `/anything`, and an exactly
> registered URI matches none of them. Registering `/*` is the documented cost of that design.
>
> **Narrow it in production.** Either register the handful of real landing paths, or pass a fixed
> `redirectUri` to `init()` so every login returns to one registered URL and your router restores
> the deep link. Never register `*` alone. A permissive redirect list on a public client is a real
> attack surface, not a style preference — see [`pattern-common-errors.md`](pattern-common-errors.md).

PKCE needs no configuration: `pkceMethod` defaults to `'S256'`. Passing `pkceMethod: false` disables
it, which for a public client is a downgrade — don't.

## Step 2: `public/silent-check-sso.html`

Only needed if you use `onLoad: 'check-sso'` with silent restoration. Create this file **verbatim**
and register its URL as a valid redirect URI:

```html
<!doctype html>
<html>
<body>
    <script>
        parent.postMessage(location.href, location.origin);
    </script>
</body>
</html>
```

It must be a **static file in `public/`**, not a Vue route. Keycloak redirects a hidden iframe to
it; if your SPA's history fallback serves `index.html` there instead, the app boots inside the
iframe and the handshake never completes.

> ⚠️ Silent check-SSO uses a hidden cross-site iframe, which browsers that block third-party
> cookies will break. `keycloak-js` falls back to a full-page redirect
> (`silentCheckSsoFallback` defaults to `true`), so the user sees a flash rather than a failure.
> Skip the iframe entirely with `onLoad: 'login-required'` if every route needs a session.

## Step 3: `src/keycloak.ts`

```ts
import Keycloak from "keycloak-js";
import { reactive } from "vue";

export const keycloak = new Keycloak({
    url: import.meta.env.VITE_KEYCLOAK_URL,
    realm: import.meta.env.VITE_KEYCLOAK_REALM,
    clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID
});

export const auth = reactive({
    isAuthenticated: false,
    username: undefined as string | undefined,
    name: undefined as string | undefined,
    roles: [] as string[]
});

function sync() {
    auth.isAuthenticated = keycloak.authenticated ?? false;
    auth.username = keycloak.idTokenParsed?.preferred_username;
    auth.name = keycloak.idTokenParsed?.name;
    auth.roles = keycloak.tokenParsed?.realm_access?.roles ?? [];
}

export async function initKeycloak(): Promise<boolean> {
    if (keycloak.didInitialize) {
        return auth.isAuthenticated;
    }

    keycloak.onAuthSuccess = sync;
    keycloak.onAuthRefreshSuccess = sync;
    keycloak.onAuthLogout = sync;
    keycloak.onTokenExpired = () => {
        keycloak.updateToken(30).catch(() => keycloak.login());
    };

    const authenticated = await keycloak.init({
        onLoad: "check-sso",
        silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
        checkLoginIframe: false
    });

    sync();
    return authenticated;
}
```

```bash
# .env.local
VITE_KEYCLOAK_URL=https://auth.example.com
VITE_KEYCLOAK_REALM=myrealm
VITE_KEYCLOAK_CLIENT_ID=my-web-app
```

**`url` is the server root, without the realm.** `keycloak-js` takes `url` + `realm` + `clientId`
separately and builds `${url}/realms/${realm}/protocol/openid-connect/...` itself. This is the
opposite convention from `oidc-spa`, whose single `issuerUri` *includes* `/realms/<realm>` — mixing
them up produces a 404 on the authorization endpoint. On pre-Quarkus Keycloak the root ends in
`/auth`.

Two things that are load-bearing:

- **The `didInitialize` guard.** `keycloak.init()` must run exactly once per instance; a second call
  rejects. Vite HMR re-executes modules, so without the guard every hot reload throws.
- **`checkLoginIframe: false`.** The default is `true`, which polls a cross-site iframe every 5
  seconds to detect logout in other tabs. Under third-party cookie blocking that iframe silently
  fails and can log the user out. The `onTokenExpired` handler above covers renewal without it. Turn
  it back on only if Keycloak is same-site with the app and you need cross-tab logout.

**Tokens stay in memory.** `keycloak-js` does not persist them, and you should not add persistence —
`localStorage` hands any XSS a working credential. A page reload silently re-authenticates against
the Keycloak SSO session; that is the intended behaviour, see
[`pattern-integration-decision.md`](pattern-integration-decision.md).

## Step 4: `src/main.ts`

```ts
import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import { initKeycloak } from "./keycloak";

initKeycloak()
    .catch(error => console.error("Keycloak init failed", error))
    .finally(() => {
        createApp(App).use(router).mount("#app");
    });
```

Mounting **after** `init()` settles is what keeps components from ever seeing an indeterminate auth
state. `.finally()` rather than `.then()` — an unreachable Keycloak should still render the app so
it can show an error, not a blank page.

## Step 5: Protecting a route

```ts
// src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";
import { auth, keycloak } from "../keycloak";

const router = createRouter({
    history: createWebHistory(),
    routes: [
        { path: "/", component: () => import("../views/Home.vue") },
        {
            path: "/dashboard",
            component: () => import("../views/Dashboard.vue"),
            meta: { requiresAuth: true }
        },
        {
            path: "/admin",
            component: () => import("../views/Admin.vue"),
            meta: { requiresAuth: true, roles: ["admin"] }
        }
    ]
});

router.beforeEach(async to => {
    if (!to.meta.requiresAuth) return true;

    if (!auth.isAuthenticated) {
        await keycloak.login({ redirectUri: window.location.origin + to.fullPath });
        return false; // login() navigates away; nothing after this runs
    }

    const required = (to.meta.roles as string[] | undefined) ?? [];
    if (required.length > 0 && !required.some(role => keycloak.hasRealmRole(role))) {
        return { path: "/" };
    }

    return true;
});

export default router;
```

`keycloak.hasRealmRole(role)` and `keycloak.hasResourceRole(role, clientId)` read
`realm_access.roles` and `resource_access.<client>.roles` from the access token, so you don't have
to.

**Roles in the UI are for rendering, not for security.** Blocking a route is not authorization; the
API must validate independently — see [`pattern-token-validation.md`](pattern-token-validation.md).

## Step 6: Login, logout, and reading the user

```vue
<script setup lang="ts">
import { auth, keycloak } from "../keycloak";

const login = () => keycloak.login();
const register = () => keycloak.register();
const logout = () => keycloak.logout({ redirectUri: window.location.origin });
</script>

<template>
    <header v-if="auth.isAuthenticated">
        <span>{{ auth.name ?? auth.username }}</span>
        <button @click="logout">Log out</button>
    </header>
    <header v-else>
        <button @click="login">Log in</button>
        <button @click="register">Register</button>
    </header>
</template>
```

Wrap the calls in `<script setup>` rather than inlining them in `@click` — `window` is not in a
Vue template's scope, so `@click="keycloak.logout({ redirectUri: window.location.origin })"` fails
at render with `window is not defined`.

`register()` is a `keycloak-js` convenience that sends the user to the registration page instead of
the login page. `keycloak.accountManagement()` opens the account console.

Claims live on **`keycloak.idTokenParsed`** (profile: `name`, `email`, `preferred_username`) and
**`keycloak.tokenParsed`** (the access token: `realm_access.roles`, `resource_access`). Both are
plain objects with an index signature, so a custom claim reads without a cast.

## Step 7: Calling your API

```ts
export const fetchWithAuth: typeof fetch = async (input, init) => {
    if (keycloak.authenticated) {
        try {
            await keycloak.updateToken(30);
        } catch {
            await keycloak.login();
        }
        const headers = new Headers(init?.headers);
        headers.set("Authorization", `Bearer ${keycloak.token}`);
        init = { ...init, headers };
    }
    return fetch(input, init);
};
```

`updateToken(minValidity)` refreshes only if the token expires within `minValidity` seconds and
resolves to `true` if it actually refreshed. Call it **per request**; don't cache `keycloak.token`
in a variable, or you will send an expired token after the first refresh.

## Verify

1. `npm run build` succeeds.
2. Click login → you land on Keycloak → after authenticating you return to the app **logged in**.
3. The user's name renders from `auth.name`.
4. A protected route redirects when logged out and renders when logged in.
5. **In a real browser**, an API call carries `Authorization: Bearer …` and does not fail CORS.
6. Leave the tab idle past the access-token lifetime, then act — the request succeeds because
   `updateToken` refreshed, rather than 401-ing.

Step 5 is the one a scripted test cannot do for you. A server-side script never triggers a CORS
preflight, so a wrong `webOrigins` passes every automated check and fails only in the browser.

## If you have seen a different API

| What you may have seen | Status |
|---|---|
| `keycloak.init().success(…).error(…)` | **Gone.** The custom promise object was removed; `init()` returns a real `Promise<boolean>`. Use `await` / `.then()`. |
| `promiseType: 'native'` in `init()` | Gone with it — native promises are the only option. |
| `import Keycloak from 'keycloak-js/dist/keycloak.js'` | Deep imports are blocked by the `exports` map. Import the package root. |
| `Keycloak('/keycloak.json')` called without `new` | Still typed as a constructor: `new Keycloak(config)`. The config may be a path to a JSON file. |
| `flow: 'implicit'` / `'hybrid'` | Still in the types, but implicit is dead — removed from OAuth 2.1. Use the default `'standard'`. |
| `adapters` for Cordova | Still supported (`'cordova'`, `'cordova-native'`), but a native app belongs in `app:mobile-login`, not here. |
| `@dsb-norge/vue-keycloak-js`, `vue-keycloak-js` | Third-party Vue wrappers around `keycloak-js`. Not maintained by Keycloak; verify their upkeep before adopting one. Nothing in this file needs them. |
| `oidc-spa/vue` | **Never existed.** See "Why not `oidc-spa`" above. |

### The `oidc-spa` polyfill, if you want its security features

`oidc-spa` publishes a `keycloak-js`-shaped surface that is close to a drop-in swap, keeping the
code in this file while gaining DPoP, browser-runtime freeze, cross-tab login propagation, and
static (non-wildcard) redirect URIs:

```diff
-import Keycloak from "keycloak-js";
+import { Keycloak } from "oidc-spa/keycloak-js";
```

Note the **named** export — real `keycloak-js` has a default export, the polyfill does not, so a
mechanical find-and-replace of the package name alone will not compile. The polyfill is deliberately
non-exhaustive: implicit and hybrid flows are unavailable, PKCE cannot be disabled, and
`silentCheckSsoRedirectUri` / `responseMode` are dropped. UNVERIFIED: this file does not walk
through the polyfill end to end — treat the diff as a pointer to
`oidc-spa`'s "Migrating from Keycloak-js" guide, not as a verified migration.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid redirect_uri` before the login form | client-side route not covered by the registered URIs | register `http://localhost:5173/*`, or pin `redirectUri` in `init()` |
| `Invalid redirect_uri` **on logout only** | post-logout redirect not allowed | set Valid post logout redirect URIs on the client (`+` mirrors the login list) |
| Login works, then CORS error on the token call | `webOrigins` not set on the client | add the exact origin; redirect URIs do not imply origins |
| `A 'Keycloak' instance can only be initialized once` | `init()` ran twice — usually Vite HMR | keep the `didInitialize` guard from Step 3 |
| App renders inside the silent-SSO iframe; login never finishes | `silent-check-sso.html` is being served by the SPA fallback | put the real static file in `public/` and register its URL |
| User appears logged out at random | `checkLoginIframe` polling failing under third-party cookie blocking | `checkLoginIframe: false`, and see [`pattern-common-errors.md`](pattern-common-errors.md) |
| 401 from the API after the tab sat idle | a cached `keycloak.token` string | call `updateToken(30)` per request and read `keycloak.token` after it |
| `auth.name` is `undefined` but login worked | the claim isn't in the **ID token** | add a mapper in Keycloak (realm config — the `keycloak` skill), or read `keycloak.tokenParsed` |
| Roles empty though the user has them | reading `idTokenParsed` | realm roles live on `tokenParsed.realm_access.roles`, or use `hasRealmRole()` |
| `ERR_REQUIRE_ESM` / "Cannot use import statement outside a module" in tests | `keycloak-js` is ESM-only | run the test runner in ESM mode, or mock the module |
| Template shows stale auth state | a value read once instead of through `reactive` | read `auth.*` in the template; don't destructure the reactive object |
