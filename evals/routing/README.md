<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Routing check

Does a model send each request to the right intent, and the right skill? Routing is where a
router skill quietly breaks: a wrong row sends a developer down the wrong procedure with full
confidence, and nothing else in this repo would notice. The benchmarks measure what happens
*after* the right reference is loaded; this measures whether it gets loaded.

It exists to answer one question with evidence before it is answered by opinion: **can the
`keycloak` router be tightened, or split into several skills, without routing worse?** Run it
before and after.

## What it measures

| `--level` | The model sees | Question |
|---|---|---|
| `intent` | the whole router `SKILL.md` | Which intent row does this request belong to, or `NONE` (not covered), or `DENY` (Step 0: a deletion)? |
| `skill` | only each skill's `name` and `description` | Which skill would be loaded, if any? |

The second level matters because a skill is activated by its frontmatter description, which is
capped at 1,024 characters, and that cap, not the intent table, limits how many intents one
skill can advertise.

## Files

| | |
|---|---|
| `cases.jsonl` | 95 requests, each with the expected `intent` and a `group` |
| `groups.json` | which skill should handle each group (today every Keycloak group → `keycloak`) |
| `route_check.py` | the runner (standard library only) |
| `test_route_check.py` | offline tests: `python3 -m unittest discover -s evals/routing` |

The prompts are fresh paraphrases. `--check` warns when one repeats a trigger phrase quoted in
the router, because that would test string matching, not understanding. A `planned` case names
an intent that does not exist yet and is expected to route to `NONE` until it does, then to the
intent itself.

## Running it

```bash
python3 evals/routing/route_check.py --check       # validate the cases; free
python3 evals/routing/route_check.py --dry-run     # one prompt and a cost estimate; free
```

With an Anthropic API key (about $0.45 for `--level intent`, $0.06 for `--level skill`):

```bash
export ANTHROPIC_API_KEY=...
python3 evals/routing/route_check.py --level intent
python3 evals/routing/route_check.py --level skill
```

Through Amazon Bedrock Mantle's Anthropic endpoint:

```bash
export AWS_BEARER_TOKEN_BEDROCK=...
python3 evals/routing/route_check.py --level intent \
  --base-url https://bedrock-mantle.us-east-1.api.aws/anthropic \
  --model anthropic.claude-haiku-4-5 --key-env AWS_BEARER_TOKEN_BEDROCK
```

To compare a change with `main`, score both routers with the same cases:

```bash
git show origin/main:plugins/phasetwo/skills/keycloak/SKILL.md > /tmp/router-main.md
python3 evals/routing/route_check.py --router /tmp/router-main.md --out /tmp/main.json
python3 evals/routing/route_check.py --out /tmp/branch.json
```

The report gives accuracy overall, by group and by intent, then every wrong answer and the
confusions (`expected → got`) ranked by count. The confusions are the useful part: they name
which pair of rows a model cannot tell apart.

## Adding an intent

`--check` fails until every router intent has at least three cases, so a new intent comes with
its evidence. Write fresh paraphrases (not the router's trigger phrases), include requests that
sit next to a neighbouring intent, and set a `group`. If the intent is not in the router yet,
mark its cases `"planned": true`.

## Planned layout

The groups are the boundaries a split of the `keycloak` skill would use:

| Group | Intents |
|---|---|
| `auth-flows` | passwordless-magic-link, email-otp-login, password-email-otp-mfa, totp-second-factor, passwordless-passkey, zero-password-login, password-or-passkey-login (and step-up) |
| `organizations` | corporate-sso, org-restrict-login, idp-org-restrict-login, passwordless-magic-link-org-restrict |
| `identity-providers` | social-login, idp-federation, idp-initiated-sso |
| `realm-admin` | cluster-setup, cluster-create-deployment, credential-enrollment |

If the skill is split, change the right-hand side of `groups.json` to the new skill names and
add the new descriptions; the same cases then score the new layout.

## Limits

- One sample per case at temperature 0: a case that flips between runs is not detected.
- `--level skill` pits a plugin's own skills against each other, not the dozens a user may have
  installed.
- It stops at routing. Step 2 (are you a Phase Two user?) and everything after it are not run.
- The cases are written by us. Real requests from users are better; add them as they turn up.
