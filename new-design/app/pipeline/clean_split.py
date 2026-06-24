#!/usr/bin/env python3
"""
文本清洗 + 章节拆分(确定性,不调模型)

清洗(激进,规则可配置):去编码噪音/零宽字符、全半角统一、删广告水印翻页行、规整空行。
拆分:正则多模式匹配章节标题,切成 chNN。

规则集中在 NOISE_PATTERNS / CHAPTER_PATTERNS,按作品可增删。
"""
import re, unicodedata

# ---------- 清洗规则(可配置) ----------
ZERO_WIDTH = ["\u200b","\u200c","\u200d","\ufeff","\u2060"]

# 整行匹配即删除的噪音(网文盗版常见)。按需增删。
NOISE_PATTERNS = [
    r'.*www\.[\w.-]+\.(com|net|org|cc|cn).*',   # 含网址的行
    r'.*[\wＷｗ]{3,}\.(piratebook|qidian|biquge|[\w-]+)\.(com|net|cc).*',
    r'.*请记住本站.*', r'.*手机用户请访问.*', r'.*请访问本站.*',
    r'.*本章未完.*', r'.*请翻页.*', r'.*未完待续.*',
    r'.*本书由.*整理.*', r'.*独家整理.*', r'.*转载请注明.*',
    r'.*更多精彩.*请访问.*',
    r'^[─—\-=*＊·•\s]{5,}$',                      # 纯分隔线行
    r'^\s*全文完[。.\s]*$',
]

def _fullwidth_to_half(s):
    out=[]
    for ch in s:
        code=ord(ch)
        if code==0x3000: out.append(" ")          # 全角空格→半角
        elif 0xFF01<=code<=0xFF5E: out.append(chr(code-0xFEE0))
        else: out.append(ch)
    return "".join(out)

def clean(text, noise_patterns=None, drop_fullwidth_digits_punct=False):
    """返回 (cleaned_text, report)。"""
    patterns=[re.compile(p) for p in (noise_patterns or NOISE_PATTERNS)]
    text=unicodedata.normalize("NFC", text)
    for z in ZERO_WIDTH: text=text.replace(z,"")
    lines=text.split("\n")
    kept=[]; dropped=[]
    for ln in lines:
        probe=_fullwidth_to_half(ln).strip()   # 用半角化后的内容判噪音
        if probe and any(p.match(probe) for p in patterns):
            dropped.append(ln.strip()); continue
        kept.append(ln)
    # 规整:去行首全角/多余空白,折叠连续空行
    norm=[]
    for ln in kept:
        ln=ln.replace("\u3000"," ").rstrip()
        ln=re.sub(r'^[ \t]+','',ln)             # 去行首缩进(正文段首空格)
        norm.append(ln)
    out=[]; blank=0
    for ln in norm:
        if ln.strip()=="":
            blank+=1
            if blank<=1: out.append("")
        else:
            blank=0; out.append(ln)
    cleaned="\n".join(out).strip()+"\n"
    return cleaned, {"dropped_lines":dropped, "dropped_count":len(dropped)}

# ---------- 章节拆分(多模式) ----------
CHAPTER_PATTERNS = [
    r'^\s*第\s*[0-9]+\s*[章回卷节]\b.*$',
    r'^\s*第\s*[一二三四五六七八九十百千零〇两]+\s*[章回卷节]\b.*$',
    r'^\s*Chapter\s+\d+.*$',
    r'^\s*[0-9]+[、.\s].{0,30}$',                # 数字编号短行(弱模式)
]

def split_chapters(text, patterns=None):
    """按章节标题切分。返回 [{index,title,text}]。无标题则整篇为 ch01。"""
    pats=[re.compile(p, re.M) for p in (patterns or CHAPTER_PATTERNS[:3])]  # 默认不用弱模式
    lines=text.split("\n")
    heads=[]   # (line_no, title)
    for i,ln in enumerate(lines):
        s=ln.strip()
        if s and any(p.match(s) for p in pats):
            heads.append((i, s))
    if not heads:
        return [{"index":1,"title":"(全文)","text":text.strip()}]
    chapters=[]
    for k,(ln_no,title) in enumerate(heads):
        start=ln_no+1
        end=heads[k+1][0] if k+1<len(heads) else len(lines)
        body="\n".join(lines[start:end]).strip()
        chapters.append({"index":k+1,"title":title,"text":body})
    return chapters

# ---------- 长章二次切块 ----------
def chunk_long_chapter(text, max_chars=3000):
    """超长章节按段落边界切块(每块≤max_chars),供分块喂模型。返回 [chunk_text]。"""
    if len(text)<=max_chars: return [text]
    paras=re.split(r'\n\s*\n', text)
    chunks=[]; cur=""
    for p in paras:
        if len(cur)+len(p)+2>max_chars and cur:
            chunks.append(cur.strip()); cur=""
        cur+=p+"\n\n"
    if cur.strip(): chunks.append(cur.strip())
    return chunks

if __name__=="__main__":
    import sys, json
    raw=open(sys.argv[1],encoding="utf-8").read()
    cleaned, rep=clean(raw)
    chapters=split_chapters(cleaned)
    print(f"清洗: 删除 {rep['dropped_count']} 行噪音")
    print(f"拆分: {len(chapters)} 章")
    for c in chapters:
        chunks=chunk_long_chapter(c["text"])
        print(f"  ch{c['index']:02d} 「{c['title']}」 {len(c['text'])}字 {len(chunks)}块")
