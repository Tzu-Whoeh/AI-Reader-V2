# 叙事分析 · 完整数据模型(事件中枢版)蓝图

本文是动手前的设计蓝图。核心变更:**事件(event)从时间维度的附属,提升为连接全部维度的一等中枢**。一个事件 = 谁(人物)、对谁/和谁、做了什么、在哪一幕(场景)、何地(地点)、何时(时间)、用什么(物品)的交汇记录。

---

## 一、六类实体 + 其字段(现状 → 目标)

图例:`✓` 已有 · `+` 本次新增 · `(推导)` 代码确定性推导,非模型产出

### 1. 场景 scene(章节内顺序单位)
```
index        ✓  场景序号
title        ✓
type         ✓  现实叙述|回忆|内心独白|动作
location     ✓  地点字符串(模型产出)
location_ref (推导) → 地点 id
summary      ✓
start_text   ✓  原文锚点(供事件/物品按位置归属)
end_text     ✓
```

### 2. 人物 character
```
id           ✓
name/aliases ✓  (共指归并)
role         ✓
confidence   ✓
evidence/note✓
scene_refs   +  出现在哪些场景 [index...](模型标 or 锚点推导)
```
人物关系(单列): `from_id,to_id,relation_type(7类),label,evidence,confidence`

### 3. 物品 item
```
id           ✓
name/mentions✓  (共指)
category     ✓  prop|set
owner        ✓  → owner_ref(推导)→ 人物 id
scene        ✓  出现的场景 index(已加)
location_refs(推导) → 经场景推出的地点 [{location_id,via_scene}]
part_of/set_group ✓ (物品间关系)
function/confidence/note ✓
```

### 4. 地点 location
```
id           ✓
name/mentions✓  (共指)
scale        ✓  city|building|area|room
confidence/note ✓
```
地点关系(单列): `from_id,to_id,relation_type(containment|adjacency|movement|remote),label,...`

### 5. 时间 time_expression
```
text  ✓  原文时间词(锚点)
kind  ✓  clock|duration|relative
anchor✓  所修饰事件简述
```

### 6. ★事件 event(中枢 —— 本次重点扩展)
```
event_id      +  全局/章内唯一编号(现在 events 无显式 id,靠下标)
desc          ✓  事件简述
participants  ✓  → 人物 id 数组(施事+受事)
scene_ref     +  发生在哪个场景 index(现字段名 scene_ref 但多为 null,要认真填)
location_ref  (推导) → 经 scene_ref → 场景.location_ref → 地点 id
items         +  涉及哪些物品 id 数组(全新)
narrative_order ✓ 叙述序
story_order     ✓ 故事序
is_flashback    ✓
storyline       ✓
abs_interval    ✓  绝对间隔(仅原文明确)
confidence      ✓
```

---

## 二、事件作为五维交汇点(目标能力)

补齐后,单条事件即可回答"谁/对谁/做什么/何幕/何地/何时/用什么":

```
                    ┌── participants ──→ 人物(谁,含施事/受事方向)
                    ├── scene_ref ─────→ 场景(哪一幕)
   event ───────────┤── (经场景) ───────→ 地点(何地)  [推导]
                    ├── items ─────────→ 物品(用什么)
                    └── story_order ───→ 时间(何时/先后)
```

示例(目标):
```json
{"event_id": 12, "desc": "武田用烙铁刑讯女人",
 "participants": [2, 6],            // 武田(施)、无名女人(受)
 "scene_ref": 4,                    // 刑讯室一幕
 "location_ref": {"location_id": 4},// (推导)地下刑讯室
 "items": [3, 8],                   // 三角烙铁、铁钳
 "story_order": 5, "is_flashback": false}
```

---

## 三、关系的三个来源(回答"能推导出所有关系吗")

场景/事件挂接能推出**时空共现**,但关系有三个来源,互补缺一不可:

| 来源 | 推出什么 | 性质 |
|---|---|---|
| **事件中枢**(participants/scene/items/time) | 谁在何时何地和谁用什么做了什么 | 共现,有施受方向 |
| **各维度 Pass2** | 关系的语义类型(上下级/敌对/情感/包含...) | 有向、有类型 |
| **时间线** | 事件先后、因果、闪回 | 时序 |

**结论**:事件中枢能推出"共现型"关系(谁和谁有交集、物品在何地、谁在何时在场),但**关系的语义性质**(是朋友还是敌人)、**非共现的抽象关联**(知情度、远程亲属)、必须由 Pass2 直接标注。事件中枢 + Pass2 + 时间线三者合一,才是完整关系图。

---

## 四、需要的改动清单(实现时按此施工)

### 模型侧(提示词)
1. **时间 Pass**:`scene_ref` 认真填(给场景清单做参考,像物品那样);新增 `items` 字段(事件涉及的物品 id,需给物品清单);给每个 event 加显式 `event_id`。
2. **人物 Pass1**:加 `scene_refs`(可选,人物出现在哪些场景)。

### 代码侧(管道)
3. **merge_core**:加 `resolve_event_locations`(事件 scene_ref → 场景 location_ref → 事件 location_ref);事件的 participants/items 已是 id,做引用完整性校验。
4. **执行顺序**:场景 → 物品 Pass1(已依赖场景)→ 时间 Pass(依赖场景清单+物品清单)。即时间 Pass 要后置到物品之后。

### 依赖顺序(关键)
```
场景 ──┬─→ 物品Pass1(scene)
       ├─→ 人物Pass1(scene_refs)
       └─→ 时间Pass(scene_ref + items 引用物品清单)  ← 最后跑
```

---

## 五、待定/风险

- **事件→物品挂接的可靠性**:事件涉及哪些物品,模型可能漏标或多标。考虑用"事件 scene_ref == 物品 scene"做交叉补全(同场景的物品是该事件的候选物品)。
- **scene_ref 填充率**:之前 scene_ref 多为 null,需验证给了场景清单后填充率能上来。
- **事件 id 跨章**:章内 event_id + 章号 → 全局 event 唯一键,跨章缝合已有逻辑可复用。
- **是否值得**:事件中枢让数据模型更规范,但增加一次提示词复杂度。若 35b 在"事件同时挂场景+物品+人物"上不稳,可退回"只挂场景"的较简版本。

---

*事件中枢已按两层模型实现,见第六节。*


---

## 六、实现状态(已落地)

蓝图经验证后采用**两层事件模型**(章节父事件 + 场景子事件),而非单层。理由:纯逐场景抽取指代消解易错(丢全章上下文),纯章节级粒度太粗。两层结合 = 父事件定骨架(看全章,participants 准)+ 子事件补血肉(逐场景,细节全)。

### 已实现
- **父事件(章节级)**:`事件分析_Pass1_章节父事件.txt`。看全章抽骨架事件,带 `scene_ref` + `anchor_text`(锚点) + `participants`(从人物候选选,纯数字 id) + `story_order` + `is_flashback`。验证:participants 准确、锚点全命中、scene_ref 全填。
- **子事件(场景级)**:`事件分析_Pass2_场景子事件.txt`。逐场景补细节动作,挂 `parent`,从候选清单选 participants/items,带 `anchor_text`。
- **两道确定性校验**(`事件管道_event_pipeline.py`):
  - 施事者从父继承:子事件 participants 空 → 继承父事件 agent/participants(修复承前省略主语)
  - 物品锚点校验:子事件 items 必须出现在其 anchor_text 句内,否则剔除(修复物品误连)
- **事件→地点推导**:`resolve_event_locations` — 事件 scene_ref → 场景 location_ref → 事件 location_ref。验证 5/5。

### 调用代价
每章 1 次父事件 + N 次子事件(N=场景数)。比单层多,换来骨架准 + 细节全。

### id 格式
候选清单用**纯数字 id**(不加 C/I 前缀),避免模型照抄前缀导致连线值不是数字。

### 验证结果(文本B)
5 父事件 + 31 子事件,participants 全部填全(0 空缺)、物品锚点校验通过、事件位置推导 5/5。两个原始瑕疵(施事者漏标、物品误连)均修复。
