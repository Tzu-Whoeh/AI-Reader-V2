"""
人名归一与相似合并(两层证据:符号归一 + 名字相似×上下文佐证)
依赖标准库;繁简转换若装了 opencc 则用,否则用内置简版映射(可扩展)。
"""
import re, unicodedata
from difflib import SequenceMatcher

# ---------- 第一层:符号归一(确定性,全覆盖) ----------
_ZERO_WIDTH = "".join(["\u200b","\u200c","\u200d","\ufeff","\u2060"])
_SYMBOLS = r"[\s_\-\*·.、,，。:：;；!！?？\"'`~^|/\\()（）\[\]【】<>《》…—\u200b\u200c\u200d\ufeff\u2060]"

def _fullwidth_to_half(s):
    out=[]
    for ch in s:
        code=ord(ch)
        if code==0x3000: out.append(" ")
        elif 0xFF01<=code<=0xFF5E: out.append(chr(code-0xFEE0))
        else: out.append(ch)
    return "".join(out)

# 极简繁简映射(示例;生产建议用 opencc)。覆盖测试与常见字。
_T2S = str.maketrans({"華":"华","劍":"剑","員":"员","體":"体","國":"国","學":"学","會":"会","這":"这"})

def normalize_name(s, do_t2s=True):
    """剥离符号/零宽/全半角统一/(可选)繁转简。返回归一后的纯名字。"""
    if s is None: return ""
    s = unicodedata.normalize("NFKC", s)         # 兼容性分解,顺带处理部分全角
    s = _fullwidth_to_half(s)
    for z in _ZERO_WIDTH: s = s.replace(z, "")
    if do_t2s: s = s.translate(_T2S)
    s = re.sub(_SYMBOLS, "", s)                  # 去掉所有符号/空白
    return s.strip()

# ---------- 第二层:名字相似 + 上下文佐证 ----------

def _levenshtein(a, b):
    if a==b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]
        for j,cb in enumerate(b,1):
            cur.append(min(prev[j]+1, cur[j-1]+1, prev[j-1]+(ca!=cb)))
        prev=cur
    return prev[-1]

def name_similarity(a, b):
    """归一后名字的相似度 0..1。结合序列相似与长度差惩罚。"""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb: return 0.0
    if na==nb: return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    return ratio

def context_support(recA, recB):
    """
    上下文佐证强度 0..1。证据:role 词重叠、共同场景id、共同地点id、与相同第三方有关系。
    recA/recB 可带可选字段: role, scene_ids(set), location_ids(set), related_ids(set)
    """
    score=0.0; signals=0
    ra, rb = recA.get("role",""), recB.get("role","")
    if ra and rb:
        signals+=1
        # role 词重叠
        sa=set(re.findall(r"[\u4e00-\u9fff]{2,}", ra)); sb=set(re.findall(r"[\u4e00-\u9fff]{2,}", rb))
        if sa and sb and (sa & sb): score+=0.5
    for key,w in [("scene_ids",0.3),("location_ids",0.2),("related_ids",0.4)]:
        A=set(recA.get(key,[]) or []); B=set(recB.get(key,[]) or [])
        if A or B:
            signals+=1
            if A & B: score+=w
    return min(score,1.0), signals


# 身份大类(用于"严重互斥"检测;同名默认合,仅命中不同大类才 review)
_ROLE_CLASSES = {
    "特务谍报": ["特务","谍报","间谍","情报","军统","中统","76号","心腹","潜伏"],
    "军警官员": ["宪兵","队长","军官","警察","官员","主任","司令","长官"],
    "商贩平民": ["掌柜","老板","商人","小贩","平民","茶楼","店主","伙计"],
    "学界文人": ["教授","学者","文人","先生","学生","记者"],
    "服务侍从": ["司机","佣人","仆人","保姆","侍从","厨子"],
}
def _role_class(role):
    if not role: return set()
    hit=set()
    for cls,kws in _ROLE_CLASSES.items():
        if any(k in role for k in kws): hit.add(cls)
    return hit

def role_conflict(roleA, roleB):
    """严重互斥: 两 role 各自命中身份大类, 且无任何交集。返回 True 表示严重冲突。"""
    ca, cb = _role_class(roleA), _role_class(roleB)
    if not ca or not cb: return False        # 有一方无法归类 -> 不算冲突(宽松)
    return len(ca & cb)==0                    # 完全不沾边才算冲突

def classify_merge(recA, recB, ctx_min=0.3):
    """
    返回 ('auto'|'review'|'no', detail)
    规则(适配中文短名,以编辑距离为主 + 上下文佐证):
    - 符号归一后完全相同 -> auto(纯符号差异)
    - 归一后编辑距离==1(差一字,典型错别字):
        上下文有支持(ctx>=ctx_min) -> auto  ; 否则 -> review(防误并同构不同人)
    - 编辑距离==2 或 相似度中等 -> review
    - 其余 -> no
    """
    na, nb = normalize_name(recA.get("name")), normalize_name(recB.get("name"))
    sim = name_similarity(recA.get("name"), recB.get("name"))
    ctx, signals = context_support(recA, recB)
    lev = _levenshtein(na, nb)
    detail={"normA":na,"normB":nb,"name_sim":round(sim,3),"edit_dist":lev,
            "ctx":round(ctx,3),"ctx_signals":signals}
    if na and na==nb:
        if role_conflict(recA.get("role"), recB.get("role")):
            detail["reason"]="同名但身份大类严重互斥(疑似重名不同人) -> 待人工确认"
            return "review", detail
        detail["reason"]="符号归一后同名"; return "auto", detail
    if not na or not nb:
        detail["reason"]="空名"; return "no", detail
    if lev==1 and len(na)==len(nb):
        if ctx>=ctx_min:
            detail["reason"]="差一字(疑错别字)且上下文吻合 -> 自动合"; return "auto", detail
        else:
            detail["reason"]="差一字但上下文不支持 -> 待人工确认"; return "review", detail
    if lev==2 or (0.5<=sim<1.0):
        detail["reason"]="名字相似(编辑距离2或中等相似) -> 待确认"; return "review", detail
    detail["reason"]="不相似"; return "no", detail
