<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Install with Cursor

Requires Cursor 3.19 or later.

## Add the marketplace

Cursor imports a marketplace from a GitHub repository through the web dashboard:

1. **Dashboard → Plugins**
2. Under **Team Marketplaces**, click **Add Marketplace**
3. Choose **Import from Repo** and point it at `p2-inc/keycloak-skills`
4. Cursor lists the plugins it finds — add **Phase Two Keycloak** with
   **Add to Marketplace**
5. Set **Marketplace Access**, optionally enable **Auto Refresh** so the plugin
   updates when changes are pushed (this needs the Cursor GitHub App installed on
   the repository), and save

## Install the plugin

In Cursor, open **Customize** in the sidebar, find **Phase Two Keycloak**, click
**Install**, and choose project or user scope.

The plugin's two skills — `keycloak` for realm administration and `securing-apps`
for wiring login into your own application — are then listed under **Customize**.
Ask for something like *"set up passwordless magic-link login on my Keycloak realm"*
and the matching skill activates.

## The Keycloak MCP server

Both skills use the Keycloak MCP server at `https://mcp.phasetwo.io/mcp` to inspect
deployment targets and verify changes against a live realm. Installing the plugin
connects it — there is nothing to configure.

The server is OAuth-protected. The first time a skill uses a tool, Cursor opens a
browser window to sign in to Phase Two; after you approve, Cursor stores the tokens
and refreshes them for you. The plugin ships with a pre-registered OAuth client, so
you are only ever asked to sign in, never to register anything.

Once connected, Cursor has the full Keycloak toolset available — creating clusters
and deployments, configuring authentication flows, identity providers, client
scopes and SMTP, and reading back the realm to verify a change landed.

Two things worth knowing:

- **The tools act on your own Phase Two account.** Cursor signs in as you, and every
  tool call carries your identity, so an agent can only do what you can do.
- **Deleting clusters, deployments and realms is deliberately not available.** The
  server refuses those operations regardless of your permissions; remove them from
  the Phase Two console instead.

## References

- [Cursor — Plugins](https://cursor.com/docs/plugins)
- [Cursor — Model Context Protocol](https://cursor.com/docs/mcp)
