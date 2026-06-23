# timeline_sync — 跨章时间线同步:诊断与设计

本文件沉淀「时间线同步」研究线的**诊断结论 + 目标设计 + 待定决策**。
配套代码在 `pipeline/cross_chapter.py`(`stitch_timelines` / `run`)与 `pipeline/aggregate.py`(`timeline` 全局文档)。
本轮只做研究/诊断,**未改代码**。落地分阶段,见末尾「实施路线」。

## 0. 一句话目标

把各章独立抽出的父事件,缝成**跨章、跨人物对齐的故事时间轴**:
非闪回事件按章内序铺骨架,闪回与平行事件靠「锚」拉回真实故事时刻。
原则不变:**代码确定性兜底、不引二次模型调用、歧义交人工**。

## 1. 现状数据流(已核实)

```
06_event_pass1_parent.txt(prompt)
  → 父事件字段: desc / anchor_text / scene_ref / participants / agent / story_order / is_flashback
event_pipeline.extract_parent_events → merged["parent_events"](逐章)
aggregate.aggregate → 把 parent_events 映射成 "events" 键传入 cross_chapter.run
cross_chapter.stitch_timelines → global_events / character_timelines / sync_points
aggregate → output/global/timeline.json
```

**已澄清的误判**:父事件 prompt 明确产出 `participants`(施事+受事都算),
`stitch_timelines` 读的就是 `participants` 键,二者对齐 —— **时间线不会大面积为空**。
(早期怀疑「participants 字段没接上导致时间线空」一项,核 prompt 后撤回。)

## 2. 诊断:三个问题

### B(核心)— 排序键作废了 story_order 的故事时间语义

```python
evs_sorted = sorted(evs, key=lambda x: (x["chapter"], x["story_order"] or 0))
```

- prompt 里 `story_order` 的语义已是「真实发生序(回忆/闪回给较小序号)」。
- 但排序**先按 chapter**,等于把闪回又拍回它被叙述的章 —— 故事时间序被叙述顺序覆盖。
  一段写在第 5 章、story_order 很小的闪回,本应排到时间线最前,却被 `chapter=5` 压在后面。
- 三个叠加 bug:
  1. **chapter 作第一键**,压制 story_order(闪回不归位的直接原因)。
  2. **story_order 章内局部、跨章不可比**:每章都从 1 递增,跨章直接比无意义。
  3. **abs_interval 完全没用**:有字面绝对时间的事件本应优先用它定位(呼应「绝对时间纪律」),目前忽略。

### A(增强)— 同步点语义弱、无交叉索引

- 现 `sync_points` 仅「单条事件 participants ≥ 2」= 共同在场标记。
- 没回填「该事件落在每个参与者个人线的第几格」,下游/前端拿到还得 O(n) 反查。
- 更关键:同步点目前只是**输出产物**,没被用作**重排的锚**(见 §3 目标)。

### C(兜底)— agent 漏读

- prompt 同时有 `participants` 和 `agent`;`stitch_timelines` 只读 `participants`。
- 若某事件模型只填 agent、漏填 participants(不规范输出),该事件从所有时间线漏掉。
- 边缘 robustness,非主 bug。

## 3. 目标设计:两段式「初排 → 锚接线」

### 段一:初排骨架(确定性,不依赖闪回判断)

全体父事件用 `(chapter, story_order)` 排出**不冲突全序**,作为底座。
保证任意两事件有确定先后,与「准确性优先、代码兜底」一致。
说明:此处 `story_order` 仅用于章内排序;跨章靠 chapter 兜底,**不跨章比较 story_order**(它章内局部)。

### 段二:锚接线(把骨架校正成故事时间)

用「锚」对齐跨章/跨人物,并把闪回拉回真实位置。**冲突时锚优先于 story_order**(本轮决策)。

**两类锚:**

1. **共享参与者锚**:≥2 个全局人物共享的事件 → 在这些人物各自时间线上必须是同一点。
   提供跨线对齐约束:同一事件在不同人物线的 seq 必须可互相映射。
2. **同时性锚**:原文显式同时标记(「与此同时 / 就在这时 / 同时 / 这时」等)把两个事件锚到同一时点,
   **即使无共享参与者** —— 能连接本无共同人物的平行事件(跨线对齐的强补充)。

**闪回归位**:闪回/冲突事件**服从锚的位置约束**(本轮决策:同步点为准),
被拉到锚点位置;story_order 仅在无锚约束时决定相对序。

**输出**:`sync_point` 回填 `positions: {global_id: seq}`,缝完时间线扫一遍即可(纯确定性)。

## 4. 待定决策(需拍板后才进实施)

### D1 — 同时性锚的数据来源 ★关键

「哪两个事件同时」当前 prompt 不产出。anchor_text 里虽可能含「与此同时」,但**指代哪个事件模型没标**。

- **路 A(后处理猜指代)**:扫 anchor_text 同时性词 + 靠邻接/位置猜指向。
  ✗ 违反 AGENT.md「不 regex 提取、不靠位置猜指代」,不稳,**不推荐**。
- **路 B(源头标注)★推荐**:父事件抽取加 `concurrent_with` 字段(指向同时发生的另一事件 id),
  让模型在能看全章时直接标出同时性关系。符合「在源头解决指代」(同 viewpoint 字段那次思路)。
  代价:改 `06_event_pass1_parent.txt` + 结构,需 `samples/` 样本验证,属**独立后续立项**。

**本轮结论**:推荐方向 = 路 B,但**先不改 prompt**;第一阶段先落地不依赖同时性锚的部分(见 §5)。

### D2 — 跨章 story_order 全局基准

每章 story_order 独立从 1 起。段二要把闪回跨章拉位时,需要一个全局故事时间基准。
本轮采用「主线锚定」隐式解决:非闪回事件按 `(chapter, story_order)` 铺主线,
闪回事件靠**锚(共享参与者 / 同时性)**接到主线对应位置,而非直接比较跨章 story_order 数值。
→ 不需要改 prompt 让 story_order 全局可比(违反逐章独立抽取架构,且违背「后处理兜底而非堆 prompt」)。

### D3 — abs_interval 的引入时机

有字面绝对时间的事件,理论上应作最硬锚(高于叙述序与同步点)。
本轮不纳入第一阶段,避免一次引入过多变量;留作 §5 阶段三,届时需定义 abs_interval 的可比格式与缺失回退。

## 5. 实施路线(分阶段,每阶段独立 PR + 样本验证)

- **阶段一(低风险,可先做)**:修排序键 + agent 兜底 + 同步点 positions 回填。
  - B 的 bug1:排序不再让 chapter 压制故事序(段一初排 + 闪回靠共享参与者锚归位)。
  - A:sync_point 回填 positions。
  - C:取参与者并入 agent。
  - 仅改 `cross_chapter.py`,纯确定性,不动 prompt。
- **阶段二(独立立项)**:同时性锚走路 B —— 加 `concurrent_with`,改父事件 prompt,`samples/` 验证。
- **阶段三(独立立项)**:引入 abs_interval 作绝对时间硬锚(D3)。

## 6. 验证基准

- 用 `research/test_chapters/` 四章 + 跨章组合(尤其含闪回/往事回放的章)。
- 验收点:闪回事件在个人线中的位置是否被拉回故事时间;共享事件在多人物线的 seq 是否一致可映射;
  sync_point.positions 是否与各 character_timelines 的 seq 对得上。
- 改任何排序/接线逻辑后,对照 `samples/full_run/` 的 timeline.json 结构契约。

## 7. 教训 / 原则锚定

- story_order 已含故事时间语义,问题在**下游排序键用错**,不是上游缺数据 —— 改前先核 prompt 输出契约。
- 跨章对齐优先**靠锚(结构关系)**而非**跨章比较局部序号**(局部序号跨章不可比)。
- 同时性 / 指代关系应**在源头(能看全章时)标注**,不在后处理靠位置猜(同 viewpoint 思路)。
- 分阶段落地:先做不改 prompt 的确定性修复,prompt 级改动单独立项 + 样本验证。
