<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-skills

An Agent Skills marketplace for Phase Two — Claude Code, Cursor and Codex skills for configuring Keycloak/Phase Two extension behaviors, for both vanilla/self-hosted Keycloak and Phase Two hosted Keycloak.

Each plugin lives under `plugins/<name>/`, with one shared set of Agent Skills and a manifest per platform — Claude Code, Cursor and Codex.
## Install

One plugin, three clients. Pick your guide:

| Client | Guide | Reads |
| --- | --- | --- |
| Claude Code | [docs/install-claude-code.md](docs/install-claude-code.md) | [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) |
| Cursor | [docs/install-cursor.md](docs/install-cursor.md) | [`.cursor-plugin/marketplace.json`](.cursor-plugin/marketplace.json) |
| Codex / ChatGPT | [docs/install-codex.md](docs/install-codex.md) | [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json) |

The repo root *is* the marketplace. `keycloak-skills` is the marketplace name declared
in those files (it matches the repo name); `phasetwo` is the plugin inside it. That
pairing is what ids like `phasetwo@keycloak-skills` are built from.

## Plugins

- [`phasetwo`](plugins/phasetwo/) — a unified `keycloak` skill that routes Keycloak/Phase Two requests to the right guidance: passwordless login (magic link, email OTP, passkey, or passkey-or-magic-link), email OTP as a second factor, organization-membership login restriction, corporate SSO by email domain, social login and enterprise IdP federation, IdP-initiated SSO, and Phase Two cluster/deployment provisioning. New capabilities get added as reference docs under the same skill, once genuinely written and verified, rather than as new skills.

## Dependency

The `keycloak` skill relies on the Keycloak MCP server to check deployment targets and verify changes against a live deployment. The plugin **declares it** in [`plugins/phasetwo/.mcp.json`](plugins/phasetwo/.mcp.json), so installing the plugin connects it — there is no command to run:

```json
{ "mcpServers": { "keycloak": { "type": "http", "url": "https://mcp.phasetwo.io/mcp" } } }
```

That file has to sit at the plugin root, beside `.claude-plugin/`. An `mcpServers` key inside `plugin.json` passes `claude plugin validate --strict` but is silently ignored at runtime — `claude plugin details phasetwo` reports `MCP servers (0)`. Cursor is the exception: its manifest schema *does* accept `mcpServers`, which is why the Cursor build declares its own entry with a pinned OAuth client (see [docs/install-cursor.md](docs/install-cursor.md)). Endpoints are unversioned and images are tagged by commit, so this URL picks up new server releases with no change here.

It is a remote server behind OAuth, so the first tool call prompts you to authorize; check the connection with `/mcp` in a session. Each client authenticates differently — see the install guide for [Claude Code](docs/install-claude-code.md), [Cursor](docs/install-cursor.md) or [Codex](docs/install-codex.md). If you are using the skill *without* the plugin — a copy under `~/.claude/skills/`, say — add it yourself, since nothing declares it for you:

```bash
claude mcp add --transport http keycloak https://mcp.phasetwo.io/mcp
```

## Linting

This repo uses [skillsaw](https://github.com/stbenjam/skillsaw) to enforce Agent Skills structure and marketplace conventions. Config is in [`.skillsaw.yaml`](.skillsaw.yaml); repo-specific rules are in [`.skillsaw/rules.py`](.skillsaw/rules.py).

## License

This repository is **dual-licensed by content type**, so the skills carry an
attribution-and-share-alike condition while the code stays permissive:

| Content | License | Text |
| --- | --- | --- |
| Skill content and documentation — `plugins/**/skills/**/*.md`, `docs/**/*.md`, `benchmarks/**/*.md`, `README.md` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | [`LICENSE`](LICENSE) |
| Code, scripts, and configuration — `scripts/`, bundled `assets/*.json`, benchmark harnesses, CI, lint rules | [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) | [`LICENSE-CODE`](LICENSE-CODE) |

Copyright 2026 Phase Two, Inc.

Every file whose format allows a comment carries an `SPDX-License-Identifier`
header, so a single `SKILL.md` or reference doc copied into someone's
`.claude/skills/` still declares its own terms — the licensing does not live only
at the repo root. Files that cannot carry a comment (JSON, `.jar`, fixture
`.txt`) follow the table above and the mapping in [`NOTICE`](NOTICE).

Bundled authentication-flow JSON under `skills/*/assets/` is Apache-2.0 rather
than CC BY-SA: it is configuration you import into your own realm, and ShareAlike
should not reach your realm's config.

### Attribution

If you redistribute, incorporate, or adapt the CC BY-SA 4.0 material, include
attribution substantially similar to:

```text
Contains material from "keycloak-skills" by Phase Two, Inc.
https://github.com/p2-inc/keycloak-skills
Licensed under CC BY-SA 4.0.
```

Adaptations must indicate that changes were made, and must themselves be
distributed under CC BY-SA 4.0 or a compatible license.

### Contributing

Contributors retain copyright in their contributions and license them to this
project under the license that applies to the file being changed — CC BY-SA 4.0
for skill content and documentation, Apache-2.0 for code. There is no CLA.
