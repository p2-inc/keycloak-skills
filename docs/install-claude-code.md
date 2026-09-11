<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Install with Claude Code

## From GitHub

```bash
claude plugin marketplace add p2-inc/keycloak-skills
```

```bash
claude plugin install phasetwo@keycloak-skills
```

Or interactively inside a Claude Code session: `/plugin marketplace add p2-inc/keycloak-skills`, then `/plugin install phasetwo`.

The repo root *is* the marketplace — that's where [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) lives. `keycloak-skills` is the marketplace name declared in that file (it matches the repo name); `phasetwo` is the plugin inside it. That pairing is what `plugin@marketplace` ids are built from: `phasetwo@keycloak-skills`.

## From a local checkout

Same two commands — point the marketplace at your clone instead of the GitHub slug. Use an absolute path:

```bash
claude plugin marketplace add /absolute/path/to/keycloak-skills
```

```bash
claude plugin install phasetwo@keycloak-skills
```

Then **restart Claude Code** (or open a new session) — skills are loaded at session start, so an already-running session won't see the plugin.

A marketplace added from a directory reads the checkout **live**: its `installLocation` is the repo path itself, not a cached copy, so uncommitted edits take effect with no refresh step. Add `--scope project` to `marketplace add` to record the marketplace in this checkout's own settings instead of your user config, so everyone working in the repo picks up the same plugin; `--scope local` keeps it to your machine without touching either.

## While developing the plugin

Validate before you install — the first command checks the marketplace manifest, the second the plugin manifest and the skills under it:

```bash
claude plugin validate .
```

```bash
claude plugin validate plugins/phasetwo --strict
```

Neither one verifies that an MCP server is actually wired up (see [Dependency](../README.md#dependency)), so confirm components separately:

```bash
claude plugin details phasetwo
```

That prints the component inventory — `Skills`, `MCP servers`, `Hooks` — plus the projected always-on vs on-invoke token cost. It is the only check that proves the runtime sees what you declared. `skillsaw` (see [Linting](../README.md#linting)) is the deeper lint on the skills themselves.

For a marketplace added from a git or GitHub source rather than a directory, pull new commits with:

```bash
claude plugin marketplace update keycloak-skills
```

## Verify, and back out

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

## If you have a copy in `~/.claude/skills/`

A plain directory in `~/.claude/skills/<name>/` also auto-loads, as `<name>@skills-dir`,
which makes it a quick way to try one skill on its own. It is a **copy**, though: it does
not track your checkout, it goes stale silently, and if you also install the plugin you
end up with two `keycloak` skills of different vintages in the same session. Prefer the
local marketplace above, and delete `~/.claude/skills/keycloak/` once the plugin is
installed.
