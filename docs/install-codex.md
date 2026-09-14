<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Install with Codex

```bash
codex plugin marketplace add p2-inc/keycloak-skills
```

```bash
codex plugin add phasetwo@keycloak-skills
```

Codex reads [`.agents/plugins/marketplace.json`](../.agents/plugins/marketplace.json)
at the repo root — the OpenAI/ChatGPT convention, the same path Codex's own bundled
and curated marketplaces use — and the Codex manifest at
[`plugins/phasetwo/.codex-plugin/plugin.json`](../plugins/phasetwo/.codex-plugin/plugin.json).

Inspect and refresh configured marketplaces with:

```bash
codex plugin marketplace list
```

```bash
codex plugin marketplace upgrade
```

Start a **new** Codex task after installing, so it picks up the skills and the MCP
server.

## The MCP server

Both skills use the Keycloak MCP server at `https://mcp.phasetwo.io/mcp`. The Codex
manifest declares it with a pre-registered OAuth client, so Codex does not have to
register one of its own:

```json
"mcpServers": {
  "keycloak": {
    "type": "http",
    "url": "https://mcp.phasetwo.io/mcp",
    "scopes": ["openid"],
    "oauth": {
      "client_id": "…",
      "callback_url": "http://localhost:8787/callback",
      "callback_port": 8787
    }
  }
}
```

You do not have to connect or authenticate it separately. The marketplace entry
declares `"authentication": "ON_INSTALL"`, so Codex runs the browser sign-in as part
of installing the plugin.

If you ever need to sign in again — revoked access, a cleared token store:

```bash
codex mcp login keycloak
```

If you need Codex to register its own client instead — against an authorization
server that allows it — override the strategy for a single login:

```bash
codex mcp login keycloak --oauth-client-registration dcr
```

That flag cannot be embedded in the plugin manifest, and dynamic registration must
also be permitted by the Phase Two authorization server.

## Known limitations

Two Codex-side issues affect the MCP tools specifically. Neither affects the skills,
which work normally.

**Only the first page of `tools/list` is read.** Codex does not follow the
`nextCursor` pagination cursor ([openai/codex#28858](https://github.com/openai/codex/issues/28858)),
so it sees a truncated toolset. The server raises its page size to compensate
(`quarkus.mcp.server.tools.page-size`), but a client that paginates — Claude Code,
Cursor — sees more tools than Codex does.

**Scope over-request on authorization.** The protected-resource metadata at
`https://mcp.phasetwo.io/.well-known/oauth-protected-resource/mcp` advertises no
`scopes_supported`, so Codex's OAuth layer falls back to requesting every scope the
authorization server publishes, which Phase Two rejects.

Because the tools may be missing or unavailable, every MCP skill opens with a
capability check and falls through to the Keycloak admin REST API when the tools
are not present. The guidance itself is transport-agnostic, so the task still
completes.

## Publishing

A manifest and a repository marketplace do not publish the plugin. Listing in the
public ChatGPT and Codex directory goes through the
[OpenAI plugin submission portal](https://platform.openai.com/plugins) as a
**Skills only** submission, which requires a verified developer or business identity
and Apps Management write access for the submitting organization.
