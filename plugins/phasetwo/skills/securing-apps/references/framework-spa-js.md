<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Vanilla SPA — login, logout and route protection with no framework

## What this is

A browser-only app with **no UI framework** — plain TypeScript or JavaScript, a hand-rolled or
micro router, bundled by Vite/Rollup/esbuild or served as modules. Users log into Keycloak with
authorization code + PKCE. The client is **public** — no secret ever reaches the bundle.

Two libraries are correct here, and the choice is real:

| | `oidc-spa` core | `keycloak-js` |
|---|---|---|
| Import | `createOidc` from `oidc-spa/core` | default export of `keycloak-js` |
| Shape | one `await`, then an immutable `oidc` object | an instance you mutate and read |
| Redirect URIs | one exact URI ending in `/` | wildcard, or a pinned `redirectUri` |
| Extras | DPoP, runtime freeze, auto-logout countdown, cross-tab propagation | Keycloak's own library, `hasRealmRole`, authz endpoint |
| Choose it when | new app, you want the tighter defaults | already wired, or you need `keycloak-js` semantics |

This file leads with **`oidc-spa` core** — Phase Two's house choice — and covers `keycloak-js` at
the end. Neither is a fallback for the other.

**Verified against `oidc-spa` 10.2.11** (npm `latest`, published 2026-08-01) and **`keycloak-js`
26.2.4** (npm `latest`, published 2026-04-22). Check the installed version before trusting the API
shape below — `oidc-spa` has renamed entry points twice, see "If you have seen a different API".

If your app *does* have a framework, use its file instead:
[`framework-react.md`](framework-react.md), [`framework-angular.md`](framework-angular.md),
[`framework-vue.md`](framework-vue.md), [`framework-nextjs.md`](framework-nextjs.md). The core
adapter is also the right base for a framework `oidc-spa` has no adapter for (Svelte, Solid, Lit,
Vue) — you write the reactive bindings over the object this file builds.

## Install

```bash
npm install oidc-spa zod
```

`zod` is optional but recommended — it validates the ID token's shape so a missing claim fails at
the boundary instead of as `undefined` deep in a handler. Any object with a `parse(claims)` method
works; Zod is not required. There are no required peer dependencies.

## Step 1: The Keycloak client

A public client. See [`client-registration-mcp.md`](client-registration-mcp.md) or
[`client-registration.md`](client-registration.md) for the calls; what this framework needs:

| Setting | Value |
|---|---|
| Client authentication | **off** (public) |
| Standard flow | **on** |
| Valid redirect URIs | **must end with `/`** — e.g. `http://localhost:5173/` |
| Web origins | the app's origin, e.g. `http://localhost:5173` |

> ⚠️ **The trailing slash on the redirect URI is not optional for `oidc-spa`.** It redirects back to
> the app's base path, and a URI registered without the trailing slash fails to match. This produces
> `Invalid redirect_uri` on the Keycloak error page before login — see
> [`pattern-common-errors.md`](pattern-common-errors.md).

If the app is **not** hosted at the domain root, the redirect URI is the base path with its slash —
`https://example.com/dashboard/` — and that same path is what you pass as `BASE_URL` in Step 2.

PKCE needs no configuration. It is automatic and cannot be disabled — the library enforces `S256`.

Using `keycloak-js` instead? Its redirect URI rules are different — see
[the `keycloak-js` section](#alternative-keycloak-js).

## Step 2: Run `oidcEarlyInit()` before the app loads

`oidc-spa` needs a few lines to execute before your app does, so it can recognise a page load that
is really a login round-trip and skip booting the app for it. Pick **one** of three:

**Vite projects — the plugin.** Nothing else to write:

```ts
// vite.config.ts
import { defineConfig } from "vite";
import { oidcSpa } from "oidc-spa/vite-plugin";

export default defineConfig({
    plugins: [oidcSpa()]
});
```

**Not Vite, single entry point — split it.** Rename `src/main.ts` to `src/main.lazy.ts`, then:

```ts
// src/main.ts
import { oidcEarlyInit } from "oidc-spa/entrypoint";

const { shouldLoadApp } = oidcEarlyInit({
    BASE_URL: "/" // where the app is hosted; `process.env.PUBLIC_URL` or `import.meta.env.BASE_URL`
});

if (shouldLoadApp) {
    import("./main.lazy");
}
```

**Can't touch the entry file — call it inline.** Least good, and the library says so: it downgrades
the security posture relative to the other two and can conflict with a client-side router. Call
`oidcEarlyInit()` at the top of the same module as `createOidc()`, importing both from
`oidc-spa/core`.

## Step 3: `src/oidc.ts`

```ts
import { createOidc } from "oidc-spa/core";
import { z } from "zod";

const decodedIdTokenSchema = z.object({
    sub: z.string(),
    name: z.string(),
    email: z.string().email().optional(),
    preferred_username: z.string().optional(),
    realm_access: z.object({ roles: z.array(z.string()) }).optional()
});

const prOidc = createOidc({
    issuerUri: import.meta.env.VITE_OIDC_ISSUER_URI,
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID,
    decodedIdTokenSchema
});

export function getOidc() {
    return prOidc;
}
```

```bash
# .env.local
VITE_OIDC_ISSUER_URI=https://auth.example.com/realms/myrealm
VITE_OIDC_CLIENT_ID=my-web-app
```

**`issuerUri` includes `/realms/<realm>`.** Shape:
`https://<host><relative-path>/realms/<realm>` — the relative path is empty on modern Keycloak and
`/auth` on pre-Quarkus versions. Getting this wrong is the most common setup failure; the library
discovers every endpoint from it.

`createOidc` is **memoized** — calling it twice with the same `issuerUri` + `clientId` returns the
same promise rather than starting a second handshake. Exporting `getOidc()` over the raw promise is
still worth it: every consumer awaits the same object, and the module can't be imported for its side
effect alone.

Options worth knowing, all verified present in 10.2.11:

| Option | Effect |
|---|---|
| `scopes: string[]` | defaults to `["profile"]`; `openid` is added automatically |
| `autoLogin: true` | every page requires a session; `createOidc` then resolves to `Oidc.LoggedIn` |
| `extraQueryParams` | added to the authorization URL — e.g. `{ ui_locales: "fr" }`, `{ kc_idp_hint: "google" }` |
| `sessionRestorationMethod` | `"iframe"` / `"full page redirect"` / `"auto"` (default) |
| `idleSessionLifetimeInSeconds` | auto-logout after inactivity; inferred from the refresh token if omitted |
| `autoLogoutParams` | where to land on auto-logout, e.g. `{ redirectTo: "specific url", url: "/expired" }` |
| `debugLogs: true` | verbose console output while wiring this up |

## Step 4: Login, logout, and reading the user

The object is a **discriminated union** on `isUserLoggedIn`, and it does not mutate — the state
never flips without a full page load. Narrow once, then use it:

```ts
import { getOidc } from "./oidc";

const oidc = await getOidc();

if (oidc.isUserLoggedIn) {
    const decodedIdToken = oidc.getDecodedIdToken();
    renderUser(decodedIdToken.name);

    document.querySelector("#logout")!.addEventListener("click", () => {
        oidc.logout({ redirectTo: "home" });
    });
} else {
    document.querySelector("#login")!.addEventListener("click", () => {
        oidc.login({ doesCurrentHrefRequiresAuth: false });
    });
}
```

`doesCurrentHrefRequiresAuth` is not optional in practice, and it is the one parameter people get
wrong:

- **`false`** — the user clicked a Login button on a page they were allowed to see. The current URL
  stays in history.
- **`true`** — you are redirecting because the user landed on a page that requires a session. The
  current URL is *replaced*, so pressing Back after login doesn't bounce them into the login
  redirect again.

`login()` and `logout()` return `Promise<never>` — they navigate away, so nothing after them runs.

**Roles in the UI are for rendering, not for security.** Hiding a button is not authorization; the
API must validate independently — see [`pattern-token-validation.md`](pattern-token-validation.md).

## Step 5: Protecting a route in a hand-rolled router

There is no guard helper in the core adapter — protection is one `if`:

```ts
const PROTECTED = ["/dashboard", "/settings"];

export async function handleRoute(path: string) {
    const oidc = await getOidc();

    if (PROTECTED.includes(path) && !oidc.isUserLoggedIn) {
        await oidc.login({ doesCurrentHrefRequiresAuth: true });
        return; // never reached — login() navigates away
    }

    render(path);
}
```

For a role check, read the claims after narrowing:

```ts
if (!oidc.getDecodedIdToken().realm_access?.roles.includes("admin")) {
    render("/forbidden");
    return;
}
```

If *every* route needs a session, don't write the guard at all — pass `autoLogin: true` to
`createOidc` and the library handles it before your code runs.

## Step 6: Calling your API

The core adapter exposes **`getTokens()`**, which resolves to a token bundle:

```ts
export const fetchWithAuth: typeof fetch = async (input, init) => {
    const oidc = await getOidc();

    if (oidc.isUserLoggedIn) {
        const { accessToken } = await oidc.getTokens();
        const headers = new Headers(init?.headers);
        headers.set("Authorization", `Bearer ${accessToken}`);
        init = { ...init, headers };
    }

    return fetch(input, init);
};
```

`getTokens()` refreshes if needed, so call it per request rather than caching `accessToken`.

> **Three adapters, three shapes — don't mix them.** The core returns `getTokens()`;
> `oidc-spa/react-spa` returns `getAccessToken(): Promise<string>`
> ([`framework-react.md`](framework-react.md)); `oidc-spa/angular` returns
> `getAccessToken(): Promise<{ isUserLoggedIn, accessToken? }>`
> ([`framework-angular.md`](framework-angular.md)). Each is correct for its own adapter, and
> `getTokens` exists **only** on the logged-in variant of the union.

The bundle also carries `accessTokenExpirationTime`, `idToken`, `decodedIdToken`,
`decodedIdToken_original` (the untransformed payload, before your schema stripped it),
`issuedAtTime`, `getServerDateNow()` and — when the server issued one — `refreshToken` behind a
`hasRefreshToken: true` discriminant.

To react to renewals without polling:

```ts
const { unsubscribeFromTokensChange } = oidc.subscribeToTokensChange(tokens => {
    console.log("new access token", tokens.accessToken);
});
```

## Keycloak extras

`oidc-spa/keycloak` carries Keycloak-specific helpers, behind a guard so the same code works against
a non-Keycloak issuer:

```ts
import { createKeycloakUtils, isKeycloak } from "oidc-spa/keycloak";

const keycloakUtils = isKeycloak({ issuerUri: oidc.issuerUri })
    ? createKeycloakUtils({ issuerUri: oidc.issuerUri })
    : undefined;

keycloakUtils?.getAccountUrl({
    clientId: oidc.clientId,
    validRedirectUri: oidc.validRedirectUri,
    locale: "en"
});
```

Register button:

```ts
oidc.login({
    doesCurrentHrefRequiresAuth: false,
    transformUrlBeforeRedirect: keycloakUtils!.transformUrlBeforeRedirectForRegister
});
```

`createKeycloakUtils` also gives `adminConsoleUrl`, `fetchUserProfile({ accessToken })` and
`fetchUserInfo({ accessToken })`. Account actions (change password, update profile) go through
`oidc.goToAuthServer({ extraQueryParams: { kc_action: "UPDATE_PASSWORD" } })`, and the outcome comes
back on `oidc.backFromAuthServer`.

## Developing without an auth server

```ts
import { createMockOidc } from "oidc-spa/core-mock";

const prOidc = !import.meta.env.VITE_OIDC_ISSUER_URI
    ? createMockOidc({
          isUserInitiallyLoggedIn: false,
          mockedParams: { issuerUri: "https://auth.example.com/realms/myrealm", clientId: "my-web-app" },
          mockedTokens: { decodedIdToken: { sub: "1", name: "John Doe" } }
      })
    : createOidc({ /* … */ });
```

> ⚠️ **The published docs' mock example does not compile against 10.2.11.** It passes `mockedUser`
> and a `createUser` import. Verified against the 10.2.11 tarball: neither exists — no `createUser`,
> no `withUser`, no `mockedUser` anywhere in the package. Those are `10.3.0-rc.4` APIs and the docs
> are ahead of the stable release. The real 10.2.11 parameters are the ones above:
> `mockedParams`, `mockedTokens`, `BASE_URL`, `autoLogin`, `postLoginRedirectUrl`,
> `isUserInitiallyLoggedIn`.

## Alternative: `keycloak-js`

Same job, Keycloak's own library, no build-time step:

```bash
npm install keycloak-js
```

```ts
import Keycloak from "keycloak-js";

export const keycloak = new Keycloak({
    url: "https://auth.example.com",   // server root — NOT including /realms/<realm>
    realm: "myrealm",
    clientId: "my-web-app"
});

if (!keycloak.didInitialize) {
    keycloak.onTokenExpired = () => {
        keycloak.updateToken(30).catch(() => keycloak.login());
    };
    await keycloak.init({
        onLoad: "check-sso",
        silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
        checkLoginIframe: false
    });
}

if (keycloak.authenticated) {
    await keycloak.updateToken(30);
    fetch("/api/orders", { headers: { Authorization: `Bearer ${keycloak.token}` } });
}
```

Four differences that bite when switching between the two:

1. **`url` is the server root, without the realm.** `keycloak-js` composes
   `${url}/realms/${realm}/…` itself. `oidc-spa`'s single `issuerUri` *includes* `/realms/<realm>`.
   Mixing them up produces a 404 on the authorization endpoint.
2. **Redirect URIs need a wildcard.** `keycloak-js` redirects to
   `options.redirectUri || this.redirectUri || location.href` — the page the user was on — so
   register `http://localhost:5173/*`, or pin `redirectUri` in `init()` and register that one URL.
   Never register `*` alone.
3. **`init()` runs exactly once per instance**; a second call rejects. Guard on `didInitialize` or
   HMR will throw.
4. **`checkLoginIframe` defaults to `true`** and polls a cross-site iframe every 5s. Under
   third-party cookie blocking it fails silently and can log the user out. Set it `false` unless
   Keycloak is same-site.

Silent check-SSO also needs a **static** `public/silent-check-sso.html`, registered as a valid
redirect URI. Full walkthrough, including that file's exact contents and the reactive-store pattern,
is in [`framework-vue.md`](framework-vue.md) — the Keycloak-side wiring there is framework-neutral.

There is also `oidc-spa/keycloak-js`, a near-drop-in polyfill of the `keycloak-js` surface that
gives you `oidc-spa`'s security features without rewriting. Note it is a **named** export
(`import { Keycloak } from "oidc-spa/keycloak-js"`) where real `keycloak-js` is a default export, and
it deliberately drops implicit/hybrid flows, disabling PKCE, `silentCheckSsoRedirectUri` and
`responseMode`.

## Verify

1. The bundle builds.
2. Click login → you land on Keycloak → after authenticating you return to the app **logged in**.
3. The user's name renders from `getDecodedIdToken()`.
4. A protected path redirects when logged out and renders when logged in.
5. Pressing **Back** after logging into a protected page does not bounce you into the login
   redirect — that is `doesCurrentHrefRequiresAuth: true` working.
6. **In a real browser**, an API call carries `Authorization: Bearer …` and does not fail CORS.

Step 6 is the one a scripted test cannot do for you. A server-side script never triggers a CORS
preflight, so a wrong `webOrigins` passes every automated check and fails only in the browser.

## If you have seen a different API

`oidc-spa` renamed its entry points twice; the core is where the older names are most often
mis-remembered:

| Old | Status |
|---|---|
| `createOidc` from `oidc-spa` (bare) | The package root exports the **entrypoint** helpers. Import `createOidc` from `oidc-spa/core`. |
| `createReactOidc` from `oidc-spa/react` | **Removed.** The entire `oidc-spa/react` entry point was deleted in v9. |
| `createOidcProvider`, `createUseOidc` | v3-era. Gone. |
| `oidc.getAccessToken()` on the core object | Not on the core adapter — that's `react-spa`/`angular`. The core has `getTokens()`. |
| `homeUrl` | Now `BASE_URL`, on `oidcEarlyInit()` / the Vite plugin / `createOidc`. |
| `trustedThirdPartyResourceServers` | Renamed to `trustedExternalResourceServers` in v10. |
| `enableTokenSubstitution` | Now `tokenSubstitution`, from `oidc-spa/token-substitution`. |
| `createUser` / `withUser` / `mockedUser` | **Not in 10.2.11.** `10.3.0-rc.4` only, despite the docs. |
| `keycloak.init().success(…)` | `keycloak-js` removed its custom promise object; `init()` returns `Promise<boolean>`. |

The docs' Keycloak page also has typos — it prints `clientId! "myclient"` (should be `clientId:`)
and misspells a realm as `myeralm`. Don't copy from it verbatim.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid redirect_uri` before the login form | redirect URI missing its **trailing slash** | register `http://localhost:5173/`, with the slash |
| `Invalid redirect_uri`, app not at the domain root | `BASE_URL` and the registered URI disagree | both must be the base path with its slash, e.g. `/dashboard/` |
| Login works, then CORS error on the token call | `webOrigins` not set on the client | add the exact origin; redirect URIs do not imply origins |
| `Cannot find module 'oidc-spa/react'` | v8 import against a v9/v10 install | not a vanilla entry point at all; use `oidc-spa/core` |
| `oidc.getTokens is not a function` | called on the union without narrowing | check `if (oidc.isUserLoggedIn)` first — `getTokens` exists only on that branch |
| `oidc.getAccessToken is not a function` | mixed a framework adapter's API into the core | the core adapter's method is `getTokens()` |
| Back button after login re-triggers the login redirect | `doesCurrentHrefRequiresAuth: false` on a guard redirect | pass `true` when redirecting *because* the page needs auth |
| Login round-trips boot the whole app twice | `oidcEarlyInit()` / the Vite plugin not wired | do Step 2 |
| Zod validation throws on login | the schema demands a claim Keycloak doesn't send | mark it `.optional()`, or add the mapper |
| A claim is missing from `decodedIdToken` | the claim isn't in the **ID token** | add a mapper in Keycloak (realm config — the `keycloak` skill), or read `decodedIdToken_original` / the access token |
| Session drops after a few minutes | third-party cookie blocking | `sessionRestorationMethod: "full page redirect"`, and see [`pattern-common-errors.md`](pattern-common-errors.md) |
| Tokens land in `localStorage` unexpectedly | `sessionRestorationMethod: "full page redirect"` with multiple OIDC clients | documented behaviour of that mode; use `"auto"` if same-site allows it |
