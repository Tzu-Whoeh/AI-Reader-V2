# 时间轴重构:事件级 → 场景级

承 timeline_sync 研究线。把跨章时间轴的【基本单位从事件改为场景】,事件降为场景下挂的一组。
本文件记录动机、新数据模型、与旧(事件级)的差异、真实数据验证。本次为 PR-A(场景级主干,不含跨章同时性;同时性见后续 PR-B)。

## 为什么改成场景级

做跨章同时性时撞到一个根本问题:doc4"就在华剑雄在得胜楼的时候,公寓里争论"——
这是【得胜楼场景 ↔ 公寓场景】的同时,不是某个具体动作和另一个动作同时。
硬塞到事件级会粒度错配(time_ref 说"争论",事件层却把争论拆成"反对/解释"等发言级事件,对不上)。

更深一层:
- 场景拆分是【成熟稳定的骨架】(loc/time 两条硬边界,prompt 迭代到 v8/v9);
  而事件 story_order 屡屡标错(ch01 长春闪回、doc3 惊闻遇刺位置错)。把时间轴建在稳的东西上更可靠。
- 同时性、闪回(往事回放)天然是【场景级】的;事件级处理它们是自找麻烦。

结论:**场景级时间轴为主干,事件作为场景下挂的一组**(事件 story_order 只在场景内有意义,不再承担跨章主干排序)。

## 新数据模型(cross_chapter.run 输出)

- `global_scenes`: 全局场景列表(取代旧 global_events)。每个场景:
  scene_uid / chapter / scene_index / title / type / location_global / location_name /
  global_participants(场景内所有事件参与者的全局并集) / is_flashback(场景级) / events(下挂事件,保留 story_order) / global_seq(全局时间序)。
- `character_timelines`: 每个全局人物 = 其出现的【场景序】子集投影(seq + global_seq + title + is_flashback)。
- `sync_points`: 被 >=2 全局人物共享的【场景】+ positions(各参与者场景线内 seq)。
- `ambiguities.timeline`: abs 一致性校验(场景级)。

## 关键逻辑

- 场景闪回判定 _scene_flashback:场景 type/title 含"往事/回忆/闪回/倒叙/回放" 则闪回;
  否则看下挂事件多数 is_flashback 则场景闪回。(doc4 场景2 type 标"现实叙述"但事件全闪回,靠事件聚合判出闪回。)
- 场景级总序:基准键 (章, 场景index);闪回场景靠共享人物锚到更早主线场景之后,无锚退基准键。
- 人物线 = 场景序子集投影:共享场景在多人物线 global_seq 自动一致。
- 场景地点归一:场景 location_ref 优先,否则由下挂事件 location_ref 推,经全局地点归一得 location_name。
- abs 校验场景级:取场景首事件 abs_interval 作场景时间锚,方向与场景顺序矛盾则报歧义(不改排序)。

## 真实数据验证(doc3 + doc4)

场景级时间轴:
- gseq1 ch1.s1 办公室接电话
- gseq2 ch1.s2 得胜楼密谈与调派秘书(得胜楼, 3事件)
- gseq3 ch1.s3 车内惊闻大使遇刺
- gseq4 ch2.s1 霞露公寓争论与告别(霞露公寓, 6事件)
- gseq5 ch2.s2 周雪萍的悲痛与回忆(闪回, 4事件) — 场景 type 标"现实叙述"但事件全闪回,正确判为 fb

- 得胜楼场景正确聚合 3 事件(送丝巾/回忆/调秘书)、地点归一"得胜楼"。
- 闪回场景(周雪萍回忆)靠事件聚合正确识别,排在最后。
- 华剑雄场景线 = 得胜楼 -> 车内惊闻(其参与场景的投影,顺序正确)。
- 旧事件级问题(doc3 惊闻遇刺 story_order 标错)不再污染主干:它只是场景内一个事件,场景归属对即可。

## 影响面 / 兼容

- 下游 graph_index / gap_scan 不依赖 cross_chapter 输出(章内层),不受影响。
- aggregate: timeline_doc 与 stats 由 global_events 改 global_scenes。
- 事件抽取 / 实体归一 / 各维度 pass 不变。

## 未尽(PR-B)

- 跨章同时性(time_ref):08 独立 pass 抽 names/places/local_scene_ref,cross_chapter 场景级匹配锚定。
  已在本地验证逻辑(用 local_scene_ref 把 doc4 公寓场景锚到 doc3 得胜楼场景,gseq 相邻),
  但新 08 prompt(带 local_scene_ref)需实跑验证后单独提 PR-B。
- abs 校验目前用场景首事件的 abs;场景级 abs 语义可再细化。
