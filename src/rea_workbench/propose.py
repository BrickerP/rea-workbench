"""Turn a Recovery into rebuild.py + evidence.json + evals.json for the gate."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .recover import Recovery

SCHEMA = "rea-rebuild-gate/v1"


def _traces_digest(traces: list[dict]) -> str:
    blob = json.dumps(traces, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _assign_coverage(recovery: Recovery, evals: list[dict]) -> None:
    ids = [e["id"] for e in evals]
    if recovery.case == "fee_schedule":
        small, big = [], []
        for e in evals:
            if float(e["input"].get("amount", 0)) < 50:
                small.append(e["id"])
            else:
                big.append(e["id"])
        for claim in recovery.claims:
            if claim.id == "under-50-surcharge":
                claim.covers_eval = small or ids[:1]
            elif claim.id == "tier-rates":
                claim.covers_eval = big or ids
    elif recovery.case == "percent_rule":
        add_ids = [e["id"] for e in evals if e["input"].get("op") in ("+", "-")]
        mul_ids = [e["id"] for e in evals if e["input"].get("op") in ("*", "/")]
        for claim in recovery.claims:
            if claim.id == "add-sub-percent":
                claim.covers_eval = add_ids
            elif claim.id == "mul-div-percent":
                claim.covers_eval = mul_ids
    else:
        for claim in recovery.claims:
            claim.covers_eval = ids


def propose(
    recovery: Recovery,
    traces: list[dict],
    out_dir: Path,
    traces_digest: str | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    evals = recovery.eval_builder(traces)
    _assign_coverage(recovery, evals)

    rebuild_path = out_dir / "rebuild.py"
    rebuild_path.write_text(recovery.rebuild_source, encoding="utf-8")

    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "artifact": {
            "name": f"blackbox-{recovery.case}",
            "digest": traces_digest or _traces_digest(traces),
            "kind": "synthetic",
        },
        "provider": {
            "id": "rea-workbench",
            "version": "1.0.0",
        },
        "recovered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claims": [
            {
                "id": c.id,
                "statement": c.statement,
                "confidence": c.confidence,
                "authority": c.authority,
                "limitations": c.limitations,
                "covers_eval": c.covers_eval,
            }
            for c in recovery.claims
        ],
    }

    evidence_path = out_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    evals_path = out_dir / "evals.json"
    evals_path.write_text(json.dumps(evals, indent=2) + "\n", encoding="utf-8")

    summary_path = out_dir / "recovery.json"
    summary_path.write_text(
        json.dumps(
            {
                "case": recovery.case,
                "title": recovery.title,
                "summary": recovery.summary,
                "params": recovery.params,
                "n_traces": len(traces),
                "n_evals": len(evals),
                "n_claims": len(recovery.claims),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "rebuild": rebuild_path,
        "evidence": evidence_path,
        "evals": evals_path,
        "summary": summary_path,
    }
