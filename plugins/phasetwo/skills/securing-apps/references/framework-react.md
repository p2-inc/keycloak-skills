<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# React SPA — login, logout and route protection with `oidc-spa`

## What this is

A browser-only React app with a Vite `index.html` entry (TanStack Router, or React Router in data or declarative mode) logging users into Keycloak with authorization code + PKCE. The client is **public** — no secret ever reaches the bundle. React Router *framework mode* works but only partially protects the tokens; see "Choosing the router" below.

`oidc-spa` is Phase Two's house choice for SPAs. `keycloak-js` remains a supported alternative and
is the right call if you need its imperative API or already have it wired.

**Verified against `oidc-spa` 10.2.18** (npm `latest`, published 2026-10-12). Check the installed version before trusting the API shape below — this library has had two breaking renames, see "If you have seen a different API" at the end.

v11 is a release candidate (npm `next`) and changes this API substantially; everything here targets v10. Don't install `next`, and don't copy examples from the v11 pages of the docs site.

## Install

```bash
npm install oidc-spa zod
```

`zod` is optional but recommended — it validates the ID token's shape so a missing claim fails at the boundary instead of as `undefined` three components deep. See "The ID-token schema" below for how strict to make it. There are no required peer dependencies, but there is a required build step: the early init in Step 2.

## Step 1: The Keycloak client

A public client. See [`client-registration-mcp.md`](client-registration-mcp.md) or
[`client-registration.md`](client-registration.md) for the calls; what this framework needs:

| Setting | Value |
|---|---|
| Client authentication | **off** (public) |
| Standard flow | **on** |
| Valid redirect URIs | **must end with `/`** — e.g. `http://localhost:5173/` |
| Web origins | the app's origin, e.g. `http://localhost:5173` |

> ⚠️ **The trailing slash on the redirect URI is not optional for this library.** `oidc-spa`
> redirects back to a URL under the app's base path, and a redirect URI registered without the
> trailing slash fails to match. This produces `Invalid redirect_uri` on the Keycloak error page
> before login — see [`pattern-common-errors.md`](pattern-common-errors.md).

PKCE needs no configuration. It is automatic and cannot be disabled — the library enforces `S256`.

## Step 2: Run the early init before the app loads

`oidc-spa` v10 needs a few lines to run before any of your app's modules: they recognize a page load that is really a login round-trip, and they install the security defenses (runtime freeze, token substitution, DPoP) while the browser runtime is still untouched. **Without it the app renders a blank page**: initialization waits forever for the early init, every asset loads with a `200`, and the only clue is a console warning after three seconds, `oidc-spa: Setup error. oidcEarlyInit() wasn't called.`

**Vite — the plugin.** Nothing else to write:

```ts
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { oidcSpa } from "oidc-spa/vite-plugin";

export default defineConfig({
    plugins: [react(), oidcSpa()]
});
```

**Not Vite — split the entry.** Rename `src/main.tsx` to `src/main.lazy.tsx`, then:

```ts
// src/main.tsx
import { oidcEarlyInit } from "oidc-spa/entrypoint";

const { shouldLoadApp } = oidcEarlyInit({ BASE_URL: "/" });

if (shouldLoadApp) {
    import("./main.lazy");
}
```

**Several HTML entries.** The Vite plugin refuses a build whose `build.rollupOptions.input` lists more than one HTML file (`oidc-spa: Multiple HTML inputs detected`). Use the manual split above instead, in the entry module of every page that uses `oidc-spa`. A page that never logs anyone in doesn't need it.

### Choosing the router

The early init only protects tokens if it runs before every other module. That depends on who owns the entry point:

| Setup | Protection | Why |
|---|---|---|
| Vite `index.html` + `src/main.tsx`, with TanStack Router or React Router in **data** or **declarative** mode | full | your `main.tsx` is the entry; the plugin wraps it |
| React Router **framework mode** (`@react-router/dev`), `ssr: false` included | **partial** | the framework generates the client entry and loads app code before the early init runs |

The [`oidc-spa` React Router guide](https://docs.oidc-spa.dev/v/v10/integration-guides/react-router) says it directly: "The security features of `oidc-spa` are not fully effective with React Router Framework", because "React Router Framework does not expose a true client entrypoint", and "There's no workaround for this." Login still works in framework mode; what weakens is the guarantee that a compromised dependency can't tamper with the runtime first. For a new app, prefer a plain Vite `index.html` + `main.tsx` entry.

## Step 3: `src/oidc.ts`

`oidcSpa` is a **builder**, not a config function. Chain each method at most once, then
`createUtils()`:

```ts
import { oidcSpa } from "oidc-spa/react-spa";
import { z } from "zod";

export const {
    bootstrapOidc,
    useOidc,
    getOidc,
    withLoginEnforced,
    OidcInitializationGate
} = oidcSpa
    .withExpectedDecodedIdTokenShape({
        // Describe exactly the claims this app reads. See "The ID-token schema" below.
        decodedIdTokenSchema: z.object({
            sub: z.string(),
            preferred_username: z.string(),
            name: z.string(), // the realm's user profile requires first and last name
            email: z.string().optional(), // optional: some users in this realm have no email
            // Needs "Add to ID token" on the realm-roles mapper; Keycloak's default is access token only
            realm_access: z.object({ roles: z.array(z.string()) })
        })
    })
    .createUtils();

bootstrapOidc({
    implementation: "real",
    issuerUri: import.meta.env.VITE_OIDC_ISSUER_URI,
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID,
    debugLogs: import.meta.env.VITE_OIDC_SPA_DEBUG === "true"
});
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

Note `withLoginEnforced` and `enforceLogin` exist **only if you did not call `.withAutoLogin()`**.
With auto-login every route requires a session, so route-level enforcement is meaningless and those
helpers are removed from the returned type.

## Step 4: `src/main.tsx`

The wrapper is `OidcInitializationGate`. There is **no `OidcProvider`** in v10:

```tsx
import { OidcInitializationGate } from "./oidc";

ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <OidcInitializationGate>
            <BrowserRouter>
                <App />
            </BrowserRouter>
        </OidcInitializationGate>
    </React.StrictMode>
);
```

The gate holds rendering until the library has settled whether a session exists — which is why
components below it never see an indeterminate state.

## Step 5: Login, logout, and reading the user

```tsx
import { useOidc } from "./oidc";

function Header() {
    const { isUserLoggedIn } = useOidc();

    if (!isUserLoggedIn) {
        const { login } = useOidc({ assert: "user not logged in" });
        return <button onClick={() => login()}>Log in</button>;
    }

    const { decodedIdToken, logout } = useOidc({ assert: "user logged in" });
    return (
        <>
            <span>{decodedIdToken.name}</span>
            <button onClick={() => logout({ redirectTo: "home" })}>Log out</button>
        </>
    );
}
```

`assert` narrows the type so `decodedIdToken` and `logout` are available without optional chaining.
Claims live on **`decodedIdToken`**, typed by your schema — `.sub`, `.name`, `.email`, `.preferred_username`, and `.realm_access.roles` for Keycloak realm roles.

**Roles in the UI are for rendering, not for security.** Hiding a button is not authorization; the
API must validate independently — see [`pattern-token-validation.md`](pattern-token-validation.md).

## Step 6: Protecting a route

```tsx
import { withLoginEnforced } from "./oidc";

const Dashboard = withLoginEnforced(function Dashboard() {
    const { decodedIdToken } = useOidc({ assert: "user logged in" });
    return <h1>Hello {decodedIdToken.name}</h1>;
});
```

An unauthenticated visitor is redirected to Keycloak and returned to this route afterwards.

## Step 7: Calling your API

```ts
import { getOidc } from "./oidc";

export const fetchWithAuth: typeof fetch = async (input, init) => {
    const oidc = await getOidc();
    if (oidc.isUserLoggedIn) {
        const accessToken = await oidc.getAccessToken();
        const headers = new Headers(init?.headers);
        headers.set("Authorization", `Bearer ${accessToken}`);
        (init ??= {}).headers = headers;
    }
    return fetch(input, init);
};
```

`getAccessToken()` refreshes if needed, so call it per request rather than caching the string.

> The `react-spa` adapter exposes `getAccessToken()`. The **framework-agnostic core** adapter
> (`oidc-spa/core`, used by `framework-spa-js.md`) exposes `getTokens()` instead. Both are correct
> for their own adapter — don't mix them.

## Keycloak extras

`oidc-spa/keycloak` carries Keycloak-specific helpers:

```ts
import { createKeycloakUtils } from "oidc-spa/keycloak";

const keycloakUtils = createKeycloakUtils({ issuerUri });
keycloakUtils.getAccountUrl({ clientId, validRedirectUri, locale });   // account console
keycloakUtils.transformUrlBeforeRedirectForRegister;                   // "Register" button
```

Account actions (change password, update profile) go through
`goToAuthServer({ extraQueryParams: { kc_action: "UPDATE_PASSWORD" } })`.

## Hardening for production

### The ID-token schema: as strict as the app's needs

`withExpectedDecodedIdTokenShape` runs `decodedIdTokenSchema.parse()` on every ID token, and **a parse failure halts initialization**: `OidcInitializationGate` never renders its children. That is a feature. A token that doesn't match what the app expects should fail loudly at startup, where it is one obvious error, instead of breaking deep in the UI as an `undefined` name, an empty role list, or a permission check that silently denies.

So make the schema describe the claims the app actually relies on, as precisely as you can:

- **Required** wherever the app needs the claim. If a screen reads `realm_access.roles`, the schema requires it.
- **Exact types and nested shapes**: `z.array(z.string())`, not `z.any()`; the object inside `realm_access`, not just "an object".
- **Optional only when the IdP genuinely omits the claim for some users** — `email` for users who have none, a claim only some identity providers supply. Then the code handles its absence on purpose.
- `z.object` is right: it drops claims you didn't declare rather than rejecting them, so Keycloak adding `sid`, `acr` or `at_hash` doesn't break the app. Don't use `z.strictObject`, which would.

Don't make it lenient. `.catch()` turns a wrong claim into a silent `undefined`, `looseObject`/`.passthrough()` hands untyped claims to the app, and "only `sub` required" defers every mismatch to whichever component trips over it first. All three trade a clear startup error for a vague runtime one.

Keep it true:

- **Check it against a real token.** Set `debugLogs: true` (wired to `VITE_OIDC_SPA_DEBUG` above). On first init `oidc-spa` logs the decoded ID token **before and after** `decodedIdTokenSchema.parse()`, which shows exactly which claim is missing, renamed or shaped differently. Local only: the log is a user's claims.
- **Keep the Keycloak side in sync.** Every required claim needs a client scope and mapper that put it in the **ID token** (many mappers default to the access token only). The realm-roles mapper is the usual surprise.
- **Treat a schema change as part of any mapper change**, in the same pull request or release. Renaming, moving or removing a claim in Keycloak without updating the schema is exactly the outage the schema is there to catch before users do.

### UI parameters stay off silent requests

`oidc-spa` restores sessions with a silent, non-interactive authorization request (a hidden iframe when the app and Keycloak share a site). Give `extraQueryParams` a **getter** and return nothing for those:

```ts
bootstrapOidc({
    implementation: "real",
    issuerUri: import.meta.env.VITE_OIDC_ISSUER_URI,
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID,
    extraQueryParams: ({ isSilent }) => {
        if (isSilent) {
            return {}; // the silent request renders no UI
        }
        return { ui_locales: i18n.language }; // plus any theme or color-scheme hint your login theme reads
    }
});
```

Only UI hints belong in the getter: `ui_locales` and theme or color-scheme parameters. Anything that changes what *this* login does goes on the individual call, because the getter applies to every authorization request, the silent ones included:

```ts
// logged out: useOidc({ assert: "user not logged in" })
login({ extraQueryParams: { kc_idp_hint: "google" } });                 // a "Sign in with Google" button

// logged in: useOidc({ assert: "user logged in" })
goToAuthServer({ extraQueryParams: { prompt: "login" } });              // force re-authentication
goToAuthServer({ extraQueryParams: { kc_action: "UPDATE_PASSWORD" } }); // a required action
```

`kc_idp_hint` in the getter would stop users ever choosing another login method, and `prompt` there conflicts with the silent session check.

### Token substitution: a build-time allowlist

With `tokenSubstitution` on, app code only sees a placeholder access token and `oidc-spa` swaps the real one in at the network layer, **only** for trusted hosts; an authenticated request to any other host is blocked. The docs list `browserRuntimeFreeze` as a requirement for it:

```ts
// vite.config.ts
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { oidcSpa } from "oidc-spa/vite-plugin";

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), "VITE_");

    // Hosts that may receive the user's access token, from the same env the app calls them with.
    // Same origin is always allowed, and host filtering is off on localhost.
    const trustedExternalResourceServers = [env.VITE_API_URL, env.VITE_REPORTS_API_URL]
        .filter((url): url is string => !!url)
        .map(url => new URL(url).hostname);

    return {
        plugins: [
            react(),
            oidcSpa({
                browserRuntimeFreeze: { enabled: true },
                tokenSubstitution: { enabled: true, trustedExternalResourceServers }
            })
        ]
    };
});
```

- **The allowlist is fixed at build time.** Derive it from the same `VITE_*` URLs the app uses to reach its APIs, so a new environment can't drift from it.
- **Entries are hostnames, not URLs**: an exact host (`api.example.com`) or a subdomain wildcard (`*.example.com`). No scheme, port or path.
- **Avoid broad wildcards.** Each entry is a host that may receive a user's bearer token; `*.amazonaws.com` or `*.workers.dev` hands it to anyone's bucket or worker.
- **Same origin and localhost are implicit.** Don't list the app's own host; on `localhost`, `127.0.0.1` and `[::]` filtering is off entirely, so test the allowlist on a deployed build.
- Anything that needs the real token string breaks: displaying it, or sending it in a request body.

### DPoP

`oidcSpa({ DPoP: { enabled: true, mode: "auto" } })` binds the access token to a browser-held key and sends `Authorization: DPoP <token>` plus a `DPoP` proof header on every authenticated request. There is no per-host opt-out, so **every API that receives the token must accept DPoP before you turn it on**; the checklist for API owners is in [`pattern-token-validation.md`](pattern-token-validation.md#dpop-bound-tokens). Keycloak supports DPoP officially from 26.4.

### Analytics in `index.html` run twice

Scripts in `index.html` itself (an analytics tag, a chat widget) also load inside `oidc-spa`'s hidden session-check iframe, because the silent request redirects back to the app's own URL. That inflates page views and sends the authorization response URL to a third party. Guard them:

```html
<script>
    if (window.self === window.top) {
        // load analytics here
    }
</script>
```

Or initialize them from app code, which never runs in the iframe.

## Verify

1. `npm run build` succeeds.
2. Click login → you land on Keycloak → after authenticating you return to the app **logged in**.
3. The user's name renders from `decodedIdToken`.
4. A protected route redirects when logged out and renders when logged in.
5. **In a real browser**, an API call carries `Authorization: Bearer …` and does not fail CORS.

Step 5 is the one a scripted test cannot do for you. A server-side script never triggers a CORS
preflight, so a wrong `webOrigins` passes every automated check and fails only in the browser.

## If you have seen a different API

This library renamed its React entry point twice. If your memory or an older example disagrees with
the code above, the code above is right for v10:

| Old | Status |
|---|---|
| `createReactOidc` from `oidc-spa/react` | **Removed.** The entire `oidc-spa/react` entry point was deleted in v9. v8 and earlier only. |
| `createOidcProvider`, `createUseOidc` | v3-era. Gone. |
| `<OidcProvider>` | Never existed in v10 — the wrapper is `OidcInitializationGate`. |
| `trustedThirdPartyResourceServers` | Renamed to `trustedExternalResourceServers` in v10. |
| `enableTokenSubstitution` | Now `tokenSubstitution`, from `oidc-spa/token-substitution`. |

Live documentation hazards, current as of 10.2.18:

- The docs' Keycloak page has typos — it prints `clientId! "myclient"` (should be `clientId:`) and
  misspells a realm as `myeralm`. Don't copy from it verbatim.
- `createUser` / `withUser` **do not exist in 10.2.18**. They appeared in the `10.3.0` prereleases and belong to the v11 release-candidate API. Pages under `/docs/v11/` describe v11; use the v10 pages.
- The docs name the same things two ways. The security-features overview mentions `oidcSpaEarlyInit`; the real export is **`oidcEarlyInit`** from `oidc-spa/entrypoint`. The "talking to multiple APIs" page passes `disabledDPoP: true`; the real option is **`disableDPoP`** (TypeScript rejects the misspelling in an object literal; plain JavaScript silently ignores it). One page also writes `browserRuntimeFreeze.exclude`; the option is **`excludes`**.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid redirect_uri` before the login form | redirect URI missing its **trailing slash** | register `http://localhost:5173/`, with the slash |
| Login works, then CORS error on the token call | `webOrigins` not set on the client | add the exact origin; redirect URIs do not imply origins |
| `Cannot find module 'oidc-spa/react'` | v8 import against a v9/v10 install | use `oidc-spa/react-spa` and the builder API above |
| `decodedIdToken` is `undefined` | read without `assert: "user logged in"` | narrow with `assert`, or check `isUserLoggedIn` first |
| A claim is missing from `decodedIdToken` | the claim isn't in the **ID token** | add a mapper in Keycloak (realm config — the `keycloak` skill), or read it from the access token |
| `withLoginEnforced` is not exported | `.withAutoLogin()` was called | with auto-login every route already requires a session; drop the wrapper |
| Blank page, all assets `200`, `oidcEarlyInit() wasn't called` in the console | no early init | do Step 2; with several HTML inputs, use the manual split |
| Blank page with a Zod error in the console | the ID token doesn't match the schema — usually a mapper changed, or a client scope isn't assigned | read the before/after logs from `debugLogs: true`; fix the mapper or scope, or update the schema with it. Make the claim optional only if some users genuinely lack it |
| `oidc-spa: Blocked authed request to <host>` | token substitution: the host isn't in `trustedExternalResourceServers` | add the hostname (derived from the env that names that API), then rebuild |
| API returns `401` after enabling DPoP | that API doesn't accept the `DPoP` scheme yet | [`pattern-token-validation.md`](pattern-token-validation.md#dpop-bound-tokens) |
| Session drops after a few minutes | third-party cookie blocking | see the silent-renew section in [`pattern-common-errors.md`](pattern-common-errors.md) |
