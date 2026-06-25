#!/usr/bin/env python3
"""确定性证据检索:给一条歧义对,从原文逐句捞出两个名字各自出现的句子。
锚点原则:只返回名字逐字出现的句子(与主流水线一致),不做语义检索。"""
import re, os, glob

def split_sentences(text):
    # 中文句末标点切句,保留标点
    parts = re.split(r'(?<=[。!?；…\n])', text or "")
    return [p.strip() for p in parts if p.strip()]

def load_chapter_text(input_dir, chapter):
    """input/<slug>/chNN.txt 或任意给定目录下的 chNN.txt。"""
    for pat in (f"ch{chapter:02d}.txt", f"ch{chapter}.txt", f"{chapter:02d}.txt"):
        p = os.path.join(input_dir, pat)
        if os.path.isfile(p):
            return open(p, encoding="utf-8", errors="replace").read()
    return ""

def sentences_with(name, text, limit=8):
    if not name: return []
    return [s for s in split_sentences(text) if name in s][:limit]

def make_evidence_fn(input_dir):
    """返回 evidence_for(pair)->{"A":[...],"B":[...]},句子来自各自章节原文。"""
    cache = {}
    def _text(ch):
        if ch not in cache: cache[ch] = load_chapter_text(input_dir, ch)
        return cache[ch]
    def evidence_for(pair):
        chA = pair.get("chapterA", pair.get("chA"))
        chB = pair.get("chapterB", pair.get("chB"))
        return {
            "A": sentences_with(pair["nameA"], _text(chA)),
            "B": sentences_with(pair["nameB"], _text(chB)),
        }
    return evidence_for