"""CLI entry: python -m rea_workbench demo"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import CASES, run_case, run_demo
from .report import write_report


def cmd_demo(args: argparse.Namespace) -> int:
    print("rea-workbench demo")
    print("=" * 56)
    print("Use case: reverse-engineer a black-box business rule")
    print("from input/output traces → propose rebuild → gate → HTML report")
    cases = tuple(args.cases) if args.cases else CASES
    results, report = run_demo(
        cases=cases,
        report_path=Path(args.report) if args.report else None,
        min_confidence=args.min_confidence,
    )
    return 0 if all(r["ok"] for r in results) else 1


def cmd_run(args: argparse.Namespace) -> int:
    result = run_case(
        args.case,
        traces_path=Path(args.traces) if args.traces else None,
        work_dir=Path(args.out) if args.out else None,
        min_confidence=args.min_confidence,
    )
    report = Path(args.report) if args.report else Path("reports") / f"{args.case}.html"
    write_report([result], report, title=f"rea-workbench · {args.case}")
    status = "PASS" if result["ok"] else "FAIL"
    print(f"{status}  {result['title']} → {report}")
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rea_workbench",
        description=(
            "Recover a black-box business rule from I/O traces, "
            "propose a rebuild, validate evidence, run evals, emit HTML report."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="Full loop on bundled fee/percent/speed cases")
    d.add_argument("--cases", nargs="+", choices=list(CASES), default=None)
    d.add_argument("--report", default=None, help="HTML report path")
    d.add_argument("--min-confidence", type=float, default=0.8)
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("run", help="Run one case from traces JSON")
    r.add_argument("case", choices=list(CASES))
    r.add_argument("--traces", help="Path to traces JSON (default: generate fixtures)")
    r.add_argument("--out", help="Artifact directory for rebuild/evidence/evals")
    r.add_argument("--report", help="HTML report path")
    r.add_argument("--min-confidence", type=float, default=0.8)
    r.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
