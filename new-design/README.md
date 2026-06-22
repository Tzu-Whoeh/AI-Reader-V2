# 中文叙事文本分析框架 (Narrative Analysis)

面向中文叙事文本(网文/小说)的结构化分析框架,基于本地 Ollama 模型 `huihui_ai/Qwen3.6-abliterated:35b`。从原文抽取五个维度,归并成带跨维度引用的统一结构,并支持跨章节的全局实体归一与时间线缝合。

## 设计哲学:分而治之 + 确定性归并

不把多目标塞进一个大提示词(实测会严重相互干扰)。每个维度独立调用、各出 JSON;人物/物品/地点用两-pass(Pass1 识别 + Pass2 关系),Pass2 只引用 Pass1 的 id,机制上杜绝脑补;最后用**代码**归并(不过模型,避免二次幻觉),并解析跨维度引用。

## 目录结构

```
new-design/
├── README.md                  本文件
├── prompts/                   各维度提示词(含 {TEXT} 占位)
│   ├── 01_scene_splitting.txt
│   ├── 02_character_pass1_recognition.txt / 02_character_pass2_relations.txt
│   ├── 03_item_pass1_extraction.txt / 03_item_pass2_relations.txt
│   ├── 04_location_pass1_recognition.txt / 04_location_pass2_relations.txt
│   ├── 05_time_analysis.txt
│   ├── 06_event_pass1_parent.txt    章节级父事件(骨架,participants准)
│   └── 06_event_pass2_sub.txt       场景级子事件(细节,挂父)
├── pipeline/                  归并与跨章代码
│   ├── orchestrator.py        总编排:跑五维度 + 单章归并
│   ├── merge_core.py          章节内归并 + 跨维度 id 解析 + 锚点校验
│   ├── cross_chapter.py       跨章:全局实体归一 + 个人时间线缝合 + 同步点
│   ├── entity_normalize.py    脏人名归一(符号/错字/繁简/重名防误合)
│   ├── storage.py             三层产物落盘 + 路径契约
│   ├── aggregate.py           跨章按维度聚合,每维度一个全局文件
│   └── event_pipeline.py      两层事件抽取 + 两道校验 + 事件→地点推导
├── samples/full_run/          完整三层产物样例(见下)
│   └── global/visualization.html  全局可视化(浏览器打开)
├── docs/                      各维度详细说明
└── samples/                   真实运行结果样例
```

## 五个维度

| 维度 | Pass1 | Pass2 关系 |
|---|---|---|
| 场景 | 按叙事单元切分(type/location/锚点) | 单 pass |
| 人物 | 识别 + 共指(本名/绰号/自称) | 7类:social/kin/affective/event/allegiance/awareness/attitude |
| 物品 | 抽取 + 共指 + prop/set 分类 + owner | part_of(部件/容器)+ set_group(成套) |
| 地点 | 识别 + 共指 + 尺度分类(city/building/area/room) | containment/adjacency/movement/remote |
| 时间 | 时间表达式 + 双时间轴事件 | 叙述序/故事序 + 闪回 + participants + 绝对间隔 |
| 事件 | 两层:章节父事件(骨架) + 场景子事件(细节) | 中枢:连接人物/场景/地点/物品/时间 |

## 三层架构

1. **章节内**:五维度抽取,各出 JSON。
2. **归并层**(merge_core):四维度合并 + 跨维度 id 引用(物品 owner→人物 id、场景 location→地点 id)+ 三道校验(锚点/id引用/交通工具过滤)。
3. **跨章层**(cross_chapter + entity_normalize):全局实体归一(含脏人名处理)→ 个人时间线跨章缝合 → 跨人物同步点 → 歧义报告。

## 核心可靠性机制

- **锚点校验**:所有 mention/alias 必须逐字出现在原文,否则剔除并记录(根除内容幻觉)。
- **id 引用**:Pass2/跨章只能引用已存在的 id,无法凭空造实体。
- **绝对时间纪律**:只认原文字面时间,无明确日期一律 null,绝不推算。
- **歧义报告**:跨章/脏名合并中,非高置信的归并不擅自决定,全部进 ambiguities 供人工确认。

## 调用配置

模型 `huihui_ai/Qwen3.6-abliterated:35b`;`format:"json"`(必须);`num_ctx 8192`;`think:false`;`stream:false`;temperature:场景 0.15,其余 0.12。

## 运行

```bash
cd pipeline
# 默认直连 Ollama 127.0.0.1:11434;经平台调用时替换 orchestrator.py 的 call_model()
python3 orchestrator.py 你的文本.txt > result.json
```



## 事件中枢(两层模型)

事件是连接全部维度的中枢:一条事件 = 谁(人物)、哪一幕(场景)、何地(地点)、何时(时间)、用什么(物品)。采用两层抽取:

- **父事件(章节级)**:看全章抽骨架事件,participants 指代准确,带 scene_ref + anchor_text + story_order + is_flashback。
- **子事件(场景级)**:逐场景补细节动作,挂到父事件,从候选清单选 participants/items。

两道确定性校验(`pipeline/event_pipeline.py`):施事者承前省略时从父事件继承;子事件物品必须出现在其 anchor_text 句内,否则锚点剔除。事件→地点经 scene_ref→场景 location 推导。

设计推演见 `docs/07_event_hub_blueprint.md`,样例见 `samples/full_run/chNN/events_twolayer.json`。

## 三层产物结构

每次完整运行产出三层文件(见 `samples/full_run/`):

1. **原始 pass 层** `chNN/{dimension}_{pass}.json` — 每章每维度每个提示词的原始输出,单独存盘、可追溯。如 `ch01/character_pass2.json`(人物关系)、`ch01/item_pass1.json`(物品抽取)。
2. **章节归一层** `chNN/_merged.json` — 该章六个 pass 跨维度合并:挂关系(character_relations / location_relations / 物品 part_of+set_group)、跨维度 id 引用(物品 owner→人物、场景 location→地点)、三道校验。
3. **全局分维度层** `global/{dimension}.json` — 跨章归一后,每个维度一个全局文件:
   - `characters.json` 全局人物表 + 跨章关系(局部 id 映射为全局 id)+ 个人时间线 + 歧义报告
   - `items.json` / `locations.json`(含 containment 等关系)/ `timeline.json`(事件 + 同步点)/ `scenes.json`
   - `_index.json` 顶层索引(章节清单、各全局文件、统计、歧义计数)

落盘契约见 `pipeline/storage.py`,跨章聚合见 `pipeline/aggregate.py`。

## 全局可视化

`samples/full_run/global/visualization.html` — 单文件、数据内嵌,浏览器直接打开。档案卷宗风格,四个视图:

- **人物关系网**:力导向图,跨章人物高亮为枢纽节点,边按七类关系着色、带方向,medium 关系虚线;悬停看关系标签与人物别名。
- **个人时间线**:每个全局人物一行,事件卡片按"第N章·序号"跨章缝合排列,闪回卡片虚线框 + "回"角标。
- **地点层级**:containment 关系构成的空间包含树。
- **同步点**:多人共在事件,各人物时间线在此对齐。

## 已知局限

各维度 docs/ 有详述。要点:人物关系新增三类(allegiance/awareness/attitude)语义准但方向偶反转;物品 container 关系会过度标注;地点会误收交通工具(已后处理);绝对时间多为 null(文本特性);跨章实体归一靠名称+上下文,歧义进报告人工终裁。

---
*本框架由提示工程迭代 + 确定性后处理管道构成,强调"模型做判断、代码兜底校验、不确定项交人工"的工程原则。*
