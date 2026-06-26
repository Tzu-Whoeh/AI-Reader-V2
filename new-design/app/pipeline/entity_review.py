# -*- coding: utf-8 -*-
"""
模型复核归并层 (resolve_with_llm_review)。
背景:cross_chapter.resolve_global_entities 采用策略①(仅 exact 本名自动并),
刻意保守 → 会欠合并(同一人的不同书写/称谓被拆开,如 丁主任/丁墨村/丁默村)。
本层消化①产出的 ambiguities:对"本名不同但名称/别名重叠"的候选对,
聚合双方身份画像(role/evidence)喂模型判定是否同指,same=True 才合并。
判断交给模型(语义),执行用确定性并查集 —— 不用人工表、不靠脆弱字面桥。
"""
import json, urllib.request, time
from collections import defaultdict

def _build_profiles(char_global, chapters):
    """每个全局节点 -> 身份画像(canonical, 别名, 各章 role/evidence 摘要)。"""
    # 索引: (chapter, local_id) -> raw character
    idx={}
    for ci,ch in enumerate(chapters, 1):
        for r in ch.get("characters",[]):
            idx[(ci, r["id"])]=r
    profiles={}
    for g in char_global:
        roles=[]; evs=[]
        for m in g["members"]:
            r=idx.get((m["chapter"], m["local_id"]))
            if not r: continue
            rl=(r.get("role") or "").strip()
            ev=(r.get("evidence") or "").strip()
            if rl and rl not in roles: roles.append(rl)
            if ev and ev not in evs: evs.append(ev)
        profiles[g["global_id"]]={
            "gid":g["global_id"],"canonical":g["canonical"],
            "names":g["all_names"],
            "roles":roles[:5],"evidence":evs[:4]}
    return profiles

def _candidate_pairs(char_global, ambiguities):
    """从 ambiguities 提取去重的全局节点对(gidA,gidB)。"""
    # 本名 -> 所属 gid 集合(①下同名只一个 gid,但 canonical 可能不等于 nameA)
    name2gid=defaultdict(set)
    for g in char_global:
        name2gid[g["canonical"]].add(g["global_id"])
        for nm in g["all_names"]:
            name2gid[nm].add(g["global_id"])
    pairs=set()
    for a in ambiguities:
        A,B=a.get("nameA"),a.get("nameB")
        if not A or not B or A==B: continue
        for ga in name2gid.get(A,()):
            for gb in name2gid.get(B,()):
                if ga!=gb: pairs.add(tuple(sorted([ga,gb])))
    return sorted(pairs)

PROMPT_HEAD = """你判断两个从不同章节抽取的人物画像是否指同一个真实人物。

判定规则:
- same=true 仅当:本名相同;或同音异写(丁墨村=丁默村);或一方是另一方的正式职务/称谓且身份画像一致(丁主任=丁墨村,同为76号负责人)。
- same=false 当:亲属/同僚/上下级是不同个体(周丽萍与周雪萍是姐妹→false;华剑雄是丁墨村下属→false);仅共享泛称("剑雄"作他人简称、"老家伙""那女人")而重叠→false;有任何不确定→false。

只输出一个 JSON 对象,首字符 {,末字符 }。禁止任何解释、思考、前后缀、markdown。
严格结构(不要增加字段、不要写理由):{"same":true}  或  {"same":false}

画像:
"""

def _format_one(pa, pb):
    return (f"A: 本名={pa['canonical']} 别名={('、'.join(pa['names'][:8]))}\n"
            f"   身份={('；'.join(pa['roles'])) or '(无)'}\n"
            f"   线索={('；'.join(pa['evidence'][:2])) or '(无)'}\n"
            f"B: 本名={pb['canonical']} 别名={('、'.join(pb['names'][:8]))}\n"
            f"   身份={('；'.join(pb['roles'])) or '(无)'}\n"
            f"   线索={('；'.join(pb['evidence'][:2])) or '(无)'}\n")

REQ_TIMEOUT = 30  # 单次请求硬超时(秒);兜底 socket 卡死(集成实测某些词触发长响应需此保护)

def _judge_pair(call_model, pa, pb, votes=3):
    """单对同指判定 + 多次投票抗抖动(abliterated 单次采样不稳)。多数 True 才 True。
    全部失败返回 False(保守:不并,符合 uncertain→不动 的纪律)。"""
    prompt=PROMPT_HEAD+_format_one(pa,pb)
    yes=tot=0
    for _ in range(votes):
        try:
            v=call_model(prompt, temperature=0.1, num_ctx=2048, timeout=REQ_TIMEOUT)
            same=v.get("same")
            if isinstance(same,bool):
                tot+=1
                if same: yes+=1
        except Exception:
            continue
    if tot==0: return False
    return yes*2 > tot

def _pair_cache_key(pa, pb):
    """缓存键:本名对(有序) + 双方画像指纹。画像(身份线索)变了则重判。"""
    import hashlib
    a=(pa["canonical"], tuple(pa.get("roles",[])))
    b=(pb["canonical"], tuple(pb.get("roles",[])))
    lo,hi=sorted([a,b])
    raw=repr(lo)+"||"+repr(hi)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

def resolve_with_llm_review(char_global, ambiguities, chapters, call_model,
                            votes=3, cache=None, log=print):
    """
    复核归并层。对①产出的"本名不同但重叠"候选对,喂模型判定同指,same=True 才合并。
    - call_model: app.py 的 call_model(prompt, temperature, num_ctx, timeout) -> dict
    - cache: 可选 dict {key: bool};传入则复用/写入(增量分析跨次复用判定)。
    返回 (new_global, decisions)。
    """
    import socket
    socket.setdefaulttimeout(REQ_TIMEOUT + 5)
    if cache is None: cache={}
    profiles=_build_profiles(char_global, chapters)
    pairs=_candidate_pairs(char_global, ambiguities)
    log(f"[review] 候选全局节点对: {len(pairs)} (逐对×{votes}票, 已缓存{len(cache)})")
    decisions={}
    for k,(ga,gb) in enumerate(pairs):
        ck=_pair_cache_key(profiles[ga], profiles[gb])
        if ck in cache:
            same=cache[ck]
        else:
            same=_judge_pair(call_model, profiles[ga], profiles[gb], votes=votes)
            cache[ck]=same
        decisions[(ga,gb)]=same
        if log and (k+1)%25==0: log(f"[review] {k+1}/{len(pairs)} done")
    gids=[g["global_id"] for g in char_global]
    parent={g:g for g in gids}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b): parent[find(a)]=find(b)
    merged_pairs=0
    for (ga,gb),same in decisions.items():
        if same: union(ga,gb); merged_pairs+=1
    groups=defaultdict(list)
    for g in char_global: groups[find(g["global_id"])].append(g)
    new_global=[]
    for ni,(root,gs) in enumerate(groups.items(),1):
        members=[]; allnames=set()
        for g in gs:
            members+=g["members"]; allnames|=set(g["all_names"])
        canon=sorted((g["canonical"] for g in gs), key=lambda s:(-len(s or ""), s or ""))[0]
        new_global.append({"global_id":ni,"canonical":canon,
            "all_names":sorted(allnames),"members":members})
    log(f"[review] same=True 对: {merged_pairs}; 节点 {len(char_global)} -> {len(new_global)}")
    return new_global, decisions
