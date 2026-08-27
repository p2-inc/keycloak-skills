---
name: securing-apps
description: >-
  Use when wiring Keycloak/OIDC login into your own app's source, or protecting an API with it.
  Browser login, logout and route protection for React, Angular, Vue, Next.js or a vanilla SPA
  (oidc-spa, keycloak-js, Auth.js); bearer-JWT validation in a Spring Boot, Express, FastAPI or
  Quarkus resource server (JWKS, issuer, audience); native login on Android, iOS or React Native
  (AppAuth, PKCE). Also registers or updates the app's OIDC client — redirect URIs, web origins,
  public vs confidential. Triggers: "add login to my React/Angular/Vue/Next.js app",
  "secure/protect my API", "validate a JWT", "invalid redirect_uri", "401 from my API",
  "CORS on the token call". **OIDC/OAuth2 only, not SAML.** Not realm, flow or IdP
  admin, not passwordless/SSO setup — that is the `keycloak` skill.
license: Apache-2.0
metadata:
  version: '0.1.0'
  author: Phase Two <support@phasetwo.io>
---

# Securing applications

Detect intent → detect framework → ask two questions → load references.

A **router**: no steps of its own, every instruction behind a `Read:` in Step 5. Its target is
**your application's source code**. Configuring the realm — flows, passwordless, IdP federation,
organizations — is the sibling `keycloak` skill. "Make login work *in Keycloak*" → hand off.

---

**Detection is free, questions are expensive.** Steps 1-2 read files and ask nothing. Steps 3-4 are
the **only two questions**, in that order: Step 4 needs Step 2's answer. Don't ask either twice.

---

## Step 0: Before you write to a live realm

Read before routing: Step 4's existing-client branch changes a client others may depend on.

- **Confirm before changing an existing client** — say what changes, on which, and wait. Creating a
  new one needs no confirmation; altering one that serves traffic does.
- **Verify by re-reading, not by the return code.** Keycloak's client PUT answers `204` while
  silently blanking every field the payload omitted. Read it back and check what you did *not*
  intend to change survived.
- **Never hardcode a secret.** Public clients have none; a confidential client's stays server-side.

---

## Step 1: Detect intent

| What the developer wants (plain language) | Intent |
|---|---|
| Log users in from a **browser** app — "add login to my React app", "sign in with Keycloak", "protect this route/page", "log out". The app renders UI and redirects a human to Keycloak. Not a backend that only checks a token (next row), not a native app (row after). | **app:add-login** |
| Protect an **API** by validating a bearer token — "secure my API", "validate the JWT", "map Keycloak roles to authorities". No login UI, no redirect, no cookie session: the token arrives in an `Authorization` header. Not a server-rendered web app that logs users in, and not fixing an API that already validates (last row). | **app:protect-api** |
| Log users in from a **native mobile or desktop** app — "add login to my Android/iOS app", "React Native + Keycloak", "custom URL scheme callback", "where do I store tokens". System browser, never an embedded WebView. Not a mobile-shaped web page (`app:add-login`). | **app:mobile-login** |
| **Diagnose** an integration that already exists and is failing — "invalid redirect_uri", "401 from my API", "CORS on the token call", "redirect loop", "my roles are missing". Something is wired; find what is wrong. Not a fresh build (rows above) — look for existing auth code first. | **app:debug** |

### The app speaks SAML, not OIDC

**Never route a SAML app into an OIDC framework file** — nothing in `references/framework-*.md`
applies. Recognise it from the request ("SAML SSO", "ACS URL", "SP metadata", "assertion") or the
manifest — `passport-saml`, `@node-saml/node-saml`, `samlify`, `python3-saml`, `pysaml2`,
`spring-security-saml2-service-provider`, `ruby-saml`, `simplesamlphp`.

Split the answer. **Keycloak side: available** — `createSamlClient` takes `spMetadataXml`, and the
org-level `connectingkeycloakclient` skill walks the registration (no SAML *update* tool exists, so
changing one means the REST read-merge-PUT). **App side — SP library, assertion handling, session —
not covered in v1.** Offer the first, say the second is uncovered, don't improvise SP code.

### No intent matches

Don't force an uncovered request into `app:add-login` just to have somewhere to send it.

Out of scope: realm/flow/IdP config, passwordless, SSO, organizations → the **`keycloak`** skill.
Running/deploying the server, or writing an SPI provider, theme or extension jar → neither yet.

Otherwise follow the `keycloak` router's gap procedure: say plainly it isn't covered, offer to open
an issue in `p2-inc/keycloak-skills` quoting the developer's **verbatim** prompt, and show the draft
before filing. If they decline, leave it — don't paper over the gap by answering anyway.

---

## Step 2: Detect framework

Read the project's manifests. **Stop at the first tier that yields a framework.**

### Tier 1 — an OIDC/auth SDK is installed (strongest signal)

**Top to bottom, stop at the first match** — a superset carries the subset's dependency, so compound
rows precede bare ones. An SDK installed but not yet configured still counts.

| Dependency found | Framework |
|---|---|
| `next-auth` / `@auth/*` | `nextjs` |
| `oidc-spa` + `@angular/core` · `keycloak-angular` | `angular` |
| `oidc-spa` + `react` | `react` |
| `keycloak-js` + `vue` | `vue` |
| `oidc-spa` or `keycloak-js`, alone | `spa-js` |
| `react-native-app-auth` / `expo-auth-session` | `react-native` |
| `AppAuth` (`Package.swift`, `*.xcodeproj`) | `ios-swift` |
| `net.openid:appauth` (`build.gradle(.kts)`) | `android` |
| `spring-boot-starter*-oauth2-resource-server` | `springboot-api` |
| `quarkus-oidc` | `quarkus-api` |
| `jose` / `express-jwt` / `jwks-rsa` | `express-api` |
| `pyjwt` / `python-jose` | `fastapi-api` |

Manifests: `package.json`, `requirements.txt` / `pyproject.toml`, `pom.xml` / `build.gradle(.kts)`,
`Package.swift` / `*.xcodeproj`, `pubspec.yaml`, `*.csproj`.

### Tier 2 — ordinary (non-auth) dependencies

Same order rule; `*` needs the variant rule below.

| Dependency | Framework | | Dependency | Framework |
|---|---|---|---|---|
| `next` | `nextjs` | | `express` / `fastify` | `express-api` * |
| `@angular/core` | `angular` | | `fastapi` / `flask` | `fastapi-api` * |
| `vue` / `nuxt` | `vue` | | `spring-boot-starter-web` | `springboot-api` * |
| `react-native` / `expo` | `react-native` | | `quarkus` | `quarkus-api` |
| `react` | `react` | | | |

### Tier 3 — the prompt

Map the developer's words to the same keys.

### Variant disambiguation — web app vs API

**Only when Tier 1 didn't already pin it** — a Tier 1 match on `spring-boot-starter*-oauth2-resource-server`,
`jose`/`express-jwt`, `pyjwt` or `quarkus-oidc` *is* the API variant. This rule is for **Tier 2/3**
matches, where intent outranks the manifest. Web variants are v2.

| Tier 2/3 base | API variant | Choose it when… |
|---|---|---|
| `express` / `fastify` | `express-api` | validating JWTs on routes, no server-rendered login UI |
| `spring-boot-starter-web` | `springboot-api` | resource server, no cookie-based login |
| `fastapi` / `flask` | `fastapi-api` | token validation only |

If the app genuinely has **both** a login UI and protected endpoints, **state what was detected and
ask** which half to do first. Don't silently pick.

### Conflicts and gaps

- **Tier 2 and Tier 3 disagree materially** → state the conflict and ask. Workspace signals outrank
  the prompt when both are present and consistent.
- **Nothing matched** → ask. Don't guess.
- **Detection must not outrun coverage.** Flutter (`pubspec.yaml`), .NET (`*.csproj`), Go and
  reverse-proxy setups (oauth2-proxy, `mod_auth_openidc`, Envoy, NGINX) are recognised for
  disambiguation but have **no reference file in v1**. Say so and offer the generic OIDC shape from
  `pattern-integration-decision.md` — never a neighbouring framework's file, never a silent dead end.

---

## Step 3 (first question): Phase Two, or self-managed?

This decides the **tooling** for client registration. Ask directly; don't infer it.

| Answer | Tooling |
|---|---|
| **Yes — Phase Two hosted.** | **mcp.** The plugin declares it as `keycloak` (`https://mcp.phasetwo.io/mcp`). Missing tools usually mean an unauthorized OAuth connection, not a missing server — have them check `/mcp`. |
| **No — self-managed** (bare metal, Docker, Kubernetes; direct Admin REST access). | **rest.** |

If the answer is ambiguous, ask — don't guess and don't default to either side.

**On `mcp`, `rest` is not a fallback.** A hosted deployment has no self-service admin REST credential
of any kind, so the `rest` file fails at its first step: nothing to put in `$ADMIN_TOKEN`. If the
developer declines MCP, point them at reconnecting it or at the dashboard.

Tooling affects only client registration — never the app's library or wiring.

---

## Step 4 (second question): a new client, or one that already exists?

Step 2 must have run first: the app's shape decides the client **type**.

**On `tooling=mcp`, answer by detection, not by asking** — `listClients` shows what exists. Check the
app's own config too (`.env`, `keycloak.json`, `application.properties`): a `clientId` already there
means "existing", and its value is the answer. Ask outright only if that's ambiguous, or on `rest`.

| Branch | What it means |
|---|---|
| **New client** | Nothing exists yet. Create it; Step 2's framework decides public vs confidential. |
| **Existing client** | A `clientId` already exists and needs its redirect URIs or web origins widened. **Update it; never delete and re-create a live client.** |

The client-registration reference carries both branches. Say which you're on.

---

## Step 5: Load reference files

| Read | When |
|---|---|
| [`pattern-integration-decision.md`](references/pattern-integration-decision.md) | build intents, **first** — pattern before library |
| `references/framework-{framework}.md` | whenever Step 2 identified one |
| [`client-registration-mcp.md`](references/client-registration-mcp.md) *(mcp)* / [`client-registration.md`](references/client-registration.md) *(rest)* | build intents, per Step 3 |
| [`pattern-token-validation.md`](references/pattern-token-validation.md) | `app:protect-api`, or `app:debug` on an API symptom (401/403). The `framework-*-api.md` files don't repeat it. |
| [`pattern-common-errors.md`](references/pattern-common-errors.md) | always — and **first** for `app:debug`: symptom → cause |

**`app:debug` is diagnostic, not constructive: it skips Steps 3-4** until the diagnosis names the
client. Don't ask someone with a broken flow which tooling they run before you know whether the fix
is even in Keycloak.

### Framework files

`references/framework-{framework}.md`. **A framework key not listed here has no file** — admit the
gap rather than substituting a neighbour.

| Intent | Framework key → file |
|---|---|
| `app:add-login` | [react](references/framework-react.md) · [angular](references/framework-angular.md) · [vue](references/framework-vue.md) · [spa-js](references/framework-spa-js.md) · [nextjs](references/framework-nextjs.md) |
| `app:protect-api` | [springboot-api](references/framework-springboot-api.md) · [express-api](references/framework-express-api.md) · [fastapi-api](references/framework-fastapi-api.md) · [quarkus-api](references/framework-quarkus-api.md) |
| `app:mobile-login` | [android](references/framework-android.md) · [ios-swift](references/framework-ios-swift.md) · [react-native](references/framework-react-native.md) |

**If a framework file and your recollection disagree about which library to use, the file is right.**
Keycloak removed its Java adapters in 25.0.0 and deprecated `keycloak-connect`; each framework file
names the dead adapter it replaces. Emitting one is the most likely failure here, because it is what
older training data suggests and the code does not build.
