#!/usr/bin/env python3
"""
Self-test — verify the whole pipeline works WITHOUT a GPU or API key.
Run this locally before renting the VM:

    python3 selftest.py

It does three things:
  1. Checks every task file loads and has a matching grader or rubric.
  2. Feeds known-correct reference answers through the auto-graders and
     confirms they PASS; feeds known-wrong answers and confirms they FAIL.
  3. Generates fake results + outputs, runs evaluate (--no-judge) and report,
     then cleans up. Confirms the scoring + report wiring is intact.

If it prints "ALL CHECKS PASSED", the code is sound and you only need a real
model + API key to run the actual benchmark.
"""
import importlib.util, json, sys, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).parent
TASKS = ROOT / "tasks"

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

ev = load_mod("ev", ROOT / "evaluate.py")

fails = []

# ---- 1. task coverage ----
print("== 1. Task coverage ==")
all_tasks = []
for cat in sorted(TASKS.iterdir()):
    if not cat.is_dir(): continue
    for md in sorted(cat.glob("*.md")):
        all_tasks.append((cat.name, md.stem))
        body = md.read_text(encoding="utf-8").strip()
        if not body:
            fails.append(f"empty task file: {md}")
print(f"   found {len(all_tasks)} task files")
for cat, task in all_tasks:
    has_auto = task in ev.AUTO
    has_rubric = task in ev.RUBRICS
    if not (has_auto or has_rubric):
        fails.append(f"no grader/rubric for {cat}/{task}")
    if cat in ("coding", "structured") and not has_auto:
        fails.append(f"{cat}/{task} should be auto-graded but isn't")
    if cat in ("reasoning", "text") and not has_rubric:
        fails.append(f"{cat}/{task} should have a rubric but doesn't")
print(f"   auto-graders: {len(ev.AUTO)}, rubrics: {len(ev.RUBRICS)}")

# ---- 2. graders pass good / fail bad ----
print("== 2. Auto-grader correctness ==")
good = {
"01_fizzbuzz":'```python\ndef solve(n):\n    r=[]\n    for i in range(1,n+1):\n        s=""\n        if i%3==0:s+="fizz"\n        if i%5==0:s+="buzz"\n        if i%7==0:s+="bang"\n        r.append(s or str(i))\n    return r\n```',
"02_palindrome":'```python\ndef is_palindrome(s):\n    c=[ch.lower() for ch in s if ch.isalnum()]\n    return c==c[::-1]\n```',
"03_bug_fix":'```python\ndef second_largest(nums):\n    u=sorted(set(nums))\n    return u[-2] if len(u)>=2 else None\n```',
"04_sql":'```sql\nSELECT c.country, COUNT(DISTINCT c.id) AS n, SUM(o.total_cents)/100.0 AS rev\nFROM customers c JOIN orders o ON o.customer_id=c.id\nWHERE o.created_at>=\'2025-01-01\' AND o.created_at<\'2026-01-01\'\nGROUP BY c.country ORDER BY rev DESC;\n```',
"05_lru_cache":'```python\nfrom collections import OrderedDict\nclass LRUCache:\n    def __init__(self,capacity):\n        self.cap=capacity; self.d=OrderedDict()\n    def get(self,key):\n        if key not in self.d: return -1\n        self.d.move_to_end(key); return self.d[key]\n    def put(self,key,value):\n        if key in self.d: self.d.move_to_end(key)\n        self.d[key]=value\n        if len(self.d)>self.cap: self.d.popitem(last=False)\n```',
"06_intervals":'```python\ndef merge(intervals):\n    if not intervals: return []\n    s=sorted(intervals,key=lambda x:x[0]); out=[list(s[0])]\n    for a,b in s[1:]:\n        if a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n        else: out.append([a,b])\n    return out\n```',
"07_parens":'```python\ndef generate(n):\n    res=[]\n    def bt(cur,o,c):\n        if len(cur)==2*n: res.append(cur); return\n        if o<n: bt(cur+"(",o+1,c)\n        if c<o: bt(cur+")",o,c+1)\n    bt("",0,0); return res\n```',
"01_json_basic":'{"name":"Artur","age":33,"skills":["C#","AWS","Postgres"],"remote":true}',
"02_classify":'[{"id":1,"label":"bug"},{"id":2,"label":"feature_request"},{"id":3,"label":"question"},{"id":4,"label":"bug"}]',
"03_csv":"city,country,population_millions\nTokyo,Japan,37\nDelhi,India,33\nSao Paulo,Brazil,22",
"04_nested_json":'{"order_id":"A-1007","customer":{"name":"Lena Roth","vip":true},"items":[{"sku":"KB-12","qty":2},{"sku":"MS-04","qty":1}],"total":149.97}',
"05_dependent_total":'{"items":[{"name":"notebook","price":2.50,"qty":3,"line_total":7.50},{"name":"pen","price":1.20,"qty":2,"line_total":2.40},{"name":"stapler","price":7.99,"qty":1,"line_total":7.99}],"grand_total":17.89}',
"06_yaml":'name: auth-api\nversion: 2\nport: 8080\nenv:\n  LOG_LEVEL: info\n  TIMEOUT: 30\ndepends_on:\n  - postgres\n  - redis',
"07_enum_schema":'{"username":"sam.vega","role":"editor","active":true,"login_count":12}',
}
for task, ans in good.items():
    res = ev.AUTO[task](ans)
    if res[0] is not True:
        fails.append(f"GOOD answer for {task} did not pass (got {res[0]}: {res[1]})")
print(f"   {len(good)} correct answers checked")

bad = {
"03_bug_fix":'```python\ndef second_largest(nums):\n    return sorted(nums)[-2]\n```',
"04_sql":'```sql\nSELECT c.country, COUNT(o.id) AS n, SUM(o.total_cents)/100.0 AS rev FROM orders o JOIN customers c ON o.customer_id=c.id WHERE EXTRACT(YEAR FROM o.created_at)=2025 GROUP BY c.country ORDER BY rev DESC;\n```',  # COUNT(o.id) bug
"02_classify":'[{"id":1,"label":"bug"},{"id":2,"label":"feature_request"},{"id":3,"label":"question"},{"id":4,"label":"feature_request"}]',
"05_dependent_total":'{"items":[{"name":"x","price":2.50,"qty":3,"line_total":7.50}],"grand_total":99.0}',
"06_yaml":'name: wrong\nversion: 2',
}
for task, ans in bad.items():
    res = ev.AUTO[task](ans)
    if res[0] is True:
        fails.append(f"BAD answer for {task} wrongly passed")
print(f"   {len(bad)} wrong answers checked (incl. the COUNT-orders SQL bug)")

# ---- 3. end-to-end evaluate + report on fake data ----
print("== 3. End-to-end evaluate + report (fake data) ==")
(ROOT/"metrics").mkdir(exist_ok=True)
rows=[]
for run,model in [("test-good__mock","mock-good")]:
    od = ROOT/"outputs"/run; od.mkdir(parents=True, exist_ok=True)
    for cat, task in all_tasks:
        ans = good.get(task, "placeholder answer for judged task")
        (od/f"{cat}__{task}.txt").write_text(ans, encoding="utf-8")
        rows.append({"run_name":run,"backend":"mock","model":model,"hardware":"mock",
            "category":cat,"task":task,"output_file":f"outputs/{run}/{cat}__{task}.txt",
            "latency_total_s":1.0,"time_to_first_token_s":0.1,"tokens_in":50,"tokens_out":120,
            "tokens_per_sec":60.0,"cost_usd":0.0,"vm_cost_usd_est":0.0002,
            "ram_used_mb_after":1000,"error":None,"ts":"test"})
(ROOT/"metrics"/"results.jsonl").write_text(
    "\n".join(json.dumps(r) for r in rows)+"\n", encoding="utf-8")

r1 = subprocess.run([sys.executable, str(ROOT/"evaluate.py"), "--no-judge"],
                    capture_output=True, text=True)
if r1.returncode != 0:
    fails.append(f"evaluate.py crashed: {r1.stderr[-300:]}")
elif not (ROOT/"metrics"/"scored.jsonl").exists():
    fails.append("evaluate.py did not produce scored.jsonl")
else:
    scored=[json.loads(l) for l in (ROOT/"metrics"/"scored.jsonl").read_text().splitlines() if l.strip()]
    auto_rows=[s for s in scored if not s.get("judge") and s["score"] is not None]
    passed=[s for s in auto_rows if s["score"]==1.0]
    print(f"   evaluate ran: {len(passed)}/{len(auto_rows)} auto-graded tasks passed on reference answers")
    if len(passed)!=len(auto_rows):
        for s in auto_rows:
            if s["score"]!=1.0:
                fails.append(f"reference answer failed grading: {s['task']} ({s['verdict']})")

r2 = subprocess.run([sys.executable, str(ROOT/"report.py")], capture_output=True, text=True)
if r2.returncode != 0:
    fails.append(f"report.py crashed: {r2.stderr[-300:]}")
elif not (ROOT/"report.html").exists():
    fails.append("report.py did not produce report.html")
else:
    print("   report.py produced report.html OK")

# cleanup
shutil.rmtree(ROOT/"outputs", ignore_errors=True)
for f in ["metrics/results.jsonl","metrics/scored.jsonl","report.html"]:
    (ROOT/f).unlink(missing_ok=True)
shutil.rmtree(ROOT/"__pycache__", ignore_errors=True)
print("   cleaned up test artifacts")

print()
if fails:
    print("CHECKS FAILED:")
    for f in fails: print("  -", f)
    sys.exit(1)
else:
    print("ALL CHECKS PASSED — pipeline is sound. Add a model + API key to run for real.")
