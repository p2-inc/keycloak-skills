<!-- Copyright 2026 Phase Two, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# Building and evaluating agent skills — distilled lessons

Portable rules extracted from building the `keycloak` router skill and its benchmarks. Written to
be pasted into a context window: each rule is prescriptive, with the shortest evidence that makes
it credible. Keycloak specifics appear only as worked examples.

---

## 1. Authoring a skill

**Verify against source AND a live system. Docs and fixtures are not spec.**
A user-supplied test fixture was faithfully mirrored into a skill asset; it contained a real
account-enumeration leak. Reading the *target* authenticator's source correctly was still not
enough — the leak lived in a **different, earlier** component in the same pipeline, which rejected
unknown users before the target ever ran. Only driving a real request against a live system caught
it. Corollary: *"component X is anti-enumeration-safe"* can be true while *"the flow containing X"*
is not.

**The same component can be correct in one skill and a bug in another.**
`auth-username-password-form` is the right first step for a password+OTP (2FA) skill and the wrong
one for a passwordless-OTP skill. Never copy a step between skills because it "looks like the same
shape" — state *why* it belongs, per skill.

**Make load-bearing order explicit, with the failure mode.**
"A must run before B" is useless without "otherwise C happens silently." Write the consequence:
*"putting the send step before the gate emails everyone regardless of membership."*

**Document defaults that differ between sibling components.**
Two authenticators sharing a config key had opposite defaults (`false` vs `true`). A reader who
generalises from one gets it wrong. Say which is which and that they differ.

**Disambiguate confusable intents in the intent table itself.**
Every routing row states what it is **not**, naming the sibling intent. Requests like "email OTP",
"2FA by email", and "magic link restricted to an org" collide badly in natural phrasing; the
disambiguation *is* the routing logic.

**Progressive disclosure is the architecture, not a nicety.**
Router holds no domain content: metadata always loaded → detect intent → detect tooling → load
exactly one reference file. Keeps context small and stops unrelated guidance leaking in.

**The frontmatter `description` is the binding constraint.**
Hard limit ~1024 chars / ~500 tokens; soft warning ~200 tokens. It needed trimming twice as
intents were added. Budget it deliberately — and it must contain trigger phrasing (`Use when …`)
or the skill never activates. Adding an intent without adding its trigger vocabulary is a silent
no-op.

**When a skill can't cover a request, say so and offer to file a gap issue.**
Include the developer's **verbatim** prompt in that issue. A paraphrase loses exactly the phrasing
future routing needs to recognise the case.

**Write the reference doc first, then derive the benchmark from it.**
Doing the reverse left a proven procedure sitting in the test tree while the shipped skill
declared that path missing.

---

## 2. Evaluating a skill — the part most often skipped

**A no-skill baseline is mandatory. Without it, success tells you nothing.**
Measured here: both tasks passed at reward 1.0 *without* the skill. So the skills do not enable a
capability — they cut its cost. Any claim of "the skill works" that lacks a baseline is unfounded.

**Skills usually buy efficiency, not capability. Measure accordingly.**
Track pass/fail **and** tool calls, cost, wall time. Real numbers from one task:

| Arm | Reward | Tool calls | Cost | Wall |
|---|---|---|---|---|
| no-skill | 1.0 | 126 | $5.59 | 40.5 min |
| with-skill | 1.0 | 33 | $0.85 | 3.5 min |

**Run the oracle first — it is free and it proves the task isn't broken.**
Policy: oracle must reach reward 1.0 before any paid agent run.

**An oracle failure with a passing verifier means the verifier is broken.**
Observed: `reward=1.0` alongside `Oracle solve.sh exited with rc=1`. Never bank a green result
that contradicts itself. (Cause was a mail-capture format assumption, below.)

**Run the negative control: on unconfigured state the verifier MUST fail.**
A verifier that passes on a realm where nothing was done is measuring nothing.

**Negative assertions pass vacuously — gate them behind a liveness check.**
"No email was sent to the non-member" is trivially true when *nothing* sends email. Fix: a
fixture that first proves the positive path works, so the negative carries information. Before
this, a completely unconfigured environment scored partial credit on exactly the checks meant to
catch a wrong answer.

**Test the distinguishing property, not the happy path.**
"A valid user gets in" passes even when the gate is never consulted. The decisive assertions were:
a non-member gets *no email at all*; a wrong password sends *no email at all*. Those separate a
correct solution from one that merely looks correct.

**Don't over-constrain the solution. Resolve what's actually in effect.**
A verifier requiring a *realm-level* binding failed a correct solution that bound at *client*
level. Resolve the effective config the way the system itself resolves it (client override wins).

**Discover names, don't hardcode them.**
Aliases got hash-prefixed by the tool that created them; user-chosen names vary. Look up what was
actually created.

**Separate the tooling arms — and check what the "with-skill" arm actually measured.**
MCP-only vs REST-only on the same task: **37 vs 135** tool calls. Worse, the REST arm (135 calls,
42.5 min) was indistinguishable from no-skill (126, 40.5 min) — the prose guidance bought nothing
where the underlying path is inherently many calls. And the combined "with-skill" run (33 calls)
turned out to be measuring MCP, because the router had already chosen it. **A blended arm can
silently be a single-tooling arm.**

**n=1 is not evidence. Know your variance band before interpreting deltas.**
Identical reruns in this project swung $1.61 → $4.12. A 126→33 gap is trustworthy in direction; a
$0.83 → $1.07 gap is noise. Say which one you have.

**Watch for telemetry gaps.**
A 135-call, 42-minute run reported `total_cost_usd: 0`. Don't quote instrumented numbers you
haven't sanity-checked against wall time and call count.

**One task per capability is an anti-pattern; a deliberate pair is much better.**
Two tasks probing the *same* component in opposite configurations (passwordless vs password-gated)
revealed that skill value is concentrated in the task with a hidden trap — 74% savings vs 45%. A
single task would have implied a uniform benefit.

**Skills are model-dependent.** Everything above was measured on one model. Treat cross-model
transfer as unverified.

**Agents sometimes beat the oracle.** One discovered the target image already shipped a suitable
built-in flow, so no authoring was needed. Lead skills with "check what already exists."

---

## 3. Tooling and MCP design

**A tool that swallows the upstream error body is worse than no tool.**
The agent can neither succeed nor diagnose, so it abandons the tool surface and hand-rolls
everything — one measured case burned 94 calls / $5.34 where the fixed version used 46 / $1.13.
Fixing *only* the error-reporting bug produced −51% calls, −79% cost, 6 → 0 errored calls.

**A tool that reports incomplete state does the same damage.**
A "what is bound?" tool reported only realm-level config, so a successful *client-level* write
looked like a failure. In the trajectory the agent then made **13 consecutive shell calls and never
returned to the tool surface**. Rule: a state-reporting tool must report what is *effectively* in
force, resolved the way the target system resolves it — and its own "verify with X" hints must
point at a call that can actually see the thing just written.

**Read trajectories, not just scores.** Both findings above came from reading the tool-call
sequence. "Cleaner, more direct workflow" is a real signal; scores alone hide it.

---

## 4. Harness traps that masquerade as agent failure

Each of these cost a wasted run and initially looked like the skill or the model failing.

- **A dead/rotated API key** presents as a degenerate run: ~2 output tokens, 1 tool call, then a
  stall — *or* as a hard `401` after 60 minutes of wall time. **When output-token count is
  near-zero or a run stalls inexplicably, test the API key before concluding anything.**
- **Prebuilt-image tasks break skill-injection.** Skills are injected by adding layers and
  rebuilding; a task pinned to a prebuilt image skips the build, so the with-skill arm tries to
  *pull* an image that was only ever built locally. Locally-built images also get reclaimed
  between runs. Build in-test unless the image is genuinely published.
- **Generic env vars leak between co-located apps.** Setting `QUARKUS_MANAGEMENT_PORT` to dodge a
  port clash moved *both* Quarkus apps in the container onto the new port and reproduced the
  clash. Scope such settings to one process (`-D` on its JVM), not the environment.
- **Build-time vs runtime config.** `quarkus.management.enabled` cannot be changed at runtime;
  only the port can. Check which phase a setting belongs to before "overriding" it.
- **Minimal base images lack GNU tools.** BusyBox `find` has no `-printf` (breaks skill
  deployment); BusyBox `setpriv` lacks `--reuid`, so the harness falls back to a **login shell**
  that resets the environment and drops the API key — surfacing only as an opaque auth error.
  Install `findutils` and `util-linux-bins`.
- **Test-port collisions with unrelated long-lived containers** produce "N tests skipped" that
  reads as real failure. Move the test ports; don't kill someone else's containers.
- **`Secure`-flagged cookies + scripted HTTP.** Browsers send `Secure` cookies over
  `http://localhost` (loopback is a secure context); `requests` and `urllib` do not, so the first
  POST fails a CSRF/session check. Override the cookie policy, follow redirects manually, and
  never blindly follow a redirect to the app's callback (nothing listens there → opaque
  "Connection refused").
- **Assumed capture/log formats.** A mail-capture server wrote **JSON**, not `.eml`; its float
  `received_at` ends in six digits, so a `\b\d{6}\b` regex happily returned the timestamp instead
  of the 6-digit code. Parse the structure; don't regex the whole file.
- **Don't run rollouts concurrently on a contended machine** when you need clean per-run metrics.

---

## 5. Process

- **Benchmarks earn their cost by finding real product bugs.** Four defects in a production MCP
  server surfaced from agent runs, none from code review.
- **Distinguish "my test is wrong" from "the agent failed."** Several of the most confusing
  failures here were the verifier, the environment, or a dead key — not the skill.
- **Verify claims before repeating them.** A dependency cited across multiple docs and source
  comments had no public repository; nobody had checked. Confirm the primary source the first time
  a claim is used, not when someone tries to act on it.
- **Check the integration branch, not just `main`.** A merged fix looked "missing" because the
  repo promotes `dev` → `main`.
- **Merged ≠ deployed.** A fix on a branch is not in the published image the benchmarks pin. Those
  are separate milestones; state which one you mean.
- **Never put secrets in chat.** Route API keys through a gitignored `.env`; confirm presence with
  a `grep -q`, never by printing. Check `git status` before committing — a `.env` was once staged.
