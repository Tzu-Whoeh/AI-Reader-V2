"""事件流确定性处理(不调模型):
输入 = 模型抽的事件流(带 narrative_order/time_link/is_flashback/abs_time/participants)
1. 聚组:连续事件(continuous)合一组;flashback_in/gap/flashback_out 开新组。组内保持自然顺序。
2. 选主线人物:participants 里出现最多的人。
3. 闪回组归位:闪回组若有明确 abs_time 锚→可移动到较早位置;无锚→保持原叙述位置,仅标记 is_flashback。
   (不编造时序:无客观时间锚就不强行移动。)
4. 输出主线人物的事件流(组为单位)。
"""
from collections import Counter

def build_groups(events):
    """按 time_link 把事件聚成组。组内保持 narrative_order。"""
    evs = sorted(events, key=lambda e: e.get("narrative_order", 0))
    groups = []
    cur = []
    for e in evs:
        link = e.get("time_link", "continuous")
        # 这些 link 表示"与前一事件断开",开新组
        if cur and link in ("gap", "flashback_in", "flashback_out"):
            groups.append(cur)
            cur = [e]
        else:
            cur.append(e)
    if cur:
        groups.append(cur)
    # 组的属性:是否闪回组(组内多数 is_flashback)、组的绝对时间锚(组内第一个有 abs_time 的)
    out = []
    for gi, g in enumerate(groups):
        is_fb = sum(1 for e in g if e.get("is_flashback")) > len(g) / 2
        anchor = next((e.get("abs_time") for e in g if e.get("abs_time")), None)
        out.append({
            "group_id": gi,
            "is_flashback": is_fb,
            "abs_time": anchor,
            "narr_start": g[0].get("narrative_order"),
            "events": g,
        })
    return out

def select_mainline(events):
    """主线人物 = participants 里出现最多的人。"""
    c = Counter()
    for e in events:
        for p in e.get("participants", []):
            c[p] += 1
    return c.most_common(1)[0][0] if c else None

def story_stream(events):
    """产出按故事顺序的事件流(组为单位)。
    保守策略:当下组按 narrative_order;闪回组有 abs_time 锚才前移,否则原位标记。"""
    groups = build_groups(events)
    mainline = select_mainline(events)
    # 默认顺序 = 叙述顺序(组的 narr_start)
    # 闪回组若无 abs_time:留在原位(只标 flashback);有 abs_time:这里先只标注,实际跨事件定序需要时间解析,
    # 当前保守不强行重排(避免编造),仅输出"建议较早"的标记。
    ordered = sorted(groups, key=lambda g: g["narr_start"])
    return mainline, ordered

if __name__ == "__main__":
    import json, sys
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    events = data["events"] if "events" in data else data
    mainline, groups = story_stream(events)
    print(f"主线人物: {mainline}")
    print(f"事件组数: {len(groups)}\n")
    for g in groups:
        tag = "🔙闪回组" + (f"(锚:{g['abs_time']})" if g["abs_time"] else "(无时间锚,原位标记)") if g["is_flashback"] else "当下组"
        print(f"  组{g['group_id']} [{tag}] (叙述起点N{g['narr_start']}):")
        for e in g["events"]:
            mark = " ★主线在场" if mainline in e.get("participants", []) else ""
            print(f"      N{e.get('narrative_order')} {e['desc']} {('['+e['abs_time']+']') if e.get('abs_time') else ''}{mark}")
