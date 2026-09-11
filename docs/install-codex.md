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

## Authenticate the MCP server

Codex discovers the MCP server from [`.mcp.json`](../plugins/phasetwo/.mcp.json).
Authenticate it from the CLI:

```bash
codex mcp login keycloak
```

Codex can request dynamic client registration explicitly:

```bash
codex mcp login keycloak --oauth-client-registration dcr
```

This setting cannot be embedded in the plugin manifest. DCR must also be allowed by
the Phase Two authorization server. If the server rejects client registration,
reconnect the `keycloak` entry from `/mcp` in Codex, or ask Phase Two to enable DCR
for `https://mcp.phasetwo.io/mcp`.

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
