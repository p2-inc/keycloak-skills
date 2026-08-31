<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# `securing-apps` — reference manifest

The [`../SKILL.md`](../SKILL.md) router dispatches to the files below. Each is loaded **on demand**
for a specific intent + framework + tooling, never all at once.

Unlike the `keycloak` router — which loads exactly one file per intent+tooling — this skill loads
**three to five**: a pattern file, a framework file, a client-registration file, and (for APIs) the
shared token-validation file. That is the reason it is a separate skill rather than more intents on
the router; see [`docs/adding-a-skill.md`](../../../../../docs/adding-a-skill.md) §1.

## Always loaded

| File | When | Status |
|---|---|---|
| [`pattern-integration-decision.md`](pattern-integration-decision.md) | every intent, **first** | written |
| [`pattern-common-errors.md`](pattern-common-errors.md) | every intent, last | written |

## Client registration (tooling axis)

| File | Tooling | Status |
|---|---|---|
| [`client-registration-mcp.md`](client-registration-mcp.md) | `mcp` — Phase Two hosted | written |
| [`client-registration.md`](client-registration.md) | `rest` — self-managed | written |

Both cover **two branches**: creating a new client, and updating one that already exists. The
existing-client branch is not an afterthought — widening redirect URIs for local development is the
single most common client operation, and doing it by delete-and-re-create destroys a live client's
secret, role mappings, and sessions.

## Shared, intent-scoped

| File | Intent | Status |
|---|---|---|
| [`pattern-token-validation.md`](pattern-token-validation.md) | `app:protect-api` only | written |

Carries JWKS caching, issuer/audience validation, `azp`, clock skew and algorithm pinning for every
API framework. The `framework-*-api.md` files deliberately **do not repeat it** — they carry only
their own wiring and role-converter. Writing it per framework is how three of the four copies drift.

## Framework files

### `app:add-login` — browser apps

| File | Framework key | Library | Status |
|---|---|---|---|
| [`framework-react.md`](framework-react.md) | `react` | `oidc-spa` 10.2.11 | written |
| [`framework-angular.md`](framework-angular.md) | `angular` | `oidc-spa/angular` 10.2.11 | written |
| [`framework-vue.md`](framework-vue.md) | `vue` | `keycloak-js` 26.2.4 | written |
| [`framework-spa-js.md`](framework-spa-js.md) | `spa-js` | `oidc-spa` core 10.2.11 / `keycloak-js` 26.2.4 | written |
| [`framework-nextjs.md`](framework-nextjs.md) | `nextjs` | Auth.js (`next-auth` 5.0.0-beta.32) | written |

`framework-vue.md` leads with `keycloak-js` rather than `oidc-spa` because **`oidc-spa` has no Vue
adapter** — verified against 10.2.11's `exports` map (`./angular`, `./react-spa`, `./nuxt-spa`,
`./react-tanstack-start`; no `./vue`) and the v10 docs sitemap (no Vue page, no Vue example). That
is a library fact, not a preference, and the file says so rather than implying parity.

### `app:protect-api` — resource servers

| File | Framework key | Library | Status |
|---|---|---|---|
| [`framework-springboot-api.md`](framework-springboot-api.md) | `springboot-api` | `spring-boot-starter-security-oauth2-resource-server` (4.0+) / `spring-boot-starter-oauth2-resource-server` (3.x) | written |
| [`framework-express-api.md`](framework-express-api.md) | `express-api` | `jose` `6.2.10` + JWKS | written |
| [`framework-fastapi-api.md`](framework-fastapi-api.md) | `fastapi-api` | PyJWT + JWKS | written |
| [`framework-quarkus-api.md`](framework-quarkus-api.md) | `quarkus-api` | `quarkus-oidc` `3.39.1` | written |

Three findings from writing these are worth knowing before editing them:

- **Spring Boot 4.0 renamed the starter** to `spring-boot-starter-security-oauth2-resource-server`;
  the old artifact's own POM description now reads "(deprecated in favor of ...)". The file carries a
  version-keyed table rather than one answer, because the new name does not exist before 4.0.0-M1.
- **PyJWT raises on Keycloak's default token.** `_validate_aud` raises `InvalidAudienceError` when
  `audience=None` *and* the token has an `aud` claim — and Keycloak issues `aud: account` by default,
  so the natural call fails on every token. The obvious "fix" (`verify_aud: False`) disables the check
  entirely. It is the first troubleshooting row in that file.
- **Quarkus's automatic role handling has three silent off-switches** (`role-claim-path` replaces
  rather than adds; a non-empty `groups` claim shadows `realm_access`; `resource_access` is only read
  when `quarkus.oidc.client-id` is set), read from `OidcUtils.findRoles`.

### `app:mobile-login` — native apps

| File | Framework key | Library | Status |
|---|---|---|---|
| [`framework-android.md`](framework-android.md) | `android` | AppAuth-Android `0.11.1` | written |
| [`framework-ios-swift.md`](framework-ios-swift.md) | `ios-swift` | AppAuth-iOS `3.0.0` | written |
| [`framework-react-native.md`](framework-react-native.md) | `react-native` | `react-native-app-auth` `8.4.1` | written |

All three carry the same four non-negotiables and deliberately state them per platform rather than
factoring them out: **system browser, never a WebView** (RFC 8252 §8.12); **PKCE, always** — these
are public clients and no secret ships in a mobile binary; **the custom-scheme redirect registered
in *both* Keycloak and the app**, because each half fails with a different symptom; and **OS keystore
token storage**. The React Native file additionally settles the Expo question: `react-native-app-auth`
ships an official Expo config plugin, so Expo needs no other library — the real blocker is that Expo
Go cannot customise the app scheme, which no library works around.

## Not covered in v1 — say so, don't improvise

The router recognises these for disambiguation but has no file for them. Say plainly that the
framework isn't covered yet and fall back to the generic OIDC shape in
`pattern-integration-decision.md`. Never route them into a neighbouring framework's file.

**SAML is the one row where the generic-OIDC fallback is wrong**, because the protocols share
nothing at the app layer. Its Keycloak half is nonetheless available — `createSamlClient` on the MCP
server, or the org-level `connectingkeycloakclient` skill. See SKILL.md's "The app speaks SAML"
section, which splits the two halves explicitly.

| Not covered | Detected via | Roadmap |
|---|---|---|
| **SAML SP integration (app side)** — consuming assertions, ACS endpoint, SP libraries | `passport-saml`, `@node-saml/node-saml`, `samlify`, `python3-saml`, `pysaml2`, `spring-security-saml2-service-provider`, `ruby-saml` | v2 |
| Go | `go.mod` | H8 |
| .NET | `*.csproj` | H9 |
| Flutter / Dart | `pubspec.yaml` | — |
| Reverse proxy / gateway (oauth2-proxy, `mod_auth_openidc`, Envoy, NGINX) | no manifest signal | H11 |
| Server-rendered Express / Flask / Spring MVC **web apps** (as opposed to APIs) | intent + manifest | H3, H4, H7 |
| Keycloak as the authorization server for an MCP server | — | H12 |

## Authoring conventions

Same rule as the `keycloak` router: **grow this skill by adding framework files once the content is
genuinely written and verified — never stub out a framework ahead of time.** A row above that says
"not written yet" is a promise to the reader that the router will admit the gap rather than guess.

Three rules specific to this skill:

1. **Lead with the ecosystem-native library, and name the dead adapter it replaces.** Keycloak
   removed its Java adapters in **25.0.0** and deprecated `keycloak-connect`. An agent working from
   older training data will otherwise emit code that does not build. State the version.
2. **Verify the library's current API before writing a code example.** Library APIs move faster than
   Keycloak does; an example using a renamed export is the exact failure this skill exists to
   prevent. Cite the version the example was verified against.
3. **Don't repeat `pattern-token-validation.md`.** If a framework file is explaining JWKS caching or
   audience validation, that content is in the wrong file.
