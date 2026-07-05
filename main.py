# -*- coding: utf-8 -*-
# 끄투 공격 조회 디스코드 봇
# 명령어:  !공격 <글자>   그 글자로 시작하는 공격 단어 (⚡ = 한방/깊이1)
#          !한방 <글자>   그 글자의 한방 단어만
# 깊이는 무시하고, 깊이 1만 한방으로 표시한다.

import os, re, glob
import discord

# ================== 설정 ==================
# 인공지능 채널에서만 답하게 하려면, 채널 ID를 여기 넣어. (0 이면 모든 채널에서 작동)
# 채널 ID 얻는 법: 디스코드 설정 → 고급 → 개발자 모드 ON → 채널 길게 눌러 "채널 ID 복사"
CHANNEL_ID = 0
# ==========================================

# ---- 한글 유틸 (초성/두음) ----
CHO = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']

def dec(ch):
    o = ord(ch) - 0xAC00
    return None if o < 0 or o > 11171 else (o // 588, (o % 588) // 28, o % 28)

def dueum(ch):
    d = dec(ch)
    if not d:
        return None
    c, j, k = d
    if c == 5:  # ㄹ
        if j in (2, 6, 7, 12, 17, 20): return chr(0xAC00 + (11 * 21 + j) * 28 + k)  # ㄹ→ㅇ
        if j in (0, 1, 8, 11, 13, 18): return chr(0xAC00 + (2 * 21 + j) * 28 + k)   # ㄹ→ㄴ
    elif c == 2:  # ㄴ
        if j in (6, 12, 17, 20): return chr(0xAC00 + (11 * 21 + j) * 28 + k)         # ㄴ→ㅇ
    return None

# ---- 공격 데이터 로드 ----
ATTACK = {}  # 글자 -> {단어: 최소깊이}

def find_data_file():
    for pat in ["attack_data.txt", "끄글_공격*.txt", "*공격*.txt"]:
        hit = glob.glob(pat)
        if hit:
            return hit[0]
    return None

def load():
    path = find_data_file()
    if not path:
        print("[경고] 공격 데이터 파일을 못 찾음 (attack_data.txt 를 같이 올렸는지 확인)")
        return
    sec = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                sec = s[1:-1]
                ATTACK.setdefault(sec, {})
                continue
            m = re.match(r'깊이\s*(\d+)\s*[:：]\s*(.*)', s)
            if not m or sec is None:
                continue
            depth = int(m.group(1))
            for w in m.group(2).split(','):
                w = w.strip()
                if w and (w not in ATTACK[sec] or depth < ATTACK[sec][w]):
                    ATTACK[sec][w] = depth
    total = sum(len(v) for v in ATTACK.values())
    print(f"[로드] {len(ATTACK)} 글자, {total} 단어  (파일: {path})")

def attacks_of(syl):
    """받은 글자의 공격 단어 (두음 합쳐 중복 제거). {단어: 깊이}"""
    merged = {}
    for k in (syl, dueum(syl)):
        if not k:
            continue
        for w, d in ATTACK.get(k, {}).items():
            if w not in merged or d < merged[w]:
                merged[w] = d
    return merged

# ---- 응답 포맷 ----
def join_cap(words, cap):
    out, used = [], 0
    for w in words:
        add = len(w) + (2 if out else 0)
        if used + add > cap:
            return ", ".join(out) + (f" …외 {len(words) - len(out)}개" if out else "")
        out.append(w); used += add
    return ", ".join(out)

def reply_gongkyeok(syl):
    merged = attacks_of(syl)
    if not merged:
        return f"**{syl}** → 공격 단어 없음 (양보)"
    hanbang = sorted(w for w, d in merged.items() if d == 1)
    normal  = sorted(w for w, d in merged.items() if d != 1)
    head = f"**{syl}** → 공격 {len(merged)}개" + (f"  ·  ⚡한방 {len(hanbang)}개" if hanbang else "")
    lines = [head]
    if hanbang:
        lines.append("⚡ **한방**: " + join_cap(hanbang, 800))
    if normal:
        lines.append("• 공격: " + join_cap(normal, 900))
    return "\n".join(lines)

def reply_hanbang(syl):
    merged = attacks_of(syl)
    hanbang = sorted(w for w, d in merged.items() if d == 1)
    if not hanbang:
        return f"**{syl}** → 한방 단어 없음"
    return f"**{syl}** ⚡ 한방 {len(hanbang)}개\n" + join_cap(hanbang, 1800)

# ---- 디스코드 ----
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"[로그인] {client.user}  ·  채널제한={'없음(전체)' if CHANNEL_ID == 0 else CHANNEL_ID}")

def first_syllable(arg):
    arg = arg.strip()
    if not arg:
        return None, "사용법: `!공격 <글자>`  (예: `!공격 깐`)"
    syl = arg[0]
    if dec(syl) is None:
        return None, "완성된 한 글자를 입력해줘  (예: `!공격 가`)"
    return syl, None

@client.event
async def on_message(msg):
    if msg.author.bot:
        return
    if CHANNEL_ID and msg.channel.id != CHANNEL_ID:
        return
    content = msg.content.strip()

    if content.startswith("!공격"):
        syl, err = first_syllable(content[len("!공격"):])
        await msg.channel.send(err if err else reply_gongkyeok(syl))
    elif content.startswith("!한방"):
        syl, err = first_syllable(content[len("!한방"):])
        await msg.channel.send(err if err else reply_hanbang(syl))
    elif content in ("!도움", "!help", "!명령어"):
        await msg.channel.send(
            "**끄투 공격 봇**\n"
            "`!공격 <글자>` — 그 글자 공격 단어 (⚡=한방)\n"
            "`!한방 <글자>` — 한방 단어만\n"
            "예: `!공격 깐`, `!한방 가`"
        )

# ---- 실행 ----
load()
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("[에러] 환경변수 DISCORD_TOKEN 이 없어. (Railway의 Variables에 토큰을 넣어줘)")
else:
    client.run(token)
