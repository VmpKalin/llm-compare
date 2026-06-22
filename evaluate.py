#!/usr/bin/env python3
"""
Evaluate benchmark outputs.
===========================
Reads metrics/results.jsonl + the output files, scores each output,
writes metrics/scored.jsonl (results + a "score" 0..1 and "verdict").

Grading modes:
  * AUTO  -> coding + structured: run/parse the output, objective pass/fail.
  * JUDGE -> reasoning + text: Claude rates 1..5 against a rubric
             (needs ANTHROPIC_API_KEY). Marked judge=true (possible bias).

Usage:
  export ANTHROPIC_API_KEY=sk-...     # only needed for JUDGE scoring
  python3 evaluate.py                 # full
  python3 evaluate.py --no-judge      # auto tasks only
"""

import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None
try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

ROOT = Path(__file__).parent
METRICS = ROOT / "metrics" / "results.jsonl"
SCORED = ROOT / "metrics" / "scored.jsonl"
JUDGE_MODEL = "claude-sonnet-4-6"


def load_dotenv():
    """Minimal .env loader (no dependency)."""
    envf = ROOT / ".env"
    if not envf.exists():
        return
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


def extract_code(text):
    m = re.search(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def extract_json(text):
    t = re.sub(r"```(?:json)?", "", text).strip()
    for start in range(len(t)):
        if t[start] in "[{":
            for end in range(len(t), start, -1):
                try:
                    return json.loads(t[start:end])
                except Exception:
                    continue
    raise ValueError("no JSON found")


def run_py(code, harness):
    full = code + "\n\n" + harness
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(full)
        path = f.name
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=20)
        ok = r.returncode == 0 and "ASSERT_OK" in r.stdout
        return ok, (r.stdout + r.stderr).strip()[-250:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        os.unlink(path)


# ---------- CODING graders ----------

def g_fizzbuzz(out):
    h='''
exp=[]
for i in range(1,106):
    s=""
    if i%3==0:s+="fizz"
    if i%5==0:s+="buzz"
    if i%7==0:s+="bang"
    exp.append(s or str(i))
assert solve(105)==exp
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)

def g_palindrome(out):
    h='''
assert is_palindrome("A man, a plan, a canal: Panama") is True
assert is_palindrome("race a car") is False
assert is_palindrome("") is True
assert is_palindrome("No 'x' in Nixon") is True
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)

def g_bugfix(out):
    h='''
assert second_largest([4,1,3,2])==3
assert second_largest([5,5,5]) is None
assert second_largest([5,5,3])==3
assert second_largest([1]) is None
assert second_largest([]) is None
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)

def g_sql(out):
    sql=extract_code(out).lower()
    need=["group by","country","2025","order by","desc"]
    missing=[c for c in need if c not in sql]
    has_div="/100" in sql.replace(" ","") or "100.0" in sql
    # Must count DISTINCT customers, not rows/orders — a common subtle bug.
    norm=sql.replace(" ","")
    count_distinct=("count(distinctc." in norm or "count(distinctcustomer" in norm
                    or "count(distinctc.id" in norm)
    ok=not missing and has_div and count_distinct
    why="ok" if ok else f"missing={missing} div={has_div} count_distinct={count_distinct}"
    return ok,why

def g_lru(out):
    h='''
c=LRUCache(2)
c.put(1,1); c.put(2,2)
assert c.get(1)==1
c.put(3,3)
assert c.get(2)==-1
c.put(4,4)
assert c.get(1)==-1
assert c.get(3)==3
assert c.get(4)==4
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)

def g_intervals(out):
    h='''
def norm(x): return [list(p) for p in x]
assert norm(merge([[1,3],[2,6],[8,10],[15,18]]))==[[1,6],[8,10],[15,18]]
assert norm(merge([[1,4],[4,5]]))==[[1,5]]
assert norm(merge([[1,4],[2,3]]))==[[1,4]]
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)

def g_parens(out):
    h='''
r=generate(3)
assert sorted(r)==sorted(["((()))","(()())","(())()","()(())","()()()"])
assert sorted(generate(1))==["()"]
print("ASSERT_OK")
'''
    return run_py(extract_code(out),h)


# ---------- STRUCTURED graders ----------

def g_json_basic(out):
    try: d=extract_json(out)
    except Exception as e: return False,str(e)
    ok=(isinstance(d,dict) and isinstance(d.get("name"),str) and d.get("age")==33
        and isinstance(d.get("skills"),list) and len(d["skills"])==3 and d.get("remote") is True)
    return ok,("ok" if ok else f"got {d}")

def g_classify(out):
    try:
        d=extract_json(out); got={i["id"]:i["label"] for i in d}
    except Exception as e: return False,str(e)
    want={1:"bug",2:"feature_request",3:"question",4:"bug"}
    return got==want,("ok" if got==want else f"got {got}")

def g_csv(out):
    text=extract_code(out) if "```" in out else out.strip()
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    if not lines: return False,"empty"
    header_ok=lines[0].replace(" ","").lower()=="city,country,population_millions"
    body=lines[1:]
    ok=header_ok and len(body)==3 and all(len(l.split(","))==3 for l in body)
    return ok,("ok" if ok else f"header={header_ok} rows={len(body)}")

def g_nested_json(out):
    try: d=extract_json(out)
    except Exception as e: return False,str(e)
    try:
        ok=(d["customer"]["vip"] is True and d["customer"]["name"].strip()=="Lena Roth"
            and abs(d["total"]-149.97)<0.01 and len(d["items"])==2
            and {it["sku"]:it["qty"] for it in d["items"]}=={"KB-12":2,"MS-04":1})
    except Exception as e: return False,f"shape {e}"
    return ok,("ok" if ok else f"got {d}")

def g_dependent_total(out):
    try: d=extract_json(out)
    except Exception as e: return False,str(e)
    try:
        for it in d["items"]:
            if abs(it["line_total"]-it["price"]*it["qty"])>0.01:
                return False,f"line_total wrong: {it}"
        gt=sum(it["line_total"] for it in d["items"])
        ok=abs(d["grand_total"]-gt)<0.01 and abs(gt-17.89)<0.01
    except Exception as e: return False,f"shape {e}"
    return ok,("ok" if ok else f"grand_total={d.get('grand_total')} expected 17.89")

def g_yaml(out):
    if not HAVE_YAML: return None,"pyyaml not installed"
    text=re.sub(r"```(?:yaml)?","",out.strip()).strip()
    try:
        d=yaml.safe_load(text)
        ok=(d["name"]=="auth-api" and d["version"]==2 and d["port"]==8080
            and d["env"]["LOG_LEVEL"]=="info" and d["env"]["TIMEOUT"]==30
            and set(d["depends_on"])=={"postgres","redis"})
    except Exception as e: return False,f"invalid yaml/shape: {e}"
    return ok,("ok" if ok else f"got {d}")

def g_enum_schema(out):
    try: d=extract_json(out)
    except Exception as e: return False,str(e)
    try:
        u=d["username"]
        ok=(isinstance(u,str) and u==u.lower() and " " not in u
            and d["role"]=="editor" and d["active"] is True
            and isinstance(d["login_count"],int) and d["login_count"]==12)
    except Exception as e: return False,f"shape {e}"
    return ok,("ok" if ok else f"got {d}")


AUTO={
 "01_fizzbuzz":g_fizzbuzz,"02_palindrome":g_palindrome,"03_bug_fix":g_bugfix,
 "04_sql":g_sql,"05_lru_cache":g_lru,"06_intervals":g_intervals,"07_parens":g_parens,
 "01_json_basic":g_json_basic,"02_classify":g_classify,"03_csv":g_csv,
 "04_nested_json":g_nested_json,"05_dependent_total":g_dependent_total,
 "06_yaml":g_yaml,"07_enum_schema":g_enum_schema,
}


# ---------- JUDGE rubrics ----------

RUBRICS={
 "01_water_jugs":"Must give a valid step sequence ending with exactly 4 litres measured.",
 "02_boxes":"Correct: draw from the box labeled 'Apples & Oranges'. Reasoning must be sound.",
 "03_pipes":"Correct: 1/6 + 1/4 - 1/12 = 1/3 per hour, so exactly 3 hours (3h 0m).",
 "04_monty_hall":"Correct: switch. Switching wins 2/3, staying 1/3. Explanation must be sound.",
 "05_bat_ball":"Correct: ball = 0.05 euro (5 cents), bat = 1.05. Penalize the intuitive wrong answer 0.10.",
 "06_fermi":"No single right number. Grade the reasoning chain: population, pianos-per-person, tuning frequency, tuner workload, sane final estimate. Penalize missing steps or absurd arithmetic.",
 "07_false_proof":"Correct: dividing by (a-b) is invalid because a=b makes a-b=0 (division by zero). Must identify that step.",
 "01_summarize":"Exactly 3 bullets, each under ~15 words, faithful to source, no invented facts.",
 "02_extract_names":"Must list: Maria Schmidt - Novoferm, Tom Becker - SIG. BambooCard person unnamed (ok to omit/note).",
 "03_rewrite_b1":"Simple B1 English, short sentences, no idioms, all facts kept (complexity, successful migration, lower latency, higher throughput).",
 "04_extract_contract":"Must capture: Parties Acme GmbH & Nordwind AG; Effective 1 March 2025; Term 24 months; Notice 60 days; Fee 4,500 EUR.",
 "05_contradiction":"Must identify: A says nothing arrived on the weekend, but B says Hamburg signed Saturday (weekend).",
 "06_no_answer":"Correct answer is exactly 'Not stated in the text.' Revenue is NOT given. Penalize any invented number (hallucination test).",
 "07_fix_facts":"Three errors: water boils at 100C not 90; body has 206 bones not 106; capital of Australia is Canberra not Sydney. The light/sound statement is correct and must NOT be flagged.",
}


def judge(task,output):
    if requests is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return None,"judge skipped (no key/requests)"
    rubric=RUBRICS.get(task,"Rate overall correctness and quality.")
    prompt=(f"You are grading an LLM answer. Rubric: {rubric}\n\nANSWER:\n{output}\n\n"
            "Score 1-5 (5=fully correct & well done, 1=wrong/empty). "
            'Reply ONLY as JSON: {"score": <int>, "reason": "<short>"}')
    try:
        r=requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key":os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version":"2023-06-01","content-type":"application/json"},
            json={"model":JUDGE_MODEL,"max_tokens":300,"temperature":0,
                  "messages":[{"role":"user","content":prompt}]},timeout=120)
        r.raise_for_status()
        txt="".join(b.get("text","") for b in r.json()["content"] if b.get("type")=="text")
        d=extract_json(txt)
        return (d["score"]-1)/4.0,d.get("reason","")
    except Exception as e:
        return None,f"judge error: {e}"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--no-judge",action="store_true")
    args=ap.parse_args()
    if not METRICS.exists():
        sys.exit("No results.jsonl yet. Run runner.py first.")
    rows=[json.loads(l) for l in METRICS.read_text(encoding="utf-8").splitlines() if l.strip()]
    scored=[]
    for row in rows:
        out_path=ROOT/row["output_file"]
        output=out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        task=row["task"]
        if row.get("error"):
            row.update(score=0.0,verdict=f"run error: {row['error'][:80]}",judge=False)
        elif task in AUTO:
            sc,detail=AUTO[task](output)
            row.update(score=(1.0 if sc else 0.0) if sc is not None else None,verdict=detail,judge=False)
        elif not args.no_judge:
            sc,reason=judge(task,output)
            row.update(score=sc if sc is not None else 0.0,verdict=reason,judge=True)
        else:
            row.update(score=None,verdict="skipped",judge=False)
        scored.append(row)
        sc_disp=row["score"] if row["score"] is not None else "n/a"
        print(f"  {row['run_name']:26} {row['category']:11}/{task:20} -> {sc_disp}  ({str(row['verdict'])[:42]})")
    with SCORED.open("w",encoding="utf-8") as f:
        for r in scored: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    print(f"\nScored -> {SCORED}")


if __name__=="__main__":
    main()
