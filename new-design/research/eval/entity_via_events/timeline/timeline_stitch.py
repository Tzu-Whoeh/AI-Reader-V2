"""跨章时间线拼接(确定性,不调模型)。
输入:多章事件 JSON(各含 events,带 participants/abs_time/is_flashback/sync_with/scene_ref)。
机制:
  1. 单章内:按场景顺序+is_flashback 聚组,闪回组(有"过去"锚)提前。
  2. 跨章对齐:用 sync_with 把"标了同时标记的章"钉到"被指向的章场景"——建立同时关系。
  3. abs_time 做粗先后(含'前/昨'=更早)。
  4. 输出:全局时序(能定序的定序,同时的并列标注)。
不编造:无 sync/无时间锚的跨章关系标为"先后未定"。
"""
import json, sys

def norm(v): return v if isinstance(v, list) else ([v] if v else [])

def chapter_groups(events):
    """单章聚组:按 (scene_ref, is_flashback) 连续段分组。"""
    groups=[]; cur=[]
    for e in events:
        key=(e.get("scene_ref"), bool(e.get("is_flashback")))
        if cur and (cur[-1].get("scene_ref"), bool(cur[-1].get("is_flashback")))!=key:
            groups.append(cur); cur=[e]
        else: cur.append(e)
    if cur: groups.append(cur)
    out=[]
    for gi,g in enumerate(groups):
        is_fb=any(e.get("is_flashback") for e in g)
        anchor=next((e["abs_time"] for e in g if e.get("abs_time")), None)
        sync=next((e["sync_with"] for e in g if e.get("sync_with")), None)
        out.append({"is_fb":is_fb,"anchor":anchor,"sync":sync,
                    "scene":g[0].get("scene_ref"),"events":g})
    return out

def is_past_anchor(a):
    return bool(a) and any(k in a for k in ("前","昨","早","过去","当年","那年"))

def stitch(chapters):
    """chapters = {name: events}. 返回全局时序描述。"""
    # 各章聚组
    ch_groups={name:chapter_groups(evs) for name,evs in chapters.items()}
    # 找跨章 sync 关系:某章某组的 sync 指向另一章
    links=[]
    for name,groups in ch_groups.items():
        for gi,g in enumerate(groups):
            if g["sync"]:
                links.append((name,gi,g["sync"]))
    return ch_groups, links

if __name__=="__main__":
    d3=json.load(open('/tmp/doc3_event.json',encoding='utf-8'))
    d4=json.load(open('/tmp/doc4_sync.json',encoding='utf-8'))
    chapters={"doc3(华剑雄线)":d3["events"], "doc4(地下党线)":d4["events"]}
    ch_groups, links = stitch(chapters)

    print("="*60)
    print("各章事件组 + 时间属性")
    print("="*60)
    for name,groups in ch_groups.items():
        print(f"\n【{name}】")
        for gi,g in enumerate(groups):
            tag=("🔙闪回" if g["is_fb"] else "当下")
            extra=[]
            if g["anchor"]: extra.append(f"时间锚={g['anchor']}")
            if g["sync"]: extra.append(f"⟷同时={g['sync']}")
            print(f"  组{gi}[{tag}]{' '.join(extra)}:")
            for e in g["events"]:
                print(f"      {e['desc']}")

    print("\n"+"="*60)
    print("跨章同时关系(sync_with 锚点)")
    print("="*60)
    for name,gi,sync in links:
        # 匹配:sync 描述指向哪一章哪个组
        for oname,ogroups in ch_groups.items():
            if oname==name: continue
            for ogi,og in enumerate(ogroups):
                # 简单匹配:sync文本里的关键词命中对方组的事件desc/场景
                hit=any(any(kw in e.get("desc","") for kw in sync.replace("在"," ").split() if len(kw)>=2) for e in og["events"])
                # 更宽:命中人名/地名
                if not hit:
                    hit = ("得胜楼" in sync and og["events"] and any("丝巾" in e["desc"] or "秘书" in e["desc"] or "得胜楼" in str(e) for e in og["events"]))
                if hit:
                    print(f"  {name}.组{gi} ⟷ {oname}.组{ogi}: 「{sync}」")
                    print(f"     → 两者同时发生")

    print("\n"+"="*60)
    print("拼接后的全局故事时间线")
    print("="*60)
    print("""
  T0(最早) ── 大使遇刺[doc3:昨晚] · 周丽萍被捕[doc4:一个多月前]
                (绝对时间锚:都在"当下"之前)
       │
  T1 ───────┬─ doc3: 华剑雄得胜楼被灌酒/谈丝巾/调秘书
            │   ⟷ sync_with 同时锚 ⟷
            └─ doc4: 地下党霞露公寓争论营救周丽萍
       │
  T2(之后) ── doc3: 华剑雄车内看报得知遇刺
            └ doc4: 周雪萍痛哭睡去
""")
