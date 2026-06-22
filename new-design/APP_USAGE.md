# 叙事分析应用 · 使用说明

对指定文件或目录运行完整分析流水线:清洗 → 章节拆分 → 逐章五维度+事件分析 → 全局合并。

## 运行

```bash
cd new-design/pipeline   # 提示词与脚本同目录
python app.py <输入文件或目录> [输出目录]
# 例: python app.py 我的小说.txt result/
```

默认直连 Ollama(127.0.0.1:11434);经平台调用时替换 `app.py` 的 `call_model()`。

## 流水线

```
输入(文件/目录)
  → ① clean_split.clean()      清洗:去编码噪音/零宽字符、全半角统一、删广告水印翻页行
  → ② clean_split.split_chapters()  正则多模式切章(第X章/Chapter/卷)
  → ③ 逐章 analyze_chapter()    场景→人物/物品/地点(各2pass)→两层事件→章节归并
  → ④ aggregate.aggregate()     跨章实体归一+时间线缝合+按维度聚合+(可接图索引/漏标扫描)
输出: output/chNN/_merged.json(每章) + output/global/*.json(全局分维度) + _index.json
```

## 特性

- **输入**:单文件,或目录(目录下所有 .txt 按文件名排序合并)。
- **断点续跑**:已生成 `chNN/_merged.json` 的章节自动跳过,中断后重跑只补未完成章。
- **错误隔离**:单章分析失败仅跳过该章并报告,不影响其余章和全局合并。
- **长章切块**:超 `max_chars` 的章节按段落边界二次切块(`chunk_long_chapter`);多块章节的块内归一接口已预留。

## 清洗规则(可配置)

`clean_split.py` 的 `NOISE_PATTERNS` 是整行删除的噪音正则(网址行、翻页提示、水印、整理声明、分隔线等),按作品增删。`clean()` 默认激进清洗;传入自定义 `noise_patterns` 可调。

## 章节拆分规则

`CHAPTER_PATTERNS` 多模式:阿拉伯数字章节、中文数字章节、Chapter N。默认用前三个稳健模式;数字编号弱模式默认关闭(易误切)。

## 依赖

提示词:`01_scene_splitting` / `02_character_pass1|pass2` / `03_item_pass1|pass2` / `04_location_pass1|pass2` / 事件父子两提示词。
脚本:`clean_split` `merge_core` `cross_chapter` `entity_normalize` `aggregate` `event_pipeline` `storage`(可选 `graph_index` `gap_scan`)。

## 已知限制

- 长章多块的"块内跨块实体归一"目前留接口未实现(短章无需);需要时可复用 `cross_chapter` 的并查集逻辑做块级归一。
- 全局合并默认不自动调 `graph_index` / `gap_scan`,按需在 `run()` 末尾追加。
