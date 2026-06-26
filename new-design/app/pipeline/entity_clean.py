# -*- coding: utf-8 -*-
"""
封闭式人物清洗层 (entity_clean)。

动机:上游 pass1 抽取存在偶发结构性错误(abliterated 模型抖动),典型三类:
  1. 复合名: 一个 name 把多个不同的人并列写成一条(如"吴四宝和刘大壮");
  2. 描述当名: name 是情节/场景化短语而非人物称呼(如"吊着的女人""共党的区委书记");
  3. 描述性别名: aliases 里混入场景化指代短语。
这些脏数据会成为跨章归并的错误桥,导致 over-merge 超级簇。

经验证(详见会话记录):让 abliterated 做"开放式自检"会过度报告(76% 误报),
但做"封闭式二选一判定"准确率极高。故本层用封闭判定 + 多次投票抗抖动:
  - multi?      : 这个 name 是否把多人并列成一条
  - is_person?  : 这个词是否一个具体人物的称呼(否=描述短语)
仅对长度>=4 的 name/alias 送判(<=4 字几乎不可能是复合名/描述短语,免判直接留,省调用)。

判定结果按词缓存到 <novel_root>/.review_cache/clean.json,增量分析只判新词。
本层不使用任何关键词表 —— 完全由模型语义判断,避免过拟合到特定语料。
"""
import json, os, socket

MIN_LEN = 4          # 仅判 >=4 字的词
VOTES = 3            # 每词投票次数(抗 abliterated 单次采样抖动)
REQ_TIMEOUT = 30     # 单次请求硬超时(秒);兜底 socket 卡死

P_MULTI = ('判断下面这个"名字"是不是把两个或更多不同的人合并写成了一条'
           '(例如用"和""与""、"等把多人并列)。\n'
           '只输出 JSON,首字符{末字符},无其他文字。结构:{"multi":true}或{"multi":false}\n名字:「%s」')
P_PERSON = ('判断下面这个词是不是一个具体人物的称呼(本名/简称/绰号/尊称/头衔皆可)。\n'
            '如果它其实是一句情节描述或场景化短语(例如"吊着的女人""共党的区委书记""和武田一起来的那个人"),'
            '则不是人物称呼。\n'
            '只输出 JSON,首字符{末字符},无其他文字。结构:{"is_person":true}或{"is_person":false}\n词:「%s」')


def _vote(call_model, prompt, key, votes=VOTES):
    """对单个封闭判定投票:多数 True 才 True;全部失败返回 None(保守:不动该词)。"""
    yes = tot = 0
    for _ in range(votes):
        try:
            v = call_model(prompt, temperature=0.1, num_ctx=2048, timeout=REQ_TIMEOUT)
            b = v.get(key)
            if isinstance(b, bool):
                tot += 1
                yes += 1 if b else 0
        except Exception:
            continue
    if tot == 0:
        return None
    return yes * 2 > tot


def _cache_path(novel_root):
    d = os.path.join(novel_root, ".review_cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "clean.json")


def _load_cache(novel_root):
    if not novel_root:
        return {"multi": {}, "person": {}}
    p = _cache_path(novel_root)
    if os.path.exists(p):
        try:
            c = json.load(open(p, encoding="utf-8"))
            c.setdefault("multi", {}); c.setdefault("person", {})
            return c
        except Exception:
            pass
    return {"multi": {}, "person": {}}


def _save_cache(novel_root, cache):
    if not novel_root:
        return
    try:
        json.dump(cache, open(_cache_path(novel_root), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def clean_chapters(chapters, call_model, novel_root=None, log=print):
    """
    对各章 characters 做封闭式清洗,返回清洗后的 chapters(深层 list,结构不变)。
    - call_model: app.py 提供的 call_model(prompt, temperature, num_ctx, timeout, ...) -> dict
    - novel_root: 提供则启用磁盘缓存(增量分析复用已判结果)
    清洗动作:
      * name 命中 multi=True 或 is_person=False -> 丢弃该人物条目(留待后续重抽/人工);
      * alias 命中 is_person=False -> 从该人物 aliases 剔除。
    """
    socket.setdefaulttimeout(REQ_TIMEOUT + 5)  # connect 阶段兜底
    cache = _load_cache(novel_root)
    multi_dec, person_dec = cache["multi"], cache["person"]

    # 收集 >=4 字待判词
    names, aliases = set(), set()
    for ch in chapters:
        for c in ch.get("characters", []):
            nm = c.get("name")
            if nm and len(nm) >= MIN_LEN:
                names.add(nm)
            for a in (c.get("aliases") or []):
                if a and len(a) >= MIN_LEN:
                    aliases.add(a)
    new_names = [n for n in names if n not in multi_dec or n not in person_dec]
    new_alias = [a for a in aliases if a not in person_dec]
    log(f"[clean] 待判 name>={MIN_LEN}:{len(names)}(新{len(new_names)}) "
        f"alias>={MIN_LEN}:{len(aliases)}(新{len(new_alias)})")

    for i, nm in enumerate(sorted(new_names), 1):
        if nm not in multi_dec:
            multi_dec[nm] = _vote(call_model, P_MULTI % nm, "multi")
        if nm not in person_dec:
            person_dec[nm] = _vote(call_model, P_PERSON % nm, "is_person")
        if i % 10 == 0:
            _save_cache(novel_root, cache); log(f"[clean] name {i}/{len(new_names)}")
    _save_cache(novel_root, cache)
    for i, a in enumerate(sorted(new_alias), 1):
        if a not in person_dec:
            person_dec[a] = _vote(call_model, P_PERSON % a, "is_person")
        if i % 15 == 0:
            _save_cache(novel_root, cache); log(f"[clean] alias {i}/{len(new_alias)}")
    _save_cache(novel_root, cache)

    # 应用清洗
    dropped, removed_alias = 0, 0
    out = []
    for ch in chapters:
        newchars = []
        for c in ch.get("characters", []):
            nm = c.get("name")
            if nm and len(nm) >= MIN_LEN and (multi_dec.get(nm) is True or person_dec.get(nm) is False):
                dropped += 1
                continue
            al = c.get("aliases") or []
            newal = [a for a in al if not (len(a) >= MIN_LEN and person_dec.get(a) is False)]
            removed_alias += len(al) - len(newal)
            c = dict(c); c["aliases"] = newal
            newchars.append(c)
        ch2 = dict(ch); ch2["characters"] = newchars
        out.append(ch2)
    log(f"[clean] 丢弃复合/描述 name 条目={dropped} 剔除描述 alias={removed_alias}")
    return out
