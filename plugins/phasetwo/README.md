# Phase Two Agent Skills Plugin

Agent skills for Keycloak: configuring behaviors from real p2-inc extensions, for both vanilla/self-hosted Keycloak and Phase Two hosted Keycloak — and protecting your own applications with them.

The two skills split by **what the work targets**: `keycloak` changes a live realm, `securing-apps` changes your application's source code.

## Skills

- [`securing-apps`](./skills/securing-apps/) — app-side integration: wiring Keycloak/OIDC login into your own application. Browser login, logout and route protection for React, Angular, Vue, Next.js or a vanilla SPA (oidc-spa, keycloak-js, Auth.js); bearer-JWT validation in a Spring Boot, Express, FastAPI or Quarkus resource server (JWKS, issuer, audience, and Keycloak's nested role claims); native login on Android, iOS and React Native (AppAuth, PKCE, custom-scheme callbacks). Detects the framework from the project's own manifests rather than asking, then registers or updates the OIDC client the app needs — redirect URIs, web origins, public vs confidential — via either the Keycloak MCP server or raw Admin REST. Leads with the ecosystem-native library for each stack and names the Keycloak adapter it replaces, since the adapters were removed in Keycloak 25.0.0 and older training data still suggests them.

- [`keycloak`](./skills/keycloak/) — unified entry point for Keycloak *administration*. Detects intent, then loads the matching reference doc. Today that's turning on passwordless login by magic link (the p2-inc `keycloak-magic-link` provider) via either raw Admin REST or the Keycloak MCP server, turning on passkey-only WebAuthn login via either tooling, offering a passkey **or** a magic link in one flow with no password anywhere (the "0 password required login flow", where magic link doubles as the passkey bootstrap path) via either tooling, routing corporate/enterprise SSO by email domain via either tooling, adding built-in social login buttons (Google, GitHub, Microsoft personal accounts, Facebook, and more), brokering a company's own enterprise identity provider (Entra ID, Okta, Auth0, ADFS, AWS SSO, Google Workspace, PingOne, OneLogin, Oracle, Duo, CyberArk, JumpCloud, LastPass, Salesforce, Cloudflare Access) as a login option, restricting login to one organization's members — for local password logins and for federated logins through an external IdP — via either tooling, and provisioning Phase Two clusters/deployments via the Keycloak MCP server (Phase Two SaaS-only, no self-managed equivalent).

## Dependency

Both skills rely on the Keycloak MCP server to check deployment targets and verify changes against a live Keycloak. The plugin declares it in [`.mcp.json`](.mcp.json) at the plugin root, so installing the plugin connects `keycloak` → `https://mcp.phasetwo.io/mcp` for you. It sits behind OAuth: the first tool call prompts you to authorize, and `/mcp` shows the connection state.

Only add it by hand if you are running the skill outside the plugin:

```bash
claude mcp add --transport http keycloak https://mcp.phasetwo.io/mcp
```
