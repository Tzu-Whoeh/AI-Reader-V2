# 事件抽取 story_order 改进 — doc4 实跑验证

记录 `06_event_pass1_parent.txt` 改写前后,在真实模型(35b)上对 `test_chapters/doc4.txt` 的对比。
目的:验证「强化 story_order 说明 + 加时间锚字段 + few-shot」是否真能修正多段闪回的时序标注。

## 背景:问题怎么暴露的

时间线同步研究中(见 timeline_sync/DESIGN.md),阶段一确定性重排在真实 ch01 上跑出闪回簇内部 3/15 逆序对。
离线策略实验(本目录 sort_experiment)证明:abs_interval 全空、narrative_order 与 story_order 完全平行,
下游确定性策略天花板极低 —— 根因在**事件抽取 prompt 没要求模型对闪回内部做时序推理**,模型直接把叙述序当故事序填。
故把优化上推到事件 prompt(阶段二)。

## 改写内容(06_event_pass1_parent.txt)

1. **强化 story_order 说明**:新增「怎么定」专段 —— narrative≠story、抓相对时序词(之前/当晚/期间/后来)作硬依据、
   回忆内部要继续排序、「去X前」必须早于「在X期间/离开X」、拿不准给相同值不硬猜。
2. **加时间锚字段**:narrative_order / abs_interval / confidence,格式契约沿用既有的 05_time_analysis.txt,不另造。
3. **few-shot**:一个多段回忆示例,演示「交情报 so=1 最前 / 遇刺 so=4 回忆内最晚 / 当下事件 so 最大」。

## 实跑设置(贴生产)

- 机器 wangcai → ollama 隧道(127.0.0.1:18434),模型 huihui_ai/Qwen3.6-abliterated:35b,temp 0.12,num_ctx 49152,format json,think false。
- 真依赖:先跑场景(27b)+人物 pass1(35b)生成 scene_list / char_cand,再用真依赖分别跑旧/新 prompt 事件抽取。
- doc4 结构:前半当下(霞露公寓密谈→离去→独哭),后半大段往事回放(周丽萍被捕来龙去脉,倒叙)。

## 结果对比

**旧 prompt(4 事件)**:全部 is_flashback=False,story_order=叙述序,narrative/abs/confidence 全空。
后半整段往事被压成一个「周雪萍痛哭回忆往事」(so=4)。**往事零拆解、零闪回识别** —— 病灶复现。

**新 prompt(10 事件)**:
- 往事簇 5 件(看电影被捕→掩护被捕→免职→三张情报→今夜处决)全部 is_flashback=True,story_order=1~5。
- 当下线 5 件(反对营救→宣布决定→愤然离去→老任离开→痛哭)is_flashback=False,story_order=6~10。
- abs_interval 开始产出:「一个多月前」「今天中午」(旧版全 null)。
- narrative_order 与 story_order 不再平行(往事 narr=6~10 / so=1~5),正确体现倒叙。

**对真值**:往事真值序(看电影被捕→掩护被捕→免职→三张情报→今夜处决)与新 prompt so=1~5 **完全一致**;当下线顺序亦正确。

## 局限 / 观察

- 新版「看电影被捕」「掩护被捕」拆两件且都含「被捕」,语义略重叠;「三张情报」合成一件,粒度比人工真值粗一档。
  按父事件「骨架级、宁粗不错」原则可接受,下游子事件层可再细分。
- 本验证为单章(doc4)单次跑,非多样本统计;few-shot 把 prompt 从 688B 扩到约 4.6KB,长输入下 35b 偶有格式漂移风险,
  本次未出现(exit 0,JSON 正常)。多章回归建议纳入后续。
- 生产 app.py 写死端口 11434,本机实际隧道在 18434(运行环境差异,本验证用 18434)。与 prompt 改动无关,记此备查。

## 结论

prompt 改写在真实 35b 上把「往事整段塌缩、零闪回识别」修成「往事正确拆解 + 闪回正确标注 + 内部时序与真值一致 + 时间锚开始产出」。
确认改 prompt(源头)是修 story_order 质量的正确层,优于下游确定性兜底。
