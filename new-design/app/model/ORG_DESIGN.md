# 组织(organization)维度 · 设计契约

新增一等实体维度,与人物/物品/地点平级。**本阶段(Option A)不依赖推理**:打通数据模型 + schema + 聚合 + API + 前端骨架,用造样本驱动;prompt 抽取等隧道恢复后在 research 验证再进主管线。

## 0. 红线对齐(Q2=3)
成员归属(membership)只有两类来源:
- **明说**(原文逐字可证「X 是 Y 的人」「X 隶属 Y」)→ 高置信,直接成边。
- **推断**(从行为/上下文猜)→ 进 `ambiguities`,**代码不擅自归并**,交人工。
本阶段不抽取,故 membership 由样本/未来 prompt 提供;聚合层只做确定性投影 + 锚点校验占位。

## 1. 数据形态

### 章级(_merged.json 新增)
```
"organizations": [
  {"id": 1, "name": "军统", "type": "情报机构",
   "aliases": ["军事委员会调查统计局"], "mentions": ["军统","军统局"],
   "desc": "国民政府情报机构"}
],
"org_memberships": [           # 章内明说的人物→组织归属
  {"character_id": 1, "org_id": 1, "role": "处长",
   "anchor_text": "华剑雄是军统的人", "confidence": "explicit"}
]
```
- `type` 自由文本(公司/军队/情报机构/帮派/政党…),不枚举死。
- membership 的 `character_id`/`org_id` 是**章内局部 id**,聚合时经 members 映射到全局。
- `source`: `explicit`(明说)| `inferred`(推断,进 ambiguities)。注:与 core.confidence(high/medium/low)是不同轴,故独立字段。

### 全局(output/global/organizations.json)
```
{
  "global_organizations": [ globalEntity ],     # 复用 core.schema globalEntity(global_id/canonical/all_names/members)
  "memberships": [                              # 跨章去重后的人物→组织(全局 id)
    {"character_global": 1, "org_global": 1, "role": "处长",
     "chapter": 3, "anchor_text": "...", "confidence": "explicit"}
  ],
  "relations": [ relation ],                    # 组织间关系(隶属/敌对…),复用 core relation
  "ambiguities": [ ambiguity ]                  # 推断 membership / 弱归并,交人工
}
```

## 2. 聚合(aggregate.py)
- `chapters[].organizations` 走 `cross_chapter.resolve_global_entities(..., "organizations","name","aliases")`——**复用现有并查集归一**,零新逻辑。
- membership:遍历各章 `org_memberships`,用 `loc2glob_char` + 新 `loc2glob_org` 映射到全局,`explicit` 进 `memberships`,`inferred` 进 `ambiguities`。跨章去重(character_global,org_global,role)。
- index counts 加 `global_organizations`。

## 3. API
- `/api/dimension/organizations` 自动可用(维度端点通用)。
- `/api/summary` counts 加 `organizations`。
- `/api/graph`:组织作为新节点类型 `organization`;边 `membership`(组织↔人物)+ 组织间 `org` 关系边。

## 4. 前端(本阶段骨架)
- 属性面板(SidePanel / Reader detail):人物显示「所属组织」;组织节点显示成员列表。
- 图谱:组织节点新类型 + 配色;membership 边。
- 顶栏 stat / summary 显示组织数。
- 不做独立"组织"视图(Q3=1,后续)。

## 5. 校验(validate.py / schema)
- 新 `global_organizations.schema.json`(仿 locations + memberships)。
- membership `anchor_text` 锚点校验占位(抽取接入后逐字校验,本阶段样本已合规)。

## 6. 不在本阶段
- prompt 抽取(`09_org_*.txt`)、真模型验证 → 等隧道,research 先验。
- 独立组织视图。