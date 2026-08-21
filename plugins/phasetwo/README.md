# Phase Two Agent Skills Plugin

Agent skills for Keycloak: configuring behaviors from real p2-inc extensions, for both vanilla/self-hosted Keycloak and Phase Two hosted Keycloak.

## Skills

- [`keycloak`](./skills/keycloak/) — unified entry point for Keycloak work. Detects intent, then loads the matching reference doc. Today that's turning on passwordless login by magic link (the p2-inc `keycloak-magic-link` provider) via either raw Admin REST or the Keycloak MCP server, turning on passkey-only WebAuthn login via either tooling, offering a passkey **or** a magic link in one flow with no password anywhere (the "0 password required login flow", where magic link doubles as the passkey bootstrap path) via either tooling, routing corporate/enterprise SSO by email domain via either tooling, adding built-in social login buttons (Google, GitHub, Microsoft personal accounts, Facebook, and more), brokering a company's own enterprise identity provider (Entra ID, Okta, Auth0, ADFS, AWS SSO, Google Workspace, PingOne, OneLogin, Oracle, Duo, CyberArk, JumpCloud, LastPass, Salesforce, Cloudflare Access) as a login option, restricting login to one organization's members — for local password logins and for federated logins through an external IdP — via either tooling, and provisioning Phase Two clusters/deployments via the Keycloak MCP server (Phase Two SaaS-only, no self-managed equivalent).

## Dependency

This plugin's skill relies on the Keycloak MCP server to check deployment targets and verify changes against a live Keycloak:

```bash
mcp add --transport http keycloak https://mcp-staging.phasetwo.io/mcp
```
