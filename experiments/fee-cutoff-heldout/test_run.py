#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("fee_cutoff_run", HERE / "run.py")
assert SPEC is not None and SPEC.loader is not None
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class FeeCutoffExperimentTests(unittest.TestCase):
    def test_reproduces_expected_counts(self):
        results = RUN.run_experiment(ROOT)
        self.assertEqual(results["conditions"]["controlled_50"]["heldOut"]["passed"], 36)
        self.assertEqual(results["conditions"]["controlled_60"]["training"]["passed"], 21)
        self.assertEqual(results["conditions"]["controlled_60"]["heldOut"]["passed"], 24)
        self.assertFalse(results["conditions"]["controlled_60"]["unchangedPipelineGateOk"])

    def test_rejects_tested_source_drift(self):
        original = RUN.git

        def changed(repo: Path, *args: str) -> bytes:
            value = original(repo, *args)
            if args[:1] == ("show",) and args[1].endswith("recover.py"):
                return value + b"# drift\n"
            return value

        with mock.patch.object(RUN, "git", side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, "tested source differs"):
                RUN.verify_source_snapshot(ROOT)


if __name__ == "__main__":
    unittest.main()
