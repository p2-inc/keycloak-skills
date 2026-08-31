<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Pick the integration pattern before picking the library

Loaded on **every** intent, ahead of the framework file. Most serious mistakes in app-side auth are
made here, before a line of code is written — and no amount of correct library usage repairs a wrong
pattern.

## The four decisions

### 1. Where do the tokens live?

| Pattern | Tokens live | Use when |
|---|---|---|
| **Public SPA client** | in browser memory (JS), never persisted | a static/CDN-hosted SPA with no server of its own |
| **BFF** (backend-for-frontend) | server-side session; browser gets an `HttpOnly` cookie | the app already has a server, or tokens must never reach JS |
| **Native app** | OS keystore (Keychain / EncryptedSharedPreferences) | mobile and desktop |
| **Resource server** | nowhere — it only *validates* what arrives | an API behind a bearer token |

**Never `localStorage` or `sessionStorage` for tokens.** Any XSS on the page reads them and exfiltrates
a working credential. In-memory means a refresh loses the token and the app silently re-authenticates
against the existing Keycloak SSO session — that is the intended behaviour, not a bug to fix.

If the app already has a backend, **BFF is the stronger choice** and worth saying so, even when the
developer asked for a SPA library: the browser never holds a token at all.

### 2. Which grant?

| Grant | Verdict |
|---|---|
| **Authorization code + PKCE** | The answer for every interactive login — SPA, server-rendered, and native alike. |
| **Client credentials** | Machine-to-machine only. No user is present, so there is no one to log in. |
| Implicit | **Dead.** Removed from OAuth 2.1. Returns tokens in the URL fragment, where they land in browser history and referrer headers. |
| Resource Owner Password (direct grant) | **Effectively dead.** The app collects the user's password directly, which defeats SSO, blocks MFA and federation, and is disabled by default on new clients. Not a shortcut for tests either — script the code flow instead. |

PKCE is mandatory for public clients and harmless for confidential ones. If a library makes it
optional, turn it on.

### 3. Public or confidential?

Decided by one question: **can this app keep a secret from its own user?**

- A browser bundle cannot. Anyone opens devtools and reads it. → `public`
- A mobile binary cannot. It ships to the device and can be unpacked. → `public`
- A server process can, if the secret is in its environment and not its repo. → `confidential`

A secret in a React/Angular/Vue bundle, a mobile app, or a committed `.env` is a leaked secret. There
is no "obfuscated well enough" version of this.

### 4. Library, or no code at all?

Before writing integration code, check whether the app needs any:

- A **reverse proxy or gateway** (oauth2-proxy, `mod_auth_openidc`, Envoy, NGINX) can authenticate an
  app that has no auth code whatsoever, and is often right for legacy or internal apps. Not covered by
  a reference file in v1 — say so plainly rather than steering the developer into a library because
  that is what this skill has files for.
- A **platform-native option** may already exist (a framework's own auth module, a hosting platform's
  edge auth). Prefer the ecosystem-native path; Keycloak's own guidance is that its adapters "should
  be used as a last resort if you cannot rely on what is available from the application ecosystem."

## Check what already exists before building anything

In order:

1. **Is there already a client for this app?** `listClients` (MCP) or `GET /admin/realms/{realm}/clients`
   (REST). Reusing and widening one beats creating a duplicate.
2. **Is there already auth code in the project?** A half-wired `keycloak-js` setup, a stale
   `keycloak.json`, a `next-auth` config. Finishing it is usually cheaper than replacing it — and
   replacing it without saying so loses the developer's work.
3. **Is the library in the project already current?** If it is a removed adapter (see the framework
   file), the migration *is* the task, and it needs saying up front rather than discovering it
   halfway through.

## What this skill does not decide

Authorization — who may do what once logged in — is a separate problem from authentication. Role
mapping into the token, fine-grained permissions, and policy enforcement live in the `keycloak`
skill and in Keycloak's authorization services. This skill gets the user authenticated and the token
validated; it does not design a permission model.
