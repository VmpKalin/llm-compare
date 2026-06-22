#!/usr/bin/env python3
"""
Build report.html from metrics/scored.jsonl (falls back to results.jsonl).
Self-contained: open in any browser. No network needed.

  python report.py
"""
import json, html
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent
SCORED = ROOT / "metrics" / "scored.jsonl"
RESULTS = ROOT / "metrics" / "results.jsonl"
OUT = ROOT / "report.html"


def load():
    src = SCORED if SCORED.exists() else RESULTS
    return [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()], src.name


def fmt(v, suffix="", dash="–"):
    return f"{v}{suffix}" if v is not None else dash


def main():
    rows, src = load()
    runs = sorted({r["run_name"] for r in rows})
    cats = sorted({r["category"] for r in rows})
    tasks = sorted({(r["category"], r["task"]) for r in rows})

    by = {(r["run_name"], r["category"], r["task"]): r for r in rows}

    # ---- aggregates per run ----
    agg = {}
    for run in runs:
        rs = [r for r in rows if r["run_name"] == run]
        scores = [r["score"] for r in rs if r.get("score") is not None]
        lat = [r["latency_total_s"] for r in rs if r.get("latency_total_s")]
        tps = [r["tokens_per_sec"] for r in rs if r.get("tokens_per_sec")]
        cost = sum(r.get("cost_usd") or 0 for r in rs)
        energy = sum(r.get("vm_cost_usd_est") or 0 for r in rs)
        agg[run] = {
            "quality": round(sum(scores) / len(scores), 3) if scores else None,
            "avg_lat": round(sum(lat) / len(lat), 2) if lat else None,
            "avg_tps": round(sum(tps) / len(tps), 1) if tps else None,
            "total_cost": round(cost, 5),
            "total_vmcost": round(energy, 5),
            "model": rs[0]["model"], "hw": rs[0]["hardware"],
        }

    # ---- quality matrix: category x run ----
    cat_quality = defaultdict(dict)
    for run in runs:
        for cat in cats:
            sc = [by[(run, cat, t)]["score"]
                  for (c, t) in tasks if c == cat and (run, cat, t) in by
                  and by[(run, cat, t)].get("score") is not None]
            cat_quality[cat][run] = round(sum(sc) / len(sc), 2) if sc else None

    def heat(v):
        if v is None: return "background:var(--null)"
        # green high, red low
        r = int(220 * (1 - v)); g = int(180 * v)
        return f"background:rgb({r+30},{g+40},60);color:#fff"

    css = """
    :root{--bg:#0f1117;--panel:#171a22;--line:#262b36;--ink:#e7ecf3;--mut:#8b95a7;
          --acc:#3ddc84;--acc2:#5b9dff;--null:#222730;}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
      font:14px/1.5 ui-monospace,'SF Mono',Menlo,monospace}
    .wrap{max-width:1200px;margin:0 auto;padding:32px 20px 80px}
    h1{font-size:22px;letter-spacing:.5px;margin:0 0 4px}
    h2{font-size:15px;color:var(--acc);text-transform:uppercase;letter-spacing:1px;
       margin:38px 0 12px;border-bottom:1px solid var(--line);padding-bottom:6px}
    .sub{color:var(--mut);font-size:12px;margin-bottom:8px}
    table{border-collapse:collapse;width:100%;margin:6px 0 4px;font-size:13px}
    th,td{border:1px solid var(--line);padding:7px 10px;text-align:center}
    th{background:var(--panel);color:var(--mut);font-weight:600;
       text-transform:uppercase;font-size:11px;letter-spacing:.5px}
    td.l,th.l{text-align:left}
    .run{font-size:12px}.mut{color:var(--mut)}
    .bar{height:6px;background:var(--acc);border-radius:3px;display:inline-block}
    details{background:var(--panel);border:1px solid var(--line);border-radius:8px;
            margin:8px 0;padding:0 14px}
    summary{cursor:pointer;padding:12px 0;font-size:13px;color:var(--acc2)}
    pre{background:#0b0d12;border:1px solid var(--line);border-radius:6px;
        padding:10px;overflow:auto;white-space:pre-wrap;font-size:12px;color:#cdd6e4;max-height:340px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
    .badge{display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;
           background:#2a2f3a;color:var(--mut);margin-left:6px}
    .judge{background:#3a2f12;color:#e3b341}
    """

    H = [f"<!doctype html><html><head><meta charset='utf-8'><title>LLM Benchmark</title><style>{css}</style></head><body><div class='wrap'>"]
    H.append("<h1>Local vs Cloud — Model &amp; Hardware Benchmark</h1>")
    H.append(f"<div class='sub'>source: {src} · {len(runs)} runs · {len(tasks)} tasks · {len(cats)} categories</div>")

    # --- Summary table ---
    H.append("<h2>Run summary — quality vs cost vs speed</h2>")
    H.append("<table><tr><th class='l'>Run (model · hardware)</th><th>Quality</th>"
             "<th>Avg latency</th><th>Avg tok/s</th><th>Total $ (Claude)</th><th>VM $ (local est.)</th></tr>")
    for run in runs:
        a = agg[run]
        q = a["quality"]
        qcell = f"{int(q*100)}%" if q is not None else "–"
        H.append(f"<tr><td class='l run'>{html.escape(a['model'])} "
                 f"<span class='mut'>· {html.escape(a['hw'])}</span></td>"
                 f"<td style='{heat(q)}'>{qcell}</td>"
                 f"<td>{fmt(a['avg_lat'],'s')}</td><td>{fmt(a['avg_tps'])}</td>"
                 f"<td>{'$'+format(a['total_cost'],'.4f') if a['total_cost'] else '–'}</td>"
                 f"<td>{'$'+format(a['total_vmcost'],'.4f') if a['total_vmcost'] else '–'}</td></tr>")
    H.append("</table>")

    # --- Quality by category ---
    H.append("<h2>Quality by category</h2>")
    H.append("<div class='sub'>1.0 = all tasks in that category passed. AUTO-graded for coding/structured; "
             "Claude-judged for reasoning/text (judge bias possible).</div>")
    H.append("<table><tr><th class='l'>Category</th>" +
             "".join(f"<th class='run'>{html.escape(agg[r]['model'])}<br><span class='mut'>{html.escape(agg[r]['hw'])}</span></th>" for r in runs) + "</tr>")
    for cat in cats:
        H.append(f"<tr><td class='l'>{cat}</td>")
        for run in runs:
            v = cat_quality[cat][run]
            cell = f"{int(v*100)}%" if v is not None else "–"
            H.append(f"<td style='{heat(v)}'>{cell}</td>")
        H.append("</tr>")
    H.append("</table>")

    # --- Cross-hardware speed (same model, different hw) ---
    H.append("<h2>Cross-hardware speed (tok/s)</h2>")
    H.append("<div class='sub'>Same local model on different machines — the hardware story.</div>")
    models_hw = defaultdict(dict)
    for run in runs:
        if agg[run]["hw"] != "api":
            models_hw[agg[run]["model"]][agg[run]["hw"]] = agg[run]["avg_tps"]
    hw_order = ["rtx3060", "m1", "pi5"]
    present_hw = [h for h in hw_order if any(h in v for v in models_hw.values())]
    if models_hw:
        H.append("<table><tr><th class='l'>Model</th>" +
                 "".join(f"<th>{h}</th>" for h in present_hw) + "</tr>")
        for model, hws in models_hw.items():
            H.append(f"<tr><td class='l'>{html.escape(model)}</td>")
            mx = max([v for v in hws.values() if v] or [1])
            for h in present_hw:
                v = hws.get(h)
                bar = f"<span class='bar' style='width:{int((v/mx)*80)}px'></span>" if v else ""
                H.append(f"<td>{fmt(v)} {bar}</td>")
            H.append("</tr>")
        H.append("</table>")
    else:
        H.append("<div class='sub'>No local runs yet.</div>")

    # --- Side-by-side outputs ---
    H.append("<h2>Outputs side by side</h2>")
    for cat, task in tasks:
        H.append(f"<details><summary>{cat} / {task}</summary><div class='grid'>")
        for run in runs:
            r = by.get((run, cat, task))
            if not r: continue
            out_path = ROOT / r["output_file"]
            txt = out_path.read_text(encoding="utf-8")[:1500] if out_path.exists() else "(missing)"
            sc = r.get("score")
            sc_txt = f"{int(sc*100)}%" if sc is not None else "n/a"
            jb = "<span class='badge judge'>judge</span>" if r.get("judge") else ""
            H.append(f"<div><div class='run'>{html.escape(r['model'])} "
                     f"<span class='mut'>· {html.escape(r['hardware'])}</span> "
                     f"<span class='badge'>{sc_txt}</span>{jb}</div>"
                     f"<pre>{html.escape(txt)}</pre></div>")
        H.append("</div></details>")

    H.append("</div></body></html>")
    OUT.write_text("".join(H), encoding="utf-8")
    print(f"Report -> {OUT}")


if __name__ == "__main__":
    main()
