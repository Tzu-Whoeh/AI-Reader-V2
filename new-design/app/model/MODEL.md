# 叙事分析 · 实体关系模型(领域核心模型)

> **单一事实源(SSOT)**。落盘、传输、修改、校验皆以本模型为依据。
> 权威定义在 `schema/*.schema.json`(JSON Schema,机器可校验);本文件是人读导读。
> 二者冲突以 JSON Schema 为准。

本模型据 `new-design/samples/` 真实产物归纳,**不臆造字段**。枚举值仅在样本与 prompt
确属有限集合时声明;模型自由生成的文本(如 `role`、`storyline`)标为自由文本。

---

## 0. 设计原则

1. **分层(实体层 / 时序层)**:人物·物品·地点是**实体**(谁/什么/哪里);场景·事件·时间是**时序结构**(何时/何序发生),单独建模,经引用挂接实体。
2. **两层 id(局部 / 全局)**:抽取在**章级**产出局部实体(`chapter`+`local_id`),跨章缝合产出**全局实体**(`global_id`),全局实体经 `members` 并查集回指其局部来源(provenance)。
3. **引用而非内联**:关系、场景、事件只持有对方 **id**(`*_ref` / `*_id` / `global_id`),不内联实体副本。单一事实源唯一。
4. **校验进模型**:每个跨实体引用、锚点字段、时间字段都带可声明的约束(必填性、id 存在性、anchor 逐字命中、绝对时间纪律)。规则见 §5。

---

## 1. 实体层(Entity Layer)

三类实体共享**基类形态**,各有专有字段。

### 1.1 基类 EntityBase(局部)
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | int | ✔ | 章内局部 id,章内唯一 |
| `name` | string | ✔ | 规范名 |
| `confidence` | enum`high|medium|low` | ✔ | 抽取置信度 |
| `note` | string | | 备注 |

### 1.2 Character(人物)
继承基类,增:`aliases: string[]`、`role: string`(**自由文本**,叙事角色描述,非枚举)、`evidence: string`(锚点,见 §5)。

### 1.3 Item(物品)
继承基类,增:`category: enum{prop, set}`、`mentions: string[]`、`function: string`、
以及**物品内部关系**(这是旧前端缺失的物品边来源):
`owner: string`、`owner_ref: int|object|null`(→Character.id)、`part_of: int|object|null`(→Item.id;实样为 `{whole_id, relation, confidence}`)、`set_group`(套组聚合,标量或 dict)。

### 1.4 Location(地点)
继承基类,增:`scale: enum{room, building, area, city}`、`mentions: string[]`。

### 1.5 全局实体 GlobalEntity(跨章缝合产物)
人/物/地三类同形:
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `global_id` | int | ✔ | 全局唯一 |
| `canonical` | string | ✔ | 全局规范名 |
| `all_names` | string[] | ✔ | 所有别名并集 |
| `members` | Member[] | ✔ | **provenance 并查集**:`{chapter:int, local_id:int}[]`,回指局部来源 |

---

## 2. 关系(Relation,实体层的边)

人物关系、地点关系同形(物品关系内联在 Item 字段,见 §1.3;未来可规整为统一 Relation)。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `from_id` / `to_id` | int | ✔ | 局部端点(→同类实体 `id`) |
| `from_global` / `to_global` | int | | 全局端点(→`global_id`),缝合后回填 |
| `relation_type` | enum | ✔ | 见下 |
| `label` | string | ✔ | 关系的自然语言描述 |
| `evidence` | string | ✔ | 锚点(§5) |
| `confidence` | enum`high|medium|low` | | |
| `chapter` | int | | 关系来源章 |

`relation_type` 枚举(据实):
- 人物:`social, kin, affective, attitude, event, awareness`
- 地点:`adjacency, containment, movement, remote`

---

## 3. 时序层(Temporal Layer)

### 3.1 Scene(场景)
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `index` | int | ✔ | 章内场景序 |
| `title` | string | ✔ | |
| `type` | enum{现实叙述, 回忆, 内心独白, 动作} | ✔ | 叙事类型 |
| `location` | string | | 地点名 |
| `location_ref` | object|null | | →Location:`{location_id, matched}` |
| `summary` | string | | |
| `start_text` / `end_text` | string | ✔ | **锚点**:场景首尾原文逐字片段(§5) |

### 3.2 Event(事件)— 时序层中枢
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_id` | int | ✔ | 全局事件 id(`timeline.json`) |
| `chapter` | int | ✔ | 来源章 |
| `desc` | string | ✔ | 事件描述 |
| `narrative_order` | int | ✔ | 叙述顺序(文本出现序) |
| `story_order` | int | ✔ | 故事顺序(时间真实序) |
| `is_flashback` | bool | ✔ | 是否倒叙 |
| `global_participants` | int[] | ✔ | →Character.global_id[] |
| `storyline` | string | | **自由文本**,所属故事线 |
| `abs_interval` | object|null | | **绝对时间区间**;不可靠时**必须 null**(§5 纪律) |

章级 event 用 `participants`(局部)替代 `global_participants`;无 `event_id`(缝合时赋 id)。

### 3.3 TimeExpression(时间表达式)
`{text: string, kind: enum{clock, duration, relative}, anchor: string}`。`anchor` 为锚点(§5)。

### 3.4 派生时序视图(只读,缝合产出)
- `character_timelines: { <global_id>: TimelineEntry[] }`,`TimelineEntry={seq,event_id,chapter,desc,is_flashback}`。
- `sync_points: {event_id, desc, global_participants, chapter}[]`,多人物线交汇点。
- `item_locations: { <item_global_id>: {chapter, location_id, location_name, via_scene}[] }`,物品↔地点时空映射(物品边的另一来源)。

---

## 4. 跨实体引用图(谁指向谁)

```
Relation.from_id/to_id        → Character.id / Location.id (同类)
Relation.from_global/to_global→ GlobalEntity.global_id
Item.owner_ref                → Character.id
Item.part_of.whole_id         → Item.id
Scene.location_ref.location_id → Location.id
Event.global_participants[]   → Character.global_id
TimelineEntry.event_id        → Event.event_id
GlobalEntity.members[]        → (chapter, local_id) 局部实体
```
**校验器据此图做引用完整性检查(§5 R2)。**

---

## 5. 校验(模型约束 + 规则声明)

JSON Schema 表达**结构约束**(类型/必填/枚举/形态);以下**跨字段规则**由校验器据本节实现(Schema 表达不了的)。对应 AGENT.md 四道防线:

- **R1 锚点逐字命中**:`evidence`、`start_text`、`end_text`、`anchor` 必须是原文的**逐字子串**(去空白后)。命中失败 → 该条目标记 `_anchor_miss`,不静默丢弃。
- **R2 引用完整性**:§4 所有 `*_id/*_ref/*_global` 非 null 时,被指 id 必须存在于对应集合;悬空引用 → `_dangling_ref`。
- **R3 绝对时间纪律**:`abs_interval` 仅在文本有**明确绝对时间依据**时填;无依据**必须 null**,禁止模型臆测推算。非 null 时须含可校验的区间结构。
- **R4 歧义留痕**:跨章同名/疑似同体但不能可靠缝合的,进 `ambiguities`(`{reason, chapterA, nameA, chapterB, nameB, overlap}`),**不硬合并**。
- **R5 provenance 自洽**:`GlobalEntity.members` 每个 `{chapter,local_id}` 必须能在该章局部实体中找到;全局 `all_names` ⊇ 各成员 `name/aliases` 并集。
- **R6 枚举闭合**:§1–3 标注的 enum 字段取值必须在声明集合内;自由文本字段(`role`/`storyline`/`label`)不做枚举校验。

校验产出统一形态 `ValidationReport`:`{ok: bool, errors: Issue[], warnings: Issue[]}`,`Issue={rule, path, detail}`。详见 `schema/validation_report.schema.json`。

---

## 6. 落盘 / 传输 / 修改的共同依据

- **落盘**:`output/chNN/*.json`(局部层)+ `output/global/*.json`(全局层+派生视图)。结构即本模型。
- **传输(API)**:端点响应是本模型实体/视图的**子集投影或组合**,不新增语义。图谱端点把实体映射为 `node`、关系映射为 `edge`(见 `schema/api_*.schema.json`)。
- **修改**:任何对产物的人工/程序修改,改后须过 §5 校验;`members`/引用变更须保持 R2/R5 自洽。
