#!/usr/bin/env python3
"""
LLM Benchmark Runner
====================
Runs every task in ./tasks/ against ONE model on the CURRENT machine,
writes outputs to ./outputs/<run_name>/ and metrics to ./metrics/results.jsonl

Run this once per (model x hardware) combo. Examples:

  # On the RTX 3060 laptop, Qwen coder via Ollama:
  python runner.py --backend ollama --model qwen2.5-coder:7b --hw rtx3060

  # On the M1 Mac, same model:
  python runner.py --backend ollama --model qwen2.5-coder:7b --hw m1

  # On the Pi 5:
  python runner.py --backend ollama --model qwen2.5-coder:7b --hw pi5

  # Bigger local model (only fits on 3060 / M1):
  python runner.py --backend ollama --model qwen2.5:14b --hw rtx3060

  # Claude (hardware label is just "api"):
  python runner.py --backend claude --model claude-haiku-4-5-20251001 --hw api
  python runner.py --backend claude --model claude-sonnet-4-6 --hw api

The run_name (= output folder) is built as <model_slug>__<hw>.
Re-running the same combo overwrites that folder and replaces its rows in results.jsonl.

Dependencies:
  pip install requests psutil          # psutil optional, for RAM tracking
  Ollama:  ollama serve  (default http://localhost:11434)
  Claude:  export ANTHROPIC_API_KEY=sk-...
"""

import argparse, json, os, re, sys, time, glob
from pathlib import Path


def load_dotenv():
    """Minimal .env loader (no dependency). Reads KEY=VALUE lines from ./.env
    and puts them in os.environ if not already set."""
    envf = Path(__file__).parent / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Need 'requests': pip install requests")

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

ROOT = Path(__file__).parent
TASKS_DIR = ROOT / "tasks"
OUTPUTS_DIR = ROOT / "outputs"
METRICS_FILE = ROOT / "metrics" / "results.jsonl"

# Claude per-million-token prices (USD), input/output. Update if prices change.
CLAUDE_PRICES = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6":          (3.00, 15.00),
    "claude-opus-4-8":            (5.00, 25.00),
}

# Cost model for local runs on a RENTED VM (USD per hour of GPU).
# This is the "what did the local path cost us" lever. Set it to your
# provider's hourly rate. RunPod RTX 5090 on-demand ~ $0.69/hr (June 2026).
# For an owned machine instead, set the rate to 0 and use electricity if you like.
VM_USD_PER_HOUR = {"rtx5090": 0.69, "rtx4090": 0.34, "api": 0.0}
DEFAULT_VM_RATE = 0.69  # fallback for any other --hw label


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_tasks():
    """Returns list of dicts: {category, name, path, prompt}."""
    tasks = []
    for cat_dir in sorted(TASKS_DIR.iterdir()):
        if not cat_dir.is_dir():
            continue
        for md in sorted(cat_dir.glob("*.md")):
            tasks.append({
                "category": cat_dir.name,
                "name": md.stem,
                "path": str(md),
                "prompt": md.read_text(encoding="utf-8"),
            })
    return tasks


def peak_ram_mb():
    if not HAVE_PSUTIL:
        return None
    return round(psutil.virtual_memory().used / (1024 * 1024), 1)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def run_ollama(model, prompt, host):
    """Call Ollama /api/generate (non-streaming). Returns dict of result+metrics."""
    url = f"{host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 8192},
    }
    t0 = time.time()
    r = requests.post(url, json=payload, timeout=1800)
    t1 = time.time()
    r.raise_for_status()
    data = r.json()

    # Ollama returns timings in nanoseconds when available.
    eval_count = data.get("eval_count")          # output tokens
    prompt_eval = data.get("prompt_eval_count")  # input tokens
    eval_dur_ns = data.get("eval_duration")      # generation time
    first_ns = data.get("prompt_eval_duration")  # ~time to process prompt

    tps = None
    if eval_count and eval_dur_ns:
        tps = round(eval_count / (eval_dur_ns / 1e9), 2)

    # Reasoning models (qwen3, deepseek-r1) put their <think> block in a
    # separate "thinking" field; "response" holds only the post-think answer.
    # If the model exhausted num_predict while still thinking, "response" is
    # empty — fall back to "thinking" so we don't lose the output entirely.
    output = data.get("response", "") or data.get("thinking", "")

    return {
        "output": output,
        "latency_total_s": round(t1 - t0, 3),
        "time_to_first_token_s": round(first_ns / 1e9, 3) if first_ns else None,
        "tokens_in": prompt_eval,
        "tokens_out": eval_count,
        "tokens_per_sec": tps,
        "cost_usd": 0.0,
    }


def run_claude(model, prompt, _host):
    """Call Anthropic Messages API. Returns dict of result+metrics."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY for the claude backend.")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 2048,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    t0 = time.time()
    r = requests.post(url, headers=headers, json=payload, timeout=600)
    t1 = time.time()
    r.raise_for_status()
    data = r.json()

    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage", {})
    tin = usage.get("input_tokens")
    tout = usage.get("output_tokens")

    cost = 0.0
    if model in CLAUDE_PRICES and tin is not None and tout is not None:
        pin, pout = CLAUDE_PRICES[model]
        cost = round((tin / 1e6) * pin + (tout / 1e6) * pout, 6)

    elapsed = t1 - t0
    tps = round(tout / elapsed, 2) if tout and elapsed else None

    return {
        "output": text,
        "latency_total_s": round(elapsed, 3),
        "time_to_first_token_s": None,  # not measured (non-streaming)
        "tokens_in": tin,
        "tokens_out": tout,
        "tokens_per_sec": tps,
        "cost_usd": cost,
    }


BACKENDS = {"ollama": run_ollama, "claude": run_claude}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=BACKENDS.keys())
    ap.add_argument("--model", required=True, help="e.g. qwen2.5-coder:7b or claude-haiku-4-5-20251001")
    ap.add_argument("--hw", required=True, help="hardware label: rtx3060 | m1 | pi5 | api")
    ap.add_argument("--host", default="http://localhost:11434", help="Ollama host")
    args = ap.parse_args()

    run_name = f"{slugify(args.model)}__{args.hw}"
    out_dir = OUTPUTS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_tasks()
    if not tasks:
        sys.exit("No tasks found under ./tasks/<category>/*.md")

    backend_fn = BACKENDS[args.backend]
    vm_rate = VM_USD_PER_HOUR.get(args.hw, DEFAULT_VM_RATE)

    # Drop any previous rows for this run_name, then append fresh ones.
    existing = []
    if METRICS_FILE.exists():
        for line in METRICS_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("run_name") != run_name:
                    existing.append(row)

    new_rows = []
    print(f"Running {len(tasks)} tasks  |  model={args.model}  hw={args.hw}")
    for i, t in enumerate(tasks, 1):
        print(f"  [{i}/{len(tasks)}] {t['category']}/{t['name']} ...", end=" ", flush=True)
        ram_before = peak_ram_mb()
        try:
            res = backend_fn(args.model, t["prompt"], args.host)
            error = None
        except Exception as e:
            res = {"output": "", "latency_total_s": None, "time_to_first_token_s": None,
                   "tokens_in": None, "tokens_out": None, "tokens_per_sec": None, "cost_usd": 0.0}
            error = str(e)
            print(f"ERROR: {e}")
        ram_after = peak_ram_mb()

        # Save the raw output file (same filename in every run folder -> easy diff).
        out_path = out_dir / f"{t['category']}__{t['name']}.txt"
        out_path.write_text(res["output"], encoding="utf-8")

        # VM-time cost for local runs: hourly GPU rate prorated by wall-clock seconds.
        # For api runs this is 0 (Claude cost is in cost_usd already).
        vm_cost = None
        if vm_rate and res["latency_total_s"]:
            vm_cost = round((res["latency_total_s"] / 3600) * vm_rate, 6)

        row = {
            "run_name": run_name,
            "backend": args.backend,
            "model": args.model,
            "hardware": args.hw,
            "category": t["category"],
            "task": t["name"],
            "output_file": str(out_path.relative_to(ROOT)),
            "latency_total_s": res["latency_total_s"],
            "time_to_first_token_s": res["time_to_first_token_s"],
            "tokens_in": res["tokens_in"],
            "tokens_out": res["tokens_out"],
            "tokens_per_sec": res["tokens_per_sec"],
            "cost_usd": res["cost_usd"],
            "vm_cost_usd_est": vm_cost,
            "ram_used_mb_after": ram_after,
            "error": error,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        new_rows.append(row)
        if not error:
            print(f"{res['latency_total_s']}s  {res['tokens_per_sec']} tok/s")

    # Write merged metrics back.
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("w", encoding="utf-8") as f:
        for row in existing + new_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nDone. Outputs -> {out_dir}")
    print(f"Metrics -> {METRICS_FILE}")


if __name__ == "__main__":
    main()
