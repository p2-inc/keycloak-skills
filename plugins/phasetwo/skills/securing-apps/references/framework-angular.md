# Angular SPA — login, logout and route protection with `oidc-spa/angular`

## What this is

A browser-only Angular app (Angular CLI, standalone components, `provideRouter`) logging users into
Keycloak with authorization code + PKCE. The client is **public** — no secret ever reaches the
bundle.

`oidc-spa` ships a **dedicated Angular adapter** at `oidc-spa/angular`, with its own docs guide and
two maintained examples. It is not the React adapter with a wrapper: it is an abstract Angular
service you subclass, plus a `provideAppInitializer`-based provider, an `HttpInterceptorFn`, and a
`CanActivateFn` guard. [`keycloak-angular`](#if-you-have-seen-a-different-api) remains a supported
alternative.

**Verified against `oidc-spa` 10.2.11** (npm `latest`, published 2026-08-01), whose Angular examples
target Angular 20.3. Check the installed version before trusting the API shape below — this library
has renamed entry points twice, see "If you have seen a different API" at the end.

> ⚠️ **`oidc-spa/angular` requires Angular ≥ 19.** The adapter's `provide()` is built on
> `provideAppInitializer`, which Angular added in 19.0.0. On Angular 18 or earlier the import
> resolves but `provideAppInitializer` is `undefined` and bootstrap throws at runtime. Use
> `keycloak-angular` on those versions instead.

## Install

```bash
npm install oidc-spa zod
```

`zod` is optional but recommended — it validates the ID token's shape so a missing claim fails at
the boundary instead of as `undefined` three components deep. `@angular/core`, `@angular/common`,
`@angular/router` and `rxjs` are **optional peer dependencies** already in any Angular project;
nothing extra to install.

## Step 1: The Keycloak client

A public client. See [`client-registration-mcp.md`](client-registration-mcp.md) or
[`client-registration.md`](client-registration.md) for the calls; what this framework needs:

| Setting | Value |
|---|---|
| Client authentication | **off** (public) |
| Standard flow | **on** |
| Valid redirect URIs | **must end with `/`** — e.g. `http://localhost:4200/` |
| Web origins | the app's origin, e.g. `http://localhost:4200` |

> ⚠️ **The trailing slash on the redirect URI is not optional for this library.** `oidc-spa` always
> redirects back to the app's base path, and a redirect URI registered without the trailing slash
> fails to match. This produces `Invalid redirect_uri` on the Keycloak error page before login —
> see [`pattern-common-errors.md`](pattern-common-errors.md).

You do **not** need a wildcard redirect URI. That is the deliberate difference from `keycloak-js`,
which redirects back to whatever page the user was on and therefore forces
`https://app.example.com/*`.

PKCE needs no configuration. It is automatic and cannot be disabled — the library enforces `S256`.

## Step 2: Run `oidcEarlyInit()` before Angular boots

Split the entry point. Rename `src/main.ts` to `src/main.lazy.ts`, then create a new `src/main.ts`:

```bash
mv src/main.ts src/main.lazy.ts
```

```ts
// src/main.ts
import { oidcEarlyInit } from "oidc-spa/entrypoint";

const { shouldLoadApp } = oidcEarlyInit({
    BASE_URL: "/" // the path where the app is hosted
});

if (shouldLoadApp) {
    import("./main.lazy");
}
```

```ts
// src/main.lazy.ts  — this is your original main.ts, unchanged
import { bootstrapApplication } from "@angular/platform-browser";
import { appConfig } from "./app/app.config";
import { App } from "./app/app";

bootstrapApplication(App, appConfig).catch(err => console.error(err));
```

**Skipping this step is the most common Angular-specific failure.** During a login round-trip the
browser lands back on the app inside a redirect or an iframe that exists only to complete the OIDC
handshake. `oidcEarlyInit()` detects that case and returns `shouldLoadApp: false`, so Angular never
bootstraps for a throwaway navigation. Without the split, every silent renew pays a full Angular
bootstrap and the handshake is measurably slower.

## Step 3: `src/app/services/oidc.service.ts`

The adapter is an **abstract class you extend** — there is no `createOidc`-style factory here:

```ts
import { Injectable } from "@angular/core";
import { AbstractOidcService } from "oidc-spa/angular";
import { HttpContextToken } from "@angular/common/http";
import { z } from "zod";

const decodedIdTokenSchema = z.object({
    sub: z.string(),
    name: z.string(),
    email: z.string().email().optional(),
    preferred_username: z.string().optional(),
    realm_access: z.object({ roles: z.array(z.string()) }).optional()
});

export type DecodedIdToken = z.infer<typeof decodedIdTokenSchema>;

@Injectable({ providedIn: "root" })
export class Oidc extends AbstractOidcService<DecodedIdToken> {
    override decodedIdTokenSchema = decodedIdTokenSchema;
}

export const REQUIRE_ACCESS_TOKEN = new HttpContextToken<boolean>(() => false);
```

`@Injectable({ providedIn: "root" })` is required — `Oidc.provide()` registers the class itself as a
provider and then injects it from the app initializer.

The overridable fields and their defaults:

| Field | Default | Effect |
|---|---|---|
| `decodedIdTokenSchema` | `undefined` | any `{ parse(claims) }` object; Zod is not required |
| `autoLogin` | `false` | `true` makes every route require a session |
| `providerAwaitsInitialization` | `true` | `false` renders the app before auth settles |
| `mockDecodedIdToken` | `undefined` | claims returned by `provideMock()` |

## Step 4: `src/app/app.config.ts`

```ts
import { ApplicationConfig, inject } from "@angular/core";
import { provideHttpClient, withInterceptors } from "@angular/common/http";
import { provideRouter } from "@angular/router";
import { routes } from "./app.routes";
import { Oidc, REQUIRE_ACCESS_TOKEN } from "./services/oidc.service";

export const appConfig: ApplicationConfig = {
    providers: [
        provideHttpClient(
            withInterceptors([
                Oidc.createBearerInterceptor({
                    shouldInjectAccessToken: req => req.context.get(REQUIRE_ACCESS_TOKEN)
                })
            ])
        ),
        provideRouter(routes),
        Oidc.provide({
            issuerUri: "https://auth.example.com/realms/myrealm",
            clientId: "my-web-app"
        })
    ]
};
```

**`issuerUri` includes `/realms/<realm>`.** Shape:
`https://<host><relative-path>/realms/<realm>` — the relative path is empty on modern Keycloak and
`/auth` on pre-Quarkus versions. Getting this wrong is the most common setup failure; the library
discovers every endpoint from it.

`provide()` also takes an **async getter**, for apps that fetch their config at runtime:

```ts
Oidc.provide(async () => {
    const http = inject(HttpClient);
    const config = await firstValueFrom(http.get<{ issuerUri: string; clientId: string }>("./oidc-config.json"));
    return { issuerUri: config.issuerUri, clientId: config.clientId };
});
```

For tests and Storybook, swap it for `Oidc.provideMock({ isUserInitiallyLoggedIn: true })` — same
providers, no auth server.

## Step 5: Protecting a route

`enforceLoginGuard` is a **static getter** that returns a `CanActivateFn`. Reference it, don't call
it:

```ts
import { Routes } from "@angular/router";
import { Oidc } from "./services/oidc.service";

export const routes: Routes = [
    { path: "", loadComponent: () => import("./pages/public").then(c => c.Public) },
    {
        path: "protected",
        loadComponent: () => import("./pages/protected").then(c => c.Protected),
        canActivate: [Oidc.enforceLoginGuard]
    },
    { path: "**", redirectTo: "" }
];
```

An unauthenticated visitor is redirected to Keycloak and returned to this route afterwards.

For a role check, `await` the guard first, then read the claims:

```ts
canActivate: [
    async route => {
        const oidc = inject(Oidc);
        const router = inject(Router);

        await Oidc.enforceLoginGuard(route);

        if ((oidc.$decodedIdToken().realm_access?.roles ?? []).includes("admin")) {
            return true;
        }
        return new RedirectCommand(router.parseUrl("/"));
    }
]
```

**Roles in the UI are for rendering, not for security.** Hiding a route is not authorization; the
API must validate independently — see [`pattern-token-validation.md`](pattern-token-validation.md).

## Step 6: Login, logout, and reading the user

Inject the service and read it directly in the template:

```ts
import { Component, inject } from "@angular/core";
import { Oidc } from "./services/oidc.service";

@Component({
    selector: "app-header",
    template: `
        @if (oidc.isUserLoggedIn) {
            <span>{{ oidc.$decodedIdToken().name }}</span>
            <button (click)="oidc.logout({ redirectTo: 'home' })">Log out</button>
        } @else {
            <button (click)="oidc.login()">Log in</button>
        }
    `
})
export class Header {
    oidc = inject(Oidc);
}
```

| Member | Type | Notes |
|---|---|---|
| `isUserLoggedIn` | `boolean` getter | never indeterminate once initialization settles |
| `$decodedIdToken()` | `Signal<DecodedIdToken>` | the Angular-idiomatic read |
| `decodedIdToken$` | `ReadonlyBehaviorSubject` | for RxJS pipelines / `| async` |
| `$secondsLeftBeforeAutoLogout()` | `Signal<number \| null>` | drives a "you will be logged out" overlay |
| `prInitialized` | `Promise<true>` | resolves when initialization has settled |

Reading `$decodedIdToken()` **before initialization completes throws** with a message naming the
caller. That only happens if you set `providerAwaitsInitialization = false`; with the default `true`
the app initializer already awaited it.

## Step 7: Calling your API

The interceptor from Step 4 attaches the bearer token. Mark the requests that need it:

```ts
import { HttpClient, HttpContext } from "@angular/common/http";
import { inject, Injectable } from "@angular/core";
import { REQUIRE_ACCESS_TOKEN } from "./oidc.service";

@Injectable({ providedIn: "root" })
export class OrderService {
    private readonly http = inject(HttpClient);

    getOrders() {
        return this.http.get<Order[]>("https://api.example.com/orders", {
            context: new HttpContext().set(REQUIRE_ACCESS_TOKEN, true)
        });
    }
}
```

Prefer this per-request `HttpContext` token over URL matching in `shouldInjectAccessToken`. A regex
over `req.url` is the familiar pattern but it silently attaches the token to anything the regex
happens to match — including a third-party host that later moves onto a matching domain.

Outside `HttpClient`, `getAccessToken()` returns a **discriminated object**, not a string:

```ts
const { isUserLoggedIn, accessToken } = await oidc.getAccessToken();
if (isUserLoggedIn) {
    headers.set("Authorization", `Bearer ${accessToken}`);
}
```

> Three adapters, three shapes — don't mix them. `oidc-spa/angular` returns
> `{ isUserLoggedIn, accessToken? }`; `oidc-spa/react-spa` returns `Promise<string>`
> ([`framework-react.md`](framework-react.md)); the framework-agnostic core returns `getTokens()`
> ([`framework-spa-js.md`](framework-spa-js.md)). Each is correct for its own adapter.

## Keycloak extras

`oidc-spa/keycloak` carries Keycloak-specific helpers:

```ts
import { createKeycloakUtils } from "oidc-spa/keycloak";

export class App {
    oidc = inject(Oidc);
    keycloakUtils = createKeycloakUtils({ issuerUri: this.oidc.issuerUri });
}
```

```html
<button (click)="oidc.login({
    transformUrlBeforeRedirect: keycloakUtils.transformUrlBeforeRedirectForRegister
})">Register</button>
```

`keycloakUtils.getAccountUrl({ clientId, validRedirectUri, locale })` builds the account-console
link. Account actions (change password, update profile) go through
`oidc.goToAuthServer({ extraQueryParams: { kc_action: "UPDATE_PASSWORD" } })`.

## Verify

1. `ng build` succeeds.
2. Click login → you land on Keycloak → after authenticating you return to the app **logged in**.
3. The user's name renders from `$decodedIdToken()`.
4. A protected route redirects when logged out and renders when logged in.
5. **In a real browser**, a marked `HttpClient` call carries `Authorization: Bearer …` and does not
   fail CORS — and an *unmarked* call does **not** carry it.

Step 5 is the one a scripted test cannot do for you. A server-side script never triggers a CORS
preflight, so a wrong `webOrigins` passes every automated check and fails only in the browser.

## If you have seen a different API

`oidc-spa` renamed its framework entry points twice, and Angular has a second, older Keycloak
library that people confuse with it:

| What you may have seen | Status |
|---|---|
| `createReactOidc` from `oidc-spa/react` | **Removed.** The whole `oidc-spa/react` entry point was deleted in v9. Not an Angular API at all. |
| `createOidcProvider`, `createUseOidc` | v3-era `oidc-spa`. Gone. |
| `oidc-spa/vue` | **Never existed.** `oidc-spa` has no Vue adapter — see [`framework-vue.md`](framework-vue.md). |
| `trustedThirdPartyResourceServers` | Renamed to `trustedExternalResourceServers` in v10. |
| `keycloak-angular` + `KeycloakService` | Still published (22.0.0, 2026-06-15) but `KeycloakService` is the **deprecated** part of it. |

**`keycloak-angular` is a live alternative, not a dead adapter.** v22 requires `@angular/*` ^22 and
`keycloak-js` ^18–^26, and its current API is `provideKeycloak()`, `createAuthGuard()`,
`includeBearerTokenInterceptor` + `INCLUDE_BEARER_TOKEN_INTERCEPTOR_CONFIG`,
`createInterceptorCondition()`, `withAutoRefreshToken()` and `KEYCLOAK_EVENT_SIGNAL`. The
`KeycloakService` / `KeycloakAuthGuard` / `KeycloakBearerInterceptor` / `KeycloakAngularModule`
surface is deprecated in favour of those. Choose it if you are already on it or you need
`keycloak-js` semantics underneath; choose `oidc-spa/angular` for a new app.

Two live documentation hazards, current as of 10.2.11:

- The docs describe a `createUser` / `withUser` API and a `mockedUser` option that **do not exist in
  10.2.11** — they are only in the `10.3.0-rc.4` prerelease. Confirmed absent from the published
  10.2.11 tarball. The docs are ahead of the stable release there.
- The docs' Keycloak page has typos — it prints `clientId! "myclient"` (should be `clientId:`) and
  misspells a realm as `myeralm`. Don't copy from it verbatim.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid redirect_uri` before the login form | redirect URI missing its **trailing slash** | register `http://localhost:4200/`, with the slash |
| Login works, then CORS error on the token call | `webOrigins` not set on the client | add the exact origin; redirect URIs do not imply origins |
| `provideAppInitializer is not a function` at bootstrap | Angular < 19 | upgrade to Angular ≥ 19, or use `keycloak-angular` |
| Login round-trips are slow; Angular bootstraps twice per login | `oidcEarlyInit()` split from Step 2 skipped | add `src/main.ts` → `src/main.lazy.ts` |
| Reading `$decodedIdToken()` throws "not yet initialized" | `providerAwaitsInitialization = false` and the read happened too early | leave it `true`, or gate on `prInitialized` |
| `NullInjectorError: No provider for Oidc` | the subclass is missing `@Injectable({ providedIn: "root" })` | add the decorator |
| Console warns "Probable deadlock detected" | a request needing a token is fired from inside `provide(async () => …)` | return `false` early in `shouldInjectAccessToken` for that request |
| `OidcAccessedTooEarlyError` from the interceptor | a token-requiring request fired while logged out | guard the route, or gate the call on `isUserLoggedIn` |
| Zod validation throws on login | the schema demands a claim Keycloak doesn't send | mark it `.optional()`, or add the mapper |
| A claim is missing from `$decodedIdToken()` | the claim isn't in the **ID token** | add a mapper in Keycloak (realm config — the `keycloak` skill), or read it from the access token |
| Session drops after a few minutes | third-party cookie blocking | set `sessionRestorationMethod: "full page redirect"`, and see [`pattern-common-errors.md`](pattern-common-errors.md) |
