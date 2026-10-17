#!/usr/bin/env python3
"""Reproduce the synthetic fee-cutoff held-out experiment.

The script executes the unchanged rea-workbench pipeline. It verifies the
source files against the pinned research commit instead of requiring a clean
tree, so the experiment can live in the repository it tests.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

RESEARCH_COMMIT = "f334078b7752cbca47afba6c97db2ec4a0d8cf2c"
TIERS = ("standard", "silver", "gold")
CONTROL_TRAIN_AMOUNTS = (10.0, 49.99, 50.0, 55.0, 59.99, 60.0, 1000.0, 2500.0)
HELDOUT_AMOUNTS = (5.0, 12.34, 49.0, 49.98, 50.01, 54.99, 59.98, 60.02,
                   60.5, 99.99, 150.0, 777.77)
SOURCE_FILES = (
    "src/rea_workbench/recover.py",
    "src/rea_workbench/pipeline.py",
    "src/rea_workbench/propose.py",
    "src/rea_workbench/blackbox.py",
    "vendor/rea_rebuild_gate.py",
    "fixtures/traces/fee_schedule.json",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args])


def verify_source_snapshot(repo: Path) -> dict[str, str]:
    """Require every tested source file to match the pinned commit exactly."""
    git(repo, "cat-file", "-e", f"{RESEARCH_COMMIT}^{{commit}}")
    hashes: dict[str, str] = {}
    for name in SOURCE_FILES:
        current = (repo / name).read_bytes()
        pinned = git(repo, "show", f"{RESEARCH_COMMIT}:{name}")
        if current != pinned:
            raise RuntimeError(f"tested source differs from {RESEARCH_COMMIT}: {name}")
        hashes[name] = sha256(current)
    return hashes


def synthetic_dataset(amounts: tuple[float, ...], cutoff: float, prefix: str,
                      fee_schedule) -> list[dict]:
    """Move only the surcharge cutoff in the repository's existing oracle."""
    rows = []
    for tier in TIERS:
        for index, amount in enumerate(amounts):
            original = fee_schedule(amount, tier)
            output = round(
                original - (1.0 if amount < 50 else 0.0)
                + (1.0 if amount < cutoff else 0.0),
                2,
            )
            rows.append({
                "id": f"{prefix}_{tier}_{index:02d}",
                "input": {"amount": amount, "tier": tier},
                "output": output,
            })
    return rows


def evaluate(rebuild: Path, rows: list[dict], module_name: str) -> dict:
    spec = importlib.util.spec_from_file_location(module_name, rebuild)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import emitted rebuild: {rebuild}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evaluated = []
    for row in rows:
        got = module.apply(**row["input"])
        evaluated.append({
            **row,
            "got": got,
            "ok": abs(float(got) - float(row["output"])) < 1e-9,
        })
    return {
        "passed": sum(row["ok"] for row in evaluated),
        "total": len(evaluated),
        "rows": evaluated,
    }


def run_experiment(repo: Path) -> dict:
    repo = repo.resolve()
    before = verify_source_snapshot(repo)
    sys.path.insert(0, str(repo / "src"))
    sys.path.insert(0, str(repo / "vendor"))
    from rea_workbench.blackbox import fee_schedule
    from rea_workbench.pipeline import run_case

    original = json.loads((repo / "fixtures/traces/fee_schedule.json").read_text())
    original_unique_inputs = {
        (row["input"]["amount"], row["input"]["tier"]) for row in original
    }
    if len(original) != 24 or len(original_unique_inputs) != 23:
        raise RuntimeError("unexpected original fixture shape")
    if set(CONTROL_TRAIN_AMOUNTS) & set(HELDOUT_AMOUNTS):
        raise RuntimeError("training and held-out amounts overlap")

    conditions = (
        ("original_50", original, 50.0),
        ("controlled_50", synthetic_dataset(
            CONTROL_TRAIN_AMOUNTS, 50.0, "controlled_50", fee_schedule), 50.0),
        ("controlled_60", synthetic_dataset(
            CONTROL_TRAIN_AMOUNTS, 60.0, "controlled_60", fee_schedule), 60.0),
    )
    results = {
        "researchCommit": RESEARCH_COMMIT,
        "synthetic": True,
        "modelCalls": 0,
        "productionData": False,
        "sourceHashes": before,
        "originalFixture": {"rows": 24, "uniqueInputs": 23},
        "controlledTraining": {
            "amounts": list(CONTROL_TRAIN_AMOUNTS),
            "tiers": list(TIERS),
            "rows": 24,
        },
        "heldOut": {
            "amounts": list(HELDOUT_AMOUNTS),
            "tiers": list(TIERS),
            "rows": 36,
        },
        "metric": "exact fee match; abs(error) < 1e-9",
        "scope": "deterministic fee recovery; not an LLM or production benchmark",
        "conditions": {},
    }
    with tempfile.TemporaryDirectory(prefix="rea-fee-cutoff-") as temp_dir:
        scratch = Path(temp_dir)
        for label, training, cutoff in conditions:
            train_path = scratch / f"{label}-train.json"
            train_path.write_text(json.dumps(training, indent=2) + "\n")
            heldout = synthetic_dataset(
                HELDOUT_AMOUNTS, cutoff, f"{label}_heldout", fee_schedule
            )
            pipeline = run_case(
                "fee_schedule", traces_path=train_path, work_dir=scratch / label
            )
            rebuild = Path(pipeline["paths"]["rebuild"])
            results["conditions"][label] = {
                "cutoffInSyntheticOracle": cutoff,
                "unchangedPipelineGateOk": pipeline["ok"],
                "pipelineErrors": pipeline["errors"],
                "pipelineClaims": pipeline["claims"],
                "emittedSourceSha256": sha256(rebuild.read_bytes()),
                "training": evaluate(rebuild, training, f"{label}_training"),
                "heldOut": evaluate(rebuild, heldout, f"{label}_heldout"),
            }
    after = verify_source_snapshot(repo)
    if before != after:
        raise RuntimeError("tested source changed during experiment")
    results["testedSourceUnchanged"] = True
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    results = run_experiment(args.repo)
    rendered = json.dumps(results, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
