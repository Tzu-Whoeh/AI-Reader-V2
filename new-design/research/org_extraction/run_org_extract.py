#!/usr/bin/env python3
"""research: 在真实章节上跑 09_org_extraction,做锚点校验 + 多跑稳定性。不接主管线。"""
import urllib.request, json, sys, os

OLLAMA="http://127.0.0.1:18434"
MODEL="huihui_ai/Qwen3.6-abliterated:35b"
PROMPT=open("/tmp/orgx/09_org_extraction.txt",encoding="utf-8").read()
INPUT="/home/aiops/ai-reader-app/app/input/潜伏(2.0版)"

def call(text):
    body=json.dumps({"model":MODEL,"prompt":PROMPT.replace("{TEXT}",text),
        "stream":False,"format":"json","think":False,
        "options":{"temperature":0.12,"num_ctx":49152,"num_predict":4096}}).encode()
    req=urllib.request.Request(OLLAMA+"/api/generate",data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=300) as r:
        return json.loads(r.read())["response"]

def anchor_check(obj, text):
    """锚点校验:mentions / anchor_text 必须逐字出现在原文。返回 (ok_orgs, bad)。"""
    bad=[]
    for o in obj.get("organizations",[]):
        for m in o.get("mentions",[]):
            if m and m not in text: bad.append(("mention",o.get("name"),m))
    for mem in obj.get("memberships",[]):
        if mem.get("source")=="explicit":
            at=mem.get("anchor_text","")
            if not at or at not in text: bad.append(("anchor",mem.get("character_name"),at))
    return bad

def run_ch(ch, runs=3):
    p=os.path.join(INPUT,ch); text=open(p,encoding="utf-8").read()
    results=[]
    for i in range(runs):
        raw=call(text)
        try: obj=json.loads(raw)
        except Exception as e:
            print(f"  [{ch} run{i}] JSON parse FAIL: {e}"); results.append(None); continue
        bad=anchor_check(obj,text)
        orgs=[o.get("name") for o in obj.get("organizations",[])]
        mems=[(m.get("character_name"),m.get("org_id"),m.get("source")) for m in obj.get("memberships",[])]
        results.append({"orgs":orgs,"mems":mems,"bad":bad})
        print(f"  [{ch} run{i}] orgs={orgs} | memberships={len(mems)} (expl={sum(1 for m in mems if m[2]=='explicit')}) | anchor_bad={len(bad)}")
        if bad: print(f"      BAD anchors: {bad[:3]}")
    # stability: org set consistency across runs
    sets=[frozenset(r["orgs"]) for r in results if r]
    if sets:
        consistent = len(set(sets))==1
        print(f"  [{ch}] org-set 3跑一致: {consistent}  ({[sorted(s) for s in set(sets)]})")
    return results

if __name__=="__main__":
    chs=sys.argv[1:] or ["ch08.txt"]
    for ch in chs:
        print(f"=== {ch} ===")
        run_ch(ch, runs=3)