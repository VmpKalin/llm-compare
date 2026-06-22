# Local vs Cloud LLM Benchmark

Compare local models (via Ollama on a rented GPU) against Claude across four
task categories — coding, reasoning, text, structured output — measuring
**quality**, **speed**, and **cost** at the same time.

28 tasks (7 per category), mixed difficulty, including deliberate trap tasks
that test reliability (hallucination, intuitive-but-wrong answers).

---

## Quick start (TL;DR)

python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

    # 0. one-time: install deps + set key
    pip install -r requirements.txt
    cp .env.example .env          # then edit .env, paste your ANTHROPIC_API_KEY

    # 1. verify everything works WITHOUT a GPU or paid calls
    python3 selftest.py           # must print "ALL CHECKS PASSED"

    # 2. run models (local needs Ollama running; see below)
    python3 runner.py --backend ollama --model qwen3:32b       --hw rtx5090
    python3 runner.py --backend ollama --model gemma3:27b      --hw rtx5090
    python3 runner.py --backend ollama --model deepseek-r1:32b --hw rtx5090
    python3 runner.py --backend claude --model claude-haiku-4-5-20251001 --hw api
    python3 runner.py --backend claude --model claude-sonnet-4-6          --hw api

    # 3. score + report
    python3 evaluate.py
    python3 report.py             # open report.html

---

## Files
- `requirements.txt`  — Python deps (requests, psutil, PyYAML)
- `.env.example`      — copy to `.env`, holds your ANTHROPIC_API_KEY
- `selftest.py`       — offline check that the whole pipeline works (no GPU/key)
- `setup_vm.sh`       — one-shot prep for a fresh Ubuntu+GPU VM
- `runner.py`         — runs all 28 tasks for ONE model, records metrics
- `evaluate.py`       — scores outputs (auto for code/structured, judge for the rest)
- `report.py`         — builds report.html
- `tasks/`            — the 28 task prompts, grouped by category
- `outputs/`          — model answers (created at runtime)
- `metrics/`          — results.jsonl + scored.jsonl (created at runtime)

## How keys are loaded
Both runner.py and evaluate.py auto-load a `.env` file in this folder (no
library needed). You can also just `export ANTHROPIC_API_KEY=sk-...` instead.
The key is needed for: the two Claude runs, and the LLM-as-judge scoring of
reasoning/text tasks. Coding/structured scoring needs no key.

---

## Running locally vs on a rented VM

### Local (if you already have Ollama + a capable GPU)
    ollama serve                       # in one terminal
    ollama pull qwen3:32b              # etc.
Then run the commands in Quick start.

### Rented VM (recommended: RunPod RTX 5090, ~$1/hr)
1. Create a Pod: clean Ubuntu image, 32GB-VRAM 5090, Container disk ~30GB,
   Network volume (persistent, mounted at /workspace) ~80GB. Add your SSH key.
2. SSH in, copy this folder over (scp or git), then:

       cd llm-benchmark
       export OLLAMA_MODELS=/workspace/ollama   # keep models on the persistent volume
       chmod +x setup_vm.sh && ./setup_vm.sh    # installs Ollama, pulls 3 models, deps
       cp .env.example .env && nano .env        # paste ANTHROPIC_API_KEY

3. Run the 5 runner commands, then evaluate + report.
4. Download report.html (and outputs/ if you want raw answers), then DELETE the
   Pod and its volume so storage stops billing.

Whole benchmark runs in ~1-1.5h => under $2 of VM time.

---

## How scoring works (and why)
- **Coding + structured = AUTO.** The output is executed / parsed and checked
  against assertions or a schema. Objective pass/fail. No API key needed.
  The SQL grader even catches the common COUNT(orders) vs COUNT(DISTINCT
  customers) mistake.
- **Reasoning + text = JUDGE.** No binary truth, so Claude (Sonnet) rates 1-5
  against a per-task rubric with the known correct answer. Rows are flagged
  `judge=true` — treat with a grain of salt since a Claude judge can favor
  Claude answers. Spot-check the trap tasks yourself.

Run `python3 selftest.py` any time — it proves the graders accept correct
answers and reject wrong ones, so a failing model is really the model's fault,
not a broken grader.

---

## Task catalog (28 tasks)
Difficulty: easy / medium / hard. [TRAP] = reliability test.

CODING (auto-graded)
- 01_fizzbuzz      easy   — multi-rule fizz/buzz/bang
- 02_palindrome    easy   — palindrome ignoring case/punctuation
- 03_bug_fix       medium — fix second-largest (dup/empty edges) [TRAP]
- 04_sql           medium — JOIN + GROUP BY + date filter + revenue
- 05_lru_cache     hard   — O(1) LRU cache
- 06_intervals     hard   — merge overlapping intervals
- 07_parens        hard   — generate all valid parentheses

REASONING (judged)
- 01_water_jugs    easy   — measure 4L with 3L/5L jugs
- 02_boxes         easy   — mislabeled boxes deduction
- 03_pipes         medium — fill/empty rates -> exactly 3h
- 04_monty_hall    medium — probability, switch = 2/3
- 05_bat_ball      medium — intuitive trap (5 cents, not 10) [TRAP]
- 06_fermi         hard   — piano tuners in Berlin, grade the chain
- 07_false_proof   hard   — find divide-by-zero in fake 2=1 proof

TEXT (judged)
- 01_summarize        easy   — 3 bullets under 15 words
- 02_extract_names    easy   — names + companies
- 03_rewrite_b1       easy   — simplify to B1 English
- 04_extract_contract medium — pull 5 contract fields
- 05_contradiction    medium — spot the contradiction
- 06_no_answer        medium — answer absent; must say so [TRAP: hallucination]
- 07_fix_facts        hard   — fix 3 errors, leave the correct one [TRAP]

STRUCTURED (auto-graded)
- 01_json_basic       easy   — parse to flat JSON
- 02_classify         medium — JSON array, fixed labels
- 03_csv              easy   — text to CSV with header
- 04_nested_json      medium — nested objects + array
- 05_dependent_total  hard   — totals must be computed correctly
- 06_yaml             medium — valid YAML, map + list
- 07_enum_schema      hard   — enum + lowercase + integer constraints

## Cost knobs (top of runner.py)
- `VM_USD_PER_HOUR`  — your GPU rental rate (rtx5090 default 0.69), prorated per task
- `CLAUDE_PRICES`    — per-Mtok rates (Haiku $1/$5, Sonnet $3/$15)

## Changing the model lineup
Edit the model list in setup_vm.sh (the pull loop) and just pass different
`--model` values to runner.py. Add tasks by dropping .md files into
tasks/<category>/ and adding a grader (evaluate.py AUTO dict) or rubric (RUBRICS).
