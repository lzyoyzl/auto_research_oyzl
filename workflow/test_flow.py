"""Offline research-control fixtures. No test output represents a research finding."""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from approvals import budget_path, estimate, excess, pending_text, process_env, proposal_path, totals
from driver import artifacts, drive
from study import advance, check, new, read, record_reply, save, snapshot


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class FlowTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for i in range(3):
            (root / f"P{i}.html").write_text("<article><h2>Methods</h2><p>" +
                (f"Fixture method in document {i} has a deliberately testable assumption. " * 15) + "</p></article>")
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{server.server_port}/"
        self.run_dir = new("controller integration fixture", root / "fixture", rounds=3, seconds=5)
        self.calls = []

    def worker(self, exe, run, s, feedback):
        phase, number = s["phase"], s["round"]
        self.calls.append(phase)
        files = [run / p for p in artifacts(s)]
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
        if phase == "discover":
            save(files[0], {"queries": ["fixture"], "sources": [
                {"id": f"P{i}", "title": f"Fixture {i}", "url": self.url + f"P{i}.html"} for i in range(3)]})
        elif phase == "read":
            save(files[0], {"searches": ["fixture"], "papers": [
                {"id": f"P{i}", "title": f"Fixture {i}", "section": "Methods",
                 "method": "fixture", "data": "fixture", "comparison": "fixture",
                 "excerpt": f"Fixture method in document {i}", "finding": "fixture", "limitation": "fixture"}
                for i in range(3)]})
        elif phase == "ideas":
            save(files[0], {"reason": "low-cost test", "venue": "acl", "venue_reason": "fixture",
                            "ideas": [{"id": f"I{i}", "title": f"Option {i}", "mechanism": f"mechanism-{i}",
                            "novelty_assessment": f"prior art check {i}", "introduction": f"question {i}",
                            "background": f"technical context {i}", "motivation": f"reason to test {i}",
                            "evidence_gap": f"untested premise {i}", "prediction": f"conditional effect {i}",
                            "technical_neighbor": {"url": self.url + "P0.html", "section": "Methods",
                                "excerpt": "Fixture method in document 0", "transfer_baseline": f"direct transfer {i}"},
                            "technical_obstacle": f"technical obstacle {i}", "cost_boundary": f"cost and scope {i}",
                            "competing_explanation": f"matched control {i}",
                            "closest_difference": "fixture", "sources": ["P0"], "pilot": "paired",
                            "falsifier": "zero gain"} for i in range(3)]})
        elif phase == "pilot":
            save(files[0], {"idea_id": s["idea"], "workload": "two fixture samples"})
            files[1].write_text("import os\nassert not os.environ['CUDA_VISIBLE_DEVICES']\nprint('{\"n\":2}')")
        elif phase == "budget":
            save(files[0], {"idea_id":s["idea"], "pilot_ref":s["pilot_ref"], "estimate_basis":"pilot x 3",
                            "pricing_basis":"owned CPU", "currency":"CNY", "hourly_rate":0,
                            "gpu_model":"CPU", "cards":0, "vram_gib_per_card":0, "wall_hours":0.02})
        elif phase == "plan":
            save(files[0], {"idea_id": s["idea"], "hypothesis": "fixture", "dataset": "local fixture",
                            "change": f"trial {number}", "metric": "paired score", "higher_is_better": True,
                            "min_gain": 0.1, "dev_split": "A", "confirm_split": "B",
                            "compute":{"gpu_model":"CPU","cards":0,"vram_gib_per_card":0,"seconds":2,
                                       "currency":"CNY","hourly_rate":0}})
            if number == 1:
                files[1].write_text("raise ValueError('deliberate fixture error')\n")
            else:
                files[1].write_text("import json, sys\nfrom pathlib import Path\n"
                    "mode=sys.argv[-1]\nbase=[0, 1] if mode=='dev' else [0, 0]\n"
                    + ("pred=base\n" if number == 2 else "pred=[1, 1]\n")
                    + "rows=[dict(unit=str(i),baseline=b,candidate=c) for i,(b,c) in enumerate(zip(base,pred))]\n"
                    "Path(mode+'-scores.json').write_text(json.dumps(rows))\n"
                    "print(json.dumps(dict(baseline=sum(base)/2,candidate=sum(pred)/2,n=len(base))))\n")
        elif phase == "decide":
            result = read(files[0].parent / "dev.json")
            action = {"execution_error":"refine", "not_met":"pivot", "met":"confirm"}[result["outcome"]]
            ident = "I1" if action == "pivot" else s["idea"]
            save(files[0], dict(action=action, idea_id=ident, diagnosis=result["outcome"], next_test="fixture"))
        elif phase == "write":
            claim = "The paired fixture executed successfully."
            text = "# Workflow test manuscript\n" + claim + "\n" + (
                   "This generated document is exclusively a test of the research controller. " * 4)
            files[0].write_text(text + self.url + "P0.html")
            save(files[1], [{"claim": claim, "evidence":["rounds/03/confirm.json"]}])
        elif phase == "review":
            if s["version"] == 1:
                save(files[0], dict(verdict="revise", checks=["evidence"], issues=["clarify scope"]))
            else:
                save(files[0], dict(verdict="ready", checks=["evidence"], issues=[]))
        elif phase == "typeset":
            files[0].write_text(r"""\documentclass{article}
\usepackage[review]{acl}
\title{Controller Fixture}
\author{Anonymous}
\begin{document}\maketitle
This fixture exercises compilation and citation \citep{local}.
The paired fixture executed successfully.
\bibliography{references}
\end{document}
""")
            files[1].write_text("@article{local,title={Test Fixture},author={Fixture, Local},"
                                "year={2000},journal={Workflow Fixture}}\n")

    def run_to_pause(self):
        drive(self.run_dir, self.worker, lambda: "fixture")
        return snapshot(self.run_dir)

    def reply(self, action, value=None):
        pending = snapshot(self.run_dir)["pending"]
        return record_reply(self.run_dir, pending["id"], action, value)

    def through_budget(self):
        self.assertEqual(self.run_to_pause()["phase"], "idea_review")
        self.reply("choose", "I0")
        self.assertEqual(self.run_to_pause()["phase"], "budget_review")
        self.reply("approve-budget")

    def test_loop_and_restart(self):
        self.through_budget()
        pivot = self.run_to_pause()
        self.assertEqual(pivot["phase"], "idea_review")
        self.assertEqual(pivot["pending"]["recommended"], "I1")
        self.assertEqual(pivot["idea"], "I0")
        self.assertFalse((self.run_dir / "rounds/03/dev.json").exists())
        self.reply("choose", "I1")
        # Lower the follow-up estimate so it fits the remaining approved allowance.
        def followup(exe, run, s, feedback):
            self.worker(exe, run, s, feedback)
            if s["phase"] == "budget":
                path = run / budget_path(s)
                obj = read(path)
                obj["wall_hours"] /= 2
                save(path, obj)
        drive(self.run_dir, followup, lambda: "fixture")
        s = read(self.run_dir / "state.json")
        self.assertEqual(s["phase"], "done")
        self.assertEqual(s["idea"], "I1")
        self.assertEqual(s["version"], 2)
        self.assertEqual(read(self.run_dir / "rounds/01/dev.json")["outcome"], "execution_error")
        self.assertEqual(read(self.run_dir / "rounds/02/dev.json")["outcome"], "not_met")
        self.assertEqual(read(self.run_dir / "rounds/03/confirm.json")["outcome"], "met")
        self.assertTrue((self.run_dir / "paper.pdf").read_bytes().startswith(b"%PDF"))
        drive(self.run_dir, lambda *_: self.fail("finished run called worker"), lambda: "fixture")
        (self.run_dir / "rounds/03/dev-scores.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "Frozen evidence changed"):
            check(self.run_dir, s)

    def test_no_paper_on_all_errors(self):
        path = self.run_dir / "state.json"
        s = read(path)
        s["max_rounds"] = 1
        save(path, s)
        self.through_budget()
        with self.assertRaisesRegex(RuntimeError, "未获得有效测量"):
            drive(self.run_dir, self.worker, lambda: "fixture")
        self.assertFalse((self.run_dir / "paper.md").exists())

    def test_repropose_and_choose_runner_up(self):
        run = self.run_dir
        first = self.run_to_pause()
        gate = first["pending"]["id"]
        self.assertIn("Option 2", pending_text(run, first))
        self.assertIn("low-cost test", (run / "reviews" / (gate + ".md")).read_text())
        self.assertEqual(advance(run), "idea_review")
        drive(run, lambda *_: self.fail("worker called at human gate"), lambda: self.fail("resolved backend"))
        self.assertFalse((run / "pilots").exists())
        with self.assertRaises(ValueError):
            self.reply("choose", "absent")
        self.reply("repropose", "prefer less annotation")
        s = snapshot(run)
        self.worker("", run, s, "")
        path = run / proposal_path(s)
        with self.assertRaisesRegex(ValueError, "rejected mechanism"):
            advance(run)
        obj = read(path)
        for idea in obj["ideas"]:
            idea["mechanism"] += " with weak supervision"
        save(path, obj)
        self.assertEqual(advance(run), "idea_review")
        with self.assertRaisesRegex(ValueError, "matching pending"):
            record_reply(run, gate, "choose", "I0")
        self.reply("choose", "I2")
        budget = self.run_to_pause()
        self.assertEqual(budget["idea"], "I2")
        self.assertIsNone(budget["grant"])
        self.assertFalse((run / "rounds").exists())
        self.assertEqual(advance(run), "budget_review")
        drive(run, lambda *_: self.fail("worker called at budget review"), lambda: "")
        first_budget = budget["pending"]["id"]
        self.reply("revise-budget", "reduce the run count")
        budget = self.run_to_pause()
        self.assertNotEqual(budget["pending"]["id"], first_budget)
        with self.assertRaises(ValueError):
            record_reply(run, first_budget, "approve-budget")
        self.assertTrue((run / budget["pilot_ref"]).exists())
        self.assertFalse((run / "rounds").exists())

    def test_each_idea_requires_and_displays_review_sections(self):
        run = self.run_dir
        for phase in ("discover", "read", "ideas"):
            s = snapshot(run)
            self.assertEqual(s["phase"], phase)
            self.worker("", run, s, "")
            if phase != "ideas":
                advance(run)
        path = run / proposal_path(s)
        obj = read(path)
        for key in ("novelty_assessment", "introduction", "background", "motivation",
                    "evidence_gap", "prediction", "competing_explanation", "technical_obstacle", "cost_boundary"):
            with self.subTest(key=key):
                original = obj["ideas"][-1][key]
                obj["ideas"][-1][key] = " "
                save(path, obj)
                with self.assertRaisesRegex(ValueError, key):
                    advance(run)
                self.assertEqual(snapshot(run)["phase"], "ideas")
                obj["ideas"][-1][key] = original
        neighbor = obj["ideas"][-1]["technical_neighbor"]
        for key in ("url", "section", "excerpt", "transfer_baseline"):
            with self.subTest(neighbor_key=key):
                value = neighbor.pop(key)
                save(path, obj)
                with self.assertRaisesRegex(ValueError, key):
                    advance(run)
                neighbor[key] = value
        # A method found during ideation need not have been in the sealed reading list.
        (run.parent / "late.html").write_text("<p>" + "New technical comparison in section 4. " * 20 + "</p>")
        neighbor.update(url=self.url + "late.html", section="§4", excerpt="invented source quotation")
        save(path, obj)
        with self.assertRaisesRegex(ValueError, "Unmatched excerpt"):
            advance(run)
        self.assertEqual(snapshot(run)["phase"], "ideas")
        neighbor["excerpt"] = "New technical comparison in section 4."
        save(path, obj)
        self.assertEqual(advance(run), "idea_review")
        s = snapshot(run)
        rendered = pending_text(run, s)
        self.assertTrue(any(p.startswith("sources/N") and p.endswith("/text.txt") for p in s["sealed"]))
        self.assertEqual((run / "reviews" / (s["pending"]["id"] + ".md")).read_text(), rendered + "\n")
        for section, idea in zip(rendered.split("\n## ")[1:], obj["ideas"], strict=True):
            for key, label in (("novelty_assessment", "查新判断"), ("introduction", "Introduction"),
                               ("background", "Background"), ("motivation", "Motivation"),
                               ("evidence_gap", "已知证据与待验证前提"), ("prediction", "机制产生的可区分预测"),
                               ("technical_obstacle", "技术难点"), ("cost_boundary", "代价与适用边界"),
                               ("competing_explanation", "竞争解释与对照")):
                self.assertIn(f"**{label}**　{idea[key]}", section)
            ref = idea["technical_neighbor"]
            self.assertIn(ref["transfer_baseline"], section)
            self.assertIn(f"[原文章节 · {ref['section']}]({ref['url']})", section)
        previous = s["pending"]["id"]
        self.reply("revise-brief", "test the alternative explanation")
        revised = self.run_to_pause()
        self.assertEqual(revised["phase"], "idea_review")
        self.assertIsNone(revised["idea"])
        self.assertNotEqual(revised["pending"]["id"], previous)
        self.assertTrue((run / proposal_path(revised)).is_file())
        self.assertEqual((run / "reviews" / (previous + ".md")).read_text(), rendered + "\n")

    def test_financial_request_and_overrun_before_launch(self):
        run = self.run_dir
        self.run_to_pause()
        self.reply("choose", "I0")
        s = snapshot(run)
        self.worker("", run, s, "")
        advance(run)
        s = snapshot(run)
        self.worker("", run, s, "")
        path = run / budget_path(s)
        req = read(path)
        req.update(wall_hours=1 / 3600)
        save(path, req)
        advance(run)
        self.reply("approve-budget")
        s = snapshot(run)
        self.worker("", run, s, "")
        with patch("study.execute", side_effect=AssertionError("over-budget job started")):
            self.assertEqual(advance(run), "budget")
        self.assertFalse((run / "rounds/01/dev.log").exists())
        self.assertEqual(s["grant"]["limits"]["gpu_hours"], 0)
        s = snapshot(run)
        self.worker("", run, s, "")
        advance(run)
        self.reply("approve-budget")
        self.assertEqual(advance(run), "decide")
        grant = snapshot(run)["grant"]
        spent = totals(run, grant["id"])
        self.assertGreater(spent["wall_hours"], 0)  # failed experiments count, too
        shape = estimate(dict(req, gpu_model="example GPU", cards=2, vram_gib_per_card=24,
                              wall_hours=3, hourly_rate=4))
        self.assertEqual((shape["gpu_hours"], shape["cost"]), (6, 24))
        self.assertTrue(excess(run, grant, shape))
        self.assertTrue(excess(run, grant, dict(grant["limits"])))  # used + proposed > approved

    def test_unmatched_source(self):
        s = read(self.run_dir / "state.json")
        self.worker("", self.run_dir, s, "")
        advance(self.run_dir)
        self.worker("", self.run_dir, read(self.run_dir / "state.json"), "")
        path = self.run_dir / "literature.json"
        doc = read(path)
        doc["papers"][1]["excerpt"] = "an invented excerpt which is not in the document"
        save(path, doc)
        with self.assertRaisesRegex(ValueError, "Unmatched excerpt"):
            advance(self.run_dir)
        self.assertEqual(read(self.run_dir / "state.json")["phase"], "read")

    def test_confirmation_budget_rejection_replans_without_reusing_frozen_inputs(self):
        run = self.run_dir
        self.through_budget()
        s = snapshot(run)
        self.worker("", run, s, "")
        rd = run / "rounds/01"
        code = ("import json, sys\nfrom pathlib import Path\nmode=sys.argv[-1]\n"
                "Path(mode+'-scores.json').write_text(json.dumps([dict(unit='a',baseline=0,candidate=1)]))\n"
                "print(json.dumps(dict(baseline=0,candidate=1,n=1)))\n")
        (rd / "experiment.py").write_text(code)
        advance(run)
        self.worker("", run, snapshot(run), "")
        self.assertEqual(advance(run), "confirm")
        # Account for other already reserved time in this grant.
        grant = s["grant"]
        save(run / "accounting/other.json", dict(grant=grant["id"], cards=0, hourly_rate=0,
                                               reserved_seconds=grant["limits"]["wall_hours"] * 3600 - 1))
        with patch("study.execute", side_effect=AssertionError("confirmation launched early")):
            self.assertEqual(advance(run), "budget")
        self.assertEqual(self.run_to_pause()["phase"], "budget_review")
        self.reply("revise-budget", "fit the remaining allowance with a smaller design")
        s = snapshot(run)
        self.worker("", run, s, "")
        path = run / budget_path(s)
        req = read(path)
        req["wall_hours"] = 0.1 / 3600
        save(path, req)
        self.assertEqual(advance(run), "plan")  # old grant covers the reduced design
        self.assertIn("-rev", artifacts(snapshot(run))[0])
        self.assertTrue((rd / "dev.json").is_file())
        self.assertFalse((rd / "confirm.json").exists())

    def test_cli_resume_and_legacy_selection_require_real_reply(self):
        run = self.run_dir
        self.run_to_pause()
        old = read(run / "state.json")
        old.pop("approval_version")
        old.update(phase="plan", idea="I0")
        save(run / "state.json", old)
        cli = [sys.executable, str(Path(__file__).with_name("study.py"))]
        text = subprocess.check_output(cli + ["resume", str(run)], text=True)
        self.assertIn("选题审核", text)
        s = snapshot(run)
        self.assertFalse((run / "pilots").exists())
        self.assertEqual(subprocess.check_output(cli + ["choose", str(run), s["pending"]["id"], "I2"],
                                                text=True).strip(), "pilot")
        self.assertEqual(snapshot(run)["idea"], "I2")

    def test_gpu_binding_and_cost_caps_with_simulated_inventory(self):
        shape = dict(gpu_model="Fixture GPU", cards=2, vram_gib_per_card=20, wall_hours=3,
                     hourly_rate=2.5, currency="CNY")
        grant = {"id": "budget-1", "limits": estimate(shape)}
        for change in ({"cards": 3}, {"vram_gib_per_card": 40}, {"gpu_model":"Other GPU"},
                       {"hourly_rate": 3}, {"currency":"USD"}, {"wall_hours": 4}):
            self.assertTrue(excess(self.run_dir, grant, estimate(dict(shape, **change))))
        self.assertEqual(grant["limits"]["cost"], 15)
        inventory = "0, GPU-a, Fixture GPU, 24576\n1, GPU-b, Fixture GPU, 24576\n"
        with patch("approvals.shutil.which", return_value=sys.executable), \
             patch("approvals.subprocess.check_output", return_value=inventory), \
             patch.dict("os.environ", {"CUDA_VISIBLE_DEVICES": "1"}):
            with self.assertRaisesRegex(RuntimeError, "可见 GPU"):
                process_env(shape)
            env, _ = process_env(dict(shape, cards=1))
            self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "GPU-b")


if __name__ == "__main__":
    unittest.main()
