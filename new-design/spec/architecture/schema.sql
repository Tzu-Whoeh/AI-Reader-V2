-- ============================================================================
-- AI-Reader-V2 · 分析结果 SQLite Schema (DDL)
-- ----------------------------------------------------------------------------
-- 用途:把 output/<slug>/global/*.json 的七维度分析结果映射为关系库,供 SQL 查询/
--      BI/导出。**当前为设计产物(spec)**,文件 JSON 仍是运行时单一真相源;本库定位
--      为旁路只读副本(见 spec/architecture/03_sqlite_storage.md §定位)。
-- 设计原则:
--   1. 一本小说一个 .db 文件(novel.db),与 output/<slug>/ 隔离对应;novel 表仅 1 行。
--   2. 两级 id 忠实保留:章内局部 (chapter, local_id) + 全局 global_id;provenance 入 member 表。
--   3. 锚点(R1)、绝对时间(R3)、歧义(R4)、provenance(R5)都有对应表,不丢可靠性信息。
--   4. **标签**用统一多态 tag 表,覆盖【场景标签】与【人物标签】(及未来任意实体),见下。
--   5. SQLite 方言:严格外键、WITHOUT ROWID 仅用于纯关联表、JSON 兜底列存放未建模的原始片段。
-- 适用:SQLite 3.37+(STRICT 表)。执行前 `PRAGMA foreign_keys=ON;`
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- 0. 小说与导出元信息
-- ---------------------------------------------------------------------------
CREATE TABLE novel (
    id                INTEGER PRIMARY KEY CHECK (id = 1),  -- 单行库:固定 1
    slug              TEXT    NOT NULL UNIQUE,
    novel_name        TEXT    NOT NULL,
    author            TEXT,
    source_type       TEXT,                                -- 'txt' | 'zip'
    chapter_count     INTEGER,
    stage             TEXT,                                -- done|partial|...
    clean_fingerprint TEXT,
    exported_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    schema_version    INTEGER NOT NULL DEFAULT 1,
    source_commit     TEXT                                 -- 导出时 repo HEAD(可空)
) STRICT;

-- 章节(input/<slug>/chNN.txt 对应;原文按需另存或留空)
CREATE TABLE chapter (
    chapter   INTEGER PRIMARY KEY,                         -- 章号(全局重排后)
    title     TEXT,
    char_count INTEGER,
    raw_text  TEXT                                         -- 可空:大库可不存原文,锚点定位时回源
) STRICT;

-- ---------------------------------------------------------------------------
-- 1. 全局实体(人物/物品/地点/组织共用一张表,type 区分)
--    对应 core.schema.json#/$defs/globalEntity
-- ---------------------------------------------------------------------------
CREATE TABLE entity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,         -- 库内代理键
    type        TEXT    NOT NULL CHECK (type IN ('character','item','location','organization')),
    global_id   INTEGER NOT NULL,                          -- 维度内全局 id(JSON 的 global_id)
    canonical   TEXT    NOT NULL,                          -- 规范名(展示用)
    role        TEXT,                                      -- 仅 character:自由文本叙事角色
    category    TEXT CHECK (category IS NULL OR category IN ('prop','set')),  -- 仅 item
    scale       TEXT CHECK (scale IS NULL OR scale IN ('room','building','area','city')), -- 仅 location
    confidence  TEXT CHECK (confidence IS NULL OR confidence IN ('high','medium','low')),
    extra_json  TEXT,                                      -- 未建模字段原样兜底(function/note 等)
    UNIQUE (type, global_id)
) STRICT;

CREATE INDEX idx_entity_type ON entity (type);
CREATE INDEX idx_entity_canonical ON entity (canonical);

-- 实体的全部名字(all_names:别名/异写)。展示与检索用。
CREATE TABLE entity_name (
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    name      TEXT    NOT NULL,
    is_canonical INTEGER NOT NULL DEFAULT 0 CHECK (is_canonical IN (0,1)),
    PRIMARY KEY (entity_id, name)
) STRICT, WITHOUT ROWID;

CREATE INDEX idx_entity_name_name ON entity_name (name);

-- provenance(R5):全局实体由哪些 (章, 局部id) 归并而来
CREATE TABLE entity_member (
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    chapter   INTEGER NOT NULL,
    local_id  INTEGER NOT NULL,
    PRIMARY KEY (entity_id, chapter, local_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX idx_entity_member_loc ON entity_member (chapter, local_id);

-- 物品定位(item_locations:物品出现在哪些地点)
CREATE TABLE item_location (
    item_entity_id     INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    chapter            INTEGER NOT NULL,
    location_global_id INTEGER,                            -- 维度内 location 的 global_id(可空)
    location_name      TEXT,
    via_scene          INTEGER                             -- 经由的场景 index(可空)
) STRICT;

CREATE INDEX idx_item_location_item ON item_location (item_entity_id);

-- 组织成员关系(memberships:人物 ∈ 组织)
CREATE TABLE org_membership (
    org_global_id        INTEGER NOT NULL,                 -- 组织 global_id
    character_global_id  INTEGER NOT NULL,                 -- 人物 global_id
    role                 TEXT,
    chapter              INTEGER,
    anchor_text          TEXT,                             -- 锚点(R1)
    source               TEXT CHECK (source IS NULL OR source IN ('explicit','inferred')),
    PRIMARY KEY (org_global_id, character_global_id, role)
) STRICT;

-- ---------------------------------------------------------------------------
-- 2. 关系(人物↔人物 / 地点↔地点 / 组织↔组织;item 边在导出时并入 relation)
--    对应 core.schema.json#/$defs/relation
-- ---------------------------------------------------------------------------
CREATE TABLE relation (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension     TEXT    NOT NULL CHECK (dimension IN ('character','location','organization','item')),
    from_global   INTEGER,                                 -- 来源实体 global_id
    to_global     INTEGER,                                 -- 目标实体 global_id
    relation_type TEXT    NOT NULL CHECK (relation_type IN
                    ('social','kin','affective','attitude','event','awareness',
                     'adjacency','containment','movement','remote')),
    label         TEXT    NOT NULL,
    evidence      TEXT,                                    -- 锚点(R1)
    confidence    TEXT CHECK (confidence IS NULL OR confidence IN ('high','medium','low')),
    chapter       INTEGER
) STRICT;

CREATE INDEX idx_relation_from ON relation (dimension, from_global);
CREATE INDEX idx_relation_to   ON relation (dimension, to_global);

-- ---------------------------------------------------------------------------
-- 3. 场景(scenes;按章归属)
--    对应 core.schema.json#/$defs/scene + 运行时 s.tags
-- ---------------------------------------------------------------------------
CREATE TABLE scene (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter         INTEGER NOT NULL REFERENCES chapter(chapter) ON DELETE CASCADE,
    scene_index     INTEGER NOT NULL,                      -- 章内 index
    title           TEXT,
    type            TEXT CHECK (type IS NULL OR type IN ('现实叙述','回忆','内心独白','动作')),
    location_name   TEXT,
    location_global_id INTEGER,                            -- location_ref.location_id(可空)
    summary         TEXT,
    start_text      TEXT,                                  -- 锚点(R1)
    end_text        TEXT,                                  -- 锚点(R1)
    UNIQUE (chapter, scene_index)
) STRICT;

CREATE INDEX idx_scene_chapter ON scene (chapter);

-- 场景参与人物(派生自基础标签/事件;多对多)
CREATE TABLE scene_character (
    scene_id            INTEGER NOT NULL REFERENCES scene(id) ON DELETE CASCADE,
    character_global_id INTEGER NOT NULL,
    PRIMARY KEY (scene_id, character_global_id)
) STRICT, WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- 4. 标签(统一多态表)★ 覆盖【场景标签】与【人物标签】
-- ----------------------------------------------------------------------------
-- 设计要点(应"给人物、场景加标签"的要求):
--   * target_type 决定标签挂在哪类对象:'scene' | 'character'(预留 item/location/organization/event)。
--   * target_id 指向对应表主键:scene.id 或 entity.id(character)。因 SQLite 不支持
--     条件外键,完整性由导出器保证 + 触发器校验(见末尾可选触发器)。
--   * kind 区分标签类别:
--       场景:'function'(功能标签)/'action'(动作标签)
--       人物:'trait'(特质)/'faction'(阵营)/'role_tag'(角色标签)等(可扩展)
--   * in_catalog:1=取自候选清单;0=清单外模型自造(对应 *_novel)。便于跨书聚合与清单扩充。
--   * 同一对象同一 (kind,label) 唯一;rank 保留模型给出的重要性顺序。
CREATE TABLE tag (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT    NOT NULL CHECK (target_type IN
                    ('scene','character','item','location','organization','event')),
    target_id   INTEGER NOT NULL,                          -- → scene.id 或 entity.id
    kind        TEXT    NOT NULL,                          -- function|action|trait|faction|role_tag|...
    label       TEXT    NOT NULL,
    in_catalog  INTEGER NOT NULL DEFAULT 1 CHECK (in_catalog IN (0,1)),
    rank        INTEGER,                                   -- 重要性序(1 最重要;可空)
    source      TEXT NOT NULL DEFAULT 'model'             -- 'model' | 'human':人工新增标签不被重导出覆盖
                  CHECK (source IN ('model','human')),
    UNIQUE (target_type, target_id, kind, label)
) STRICT;

CREATE INDEX idx_tag_target ON tag (target_type, target_id);
CREATE INDEX idx_tag_lookup ON tag (target_type, kind, label);  -- 按标签反查对象(跨章筛选)

-- 标签候选清单(便于跨书聚合 / 前端筛选条 / 清单扩充来源)
CREATE TABLE tag_catalog (
    target_type TEXT NOT NULL,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    PRIMARY KEY (target_type, kind, label)
) STRICT, WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- 5. 事件 + 时间(timeline;事件为一等节点)
--    对应 core.schema.json#/$defs/event / timelineEntry
-- ---------------------------------------------------------------------------
CREATE TABLE event (
    event_id        INTEGER PRIMARY KEY,                   -- 全局事件 id(缝合后)
    chapter         INTEGER NOT NULL,
    description     TEXT    NOT NULL,
    narrative_order INTEGER,
    story_order     INTEGER,
    is_flashback    INTEGER NOT NULL DEFAULT 0 CHECK (is_flashback IN (0,1)),
    storyline       TEXT,                                  -- 自由文本线索名
    abs_start       TEXT,                                  -- 绝对时间(R3:无依据为 NULL)
    abs_end         TEXT,
    abs_granularity TEXT,
    confidence      TEXT CHECK (confidence IS NULL OR confidence IN ('high','medium','low'))
) STRICT;

CREATE INDEX idx_event_chapter ON event (chapter);
CREATE INDEX idx_event_story_order ON event (story_order);

-- 事件参与人物(global_participants;多对多)
CREATE TABLE event_participant (
    event_id            INTEGER NOT NULL REFERENCES event(event_id) ON DELETE CASCADE,
    character_global_id INTEGER NOT NULL,
    PRIMARY KEY (event_id, character_global_id)
) STRICT, WITHOUT ROWID;

-- 人物个人时间线(character_timelines:每人一串 timelineEntry)
CREATE TABLE character_timeline (
    character_global_id INTEGER NOT NULL,
    seq                 INTEGER NOT NULL,
    event_id            INTEGER REFERENCES event(event_id) ON DELETE SET NULL,
    chapter             INTEGER,
    description         TEXT,
    is_flashback        INTEGER CHECK (is_flashback IS NULL OR is_flashback IN (0,1)),
    PRIMARY KEY (character_global_id, seq)
) STRICT, WITHOUT ROWID;

-- 多线交汇点(sync_points)
CREATE TABLE sync_point (
    event_id INTEGER PRIMARY KEY REFERENCES event(event_id) ON DELETE CASCADE,
    chapter  INTEGER,
    description TEXT
) STRICT;

CREATE TABLE sync_point_participant (
    event_id            INTEGER NOT NULL REFERENCES sync_point(event_id) ON DELETE CASCADE,
    character_global_id INTEGER NOT NULL,
    PRIMARY KEY (event_id, character_global_id)
) STRICT, WITHOUT ROWID;

-- 时间表达式(timeExpression;原文时间词 + 锚点)
CREATE TABLE time_expression (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter INTEGER,
    text    TEXT NOT NULL,
    kind    TEXT CHECK (kind IS NULL OR kind IN ('clock','duration','relative')),
    anchor  TEXT                                           -- 锚点(R1)
) STRICT;

-- ---------------------------------------------------------------------------
-- 6. 歧义留痕(R4:非高置信归并不硬合,全部入库供人工裁决)
-- ---------------------------------------------------------------------------
CREATE TABLE ambiguity (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension TEXT NOT NULL CHECK (dimension IN ('character','item','location','organization')),
    reason    TEXT NOT NULL,
    chapter_a INTEGER, name_a TEXT,
    chapter_b INTEGER, name_b TEXT,
    overlap_json TEXT                                      -- overlap 原样
) STRICT;

-- ---------------------------------------------------------------------------
-- 7. 便捷视图
-- ---------------------------------------------------------------------------
-- 7.1 场景 + 其全部标签(逗号串),区分功能/动作
CREATE VIEW v_scene_tags AS
SELECT s.id AS scene_id, s.chapter, s.scene_index, s.title, s.type,
       (SELECT group_concat(label, '、') FROM tag t
          WHERE t.target_type='scene' AND t.target_id=s.id AND t.kind='function') AS function_tags,
       (SELECT group_concat(label, '、') FROM tag t
          WHERE t.target_type='scene' AND t.target_id=s.id AND t.kind='action')   AS action_tags
FROM scene s;

-- 7.2 人物 + 其全部标签
CREATE VIEW v_character_tags AS
SELECT e.id AS entity_id, e.global_id, e.canonical, e.role,
       (SELECT group_concat(t.kind || ':' || t.label, '、') FROM tag t
          WHERE t.target_type='character' AND t.target_id=e.id) AS tags
FROM entity e WHERE e.type='character';

-- 7.3 按标签反查场景(跨章筛选,对应前端 Scenes 视图)
CREATE VIEW v_tag_scene_index AS
SELECT t.kind, t.label, s.chapter, s.scene_index, s.title
FROM tag t JOIN scene s ON t.target_type='scene' AND t.target_id=s.id;

-- ---------------------------------------------------------------------------
-- 8. (可选)多态外键完整性触发器 —— SQLite 无条件外键,用触发器兜底
--    导出器应保证一致;启用触发器可在手工写入时防悬空。
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_tag_scene_fk BEFORE INSERT ON tag
WHEN NEW.target_type='scene'
  AND NOT EXISTS (SELECT 1 FROM scene WHERE id=NEW.target_id)
BEGIN
    SELECT RAISE(ABORT, 'tag.target_id 指向不存在的 scene');
END;

CREATE TRIGGER trg_tag_character_fk BEFORE INSERT ON tag
WHEN NEW.target_type='character'
  AND NOT EXISTS (SELECT 1 FROM entity WHERE id=NEW.target_id AND type='character')
BEGIN
    SELECT RAISE(ABORT, 'tag.target_id 指向不存在的 character');
END;

-- ============================================================================
-- 9. 可写人工标注层(annotation layer)
-- ----------------------------------------------------------------------------
-- 目的:承接【人工评价 / 调整 / 补充】,与模型产出分层共存、可追溯、不被重导出覆盖。
-- 分层原则(关键):
--   * 模型产出的行 source='model';人工产出 source='human'。
--   * 重导出(global/*.json → DB)只 wipe+reload 'model' 行,**绝不删 'human' 行**。
--   * 合并展示/回写时,人工层优先(human overrides model),并保留模型原值可回溯。
-- 这样 DB 成为"模型结果 + 人工修订"的叠加视图,而文件主存储仍只承载模型结果(可靠性防线不变)。
-- ============================================================================

-- 9.1 自由标注:对任意对象的人工补充说明/纠正建议/评分(不改原始字段)
CREATE TABLE annotation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT    NOT NULL CHECK (target_type IN
                    ('scene','character','item','location','organization','event','relation')),
    target_id   INTEGER NOT NULL,                          -- 指向对应表主键
    field       TEXT,                                      -- 针对哪个字段(空=整体标注)
    kind        TEXT    NOT NULL CHECK (kind IN
                    ('note','correction','rating','flag')), -- 备注/纠错建议/评分/标记存疑
    body        TEXT,                                      -- 标注正文 / 建议的新值
    rating      INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),  -- 仅 kind='rating'
    author      TEXT    NOT NULL DEFAULT 'human',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (target_type, target_id, field, kind, author, created_at)
) STRICT;

CREATE INDEX idx_annotation_target ON annotation (target_type, target_id);
CREATE INDEX idx_annotation_kind   ON annotation (kind);

-- 9.2 人工裁决:对模型【判断】的复核结论(归并/关系/歧义/成员关系…)
--     记录:对象 + 模型原值 + 人工裁决 + 操作者 + 时间,完全可追溯。
CREATE TABLE review (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject     TEXT    NOT NULL CHECK (subject IN
                    ('entity_merge','relation','ambiguity','org_membership','event','tag')),
    ref_table   TEXT,                                      -- 指向的表名(如 'relation','ambiguity')
    ref_id      INTEGER,                                   -- 指向的行 id(可空,如对 global_id 的裁决)
    ref_global  INTEGER,                                   -- 涉及的 global_id(归并/关系裁决用)
    verdict     TEXT    NOT NULL CHECK (verdict IN
                    ('confirm','reject','merge','split','correct','defer')),
    original    TEXT,                                      -- 模型原值(JSON 片段,回溯用)
    corrected   TEXT,                                      -- 人工修正后的值(JSON 片段;verdict=correct/merge/split)
    rationale   TEXT,                                      -- 裁决理由
    author      TEXT    NOT NULL DEFAULT 'human',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    applied     INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0,1)) -- 是否已回写文件主存储
) STRICT;

CREATE INDEX idx_review_subject ON review (subject);
CREATE INDEX idx_review_ref ON review (ref_table, ref_id);
CREATE INDEX idx_review_unapplied ON review (applied) WHERE applied = 0;

-- 9.3 视图:有效标签(人工优先;人工新增可见,人工不会"删模型标签"——如需隐藏用 annotation flag)
CREATE VIEW v_effective_tag AS
SELECT target_type, target_id, kind, label, in_catalog, rank, source
FROM tag;  -- 当前模型/人工标签同表共存;source 列区分。前端可按需过滤或合并展示。

-- 9.4 视图:待回写的人工裁决(回写器据此把人工层合并回 global/*.json)
CREATE VIEW v_pending_reviews AS
SELECT id, subject, ref_table, ref_id, ref_global, verdict, original, corrected, rationale, created_at
FROM review WHERE applied = 0 ORDER BY created_at;
