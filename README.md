# agent-skills

An Agent Skills marketplace for Phase Two — Claude Code skills for configuring Keycloak/Phase Two extension behaviors, for both vanilla/self-hosted Keycloak and Phase Two hosted Keycloak.

Structured the same way as [auth0/agent-skills](https://github.com/auth0/agent-skills): a `.claude-plugin/marketplace.json` listing one or more plugins, each living under `plugins/<name>/` with its own `.claude-plugin/plugin.json` and `skills/`. Only the Claude platform surface is set up for now (no `.cursor-plugin`/`.codex-plugin`).

## Install

```
/plugin marketplace add p2-inc/agent-skills
/plugin install phasetwo
```

## Plugins

- [`phasetwo`](plugins/phasetwo/) — a unified `keycloak` skill that routes Keycloak/Phase Two requests to the right guidance. Today it covers turning on passwordless login by magic link; more capabilities get added as new reference docs under the same skill, once genuinely written and verified, rather than new skills.

## Dependency

The `keycloak` skill relies on the Keycloak MCP server to check deployment targets and verify changes against a live deployment:

```bash
mcp add --transport http keycloak https://mcp-staging.phasetwo.io/mcp
```

## Linting

This repo uses [skillsaw](https://github.com/stbenjam/skillsaw) to enforce Agent Skills structure and marketplace conventions. Config is in [`.skillsaw.yaml`](.skillsaw.yaml); repo-specific rules are in [`.skillsaw/rules.py`](.skillsaw/rules.py).
