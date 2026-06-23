# 跨章同时性(time_ref):两段式 marker 触发 + 复核

承场景级时间轴(PR-A)。本文件记录跨章同时性锚的最终设计与真实验证。PR-B。

## 问题

平行蒙太奇:"就在华剑雄在得胜楼的时候,公寓里争论" —— 得胜楼(doc3)与公寓(doc4)同时,但
两事件【无共同人物】、且分属不同章。靠共享参与者锚连不上,需要专门的同时性机制。

## 演进(几轮实跑暴露的弯路,记此备查)

1. 最初想同章 concurrent_with(指向同章 story_order):跨章场景下失效(平行叙事常跨章)。
2. 改 time_ref 独立 pass 漫扫全章找同时性:doc4 准,但 doc3(无同时性)严重过度触发 + 幻觉
   (编造原文没有的"与此同时,在另一处……")。漫扫=逼模型在没有的地方硬找。
3. 最终(本 PR):【两段式 marker 触发】—— pass1 宽触发,pass2 精判复核纠正。

## 最终机制:两段式

- **pass1(06 事件抽取)**:新增 is_concurrency_marker 字段。事件抽取若遇"就在…的时候/与此同时"
  这类【平行同时引入句】,把它作为 is_concurrency_marker=true 的标记事件抽出(anchor=逐字那句)。
  prompt 强调:只标【此刻双方并行】的同时;【得知/回忆过去】的事(看报知昨晚遇刺)不是 marker。
- **触发**:event_pipeline.extract_time_refs 只在存在 marker 时才跑;无 marker 完全不跑(doc3 正叙→不触发)。
- **pass2(08 复核+抽取)**:对每个 marker 调 08。08 先【复核】这句是不是真同时:
  是 → 抽 names/places/local_scene_ref;不是(得知过去) → 返回空。pass2 是最终关卡,纠正 pass1 的宽触发。
- **cross_chapter(场景级)**:用 time_ref.names(为主)+places(加分) 匹配【其他章场景】;
  唯一最高分场景→把本章 local_scene_ref 场景锚到该场景旁;并列且同地点同人物簇→锚簇内最后;否则报歧义。

## 真实验证(doc3 + doc4,各 3 次)

- **doc4**:06 标 1 marker(就在华剑雄在得胜楼…的时候);08 复核确认真同时,
  抽出 {names:[华剑雄,丁墨村], places:[得胜楼], local_scene_ref:1}。✓
- **doc3**:06 宽触发(不同 run 标 1-3 个 marker,如约饭电话/送丝巾/惊闻遇刺,均非真同时);
  08 复核【全部否决返回 []】。最终 doc3 产出 0 条 time_ref,零污染。✓✓
  → 印证两段式鲁棒性:pass1 不需完美,pass2 复核兜底。
- **端到端 cross_chapter**:doc4 公寓争论场景被正确锚到 doc3 得胜楼场景(gseq 相邻),
  且排在"车内惊闻遇刺"之前 —— 平行蒙太奇时序正确。

## 数据/接线

- 06: +is_concurrency_marker 字段。
- 08: 重写为"复核+抽取"(输入 MARKER 句 + 场景清单 + 全章上下文)。
- event_pipeline.extract_time_refs: marker 触发,逐 marker 调 08,汇总 time_refs。
- app: merged += time_refs。
- cross_chapter: 场景级同时性匹配(find_local_scene 用 local_scene_ref) + 簇消歧 + concurrency_links。
- aggregate: timeline_doc += concurrency_links。

## 局限

- 06 marker 召回不稳定(不同 run 标的 marker 不同),靠 08 复核兜底,最终结果稳;但若 06 某次
  漏标真 marker,则该同时性会丢(漏报)。真 marker(就在…的时候 这类显式句)召回尚可,doc4 3/3 命中。
- 同时性锚目前把本章场景紧贴被复述场景之后(微增量);严格"同一时点"的并列表达可后续再细化。
