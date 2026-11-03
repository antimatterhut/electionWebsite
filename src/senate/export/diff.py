"""“What changed since last run” report (plan §8.4): output/diff.md + output/changes.json (site `changes.json` shape)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings


@dataclass
class DiffReport:
    markdown: str
    changes: dict
    alerts: int = 0
    rows: list[dict] = field(default_factory=list)


def _load(d: Path | None, name: str) -> dict | None:
    p = Path(d) / name if d else None
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None


def _county_deltas(prev: Path | None, new: Path, top: int = 20) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    if not prev or not (new / "states").is_dir():
        return out
    for f in sorted((new / "states").glob("*.json")):
        old = _load(prev / "states", f.name)
        if not old:
            continue
        before = {c["geoid"]: c["proj_margin"] for c in old.get("counties", [])}
        for c in json.loads(f.read_text(encoding="utf-8")).get("counties", []):
            if c["geoid"] in before:
                out.append((f.stem, c.get("name", c["geoid"]), c["proj_margin"] - before[c["geoid"]]))
    return sorted(out, key=lambda t: -abs(t[2]))[:top]


def _source_status(h: dict | None) -> dict[str, str]:
    """Source name -> status, for both the live pipeline shape (`stages`) and the published shape (`sources`)."""
    if not h:
        return {}
    if "sources" in h:
        return {s["name"]: s["status"] for s in h["sources"]}
    return {k: ("ok" if v.get("ok") else "failed") for k, v in h.get("stages", {}).items()}


def diff_runs(prev_dir: Path | None, new_dir: Path, cfg: Settings) -> DiffReport:
    new_dir = Path(new_dir)
    new = _load(new_dir, "summary.json")
    if new is None:
        raise FileNotFoundError(f"{new_dir}/summary.json missing")
    prev = _load(prev_dir, "summary.json")
    am, ap = cfg.diff.alert_margin_pts, cfg.diff.alert_prob
    items: list[dict] = []
    rows: list[dict] = []
    lines = [f"# Run {new['run_id']} (as of {new['as_of']})", ""]
    if prev is None:
        lines.append("No previous published run: nothing to compare.")
        return DiffReport("\n".join(lines) + "\n", {"run_id": new["run_id"], "as_of": new["as_of"], "items": []})

    nn, pn = new["national"], prev["national"]
    d_nat = nn["s_nat"] - pn["s_nat"]
    gb_new, gb_old = (nn.get("generic_ballot") or {}).get("margin"), (pn.get("generic_ballot") or {}).get("margin")
    lines += ["## National", "", "| | previous | new | Δ |", "|---|---|---|---|",
              f"| s_nat | {pn['s_nat']:.2f} | {nn['s_nat']:.2f} | {d_nat:+.2f} |"]
    if gb_new is not None and gb_old is not None:
        lines.append(f"| generic ballot | {gb_old:.2f} | {gb_new:.2f} | {gb_new - gb_old:+.2f} |")
    c_new = (new.get("simulation") or {}).get("seats", {}).get("p_control")
    c_old = (prev.get("simulation") or {}).get("seats", {}).get("p_control")
    if c_new is not None and c_old is not None:
        lines.append(f"| P(D control) | {c_old:.3f} | {c_new:.3f} | {c_new - c_old:+.3f} |")
    lines.append("")
    if abs(d_nat) >= am:
        items.append({"kind": "national", "state": None, "text": f"National swing moved {d_nat:+.1f} pts", "delta": round(d_nat, 2)})

    old = {r["state"]: r for r in prev["races"]}
    lines += ["## States", "", "| state | Δ margin | Δ P(win) | swing source | new polls | Δ early vote | |", "|---|---|---|---|---|---|---|"]
    for r in new["races"]:
        o = old.get(r["state"])
        if o is None:
            continue
        dm = r["proj_margin"] - o["proj_margin"]
        dp = (r["p_dside_win"] - o["p_dside_win"]) if "p_dside_win" in r and "p_dside_win" in o else None
        src_changed = r["swing_source"] != o["swing_source"]
        src = f"{o['swing_source']}→{r['swing_source']}" if src_changed else r["swing_source"]
        npoll = r["polls"]["n"] - o["polls"]["n"]
        dev = (r["components"].get("early_vote") or 0) - (o["components"].get("early_vote") or 0)
        alert = abs(dm) >= am or (dp is not None and abs(dp) >= ap)
        rows.append({"state": r["state"], "d_margin": dm, "d_p": dp, "alert": alert})
        if alert or src_changed or npoll:
            dps = "" if dp is None else f"{dp:+.3f}"
            lines.append(f"| {r['state']} | {dm:+.2f} | {dps} | {src} | {npoll:+d} | {dev:+.2f} | {'⚠️' if alert else ''} |")
        if alert:
            by_p = dp is not None and abs(dp) >= ap
            items.append({"kind": "p_win" if by_p else "margin", "state": r["state"],
                          "text": f"{r['state']}: projected margin moved {abs(dm):.1f} pts toward {'Democrats' if dm > 0 else 'Republicans'}",
                          "delta": round(dp if by_p else dm, 3)})
    lines.append("")

    cty = _county_deltas(prev_dir, new_dir)
    if cty:
        lines += ["## Largest county moves", "", "| state | county | Δ margin |", "|---|---|---|"]
        lines += [f"| {s} | {n} | {d:+.2f} |" for s, n, d in cty] + [""]

    hn, hp = _source_status(_load(new_dir, "data_health.json")), _source_status(_load(prev_dir, "data_health.json"))
    bad = {k: v for k, v in hn.items() if v != "ok"}
    changed = {k: (hp.get(k), v) for k, v in hn.items() if hp.get(k) != v}
    lines += ["## Data health", ""]
    lines += [f"- ⚠️ {k}: {v}" for k, v in bad.items()] or ["- all sources ok"]
    lines += [f"- changed: {k}: {a} → {b}" for k, (a, b) in changed.items()]
    return DiffReport("\n".join(lines) + "\n", {"run_id": new["run_id"], "as_of": new["as_of"], "items": items},
                      sum(r["alert"] for r in rows), rows)


def write_diff(report: DiffReport, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diff.md").write_text(report.markdown, encoding="utf-8")
    (out_dir / "changes.json").write_text(json.dumps(report.changes, indent=2), encoding="utf-8")
