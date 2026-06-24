# 校验器 findings(R1–R6)

## 设计与实测结论

- **R1 锚点不是整字段逐字**:`evidence` 是模型说明文,逐字片段在**引号内**,且含 `...`/`……`
  省略需切段分别匹配。`start_text`/`end_text`/`time.anchor` 是纯逐字锚点(可能带引号)。
  校验器 `_anchor_fragments()` 据此抽片段;R1 命中失败记 **warning 非 error**——锚点是模型
  措辞,允许容错,但不静默丢弃。
- **R2/R6 可无条件跑**(只需 global)。反向测试(注入悬空 `global_id=99999`、非法枚举
  `telepathy`)均被精确抓出,无假阴性。
- **R3 绝对时间纪律**:`abs_interval=null` 合规;非 null 但 start/end 全空 → warning(疑似应为 null)。
  实测样本 abs_interval 多为 null,符合纪律。
- **R5 provenance**:需章级 `_merged.json`;缺则跳过成员核对(non-blocking)。
- **真实 global 样本全量跑 R2/R3/R6:0 error 0 warning**(干净)。

## 拆分:运行时 vs CI(b 方案)

- **运行时**:`pipeline/validate.py`,**纯标准库**,只跑 R1–R6 语义规则。后端零依赖红线不破。
- **CI/离线**:`tools/schema_check.py`,用 `jsonschema` 校验**结构**(类型/必填/枚举/形态)。
  开发依赖,不进后端运行时。

## ⏳ ambiguity:缺「原文 + 产物」配对基准

R1 的**真实命中验证**需要同一章的原文与其抽取产物配对。现状:
- `samples/full_run/ch01/` 有产物含锚点,但**无对应原文**(samples 不自带 raw)。
- `research/test_chapters/` 有四章原文,但**无对应产物**。

二者不配对,故 R1 目前用**合成基准**验证逻辑正确性(真锚点不报、虚构锚点报警,已通过)。
**待补**:对 test_chapters 四章跑一遍 pipeline 产出产物,即得 R1 真实基准。不在本 PR 范围,
记此处留后续。不硬凑配对以免造假基准。
