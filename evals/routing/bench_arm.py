#!/usr/bin/env python3
# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Router arm for SkillsBench: does an agent that has the WHOLE skill reach the right reference?

    python3 evals/routing/bench_arm.py --list
    python3 evals/routing/bench_arm.py --task keycloak-totp-second-factor --dry-run
    python3 evals/routing/bench_arm.py --task keycloak-totp-second-factor --arm both
    python3 evals/routing/bench_arm.py --analyze <jobs dir> --task keycloak-totp-second-factor --arm router

Every benchmark here hands the agent the one skill it needs (`environment/skills/totpSecondFactorRest`),
so the router is never exercised: the benchmark measures the procedure, not the choice of it. This
runs the same task two ways:

  intent  the task's own REST skill, as the benchmark ships it (the control);
  router  the live `keycloak` and `securing-apps` skills from this checkout (router, references,
          assets, scripts), so the agent has to find the right reference itself.

The task prompts are ordinary business requests that name no intent, so a router-arm pass means the
agent routed correctly AND configured Keycloak correctly. Routing is read from the agent's own
trajectory, with no self-report: which skill it loaded first, and which intent reference it read
first (`references/admin-<intent>.md`). The live skill is used rather than a copy inside a task,
so the scenario cannot go stale when the router changes.

bench_routes.json maps a benchmark to the route it should take: an intent id (`admin:...`), or
`skill:securing-apps` for the app-side tasks. Standard library only; shells out to `bench`.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SKILLS_DIR = REPO / "plugins" / "phasetwo" / "skills"
BENCH_DIR = REPO / "benchmarks"
ROUTES = HERE / "bench_routes.json"
ROUTER_SKILLS = ("keycloak", "securing-apps")
DEFAULT_MODEL = "aws-bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_AGENT = "claude-agent-acp"
REFERENCE = re.compile(r"references/(admin-[a-z0-9-]+?)(-mcp)?\.md")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


# --- scenarios -------------------------------------------------------------------------------


def load_routes(path=ROUTES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stem_to_intent(stem):
    """admin-totp-second-factor -> admin:totp-second-factor"""
    return stem.replace("-", ":", 1)


def intent_skill_dirs(task_dir):
    """The control arm's skills: the task's REST skill(s), not the MCP variants (the public
    build has no MCP server). `*Rest` if present, else every dir not ending in `Mcp`."""
    base = Path(task_dir) / "environment" / "skills"
    dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    rest = [d for d in dirs if d.name.endswith("Rest")]
    return rest or [d for d in dirs if not d.name.endswith("Mcp")]


def build_skills_dir(arm, task_dir, dest, skills_dir=SKILLS_DIR):
    """Populate `dest` with the skills an arm gives the agent; returns the names deployed."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if arm == "router":
        sources = [Path(skills_dir) / name for name in ROUTER_SKILLS]
    elif arm == "intent":
        sources = intent_skill_dirs(task_dir)
    else:
        raise ValueError(f"unknown arm {arm!r}")
    if not sources:
        raise RuntimeError(f"{task_dir} ships no REST skill for the intent arm")
    for src in sources:
        shutil.copytree(src, dest / src.name, ignore=IGNORE)
    return [s.name for s in sources]


def bench_argv(task_dir, jobs_dir, skills_dir, model=DEFAULT_MODEL, agent=DEFAULT_AGENT):
    return ["bench", "eval", "run", "--tasks-dir", str(task_dir), "--agent", agent,
            "--sandbox", "docker", "--jobs-dir", str(jobs_dir), "--model", model,
            "--skill-mode", "with-skill", "--skills-dir", str(skills_dir)]


# --- reading a run -----------------------------------------------------------------------------


def analyze_trajectory(path):
    """What the agent loaded, in order, from bench's llm_trajectory.jsonl: the skills named in
    `Skill` calls, and the intent references (`references/admin-*.md`) it opened with Read or
    shell commands. `intent_refs` holds each intent once, as `admin:...`, in first-read order."""
    skills, intents, tool_calls = [], [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                body = json.loads(line)["response"]["body"]
            except (KeyError, json.JSONDecodeError):
                continue
            for choice in body.get("choices", []):
                for call in choice.get("message", {}).get("tool_calls") or []:
                    tool_calls += 1
                    name, raw = call["function"]["name"], call["function"].get("arguments", "")
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {}
                    if name == "Skill" and args.get("skill") and args["skill"] not in skills:
                        skills.append(args["skill"])
                    elif name in ("Read", "Bash"):
                        text = args.get("file_path") or args.get("command") or ""
                        for m in REFERENCE.finditer(text):
                            intent = stem_to_intent(m.group(1))
                            if intent not in intents:
                                intents.append(intent)
    return {"skills": skills, "intent_refs": intents, "tool_calls": tool_calls}


def judge(expected, analysis):
    """The routing verdict. `expected` is an intent id or `skill:<name>`."""
    if expected.startswith("skill:"):
        route = analysis["skills"][0] if analysis["skills"] else None
        return {"route": route, "route_ok": route == expected.split(":", 1)[1]}
    route = analysis["intent_refs"][0] if analysis["intent_refs"] else None
    return {"route": route, "route_ok": route == expected,
            "also_read": [i for i in analysis["intent_refs"][1:]]}


def read_run(jobs_dir):
    """[{reward, cost, tool_calls, error, trajectory}] for every rollout under `jobs_dir`."""
    out = []
    for result in sorted(Path(jobs_dir).rglob("result.json")):
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "rewards" not in data and "agent_result" not in data:
            continue
        agent = data.get("agent_result") or {}
        rewards = data.get("rewards") or {}
        traj = result.parent / "trajectory" / "llm_trajectory.jsonl"
        out.append({"reward": rewards.get("reward"), "cost": agent.get("cost_usd"),
                    "tool_calls": agent.get("n_tool_calls"), "error": data.get("error"),
                    "trajectory": traj if traj.is_file() else None})
    return out


def score_run(task, arm, expected, jobs_dir):
    runs = read_run(jobs_dir)
    if not runs:
        return {"task": task, "arm": arm, "expected": expected, "error": f"no result.json under {jobs_dir}"}
    r = runs[0]
    row = {"task": task, "arm": arm, "expected": expected, "reward": r["reward"], "cost": r["cost"],
           "tool_calls": r["tool_calls"], "error": r["error"]}
    if r["trajectory"]:
        analysis = analyze_trajectory(r["trajectory"])
        row.update(judge(expected, analysis), skills=analysis["skills"])
    else:
        row.update(route=None, route_ok=None, skills=[], note="no trajectory found")
    return row


# --- reporting -----------------------------------------------------------------------------------


def _cell(v, fmt="{}"):
    return "-" if v is None else fmt.format(v)


def format_report(rows):
    lines = ["# SkillsBench router arm", "",
             "| task | arm | reward | route | expected | route ok | tool calls | cost |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {task} | {arm} | {reward} | {route} | {expected} | {ok} | {calls} | {cost} |".format(
            task=r["task"], arm=r["arm"], reward=_cell(r.get("reward")), route=_cell(r.get("route")),
            expected=r["expected"], ok={True: "yes", False: "NO", None: "-"}[r.get("route_ok")],
            calls=_cell(r.get("tool_calls")), cost=_cell(r.get("cost"), "${:.2f}")))
    by_task = {}
    for r in rows:
        by_task.setdefault(r["task"], {})[r["arm"]] = r
    pairs = [(t, a["router"], a["intent"]) for t, a in by_task.items() if "router" in a and "intent" in a]
    if pairs:
        lines += ["", "## Router vs intent arm", "| task | reward (router / intent) | tool calls | cost |", "|---|---|---|---|"]
        for t, rt, it in pairs:
            lines.append(f"| {t} | {_cell(rt.get('reward'))} / {_cell(it.get('reward'))} | "
                         f"{_cell(rt.get('tool_calls'))} / {_cell(it.get('tool_calls'))} | "
                         f"{_cell(rt.get('cost'), '${:.2f}')} / {_cell(it.get('cost'), '${:.2f}')} |")
    wrong = [r for r in rows if r.get("route_ok") is False and r["arm"] == "router"]
    if wrong:
        lines += ["", "## Misrouted"]
        for r in wrong:
            lines.append(f"- {r['task']}: expected {r['expected']}, first route {r.get('route')}"
                         + (f", also read {', '.join(r.get('also_read', []))}" if r.get("also_read") else ""))
    return "\n".join(lines)


# --- command line ----------------------------------------------------------------------------------


def run_arm(task, arm, expected, args, root):
    task_dir = BENCH_DIR / task
    jobs = root / f"{task}-{arm}" / "jobs"
    skills = root / f"{task}-{arm}" / "skills"
    names = build_skills_dir(arm, task_dir, skills)
    argv = bench_argv(task_dir, jobs, skills, args.model, args.agent)
    print(f"[{task} / {arm}] skills: {', '.join(names)}", file=sys.stderr)
    if args.dry_run:
        print(" ".join(argv))
        return None
    jobs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("AWS_REGION", "us-east-1")
    started = time.time()
    with open(jobs / "run.log", "w") as log:
        subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=args.timeout)
    print(f"[{task} / {arm}] finished in {time.time() - started:.0f}s", file=sys.stderr)
    return score_run(task, arm, expected, jobs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="list the scenarios")
    ap.add_argument("--task", action="append", help="benchmark (repeatable); default: none")
    ap.add_argument("--arm", choices=["router", "intent", "both"], default="router")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--agent", default=DEFAULT_AGENT)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per run")
    ap.add_argument("--work-dir", help="where skills dirs and job output go (default: a temp dir)")
    ap.add_argument("--dry-run", action="store_true", help="build the skills dirs and print the bench commands")
    ap.add_argument("--analyze", metavar="JOBS_DIR", help="score an existing bench jobs dir; needs one --task and --arm")
    ap.add_argument("--out", help="write the rows as JSON")
    args = ap.parse_args(argv)

    routes = load_routes()
    if args.list:
        for task, expected in routes.items():
            print(f"{task:44s} -> {expected}")
        return 0
    if not args.task:
        ap.error("give --task (or --list)")
    unknown = [t for t in args.task if t not in routes]
    if unknown:
        ap.error(f"not in bench_routes.json: {', '.join(unknown)}")

    if args.analyze:
        if len(args.task) != 1 or args.arm == "both":
            ap.error("--analyze scores one task and one arm")
        rows = [score_run(args.task[0], args.arm, routes[args.task[0]], args.analyze)]
    else:
        if not args.dry_run and not shutil.which("bench"):
            print("error: the `bench` CLI is not on PATH", file=sys.stderr)
            return 2
        root = Path(args.work_dir or tempfile.mkdtemp(prefix="route-arm-"))
        arms = ["router", "intent"] if args.arm == "both" else [args.arm]
        rows = [run_arm(t, a, routes[t], args, root) for t in args.task for a in arms]
        rows = [r for r in rows if r]
    if rows:
        print(format_report(rows))
        if args.out:
            Path(args.out).write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
