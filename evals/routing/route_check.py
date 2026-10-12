#!/usr/bin/env python3
# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Routing check: does a model send each request to the right intent (or skill)?

    python3 evals/routing/route_check.py --check                  # validate cases.jsonl, free
    python3 evals/routing/route_check.py --dry-run                # prompts and a cost estimate, free
    python3 evals/routing/route_check.py --level intent           # score the router table
    python3 evals/routing/route_check.py --level skill            # score skill activation

Two levels, because routing happens twice:

  intent  The `keycloak` router is loaded and the model reads its Step 0 / Step 1: which intent
          row, if any, does the request belong to? (or NONE: not covered, DENY: Step 0.)
  skill   Only the skills' name + description are visible: which skill, if any, would the model
          load? Descriptions are what activates a skill, and they are the binding constraint
          (1,024 characters) on how many intents one skill can advertise.

Each case in cases.jsonl is a fresh paraphrase (none repeats a trigger phrase quoted in the
router) with the expected intent and a `group`. groups.json maps a group to the skill that
should handle it; today every Keycloak group maps to `keycloak`. After a split, edit that
file and the same cases score the new layout.

Standard library only. The model API is Anthropic Messages (`POST {base-url}/v1/messages`,
header `x-api-key`), which also covers Amazon Bedrock Mantle's /anthropic endpoint.
"""

import argparse
import collections
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SKILLS_DIR = REPO / "plugins" / "phasetwo" / "skills"
DEFAULT_ROUTER = SKILLS_DIR / "keycloak" / "SKILL.md"

# USD per million tokens (input, output), for the cost estimate only.
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "anthropic.claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
}
SPECIAL = ("NONE", "DENY")
MIN_CASES_PER_INTENT = 3

INTENT_SYSTEM = """You are an assistant helping developers with Keycloak. The skill below is \
loaded. For this check, do only its routing: apply Step 0 (a request to delete a cluster, \
deployment or realm is denied) and Step 1 (detect intent) to the user's message. Do not ask \
questions, do not use tools, do not carry out the request.

Answer with exactly one line and nothing else:
ROUTE: <the intent id from Step 1's table, for example admin:cluster-setup>
ROUTE: NONE   (no intent matches: this skill does not cover the request, or another skill should handle it)
ROUTE: DENY   (Step 0 applies)

--- SKILL ---
{skill}"""

SKILL_SYSTEM = """You are an assistant with the skills listed below. Each has a name and a \
description. Decide which ONE skill, if any, you would load for the user's message, judging \
only from the descriptions. Do not answer the message itself.

Answer with exactly one line and nothing else:
SKILL: <skill name>
SKILL: NONE   (no listed skill fits)

--- SKILLS ---
{skills}"""


# --- reading the repository --------------------------------------------------------------


def load_cases(path):
    cases = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    cases.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise SystemExit(f"{path}:{n}: not valid JSON: {e}")
    return cases


def router_ids(text):
    """Intent ids of the router's Step 1 table, in order."""
    return re.findall(r"^\|.*\|\s*\*\*(admin:[a-z0-9-]+)\*\*\s*\|\s*$", text, re.M)


def router_triggers(text):
    """Quoted trigger phrases of three or more words from the router's table rows."""
    out = []
    for row in re.findall(r"^\|.*\|\s*\*\*admin:[a-z0-9-]+\*\*\s*\|\s*$", text, re.M):
        out += [q for q in re.findall(r'"([^"]+)"', row) if len(q.split()) >= 3]
    return out


def parse_frontmatter(text):
    """{key: value} of the leading --- block; folded (`>`/`>-`) values joined with spaces.
    Enough for name/description; not a YAML parser."""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fields, key, folded = {}, None, False
    for line in m.group(1).split("\n"):
        top = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if top:
            key, val = top.group(1), top.group(2).strip()
            folded = val in (">", ">-", "|", "|-")
            fields[key] = "" if folded else val.strip("'\"")
        elif key and folded and line.startswith(" "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def skill_descriptions(skills_dir=SKILLS_DIR):
    out = {}
    for md in sorted(Path(skills_dir).glob("*/SKILL.md")):
        fm = parse_frontmatter(md.read_text(encoding="utf-8"))
        if fm.get("name") and fm.get("description"):
            out[fm["name"]] = fm["description"]
    return out


# --- the cases -----------------------------------------------------------------------------


def expected_intent(case, ids):
    """The intent a router that exists today should return. A `planned` case names an intent
    the router does not have yet: NONE until it does, then the intent itself."""
    intent = case["intent"]
    if intent in SPECIAL or intent in ids:
        return intent
    if case.get("planned"):
        return "NONE"
    raise ValueError(f"case {case['id']}: intent {intent!r} is not in the router")


def accepted_intents(case, ids):
    return {expected_intent(case, ids), *case.get("accept", [])}


def expected_skill(case, groups):
    return groups.get(case["group"]) or "NONE"


def check_dataset(cases, router_text, groups):
    """(errors, warnings). Errors are structure; warnings are leaks and thin coverage."""
    ids = router_ids(router_text)
    errors, warnings = [], []
    seen_id, seen_prompt = set(), set()
    for c in cases:
        for field in ("id", "prompt", "intent", "group"):
            if not c.get(field):
                errors.append(f"case {c.get('id', '?')}: missing {field}")
        cid = c.get("id", "?")
        if cid in seen_id:
            errors.append(f"duplicate case id {cid}")
        seen_id.add(cid)
        if c.get("prompt") in seen_prompt:
            errors.append(f"case {cid}: duplicate prompt")
        seen_prompt.add(c.get("prompt"))
        if c.get("group") not in groups:
            errors.append(f"case {cid}: group {c.get('group')!r} is not in groups.json")
        try:
            expected_intent(c, ids)
        except (KeyError, ValueError) as e:
            errors.append(str(e))
        for a in c.get("accept", []):
            if a not in ids and a not in SPECIAL:
                errors.append(f"case {cid}: accept {a!r} is not in the router")
    counts = collections.Counter(c["intent"] for c in cases if not c.get("planned") and not c.get("accept"))
    for intent in ids:
        if counts[intent] < MIN_CASES_PER_INTENT:
            errors.append(f"router intent {intent} has {counts[intent]} case(s); "
                          f"add at least {MIN_CASES_PER_INTENT} fresh paraphrases to cases.jsonl")
    triggers = router_triggers(router_text)
    for c in cases:
        low = c["prompt"].lower()
        for t in triggers:
            if t.lower() in low:
                warnings.append(f"case {c['id']} repeats the router's trigger phrase {t!r}: "
                                f"it tests string matching, not understanding")
    return errors, warnings


# --- the model -----------------------------------------------------------------------------


def build_request(level, case, router_text, descriptions):
    if level == "intent":
        return INTENT_SYSTEM.format(skill=router_text.strip()), case["prompt"]
    listing = "\n".join(f"- {name}: {desc}" for name, desc in descriptions.items())
    return SKILL_SYSTEM.format(skills=listing), case["prompt"]


def call_model(base_url, key, model, system, user, max_tokens=40, retries=4, timeout=120,
               sleep=time.sleep):
    """(text, input_tokens, output_tokens). Retries 429/5xx and network errors."""
    body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": 0,
                       "system": system, "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/messages", data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            if e.code not in (429, 500, 502, 503, 529):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = f"{type(e).__name__}: {e}"
        sleep(2 ** attempt)
    raise RuntimeError(f"model call failed: {last}")


def parse_answer(level, text):
    if level == "intent":
        m = re.search(r"ROUTE:\s*(admin:[a-z0-9-]+|NONE|DENY)\b", text, re.I)
    else:
        m = re.search(r"SKILL:\s*([A-Za-z0-9._-]+)", text, re.I)
    if not m:
        return "UNPARSEABLE"
    got = m.group(1)
    return got.upper() if got.upper() in SPECIAL else got


def run_cases(cases, level, router_text, descriptions, groups, call, concurrency=4):
    """Score every case. `call(system, user)` -> (text, tokens_in, tokens_out)."""
    ids = router_ids(router_text)

    def one(case):
        system, user = build_request(level, case, router_text, descriptions)
        want = ({expected_skill(case, groups)} if level == "skill" else accepted_intents(case, ids))
        try:
            text, tin, tout = call(system, user)
        except RuntimeError as e:
            return {"case": case, "got": "ERROR", "ok": False, "raw": str(e), "tin": 0, "tout": 0,
                    "want": sorted(want)}
        got = parse_answer(level, text)
        return {"case": case, "got": got, "ok": got in want, "raw": text.strip(),
                "tin": tin, "tout": tout, "want": sorted(want)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(one, cases))


# --- reporting -----------------------------------------------------------------------------


def estimate_cost(model, tin, tout):
    price = PRICES.get(model)
    return None if price is None else tin / 1e6 * price[0] + tout / 1e6 * price[1]


def summarize(results, level):
    total = len(results)
    ok = sum(r["ok"] for r in results)
    by_group = collections.defaultdict(lambda: [0, 0])
    by_want = collections.defaultdict(lambda: [0, 0])
    confusions = collections.Counter()
    for r in results:
        by_group[r["case"]["group"]][1] += 1
        by_group[r["case"]["group"]][0] += r["ok"]
        key = r["want"][0] if level == "skill" else expected_key(r)
        by_want[key][1] += 1
        by_want[key][0] += r["ok"]
        if not r["ok"]:
            confusions[(key, r["got"])] += 1
    return {"total": total, "correct": ok, "by_group": dict(by_group), "by_want": dict(by_want),
            "confusions": confusions}


def expected_key(r):
    return r["want"][0] if r["want"] else r["case"]["intent"]


def format_report(results, level, model, router, tin, tout):
    s = summarize(results, level)
    cost = estimate_cost(model, tin, tout)
    lines = [f"# Routing check — level={level}, model={model}",
             f"router: {router}",
             f"accuracy: {s['correct']}/{s['total']} ({100 * s['correct'] / max(1, s['total']):.1f}%)"
             f"   tokens in/out: {tin}/{tout}" + (f"   cost ≈ ${cost:.3f}" if cost is not None else ""),
             "", "## By group", "| group | correct | n |", "|---|---|---|"]
    for g, (c, n) in sorted(s["by_group"].items()):
        lines.append(f"| {g} | {c} | {n} |")
    lines += ["", "## By expected " + ("skill" if level == "skill" else "intent"),
              "| expected | correct | n |", "|---|---|---|"]
    for k, (c, n) in sorted(s["by_want"].items()):
        lines.append(f"| {k} | {c} | {n} |")
    errors = [r for r in results if r["got"] == "ERROR"]
    if errors:
        lines += ["", f"## Model call errors ({len(errors)} of {len(results)}) — first: {errors[0]['raw']}"]
    wrong = [r for r in results if not r["ok"]]
    if wrong:
        lines += ["", f"## Wrong answers ({len(wrong)})"]
        for r in wrong:
            lines.append(f"- {r['case']['id']}: expected {' | '.join(r['want'])}, got {r['got']}"
                         f" — \"{r['case']['prompt'][:110]}\"")
        lines += ["", "## Confusions (expected → got)"]
        for (want, got), n in s["confusions"].most_common():
            lines.append(f"- {want} → {got}: {n}")
    return "\n".join(lines)


# --- command line --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--level", choices=["intent", "skill"], default="intent")
    ap.add_argument("--cases", default=str(HERE / "cases.jsonl"))
    ap.add_argument("--groups", default=str(HERE / "groups.json"))
    ap.add_argument("--router", default=str(DEFAULT_ROUTER), help="router SKILL.md to score")
    ap.add_argument("--skills-dir", default=str(SKILLS_DIR))
    ap.add_argument("--model", default="claude-haiku-4-5")
    ap.add_argument("--base-url", default="https://api.anthropic.com")
    ap.add_argument("--key-env", default="ANTHROPIC_API_KEY")
    ap.add_argument("--only-group", help="score only cases of this group")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", help="write the full results as JSON")
    ap.add_argument("--check", action="store_true", help="validate the cases and exit")
    ap.add_argument("--dry-run", action="store_true", help="show a prompt and the cost estimate; no calls")
    ap.add_argument("--fail-below", type=float, help="exit 1 if accuracy (0-1) is lower")
    args = ap.parse_args(argv)

    router_text = Path(args.router).read_text(encoding="utf-8")
    cases = load_cases(args.cases)
    groups = json.loads(Path(args.groups).read_text(encoding="utf-8"))
    errors, warnings = check_dataset(cases, router_text, groups)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    if errors:
        for e in errors:
            print("error:", e, file=sys.stderr)
        return 2
    if args.check:
        print(f"ok: {len(cases)} cases, {len(router_ids(router_text))} router intents, "
              f"{len(warnings)} warning(s)")
        return 0

    if args.only_group:
        cases = [c for c in cases if c["group"] == args.only_group]
    if args.limit:
        cases = cases[:args.limit]
    descriptions = skill_descriptions(args.skills_dir)

    sizes = [sum(map(len, build_request(args.level, c, router_text, descriptions))) // 4 for c in cases]
    est_in, est_out = sum(sizes), 12 * len(cases)
    est = estimate_cost(args.model, est_in, est_out)
    if args.dry_run:
        system, user = build_request(args.level, cases[0], router_text, descriptions)
        print(f"{len(cases)} calls, ~{est_in} input tokens, ~{est_out} output tokens"
              + (f", ≈ ${est:.3f} with {args.model}" if est is not None else ""))
        print("\n--- system (first 600 chars) ---\n" + system[:600] + "\n...\n--- user ---\n" + user)
        return 0

    key = os.environ.get(args.key_env)
    if not key:
        print(f"error: set {args.key_env} (or --key-env) to the API key", file=sys.stderr)
        return 2
    print(f"running {len(cases)} calls with {args.model} (≈ ${est:.3f})..." if est is not None
          else f"running {len(cases)} calls with {args.model}...", file=sys.stderr)

    def call(system, user):
        return call_model(args.base_url, key, args.model, system, user)

    results = run_cases(cases, args.level, router_text, descriptions, groups, call, args.concurrency)
    tin, tout = sum(r["tin"] for r in results), sum(r["tout"] for r in results)
    print(format_report(results, args.level, args.model, args.router, tin, tout))
    if args.out:
        Path(args.out).write_text(json.dumps(
            [{"id": r["case"]["id"], "expected": r.get("want"), "got": r["got"], "ok": r["ok"],
              "raw": r["raw"]} for r in results], indent=2), encoding="utf-8")
    if any(r["got"] == "ERROR" for r in results):
        return 3          # the numbers above are not a measurement: say so in the exit code
    acc = sum(r["ok"] for r in results) / max(1, len(results))
    return 1 if args.fail_below is not None and acc < args.fail_below else 0


if __name__ == "__main__":
    sys.exit(main())
