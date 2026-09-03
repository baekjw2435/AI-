# -*- coding: utf-8 -*-
# 끄투 봇
# 사전 모드 두 가지를 지원합니다.
#   복합 : 기존 우리말샘 계열 자료 (words.txt / attack_data.txt / endcat.txt / mid_attack.txt / dollim*.txt)
#   표준 : 신표국 표준 자료 (standard_words.txt / standard_special.json)
# 두 사전의 통계는 절대 합치지 않으며, 각 답변은 사용한 사전을 함께 표시합니다.
#
# !대결 [표준|복합] → 봇과 대국 (훈련실)
# !경기 [표준|복합] → 사람끼리 대국 (경기장)
# !기권            → 진행 중인 대국 포기
# !루트 <음절><보호막> → 연결 수순 4·6·8수 + 추천 단어 + 예상 수순 (표준 자료 전용)
# !탐색 <음절><보호막> → 후보 버튼을 눌러 한 수씩 수순을 만들어 가는 화면 (표준 자료 전용)
# !모드            → 현재 채널의 사전 모드 확인
# !모드 표준/복합  → 현재 채널의 사전 모드 변경
# !공격 <글자>     → ⚡한방 / 🗡️공격 / 🔥준공격 / 🎣유도 / 🔄돌림
# !한방 <글자>     → 한방만
# !장문 <글자>     → 그 글자로 시작하는 가장 긴 단어 TOP 30
# !종결 <글자>     → 그 글자로 끝나는 단어
# !장문종결 <글자> → 그 글자로 끝나는 가장 긴 단어
# !중간 <글자>     → 중간말잇기 (표준·복합 모두 지원)
#
# 두음법칙은 두 모드 모두 표준두음법칙만 적용합니다.

import os, re, glob, json, heapq, random, asyncio
import discord
import route_engine as rq
import game as gm

# ===== 서버 / 채널 제한 (0 = 제한 없음) =====
# GUILD_ID 에는 반드시 "서버" ID 를 넣어야 합니다. 채널 ID 를 넣으면 어떤 메시지와도
# 맞지 않아 봇이 아무 반응도 하지 않습니다. 기본값은 제한 없음(0)입니다.
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))
# ==========================================

# ===== 사전 모드 =====
MODE_COMPLEX = "복합"
MODE_STANDARD = "표준"
DEFAULT_MODE = os.environ.get("DEFAULT_MODE", MODE_COMPLEX)
if DEFAULT_MODE not in (MODE_COMPLEX, MODE_STANDARD):
    DEFAULT_MODE = MODE_COMPLEX
CHANNEL_MODE = {}   # 채널 ID -> 모드
# ====================

# ===== 채널별 고정 배정 =====
# 여기에 적힌 채널은 사전이 고정되고 `!모드` 로 바꿀 수 없습니다.
# 값은 (대국 종류, 사전) 입니다. 종류는 "훈련실"(사람 대 봇) 또는 "경기장"(사람 대 사람)입니다.
ARENA = "경기장"      # 사람끼리 대국
TRAINING = "훈련실"   # 사람 대 봇 대국
STUDY = "학습실"      # 대국 없이 조회·탐색만
CHANNEL_ROLES = {
    1544722084561817650: (ARENA, MODE_STANDARD),     # 경기장-표준사전
    1544854290819059765: (ARENA, MODE_COMPLEX),      # 경기장-복합사전
    1544722279349485578: (TRAINING, MODE_STANDARD),  # 훈련실-표준사전
    1544854625755209758: (TRAINING, MODE_COMPLEX),   # 훈련실-복합사전
    1544553748565729381: (STUDY, MODE_STANDARD),     # 표준탐색
    1523328035686846495: (STUDY, MODE_COMPLEX),      # 복합탐색
}
# ===========================

CHO = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
def dec(ch):
    o = ord(ch) - 0xAC00
    return None if o < 0 or o > 11171 else (o//588, (o%588)//28, o%28)

# 표준두음법칙: 받침은 그대로 두고 초성만 한 번 바꿉니다.
#   랴/려/례/료/류/리 → 야/여/예/요/유/이
#   라/래/로/뢰/루/르 → 나/내/노/뇌/누/느
#   녀/뇨/뉴/니       → 여/요/유/이
def dueum(ch):
    d = dec(ch)
    if not d: return None
    c, j, k = d
    if c == 5:
        if j in (2,6,7,12,17,20): return chr(0xAC00+(11*21+j)*28+k)
        if j in (0,1,8,11,13,18): return chr(0xAC00+(2*21+j)*28+k)
    elif c == 2:
        if j in (6,12,17,20): return chr(0xAC00+(11*21+j)*28+k)
    return None

def syllable_keys(syl):
    """해당 음절과 표준두음법칙 변형을 중복 없이 돌려줍니다."""
    keys = [syl]
    du = dueum(syl)
    if du and du != syl: keys.append(du)
    return keys

def is_self_loop(w):
    """첫 글자와 끝 글자가 표준두음법칙으로 이어지는 자가순환 단어인지 확인합니다."""
    f, l = w[0], w[-1]
    return f == l or f == dueum(l) or dueum(f) == l

def find_file(pats):
    for pat in pats:
        hit = sorted(glob.glob(pat))
        if hit: return hit[0]
    return None

def find_complex_word_file():
    """복합 단어 목록을 찾습니다. 표준 사전 파일은 절대 고르지 않습니다.
    두 사전을 섞으면 안 되기 때문입니다."""
    for pat in ("words.txt", "끄글_단어_목록*.txt", "끄글_단어*.txt", "끄글*단어*.txt"):
        for hit in sorted(glob.glob(pat)):
            if not hit.startswith("standard_"):
                return hit
    return None


# =====================================================================
# 복합 사전 (기존 자료)
# =====================================================================

# ---- 공격 데이터 (한방) ----
ATTACK = {}
def load_attack():
    path = find_file(["attack_data.txt", "끄글_공격*.txt", "*공격*.txt"])
    if not path:
        print("[경고] attack_data.txt 파일을 찾지 못했습니다."); return
    sec = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1]; ATTACK.setdefault(sec, {}); continue
            m = re.match(r'깊이\s*(\d+)\s*[:：]\s*(.*)', s)
            if not m or sec is None: continue
            d = int(m.group(1))
            for w in m.group(2).split(','):
                w = w.strip()
                if w and (w not in ATTACK[sec] or d < ATTACK[sec][w]):
                    ATTACK[sec][w] = d
    print(f"[로드] 복합 공격 {len(ATTACK)}글자")

# ---- 준공격/유도 (끝글자 분류): 첫글자 -> [(단어,'J'/'Y')] ----
FIRST = {}
ENDSYL = {}   # 끝글자 -> 'J'(준공격)/'Y'(유도)
def load_endcat():
    path = find_file(["endcat.txt"])
    if not path:
        print("[경고] endcat.txt 파일을 찾지 못했습니다."); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip('\n')
            if '\t' not in line: continue
            w, cat = line.split('\t', 1)
            if not w: continue
            FIRST.setdefault(w[0], []).append((w, cat)); ENDSYL[w[-1]] = cat; n += 1
    print(f"[로드] 복합 준공격·유도 {n}단어")

# ---- 장문 (읽으며 글자별 최장 30개만 메모리 유지) ----
LONGEST = {}
ENDWORDS = {}     # 끝글자 -> [그 글자로 끝나는 단어들]
STARTCOUNT = {}   # 글자 -> 그 글자로 시작하는 단어 수 (이을 수 있는 수)
ALLWORDS = set()  # 대국 판정용 전체 단어
FIRSTWORDS = {}   # 첫글자 -> [그 글자로 시작하는 단어] (대국용)
def load_words():
    path = find_complex_word_file()
    if not path:
        print("[경고] words.txt 파일을 찾지 못해 복합 사전 기능(장문·종결·대국)을 끕니다."); return
    if path != "words.txt":
        print(f"[안내] 복합 단어 목록으로 {path} 를 사용합니다.")
    KEEP = 30
    heaps = {}; n = 0
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            w = line.strip()
            if not w: continue
            ALLWORDS.add(w)
            lo = ord(w[-1]) - 0xAC00
            if 0 <= lo <= 11171:
                ENDWORDS.setdefault(w[-1], []).append(w)   # 종결용: 끝글자 인덱스
            o = ord(w[0]) - 0xAC00
            if o < 0 or o > 11171: continue
            STARTCOUNT[w[0]] = STARTCOUNT.get(w[0], 0) + 1
            FIRSTWORDS.setdefault(w[0], []).append(w)
            h = heaps.setdefault(w[0], [])
            key = (len(w), w)
            if len(h) < KEEP: heapq.heappush(h, key)
            elif key > h[0]: heapq.heapreplace(h, key)
            n += 1
    for syl, h in heaps.items():
        LONGEST[syl] = [w for _, w in sorted(h, reverse=True)]
    print(f"[로드] 복합 장문 {len(LONGEST)}글자 (원본 {n}단어, 글자별 최장 {KEEP})")

# ---- 중간말잇기 공격 데이터 ----
MID_ATTACK = {}
def load_mid():
    path = find_file(["mid_attack.txt", "끄글_공격_단어_2026070709*.txt"])
    if not path:
        print("[경고] mid_attack.txt 파일이 없어 중간말잇기 기능을 끕니다."); return
    sec = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1]; MID_ATTACK.setdefault(sec, {}); continue
            m = re.match(r'깊이\s*(\d+)\s*[:：]\s*(.*)', s)
            if not m or sec is None: continue
            d = int(m.group(1))
            for w in m.group(2).split(','):
                w = w.strip()
                if w and (w not in MID_ATTACK[sec] or d < MID_ATTACK[sec][w]):
                    MID_ATTACK[sec][w] = d
    print(f"[로드] 복합 중간 공격 {len(MID_ATTACK)}글자")

# ---- 돌림 (첫글자 -> set(단어)) ----
DOLLIM = {}
def load_dollim():
    path = find_file(["dollim.txt", "끄글_돌림*.txt"])
    if not path:
        print("[경고] dollim.txt 파일이 없어 돌림 기능을 끕니다."); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            for w in re.split(r'[,\t]', line.strip()):
                w = w.strip()
                if not w: continue
                o = ord(w[0]) - 0xAC00
                if o < 0 or o > 11171: continue
                DOLLIM.setdefault(w[0], set()).add(w); n += 1
    print(f"[로드] 복합 돌림 {len(DOLLIM)}글자 ({n}개)")

# ---- 끝말잇기 돌림 (같은 글자로 끝나는 자가순환) : 첫글자 -> set(단어) ----
DOLLIM_END = {}
def load_dollim_end():
    path = find_file(["dollim_end.txt"])
    if not path:
        print("[경고] dollim_end.txt 파일을 찾지 못했습니다."); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if not w: continue
            o = ord(w[0]) - 0xAC00
            if o < 0 or o > 11171: continue
            DOLLIM_END.setdefault(w[0], set()).add(w); n += 1
    print(f"[로드] 복합 끝말 돌림 {len(DOLLIM_END)}글자 ({n}개)")


# =====================================================================
# 표준(신표국) 사전 — 복합 자료와 절대 섞지 않습니다.
# =====================================================================

STD_LONGEST = {}      # 첫글자 -> 최장 단어 30개
STD_ENDWORDS = {}     # 끝글자 -> [그 글자로 끝나는 단어들]
STD_STARTCOUNT = {}   # 글자 -> 그 글자로 시작하는 단어 수
STD_FIRST = {}        # 첫글자 -> [그 글자로 시작하는 공격·한방 단어]
STD_ONESHOT = set()   # 한방
STD_ATTACK = set()    # 공격 (한방 제외)
STD_DOLLIM_END = {}   # 첫글자 -> set(자가순환 단어)
STD_FIRSTWORDS = {}   # 첫글자 -> [단어] (대국용)
STD_READY = False

def load_standard_words():
    global STD_READY
    path = find_file(["standard_words.txt"])
    if not path:
        print("[경고] standard_words.txt 파일이 없어 표준 모드를 끕니다."); return
    KEEP = 30
    heaps = {}; n = 0
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            w = line.strip()
            if not w: continue
            lo = ord(w[-1]) - 0xAC00
            if 0 <= lo <= 11171:
                STD_ENDWORDS.setdefault(w[-1], []).append(w)
            o = ord(w[0]) - 0xAC00
            if o < 0 or o > 11171: continue
            STD_STARTCOUNT[w[0]] = STD_STARTCOUNT.get(w[0], 0) + 1
            if is_self_loop(w):
                STD_DOLLIM_END.setdefault(w[0], set()).add(w)
            h = heaps.setdefault(w[0], [])
            key = (len(w), w)
            if len(h) < KEEP: heapq.heappush(h, key)
            elif key > h[0]: heapq.heapreplace(h, key)
            n += 1
    for syl, h in heaps.items():
        STD_LONGEST[syl] = [w for _, w in sorted(h, reverse=True)]
    STD_READY = True
    print(f"[로드] 표준 단어 {n}개 ({len(STD_LONGEST)}글자, 글자별 최장 {KEEP})")

def load_standard_special():
    path = find_file(["standard_special.json"])
    if not path:
        print("[경고] standard_special.json 파일이 없어 표준 공격 자료를 끕니다."); return
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    STD_ONESHOT.update(data.get("oneShots", []))
    STD_ATTACK.update(w for w in data.get("attacks", []) if w not in STD_ONESHOT)
    for w in STD_ONESHOT | STD_ATTACK:
        if not w: continue
        o = ord(w[0]) - 0xAC00
        if o < 0 or o > 11171: continue
        STD_FIRST.setdefault(w[0], []).append(w)
    print(f"[로드] 표준 한방 {len(STD_ONESHOT)}개 · 공격 {len(STD_ATTACK)}개")


# ---- 표준 중간말잇기 공격 자료 ----
STD_MID_ATTACK = {}   # 음절 -> {단어: 깊이}
def load_standard_mid():
    path = find_file(["standard_mid_attack.txt"])
    if not path:
        print("[경고] standard_mid_attack.txt 파일이 없어 표준 중간말잇기를 끕니다."); return
    sec = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1]; STD_MID_ATTACK.setdefault(sec, {}); continue
            m = re.match(r'깊이\s*(\d+)\s*[:：]\s*(.*)', s)
            if not m or sec is None: continue
            d = int(m.group(1))
            for w in m.group(2).split(','):
                w = w.strip()
                if w and (w not in STD_MID_ATTACK[sec] or d < STD_MID_ATTACK[sec][w]):
                    STD_MID_ATTACK[sec][w] = d
    total = len({w for v in STD_MID_ATTACK.values() for w in v})
    print(f"[로드] 표준 중간 공격 {len(STD_MID_ATTACK)}글자 ({total}단어)")


# ---- 루트 학습 자료 (신엜 루트 탐색기 v1.16 과 같은 계산) ----
ROUTE_CORE = None
ROUTE_READY = False
ROUTE_DEPTH = 24
ROUTE_SEQUENCE_LENGTHS = (4, 6, 8)
# 실전 연결에 사용하는 자료 색인입니다. 화면에는 선수 이름을 표시하지 않습니다.
ROUTE_SOURCE_INDEX = 2

def load_route_learning():
    global ROUTE_CORE, ROUTE_READY
    main_path = find_file(["standard_route_learning.json"])
    policy_path = find_file(["standard_recent_policy.json"])
    special_path = find_file(["standard_special.json"])
    if not (main_path and policy_path and special_path and STD_READY):
        print("[경고] 루트 학습 자료가 없어 !루트 기능을 끕니다."); return

    learning = rq.load_learning(main_path)
    recent_path = find_file(["standard_route_learning_recent.json"])
    recent = rq.load_learning(recent_path) if recent_path else None
    with open(policy_path, encoding="utf-8") as fp:
        policy = json.load(fp)
    with open(special_path, encoding="utf-8") as fp:
        special = json.load(fp)

    # 첫 음절 색인은 루트 탐색에서만 쓰므로 여기에서 만듭니다.
    first_words = {}
    path = find_file(["standard_words.txt"])
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            w = line.strip()
            if not w: continue
            first_words.setdefault(w[0], []).append(w)

    STD_FIRSTWORDS.update(first_words)
    ROUTE_CORE = rq.StandardCore(
        first_words, STD_STARTCOUNT,
        set(special.get("attacks", [])), set(special.get("oneShots", [])),
        special.get("routes", {}),
        learning, recent, policy.get("days", 0), policy.get("policy", {}))
    ROUTE_READY = True
    print(f"[로드] 루트 자료 준비 완료 (수순 {len(learning.words):,}단어"
          + (" · 보조층 포함)" if recent else ")"))


# =====================================================================
# 분석
# =====================================================================

def attacks_of(syl):
    m = {}
    for k in syllable_keys(syl):
        for w, d in ATTACK.get(k, {}).items():
            if w not in m or d < m[w]: m[w] = d
    return m

def attacks_of_mid(syl, mode=MODE_COMPLEX):
    table = STD_MID_ATTACK if mode == MODE_STANDARD else MID_ATTACK
    m = {}
    for k in syllable_keys(syl):
        for w, d in table.get(k, {}).items():
            if w not in m or d < m[w]: m[w] = d
    return m

def analyze_mid(syl, mode=MODE_COMPLEX):
    merged = attacks_of_mid(syl, mode)
    hb = {w for w, d in merged.items() if d == 1}
    gk = {w for w, d in merged.items() if d != 1}
    dl = set()
    # 표준 자료에는 중간말잇기 돌림 목록이 없어 복합에서만 계산합니다.
    if mode != MODE_STANDARD:
        for k in syllable_keys(syl):
            dl |= DOLLIM.get(k, set())
        dl -= hb; dl -= gk
    return sorted(hb), sorted(gk), sorted(dl)

def analyze(syl):
    """복합 사전 끝말잇기 분석: 한방·공격·준공격·유도·돌림"""
    merged = attacks_of(syl)
    hb, gk, jk, yd = set(), set(), set(), set()
    dl = set()
    for k in syllable_keys(syl):
        dl |= DOLLIM_END.get(k, set())
    # 공격 데이터: 깊이1=한방, 깊이3+는 끝글자가 준공격/유도면 그쪽, 아니면 공격
    for w, d in merged.items():
        if w in dl: continue
        if d == 1:
            hb.add(w)
        else:
            c = ENDSYL.get(w[-1])
            (jk if c == 'J' else yd if c == 'Y' else gk).add(w)
    # 끝글자 분류 단어(공격 아닌 것 포함): 한방/공격/돌림 아니면 준공격/유도로
    for k in syllable_keys(syl):
        for w, cat in FIRST.get(k, []):
            if w in hb or w in gk or w in dl: continue
            (jk if cat == 'J' else yd).add(w)
    return sorted(hb), sorted(gk), sorted(jk), sorted(yd), sorted(dl)

def analyze_standard(syl):
    """표준 사전 끝말잇기 분석: 한방·공격·돌림
    표준 자료에는 준공격·유도 분류가 없습니다. 복합 자료의 분류를 표준 단어에
    적용하면 서로 다른 사전을 섞게 되므로 그렇게 하지 않습니다."""
    dl = set()
    for k in syllable_keys(syl):
        dl |= STD_DOLLIM_END.get(k, set())
    hb, gk = set(), set()
    for k in syllable_keys(syl):
        for w in STD_FIRST.get(k, []):
            if w in dl: continue
            (hb if w in STD_ONESHOT else gk).add(w)
    return sorted(hb), sorted(gk), sorted(dl)


# =====================================================================
# 모드별 조회 도우미
# =====================================================================

def channel_role(channel_id):
    """고정 배정된 채널이면 (종류, 사전)을, 아니면 (None, None)을 돌려줍니다."""
    return CHANNEL_ROLES.get(channel_id, (None, None))

def mode_of(channel_id):
    kind, fixed = channel_role(channel_id)
    if fixed:
        return fixed
    return CHANNEL_MODE.get(channel_id, DEFAULT_MODE)

def startcount_of(mode):
    return STD_STARTCOUNT if mode == MODE_STANDARD else STARTCOUNT

def longest_of(mode):
    return STD_LONGEST if mode == MODE_STANDARD else LONGEST

def endwords_of(mode):
    return STD_ENDWORDS if mode == MODE_STANDARD else ENDWORDS

def mode_tag(mode):
    return "표준" if mode == MODE_STANDARD else "복합"

def join_cap(words, cap):
    out, used = [], 0
    for w in words:
        add = len(w) + (2 if out else 0)
        if used + add > cap:
            return ", ".join(out) + (f" …외 {len(words)-len(out)}개" if out else "")
        out.append(w); used += add
    return ", ".join(out)

def cont_count(w, mode):
    counts = startcount_of(mode)
    n = 0
    for k in syllable_keys(w[-1]):
        n += counts.get(k, 0)
    return n

def fmt_words(words, mode):
    return [f"{w}({cont_count(w, mode)})" for w in words]

def stamp(embed, mode):
    embed.set_footer(text=f"{mode_tag(mode)} 사전 · 표준두음법칙 적용")
    return embed


# =====================================================================
# 임베드
# =====================================================================

COLOR_MUTED = 0x9AA4B2

def embed_analysis(syl, mode):
    if mode == MODE_STANDARD:
        if not STD_READY:
            return stamp(discord.Embed(
                title="표준 자료를 불러오지 못했습니다",
                description="standard_words.txt 와 standard_special.json 파일을 봇과 같은 폴더에 넣어 주세요.",
                color=COLOR_MUTED), mode)
        hb, gk, dl = analyze_standard(syl)
        if not (hb or gk or dl):
            return stamp(discord.Embed(
                title=f"{syl} → 해당 단어가 없습니다",
                description="한방·공격·돌림이 모두 없어 양보하시는 편이 좋습니다.",
                color=COLOR_MUTED), mode)
        e = discord.Embed(
            title=f"🎯  '{syl}' 분석 · 표준",
            description=f"⚡ 한방 **{len(hb)}** · 🗡️ 공격 **{len(gk)}** · 🔄 돌림 **{len(dl)}**",
            color=0xC2F74A)
        if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(fmt_words(hb, mode), 950), inline=False)
        if gk: e.add_field(name=f"🗡️ 공격 · {len(gk)}개", value=join_cap(fmt_words(gk, mode), 950), inline=False)
        if dl: e.add_field(name=f"🔄 돌림 · {len(dl)}개", value=join_cap(fmt_words(dl, mode), 950), inline=False)
        e.add_field(name="안내", value="표준 자료에는 준공격·유도 분류가 없어 표시하지 않습니다.", inline=False)
        return stamp(e, mode)

    hb, gk, jk, yd, dl = analyze(syl)
    if not (hb or gk or jk or yd or dl):
        return stamp(discord.Embed(
            title=f"{syl} → 해당 단어가 없습니다",
            description="한방·공격·준공격·유도·돌림이 모두 없어 양보하시는 편이 좋습니다.",
            color=COLOR_MUTED), mode)
    e = discord.Embed(
        title=f"🎯  '{syl}' 분석 · 복합",
        description=f"⚡ 한방 **{len(hb)}** · 🗡️ 공격 **{len(gk)}** · 🔥 준공격 **{len(jk)}** · 🎣 유도 **{len(yd)}** · 🔄 돌림 **{len(dl)}**",
        color=0xC2F74A)
    if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(fmt_words(hb, mode), 950), inline=False)
    if gk: e.add_field(name=f"🗡️ 공격 · {len(gk)}개", value=join_cap(fmt_words(gk, mode), 950), inline=False)
    if jk: e.add_field(name=f"🔥 준공격 · {len(jk)}개", value=join_cap(fmt_words(jk, mode), 950), inline=False)
    if yd: e.add_field(name=f"🎣 유도 · {len(yd)}개", value=join_cap(fmt_words(yd, mode), 950), inline=False)
    if dl: e.add_field(name=f"🔄 돌림 · {len(dl)}개", value=join_cap(fmt_words(dl, mode), 950), inline=False)
    return stamp(e, mode)

def embed_hanbang(syl, mode):
    if mode == MODE_STANDARD:
        if not STD_READY:
            return stamp(discord.Embed(title="표준 자료를 불러오지 못했습니다", color=COLOR_MUTED), mode)
        hb, _, _ = analyze_standard(syl)
    else:
        merged = attacks_of(syl)
        hb = sorted(w for w, d in merged.items() if d == 1)
    if not hb:
        return stamp(discord.Embed(title=f"{syl} → 한방이 없습니다", color=COLOR_MUTED), mode)
    return stamp(discord.Embed(
        title=f"⚡  '{syl}' 한방 · {len(hb)}개 · {mode_tag(mode)}",
        description=join_cap(fmt_words(hb, mode), 1800), color=0xFF6B6B), mode)

def embed_jangmun(syl, mode):
    table = longest_of(mode)
    words = []
    for k in syllable_keys(syl):
        words += table.get(k, [])
    words = sorted(set(words), key=lambda w: (-len(w), w))[:30]
    if not words:
        return stamp(discord.Embed(title=f"{syl} → 단어가 없습니다", color=COLOR_MUTED), mode)
    lines = [f"**{i+1}.** {w}  `{len(w)}자`" for i, w in enumerate(words)]
    return stamp(discord.Embed(
        title=f"📏  '{syl}' 로 시작하는 최장 단어 TOP {len(words)} · {mode_tag(mode)}",
        description="\n".join(lines), color=0x5AC8FA), mode)

MAX_PAGES = 15   # 도배 방지: 최대 이만큼 메시지로 나눠 보냅니다.

def jonggyeol_embeds(syl, mode):
    """끝나는 단어 전체를 여러 임베드로 나눠 돌려줍니다."""
    words = endwords_of(mode).get(syl, [])
    if not words:
        return [stamp(discord.Embed(title=f"-{syl} 로 끝나는 단어가 없습니다", color=COLOR_MUTED), mode)]
    words = sorted(words, key=lambda w: (len(w), w))
    total = len(words)
    pages = []
    cur, used = [], 0
    for w in words:
        add_len = len(w) + 2
        if used + add_len > 3600 and cur:
            pages.append(cur); cur, used = [], 0
        cur.append(w); used += add_len
    if cur: pages.append(cur)

    embeds = []
    shown = 0
    for i, pg in enumerate(pages[:MAX_PAGES]):
        shown += len(pg)
        title = f"🏁  '-{syl}' 로 끝나는 단어 · {total}개 · {mode_tag(mode)}"
        if len(pages) > 1:
            title += f"  ({i+1}/{min(len(pages), MAX_PAGES)})"
        embeds.append(stamp(discord.Embed(title=title, description=", ".join(pg), color=0x00C2A8), mode))
    if len(pages) > MAX_PAGES:
        left = total - shown
        embeds.append(stamp(discord.Embed(
            description=f"…그 외 {left}개가 더 있습니다. 너무 많아 {MAX_PAGES}개 메시지까지만 표시합니다.",
            color=COLOR_MUTED), mode))
    return embeds

def embed_jangmun_end(syl, mode):
    words = endwords_of(mode).get(syl, [])
    if not words:
        return stamp(discord.Embed(title=f"-{syl} 로 끝나는 단어가 없습니다", color=COLOR_MUTED), mode)
    words = sorted(words, key=lambda w: (-len(w), w))[:30]
    lines = [f"**{i+1}.** {w}  `{len(w)}자`" for i, w in enumerate(words)]
    return stamp(discord.Embed(
        title=f"📏🏁  '-{syl}' 로 끝나는 최장 단어 TOP {len(words)} · {mode_tag(mode)}",
        description="\n".join(lines), color=0x00C2A8), mode)

def embed_mid(syl, mode):
    if mode == MODE_STANDARD and not STD_MID_ATTACK:
        return stamp(discord.Embed(
            title="표준 중간말잇기 자료를 불러오지 못했습니다",
            description="standard_mid_attack.txt 파일을 봇과 같은 폴더에 넣어 주세요.",
            color=COLOR_MUTED), mode)
    hb, gk, dl = analyze_mid(syl, mode)
    if not (hb or gk or dl):
        return stamp(discord.Embed(
            title=f"{syl} → 해당 단어가 없습니다",
            description="중간말잇기 한방·공격이 모두 없어 양보하시는 편이 좋습니다.",
            color=COLOR_MUTED), mode)
    counts = f"⚡ 한방 **{len(hb)}**    ·    🗡️ 공격 **{len(gk)}**"
    if mode != MODE_STANDARD:
        counts += f"    ·    🔄 돌림 **{len(dl)}**"
    e = discord.Embed(
        title=f"🔗  '{syl}' 중간말잇기 · {mode_tag(mode)}",
        description=counts,
        color=0xB07CFF)
    if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(fmt_words(hb, mode), 950), inline=False)
    if gk: e.add_field(name=f"🗡️ 공격 · {len(gk)}개", value=join_cap(fmt_words(gk, mode), 950), inline=False)
    if dl: e.add_field(name=f"🔄 돌림 · {len(dl)}개", value=join_cap(fmt_words(dl, mode), 950), inline=False)
    if mode == MODE_STANDARD:
        e.add_field(name="안내", value="표준 자료에는 중간말잇기 돌림 목록이 없어 표시하지 않습니다.",
                    inline=False)
    return stamp(e, mode)

def legal_candidates(syl, shield, used=None, history=()):
    """보호막 조건을 만족하는 후보를 추천 순서로 돌려줍니다."""
    used = set(used or ())
    words = ROUTE_CORE.words_for(syl, used)
    rows = [c for c in rq.analyze_candidates(ROUTE_CORE, words, syl, shield, used,
                                             True, history) if c["legal"]]
    rows.sort(key=rq.sort_key)
    return rows

def parse_shield_state(text):
    """`템11` 처럼 음절과 보호막이 붙은 표기를 읽습니다."""
    t = re.sub(r"\s+", "", text)
    m = re.match(r"^(.)(\d{1,2})$", t)
    if not m: return None
    shield = int(m.group(2))
    if shield < 0 or shield > 12: return None
    if dec(m.group(1)) is None: return None
    return m.group(1), shield

def format_sequence(words, shield):
    """수순을 `11 템포슈붕 → 10 붕사땜` 처럼 보호막과 함께 적습니다."""
    parts = []
    for i, w in enumerate(words):
        parts.append(f"`{max(0, shield - i)}` {w}")
    return " → ".join(parts)

def embed_route(syl, shield, only_length=None):
    if not ROUTE_READY:
        return discord.Embed(
            title="루트 자료를 불러오지 못했습니다",
            description="standard_route_learning.json 과 standard_recent_policy.json 파일을 봇과 같은 폴더에 넣어 주세요.",
            color=COLOR_MUTED)

    lengths = (only_length,) if only_length else ROUTE_SEQUENCE_LENGTHS
    e = discord.Embed(
        title=f"🧭  '{syl}{shield}' 루트",
        description=f"끝말 **{syl}** · 보호막 **{shield}** 에서 이어지는 수순입니다.",
        color=0xB07CFF)

    found = 0
    for length in lengths:
        rows = rq.state_sequences(ROUTE_CORE.learning, syl, shield,
                                  ROUTE_SOURCE_INDEX, length, limit=5)
        if not rows: continue
        found += len(rows)
        lines = [format_sequence(r["words"], r["shield"]) for r in rows]
        e.add_field(name=f"🔗 연결 수순 · {length}수", value="\n".join(lines)[:1024], inline=False)

    # 추천 단어는 실전 연결이 있든 없든 항상 함께 보여 줍니다.
    candidates = legal_candidates(syl, shield)
    if candidates:
        lines = [f"**{i}. {c['word']}** · 추천 점수 `{c['recommendationScore']}` "
                 f"· 후속 {c['followCount']:,}"
                 for i, c in enumerate(candidates[:8], 1)]
        head = "" if found else "이 상태에서 이어지는 수순을 찾지 못했습니다.\n"
        e.add_field(name="⭐ 추천 단어", value=(head + "\n".join(lines))[:1024], inline=False)
    else:
        e.add_field(name="⭐ 추천 단어",
                    value="이 상태에서 보호막 조건을 만족하는 후보가 없습니다.", inline=False)

    route = rq.build_auto_route(ROUTE_CORE, syl, shield, depth=ROUTE_DEPTH)
    if route:
        words = [w for w, _ in route]
        e.add_field(name=f"🤖 인공지능 예상 계산 · 예상 {len(route)}수",
                    value=format_sequence(words, shield)[:1024], inline=False)
    else:
        e.add_field(name="🤖 인공지능 예상 계산",
                    value="이어지는 합법 후보를 찾지 못했습니다.", inline=False)

    e.set_footer(text="표준 사전 · 표준두음법칙 적용")
    return e

# ---------------------------------------------------------------------
# 눌러서 수순을 만들어 가는 탐색 (사이트의 후보 목록과 같은 방식)
# ---------------------------------------------------------------------
SEARCH_TIMEOUT = 300      # 초 단위. 이 시간이 지나면 버튼을 잠급니다.
SEARCH_BUTTONS = 10       # 한 번에 보여 줄 후보 버튼 수 (한 줄 5개 × 2줄)

class PickButton(discord.ui.Button):
    def __init__(self, view_ref, candidate, index, row):
        super().__init__(
            label=f"{index}. {candidate['word']}"[:80],
            style=discord.ButtonStyle.success if index == 1 else discord.ButtonStyle.secondary,
            row=row)
        self.view_ref = view_ref
        self.candidate = candidate

    async def callback(self, interaction):
        await self.view_ref.advance(interaction, self.candidate)


class ControlButton(discord.ui.Button):
    def __init__(self, view_ref, label, action, style, disabled=False):
        super().__init__(label=label, style=style, row=2, disabled=disabled)
        self.view_ref = view_ref
        self.action = action

    async def callback(self, interaction):
        await self.view_ref.control(interaction, self.action)


class RouteSearchView(discord.ui.View):
    """후보를 눌러 한 수씩 이어 가며 수순을 만드는 화면입니다."""

    def __init__(self, user_id, current, shield):
        super().__init__(timeout=SEARCH_TIMEOUT)
        self.user_id = user_id
        self.start = (current, shield)
        self.current = current
        self.shield = shield
        self.history = []     # [(단어, 그때의 보호막, 그때의 음절)]
        self.used = set()
        self.candidates = []
        self.message = None   # 시간이 지나면 버튼을 잠그려고 보관합니다.
        self.refresh()

    # -- 상태 계산 --------------------------------------------------
    def refresh(self):
        self.candidates = legal_candidates(self.current, self.shield,
                                           self.used, self.history)
        self.clear_items()
        for i, cand in enumerate(self.candidates[:SEARCH_BUTTONS], 1):
            self.add_item(PickButton(self, cand, i, row=0 if i <= 5 else 1))
        self.add_item(ControlButton(self, "↩ 이전 수", "back",
                                    discord.ButtonStyle.secondary,
                                    disabled=not self.history))
        self.add_item(ControlButton(self, "↻ 처음부터", "reset",
                                    discord.ButtonStyle.secondary,
                                    disabled=not self.history))
        self.add_item(ControlButton(self, "🤖 예상 수순", "auto",
                                    discord.ButtonStyle.primary))

    def embed(self, auto_route=None):
        e = discord.Embed(
            title=f"🔎  '{self.current}{self.shield}' 탐색",
            color=0x5AC8FA)
        if not self.history:
            e.description = (f"끝말 **{self.current}** · 보호막 **{self.shield}** 에서 시작합니다.\n"
                             "아래 후보를 누르면 보호막이 1 줄어든 다음 상태로 이어집니다.")

        if self.candidates:
            lines = []
            for i, c in enumerate(self.candidates[:SEARCH_BUTTONS], 1):
                mark = " ⚡" if c["oneShot"] else (" 🗡️" if c["attack"] else "")
                lines.append(f"**{i}. {c['word']}**{mark} · 점수 `{c['recommendationScore']}` "
                             f"· 끝말 {c['end']} · 후속 {c['followCount']:,}")
            e.add_field(name="⭐ 추천 후보", value="\n".join(lines)[:1024], inline=False)
        else:
            e.add_field(name="⭐ 추천 후보",
                        value="보호막 조건을 만족하는 후보가 없습니다. 이 상태에서는 이어 갈 수 없습니다.",
                        inline=False)

        if auto_route:
            words = [w for w, _ in auto_route]
            e.add_field(name=f"🤖 인공지능 예상 계산 · 예상 {len(auto_route)}수",
                        value=format_sequence(words, self.shield)[:1024], inline=False)

        # 지나온 경로는 맨 아래에 둡니다. 모바일에서 버튼 바로 위라 위로 올리지 않아도 보입니다.
        if self.history:
            words = [w for w, _, _ in self.history]
            e.add_field(name=f"🧭 현재 경로 · {len(self.history)}수",
                        value=(format_sequence(words, self.start[1])
                               + f" → **{self.current}{self.shield}**")[:1024],
                        inline=False)

        e.set_footer(text="표준 사전 · 표준두음법칙 적용 · 시작하신 분만 누르실 수 있습니다")
        return e

    # -- 버튼 처리 --------------------------------------------------
    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "이 탐색을 시작하신 분만 누르실 수 있습니다. "
                "직접 쓰시려면 `!탐색` 으로 새로 시작해 주세요.", ephemeral=True)
            return False
        return True

    async def advance(self, interaction, candidate):
        self.history.append((candidate["word"], self.shield, self.current))
        self.used.add(candidate["word"])
        self.current = candidate["end"]
        self.shield = max(0, self.shield - 1)
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def control(self, interaction, action):
        if action == "back" and self.history:
            word, shield, current = self.history.pop()
            self.used.discard(word)
            self.current, self.shield = current, shield
            self.refresh()
            await interaction.response.edit_message(embed=self.embed(), view=self)
        elif action == "reset":
            self.current, self.shield = self.start
            self.history.clear()
            self.used.clear()
            self.refresh()
            await interaction.response.edit_message(embed=self.embed(), view=self)
        elif action == "auto":
            await interaction.response.defer()
            route = rq.build_auto_route(ROUTE_CORE, self.current, self.shield,
                                        depth=ROUTE_DEPTH, used=self.used,
                                        history=self.history)
            await interaction.edit_original_response(embed=self.embed(route), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                # 메시지가 지워졌으면 잠글 것도 없습니다.
                pass


# ---------------------------------------------------------------------
# 대국 (훈련실: 사람 대 봇 / 경기장: 사람 대 사람)
# ---------------------------------------------------------------------
GAMES = gm.GameRegistry()

def missing_data_notice(mode):
    """어떤 파일이 없어서 대국을 못 하는지 알려 줍니다."""
    if mode == MODE_STANDARD:
        need = "standard_words.txt, standard_special.json, standard_route_learning.json"
    else:
        need = "words.txt"
    return (f"{mode} 자료를 불러오지 못해 대국을 시작할 수 없습니다.\n"
            f"봇과 같은 폴더에 **{need}** 파일이 있는지 확인해 주세요.")

def game_dictionary(mode):
    """모드에 맞는 대국용 사전을 만듭니다. 두 사전은 서로 섞지 않습니다."""
    if mode == MODE_STANDARD:
        if not ROUTE_READY: return None
        return gm.StandardDictionary(ROUTE_CORE)
    if not ALLWORDS: return None
    return gm.ComplexDictionary(ALLWORDS, STARTCOUNT, FIRSTWORDS,
                                ATTACK, ENDSYL, FIRST, DOLLIM_END)

async def schedule_turn_timeout(game, channel):
    """제한 시간 안에 두지 못하면 그 자리에서 패배로 끝냅니다."""
    game.timer_token += 1
    token = game.timer_token
    async def waiter():
        try:
            await asyncio.sleep(gm.TURN_SECONDS)
        except asyncio.CancelledError:
            return
        if game.finished or game.timer_token != token:
            return
        loser = game.actor_name
        game.finish(game.opponent_index(),
                    f"{loser} 님이 {gm.TURN_SECONDS}초 안에 두지 못했습니다.")
        GAMES.drop(game.channel_id)
        await channel.send(embed=game.board())
    game.cancel_timer()
    game.timer = asyncio.create_task(waiter())

async def run_bot_turn(game, channel):
    """봇 차례를 처리합니다. 둘 수 없으면 봇이 집니다."""
    await asyncio.sleep(gm.BOT_THINK_SECONDS)
    word, note = game.dictionary.bot_move(
        game.current, game.shield, game.used,
        [(w, sh, "") for w, sh, _who, _n in game.history])
    if not word:
        game.finish(game.opponent_index(),
                    f"{game.actor_name} 이(가) 이을 단어를 찾지 못했습니다.")
        GAMES.drop(game.channel_id)
        await channel.send(embed=game.board())
        return
    game.apply(word, note)
    label = f"{note} " if note else ""
    notice = f"{game.names[1 - game.turn]} 이(가) {label}**{word}** 을(를) 냈습니다."
    if not game.dictionary.has_legal_move(game.current, game.shield, game.used):
        game.finish(1 - game.turn, f"{game.actor_name} 님이 이을 단어를 찾을 수 없습니다.")
        GAMES.drop(game.channel_id)
        await channel.send(embed=game.board(notice))
        return
    await channel.send(embed=game.board(notice))
    await schedule_turn_timeout(game, channel)

async def begin_game(channel, dictionary, players, names):
    syllable = gm.pick_start_syllable(dictionary)
    game = gm.Game(channel.id, dictionary, players, names, syllable)
    GAMES.put(game)
    notice = (f"제시 글자는 **{syllable}** 입니다.\n"
              f"선공은 **{names[0]}** 입니다. 채팅창에 단어만 입력해 주세요.")
    await channel.send(embed=game.board(notice))
    if game.is_bot_turn():
        await run_bot_turn(game, channel)
    else:
        await schedule_turn_timeout(game, channel)

async def handle_game_word(game, msg):
    """대국 중 채팅으로 들어온 단어를 처리합니다."""
    word = msg.content.strip()
    if game.actor != msg.author.id:
        return
    reason = game.dictionary.legal(word, game.current, game.shield, game.used)
    if reason:
        await msg.channel.send(f"{msg.author.mention} {reason}")
        return
    game.cancel_timer()
    game.apply(word)
    notice = f"{msg.author.display_name} 님이 **{word}** 을(를) 냈습니다."
    if not game.dictionary.has_legal_move(game.current, game.shield, game.used):
        game.finish(1 - game.turn, f"{game.actor_name} 님이 이을 단어를 찾을 수 없습니다.")
        GAMES.drop(game.channel_id)
        await msg.channel.send(embed=game.board(notice))
        return
    if game.is_bot_turn():
        await msg.channel.send(embed=game.board(notice))
        await run_bot_turn(game, msg.channel)
    else:
        await msg.channel.send(embed=game.board(notice))
        await schedule_turn_timeout(game, msg.channel)


class JoinView(discord.ui.View):
    """경기장에서 상대를 기다리는 참가 버튼입니다."""

    def __init__(self, host_id, host_name, dictionary):
        super().__init__(timeout=180)
        self.host_id = host_id
        self.host_name = host_name
        self.dictionary = dictionary
        self.message = None

    @discord.ui.button(label="⚔ 참가하기", style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        if interaction.user.id == self.host_id:
            await interaction.response.send_message(
                "상대를 기다리는 중입니다. 다른 분이 눌러 주셔야 합니다.", ephemeral=True)
            return
        if GAMES.get(interaction.channel_id):
            await interaction.response.send_message(
                "이 채널에서 이미 대국이 진행 중입니다.", ephemeral=True)
            return
        button.disabled = True
        await interaction.response.edit_message(view=self)
        names = [self.host_name, interaction.user.display_name]
        players = [self.host_id, interaction.user.id]
        if random.random() < 0.5:      # 선공은 무작위로 정합니다.
            names.reverse(); players.reverse()
        self.stop()
        await begin_game(interaction.channel, self.dictionary, players, names)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


def embed_mode(mode, changed=False, role=None):
    if mode == MODE_STANDARD:
        detail = ("신표국 표준 자료를 사용합니다.\n"
                  "한방·공격·돌림·장문·종결·중간말잇기를 지원하며, 준공격·유도는 지원하지 않습니다.")
    else:
        detail = ("기존 복합 자료를 사용합니다.\n"
                  "한방·공격·준공격·유도·돌림·장문·종결·중간말잇기를 모두 지원합니다.")
    title = f"사전 모드를 {mode_tag(mode)} 으로 바꿨습니다" if changed else f"현재 사전 모드는 {mode_tag(mode)} 입니다"
    e = discord.Embed(title=f"📚  {title}", description=detail, color=0xC2F74A)
    if role:
        if role == TRAINING:
            how = "`!시작` 또는 `!대결` 로 봇과 겨루실 수 있습니다."
        elif role == ARENA:
            how = "`!시작` 또는 `!경기` 로 상대를 기다리실 수 있습니다."
        else:
            how = "`!루트`·`!탐색`·`!공격` 등 조회 명령을 쓰시는 채널입니다."
        e.add_field(name="채널 배정",
                    value=f"이 채널은 **{role} · {mode_tag(mode)} 사전** 으로 고정돼 있습니다.\n{how}",
                    inline=False)
    else:
        e.add_field(name="바꾸는 방법", value="`!모드 표준` 또는 `!모드 복합` 을 입력해 주세요.", inline=False)
    return stamp(e, mode)


# =====================================================================
# 디스코드
# =====================================================================

intents = discord.Intents.default(); intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[로그인] {client.user}")
    print(f"[제한] 서버={'전체' if GUILD_ID == 0 else GUILD_ID} · 채널={'전체' if CHANNEL_ID == 0 else CHANNEL_ID}")
    print(f"[모드] 기본 사전={mode_tag(DEFAULT_MODE)} · 표준 사용 가능={'예' if STD_READY else '아니요'}")

def first_syllable(arg, command):
    arg = arg.strip()
    if not arg:
        return None, f"사용법은 `{command} <글자>` 입니다. 예를 들어 `{command} 기` 처럼 입력해 주세요."
    s = arg[0]
    if dec(s) is None:
        return None, f"완성된 한 글자를 입력해 주세요. 예를 들어 `{command} 기` 처럼 입력해 주세요."
    return s, None

HELP_TEXT = (
    "**끄투 봇 명령어입니다.**\n"
    "`!시작` — 이 채널 배정대로 대국 시작 (훈련실·경기장 채널)\n"
    "`!대결` — 봇과 끝말잇기 대국 (훈련실)\n"
    "`!경기` — 다른 분과 끝말잇기 대국 (경기장)\n"
    "`!기권` — 진행 중인 대국을 포기합니다\n"
    "`!모드` — 현재 채널의 사전 모드를 확인합니다\n"
    "`!모드 표준` · `!모드 복합` — 사전 모드를 바꿉니다\n"
    "`!루트 <음절><보호막>` — 연결 수순 4·6·8수 · 추천 단어 · 예상 수순 (표준 자료)\n"
    "`!탐색 <음절><보호막>` — 후보를 눌러 한 수씩 이어 가며 수순 만들기 (표준 자료)\n"
    "`!공격 <글자>` — 끝말잇기 ⚡한방 / 🗡️공격 / 🔥준공격 / 🎣유도 / 🔄돌림\n"
    "`!한방 <글자>` — 한방만 보여 드립니다\n"
    "`!장문 <글자>` — 그 글자로 시작하는 가장 긴 단어\n"
    "`!종결 <글자>` — 그 글자로 끝나는 단어\n"
    "`!장문종결 <글자>` — 그 글자로 끝나는 가장 긴 단어\n"
    "`!중간 <글자>` — 중간말잇기 ⚡한방 / 🗡️공격 / 🔄돌림\n"
    "예시: `!대결 표준`, `!경기`, `!루트 템11`, `!탐색 템11`, `!공격 기`\n"
    "두 모드 모두 표준두음법칙을 적용하며, 복합 자료와 표준 자료는 서로 섞지 않습니다."
)

@client.event
async def on_message(msg):
    if msg.author.bot: return
    if GUILD_ID and (msg.guild is None or msg.guild.id != GUILD_ID): return
    if CHANNEL_ID and msg.channel.id != CHANNEL_ID: return

    c = msg.content.strip()
    mode = mode_of(msg.channel.id)

    # 대국 중이면 명령이 아닌 메시지는 단어 입력으로 봅니다.
    running = GAMES.get(msg.channel.id)
    if running and not c.startswith("!"):
        await handle_game_word(running, msg)
        return

    kind, fixed = channel_role(msg.channel.id)

    if c.startswith("!시작"):
        # 고정 배정된 채널에서는 그 채널의 종류대로 바로 시작합니다.
        if kind == STUDY:
            await msg.channel.send(
                "이 채널은 조회·탐색용입니다. 대국은 훈련실이나 경기장 채널에서 시작해 주세요.")
            return
        if not kind:
            await msg.channel.send(
                "이 채널은 대국 채널로 지정돼 있지 않습니다. "
                "`!대결` (봇과) 또는 `!경기` (사람과) 로 시작해 주세요.")
            return
        c = "!대결" if kind == TRAINING else "!경기"

    if c.startswith("!대결") or c.startswith("!훈련"):
        head = "!대결" if c.startswith("!대결") else "!훈련"
        arg = c[len(head):].strip()
        if fixed:
            chosen = fixed          # 배정된 채널은 사전이 고정입니다.
        else:
            chosen = MODE_STANDARD if arg.startswith(MODE_STANDARD) else (
                     MODE_COMPLEX if arg.startswith(MODE_COMPLEX) else mode)
        if kind == ARENA:
            await msg.channel.send(
                "이 채널은 사람끼리 겨루는 경기장입니다. `!경기` 로 상대를 기다려 주세요.")
            return
        if kind == STUDY:
            await msg.channel.send(
                f"이 채널은 조회·탐색용입니다. 봇과 겨루시려면 훈련실 채널에서 `!대결` 을 입력해 주세요.")
            return
        if GAMES.get(msg.channel.id):
            await msg.channel.send("이 채널에서 이미 대국이 진행 중입니다. `!기권` 으로 끝낼 수 있습니다.")
            return
        book = game_dictionary(chosen)
        if not book:
            await msg.channel.send(missing_data_notice(chosen))
            return
        names = [msg.author.display_name, f"{book.name} 봇"]
        players = [msg.author.id, None]
        if random.random() < 0.5:      # 선공은 무작위로 정합니다.
            names.reverse(); players.reverse()
        await begin_game(msg.channel, book, players, names)
        return

    if c.startswith("!경기"):
        arg = c[len("!경기"):].strip()
        if fixed:
            chosen = fixed          # 배정된 채널은 사전이 고정입니다.
        else:
            chosen = MODE_STANDARD if arg.startswith(MODE_STANDARD) else (
                     MODE_COMPLEX if arg.startswith(MODE_COMPLEX) else mode)
        if kind == TRAINING:
            await msg.channel.send(
                "이 채널은 봇과 겨루는 훈련실입니다. `!대결` 로 시작해 주세요.")
            return
        if kind == STUDY:
            await msg.channel.send(
                "이 채널은 조회·탐색용입니다. 겨루시려면 경기장 채널에서 `!경기` 를 입력해 주세요.")
            return
        if GAMES.get(msg.channel.id):
            await msg.channel.send("이 채널에서 이미 대국이 진행 중입니다. `!기권` 으로 끝낼 수 있습니다.")
            return
        book = game_dictionary(chosen)
        if not book:
            await msg.channel.send(missing_data_notice(chosen))
            return
        view = JoinView(msg.author.id, msg.author.display_name, book)
        e = discord.Embed(
            title="⚔  상대를 기다리고 있습니다",
            description=(f"**{msg.author.display_name}** 님이 {book.name} 사전 대국을 열었습니다.\n"
                         "아래 버튼을 누르시면 바로 시작합니다. 선공은 무작위로 정합니다."),
            color=0xB07CFF)
        e.set_footer(text=f"{book.name} 사전 · 보호막 {gm.START_SHIELD}부터 시작 · 3분 안에 참가해 주세요")
        view.message = await msg.channel.send(embed=e, view=view)
        return

    if c.startswith("!기권") or c.startswith("!포기"):
        if not running:
            await msg.channel.send("이 채널에는 진행 중인 대국이 없습니다.")
            return
        if msg.author.id not in [p for p in running.players if p]:
            await msg.channel.send("대국에 참가하신 분만 기권하실 수 있습니다.")
            return
        loser = running.players.index(msg.author.id)
        running.finish(1 - loser, f"{msg.author.display_name} 님이 기권하셨습니다.")
        GAMES.drop(msg.channel.id)
        await msg.channel.send(embed=running.board())
        return

    if c.startswith("!모드"):
        arg = c[len("!모드"):].strip()
        if fixed and arg:
            await msg.channel.send(
                f"이 채널은 **{kind} · {fixed} 사전** 으로 고정돼 있어 모드를 바꿀 수 없습니다. "
                "다른 사전을 쓰시려면 해당 채널로 옮겨 주세요.")
            return
        if not arg:
            await msg.channel.send(embed=embed_mode(mode, role=kind))
        elif arg.startswith(MODE_STANDARD):
            if not STD_READY:
                await msg.channel.send(
                    "표준 자료를 불러오지 못해 표준 모드로 바꿀 수 없습니다. "
                    "standard_words.txt 와 standard_special.json 파일을 확인해 주세요.")
            else:
                CHANNEL_MODE[msg.channel.id] = MODE_STANDARD
                await msg.channel.send(embed=embed_mode(MODE_STANDARD, changed=True, role=kind))
        elif arg.startswith(MODE_COMPLEX):
            CHANNEL_MODE[msg.channel.id] = MODE_COMPLEX
            await msg.channel.send(embed=embed_mode(MODE_COMPLEX, changed=True, role=kind))
        else:
            await msg.channel.send("`!모드 표준` 또는 `!모드 복합` 으로 입력해 주세요.")
        return

    if c.startswith("!탐색"):
        arg = c[len("!탐색"):].strip()
        if not ROUTE_READY:
            await msg.channel.send(
                "표준 루트 자료를 불러오지 못해 탐색을 시작할 수 없습니다. "
                "standard_route_learning.json 파일을 확인해 주세요.")
            return
        if not arg:
            await msg.channel.send(
                "사용법은 `!탐색 <음절><보호막>` 입니다. 예를 들어 `!탐색 템11` 처럼 입력해 주세요.")
            return
        state = parse_shield_state(arg.split()[0])
        if not state:
            await msg.channel.send(
                "음절과 보호막을 붙여서 입력해 주세요. 예를 들어 `!탐색 템11` 처럼 입력해 주세요. "
                "보호막은 0부터 12까지입니다.")
            return
        view = RouteSearchView(msg.author.id, state[0], state[1])
        view.message = await msg.channel.send(embed=view.embed(), view=view)
        return

    if c.startswith("!루트"):
        arg = c[len("!루트"):].strip()
        if not arg:
            await msg.channel.send(
                "사용법은 `!루트 <음절><보호막>` 입니다. 예를 들어 `!루트 템11` 처럼 입력해 주세요.\n"
                "특정 길이만 보시려면 `!루트 템11 6수` 처럼 뒤에 수를 붙여 주세요.")
            return
        parts = arg.split()
        state = parse_shield_state(parts[0])
        if not state:
            await msg.channel.send(
                "음절과 보호막을 붙여서 입력해 주세요. 예를 들어 `!루트 템11` 처럼 입력해 주세요. "
                "보호막은 0부터 12까지입니다.")
            return
        only = None
        if len(parts) > 1:
            m = re.match(r"^(\d+)수?$", parts[1])
            if m and int(m.group(1)) in ROUTE_SEQUENCE_LENGTHS:
                only = int(m.group(1))
            else:
                await msg.channel.send("수순 길이는 `4수`, `6수`, `8수` 중에서 입력해 주세요.")
                return
        await msg.channel.send(embed=embed_route(state[0], state[1], only))
        return

    if c.startswith("!공격"):
        s, err = first_syllable(c[len("!공격"):], "!공격")
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_analysis(s, mode))
    elif c.startswith("!한방"):
        s, err = first_syllable(c[len("!한방"):], "!한방")
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_hanbang(s, mode))
    elif c.startswith("!장문종결"):
        s, err = first_syllable(c[len("!장문종결"):], "!장문종결")
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_jangmun_end(s, mode))
    elif c.startswith("!장문"):
        s, err = first_syllable(c[len("!장문"):], "!장문")
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_jangmun(s, mode))
    elif c.startswith("!중간"):
        s, err = first_syllable(c[len("!중간"):], "!중간")
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_mid(s, mode))
    elif c.startswith("!종결"):
        s, err = first_syllable(c[len("!종결"):], "!종결")
        if err:
            await msg.channel.send(err)
        else:
            for e in jonggyeol_embeds(s, mode):
                await msg.channel.send(embed=e)
    elif c in ("!도움", "!help", "!명령어"):
        await msg.channel.send(HELP_TEXT)


load_attack(); load_endcat(); load_words(); load_mid(); load_dollim(); load_dollim_end()
load_standard_words(); load_standard_special(); load_standard_mid(); load_route_learning()

token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("[에러] 환경변수 DISCORD_TOKEN 이 없습니다. Railway Variables 에 넣어 주세요.")
else:
    client.run(token)
