<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# keycloak-skills

An Agent Skills marketplace for Phase Two — Claude Code skills for configuring Keycloak/Phase Two extension behaviors, for both vanilla/self-hosted Keycloak and Phase Two hosted Keycloak.

Structured the same way as [auth0/agent-skills](https://github.com/auth0/agent-skills): a `.claude-plugin/marketplace.json` listing one or more plugins, each living under `plugins/<name>/` with its own `.claude-plugin/plugin.json` and `skills/`. Only the Claude platform surface is set up for now (no `.cursor-plugin`/`.codex-plugin`).

## Install

```bash
claude plugin marketplace add p2-inc/keycloak-skills
```

```bash
claude plugin install phasetwo@keycloak-skills
```

Then restart Claude Code (or open a new session) — skills are loaded at session start.

Or interactively inside a Claude Code session: `/plugin marketplace add p2-inc/keycloak-skills`, then `/plugin install phasetwo`.

How the ids fit together: the repo root *is* the marketplace — that's where [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) lives. `keycloak-skills` is the marketplace name declared in that file (it matches the repo name); `phasetwo` is the plugin inside it. That pairing is what `plugin@marketplace` ids are built from: `phasetwo@keycloak-skills`.

### From a local checkout

Same two commands — point the marketplace at your clone instead of the GitHub slug. Use an absolute path:

```bash
claude plugin marketplace add /absolute/path/to/keycloak-skills
```

```bash
claude plugin install phasetwo@keycloak-skills
```

A marketplace added from a directory reads the checkout **live**: its `installLocation` is the repo path itself, not a cached copy, so uncommitted edits take effect with no refresh step. Add `--scope project` to `marketplace add` to record the marketplace in this checkout's own settings instead of your user config, so everyone working in the repo picks up the same plugin; `--scope local` keeps it to your machine without touching either.

### While developing the plugin

Validate before you install — the first command checks the marketplace manifest, the second the plugin manifest and the skills under it:

```bash
claude plugin validate .
```

```bash
claude plugin validate plugins/phasetwo --strict
```

Neither one verifies that an MCP server is actually wired up (see [Dependency](#dependency)), so confirm components separately:

```bash
claude plugin details phasetwo
```

That prints the component inventory — `Skills`, `MCP servers`, `Hooks` — plus the projected always-on vs on-invoke token cost. It is the only check that proves the runtime sees what you declared. `skillsaw` (see [Linting](#linting)) is the deeper lint on the skills themselves.

For a marketplace added from a git or GitHub source rather than a directory, pull new commits with:

```bash
claude plugin marketplace update keycloak-skills
```

### Verify, and back out

```bash
claude plugin list
```

```bash
claude plugin uninstall phasetwo
```

```bash
claude plugin marketplace remove keycloak-skills
```

Renaming the marketplace in `marketplace.json` **silently orphans existing installs** — the registration is keyed on that name, so anyone who added the old one loses the plugin with no error message and has to re-add and reinstall.

### If you have a copy in `~/.claude/skills/`

A plain directory in `~/.claude/skills/<name>/` also auto-loads, as `<name>@skills-dir`, which makes it a quick way to try one skill on its own. It is a **copy**, though: it does not track your checkout, it goes stale silently, and if you also install the plugin you end up with two `keycloak` skills of different vintages in the same session. Prefer the local marketplace above, and delete `~/.claude/skills/keycloak/` once the plugin is installed.

## Plugins

- [`phasetwo`](plugins/phasetwo/) — a unified `keycloak` skill that routes Keycloak/Phase Two requests to the right guidance: passwordless login (magic link, email OTP, passkey, or passkey-or-magic-link), email OTP as a second factor, organization-membership login restriction, corporate SSO by email domain, social login and enterprise IdP federation, IdP-initiated SSO, and Phase Two cluster/deployment provisioning. New capabilities get added as reference docs under the same skill, once genuinely written and verified, rather than as new skills.

## Dependency

The `keycloak` skill relies on the Keycloak MCP server to check deployment targets and verify changes against a live deployment. The plugin **declares it** in [`plugins/phasetwo/.mcp.json`](plugins/phasetwo/.mcp.json), so installing the plugin connects it — there is no command to run:

```json
{ "mcpServers": { "keycloak": { "type": "http", "url": "https://mcp.phasetwo.io/mcp" } } }
```

That file has to sit at the plugin root, beside `.claude-plugin/`. An `mcpServers` key inside `plugin.json` passes `claude plugin validate --strict` but is silently ignored at runtime — `claude plugin details phasetwo` reports `MCP servers (0)`. Endpoints are unversioned and images are tagged by commit, so this URL picks up new server releases with no change here.

It is a remote server behind OAuth, so the first tool call prompts you to authorize; check the connection with `/mcp` in a session. If you are using the skill *without* the plugin — a copy under `~/.claude/skills/`, say — add it yourself, since nothing declares it for you:

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
