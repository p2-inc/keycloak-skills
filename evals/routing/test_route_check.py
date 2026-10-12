# Copyright 2026 Phase Two, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the routing check: no model, no network beyond a local stub server.

    python3 -m unittest discover -s evals/routing -v
"""

import contextlib
import http.server
import io
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import route_check as rc  # noqa: E402

ROUTER = rc.DEFAULT_ROUTER.read_text(encoding="utf-8")
GROUPS = json.loads((rc.HERE / "groups.json").read_text(encoding="utf-8"))
CASES = rc.load_cases(rc.HERE / "cases.jsonl")
IDS = rc.router_ids(ROUTER)


class Dataset(unittest.TestCase):
    def test_cases_are_valid_for_the_current_router(self):
        errors, _ = rc.check_dataset(CASES, ROUTER, GROUPS)
        self.assertEqual(errors, [])

    def test_the_router_table_is_parsed(self):
        self.assertGreaterEqual(len(IDS), 17)
        self.assertEqual(len(IDS), len(set(IDS)))
        for intent in ("admin:cluster-setup", "admin:totp-second-factor", "admin:idp-federation"):
            self.assertIn(intent, IDS)

    def test_a_new_intent_without_cases_is_an_error(self):
        router = ROUTER + "\n| Something new — \"do the new thing\". | **admin:brand-new** |\n"
        errors, _ = rc.check_dataset(CASES, router, GROUPS)
        self.assertTrue(any("admin:brand-new" in e and "add at least" in e for e in errors), errors)

    def test_unknown_intent_group_and_duplicates_are_errors(self):
        bad = [
            {"id": "x-1", "prompt": "a", "intent": "admin:nope", "group": "auth-flows"},
            {"id": "x-1", "prompt": "a", "intent": "NONE", "group": "nowhere"},
        ]
        errors, _ = rc.check_dataset(CASES + bad, ROUTER, GROUPS)
        joined = "\n".join(errors)
        self.assertIn("admin:nope", joined)
        self.assertIn("duplicate case id x-1", joined)
        self.assertIn("'nowhere' is not in groups.json", joined)

    def test_a_prompt_that_repeats_a_trigger_phrase_is_a_warning(self):
        trigger = rc.router_triggers(ROUTER)[0]
        leaky = {"id": "leak-1", "prompt": f"please {trigger} now", "intent": "NONE", "group": "none"}
        errors, warnings = rc.check_dataset(CASES + [leaky], ROUTER, GROUPS)
        self.assertEqual(errors, [])
        self.assertTrue(any("leak-1" in w for w in warnings))

    def test_every_group_in_the_cases_maps_to_a_skill_or_none(self):
        for c in CASES:
            self.assertIn(c["group"], GROUPS)
        self.assertIn(rc.expected_skill({"group": "securing-apps"}, GROUPS), ("securing-apps",))
        self.assertEqual(rc.expected_skill({"group": "none"}, GROUPS), "NONE")


class Expectations(unittest.TestCase):
    def test_a_planned_intent_is_none_until_the_router_has_it(self):
        case = {"id": "p", "intent": "admin:future", "group": "auth-flows", "planned": True}
        self.assertEqual(rc.expected_intent(case, IDS), "NONE")
        self.assertEqual(rc.expected_intent(case, IDS + ["admin:future"]), "admin:future")
        with self.assertRaises(ValueError):
            rc.expected_intent({**case, "planned": False}, IDS)

    def test_accept_widens_the_correct_answers(self):
        case = {"id": "a", "intent": "admin:credential-enrollment", "group": "realm-admin",
                "accept": ["admin:totp-second-factor"]}
        self.assertEqual(rc.accepted_intents(case, IDS),
                         {"admin:credential-enrollment", "admin:totp-second-factor"})

    def test_answers_are_parsed(self):
        self.assertEqual(rc.parse_answer("intent", "ROUTE: admin:cluster-setup"), "admin:cluster-setup")
        self.assertEqual(rc.parse_answer("intent", "Sure.\nroute: none"), "NONE")
        self.assertEqual(rc.parse_answer("intent", "ROUTE: DENY because"), "DENY")
        self.assertEqual(rc.parse_answer("intent", "I think cluster-setup"), "UNPARSEABLE")
        self.assertEqual(rc.parse_answer("skill", "SKILL: keycloak"), "keycloak")
        self.assertEqual(rc.parse_answer("skill", "skill: none"), "NONE")


class Frontmatter(unittest.TestCase):
    def test_every_skill_description_is_read_and_within_the_limit(self):
        descriptions = rc.skill_descriptions()
        self.assertIn("keycloak", descriptions)
        self.assertIn("securing-apps", descriptions)
        for name, desc in descriptions.items():
            self.assertTrue(0 < len(desc) <= 1024, (name, len(desc)))

    def test_folded_and_plain_values(self):
        fm = rc.parse_frontmatter("---\nname: x\ndescription: >-\n  one\n  two\nlicense: MIT\n---\nbody")
        self.assertEqual(fm, {"name": "x", "description": "one two", "license": "MIT"})


class Scoring(unittest.TestCase):
    def setUp(self):
        self.cases = [
            {"id": "c1", "prompt": "make a cluster", "intent": "admin:cluster-setup", "group": "realm-admin"},
            {"id": "c2", "prompt": "delete the realm", "intent": "DENY", "group": "deny"},
            {"id": "c3", "prompt": "react login", "intent": "NONE", "group": "securing-apps"},
        ]

    def test_intent_level_scoring_and_confusions(self):
        answers = {"make a cluster": "ROUTE: admin:cluster-create-deployment",
                   "delete the realm": "ROUTE: DENY", "react login": "ROUTE: NONE"}
        results = rc.run_cases(self.cases, "intent", ROUTER, {}, GROUPS,
                               lambda system, user: (answers[user], 10, 3), concurrency=2)
        self.assertEqual([r["ok"] for r in results], [False, True, True])
        s = rc.summarize(results, "intent")
        self.assertEqual((s["correct"], s["total"]), (2, 3))
        self.assertEqual(s["confusions"][("admin:cluster-setup", "admin:cluster-create-deployment")], 1)
        report = rc.format_report(results, "intent", "claude-haiku-4-5", "r.md", 30, 9)
        self.assertIn("accuracy: 2/3 (66.7%)", report)
        self.assertIn("admin:cluster-setup → admin:cluster-create-deployment: 1", report)

    def test_skill_level_scoring_uses_the_group_map(self):
        answers = {"make a cluster": "SKILL: keycloak", "delete the realm": "SKILL: keycloak",
                   "react login": "SKILL: keycloak"}
        results = rc.run_cases(self.cases, "skill", ROUTER, {"keycloak": "d", "securing-apps": "e"},
                               GROUPS, lambda system, user: (answers[user], 5, 2))
        self.assertEqual([r["ok"] for r in results], [True, True, False])   # react login is securing-apps

    def test_a_model_error_is_a_wrong_answer_not_a_crash(self):
        def boom(system, user):
            raise RuntimeError("HTTP 500")
        results = rc.run_cases(self.cases[:1], "intent", ROUTER, {}, GROUPS, boom)
        self.assertEqual((results[0]["got"], results[0]["ok"]), ("ERROR", False))

    def test_the_prompts_carry_the_skill_or_the_descriptions(self):
        system, user = rc.build_request("intent", self.cases[0], ROUTER, {})
        self.assertIn("Step 1: Detect intent", system)
        self.assertEqual(user, "make a cluster")
        system, _ = rc.build_request("skill", self.cases[0], ROUTER, {"keycloak": "Use for Keycloak."})
        self.assertIn("- keycloak: Use for Keycloak.", system)


class Http(unittest.TestCase):
    def test_request_shape_and_retry(self):
        seen, replies = [], [(429, {"error": "slow down"}),
                             (200, {"content": [{"type": "text", "text": "ROUTE: NONE"}],
                                    "usage": {"input_tokens": 11, "output_tokens": 4}})]

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["content-length"])
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()},   # names are case-insensitive
                             json.loads(self.rfile.read(length))))
                status, payload = replies.pop(0)
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            text, tin, tout = rc.call_model(f"http://127.0.0.1:{server.server_port}/", "k-123", "m-1",
                                            "the system", "the user", sleep=lambda s: None)
        finally:
            server.shutdown()
        self.assertEqual((text, tin, tout), ("ROUTE: NONE", 11, 4))
        self.assertEqual(len(seen), 2)                                   # 429, then success
        path, headers, body = seen[1]
        self.assertEqual(path, "/v1/messages")
        self.assertEqual(headers["x-api-key"], "k-123")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual((body["model"], body["system"], body["temperature"]), ("m-1", "the system", 0))
        self.assertEqual(body["messages"], [{"role": "user", "content": "the user"}])


class Cli(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_and_dry_run_cost_nothing(self):
        code, out, _ = self.run_main("--check")
        self.assertEqual(code, 0)
        self.assertIn("router intents", out)
        code, out, _ = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("calls, ~", out)
        code, out, _ = self.run_main("--dry-run", "--level", "skill", "--limit", "5")
        self.assertIn("5 calls", out)

    def test_a_missing_key_is_reported_not_guessed(self):
        code, _, err = self.run_main("--level", "skill", "--key-env", "NO_SUCH_KEY_VARIABLE_XYZ")
        self.assertEqual(code, 2)
        self.assertIn("NO_SUCH_KEY_VARIABLE_XYZ", err)


if __name__ == "__main__":
    unittest.main()
