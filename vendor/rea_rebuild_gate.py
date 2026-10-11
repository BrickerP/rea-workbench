#!/usr/bin/env python3
"""rea-rebuild-gate: CI/CLI gate for REA → rebuild pipelines.

Validates evidence claims (confidence + claim→eval coverage) and runs
behavior evals a rebuild must pass before merge. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

SCHEMA = "rea-rebuild-gate/v1"
DEFAULT_MIN_CONF = 0.8
KINDS = {"javascript", "native", "web", "synthetic"}
AUTHORITIES = {"observed", "inferred"}
ROOT = Path(__file__).resolve().parents[1]


class GateError(Exception):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise GateError(f"missing file: {path}") from e
    except json.JSONDecodeError as e:
        raise GateError(f"invalid JSON in {path}: {e}") from e


def validate_evidence(data: Any, min_confidence: float = DEFAULT_MIN_CONF) -> list[str]:
    """Return list of error strings; empty means OK."""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["evidence root must be an object"]

    if data.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA!r}, got {data.get('schema')!r}")

    artifact = data.get("artifact")
    if not isinstance(artifact, dict):
        errs.append("artifact must be an object")
    else:
        for key in ("name", "digest", "kind"):
            if not artifact.get(key):
                errs.append(f"artifact.{key} required")
        kind = artifact.get("kind")
        if kind and kind not in KINDS:
            errs.append(f"artifact.kind must be one of {sorted(KINDS)}, got {kind!r}")
        digest = artifact.get("digest") or ""
        if digest and not str(digest).startswith("sha256:"):
            errs.append("artifact.digest must start with 'sha256:'")

    provider = data.get("provider")
    if not isinstance(provider, dict):
        errs.append("provider must be an object")
    else:
        if not provider.get("id"):
            errs.append("provider.id required")
        if not provider.get("version"):
            errs.append("provider.version required")

    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        errs.append("claims must be a non-empty list")
        return errs

    ids: set[str] = set()
    for i, claim in enumerate(claims):
        prefix = f"claims[{i}]"
        if not isinstance(claim, dict):
            errs.append(f"{prefix} must be an object")
            continue
        cid = claim.get("id")
        if not cid:
            errs.append(f"{prefix}.id required")
        elif cid in ids:
            errs.append(f"duplicate claim id {cid!r}")
        else:
            ids.add(cid)
        if not claim.get("statement"):
            errs.append(f"{prefix}.statement required")
        conf = claim.get("confidence")
        if not isinstance(conf, (int, float)):
            errs.append(f"{prefix}.confidence must be a number")
        else:
            if not 0.0 <= float(conf) <= 1.0:
                errs.append(f"{prefix}.confidence must be in [0,1]")
            elif float(conf) < min_confidence:
                errs.append(
                    f"{prefix}.confidence {conf} below --min-confidence {min_confidence}"
                )
        auth = claim.get("authority")
        if auth not in AUTHORITIES:
            errs.append(f"{prefix}.authority must be one of {sorted(AUTHORITIES)}")
        lim = claim.get("limitations")
        if lim is not None and not isinstance(lim, list):
            errs.append(f"{prefix}.limitations must be a list")
        covers = claim.get("covers_eval")
        if not isinstance(covers, list) or not covers:
            errs.append(f"{prefix}.covers_eval must be a non-empty list of eval ids")
        elif any(not isinstance(x, str) or not x for x in covers):
            errs.append(f"{prefix}.covers_eval entries must be non-empty strings")
    return errs


def load_impl(path: Path):
    spec = importlib.util.spec_from_file_location("rebuild_impl", path)
    if spec is None or spec.loader is None:
        raise GateError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        raise GateError(f"import failed for {path}: {e}") from e
    fn = getattr(mod, "apply", None) or getattr(mod, "run", None)
    if not callable(fn):
        raise GateError(f"{path} must expose apply(**input) or run(input)")
    return fn, getattr(mod, "apply", None) is not None


def run_evals(
    evidence: dict,
    evals: list,
    impl_path: Path,
) -> tuple[list[dict], list[str]]:
    """Return (rows, errors). rows have id/ok/got/expect/error."""
    errs: list[str] = []
    if not isinstance(evals, list) or not evals:
        return [], ["evals must be a non-empty list"]

    eval_ids: set[str] = set()
    for i, item in enumerate(evals):
        if not isinstance(item, dict) or not item.get("id"):
            errs.append(f"evals[{i}] needs id")
            continue
        if item["id"] in eval_ids:
            errs.append(f"duplicate eval id {item['id']!r}")
        eval_ids.add(item["id"])
        if "expect" not in item:
            errs.append(f"evals[{i}] ({item['id']}) needs expect")
        if "input" not in item:
            errs.append(f"evals[{i}] ({item['id']}) needs input")

    for i, claim in enumerate(evidence.get("claims") or []):
        covers = claim.get("covers_eval") or []
        for eid in covers:
            if eid not in eval_ids:
                errs.append(
                    f"claim {claim.get('id')!r} covers_eval {eid!r} not in evals"
                )

    if errs:
        return [], errs

    try:
        fn, is_apply = load_impl(impl_path)
    except GateError as e:
        return [], [str(e)]

    rows: list[dict] = []
    for item in evals:
        eid = item["id"]
        inp = item["input"]
        expect = item["expect"]
        row: dict[str, Any] = {
            "id": eid,
            "ok": False,
            "expect": expect,
            "got": None,
            "error": None,
            "description": item.get("description", ""),
        }
        try:
            got = fn(**inp) if is_apply else fn(inp)
            row["got"] = got
            # numeric tolerance for floats
            if isinstance(expect, float) or isinstance(got, float):
                row["ok"] = abs(float(got) - float(expect)) < 1e-9
            else:
                row["ok"] = got == expect
            if not row["ok"]:
                row["error"] = f"expected {expect!r}, got {got!r}"
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)

    failed = [r["id"] for r in rows if not r["ok"]]
    if failed:
        errs.append(f"failed evals: {', '.join(failed)}")

    # every claim cover must pass
    for claim in evidence.get("claims") or []:
        for eid in claim.get("covers_eval") or []:
            row = next(r for r in rows if r["id"] == eid)
            if not row["ok"]:
                errs.append(
                    f"claim {claim.get('id')!r} requires passing eval {eid!r}"
                )
    return rows, errs


def _summary_md(
    evidence_path: Path,
    rows: list[dict],
    val_errs: list[str],
    eval_errs: list[str],
    min_conf: float,
) -> str:
    ok = not val_errs and not eval_errs and rows and all(r["ok"] for r in rows)
    lines = [
        f"### rea-rebuild-gate {'PASS' if ok else 'FAIL'}",
        f"- evidence: `{evidence_path}`",
        f"- min confidence: {min_conf}",
        f"- evals: {sum(1 for r in rows if r['ok'])}/{len(rows)} passed",
        "",
        "| id | result | expect | got |",
        "|---|---|---|---|",
    ]
    for r in rows:
        mark = "PASS" if r["ok"] else "FAIL"
        lines.append(
            f"| `{r['id']}` | {mark} | `{r['expect']!r}` | `{r['got']!r}` |"
        )
    if val_errs or eval_errs:
        lines.append("")
        lines.append("**Errors**")
        for e in val_errs + eval_errs:
            lines.append(f"- {e}")
    return "\n".join(lines) + "\n"


def _write_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.evidence)
    data = _load_json(path)
    errs = validate_evidence(data, args.min_confidence)
    claims = data.get("claims") if isinstance(data, dict) else []
    n = len(claims) if isinstance(claims, list) else 0
    min_c = None
    if isinstance(claims, list) and claims:
        confs = [
            float(c["confidence"])
            for c in claims
            if isinstance(c, dict) and isinstance(c.get("confidence"), (int, float))
        ]
        min_c = min(confs) if confs else None
    if errs:
        print(f"FAIL  validate {path}")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(
        f"PASS  validate {path}  ·  {n} claim(s)  ·  min confidence {min_c:.2f}"
    )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    epath = Path(args.evidence)
    evidence = _load_json(epath)
    val_errs = validate_evidence(evidence, args.min_confidence)
    evals = _load_json(Path(args.evals))
    rows, eval_errs = ([], val_errs[:]) if val_errs else run_evals(
        evidence, evals, Path(args.impl)
    )
    if val_errs:
        eval_errs = val_errs
        rows = []
    md = _summary_md(epath, rows, val_errs, eval_errs if not val_errs else [], args.min_confidence)
    _write_step_summary(md)
    passed = sum(1 for r in rows if r["ok"])
    total = len(rows)
    claims = evidence.get("claims") if isinstance(evidence, dict) else []
    n_claims = len(claims) if isinstance(claims, list) else 0
    ok = not val_errs and not eval_errs and total > 0 and passed == total
    status = "PASS" if ok else "FAIL"
    print(f"{status}  eval  {passed}/{total} evals · {n_claims} claim(s) covered")
    for r in rows:
        mark = "PASS" if r["ok"] else "FAIL"
        extra = f"  ({r['error']})" if r.get("error") and not r["ok"] else ""
        print(f"  {mark}  {r['id']}{extra}")
    for e in (val_errs or eval_errs):
        if e not in {r.get("error") for r in rows}:
            print(f"  - {e}")
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    # validate then eval; eval already re-validates
    return cmd_eval(args)


def cmd_demo(_: argparse.Namespace) -> int:
    print("rea-rebuild-gate demo")
    print("=" * 48)
    rc = 0
    for name in ("percent_rule", "speed_ramp"):
        ex = ROOT / "examples" / name
        ns = argparse.Namespace(
            evidence=str(ex / "evidence.json"),
            evals=str(ex / "evals.json"),
            impl=str(ex / "rebuild.py"),
            min_confidence=0.8,
        )
        print()
        print(f"[{name}]")
        code = cmd_eval(ns)
        if code != 0:
            rc = code
    print()
    print("=" * 48)
    if rc == 0:
        print("RESULT: all example rebuilds PASS evidence + behavior evals")
    else:
        print("RESULT: FAIL — see above")
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rea_rebuild_gate",
        description="Gate REA → rebuild PRs: evidence confidence + behavior evals.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate evidence JSON")
    v.add_argument("evidence", nargs="?", default="evidence.json")
    v.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONF)
    v.set_defaults(func=cmd_validate)

    def add_eval_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--evidence", default="evidence.json")
        sp.add_argument("--evals", default="evals.json")
        sp.add_argument("--impl", default="rebuild.py")
        sp.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONF)

    e = sub.add_parser("eval", help="Run behavior evals against a rebuild")
    add_eval_args(e)
    e.set_defaults(func=cmd_eval)

    c = sub.add_parser("check", help="Validate + eval (Action entrypoint)")
    add_eval_args(c)
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("demo", help="Run bundled examples and print a RESULT")
    d.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GateError as e:
        print(f"FAIL  {e}", file=sys.stderr)
        return 1
    except Exception:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
