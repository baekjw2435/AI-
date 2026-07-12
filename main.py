# -*- coding: utf-8 -*-
# 끄투 봇
# !공격 <글자>  → ⚡한방 / 🔥준공격 / 🎣유도  (각각 별도 박스)
# !한방 <글자>  → 한방만
# !장문 <글자>  → 그 글자로 시작하는 가장 긴 단어 TOP 30
# 규칙: 깊이 무시(깊이1만 한방). 준공격/유도 = 시작글자 + 끝글자가 준공격/유도 목록.

import os, re, glob, heapq
import discord

# ===== 특정 채널만 답하려면 채널 ID 입력 (0 = 전체) =====
CHANNEL_ID = 0
# =====================================================

CHO = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
def dec(ch):
    o = ord(ch) - 0xAC00
    return None if o < 0 or o > 11171 else (o//588, (o%588)//28, o%28)
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

def find_file(pats):
    for pat in pats:
        hit = glob.glob(pat)
        if hit: return hit[0]
    return None

# ---- 공격 데이터 (한방) ----
ATTACK = {}
def load_attack():
    path = find_file(["attack_data.txt", "끄글_공격*.txt", "*공격*.txt"])
    if not path:
        print("[경고] attack_data.txt 못 찾음"); return
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
    print(f"[로드] 공격 {len(ATTACK)}글자")

# ---- 준공격/유도 (끝글자 분류): 첫글자 -> [(단어,'J'/'Y')] ----
FIRST = {}
ENDSYL = {}   # 끝글자 -> 'J'(준공격)/'Y'(유도)
def load_endcat():
    path = find_file(["endcat.txt"])
    if not path:
        print("[경고] endcat.txt 못 찾음"); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip('\n')
            if '\t' not in line: continue
            w, cat = line.split('\t', 1)
            if not w: continue
            FIRST.setdefault(w[0], []).append((w, cat)); ENDSYL[w[-1]] = cat; n += 1
    print(f"[로드] 준공격/유도 {n}단어")

# ---- 장문 (우샘 읽으며 글자별 최장 30개만 메모리 유지) ----
LONGEST = {}
ENDWORDS = {}   # 끝글자 -> [그 글자로 끝나는 단어들]
STARTCOUNT = {}   # 글자 -> 그 글자로 시작하는 단어 수 (이을 수 있는 수)
def load_words():
    path = find_file(["words.txt", "끄글_단어_목록*.txt", "끄글_단어*.txt"])
    if not path:
        print("[경고] words.txt 없음 (장문 꺼짐)"); return
    KEEP = 30
    heaps = {}; n = 0
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            w = line.strip()
            if not w: continue
            lo = ord(w[-1]) - 0xAC00
            if 0 <= lo <= 11171:
                ENDWORDS.setdefault(w[-1], []).append(w)   # 종결용: 끝글자 인덱스
            o = ord(w[0]) - 0xAC00
            if o < 0 or o > 11171: continue
            STARTCOUNT[w[0]] = STARTCOUNT.get(w[0], 0) + 1
            h = heaps.setdefault(w[0], [])
            key = (len(w), w)
            if len(h) < KEEP: heapq.heappush(h, key)
            elif key > h[0]: heapq.heapreplace(h, key)
            n += 1
    for syl, h in heaps.items():
        LONGEST[syl] = [w for _, w in sorted(h, reverse=True)]
    print(f"[로드] 장문 {len(LONGEST)}글자 (원본 {n}단어, 글자별 최장 {KEEP})")

# ---- 중간말잇기 공격 데이터 ----
MID_ATTACK = {}
def load_mid():
    path = find_file(["mid_attack.txt", "끄글_공격_단어_2026070709*.txt"])
    if not path:
        print("[경고] mid_attack.txt 없음 (중간말잇기 꺼짐)"); return
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
    print(f"[로드] 중간 공격 {len(MID_ATTACK)}글자")

# ---- 돌림 (첫글자 -> set(단어)) ----
DOLLIM = {}
def load_dollim():
    path = find_file(["dollim.txt", "끄글_돌림*.txt"])
    if not path:
        print("[경고] dollim.txt 없음 (돌림 꺼짐)"); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            for w in re.split(r'[,\t]', line.strip()):
                w = w.strip()
                if not w: continue
                o = ord(w[0]) - 0xAC00
                if o < 0 or o > 11171: continue
                DOLLIM.setdefault(w[0], set()).add(w); n += 1
    print(f"[로드] 돌림 {len(DOLLIM)}글자 ({n}개)")

# ---- 끝말잇기 돌림 (같은 글자로 끝나는 자가순환) : 첫글자 -> set(단어) ----
DOLLIM_END = {}
def load_dollim_end():
    path = find_file(["dollim_end.txt"])
    if not path:
        print("[경고] dollim_end.txt 없음"); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            w = line.strip()
            if not w: continue
            o = ord(w[0]) - 0xAC00
            if o < 0 or o > 11171: continue
            DOLLIM_END.setdefault(w[0], set()).add(w); n += 1
    print(f"[로드] 끝말 돌림 {len(DOLLIM_END)}글자 ({n}개)")

def attacks_of(syl):
    m = {}
    for k in (syl, dueum(syl)):
        if not k: continue
        for w, d in ATTACK.get(k, {}).items():
            if w not in m or d < m[w]: m[w] = d
    return m

def attacks_of_mid(syl):
    m = {}
    for k in (syl, dueum(syl)):
        if not k: continue
        for w, d in MID_ATTACK.get(k, {}).items():
            if w not in m or d < m[w]: m[w] = d
    return m

def analyze_mid(syl):
    merged = attacks_of_mid(syl)
    hb = {w for w, d in merged.items() if d == 1}
    gk = {w for w, d in merged.items() if d != 1}
    dl = set()
    for k in (syl, dueum(syl)):
        if k: dl |= DOLLIM.get(k, set())
    dl -= hb; dl -= gk
    return sorted(hb), sorted(gk), sorted(dl)

def analyze(syl):
    merged = attacks_of(syl)
    hb, gk, jk, yd = set(), set(), set(), set()
    # 돌림(같은 글자로 끝나는 자가순환)
    dl = set()
    for k in (syl, dueum(syl)):
        if k: dl |= DOLLIM_END.get(k, set())
    # 공격 데이터: 깊이1=한방, 깊이3+는 끝글자가 준공격/유도면 그쪽, 아니면 공격
    for w, d in merged.items():
        if w in dl: continue
        if d == 1:
            hb.add(w)
        else:
            c = ENDSYL.get(w[-1])
            (jk if c == 'J' else yd if c == 'Y' else gk).add(w)
    # 끝글자 분류 단어(공격 아닌 것 포함): 한방/공격/돌림 아니면 준공격/유도로
    for k in (syl, dueum(syl)):
        for w, cat in FIRST.get(k, []):
            if w in hb or w in gk or w in dl: continue
            (jk if cat == 'J' else yd).add(w)
    return sorted(hb), sorted(gk), sorted(jk), sorted(yd), sorted(dl)

def join_cap(words, cap):
    out, used = [], 0
    for w in words:
        add = len(w) + (2 if out else 0)
        if used + add > cap:
            return ", ".join(out) + (f" …외 {len(words)-len(out)}개" if out else "")
        out.append(w); used += add
    return ", ".join(out)

def cont_count(w):
    last = w[-1]
    n = STARTCOUNT.get(last, 0)
    du = dueum(last)
    if du: n += STARTCOUNT.get(du, 0)
    return n
def fmt_words(words):
    return [f"{w}({cont_count(w)})" for w in words]

def embed_analysis(syl):
    hb, gk, jk, yd, dl = analyze(syl)
    if not (hb or gk or jk or yd or dl):
        return discord.Embed(title=f"{syl} → 해당 단어 없음",
                             description="한방·공격·준공격·유도·돌림 모두 없어 (양보)", color=0x9AA4B2)
    e = discord.Embed(title=f"🎯  '{syl}' 분석",
        description=f"⚡ 한방 **{len(hb)}** · 🗡️ 공격 **{len(gk)}** · 🔥 준공격 **{len(jk)}** · 🎣 유도 **{len(yd)}** · 🔄 돌림 **{len(dl)}**",
        color=0xC2F74A)
    if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(fmt_words(hb), 950), inline=False)
    if gk: e.add_field(name=f"🗡️ 공격 · {len(gk)}개", value=join_cap(fmt_words(gk), 950), inline=False)
    if jk: e.add_field(name=f"🔥 준공격 · {len(jk)}개", value=join_cap(fmt_words(jk), 950), inline=False)
    if yd: e.add_field(name=f"🎣 유도 · {len(yd)}개", value=join_cap(fmt_words(yd), 950), inline=False)
    if dl: e.add_field(name=f"🔄 돌림 · {len(dl)}개", value=join_cap(fmt_words(dl), 950), inline=False)
    return e

def embed_hanbang(syl):
    merged = attacks_of(syl)
    hb = sorted(w for w, d in merged.items() if d == 1)
    if not hb:
        return discord.Embed(title=f"{syl} → 한방 없음", color=0x9AA4B2)
    return discord.Embed(title=f"⚡  '{syl}' 한방 · {len(hb)}개",
                         description=join_cap(fmt_words(hb), 1800), color=0xFF6B6B)

def embed_jangmun(syl):
    words = []
    for k in (syl, dueum(syl)):
        if k: words += LONGEST.get(k, [])
    words = sorted(set(words), key=lambda w: (-len(w), w))[:30]
    if not words:
        return discord.Embed(title=f"{syl} → 단어 없음", color=0x9AA4B2)
    lines = [f"**{i+1}.** {w}  `{len(w)}자`" for i, w in enumerate(words)]
    return discord.Embed(title=f"📏  '{syl}' 로 시작하는 최장 단어 TOP {len(words)}",
                         description="\n".join(lines), color=0x5AC8FA)

MAX_PAGES = 15   # 도배 방지: 최대 이만큼 메시지로 나눠 보냄

def jonggyeol_embeds(syl):
    """끝나는 단어 전체를 여러 임베드로 나눠 반환"""
    words = ENDWORDS.get(syl, [])
    if not words:
        return [discord.Embed(title=f"-{syl} 로 끝나는 단어 없음", color=0x9AA4B2)]
    words = sorted(words, key=lambda w: (len(w), w))
    total = len(words)
    # 한 임베드에 약 3600자씩 채우기
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
        title = f"🏁  '-{syl}' 로 끝나는 단어 · {total}개"
        if len(pages) > 1:
            title += f"  ({i+1}/{min(len(pages), MAX_PAGES)})"
        e = discord.Embed(title=title, description=", ".join(pg), color=0x00C2A8)
        embeds.append(e)
    if len(pages) > MAX_PAGES:
        left = total - shown
        embeds.append(discord.Embed(description=f"…그 외 {left}개 더 (너무 많아 {MAX_PAGES}개 메시지까지만 표시)", color=0x9AA4B2))
    return embeds

def embed_mid(syl):
    hb, gk, dl = analyze_mid(syl)
    if not (hb or gk or dl):
        return discord.Embed(title=f"{syl} → 해당 단어 없음",
                             description="중간말잇기 한방·공격·돌림 모두 없어 (양보)", color=0x9AA4B2)
    e = discord.Embed(title=f"🔗  '{syl}' 중간말잇기",
        description=f"⚡ 한방 **{len(hb)}**    ·    🗡️ 공격 **{len(gk)}**    ·    🔄 돌림 **{len(dl)}**",
        color=0xB07CFF)
    if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(fmt_words(hb), 950), inline=False)
    if gk: e.add_field(name=f"🗡️ 공격 · {len(gk)}개", value=join_cap(fmt_words(gk), 950), inline=False)
    if dl: e.add_field(name=f"🔄 돌림 · {len(dl)}개", value=join_cap(fmt_words(dl), 950), inline=False)
    return e

intents = discord.Intents.default(); intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[로그인] {client.user} · 채널제한={'전체' if CHANNEL_ID == 0 else CHANNEL_ID}")

def first_syllable(arg):
    arg = arg.strip()
    if not arg: return None, "사용법: `!공격 <글자>`  (예: `!공격 기`)"
    s = arg[0]
    if dec(s) is None: return None, "완성된 한 글자를 입력해줘  (예: `!공격 기`)"
    return s, None

@client.event
async def on_message(msg):
    if msg.author.bot: return
    if CHANNEL_ID and msg.channel.id != CHANNEL_ID: return
    c = msg.content.strip()
    if c.startswith("!공격"):
        s, err = first_syllable(c[len("!공격"):])
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_analysis(s))
    elif c.startswith("!한방"):
        s, err = first_syllable(c[len("!한방"):])
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_hanbang(s))
    elif c.startswith("!장문"):
        s, err = first_syllable(c[len("!장문"):])
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_jangmun(s))
    elif c.startswith("!중간"):
        s, err = first_syllable(c[len("!중간"):])
        if err: await msg.channel.send(err)
        else:   await msg.channel.send(embed=embed_mid(s))
    elif c.startswith("!종결"):
        s, err = first_syllable(c[len("!종결"):])
        if err:
            await msg.channel.send(err)
        else:
            for e in jonggyeol_embeds(s):
                await msg.channel.send(embed=e)
    elif c in ("!도움", "!help", "!명령어"):
        await msg.channel.send(
            "**끄투 봇**\n"
            "`!공격 <글자>` — 끝말잇기 ⚡한방/🗡️공격/🔥준공격/🎣유도\n"
            "`!중간 <글자>` — 중간말잇기 ⚡한방/🗡️공격/🔄돌림\n"
            "`!한방 <글자>` — 한방만\n"
            "`!장문 <글자>` — 가장 긴 단어\n"
            "`!종결 <글자>` — 그 글자로 끝나는 단어\n"
            "예: `!공격 기`, `!중간 백`, `!장문 기`")

load_attack(); load_endcat(); load_words(); load_mid(); load_dollim(); load_dollim_end()
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("[에러] 환경변수 DISCORD_TOKEN 없음 (Railway Variables에 넣어줘)")
else:
    client.run(token)
