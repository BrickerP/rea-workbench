#!/usr/bin/env python3
"""Tests for rea-workbench end-to-end product."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))

from rea_workbench import blackbox  # noqa: E402
from rea_workbench.cli import main  # noqa: E402
from rea_workbench.pipeline import run_case, run_demo  # noqa: E402
from rea_workbench.recover import recover  # noqa: E402


class FixtureTests(unittest.TestCase):
    def test_write_all_fixtures(self):
        with tempfile.TemporaryDirectory() as td:
            paths = blackbox.write_all_fixtures(Path(td))
            self.assertEqual(len(paths), 3)
            for p in paths:
                rows = json.loads(p.read_text(encoding="utf-8"))
                self.assertIsInstance(rows, list)
                self.assertGreater(len(rows), 0)


class RecoverTests(unittest.TestCase):
    def test_fee_residual_zero(self):
        traces = blackbox.generate_fee_traces()
        rec = recover("fee_schedule", traces)
        self.assertEqual(rec.params.get("residual"), 0.0)
        self.assertEqual(rec.params.get("surcharge"), 1.0)
        self.assertIn("gold", rec.params["tiers"])

    def test_percent_formulas(self):
        traces = blackbox.generate_percent_traces()
        rec = recover("percent_rule", traces)
        self.assertTrue(rec.params["add_sub_ok"])
        self.assertTrue(rec.params["mul_div_ok"])

    def test_speed_params(self):
        traces = blackbox.generate_speed_traces()
        rec = recover("speed_ramp", traces)
        self.assertEqual(rec.params["speed"], 6.0)
        self.assertEqual(rec.params["acceleration"], 0.001)
        self.assertEqual(rec.params["max_speed"], 13.0)
        self.assertEqual(rec.params["residual"], 0.0)


class PipelineTests(unittest.TestCase):
    def test_each_case_passes(self):
        for case in ("fee_schedule", "percent_rule", "speed_ramp"):
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as td:
                    result = run_case(case, work_dir=Path(td) / case)
                    self.assertTrue(result["ok"], result.get("errors"))
                    self.assertTrue(all(r["ok"] for r in result["eval_rows"]))

    def test_demo_exit_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.html"
            # monkey via run_demo report_path; fixtures still go to ROOT
            results, path = run_demo(report_path=report)
            self.assertTrue(path.exists())
            self.assertTrue(all(r["ok"] for r in results))
            html = path.read_text(encoding="utf-8")
            self.assertIn("PASS", html)
            self.assertIn("Tiered fee schedule", html)


class CliTests(unittest.TestCase):
    def test_demo_cli(self):
        with tempfile.TemporaryDirectory() as td:
            report = str(Path(td) / "out.html")
            self.assertEqual(main(["demo", "--report", report]), 0)
            self.assertTrue(Path(report).exists())

    def test_run_cli_percent(self):
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "art")
            report = str(Path(td) / "p.html")
            self.assertEqual(
                main(["run", "percent_rule", "--out", out, "--report", report]),
                0,
            )


if __name__ == "__main__":
    unittest.main()
