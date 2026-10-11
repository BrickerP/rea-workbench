"""Opaque business-rule oracles used only to emit I/O traces for the demo.

The workbench never imports these into the rebuild — recovery sees traces only.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Callable


def _digest_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def fee_schedule(amount: float, tier: str) -> float:
    """Hidden fee rule: tiered rate with floor; express surcharge under $50."""
    tier = tier.lower()
    if tier == "gold":
        rate, floor = 0.015, 2.0
    elif tier == "silver":
        rate, floor = 0.022, 3.5
    else:  # standard
        rate, floor = 0.029, 5.0
    fee = max(floor, amount * rate)
    if amount < 50.0:
        fee += 1.0
    return round(fee, 2)


def percent_value(op: str, previous: float, current: float) -> float:
    """Hidden percent-button value selection."""
    if op in ("+", "-"):
        return current * previous / 100.0
    if op in ("*", "/"):
        return current / 100.0
    raise ValueError(f"unsupported op: {op!r}")


def speed_at(ticks: int) -> float:
    """Hidden clamped linear speed ramp."""
    speed, accel, vmax = 6.0, 0.001, 13.0
    for _ in range(int(ticks)):
        if speed < vmax:
            speed = min(vmax, speed + accel)
    return round(speed, 1)


ORACLES: dict[str, Callable[..., Any]] = {
    "fee_schedule": fee_schedule,
    "percent_rule": percent_value,
    "speed_ramp": speed_at,
}


def generate_fee_traces(n: int = 24, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    tiers = ["standard", "silver", "gold"]
    amounts = [10, 25, 49.99, 50, 75, 100, 200, 500, 1000, 2500]
    rows = []
    for i in range(n):
        amount = float(rng.choice(amounts) if i < len(amounts) else rng.uniform(5, 3000))
        tier = tiers[i % 3] if i < 12 else rng.choice(tiers)
        out = fee_schedule(amount, tier)
        rows.append(
            {
                "id": f"fee_{i:02d}",
                "input": {"amount": round(amount, 2), "tier": tier},
                "output": out,
            }
        )
    return rows


def generate_percent_traces() -> list[dict]:
    cases = [
        ("+", 200, 10),
        ("-", 50, 10),
        ("+", 0, 10),
        ("+", 100, 0),
        ("*", 200, 10),
        ("/", 200, 10),
        ("*", 50, 25),
        ("/", 100, 50),
        ("+", 80, 5),
        ("-", 120, 20),
        ("*", 10, 10),
        ("/", 40, 20),
    ]
    rows = []
    for i, (op, prev, cur) in enumerate(cases):
        rows.append(
            {
                "id": f"pct_{i:02d}",
                "input": {"op": op, "previous": float(prev), "current": float(cur)},
                "output": percent_value(op, float(prev), float(cur)),
            }
        )
    return rows


def generate_speed_traces() -> list[dict]:
    ticks_list = [0, 500, 1000, 2000, 4000, 7000, 10000, 15000]
    return [
        {
            "id": f"spd_{i:02d}",
            "input": {"ticks": t},
            "output": speed_at(t),
        }
        for i, t in enumerate(ticks_list)
    ]


GENERATORS = {
    "fee_schedule": generate_fee_traces,
    "percent_rule": generate_percent_traces,
    "speed_ramp": generate_speed_traces,
}


def write_traces(case: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = GENERATORS[case]()
    path = out_dir / f"{case}.json"
    blob = json.dumps(rows, indent=2) + "\n"
    path.write_text(blob, encoding="utf-8")
    meta = {
        "case": case,
        "n_traces": len(rows),
        "digest": _digest_bytes(blob.encode("utf-8")),
        "note": "I/O traces only — black-box source not included",
    }
    (out_dir / f"{case}.meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return path


def write_all_fixtures(out_dir: Path) -> list[Path]:
    return [write_traces(c, out_dir) for c in GENERATORS]
