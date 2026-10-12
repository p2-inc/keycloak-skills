# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the SkillsBench router arm: synthetic runs in bench's file format and a
stub in place of `bench`, so nothing is spent and no Docker is needed.

    python3 -m unittest discover -s evals/routing -v
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_arm as ba  # noqa: E402
import route_check as rc  # noqa: E402

ROUTES = ba.load_routes()
ROUTER_IDS = rc.router_ids(rc.DEFAULT_ROUTER.read_text(encoding="utf-8"))


def trajectory_line(*calls):
    """One llm_trajectory.jsonl record whose response makes the given (tool, args) calls."""
    return json.dumps({"request": {"body": {"messages": []}}, "response": {"body": {"choices": [{
        "message": {"role": "assistant", "tool_calls": [
            {"function": {"name": n, "arguments": json.dumps(a)}} for n, a in calls]}}]}}})


def write_run(jobs, lines, reward=1.0, cost=0.5, calls=12, name="task__abc"):
    run = Path(jobs) / "2026-10-12__10-00-00" / name
    (run / "trajectory").mkdir(parents=True)
    (run / "result.json").write_text(json.dumps({
        "rewards": {"reward": reward}, "error": None,
        "agent_result": {"cost_usd": cost, "n_tool_calls": calls}}))
    (run / "trajectory" / "llm_trajectory.jsonl").write_text("\n".join(lines) + "\n")
    (Path(jobs) / "2026-10-12__10-00-00" / "summary.json").write_text(json.dumps({"total": 1}))
    return run


class Scenarios(unittest.TestCase):
    def test_every_scenario_is_runnable(self):
        self.assertGreaterEqual(len(ROUTES), 17)
        for task, expected in ROUTES.items():
            self.assertTrue((ba.BENCH_DIR / task).is_dir(), f"{task}: no such benchmark")
            self.assertTrue(ba.intent_skill_dirs(ba.BENCH_DIR / task), f"{task}: no control-arm skill")
            if expected.startswith("skill:"):
                self.assertIn(expected.split(":", 1)[1], ba.ROUTER_SKILLS)
            else:
                self.assertIn(expected, ROUTER_IDS, f"{task}: {expected} is not a router intent")
                ref = ba.SKILLS_DIR / "keycloak" / "references" / ("admin-" + expected.split(":", 1)[1] + ".md")
                self.assertTrue(ref.is_file(), f"{task}: missing {ref.name}")

    def test_every_router_intent_with_a_benchmark_is_covered_once(self):
        mapped = [e for e in ROUTES.values() if e.startswith("admin:")]
        self.assertEqual(len(mapped), len(set(mapped)))

    def test_stem_to_intent(self):
        self.assertEqual(ba.stem_to_intent("admin-totp-second-factor"), "admin:totp-second-factor")
        self.assertEqual(ba.stem_to_intent("admin-idp-org-restrict-login"), "admin:idp-org-restrict-login")


class SkillsDirs(unittest.TestCase):
    def test_router_arm_deploys_the_whole_live_skills(self):
        with tempfile.TemporaryDirectory() as d:
            names = ba.build_skills_dir("router", ba.BENCH_DIR / "keycloak-totp-second-factor", d)
            self.assertEqual(names, ["keycloak", "securing-apps"])
            for rel in ("keycloak/SKILL.md", "keycloak/references/admin-totp-second-factor.md",
                        "keycloak/references/flow-execution-order.md", "securing-apps/SKILL.md"):
                self.assertTrue((Path(d) / rel).is_file(), rel)
            self.assertEqual(list(Path(d).rglob("__pycache__")), [])

    def test_intent_arm_is_the_tasks_rest_skill_only(self):
        with tempfile.TemporaryDirectory() as d:
            names = ba.build_skills_dir("intent", ba.BENCH_DIR / "keycloak-totp-second-factor", d)
            self.assertEqual(names, ["totpSecondFactorRest"])
        with tempfile.TemporaryDirectory() as d:     # no `Rest` suffix: every non-Mcp dir
            names = ba.build_skills_dir("intent", ba.BENCH_DIR / "keycloak-magic-link-login", d)
            self.assertEqual(names, ["passwordlessMagicLinkLogin"])

    def test_the_bench_command(self):
        argv = ba.bench_argv("benchmarks/t", "/jobs", "/skills", "m-1", "agent-x")
        self.assertEqual(argv[:3], ["bench", "eval", "run"])
        for flag, value in (("--tasks-dir", "benchmarks/t"), ("--agent", "agent-x"), ("--model", "m-1"),
                            ("--skill-mode", "with-skill"), ("--skills-dir", "/skills"),
                            ("--sandbox", "docker"), ("--jobs-dir", "/jobs")):
            self.assertEqual(argv[argv.index(flag) + 1], value)


class Reading(unittest.TestCase):
    def test_the_first_intent_reference_is_the_route_and_mcp_twins_collapse(self):
        with tempfile.TemporaryDirectory() as d:
            traj = Path(d) / "t.jsonl"
            traj.write_text("\n".join([
                trajectory_line(("Skill", {"skill": "keycloak"})),
                trajectory_line(("Read", {"file_path": "/skills/keycloak/references/flow-execution-order.md"})),
                trajectory_line(("Read", {"file_path": "/skills/keycloak/references/admin-totp-second-factor.md"}),
                                ("Bash", {"command": "cat /skills/keycloak/references/admin-totp-second-factor-mcp.md"})),
                trajectory_line(("Read", {"file_path": "/skills/keycloak/references/admin-email-otp-login.md"})),
                "not json",
            ]))
            a = ba.analyze_trajectory(traj)
        self.assertEqual(a["skills"], ["keycloak"])
        self.assertEqual(a["intent_refs"], ["admin:totp-second-factor", "admin:email-otp-login"])
        self.assertEqual(a["tool_calls"], 5)
        v = ba.judge("admin:totp-second-factor", a)
        self.assertEqual((v["route"], v["route_ok"], v["also_read"]),
                         ("admin:totp-second-factor", True, ["admin:email-otp-login"]))
        self.assertFalse(ba.judge("admin:email-otp-login", a)["route_ok"])      # read, but not first

    def test_skill_level_and_no_route_verdicts(self):
        a = {"skills": ["keycloak", "securing-apps"], "intent_refs": [], "tool_calls": 3}
        self.assertEqual(ba.judge("skill:securing-apps", a), {"route": "keycloak", "route_ok": False})
        self.assertTrue(ba.judge("skill:keycloak", a)["route_ok"])
        none = {"skills": [], "intent_refs": [], "tool_calls": 2}
        self.assertEqual(ba.judge("admin:totp-second-factor", none)["route"], None)
        self.assertFalse(ba.judge("admin:totp-second-factor", none)["route_ok"])

    def test_a_run_is_scored_from_its_files_and_summary_json_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            write_run(d, [trajectory_line(("Skill", {"skill": "keycloak"})),
                          trajectory_line(("Read", {"file_path": "/s/keycloak/references/admin-totp-second-factor.md"}))],
                      reward=1.0, cost=0.42, calls=19)
            row = ba.score_run("keycloak-totp-second-factor", "router", "admin:totp-second-factor", d)
        self.assertEqual((row["reward"], row["cost"], row["tool_calls"], row["route_ok"]), (1.0, 0.42, 19, True))
        self.assertEqual(row["skills"], ["keycloak"])
        with tempfile.TemporaryDirectory() as empty:
            self.assertIn("no result.json", ba.score_run("t", "router", "admin:x", empty)["error"])

    def test_the_report_pairs_arms_and_lists_misroutes(self):
        rows = [
            {"task": "t1", "arm": "router", "expected": "admin:a", "reward": 0.0, "route": "admin:b",
             "route_ok": False, "also_read": ["admin:a"], "tool_calls": 40, "cost": 1.1},
            {"task": "t1", "arm": "intent", "expected": "admin:a", "reward": 1.0, "route": None,
             "route_ok": None, "tool_calls": 22, "cost": 0.5},
        ]
        report = ba.format_report(rows)
        self.assertIn("| t1 | router | 0.0 | admin:b | admin:a | NO | 40 | $1.10 |", report)
        self.assertIn("| t1 | 0.0 / 1.0 | 40 / 22 | $1.10 / $0.50 |", report)
        self.assertIn("- t1: expected admin:a, first route admin:b, also read admin:a", report)


class Cli(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = ba.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_list(self):
        code, out, _ = self.run_main("--list")
        self.assertEqual(code, 0)
        self.assertIn("keycloak-totp-second-factor", out)
        self.assertIn("admin:totp-second-factor", out)

    def test_dry_run_builds_the_skills_and_never_calls_bench(self):
        with mock.patch.object(ba.subprocess, "run", side_effect=AssertionError("must not run")):
            code, out, err = self.run_main("--task", "keycloak-totp-second-factor", "--arm", "both", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("bench eval run"), 2)
        self.assertIn("skills: keycloak, securing-apps", err)
        self.assertIn("skills: totpSecondFactorRest", err)

    def test_an_unknown_task_is_refused(self):
        code, _, err = self.run_main("--task", "no-such-task")
        self.assertEqual(code, 2)
        self.assertIn("not in bench_routes.json", err)

    def test_a_stubbed_bench_run_is_scored_end_to_end(self):
        def fake_bench(argv, **kwargs):
            jobs = Path(argv[argv.index("--jobs-dir") + 1])
            write_run(jobs, [trajectory_line(("Skill", {"skill": "keycloak"})),
                             trajectory_line(("Read", {"file_path": "/s/keycloak/references/admin-totp-second-factor.md"}))])
            self.assertEqual(kwargs["env"]["AWS_REGION"], "us-east-1")
            return mock.Mock(returncode=0)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(ba.shutil, "which", return_value="/bin/bench"), \
                mock.patch.object(ba.subprocess, "run", side_effect=fake_bench):
            code, out, _ = self.run_main("--task", "keycloak-totp-second-factor", "--work-dir", d,
                                         "--out", str(Path(d) / "rows.json"))
            rows = json.loads((Path(d) / "rows.json").read_text())
        self.assertEqual(code, 0)
        self.assertEqual((rows[0]["arm"], rows[0]["route_ok"], rows[0]["reward"]), ("router", True, 1.0))
        self.assertIn("| keycloak-totp-second-factor | router | 1.0 | admin:totp-second-factor |", out)


if __name__ == "__main__":
    unittest.main()
