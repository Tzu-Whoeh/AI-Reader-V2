# research/agent_ambiguity · 受限 agent 歧义复核 spike

**状态:research spike,不接主流水线。** 目的:量化"用受限 agent 复核跨章归并歧义"是否值得做,数据说话再决定。

## 背景与假设

`cross_chapter.resolve_global_entities` 的策略:name/alias 有交集即 union,**完全同名=高置信,仅别名/部分重叠=记入 `ambiguities` 但仍然合并**。即:

- 当前代码对弱证据归并是"先合并,再标记交人工",**precision 有风险**:两个不同实体若共享一个通用别名(如"老板""他""老子"),会被错误合并,代码无法分辨。
- 真实样本印证:`特命全权大使` 与 `裴仁基` 因共享别名"裴仁基"被合并——这条**大概率对**(头衔指向该人);但同一机制也会把**真不同**的实体合并,代码看不出区别。

**这正是确定性代码做不到、而有原文证据的模型判断能做的事**——且决策面极小(同一/不同/存疑),符合 AGENT.md §0「模型做判断、代码兜底」。

## 受限 agent 的边界(关键:不是放开控制流)

不是让模型自由规划调工具。而是:

1. **证据由代码检索**(确定性),不由 agent 自己找:对每条歧义对,代码从原文捞出两个名字各自出现的句子(锚点校验过的)。
2. **agent 只做一次判断**:输入 = 两实体的名字/章/别名/各自原文证据;输出 = `same|different|unsure` + 一句话依据(必须引用证据,不得空想)。
3. **无多轮自我规划**、无写权限、无重抽。abliterated「爱顺 prompt 发挥」的风险被决策面收窄 + 证据约束压制。
4. **代码裁决落点**:
   - `same` → 确认现有合并(无操作)。
   - `different` → **拆回**(把被错误 union 的两节点分开,这是当前代码做不到的净增益)。
   - `unsure` → 仍进 `ambiguities` 交人工(不比现状差)。

## 评估

在 `samples/` + `research/test_chapters/` 的真实产物上,对每条歧义构造 (pair, 证据),三种方式对比:

- **baseline(现状)**:全部合并 + 标记,人工量 = 歧义条数。
- **agent 复核**:same/different/unsure 三分。
- **人工金标**(我先标一份小金标集):每条真值 same/different。

指标:
- **拆错挽回**:agent 判 different 且金标 different 的数(净增益,baseline=0)。
- **误拆**:agent 判 different 但金标 same 的数(新增风险,必须低)。
- **人工量下降**:baseline 歧义数 → agent 后剩余 unsure 数。
- **稳定性**:同输入跑 3 次,判定一致率(对 abliterated 尤其要看)。

## 决策门槛(预设,避免事后找补)

- 误拆率 > 5% → 否决(违背 precision 优先)。
- 稳定性 3 跑一致 < 5/6 → 否决(模型不稳,不可上)。
- 拆错挽回 + 人工量下降不显著(<30%)→ 不值得做,维持现状。
- 全过 → 提案做受限 agent,仍走 feature 分支 + 样本验证 + PR。

## 文件
- `reviewer.py`   受限 agent 复核器(纯逻辑 + 可注入 call_model)
- `evidence.py`   确定性证据检索(从原文 + merged 产物捞句子)
- `eval_harness.py`  跑对比 + 出指标;金标走 `goldset.json`
- `goldset.json`  人工金标(小集,先手标)