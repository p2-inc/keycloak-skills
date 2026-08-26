# Runbook: adding a skill to this repository

This repo is an Agent Skills marketplace: `.claude-plugin/marketplace.json` lists one or more
plugins, each under `plugins/<name>/`, each containing one or more skills under
`plugins/<name>/skills/<skill-name>/`. Today there is one plugin (`phasetwo`) and one skill
(`keycloak`) — a **router** that dispatches by intent + tooling to reference docs, rather than
one skill per capability. Read this whole document before writing anything; it assumes that
shape throughout.

## 0. Prerequisites

Install [skillsaw](https://github.com/stbenjam/skillsaw) — this repo's linter, which enforces
Agent Skills structure, frontmatter, and marketplace conventions (config in
[`.skillsaw.yaml`](../.skillsaw.yaml), custom rules in [`.skillsaw/rules.py`](../.skillsaw/rules.py)).
It's a PyPI package; install it as a standalone CLI tool rather than into a project virtualenv:

```bash
uv tool install skillsaw
# or: pipx install skillsaw
```

Run it from the repo root before opening a PR:

```bash
skillsaw lint .
```

Note the CLI is `skillsaw lint .` (or bare `skillsaw`, which defaults to linting the current
directory) — there is no `skillsaw check` subcommand, despite what older habit or muscle memory
might suggest. `.skillsaw.yaml`'s `version:` field pins the skillsaw release this config targets;
bump it (and re-check for newly-deprecated rule names, e.g. `skill-frontmatter` →
`agentskill-valid` as of 0.18.0) when you upgrade the installed CLI.

A clean run reports `Errors: 0` and a letter grade; treat any error as blocking and warnings as
worth a look before merging.

## 1. Where do I go to write the skill? What directories are important?

```
keycloak-skills/
├── .claude-plugin/marketplace.json       ← lists every plugin (name, version, description, ...)
├── plugins/
│   └── phasetwo/                         ← one plugin
│       ├── plugin.json                   ← plugin metadata (kept in sync with the one below)
│       ├── .claude-plugin/plugin.json    ← canonical Claude plugin manifest
│       ├── .mcp.json                      ← MCP servers the plugin connects (NOT plugin.json)
│       ├── README.md                     ← must list every skill in this plugin
│       └── skills/
│           └── keycloak/                 ← one skill = one router
│               ├── SKILL.md              ← the router itself (frontmatter + intent table)
│               └── references/
│                   ├── README.md         ← manifest of every reference file
│                   └── admin-*.md        ← the actual instructional content
└── benchmarks/                           ← skillsbench eval tasks (see §4), NOT plugin content
```

**In almost all cases you are not creating a new skill directory.** You are adding a new
*intent* + *reference file(s)* to the existing `keycloak` router (see §3).

The real test for whether it belongs in the router isn't *domain* (Keycloak vs. not) — it's the
**shape of the work**:

**Stays in the router** (new intent + reference file) when the capability is still "call some
Keycloak/Phase Two API (MCP tools or REST) to configure something on a realm/cluster/deployment,"
and fits the router's existing mechanics: pick an intent (Step 1), pick a tooling (Step 2 — even
if only one tooling applies, like the cluster/deployment intents), load one reference file
(Step 3). The cluster/deployment capabilities are a different *flavor* of work than passwordless
login (infra provisioning vs. auth config) but the same *shape* — that's why they're intents in
this router, not a new directory.

**Needs a new skill directory** (and possibly a new plugin) when:

1. **The task isn't "call an API to configure something" at all.** `SKILL.md`'s own description
   carves this out explicitly: *"Not general Keycloak/Phase Two administration or plugin
   development."* Writing a Keycloak Java SPI provider (like the real `keycloak-magic-link`
   provider this router's own passwordless skill depends on) is still 100% Keycloak-domain — but
   it's writing source code and building a jar, not driving an existing deployment through tool
   calls. Different shape, different skill.
2. **It doesn't fit the intent/tooling routing pattern** — it needs its own kind of "which tooling"
   question, its own dependency setup, or doesn't reduce to "one Read file per intent+tooling."
   Forcing it in just makes the router incoherent.
3. **It's genuinely unrelated to Keycloak/Phase Two** — e.g. Stripe billing internals, general AWS
   ops. (Connecting an external IdP *into* Keycloak, like Okta, is still Keycloak-domain and
   API-driven — that belongs in the router, not here.)
4. **Practical signal**: if adding it pushes the router's frontmatter `description` past
   skillsaw's length limit even after honest trimming (see §0), that's the router telling you it's
   doing too many unrelated things — split it, don't compress harder.

Per the Agent Skills spec (enforced here by [skillsaw](https://github.com/stbenjam/skillsaw)'s
`skill-directory-structure` rule), a skill directory may contain **only** `SKILL.md` at its
root — everything else goes in `scripts/`, `references/`, `assets/`, or `tests/`.

## 2. What is the naming convention for skills?

- **Skill/plugin directory names**: kebab-case-free single word or short identifier matching
  the domain (`keycloak`, `phasetwo`). There's only one of each here so far.
- **Reference files** (`references/*.md`): `admin-<intent>-{tooling}.md`, where `{tooling}` is
  `mcp` or omitted for the REST/plain variant. Examples already in the repo:
  - `admin-passwordless-magic-link.md` (REST) / `admin-passwordless-magic-link-mcp.md` (MCP)
  - `admin-passwordless-passkey.md` (REST) / `admin-passwordless-passkey-mcp.md` (MCP)
- **Intent names** (used in `SKILL.md`'s tables, not filenames): `<namespace>:<capability>`,
  kebab-case capability, e.g. `admin:passwordless-magic-link`, `admin:passwordless-passkey`.
- **Markdown naming rule** (skillsaw `skill-markdown-naming`): only `SKILL.md` is allowed in a
  skill's root; every other `.md` file (in `references/`, etc.) must be kebab-case. `SKILL.md`
  and `README.md` are exempt.
- **SKILL.md frontmatter** (skillsaw `skill-required-metadata`) must include:
  - `name`, `description` (spec-required)
  - `license` (e.g. `Apache-2.0`)
  - `metadata.author` in the exact form `Name <email>` (e.g. `Phase Two <support@phasetwo.io>`)
  - `metadata.version` — bump this (semver) whenever you touch the router or its references

## 3. What must be added to the router when adding a new skill/capability?

The router is [`plugins/phasetwo/skills/keycloak/SKILL.md`](../plugins/phasetwo/skills/keycloak/SKILL.md).
It carries **no domain content itself** — every instruction lives behind a `Read:` pointer to a
reference file, loaded on demand. Its own doc (`references/README.md`'s "Authoring conventions")
states the governing rule: **grow this router by adding intents + references once the content
is genuinely written and verified — never stub out a capability ahead of time.**

Checklist for adding a new intent (e.g. a new passwordless mechanism, a new admin task, etc.):

1. **`SKILL.md` Step 1** — add a row to the intent table: plain-language triggers a developer
   would actually say → your new `namespace:capability` intent. Include what it's *not* (adjacent
   but different capabilities), the same way existing rows do.
2. **`SKILL.md` Step 3** — add a `Read:` mapping block for your intent, one line per tooling
   variant you've actually written. If you've only written one tooling variant (e.g. MCP only),
   say so explicitly rather than pointing at a REST file that doesn't exist yet.
3. **`references/<your-files>.md`** — write the actual instructional content (see the existing
   `admin-passwordless-*.md` files for the expected depth: what tools/endpoints, common traps,
   how to verify the result actually worked, a troubleshooting table).
4. **`references/README.md`** — add a row to the reference-file manifest table (file, intent
   (tooling), status). If a tooling variant is intentionally missing, list it with a "not written
   yet" status rather than omitting it silently.
5. **`SKILL.md` frontmatter** — update the top-level `description` to mention the new capability
   (this drives routing/triggering — be as specific as the existing description is about what is
   and isn't covered), and bump `metadata.version`.
6. **Plugin-level files** — update `plugins/phasetwo/plugin.json`, `.claude-plugin/plugin.json`
   (description, version bump, `keywords` if relevant), and `plugins/phasetwo/README.md`'s skill
   list.
7. **`.claude-plugin/marketplace.json`** (repo root) — this lists the plugin's `version` and
   `description` independently of `plugins/phasetwo/plugin.json`. **Check it's actually in sync**
   before you finish — as of this writing it still says `version: 0.1.0` and an old description
   while the plugin itself is at a newer version, so don't assume the two stay in sync
   automatically.

Confirm live MCP tool names before writing an MCP reference — don't assume a tool exists on the
Keycloak MCP server without checking what's actually exposed (a missing tool is a real,
documented gap; a wrong guess isn't).

## 4. Testing and benchmarking a new skill

### Where these files live

Benchmark tasks live in **`benchmarks/<task-name>/`** at the repo root — sibling to `plugins/`,
not inside it. This directory holds [SkillsBench](https://github.com/benchflow-ai/skillsbench)
task definitions and is excluded from skillsaw linting (`benchmarks/**` in `.skillsaw.yaml`)
since it isn't distributable plugin content.

```
benchmarks/<task-name>/
├── task.md              ← schema_version, metadata, verifier/agent/sandbox config, the prompt
├── environment/
│   ├── Dockerfile        ← builds the sandbox; pull large prebuilt binaries, don't vendor them
│   └── skills/           ← optional: standalone skill(s) for isolated with-skill eval runs
├── oracle/
│   ├── solve.py / solve.sh   ← a real, working solution proving the task is solvable
└── verifier/
    ├── test.sh, test_outputs.py, rubrics/
```

### Writing a new benchmark task

1. Author `task.md` with the SkillsBench schema (`schema_version`, `metadata` block including
   `difficulty`/`difficulty_explanation`/`category`/`tags`, `verifier`/`agent`/`sandbox` config).
2. Build `environment/` — a `Dockerfile` plus any fixtures (realm JSON, credentials files with
   **sandbox-only dummy values**, mail-capture servers, etc.). If the task needs a large prebuilt
   binary (e.g. an internal MCP server jar), **pull it from a registry in a multi-stage Docker
   build, pinned by digest** — don't commit the binary. Example from this repo's own Dockerfiles:
   ```dockerfile
   FROM 773532640636.dkr.ecr.us-west-2.amazonaws.com/mcp/staging:latest AS mcp-app
   ...
   COPY --from=mcp-app /deployments /opt/mcp-app
   ```
   The MCP server image lives in **Phase Two's ECR staging repository**
   (`arn:aws:ecr:us-west-2:773532640636:repository/mcp/staging`), and every benchmark tracks
   `:latest` so runs exercise the current staging build. The trade-off is deliberate but real: a
   run is only reproducible relative to whatever `:latest` pointed at that day. Pin a digest
   (`@sha256:<digest>`) instead when a specific result has to be reproducible later.

   **ECR requires authentication to pull.** Log in yourself, in your own terminal, before
   building:
   ```bash
   aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 773532640636.dkr.ecr.us-west-2.amazonaws.com
   ```
   Use your own AWS credentials — don't hand credentials to an AI assistant to enter on your
   behalf. Without this, the pull fails with an authentication error even though the reference
   looks like a normal image pull. The ECR login token expires (12 hours), so a build that worked
   yesterday can fail today for this reason alone.
3. Write `oracle/solve.py` (+ `solve.sh` wrapper) — a real solution using the same
   REST/tool calls a human or agent would use. This is also your best source of ground truth
   when writing the corresponding skill reference doc.
4. Write `verifier/test.sh` + `test_outputs.py` (+ `rubrics/` if using rubric-based scoring).
5. If you want to test a skill in isolation (MCP-only vs REST-only, with-skill vs no-skill),
   drop standalone `SKILL.md` files under `environment/skills/<SomeSkillName>/` — note this
   directory's own naming convention differs from §2's (camelCase, e.g.
   `passwordlessPasskeyLoginMcp`, `passwordlessPasskeyLoginRest`), since these aren't part of the
   distributable plugin, just eval fixtures.

### Running it

Requires the `bench` CLI ([BenchFlow](https://github.com/benchflow-ai/benchflow),
`uv tool install benchflow`), Docker, and (for real agent runs) `ANTHROPIC_API_KEY` — put it in
a `.env` file, **never paste a key into chat with an AI assistant**; it ends up in transcripts.

> **Prerequisite: the oracle must pass with reward 1.0 before you run any real (paid) agent.**
> The oracle doesn't cost API tokens — it's a plain script proving the task is actually solvable
> the "correct" way. Skipping straight to a real agent means you might spend real money
> discovering the *task itself* is broken or unsolvable, not that the skill/agent failed.
> This is [skillsbench's own documented policy](https://github.com/benchflow-ai/skillsbench/blob/main/CONTRIBUTING.md),
> not a convention specific to this repo — see its `CONTRIBUTING.md`: "Make the oracle pass with
> reward 1.0 before agent runs" (Do/Avoid list) and "Oracle and verifier must not require paid API
> keys" (PR Requirements: `bench eval run --tasks-dir tasks/<task-id> --agent oracle --sandbox
> docker` must pass with reward 1.0, listed before any agent-run requirement).

```bash
# 1. Structural validation.
bench tasks check benchmarks/<task-name>

# 2. Oracle must pass before anything else — proves the task is actually solvable,
#    and costs nothing. Do not proceed to step 3 until this is reward=1.0.
bench eval run --tasks-dir benchmarks/<task-name> --agent oracle --sandbox docker

# 3. Real agent run (costs real API tokens), with a specific skill variant injected.
bench eval run --tasks-dir benchmarks/<task-name> \
  --agent claude-agent-acp --model claude-sonnet-5 \
  --skill-mode with-skill \
  --skills-dir benchmarks/<task-name>/environment/skills/<SomeSkillName> \
  --sandbox docker \
  --jobs-dir benchmarks/<task-name>/jobs-local-<variant>
```

Compare `with-skill` vs `no-skill`, and MCP-tooling vs REST-tooling variants, by pointing
`--skills-dir` at different standalone skill folders and diffing the resulting `summary.json`
(`reward`, `total_cost_usd`, `total_tool_calls`, `elapsed_sec`).

**Known local-Docker gotcha**: `claude-agent-acp` enforces an egress firewall (`iptables`) inside
the sandbox container for no-network tasks, which fails with `Permission denied (you must be
root)` on some Docker Desktop configurations (missing `NET_ADMIN`). Fix by adding a
`docker-compose.yaml` override in the task's own `environment/` directory (BenchFlow merges it
in automatically if present):
```yaml
services:
  main:
    privileged: true
```
This is scoped to the task's own compose override — no need to touch the installed `benchflow`
package itself.

Local run artifacts (`jobs-local*/` directories, and `.cache/` from `bench`'s own tool cache) are
gitignored — don't commit them; delete them once you've captured the numbers you need.

## 5. How do I PR a new skill for acceptance?

**There's no `CONTRIBUTING.md` or PR template in this repo yet** — the following is current
practice inferred from the repo's own tooling, not a documented policy. If you want a formal
process, that's worth writing down separately.

Before opening a PR:

1. Run `skillsaw lint .` from the repo root (see §0 for install) — catches missing frontmatter
   fields, undocumented skills, bad directory structure, naming violations, and oversized skill
   descriptions. Confirm `Errors: 0` before opening the PR; look at warnings too.
2. Confirm every file from §3's checklist is updated and consistent — especially
   `.claude-plugin/marketplace.json`, which is easy to forget since it's not next to the plugin
   it describes.
3. **Mandatory: a benchmark test (§4) for the new intent/capability, with the oracle passing at
   reward 1.0.** This is not conditional on "if you added or changed a benchmark task" — every new
   intent needs one. No benchmark test means no independent evidence the capability is even
   solvable, let alone that the skill helps solve it (see the "for dummies" explanation of why the
   oracle exists — it's the cheapest, free-to-run proof the task itself isn't broken).
4. **Mandatory: a results summary in the PR description.** At minimum, the oracle's `reward` from
   `summary.json`. If you ran a real agent comparison (with-skill vs. no-skill, or MCP vs. REST
   tooling), include those `reward`/`total_cost_usd`/`total_tool_calls` numbers too — this is the
   evidence that the skill actually helps, not just that it exists.
5. Open the PR against `main` with a description of the new intent/capability, which reference
   file(s) it added, and the results summary from step 4.

A skillsaw CI check now exists: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs
`skillsaw` plus `claude plugin validate --strict` on every PR into `main`. The other gates in that
family — a PR template enforcing the §3 checklist, required benchmark evidence — do **not** exist
yet; flag them as follow-up work rather than assuming they do.

The lint job reads [`.skillsaw-baseline.json`](../.skillsaw-baseline.json), which records the
router's current context-budget violations as **ceilings**, not as exemptions. Growing `SKILL.md`
past its current size fails CI; shrinking it always passes. If you hit that, trim the router rather
than regenerating the baseline — regenerating silences the ratchet, which is the one thing keeping
the always-loaded router from growing without limit.

> **Known gap, called out honestly**: the `admin:cluster-setup` / `admin:cluster-create-deployment`
> intents added earlier in this repo's history do **not** have a corresponding benchmark task yet
> — they were added before this mandatory requirement was written down. Retrofitting one is
> follow-up work, not something to assume already covered.
