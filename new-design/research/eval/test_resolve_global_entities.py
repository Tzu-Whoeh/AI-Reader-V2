"""
回归测试:cross_chapter.resolve_global_entities 倒排索引重构等价性验证。

背景:原实现用 O(n^2) 两两比较所有局部实体的 name 集合交集来做并查集合并;
长篇全本(几百章 × 每章数十实体)下 n 可达数万,n^2 上亿次集合交集。
重构改用倒排索引(name -> 节点下标),只枚举"共享至少一个名字"的节点对,
这些对恰是可能 union 的全部对,不多不少 -> 输出与两两比较 byte 级等价。

本测试做两件事:
  1. 等价性:随机语料上,新实现的 (global_list, ambiguities) 与朴素 O(n^2)
     参考实现 byte 级一致(含 ambiguity 顺序与 overlap 列表内部顺序)。
  2. 性能:现实分布(大量不同人名、各自只在若干章复现)下应显著快于朴素实现。

参考实现 _naive_resolve 内联在本文件,作为 oracle,不依赖被测代码的旧版本。
运行:python3 test_resolve_global_entities.py
"""
import json, random, time, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "pipeline"))
import cross_chapter as CC


def _naive_resolve(chapters, ent_key, name_key="name", alias_key=None):
    """朴素 O(n^2) 参考实现 —— 复刻重构前的原始逻辑,作为正确性 oracle。"""
    def norm(s): return (s or "").strip()
    nodes=[]
    for ch_idx, ch in enumerate(chapters):
        for r in ch.get(ent_key, []):
            names=set([norm(r.get(name_key))])
            if alias_key and r.get(alias_key): names|={norm(a) for a in r[alias_key]}
            names={n for n in names if n}
            nodes.append({"chapter":ch_idx+1,"local_id":r["id"],"names":names,"raw":r})
    parent=list(range(len(nodes)))
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b): parent[find(a)]=find(b)
    ambiguities=[]
    for i in range(len(nodes)):
        for j in range(i+1,len(nodes)):
            inter=nodes[i]["names"] & nodes[j]["names"]
            if inter:
                exact = nodes[i]["raw"].get(name_key)==nodes[j]["raw"].get(name_key)
                union(i,j)
                if not exact:
                    ambiguities.append({
                        "reason":"仅通过别名/部分名称重叠归并,建议人工确认",
                        "chapterA":nodes[i]["chapter"],"nameA":nodes[i]["raw"].get(name_key),
                        "chapterB":nodes[j]["chapter"],"nameB":nodes[j]["raw"].get(name_key),
                        "overlap":list(inter)})
    groups=defaultdict(list)
    for i,n in enumerate(nodes): groups[find(i)].append(n)
    global_list=[]
    for gi,(root,members) in enumerate(groups.items(),1):
        allnames=set()
        for m in members: allnames|=m["names"]
        canon=sorted((m["raw"].get(name_key) for m in members), key=lambda s:-len(s or ""))[0]
        global_list.append({
            "global_id":gi,"canonical":canon,
            "all_names":sorted(allnames),
            "members":[{"chapter":m["chapter"],"local_id":m["local_id"]} for m in members]})
    return global_list, ambiguities


def _mk(nch, per, pool, seed):
    random.seed(seed)
    names=[f"角色{n:03d}" for n in range(pool)]
    chs=[]
    for c in range(nch):
        ch=[]
        for k in range(per):
            nm=random.choice(names); al=[]
            if random.random()<0.3: al.append(random.choice(names))
            ch.append({"id":k+1,"name":nm,"aliases":al,"role":random.choice(["队长","掌柜",""])})
        chs.append({"characters":ch})
    return chs


def test_equivalence():
    cases=[(5,5,8,1),(20,30,10,42),(40,25,50,7),(60,30,120,9)]
    for nch,per,pool,seed in cases:
        chs=_mk(nch,per,pool,seed)
        eg,ea=_naive_resolve(chs,"characters","name","aliases")
        ng,na=CC.resolve_global_entities(chs,"characters","name","aliases")
        assert json.dumps(eg,ensure_ascii=False)==json.dumps(ng,ensure_ascii=False), \
            f"global_list mismatch @ N={nch*per}"
        assert json.dumps(ea,ensure_ascii=False)==json.dumps(na,ensure_ascii=False), \
            f"ambiguities mismatch @ N={nch*per}"
        print(f"  [equiv] N={nch*per:5d} pool={pool:3d}  global+amb byte-identical  ✓")


def test_performance():
    # 现实分布:大量不同人名,各自只在若干章复现 -> 名字桶小 -> 倒排索引大幅省时。
    chs=_mk(200, 30, 400, 3)
    t=time.perf_counter(); _naive_resolve(chs,"characters","name","aliases"); to=time.perf_counter()-t
    t=time.perf_counter(); CC.resolve_global_entities(chs,"characters","name","aliases"); tn=time.perf_counter()-t
    print(f"  [perf]  N=6000 pool=400  naive={to*1000:.0f}ms  inverted={tn*1000:.0f}ms  speedup={to/tn:.1f}x")
    assert tn < to, "重构在现实分布下未带来加速"


if __name__=="__main__":
    print("cross_chapter 倒排索引重构 · 回归测试")
    test_equivalence()
    test_performance()
    print("ALL PASS ✓")
