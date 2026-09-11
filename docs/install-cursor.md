<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Install with Cursor

Verified against **Cursor 3.19.13**.

Cursor loads this plugin with no Cursor-specific packaging required, because its
manifest resolver falls back to the Claude Code files:

| What Cursor looks for | Order |
| --- | --- |
| Plugin manifest | `.cursor-plugin/plugin.json` → `.claude-plugin/plugin.json` → `plugin.json` |
| Marketplace | `.cursor-plugin/marketplace.json` → `.claude-plugin/marketplace.json` |
| MCP servers | `.mcp.json` or `mcp.json` at the plugin root |

This repo ships the `.cursor-plugin/` files anyway, so the listing carries its own
display name, keywords and category instead of inheriting Claude's.

## Pick your route

### You already use Claude Code — nothing to do

Cursor imports plugins installed in Claude Code automatically. If you have already
run `claude plugin install phasetwo@keycloak-skills`, the plugin is live in Cursor
the next time it loads. You can confirm it in the log (see [Verify](#verify)):

```text
[cc-marketplace-import] discoveryComplete
loadClaudePlugin phasetwo@keycloak-skills loaded in 327.8ms
```

### From this repository — team marketplace

Cursor imports a marketplace from a GitHub repo through the web dashboard, not the
CLI (the `cursor` command is only the editor launcher and has no plugin subcommands):

1. **Dashboard → Plugins**
2. Under **Team Marketplaces**, click **Add Marketplace**
3. Choose **Import from Repo** and point it at `p2-inc/keycloak-skills`
4. Cursor parses [`.cursor-plugin/marketplace.json`](../.cursor-plugin/marketplace.json)
   and lists the plugins it found — add **Phase Two Keycloak** with **Add to Marketplace**
5. Set **Marketplace Access**, optionally enable **Auto Refresh** (needs the Cursor
   GitHub App on the repo), and save

Then install it from the editor: open **Customize** in the sidebar, find
**Phase Two Keycloak**, click **Install**, and choose project or user scope.

### From a local checkout — plugin development

Copy the plugin directory into Cursor's local plugin folder, then reload:

```bash
cp -R plugins/phasetwo ~/.cursor/plugins/local/phasetwo
```

Run **Developer: Reload Window** from the command palette, or restart Cursor.

> **Copy it — do not symlink it.** Cursor's own documentation suggests
> `ln -s /path/to/plugin ~/.cursor/plugins/local/my-plugin`, but 3.19.13 rejects a
> symlink whose target lives outside that folder:
>
> ```text
> loadUserLocalPlugin phasetwo rejected: symlink target
>   /path/to/keycloak-skills/plugins/phasetwo is outside ~/.cursor/plugins/local
> ```
>
> The plugin then silently does not load. Re-copy after changes, or use the Claude
> Code install above, which does read your checkout live.

## Authenticate the MCP server

Both skills use the Keycloak MCP server at `https://mcp.phasetwo.io/mcp` to inspect
deployment targets and verify changes against a live realm. It is OAuth-protected.

The plugin pins a pre-registered OAuth client in
[`.cursor-plugin/plugin.json`](../plugins/phasetwo/.cursor-plugin/plugin.json), so
there is nothing to configure:

```json
"mcpServers": {
  "keycloak": {
    "type": "http",
    "url": "https://mcp.phasetwo.io/mcp",
    "auth": { "CLIENT_ID": "…", "scopes": ["openid"] }
  }
}
```

On first use Cursor opens a browser window to sign in to Phase Two. After you
approve, tokens are stored by Cursor and refreshed automatically.

**Why the client is pinned.** Without `auth.CLIENT_ID`, Cursor performs dynamic
client registration, sending three redirect URIs — including
`cursor://anysphere.cursor-mcp/oauth/callback`, whose "host" is not a resolvable
hostname. Keycloak's Trusted Hosts policy rejects the registration:

```text
Policy 'Trusted Hosts' rejected request to client-registration service.
Details: URI doesn't match any trusted host or trusted domain
```

Supplying a client id makes Cursor skip registration entirely, so the policy is
never consulted. `scopes` is pinned for the same reason: left unset, Cursor falls
back to requesting the authorization server's entire `scopes_supported` list.

This block lives in the Cursor manifest rather than the shared
[`.mcp.json`](../plugins/phasetwo/.mcp.json) so that Claude Code and Codex keep
their existing behaviour.

## Verify

Open **Customize** in the sidebar — the plugin's skills should be listed.

For the authoritative view, read Cursor's logs under
`~/Library/Application Support/Cursor/logs/<timestamp>/`:

```bash
# plugin loading
tail -f ~/Library/Application\ Support/Cursor/logs/*/window*/exthost/anysphere.cursor-agent-exec/Cursor\ Plugins.*.log

# MCP connection
tail -f ~/Library/Application\ Support/Cursor/logs/*/mcp-server-plugin-phasetwo-keycloak.log
```

A healthy connection ends like this:

```text
Successfully connected to streamableHttp server
[V2 FSM] connection:connect_success: conn=connecting,auth=valid -> conn=connected,auth=valid
Server "plugin-phasetwo-keycloak" fingerprint changed: tools=159, status=connected
```

`tools=159` is the number to check. Cursor follows `tools/list` pagination correctly
and surfaces the whole toolset.

Then try it: ask Cursor something like *"set up passwordless magic-link login on my
Keycloak realm"* and confirm the `keycloak` skill activates.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Trusted Hosts rejected request to client-registration service` | Cursor fell back to dynamic registration — the `auth.CLIENT_ID` block is missing or the plugin is stale. Reinstall, or reload the window. |
| `loadUserLocalPlugin … rejected: symlink target … is outside` | You symlinked into `~/.cursor/plugins/local`. Copy the directory instead. |
| `status=needsAuth`, `tools=1` | The OAuth flow has not completed. Click the sign-in prompt, or reconnect the server from Cursor's MCP settings. |
| `tools=0, status=connected` | Transient — Cursor logs this between connecting and the first `tools/list`. If it persists, reconnect. |
| Plugin edits have no effect | Cursor does not re-read plugin manifests while a connection is live. Run **Developer: Reload Window**. |
| A tool returns a permission error that the same call does not produce in Claude Code | The pinned `scopes` list may be too narrow for the downstream Phase Two API. Widen it in the Cursor manifest. |

## References

- [Cursor — Plugins](https://cursor.com/docs/plugins)
- [Cursor — Model Context Protocol](https://cursor.com/docs/mcp)
