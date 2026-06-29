# SQLite 存储设计 · AI-Reader-V2(new-design)

> 设计文档。DDL 见同目录 `schema.sql`(已在 SQLite 3.45 实跑通过:建表/视图/触发器 + 标签读写/反查/完整性测试)。
> 数据模型权威来源:`app/model/schema/core.schema.json` 与 `global_*.schema.json`;本设计是其关系化映射。

## 1. 定位与边界(重要)

- **当前为设计产物(spec),不是已接入的运行时存储。** 系统运行时仍以
  `output/<slug>/global/*.json` + `chNN/_merged.json` 文件为**单一真相源**(NFR-2/NFR-4),
  只读后端 `readonly.py` 仍纯标准库读 JSON。
- 本库定位是**模型结果(只读副本)+ 人工标注层(可写)**的叠加视图:
  - **只读副本部分**:由导出器(未来 `export_sqlite.py`)从 `global/*.json` 生成,`source='model'`。
  - **可写人工层**(§9):人工的**评价 / 调整 / 补充**(标签、纠错、归并裁决、评分)写入
    `tag(source='human')` / `annotation` / `review`,`source='human'`。
  - 关键不变量:**重导出只 wipe+reload 模型行,绝不删人工行**(已实跑验证)。人工层叠加在模型结果之上。
- 人工裁决可经**回写器**(未来,功能 PR)合并回 `global/*.json`;在回写前,文件主存储只承载模型结果,
  四道防线语义不变。DB 因此既是只读分析副本,又是人工修订的暂存与叠加层,但**不取代文件主存储**。

> `sqlite3` 是 Python 标准库,故"接入"本身不破 NFR-2 零三方依赖红线;但**替换主存储**会改写
> 存储契约与原子提交语义,风险高,需专门评估。本设计刻意选"旁路副本 + 可写人工层"规避该风险。

## 2. 物理布局

- **一本小说一个 `.db`**:`novel.db`,与 `output/<slug>/` 一一对应、互相隔离。
  `novel` 表固定单行(`id=1`),存 slug/书名/stage/导出时间/schema 版本/源 commit。
- 不做"全库合一":隔离与文件方案一致,避免一本损坏波及全部;跨书聚合在导出层另做(可选汇总库)。
- `PRAGMA foreign_keys=ON` + `journal_mode=WAL`;表用 SQLite **STRICT**(3.37+)强类型,纯关联表用 `WITHOUT ROWID`。

## 3. 七维度 → 表的映射

| 维度 / 概念 | JSON 来源 | 表 |
|---|---|---|
| 人物/物品/地点/组织(全局实体) | `global_*.json` 的 `globalEntity` | `entity`(type 区分) |
| 实体全部名字 all_names | `globalEntity.all_names` | `entity_name` |
| provenance members(R5) | `globalEntity.members` | `entity_member` |
| 人物/地点/组织关系 | `relations`(`relation`) | `relation`(dimension 区分;item 边导出时并入) |
| 物品定位 | `items.json::item_locations` | `item_location` |
| 组织成员 | `organizations.json::memberships` | `org_membership` |
| 场景 | `scenes.json::chapters[].scenes` | `scene` + `scene_character` |
| **标签(场景/人物)** | `scene.tags.*` / 新增人物标签 | **`tag`(多态)** + `tag_catalog` |
| 事件(全局,一等节点) | `timeline.json::global_events` | `event` + `event_participant` |
| 个人时间线 | `character_timelines` | `character_timeline` |
| 多线交汇点 | `sync_points` | `sync_point` + `sync_point_participant` |
| 时间表达式 | `timeExpression` | `time_expression` |
| 绝对时间(R3) | `event.abs_interval` | `event.abs_start/abs_end/abs_granularity`(无依据为 NULL) |
| 歧义留痕(R4) | 各维度 `ambiguities` | `ambiguity` |

**两级 id 忠实保留**:全局 `entity.global_id`(维度内唯一,`UNIQUE(type,global_id)`);
章内局部 `(chapter, local_id)` 进 `entity_member`。关系/事件/成员一律用 `global_id` 互引,
与 JSON 的 `from_global`/`global_participants`/`character_global` 对齐。

## 4. 标签设计 ★(对应"给人物、场景加标签")

核心是一张**统一多态 `tag` 表**,而非给每类对象各开标签列。理由:标签种类会增长
(功能/动作已有,人物特质/阵营是新需求,未来可能给地点/物品/事件加),多态表一次到位、查询统一。

```
tag(target_type, target_id, kind, label, in_catalog, rank, source)
    target_type ∈ {scene, character, item, location, organization, event}
    target_id   → scene.id  或  entity.id(character 等)
    kind        场景: function | action      人物: trait | faction | role_tag | …(可扩展)
    in_catalog  1=候选清单内;0=清单外模型自造(对应 JSON 的 *_novel)
    rank        模型给出的重要性序(1 最重要)
    source      'model'=导出自 JSON;'human'=人工新增(不被重导出覆盖,见 §9)
    UNIQUE(target_type, target_id, kind, label)
```

- **场景标签**:`function`(功能,如 情报传递/冲突)+ `action`(动作,如 审讯/跟踪)。
  直接来自 `scene.tags.function|function_novel|action|action_novel`,清单外置 `in_catalog=0`。
- **人物标签**(新增能力):本库**结构上已支持**给人物打标签(`target_type='character'`)。
  注意:当前 JSON 管线**尚未产出**人物标签(人物只有自由文本 `role`)。本设计为人物标签预留了
  完整落点;真正生成人物标签需要在 pipeline 增一个人物标签 pass(类比场景的两段式),属后续功能 PR。
  在那之前,`tag` 表的 character 行可由 `role` 或组织成员等**确定性派生**填充(导出器可选)。
- **完整性**:SQLite 不支持条件外键,多态 `target_id` 的指向正确性由导出器保证;`schema.sql`
  另附**触发器**(`trg_tag_scene_fk`/`trg_tag_character_fk`)在手工写入时拦截悬空标签(已测试生效)。
- **候选清单** `tag_catalog`:存各 (target_type, kind) 的候选标签集,供前端筛选条与跨书清单扩充。

## 5. 可靠性信息不丢(对齐四道防线)

- **R1 锚点**:`relation.evidence` / `scene.start_text|end_text` / `org_membership.anchor_text`
  / `time_expression.anchor` 原样入库,可回 `chapter.raw_text` 逐字校验。
- **R3 绝对时间**:`event.abs_*` 三列,无可靠依据存 NULL(不推算)。
- **R4 歧义**:`ambiguity` 表整表承接各维度 `ambiguities`,不在导出时擅自合并。
- **R5 provenance**:`entity_member` 保留每个全局实体的章内来源 (chapter, local_id)。

## 6. 便捷视图(随 DDL 提供)

- `v_scene_tags`:场景 + 功能/动作标签(各自逗号串),对应前端 Scenes 卡片。
- `v_character_tags`:人物 + 其全部标签(`kind:label` 串)。
- `v_tag_scene_index`:按 (kind,label) 反查场景,对应 Scenes 的跨章标签筛选。

## 7. 典型查询示例

```sql
-- 含"审讯"动作的所有场景(跨章)
SELECT chapter, scene_index, title FROM v_tag_scene_index WHERE kind='action' AND label='审讯';

-- 某人物的全部标签
SELECT tags FROM v_character_tags WHERE canonical='余则成';

-- 出场最多的人物 Top 10(按 provenance 章数)
SELECT e.canonical, COUNT(DISTINCT m.chapter) chs
FROM entity e JOIN entity_member m ON m.entity_id=e.id
WHERE e.type='character' GROUP BY e.id ORDER BY chs DESC LIMIT 10;

-- 故事序事件流(非叙述序)
SELECT story_order, chapter, description, is_flashback FROM event ORDER BY story_order;
```

## 8. 可写人工标注层(评价 / 调整 / 补充)

让 DB 不只是只读副本,而能承接人工的**评价、调整、补充**,且与模型结果分层、可追溯、不被重导出冲掉。

### 8.1 分层原则(关键不变量)
- 每条标签有 `source`:`'model'`(导出自 JSON)/ `'human'`(人工新增)。
- **重导出幂等**:`global/*.json → DB` 时只 `DELETE ... WHERE source='model'` 再 reload,
  **绝不删 `source='human'` 行**。已实跑验证:重导出后人工标签存活。
- 合并展示时人工层优先(human overrides model),模型原值始终保留可回溯。
- 文件主存储在回写前只承载模型结果,四道防线语义不变。

### 8.2 三个写入点
- **`tag(source='human')`** —— 人工**补充标签**:给某场景/人物加一个模型没打的标签。一条 INSERT,
  受 `(target_type,target_id,kind,label)` 唯一约束防重、触发器防悬空。
- **`annotation`** —— 人工**自由标注 / 纠错建议 / 评分 / 存疑标记**(多态指向任意对象的任意字段):
  `kind ∈ {note, correction, rating, flag}`。不改原始字段,只叠加。例如"这个名字应为 X 非 Y"(correction)、
  给某场景质量打分(rating 1–5)、标记某关系存疑(flag)。
- **`review`** —— 人工对模型**判断**的结构化**裁决**:`subject ∈ {entity_merge, relation, ambiguity,
  org_membership, event, tag}`,`verdict ∈ {confirm, reject, merge, split, correct, defer}`,
  记 `original`(模型原值 JSON)+ `corrected`(修正值 JSON)+ `rationale` + `author` + `created_at` + `applied`。
  例如把一条 ambiguity 裁决为 merge、把某关系 label 由"同事"correct 为"上下级"。完全可追溯。

### 8.3 回写流向(回写器属后续功能 PR)
```
人工写入 DB(tag.human / annotation / review)
   └─ v_pending_reviews(applied=0 的裁决)
        └─ 回写器(future)→ 合并进 global/*.json(原子提交)→ review.applied=1
   前端亦可直接读 DB 人工层做"模型结果 + 人工修订"的叠加展示,无需先回写。
```
回写遵守现有原子提交(`commit_global`),不破坏断点续跑/防半成品语义。

### 8.4 这解决了什么(对应"用 DB 更容易评价调整补充")
- **改标签**:INSERT/DELETE 一行,而非读改写整个 `scenes.json`。
- **人工校正**:`annotation`/`review` 记裁决,不污染原始分析结果,带操作者与时间可审计。
- **增量补充**:新标注/裁决是 INSERT,不必重写 global 文件。
- **批量评价**:SQL 直接查"哪些场景没人工评分""哪些 ambiguity 未裁决"(`v_pending_reviews`)。

## 9. 已验证 / 未做

- **已验证**(Python sqlite3 3.45 实跑):全部建表/视图/触发器执行通过;场景标签 + 人物标签
  读写、按标签反查、多态外键触发器拦截悬空、(kind,label) 唯一约束 —— 均通过。
  **可写层亦实跑验证**:`tag.source` 模型/人工分层、重导出只删模型行而人工标签存活、
  `annotation`(纠错/评分)、`review`(裁决 + 原值/修正值/理由 + applied 标记)、
  `v_effective_tag`/`v_pending_reviews` 视图 —— 均通过。
- **`tools/export_sqlite.py` 已实现并实跑验证**(wangcai「潜伏」真实数据,207 章):
  导出 entity 1827 / relation 3447 / event 1927 / scene 447 / tag 1147 / membership 221 /
  ambiguity 3615,relation 悬空 0、event_participant 悬空 0;**幂等**(重导出计数不变)、
  **人工标签跨重导出存活**。据真实数据修正了 schema 两处:`relation_type` 增 `allegiance`;
  `story_order`/`narrative_order` 改 REAL(实数据用小数序保序,范围实测 -10..26)。
- **`tools/writeback_sqlite.py` 已实现并实跑验证**(wangcai「潜伏」global 副本):把 DB 人工层
  (`tag.source='human'` / `annotation` / 安全 `review`)**仅叠加**回 `scenes.json`(场景标签 → `s.tags`)
  与 `characters.json`(人物标签 → 新增 `tags` 字段;标注 → `_annotations` sidecar)。
  默认 **dry-run** 只出计划;`--apply` 才写盘,落盘前**逐文件备份** + 临时文件 `os.replace` 原子替换;
  应用后置安全 `review.applied=1`。**结构性裁决(entity_merge/split)不自动应用**(需重新聚合,非叠加可安全完成),
  记为 deferred 并在输出标注。实跑验证:dry-run 不动文件、apply 正确叠加+备份、**重复 apply 幂等(0 净改动)**、
  结构裁决正确 deferred。
- **未做(刻意留作后续功能,各需单独 PR)**:
  - pipeline 产出人物标签的 pass(本设计已为其预留落点);
  - 可选的跨书汇总库 / FTS5 全文检索(原文/摘要)扩展。

## 10. 与其它规格的关系

- 数据模型字段语义以 `app/model/MODEL.md` + `schema/core.schema.json` 为准;本设计是其关系化投影。
- 文件存储契约见 `spec/architecture/01_system_architecture.md` §4;本库为其旁路副本,不替代。
- 场景动作标签来自 `feat/scene-action-tags`(`s.tags.action`);人物标签为本设计新引入的扩展点。
