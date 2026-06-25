#!/usr/bin/env python3
"""对比 baseline vs agent 复核 vs 人工金标,出预设门槛指标 + 3 跑稳定性。

用法:
  python eval_harness.py --cross cross_chapter_result.json --input <input_dir> \
      --gold goldset.json [--runs 3] [--stub]
平台环境:默认调 OLLAMA_URL;--stub 用内置假模型自测流程。
"""
import json, argparse, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reviewer, evidence

def ollama_call(model, url):
    import urllib.request
    def _call(prompt):
        body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                           "format": "json", "think": False,
                           "options": {"temperature": 0.12, "num_ctx": 8192, "num_predict": 1024}}).encode()
        req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["response"]
    return _call

def stub_call(prompt):
    # 极简假模型:overlap 是通用泛称则判 different,否则 same。仅供流程自测。
    generic = ["他", "她", "它", "老板", "老子", "先生", "大人"]
    import re
    ov = re.search(r"共享:(.*)", prompt)
    text = ov.group(1) if ov else ""
    verdict = "different" if any(g in text for g in generic) else "same"
    # 摘证据里一句做引用(取 A 第一条)
    m = re.search(r"【A 的原文证据】\n- (.+)", prompt)
    quote = m.group(1) if m else ""
    return json.dumps({"verdict": verdict, "evidence_quote": quote, "reason": "stub"}, ensure_ascii=False)

def load_pairs(cross):
    d = json.load(open(cross, encoding="utf-8"))
    amb = d.get("ambiguities", {})
    pairs = []
    for kind in ("characters", "items", "locations"):
        for p in amb.get(kind, []):
            pairs.append({**p, "_kind": kind})
    return pairs

def pair_key(p):
    return (p.get("chapterA"), p.get("nameA"), p.get("chapterB"), p.get("nameB"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cross", required=True)
    ap.add_argument("--input", default="")
    ap.add_argument("--gold", default="goldset.json")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--model", default="huihui_ai/Qwen3.6-abliterated:35b")
    args = ap.parse_args()

    pairs = load_pairs(args.cross)
    ev_fn = evidence.make_evidence_fn(args.input) if args.input else (lambda p: {"A": [], "B": []})
    call = stub_call if args.stub else ollama_call(args.model, os.environ.get("OLLAMA_URL", "http://127.0.0.1:18434"))
    gold = {}
    if os.path.isfile(args.gold):
        for g in json.load(open(args.gold, encoding="utf-8")):
            gold[(g["chapterA"], g["nameA"], g["chapterB"], g["nameB"])] = g["truth"]

    runs = []
    for r in range(args.runs):
        res = reviewer.review_all(pairs, ev_fn, call)
        runs.append({pair_key(p): p["verdict"] for p in res})
        if r == 0: first = res

    # 稳定性:每条 pair 三跑是否一致
    stable = sum(1 for k in runs[0] if len({rn[k] for rn in runs}) == 1)
    total = len(pairs)

    # 用第一次跑算 baseline/agent 对比
    rescue = miss = unsure = 0
    for p in first:
        k = pair_key(p); v = p["verdict"]; t = gold.get(k)
        if v == "unsure": unsure += 1
        if t is not None:
            if v == "different" and t == "different": rescue += 1
            if v == "different" and t == "same": miss += 1

    print("=" * 56)
    print(f"歧义对总数(baseline 全部合并+标记,人工量={total}):{total}")
    print(f"agent 判定:same={sum(1 for p in first if p['verdict']=='same')} "
          f"different={sum(1 for p in first if p['verdict']=='different')} unsure={unsure}")
    print(f"人工量下降:{total} → {unsure}  ({0 if total==0 else round((total-unsure)/total*100)}%)")
    print(f"稳定性(3跑一致):{stable}/{total}")
    if gold:
        gold_diff = sum(1 for t in gold.values() if t == "different")
        print(f"金标覆盖:{len(gold)}/{total}  其中真 different={gold_diff}")
        print(f"拆错挽回(净增益,baseline=0):{rescue}")
        print(f"误拆(新增风险,门槛<5%):{miss}  "
              f"= {0 if len(gold)==0 else round(miss/len(gold)*100)}% of gold")
    else:
        print("(无金标,跳过 precision 指标 —— 先手标 goldset.json)")
    print("=" * 56)
    print("\n逐条:")
    for p in first:
        print(f"  [{p['verdict']:9s}] {p.get('nameA')}(ch{p.get('chapterA')}) ~ "
              f"{p.get('nameB')}(ch{p.get('chapterB')}) overlap={p.get('overlap')} :: {p.get('reason','')[:40]}")

if __name__ == "__main__":
    main()