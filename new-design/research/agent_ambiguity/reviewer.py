#!/usr/bin/env python3
"""
受限 agent 歧义复核器(research spike,不接主流水线)。

设计要点(对齐 AGENT.md §0/§model):
- 决策面极小:对一条"被弱证据归并的实体对",只判 same|different|unsure。
- 证据由代码检索注入(见 evidence.py),agent 不自行找工具 —— 控制流仍在代码。
- 输出 JSON,依据必须引用证据;不引用证据的 different 判定降级为 unsure(抗 abliterated 顺嘴发挥)。
- call_model 可注入:平台环境替换为 wangcai→ollama 调用;测试可注入 stub。
"""
import json, re

REVIEW_PROMPT = """你在校对一部中文小说的实体归并结果。系统怀疑下面两个名字指向【同一个实体】,但证据较弱。
请只依据给出的【原文证据】判断,不要凭常识或想象补充。

名字A:{nameA}(出现于第{chA}章)
名字B:{nameB}(出现于第{chB}章)
它们被归并是因为共享:{overlap}

【A 的原文证据】
{evA}

【B 的原文证据】
{evB}

判断规则:
- same:证据显示二者是同一实体(如一个是另一个的头衔/别称/简称,且原文可印证)。
- different:证据显示是不同实体(如共享的是通用泛称"他/老板/老子"等,各自指向不同的人/物/地)。
- unsure:证据不足以判断。

只输出 JSON,不要任何多余文字:
{{"verdict":"same|different|unsure","evidence_quote":"<从上面证据里逐字摘一句支撑你判断的话>","reason":"<一句话依据>"}}"""

VALID = {"same", "different", "unsure"}

def _extract_json(text):
    if not text: return None
    m = re.search(r'\{.*\}', text, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

def review_pair(pair, evidence, call_model):
    """
    pair: {nameA, chA, nameB, chB, overlap:[...]}
    evidence: {"A":[句子...], "B":[句子...]}  由 evidence.py 提供(锚点过的原文句)
    call_model(prompt)->str
    返回: {verdict, evidence_quote, reason, _raw}
    """
    evA = "\n".join(f"- {s}" for s in evidence.get("A", [])[:8]) or "(无)"
    evB = "\n".join(f"- {s}" for s in evidence.get("B", [])[:8]) or "(无)"
    prompt = REVIEW_PROMPT.format(
        nameA=pair["nameA"], chA=pair.get("chapterA", pair.get("chA")),
        nameB=pair["nameB"], chB=pair.get("chapterB", pair.get("chB")),
        overlap="、".join(pair.get("overlap", [])),
        evA=evA, evB=evB)
    raw = call_model(prompt)
    obj = _extract_json(raw) or {}
    verdict = obj.get("verdict") if obj.get("verdict") in VALID else "unsure"
    quote = (obj.get("evidence_quote") or "").strip()

    # 抗幻觉兜底:different 必须有"逐字出现在证据里"的引用,否则降级 unsure。
    if verdict == "different":
        all_ev = " ".join(evidence.get("A", []) + evidence.get("B", []))
        if not quote or quote not in all_ev:
            verdict = "unsure"
            obj["reason"] = (obj.get("reason", "") + " [证据引用未逐字命中,降级 unsure]").strip()

    return {"verdict": verdict, "evidence_quote": quote,
            "reason": obj.get("reason", ""), "_raw": raw}

def review_all(ambiguities, evidence_for, call_model):
    """ambiguities: [pair...]; evidence_for(pair)->{"A":[],"B":[]}"""
    out = []
    for p in ambiguities:
        ev = evidence_for(p)
        r = review_pair(p, ev, call_model)
        out.append({**p, **r})
    return out