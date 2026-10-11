"""Emit a human-readable HTML pass/fail report for one or more cases."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _esc(x: Any) -> str:
    return html.escape(str(x))


def render_case(case_result: dict) -> str:
    ok = case_result["ok"]
    badge = "PASS" if ok else "FAIL"
    badge_cls = "pass" if ok else "fail"
    rows_html = []
    for r in case_result.get("eval_rows") or []:
        mark = "PASS" if r["ok"] else "FAIL"
        cls = "pass" if r["ok"] else "fail"
        rows_html.append(
            f"<tr class='{cls}'><td><code>{_esc(r['id'])}</code></td>"
            f"<td class='{cls}'>{mark}</td>"
            f"<td><code>{_esc(r.get('expect'))}</code></td>"
            f"<td><code>{_esc(r.get('got'))}</code></td>"
            f"<td>{_esc(r.get('description') or '')}</td></tr>"
        )
    claims_html = []
    for c in case_result.get("claims") or []:
        claims_html.append(
            f"<li><strong>{_esc(c['id'])}</strong> "
            f"(conf={_esc(c['confidence'])}, {_esc(c['authority'])}): "
            f"{_esc(c['statement'])}</li>"
        )
    errs = case_result.get("errors") or []
    err_block = ""
    if errs:
        err_block = (
            "<div class='errors'><h3>Errors</h3><ul>"
            + "".join(f"<li>{_esc(e)}</li>" for e in errs)
            + "</ul></div>"
        )
    passed = sum(1 for r in (case_result.get("eval_rows") or []) if r["ok"])
    total = len(case_result.get("eval_rows") or [])
    return f"""
<section class="case">
  <header>
    <h2>{_esc(case_result.get('title') or case_result['case'])}
      <span class="badge {badge_cls}">{badge}</span>
    </h2>
    <p class="summary">{_esc(case_result.get('summary') or '')}</p>
    <p class="meta">evals {passed}/{total} · claims {len(case_result.get('claims') or [])}</p>
  </header>
  <h3>Recovered claims</h3>
  <ul class="claims">{''.join(claims_html) or '<li>(none)</li>'}</ul>
  <h3>Behavior evals</h3>
  <table>
    <thead><tr><th>id</th><th>result</th><th>expect</th><th>got</th><th>description</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  {err_block}
</section>
"""


def write_report(results: list[dict], out_path: Path, title: str = "rea-workbench report") -> Path:
    overall = all(r["ok"] for r in results) and bool(results)
    overall_badge = "PASS" if overall else "FAIL"
    overall_cls = "pass" if overall else "fail"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "\n".join(render_case(r) for r in results)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} — {overall_badge}</title>
<style>
  :root {{
    --bg: #0b1220;
    --card: #121a2b;
    --text: #e7eefc;
    --muted: #9aa8c7;
    --pass: #3dd68c;
    --fail: #ff6b6b;
    --line: #243047;
    --accent: #6ea8fe;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1a2744, var(--bg));
    color: var(--text); line-height: 1.5; padding: 32px 20px 64px;
  }}
  main {{ max-width: 960px; margin: 0 auto; }}
  .hero {{
    background: linear-gradient(135deg, #152238, #10182a 60%);
    border: 1px solid var(--line); border-radius: 16px; padding: 28px 28px 22px;
    margin-bottom: 24px; box-shadow: 0 20px 50px rgba(0,0,0,.35);
  }}
  .hero h1 {{ margin: 0 0 8px; font-size: 1.6rem; letter-spacing: -0.02em; }}
  .hero p {{ margin: 0; color: var(--muted); }}
  .badge {{
    display: inline-block; margin-left: 10px; padding: 2px 10px; border-radius: 999px;
    font-size: .85rem; font-weight: 700; vertical-align: middle;
  }}
  .badge.pass {{ background: rgba(61,214,140,.15); color: var(--pass); border: 1px solid rgba(61,214,140,.35); }}
  .badge.fail {{ background: rgba(255,107,107,.15); color: var(--fail); border: 1px solid rgba(255,107,107,.35); }}
  .case {{
    background: var(--card); border: 1px solid var(--line); border-radius: 14px;
    padding: 20px 22px 24px; margin-bottom: 18px;
  }}
  .case h2 {{ margin: 0 0 6px; font-size: 1.2rem; }}
  .summary {{ color: var(--muted); margin: 0 0 4px; }}
  .meta {{ color: var(--accent); font-size: .9rem; margin: 0 0 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; }}
  tr.pass td:nth-child(2) {{ color: var(--pass); font-weight: 700; }}
  tr.fail td:nth-child(2) {{ color: var(--fail); font-weight: 700; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .85em; }}
  .claims {{ margin-top: 0; }}
  .errors {{ margin-top: 14px; padding: 12px; border-radius: 10px; background: rgba(255,107,107,.08); border: 1px solid rgba(255,107,107,.3); }}
  footer {{ margin-top: 28px; color: var(--muted); font-size: .85rem; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<main>
  <div class="hero">
    <h1>{_esc(title)} <span class="badge {overall_cls}">{overall_badge}</span></h1>
    <p>Black-box I/O traces → recovered rule → rebuild → evidence gate → behavior evals.</p>
    <p style="margin-top:8px">Generated { _esc(now) } · {len(results)} case(s) ·
      {"all passed" if overall else "one or more failed"}</p>
  </div>
  {body}
  <footer>
    Built with <a href="https://github.com/BrickerP/rea-workbench">rea-workbench</a>
    · gate: <a href="https://github.com/BrickerP/rea-rebuild-gate">rea-rebuild-gate</a>
    · hire: <a href="https://brickerp.github.io/hire/">brickerp.github.io/hire</a>
  </footer>
</main>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    # also dump machine-readable sidecar
    side = out_path.with_suffix(".json")
    side.write_text(
        json.dumps({"ok": overall, "cases": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path
