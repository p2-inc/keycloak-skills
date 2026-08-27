# React SPA — login, logout and route protection with `oidc-spa`

## What this is

A browser-only React app (Vite, CRA, React Router) logging users into Keycloak with authorization
code + PKCE. The client is **public** — no secret ever reaches the bundle.

`oidc-spa` is Phase Two's house choice for SPAs. `keycloak-js` remains a supported alternative and
is the right call if you need its imperative API or already have it wired.

**Verified against `oidc-spa` 10.2.11** (npm `latest`, published 2026-08-01). Check the installed
version before trusting the API shape below — this library has had two breaking renames, see
"If you have seen a different API" at the end.

## Install

```bash
npm install oidc-spa zod
```

`zod` is optional but recommended — it validates the ID token's shape so a missing claim fails at
the boundary instead of as `undefined` three components deep. There are no required peer
dependencies.

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

## Step 2: `src/oidc.ts`

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
        decodedIdTokenSchema: z.object({
            sub: z.string(),
            name: z.string(),
            email: z.string().email().optional(),
            preferred_username: z.string().optional(),
            realm_access: z.object({ roles: z.array(z.string()) }).optional()
        })
    })
    .createUtils();

bootstrapOidc({
    implementation: "real",
    issuerUri: import.meta.env.VITE_OIDC_ISSUER_URI,
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID
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

## Step 3: `src/main.tsx`

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

## Step 4: Login, logout, and reading the user

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
Claims live on **`decodedIdToken`** — `.sub`, `.name`, `.email`, `.preferred_username`, and
`.realm_access?.roles` for Keycloak realm roles.

**Roles in the UI are for rendering, not for security.** Hiding a button is not authorization; the
API must validate independently — see [`pattern-token-validation.md`](pattern-token-validation.md).

## Step 5: Protecting a route

```tsx
import { withLoginEnforced } from "./oidc";

const Dashboard = withLoginEnforced(function Dashboard() {
    const { decodedIdToken } = useOidc({ assert: "user logged in" });
    return <h1>Hello {decodedIdToken.name}</h1>;
});
```

An unauthenticated visitor is redirected to Keycloak and returned to this route afterwards.

## Step 6: Calling your API

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

Two live documentation hazards, current as of 10.2.11:

- The docs' Keycloak page has typos — it prints `clientId! "myclient"` (should be `clientId:`) and
  misspells a realm as `myeralm`. Don't copy from it verbatim.
- The docs describe a `createUser` / `withUser` API that **does not exist in 10.2.11** — it is only
  in the `10.3.0-rc.4` prerelease. The docs are ahead of the stable release there.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid redirect_uri` before the login form | redirect URI missing its **trailing slash** | register `http://localhost:5173/`, with the slash |
| Login works, then CORS error on the token call | `webOrigins` not set on the client | add the exact origin; redirect URIs do not imply origins |
| `Cannot find module 'oidc-spa/react'` | v8 import against a v9/v10 install | use `oidc-spa/react-spa` and the builder API above |
| `decodedIdToken` is `undefined` | read without `assert: "user logged in"` | narrow with `assert`, or check `isUserLoggedIn` first |
| A claim is missing from `decodedIdToken` | the claim isn't in the **ID token** | add a mapper in Keycloak (realm config — the `keycloak` skill), or read it from the access token |
| `withLoginEnforced` is not exported | `.withAutoLogin()` was called | with auto-login every route already requires a session; drop the wrapper |
| Zod validation throws on login | the schema demands a claim Keycloak doesn't send | mark it `.optional()`, or add the mapper |
| Session drops after a few minutes | third-party cookie blocking | see the silent-renew section in [`pattern-common-errors.md`](pattern-common-errors.md) |
