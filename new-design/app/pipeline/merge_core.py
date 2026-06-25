"""叙事分析归并核心:四主题 JSON -> 统一结构 + 跨维度 id 引用解析。纯确定性,不过模型。"""
import json, re

# ---------- 锚点校验 ----------
def anchor_clean(records, text, name_key, mention_keys):
    """剔除 mention/alias 中原文不存在的项,记录到 dropped。"""
    report=[]
    for r in records:
        for mk in mention_keys:
            if mk not in r: continue
            kept,dropped=[],[]
            for m in r[mk]:
                (kept if m in text else dropped).append(m)
            r[mk]=kept
            if dropped: report.append({"id":r.get("id"),"name":r.get(name_key),"key":mk,"dropped":dropped})
    return report

# ---------- 跨维度名称解析 ----------
def build_name_index(records, name_key="name", alias_key=None):
    """name/alias -> id 的查找表。长名优先(避免'武田'误配到别的)。"""
    idx=[]
    for r in records:
        names=[r.get(name_key,"")]
        if alias_key and r.get(alias_key): names+=list(r[alias_key])
        for n in names:
            if n: idx.append((n, r["id"]))
    idx.sort(key=lambda x:-len(x[0]))   # 长名优先
    return idx

def resolve(value, idx):
    """把一个字符串(如 owner='武田勇夫')解析成 id。返回 (id, matched_name) 或 (None,None)。"""
    if not value: return (None,None)
    for n,i in idx:
        if n==value: return (i,n)           # 精确优先
    for n,i in idx:
        if n and (n in value or value in n): return (i,n)  # 包含次之
    return (None,None)

# ---------- 场景兜底清洗(第二道防线;prompt 是第一道) ----------
# 切分元论证标志词:模型偶尔把"该不该这样分段"的自我辩论写进 summary。
# 这些是确定性的污染信号 —— 命中即在该词处截断 summary(只保留它之前的客观叙述)。
_SCENE_META_MARKERS=["根据核心原则","根据原则","本应合并","应合并为","应合并?","严格遵循",
    "考虑到原文结构","通常叙事单元","若严格","本应","故第","注:此处","注：此处"]
_SCENE_SUMMARY_MAX=120   # 客观摘要软上限;超出在句末截断

def _truncate_at_sentence(s, limit):
    """在 limit 内的最后一个句末标点处截断;找不到则硬截到 limit。"""
    if len(s)<=limit: return s
    head=s[:limit]
    cut=max(head.rfind("。"), head.rfind("!"), head.rfind("?"),
            head.rfind("！"), head.rfind("？"))
    return head[:cut+1] if cut>0 else head

def _strip_meta(sm):
    """确定性剥离元论证:命中标志词→截到最早命中前;去自问句尾。返回 (cleaned, hit_markers)。"""
    hits=[(sm.find(m), m) for m in _SCENE_META_MARKERS if m in sm]
    markers=sorted({m for _,m in hits})
    if hits:
        pos=min(p for p,_ in hits)
        sm=sm[:pos].rstrip().rstrip("，,；;").rstrip()
    if sm.rstrip().endswith("?") or sm.rstrip().endswith("？"):
        q=max(sm.rfind("。"), sm.rfind("！"), sm.rfind("!"))
        if q>0: sm=sm[:q+1]
    return sm, markers

def detect_scene_issues(scenes, text):
    """纯检测(不改写 summary):标出需重做的场景 + 锚点/歧义报告。
    返回 (redo_list, report)。redo_list=[{index, reason}],供上层调模型重做。
    重做是首选(保信息);确定性截断只在重做失败时由 apply_summary_fallback 兜底。"""
    report={"summary":[], "anchors":[], "ambiguities":[]}
    redo=[]
    prev_start=None
    for sc in scenes:
        idx=sc.get("index")
        sm=sc.get("summary") or ""
        reasons=[]
        if any(m in sm for m in _SCENE_META_MARKERS):
            reasons.append("混入切分元论证(讨论该不该合并/分段)")
        if sm.rstrip().endswith("?") or sm.rstrip().endswith("？"):
            reasons.append("以自问句结尾")
        if len(sm)>_SCENE_SUMMARY_MAX:
            reasons.append(f"超长(>{_SCENE_SUMMARY_MAX}字)")
        if reasons:
            redo.append({"index":idx,"reason":";".join(reasons),"orig_len":len(sm)})
            report["summary"].append({"index":idx,"issues":reasons,"orig_len":len(sm),"action":"待重做"})
        # 锚点缺失
        st=sc.get("start_text"); en=sc.get("end_text")
        miss=[k for k,v in (("start_text",st),("end_text",en)) if not v]
        if miss:
            report["anchors"].append({"index":idx,"missing":miss,"title":sc.get("title")})
        for k,v in (("start_text",st),("end_text",en)):
            if v and v not in text:
                report["anchors"].append({"index":idx,"key":k,"reason":"原文未找到","head":v[:20]})
        # 相邻场景 start_text 相同 → 交人工(不硬改)
        if st and prev_start and st==prev_start:
            report["ambiguities"].append({"index":idx,"reason":"start_text与上一场景相同,锚点存疑","start_text":st[:30]})
        prev_start=st
    return redo, report

def apply_summary_fallback(sc, text=None):
    """重做失败/不可用时的确定性兜底:剥离元论证 + 句末截断。就地改写 sc['summary']。"""
    sm=sc.get("summary") or ""
    sm, markers=_strip_meta(sm)
    if len(sm)>_SCENE_SUMMARY_MAX:
        sm=_truncate_at_sentence(sm, _SCENE_SUMMARY_MAX)
    sc["summary"]=sm
    sc["_summary_flagged"]=True
    return {"index":sc.get("index"),"reason":"重做失败→确定性兜底","markers":markers,"kept_len":len(sm)}

def derive_scene_tags(merged):
    """纯确定性派生场景基础标签(零模型):
      - narrative: 叙事类型(scene.type)
      - location:  场景地点(scene.location,去'未明')
      - characters: 该场景涉及人物名(由 parent_events[scene_ref==idx].participants 聚合 → 人物名)
    结果写入 sc['tags'](dict)。功能类标签(情报传递/冲突等)由后续模型 pass 另填,不在此处覆盖。"""
    id2name={c.get("id"):c.get("name") for c in merged.get("characters",[])}
    scene_chars={}
    for ev in merged.get("parent_events",[]):
        sref=ev.get("scene_ref")
        if sref is None: continue
        bucket=scene_chars.setdefault(sref, [])
        for p in (ev.get("participants") or []):
            if p not in bucket: bucket.append(p)
    for sc in merged.get("scenes",[]):
        idx=sc.get("index")
        chars=[id2name.get(p) for p in scene_chars.get(idx,[]) if id2name.get(p)]
        loc=sc.get("location")
        base={
            "narrative": sc.get("type") or None,
            "location": loc if (loc and loc!="未明") else None,
            "characters": chars,
        }
        existing=sc.get("tags") if isinstance(sc.get("tags"), dict) else {}
        existing.update({k:v for k,v in base.items() if v})
        sc["tags"]=existing
    return merged

# 功能标签候选清单(内置默认;C2b 将改为用户可在书库维护的动态清单)。
# 作用:注入 prompt 引导模型优先复用(跨章聚合);后处理用它判 in_catalog。
FUNCTION_TAG_CATALOG=[
    "情报传递","冲突","争论","抒情","铺垫","审问","调情","回忆","日常","谈判",
    "揭露","设伏","追逐","转折","决策","心理描写","悬念设置","重逢","告别","潜入",
]

def _bad_tag(t):
    """词形校验:非 2-5 字 / 含标点或虚词 → 判废。返回 True=废弃。"""
    if not isinstance(t,str): return True
    t=t.strip()
    if not (2<=len(t)<=5): return True
    if any(p in t for p in "，,。.；;：:！!？?“”\"'（）()【】[]、 \n"): return True
    if any(w in t for w in ("的","了","是","场景","推动","体现")): return True
    return False

def sanitize_function_tags(raw_scenes_tags, catalog=None):
    """校验模型返回的功能标签:词形过滤(废弃记 report)+ in_catalog 标注。
    raw_scenes_tags: [{index, function_tags:[...]}]。
    返回 {index: {tags:[...], novel:[...]}}, report。
    清单外的合法标签【保留】并记入 novel(不丢,留作 C2b 扩充清单的来源)。"""
    cat=set(catalog or FUNCTION_TAG_CATALOG)
    out={}; report={"dropped":[], "novel":[]}
    for item in (raw_scenes_tags or []):
        idx=item.get("index")
        kept=[]; novel=[]; seen=set()
        for t in (item.get("function_tags") or []):
            ts=t.strip() if isinstance(t,str) else t
            if _bad_tag(ts):
                report["dropped"].append({"index":idx,"tag":t}); continue
            if ts in seen: continue
            seen.add(ts); kept.append(ts)
            if ts not in cat:
                novel.append(ts); report["novel"].append({"index":idx,"tag":ts})
        out[idx]={"tags":kept[:5], "novel":novel}
    return out, report


    """物品 scene 字段 -> 场景 location_ref -> 物品 location_ref(确定性推导)。
    scene 可为 int 或 list。物品可经过多地点。"""
    scene_loc={}  # scene index -> location_id
    for sc in scenes:
        idx=sc.get("index")
        ref=sc.get("location_ref")
        if idx is not None and ref:
            scene_loc[idx]=ref["location_id"]
    for it in items:
        sv=it.get("scene")
        if sv is None: 
            it["location_refs"]=[]; continue
        scenes_of=sv if isinstance(sv,list) else [sv]
        locs=[]
        for s in scenes_of:
            lid=scene_loc.get(s)
            if lid is not None and lid not in [l["location_id"] for l in locs]:
                locs.append({"location_id":lid,"via_scene":s})
        it["location_refs"]=locs
    return items

_THINK_MARKERS=["修正","思考","让我","重新审视","重新扫描","判定为","不收录","让我们","应排除","candidate","*修正*","\n"]
def sanitize_items(items):
    """剔除模型抽风产生的脏物品:字段污染(思考写进name)、id重复、错误container关系。"""
    report=[]; seen=set(); clean=[]
    id2name={it.get("id"):it.get("name","") for it in items}  # 供container语义校验查whole名
    id2obj={it.get("id"):it for it in items}                   # 供container标志位校验查whole的is_container
    for it in items:
        name=it.get("name","")
        # 1) name 污染:超长或含思考标志词
        if len(name)>20 or any(m in name for m in _THINK_MARKERS):
            report.append({"reason":"name污染/超长","id":it.get("id"),"head":name[:25]}); continue
        # 2) mentions 清洗
        it["mentions"]=[m for m in it.get("mentions",[]) if isinstance(m,str) and len(m)<=20
                        and not any(k in m for k in _THINK_MARKERS)]
        # 3) 错误 container 关系:纯标志位校验 —— container 的 whole 必须被模型(Pass1)
        #    标为 is_container=True。判断"某物能否容纳别的物"交给读过原文的模型,
        #    代码只查标志位(不再维护 PLACE_WORDS/CONTAINER_WORDS 词表)。
        po=it.get("part_of")
        if po and po.get("relation")=="container":
            whole=id2obj.get(po.get("whole_id"))
            if not (whole and whole.get("is_container") is True):
                it["part_of"]=None  # whole 未被模型标为容器 → container 关系不成立
        # 4) id 去重(去污染后再去重,保留先出现的干净条目)
        if it.get("id") in seen:
            report.append({"reason":"id重复","id":it.get("id"),"name":name}); continue
        seen.add(it.get("id")); clean.append(it)
    return clean, report

def merge(text, scenes, characters, items, locations):
    items_clean, item_report=sanitize_items(items.get("items",[]))
    scene_list=scenes.get("scenes",[])
    scene_redo, scene_report=detect_scene_issues(scene_list, text)
    out={"scenes":scene_list,
         "characters":characters.get("characters",[]),
         "items":items_clean,
         "locations":locations.get("locations",[]),
         "_validation":{"anchors":[], "xref":[], "item_sanitize":item_report,
                        "scene_sanitize":scene_report, "scene_redo":scene_redo}}

    # 锚点校验各维度
    out["_validation"]["anchors"]+=anchor_clean(out["characters"], text, "name", ["aliases"])
    out["_validation"]["anchors"]+=anchor_clean(out["items"], text, "name", ["mentions"])
    out["_validation"]["anchors"]+=anchor_clean(out["locations"], text, "name", ["mentions"])

    # 索引
    char_idx=build_name_index(out["characters"],"name","aliases")
    loc_idx =build_name_index(out["locations"],"name","mentions")

    # 跨维度1: item.owner -> character id
    for it in out["items"]:
        cid,matched=resolve(it.get("owner",""), char_idx)
        if cid is not None:
            it["owner_ref"]={"character_id":cid,"matched":matched}
        elif it.get("owner"):
            out["_validation"]["xref"].append({"type":"item.owner未匹配","item":it.get("name"),"owner":it["owner"]})

    # 跨维度2: scene.location -> location id
    for sc in out["scenes"]:
        lid,matched=resolve(sc.get("location",""), loc_idx)
        if lid is not None:
            sc["location_ref"]={"location_id":lid,"matched":matched}
        elif sc.get("location") and sc.get("location")!="未明":
            out["_validation"]["xref"].append({"type":"scene.location未匹配","scene":sc.get("title"),"location":sc["location"]})

    resolve_item_locations(out["items"], out["scenes"])
    out["counts"]={k:len(out[k]) for k in("scenes","characters","items","locations")}
    return out
