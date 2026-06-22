#!/usr/bin/env python3
"""
叙事文本分析 · 总编排
四个主题各自独立调用模型(各出 JSON),最后代码归并 + 跨维度 id 解析。

用法:
  python3 orchestrator.py <文本文件>
依赖同目录下的提示词文件:
  提示词1_场景拆分_V4.md (取其中提示词正文; 或直接用 scene 纯提示词文件)
  人物分析_Pass1_人物识别.txt / 人物分析_Pass2_关系标注.txt
  物品分析_Pass1_抽取共指分类.txt / 物品分析_Pass2_关系标注.txt
  地点分析_Pass1_地点识别.txt / 地点分析_Pass2_关系标注.txt
  merge_core.py
本脚本默认提示词文件是"纯提示词"(含 {TEXT} 占位),与各主题交付的 .txt 一致。
场景提示词请单独存为 scene_prompt.txt(从场景交付 md 里抽正文)。
"""
import json, sys, time, base64
sys.path.insert(0, ".")
import merge_core

MODEL = "huihui_ai/Qwen3.6-abliterated:35b"

# ===== 模型调用:默认直连 Ollama;经 ops 平台时替换本函数 =====
import urllib.request
def call_model(prompt, temperature=0.12, num_ctx=8192, timeout=300):
    body={"model":MODEL,"prompt":prompt,"stream":False,"think":False,"format":"json",
          "options":{"temperature":temperature,"num_ctx":num_ctx}}
    req=urllib.request.Request("http://127.0.0.1:11434/api/generate",
        data=json.dumps(body,ensure_ascii=False).encode(),
        headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])

VEHICLE_WORDS=("车","轿车","雪佛来","汽车")

def load(fn): return open(fn,encoding="utf-8").read()

def run_theme_2pass(text, p1_file, p2_file, list_key, items_key, listfmt):
    """通用两-pass: Pass1 抽取 -> Pass2 关系 -> 合并关系到条目。"""
    p1=call_model(load(p1_file).replace("{TEXT}",text))
    records=p1[items_key]
    listing="\n".join(listfmt(r) for r in records)
    p2=call_model(load(p2_file).replace(list_key,listing).replace("{TEXT}",text))
    return p1, p2.get("relations",[])

def analyze(text):
    # 1) 场景(单 pass)
    scenes=call_model(load("scene_prompt.txt").replace("{TEXT}",text), temperature=0.15)

    # 2) 人物(2 pass)
    chars_p1,char_rel=run_theme_2pass(text,
        "人物分析_Pass1_人物识别.txt","人物分析_Pass2_关系标注.txt",
        "{CHARLIST}","characters",
        lambda c:f'  id={c["id"]} name="{c["name"]}" role="{c.get("role","")}"')
    chars_p1["relations"]=char_rel   # 人物关系挂在顶层

    # 3) 物品(2 pass)
    items_p1,item_rel=run_theme_2pass(text,
        "物品分析_Pass1_抽取共指分类.txt","物品分析_Pass2_关系标注.txt",
        "{ITEMLIST}","items",
        lambda it:f'  id={it["id"]} name="{it["name"]}" category={it["category"]}')
    # 合并物品关系(part_of/set_group)到条目
    relmap={r["id"]:r for r in item_rel}
    for it in items_p1["items"]:
        r=relmap.get(it["id"],{}); it["part_of"]=r.get("part_of"); it["set_group"]=r.get("set_group","")

    # 4) 地点(2 pass + 交通工具后处理)
    locs_p1,loc_rel=run_theme_2pass(text,
        "地点分析_Pass1_地点识别.txt","地点分析_Pass2_关系标注.txt",
        "{LOCLIST}","locations",
        lambda l:f'  id={l["id"]} name="{l["name"]}" scale={l["scale"]}')
    locs_p1["locations"]=[l for l in locs_p1["locations"]
                          if not any(w in l["name"] for w in VEHICLE_WORDS)]
    locs_p1["relations"]=loc_rel

    # 5) 归并 + 跨维度
    merged=merge_core.merge(text, scenes, chars_p1, items_p1, locs_p1)
    merged["character_relations"]=char_rel
    merged["location_relations"]=loc_rel
    return merged

if __name__=="__main__":
    text=open(sys.argv[1],encoding="utf-8").read()
    print(json.dumps(analyze(text),ensure_ascii=False,indent=2))
