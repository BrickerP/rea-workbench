"""End-to-end: traces → recover → propose → gate → HTML report."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import blackbox
from .propose import propose
from .recover import recover
from .report import write_report

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from rea_rebuild_gate import run_evals, validate_evidence  # noqa: E402


CASES = ("fee_schedule", "percent_rule", "speed_ramp")


def load_traces(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"traces must be a list: {path}")
    return data


def run_case(
    case: str,
    traces_path: Path | None = None,
    work_dir: Path | None = None,
    min_confidence: float = 0.8,
) -> dict[str, Any]:
    work_dir = work_dir or (ROOT / "reports" / "artifacts" / case)
    work_dir.mkdir(parents=True, exist_ok=True)

    if traces_path is None:
        fixtures = ROOT / "fixtures" / "traces"
        fixtures.mkdir(parents=True, exist_ok=True)
        traces_path = blackbox.write_traces(case, fixtures)

    traces = load_traces(traces_path)
    recovery = recover(case, traces)
    paths = propose(recovery, traces, work_dir)

    evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    evals = json.loads(paths["evals"].read_text(encoding="utf-8"))

    val_errs = validate_evidence(evidence, min_confidence)
    rows: list[dict] = []
    eval_errs: list[str] = []
    if not val_errs:
        rows, eval_errs = run_evals(evidence, evals, paths["rebuild"])
    else:
        eval_errs = list(val_errs)

    ok = not val_errs and not eval_errs and bool(rows) and all(r["ok"] for r in rows)
    return {
        "case": case,
        "title": recovery.title,
        "summary": recovery.summary,
        "ok": ok,
        "claims": evidence.get("claims") or [],
        "eval_rows": rows,
        "errors": val_errs + [e for e in eval_errs if e not in val_errs],
        "paths": {k: str(v) for k, v in paths.items()},
        "traces_path": str(traces_path),
        "n_traces": len(traces),
        "params": recovery.params,
    }


def run_demo(
    cases: tuple[str, ...] = CASES,
    report_path: Path | None = None,
    min_confidence: float = 0.8,
) -> tuple[list[dict], Path]:
    fixtures = ROOT / "fixtures" / "traces"
    blackbox.write_all_fixtures(fixtures)

    results = []
    for case in cases:
        print(f"\n[{case}] recovering from traces …")
        result = run_case(case, min_confidence=min_confidence)
        status = "PASS" if result["ok"] else "FAIL"
        n_ok = sum(1 for r in result["eval_rows"] if r["ok"])
        n = len(result["eval_rows"])
        print(f"{status}  {result['title']}")
        print(f"  {result['summary']}")
        print(f"  evals {n_ok}/{n} · claims {len(result['claims'])}")
        for r in result["eval_rows"]:
            mark = "PASS" if r["ok"] else "FAIL"
            extra = f"  ({r['error']})" if r.get("error") and not r["ok"] else ""
            print(f"    {mark}  {r['id']}{extra}")
        for e in result["errors"]:
            print(f"  - {e}")
        results.append(result)

    report_path = report_path or (ROOT / "docs" / "demo-report.html")
    write_report(results, report_path, title="rea-workbench demo")
    # also copy to reports/
    reports_copy = ROOT / "reports" / "latest.html"
    write_report(results, reports_copy, title="rea-workbench demo")

    overall = all(r["ok"] for r in results) and bool(results)
    print("\n" + "=" * 56)
    if overall:
        print(f"RESULT: PASS — HTML report → {report_path}")
    else:
        print(f"RESULT: FAIL — HTML report → {report_path}")
    print("=" * 56)
    return results, report_path
