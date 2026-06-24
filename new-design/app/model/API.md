# API 传输契约(导读)

> 权威定义在 `api_*.schema.json`;本文件是人读导读。
> **核心原则:API 响应是领域模型(`MODEL.md` / `core.schema.json`)的投影或组合,
> 不新增语义。** 经真实样本验证(见末尾)。

## 端点清单

| 端点 | schema | 说明 | 状态 |
|---|---|---|---|
| `GET /api/summary` | `api_summary` | 统计概览(counts + 章号) | 现有 |
| `GET /api/graph` | `api_graph` | 总览图 node/edge | 现有,**契约要求补全** |
| `GET /api/dimension/<name>` | `api_dimension` | 原样返回某 global 维度 | 现有 |
| `GET /api/node/<type>/<id>` | `api_node` | 单节点详情 + 原文出处 | 现有 |
| `GET /api/events` | `api_events` | 事件时序视图 | **新增** |

## node / edge 投影(`api_core`)

- **node.id 是复合字符串** `'<type>:<global_id>'`,前端按 `:` 切分。type ∈ {character, item, location, **event**}。
- **edge.kind** 标边来源:`char`(人物关系)`loc`(地点关系)`item`(物品边)`event`(事件参与/时序)。

## graph 边映射依据(server.py 落地时遵循)

| kind | 来源 | 映射 |
|---|---|---|
| `char` | `characters.relations` | `from_global`/`to_global` → character 节点 |
| `loc` | `locations.relations` | 同上 → location 节点 |
| `item` | `Item.owner_ref` / `part_of` / `set_group` + `item_locations` | owner_ref→character;part_of→item;set_group 同组互连;item_locations→location |
| `event` | `timeline.global_events` | 每事件一 event 节点;`global_participants` → character 边 |

**这是旧前端三个图谱缺口的修法**:物品孤立(无 item 边)、事件不进图、跨维度链接缺失,
全部由上表映射补上。本 PR 仅定契约,server.py 实现单独 PR。

## ⚠️ 落地时必修的真实 bug

旧 `build_graph` 判空用 `if r.get("from_global") and r.get("to_global")`。
**`global_id` 可能为 0**(falsy),会静默漏掉以 0 号实体为端点的边。
契约要求落地时改为 `is not None` 判空。已在 `api_graph.schema.json` 的 `$comment` 标注。

## /api/node 高亮注意

`occurrences[].term` 前端高亮时**必须正则转义**(`new RegExp` 直接用会被元字符破坏)。
web 骨架的 `SidePanel.jsx` 已实现 `escapeRe`,契约在此重申。

## 与领域模型的引用关系

```
api_summary       ← 各 global 维度 count
api_graph.node    ← GlobalEntity (character/item/location) + Event
api_graph.edge    ← Relation + Item内部引用 + item_locations + Event.global_participants
api_dimension     ← global_*.json 原样(= 领域模型落盘结构)
api_node          ← node_anchors → find_occurrences(原文反查)
api_events        ← timeline.global_events + sync_points + character_timelines
```

## 验证

`api_*` schema 已用真实样本模拟响应跑通(`jsonschema`,CI 侧):
- summary / graph / node / events 全 PASS。
- graph 用真实数据生成**含事件层的增强图**(66 节点 43 边),对比旧版(仅人物+地点边、
  物品孤立、无事件)确认契约补全了缺口。
