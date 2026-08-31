<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Next.js — server-side login and route protection with the Auth.js Keycloak provider

## What this is

A Next.js App Router app where **the server holds the tokens** and the browser gets an `HttpOnly`
session cookie. This is the BFF pattern from
[`pattern-integration-decision.md`](pattern-integration-decision.md), and it is the reason Next.js
gets a different library from every other file in this skill: Next.js *has* a server, so the browser
never needs to hold a token at all.

The client is **confidential** — it has a secret, and the secret lives in the server's environment.

**Verified against `next-auth` 5.0.0-beta.32** (npm `beta`, published 2026-07-20) and its bundled
`@auth/core` 0.41.3. Every import path, export name and env var below was read from those published
packages.

> 🚨 **Auth.js v5 is still in beta, and `npm install next-auth` gives you v4.**
> The npm dist-tags as of this writing: `latest` = **4.24.15**, `beta` = **5.0.0-beta.32**.
> The install command is `npm install next-auth@beta` — *with the tag*. Install without it and you
> get v4, whose API is entirely different: every import and export in this file will fail at build
> time with errors that look like the package is broken rather than the wrong major. This is the
> single most common way this integration goes wrong, because "NextAuth v5" is what everyone writes
> and `next-auth@beta` is what everyone forgets to type.

### Why not `oidc-spa`

`oidc-spa` **works** in Next.js and ships a real, maintained `next.js` guide and example. Its own
docs are candid about the trade-off rather than refusing the use case: authentication happens in
the browser, the server rendering your pages cannot know who the user is, and that removes most of
the SSR benefits — the app effectively behaves like an SPA.

So the recommendation is **Auth.js, because `oidc-spa` downgrades a Next.js app to an SPA**, not
because `oidc-spa` is unsupported. If you have a Next.js app that is really a client-rendered SPA
with a Next shell, and you want `oidc-spa`'s security features, that guide is a legitimate path —
follow [`framework-spa-js.md`](framework-spa-js.md) for the core API and `oidc-spa`'s
`instrumentation-client.ts` wiring for the early-init step.

## Install

```bash
npm install next-auth@beta
npx auth secret
```

`npx auth secret` generates `AUTH_SECRET` and writes it into your `.env` file. It is the key that
encrypts the session JWT — without it, Auth.js throws `MissingSecret` at the first request.

## Step 1: The Keycloak client

Unlike every SPA in this skill, this one is **confidential**. See
[`client-registration-mcp.md`](client-registration-mcp.md) or
[`client-registration.md`](client-registration.md) for the calls:

| Setting | Value |
|---|---|
| Client authentication | **on** (confidential — it gets a secret) |
| Standard flow | **on** |
| Valid redirect URIs | `http://localhost:3000/api/auth/callback/keycloak` — **exact, no trailing slash, no wildcard** |
| Valid post logout redirect URIs | `http://localhost:3000` (or `+`) — only if you add the logout step below |
| Web origins | **leave empty** |

> ⚠️ **The callback path is fixed by the library**: `{origin}{basePath}/callback/{providerId}`, where
> `basePath` defaults to `/api/auth` in `next-auth` and the provider id is the literal string
> `keycloak`. Register it character for character. Getting it wrong produces `Invalid redirect_uri`
> on the Keycloak error page before the login form — see
> [`pattern-common-errors.md`](pattern-common-errors.md).

> ⚠️ **Do not set Web origins, and do not go looking for a CORS setting when something breaks.**
> The code-for-token exchange runs in the Node process, server to server. No browser request ever
> touches Keycloak's token endpoint, so there is no CORS to configure. If you find yourself adding
> web origins to fix a Next.js problem, you are debugging the wrong layer.

The secret goes in the server environment and **never** in a `NEXT_PUBLIC_*` variable. Anything
prefixed `NEXT_PUBLIC_` is inlined into the browser bundle, which publishes it.

PKCE needs no configuration. `@auth/core` defaults every OAuth/OIDC provider to `checks: ["pkce"]`.

## Step 2: `auth.ts`

At the project root (or `src/`), so `@/auth` resolves:

```ts
import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

export const { handlers, signIn, signOut, auth } = NextAuth({
    providers: [Keycloak]
});
```

That is the whole file for a basic setup. `Keycloak` is passed **unconfigured** on purpose: Auth.js
reads `AUTH_KEYCLOAK_ID`, `AUTH_KEYCLOAK_SECRET` and `AUTH_KEYCLOAK_ISSUER` from the environment and
fills them in. The naming rule is `AUTH_{PROVIDER_ID_UPPERCASED}_{ID|SECRET|ISSUER}`.

```bash
# .env.local
AUTH_SECRET=…                                              # written by `npx auth secret`
AUTH_KEYCLOAK_ID=my-web-app
AUTH_KEYCLOAK_SECRET=…                                     # from the Keycloak client's Credentials tab
AUTH_KEYCLOAK_ISSUER=https://auth.example.com/realms/myrealm
```

**`AUTH_KEYCLOAK_ISSUER` includes `/realms/<realm>`.** Auth.js appends
`/.well-known/openid-configuration` to it and discovers every endpoint from there. Shape:
`https://<host><relative-path>/realms/<realm>` — the relative path is empty on modern Keycloak and
`/auth` on pre-Quarkus versions.

To configure it explicitly instead — for a second Keycloak, or values from a secret manager:

```ts
providers: [
    Keycloak({
        clientId: process.env.KC_CLIENT_ID,
        clientSecret: process.env.KC_CLIENT_SECRET,
        issuer: process.env.KC_ISSUER
    })
]
```

## Step 3: The route handler

```ts
// app/api/auth/[...nextauth]/route.ts
import { handlers } from "@/auth";
export const { GET, POST } = handlers;
```

The directory name must be exactly `[...nextauth]` and sit under `app/api/auth/`, because that is
where `basePath: "/api/auth"` sends every request. A mismatch here is what produces
`UnknownAction` errors.

## Step 4: Reading the session

**Server Components, Route Handlers and Server Actions** — call `auth()`:

```tsx
// app/dashboard/page.tsx
import { auth } from "@/auth";
import { redirect } from "next/navigation";

export default async function Dashboard() {
    const session = await auth();
    if (!session?.user) redirect("/api/auth/signin");

    return <h1>Hello {session.user.name}</h1>;
}
```

**Login and logout buttons** — `signIn` / `signOut` from `@/auth` are server-side, so use them in a
Server Action:

```tsx
import { signIn, signOut, auth } from "@/auth";

export default async function AuthButton() {
    const session = await auth();

    if (!session) {
        return (
            <form action={async () => { "use server"; await signIn("keycloak"); }}>
                <button type="submit">Log in</button>
            </form>
        );
    }

    return (
        <form action={async () => { "use server"; await signOut(); }}>
            <button type="submit">Log out</button>
        </form>
    );
}
```

`signIn("keycloak")` skips Auth.js's provider-picker page and goes straight to Keycloak.

**Client Components** — wrap the tree in `SessionProvider` and use `useSession`:

```tsx
"use client";
import { SessionProvider, useSession } from "next-auth/react";
```

Prefer `auth()` in a Server Component where you can. Auth.js's own guidance in v5 is that
server-side session reads are the recommended path; `useSession` costs a client-side round trip to
`/api/auth/session`.

## Step 5: Protecting routes at the edge of the app

**Next.js 16+** uses `proxy.ts`; **Next.js 14–15** uses `middleware.ts`. Same content, different
filename and export name — Next.js 16 renamed the convention, and `middleware.ts` still works but is
deprecated.

```ts
// proxy.ts  (Next.js 16+)
export { auth as proxy } from "@/auth";
```

```ts
// middleware.ts  (Next.js 14–15)
export { auth as middleware } from "@/auth";
```

```ts
export const config = {
    matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"]
};
```

By itself that only *populates* `req.auth`. To actually gate routes, add the `authorized` callback
to `auth.ts` — it is a `next-auth`-specific callback, not part of `@auth/core`:

```ts
export const { handlers, signIn, signOut, auth } = NextAuth({
    providers: [Keycloak],
    callbacks: {
        authorized: ({ request, auth }) => {
            if (request.nextUrl.pathname.startsWith("/dashboard")) {
                return !!auth?.user;
            }
            return true;
        }
    }
});
```

> ⚠️ **Make sure the page you redirect to is not itself covered by the matcher**, or you get an
> infinite redirect loop between the app and the sign-in page — the symptom in
> [`pattern-common-errors.md`](pattern-common-errors.md)'s last row.

**Route protection here is not authorization.** The API must validate independently — see
[`pattern-token-validation.md`](pattern-token-validation.md).

## Step 6: Getting the Keycloak access token (only if you need it)

**By default the access token never reaches your code.** Auth.js returns a curated session — name,
email, image — and drops the provider's tokens. That is a deliberate, good default: if your Next.js
app only needs to know *who* the user is, stop here and do not add this step.

You need it when a Server Component or Route Handler must call a *separate* resource server on the
user's behalf. Then thread it through the `jwt` and `session` callbacks:

```ts
import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";

export const { handlers, signIn, signOut, auth } = NextAuth({
    providers: [Keycloak],
    callbacks: {
        jwt: ({ token, account }) => {
            if (account) {
                token.accessToken = account.access_token;
                token.idToken = account.id_token;
                token.expiresAt = account.expires_at;
            }
            return token;
        },
        session: ({ session, token }) => {
            session.accessToken = token.accessToken;
            return session;
        }
    }
});
```

`account` is populated **only on the sign-in call** — on every later invocation it is `undefined`
and `token` already carries what you stored. Writing `token.accessToken = account.access_token`
without the `if (account)` guard wipes the token on the second request.

TypeScript needs the shapes declared:

```ts
declare module "next-auth" {
    interface Session {
        accessToken?: string;
    }
}

declare module "next-auth/jwt" {
    interface JWT {
        accessToken?: string;
        idToken?: string;
        expiresAt?: number;
    }
}
```

> ⚠️ **Whatever you put on `session` is sent to the browser.** The `session` callback's return value
> is serialised to the client. Copying the access token there hands it to any XSS on the page —
> exactly the exposure the BFF pattern exists to avoid. Keep it on `token` (which stays in the
> encrypted `HttpOnly` cookie) and read it server-side via `auth()`, unless a Client Component
> genuinely needs to call the API directly.

**Token refresh is not automatic.** Auth.js stores `expires_at` but does not renew the Keycloak
access token for you. Once it expires, calls to your resource server 401 while the Auth.js session
is still valid. Implementing refresh-token rotation in the `jwt` callback is Auth.js's documented
answer; it is enough moving parts (refresh races, rotation, error state) that it is out of scope
here. UNVERIFIED: no rotation implementation is given in this file — do not paste one from memory,
read Auth.js's refresh-token-rotation guide.

## Step 7: Logging out of Keycloak, not just out of your app

**`signOut()` does not end the Keycloak session.** Verified against `@auth/core` 0.41.3: the package
contains no reference to `end_session_endpoint` anywhere. `signOut()` clears the Auth.js cookie and
that is all.

The symptom: the user clicks Log out, appears logged out, clicks Log in — and is instantly back in
with no password prompt, because Keycloak's SSO session was never touched. On a shared computer that
is a real problem, not a cosmetic one.

To end both, redirect to Keycloak's RP-initiated logout endpoint after `signOut()`. You need the
`id_token` from Step 6's `jwt` callback, surfaced onto the session so a Server Action can read it:

```ts
// auth.ts — in addition to Step 6's jwt callback
session: ({ session, token }) => {
    session.idToken = token.idToken;
    return session;
}
```

```ts
declare module "next-auth" {
    interface Session {
        idToken?: string;
    }
}
```

```tsx
// app/logout/actions.ts
"use server";
import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";

export async function logoutEverywhere() {
    const session = await auth();

    const url = new URL(`${process.env.AUTH_KEYCLOAK_ISSUER}/protocol/openid-connect/logout`);
    if (session?.idToken) url.searchParams.set("id_token_hint", session.idToken);
    url.searchParams.set("post_logout_redirect_uri", process.env.AUTH_URL!);

    await signOut({ redirect: false });
    redirect(url.toString());
}
```

Register that `post_logout_redirect_uri` under the client's **Valid post logout redirect URIs**, or
Keycloak rejects it with `Invalid redirect_uri` on the way out.

> ⚠️ **This puts the ID token where the browser can read it**, for the same reason as Step 6's
> warning: the `session` callback's return value is serialised to the client and served from
> `/api/auth/session`. An ID token is an identity assertion, not an API credential, so the exposure
> is milder than leaking the *access* token — but it is still exposure.
>
> The token-free alternative: **pass `client_id` instead of `id_token_hint`.** Keycloak requires
> *one of the two* alongside `post_logout_redirect_uri` and rejects the request if neither is
> present, so you cannot simply drop the hint. The trade-off is that without `id_token_hint`
> Keycloak cannot tell which session to end silently and shows a "do you want to log out?"
> confirmation page. UNVERIFIED: that confirmation-page behaviour is corroborated by Keycloak
> community reports rather than a statement in the official docs — check it against your own
> Keycloak version before designing the UX around it.

```ts
url.searchParams.set("client_id", process.env.AUTH_KEYCLOAK_ID!);
```

## Verify

1. `npm run build` succeeds — a v4/v5 mix-up fails here first.
2. `package.json` shows `"next-auth": "^5.0.0-beta.x"`, not `^4.x`.
3. Click login → you land on Keycloak → after authenticating you return to the app **logged in**.
4. `session.user.name` renders from a Server Component.
5. A protected route redirects when logged out and renders when logged in.
6. Devtools → Application → Cookies: the session cookie is `HttpOnly`. No token appears in
   `localStorage`.
7. Log out, then log in again — you should be **prompted**, not silently signed back in. If you are
   not, Step 7 is missing.

Step 6 is the check that the BFF pattern is actually in force rather than nominally chosen.

## If you have seen a different API

Auth.js v4 → v5 changed nearly every entry point, and v4 is still what `npm install next-auth`
installs. If your memory or an older example disagrees with the code above, the code above is v5:

| v4 (or older) | v5 |
|---|---|
| `npm install next-auth` | `npm install next-auth@beta` — **the tag is mandatory** |
| `pages/api/auth/[...nextauth].ts` exporting `NextAuth(authOptions)` | `auth.ts` + `app/api/auth/[...nextauth]/route.ts` exporting `handlers` |
| `getServerSession(authOptions)` | `auth()` |
| `withAuth` middleware from `next-auth/middleware` | `export { auth as middleware }`, or `auth as proxy` on Next 16+ |
| `NEXTAUTH_SECRET` | `AUTH_SECRET` (v5 still reads `NEXTAUTH_SECRET` as a fallback) |
| `NEXTAUTH_URL` | `AUTH_URL` (same fallback) |
| `KeycloakProvider({ clientId: process.env.KEYCLOAK_ID, … })` | `Keycloak` bare + `AUTH_KEYCLOAK_ID` / `_SECRET` / `_ISSUER` |
| `signIn(provider, { callbackUrl })` | `signIn(provider, { redirectTo })` — a **relative** path |
| `import KeycloakProvider from "next-auth/providers/keycloak"` | the import path is unchanged; only the local name convention differs — the export is a default |
| `middleware.ts` | `proxy.ts` on Next.js 16+ (`middleware.ts` deprecated, Edge-runtime only) |

Two things people expect that do not exist:

- **No built-in Keycloak logout.** See Step 7.
- **No automatic access-token refresh.** See Step 6.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Module '"next-auth"' has no exported member 'handlers'` | v4 installed | `npm install next-auth@beta` |
| `NextAuth is not a function` / v4-shaped type errors everywhere | same | same — check `package.json` says `5.0.0-beta.x` |
| `Invalid redirect_uri` before the login form | callback URL not registered exactly | register `{origin}/api/auth/callback/keycloak`, no trailing slash |
| `MissingSecret` | `AUTH_SECRET` not set | `npx auth secret` |
| `UntrustedHost` in production | `trustHost` is off outside Vercel/Cloudflare unless told otherwise | set `AUTH_URL` to the public origin, or `AUTH_TRUST_HOST=true` behind a trusted proxy |
| `UnknownAction` on `/api/auth/*` | route handler in the wrong place | `app/api/auth/[...nextauth]/route.ts`, exactly |
| Callback URL points at `http://localhost:3000` in production | Auth.js derived the origin from the request behind a proxy | set `AUTH_URL` to the real public origin |
| Infinite redirect between app and sign-in page | the sign-in page is itself inside the middleware matcher | exclude it from `config.matcher` |
| `session.accessToken` is `undefined` | Auth.js strips provider tokens by default | add the `jwt` + `session` callbacks in Step 6 |
| Access token present on first request, gone afterwards | `account` read without the `if (account)` guard | guard it — `account` exists only on sign-in |
| API 401s after ~5 minutes while the app still looks logged in | the Keycloak access token expired; Auth.js doesn't refresh it | implement refresh-token rotation in the `jwt` callback |
| Log out → log in signs the user straight back in | `signOut()` never touched Keycloak's SSO session | add the RP-initiated logout redirect, Step 7 |
| CORS errors while debugging Next.js auth | you are debugging the wrong layer | the token exchange is server-side; leave Web origins empty |
| Client secret visible in devtools | it was put in a `NEXT_PUBLIC_*` variable | move it to a server-only env var and **rotate it** — it is leaked |
