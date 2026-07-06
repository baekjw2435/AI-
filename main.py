# -*- coding: utf-8 -*-
# 끄투 봇
# !공격 <글자>  → ⚡한방 / 🔥준공격 / 🎣유도  3분류 (각각 별도 박스)
# !한방 <글자>  → 한방만
# 규칙: 깊이는 무시(깊이1만 한방). 준공격/유도 = 그 글자로 시작 + 끝글자가 준공격/유도 목록.

import os, re, glob
import discord

# ===== 설정: 특정 채널만 답하려면 채널 ID 입력 (0 = 전체 채널) =====
CHANNEL_ID = 0
# ==============================================================

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

# ---- 공격 데이터 (한방용) ----
ATTACK = {}
def load_attack():
    path = find_file(["attack_data.txt", "끄글_공격*.txt", "*공격*.txt"])
    if not path:
        print("[경고] attack_data.txt 를 못 찾음"); return
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

# ---- 준공격/유도 (끝글자 분류) : 첫글자 -> [(단어, 'J'/'Y')] ----
FIRST = {}
def load_endcat():
    path = find_file(["endcat.txt"])
    if not path:
        print("[경고] endcat.txt 를 못 찾음"); return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip('\n')
            if '\t' not in line: continue
            w, cat = line.split('\t', 1)
            if not w: continue
            FIRST.setdefault(w[0], []).append((w, cat)); n += 1
    print(f"[로드] 준공격/유도 {n}단어")

def attacks_of(syl):
    m = {}
    for k in (syl, dueum(syl)):
        if not k: continue
        for w, d in ATTACK.get(k, {}).items():
            if w not in m or d < m[w]: m[w] = d
    return m

def analyze(syl):
    merged = attacks_of(syl)
    hanbang = {w for w, d in merged.items() if d == 1}
    cand = []
    for k in (syl, dueum(syl)):
        if k: cand += FIRST.get(k, [])
    junak, yudo, seen = [], [], set()
    for w, cat in cand:
        if w in seen: continue
        seen.add(w)
        if w in hanbang: continue
        (junak if cat == 'J' else yudo).append(w)
    return sorted(hanbang), sorted(junak), sorted(yudo)

def join_cap(words, cap):
    out, used = [], 0
    for w in words:
        add = len(w) + (2 if out else 0)
        if used + add > cap:
            return ", ".join(out) + (f" …외 {len(words)-len(out)}개" if out else "")
        out.append(w); used += add
    return ", ".join(out)

def embed_analysis(syl):
    hb, jk, yd = analyze(syl)
    if not (hb or jk or yd):
        return discord.Embed(title=f"{syl} → 해당 단어 없음",
                             description="한방·준공격·유도 모두 없어 (양보)", color=0x9AA4B2)
    e = discord.Embed(title=f"🎯  '{syl}' 분석",
        description=f"⚡ 한방 **{len(hb)}**    ·    🔥 준공격 **{len(jk)}**    ·    🎣 유도 **{len(yd)}**",
        color=0xC2F74A)
    if hb: e.add_field(name=f"⚡ 한방 · {len(hb)}개", value=join_cap(hb, 1000), inline=False)
    if jk: e.add_field(name=f"🔥 준공격 · {len(jk)}개", value=join_cap(jk, 1000), inline=False)
    if yd: e.add_field(name=f"🎣 유도 · {len(yd)}개", value=join_cap(yd, 1000), inline=False)
    return e

def embed_hanbang(syl):
    merged = attacks_of(syl)
    hb = sorted(w for w, d in merged.items() if d == 1)
    if not hb:
        return discord.Embed(title=f"{syl} → 한방 없음", color=0x9AA4B2)
    return discord.Embed(title=f"⚡  '{syl}' 한방 · {len(hb)}개",
                         description=join_cap(hb, 1800), color=0xFF6B6B)

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
    elif c in ("!도움", "!help", "!명령어"):
        await msg.channel.send("**끄투 봇**\n`!공격 <글자>` — ⚡한방 / 🔥준공격 / 🎣유도\n`!한방 <글자>` — 한방만\n예: `!공격 기`, `!공격 폼`")

load_attack(); load_endcat()
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("[에러] 환경변수 DISCORD_TOKEN 없음 (Railway Variables에 넣어줘)")
else:
    client.run(token)
