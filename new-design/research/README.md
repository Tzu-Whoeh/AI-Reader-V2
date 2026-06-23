# research/ — 实验中间结果与复用基准

本目录沉淀 new-design 框架研发过程中的**可复用中间结果**:测试基准、prompt 演进史、
评测数据、关键结论。目的是**避免每次从头重跑**——下次改进某个 pass 前,先来这里看已有结论和基准。

## 目录

```
research/
├── README.md                      # 本文件
├── test_chapters/                 # 测试章节原文(复用基准)
│   ├── ch44.txt doc3.txt doc4.txt doc5.txt
│   └── README.md                  # 每章特点 + 适合测什么
├── eval/
│   └── scene_splitting/
│       ├── test_samples.md        # A/B/C 极端构造样本 + 人工预期
│       ├── findings.md            # 场景拆分:判据演进 + 模型适配 + 稳定性 + 教训
│       └── stability_v8.md        # v8 稳定性原始数据
└── prompts/
    └── scene_splitting_history/   # 场景拆分 prompt v2→v8 演进存档
        ├── 01_scene_splitting_v2.txt ... v8.txt
        └── CHANGELOG.md           # 每版改动 + 原因 + 效果
```

## 怎么复用

- **要改场景拆分** → 先读 `eval/scene_splitting/findings.md`(判据为什么是现在这样)
  和 `prompts/scene_splitting_history/CHANGELOG.md`(走过哪些弯路,别重复)。定稿版在
  `new-design/prompts/01_scene_splitting.txt`(=history 里的 v8)。
- **要测任何 pass** → 用 `test_chapters/` 的四章 + `eval/scene_splitting/test_samples.md`
  的 A/B/C 样本作基准。每章特点见 `test_chapters/README.md`。
- **要选模型** → findings.md 有「任务-模型适配」结论(判断类 27b / 抽取类 35b),附实测依据。

## 已沉淀的线

- ✅ **场景拆分**:判据从「数段数」演进到「两类客观硬边界(loc/time)+消歧」,定稿 v8 + 27b。完整。
- ⏳ 事件抽取 / 人物物品(用法B:事件骨架前置):进行中,结论稳后补入。

## 注

测试章节原文为受控研究环境用途。本仓库为 private。
