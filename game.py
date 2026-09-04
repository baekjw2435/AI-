# -*- coding: utf-8 -*-
"""끝말잇기 대전 모듈입니다.

훈련실: 사람 대 봇
경기장: 사람 대 사람

두 경우 모두 보호막 규칙을 씁니다.
  · 라운드 첫 수 전 보호막은 12이고, 한 수 둘 때마다 1씩 줄어 0에서 멈춥니다.
  · 보호막이 H일 때는 낸 단어의 끝 음절로 이을 수 있는 단어가 H개 이상이어야 합니다.
두음법칙은 표준두음법칙만 인정합니다.
"""

import asyncio, random

import discord
import route_engine as rq

TURN_SECONDS = 120        # 한 수를 둘 수 있는 시간
START_SHIELD = 12         # 라운드 첫 수의 보호막
BOT_THINK_SECONDS = 1.0   # 봇이 두기 전 잠깐 두는 사이

COLOR_TURN = 0x5AC8FA
COLOR_WIN = 0xC2F74A
COLOR_LOSE = 0xFF6B6B
COLOR_MUTED = 0x9AA4B2


# =====================================================================
# 사전 어댑터 — 표준과 복합이 같은 방식으로 보이게 감쌉니다.
# =====================================================================

class Dictionary:
    """게임에 필요한 조회만 모아 둔 껍데기입니다."""

    def __init__(self, name, words, start_count, first_words):
        self.name = name              # "표준" 또는 "복합"
        self.words = words            # set(전체 단어)
        self.start_count = start_count  # 음절 -> 시작 단어 수
        self.first_words = first_words  # 음절 -> [단어]

    def has(self, word):
        return word in self.words

    def candidates(self, current, used):
        out = []
        for v in rq.dueum_variants(current):
            for w in self.first_words.get(v, ()):
                if w not in used:
                    out.append(w)
        return out

    def follow_count(self, ending, used):
        variants = rq.dueum_variants(ending)
        total = sum(self.start_count.get(v, 0) for v in variants)
        blocked = sum(1 for w in used if w and w[0] in variants)
        return max(0, total - blocked)

    def has_legal_move(self, current, shield, used):
        """보호막까지 만족하는 수가 하나라도 남았는지 봅니다."""
        for w in self.candidates(current, used):
            if self.follow_count(w[-1], used | {w}) >= shield:
                return True
        return False

    def legal(self, word, current, shield, used):
        """규칙 위반이면 사유를, 통과하면 None 을 돌려줍니다."""
        if len(word) < 2:
            return "두 글자 이상인 단어를 입력해 주세요."
        if not self.has(word):
            return f"`{word}` 은(는) {self.name} 사전에 없는 단어입니다."
        if word in used:
            return f"`{word}` 은(는) 이미 사용한 단어입니다."
        if word[0] not in rq.dueum_variants(current):
            allowed = " 또는 ".join(f"`{v}`" for v in rq.dueum_variants(current))
            return f"{allowed} (으)로 시작하는 단어를 입력해 주세요."
        follow = self.follow_count(word[-1], used | {word})
        if follow < shield:
            return (f"`{word}` 의 끝말 `{word[-1]}` 로 이을 수 있는 단어가 {follow:,}개뿐입니다. "
                    f"지금 보호막은 {shield} 이라 {shield}개 이상이어야 합니다.")
        return None

    def bot_move(self, current, shield, used, history):
        raise NotImplementedError


class StandardDictionary(Dictionary):
    """표준 봇은 우리가 만든 추천 엔진을 그대로 씁니다."""

    def __init__(self, core):
        super().__init__("표준", None, core.start_count, core.first_words)
        self.core = core
        self.words = set()
        for rows in core.first_words.values():
            self.words.update(rows)

    def bot_move(self, current, shield, used, history):
        words = self.core.words_for(current, used)
        if not words:
            return None, ""
        rows = [c for c in rq.analyze_candidates(self.core, words, current, shield,
                                                 used, True, history) if c["legal"]]
        if not rows:
            return None, ""
        rows.sort(key=rq.sort_key)
        best = rows[0]
        if best["oneShot"]:
            note = "한방"
        elif best["attack"]:
            note = "공격"
        else:
            note = ""
        return best["word"], note


class ComplexDictionary(Dictionary):
    """복합 봇은 공격류(한방·공격·준공격·유도)만으로 둡니다.
    공격류가 하나도 없는 자리에서만 돌림을, 그마저 없으면 일반 수를 씁니다.
    고를 때는 상대가 반격할 공격류가 가장 적은 끝말을 넘깁니다."""

    def __init__(self, words, start_count, first_words,
                 attack_by_syllable, end_category, category_first, dollim_end):
        super().__init__("복합", words, start_count, first_words)
        self.attack_by_syllable = attack_by_syllable   # 음절 -> {단어: 깊이}
        self.end_category = end_category               # 끝음절 -> 'J'/'Y'
        self.category_first = category_first           # 첫음절 -> [(단어, 'J'/'Y')]
        self.dollim_end = dollim_end                   # 첫음절 -> set(자가순환 단어)

    def _attacks(self, current):
        merged = {}
        for v in rq.dueum_variants(current):
            for w, depth in self.attack_by_syllable.get(v, {}).items():
                if w not in merged or depth < merged[w]:
                    merged[w] = depth
        return merged

    def _dollim(self, current, used):
        out = set()
        for v in rq.dueum_variants(current):
            out |= self.dollim_end.get(v, set())
        return {w for w in out if w in self.words and w not in used}

    def _threat(self, ending, used):
        """상대가 그 끝말에서 쓸 수 있는 공격류(공격·준공격·유도) 수입니다.
        적을수록 상대가 반격하기 어렵습니다."""
        count = 0
        for w in self._attacks(ending):
            if w not in used and self.has(w):
                count += 1
        for v in rq.dueum_variants(ending):
            for w, _cat in self.category_first.get(v, ()):
                if w not in used and self.has(w):
                    count += 1
        return count

    def bot_move(self, current, shield, used, history):
        def usable(pool):
            return sorted({w for w in pool
                           if w not in used and self.has(w)
                           and self.follow_count(w[-1], used | {w}) >= shield})

        def best(pool, lookahead=True):
            if lookahead:
                # 상대가 반격할 공격류가 적고 이을 단어도 좁은 수를 고릅니다.
                return min(pool, key=lambda w: (self._threat(w[-1], used | {w}),
                                                self.follow_count(w[-1], used | {w}), w))
            return min(pool, key=lambda w: (self.follow_count(w[-1], used | {w}), w))

        attacks = self._attacks(current)

        # 1) 한방으로 바로 끝냅니다.
        pool = usable([w for w, d in attacks.items() if d == 1])
        if pool:
            return best(pool), "한방"

        # 2) 공격 → 3) 준공격 → 4) 유도. 여기까지가 공격류입니다.
        pool = usable([w for w, d in attacks.items() if d != 1])
        if pool:
            return best(pool), "공격"

        semi, lure = [], []
        for v in rq.dueum_variants(current):
            for w, cat in self.category_first.get(v, ()):
                (semi if cat == "J" else lure).append(w)
        pool = usable(semi)
        if pool:
            return best(pool), "준공격"
        pool = usable(lure)
        if pool:
            return best(pool), "유도"

        # 5) 공격류가 하나도 없을 때만 돌림을 씁니다.
        #    틀(틀틀·틀라솔테오틀)이나 획(획획·획득계획)처럼 돌림밖에 없는 자리가 있어서,
        #    돌림까지 막으면 봇이 둘 수 있는데도 그냥 지게 됩니다.
        pool = usable(self._dollim(current, used))
        if pool:
            return best(pool), "돌림"

        # 6) 그마저 없으면 상대를 가장 좁히는 일반 수로 버팁니다.
        pool = usable(self.candidates(current, used))
        if pool:
            return best(pool, lookahead=False), ""
        return None, ""


# =====================================================================
# 제시 글자
# =====================================================================

def pick_start_syllable(dictionary, minimum=300):
    """넉넉히 이어 갈 수 있는 음절 중에서 제시 글자를 하나 고릅니다."""
    pool = [syl for syl, count in dictionary.start_count.items()
            if count >= minimum and "가" <= syl <= "힣"]
    if not pool:
        pool = [syl for syl in dictionary.start_count if "가" <= syl <= "힣"]
    return random.choice(sorted(pool))


# =====================================================================
# 대국
# =====================================================================

class Game:
    """한 채널에서 진행 중인 대국 하나입니다."""

    def __init__(self, channel_id, dictionary, players, names, start_syllable):
        self.channel_id = channel_id
        self.dictionary = dictionary
        self.players = players      # [플레이어 id 또는 None(봇)]
        self.names = names          # 보여 줄 이름 두 개
        self.current = start_syllable
        self.start_syllable = start_syllable
        self.shield = START_SHIELD
        self.used = set()
        self.history = []           # [(단어, 그때 보호막, 둔 사람 번호, 표시)]
        self.turn = 0
        self.finished = False
        self.result = ""
        self.timer_token = 0
        self.timer = None

    # -- 상태 ------------------------------------------------------
    @property
    def actor(self):
        return self.players[self.turn]

    @property
    def actor_name(self):
        return self.names[self.turn]

    def is_bot_turn(self):
        return self.players[self.turn] is None

    def opponent_index(self):
        return 1 - self.turn

    def apply(self, word, note=""):
        self.history.append((word, self.shield, self.turn, note))
        self.used.add(word)
        self.current = word[-1]
        self.shield = max(0, self.shield - 1)
        self.turn = 1 - self.turn

    def finish(self, winner_index, reason):
        self.finished = True
        self.result = reason
        self.winner = winner_index
        self.cancel_timer()

    def cancel_timer(self):
        if self.timer and not self.timer.done():
            self.timer.cancel()
        self.timer = None

    # -- 화면 ------------------------------------------------------
    def route_text(self, limit=12):
        rows = self.history[-limit:]
        parts = []
        for word, shield, who, note in rows:
            tag = "🔵" if who == 0 else "🔴"
            mark = f" ({note})" if note else ""
            parts.append(f"{tag} `{shield}` {word}{mark}")
        text = " → ".join(parts)
        if len(self.history) > limit:
            text = "…  " + text
        return text or "아직 둔 수가 없습니다."

    def board(self, notice=""):
        if self.finished:
            color = COLOR_WIN
            title = f"🏁  {self.names[self.winner]} 님의 승리입니다"
            if self.players[self.winner] is None:
                title = f"🏁  {self.names[self.winner]} 승리"
        else:
            color = COLOR_TURN
            title = f"⏳  {self.actor_name} 님의 차례입니다"
            if self.is_bot_turn():
                title = f"⏳  {self.actor_name} 생각 중"

        e = discord.Embed(title=title, color=color)
        if notice:
            e.description = notice

        if not self.finished:
            allowed = " 또는 ".join(f"**{v}**" for v in rq.dueum_variants(self.current))
            e.add_field(
                name="🎯 이번 수",
                value=(f"{allowed} (으)로 시작하는 단어 · 보호막 **{self.shield}**\n"
                       f"끝말로 이을 단어가 **{self.shield}개 이상** 남아야 합니다."),
                inline=False)
        else:
            e.add_field(name="🏁 결과", value=self.result, inline=False)

        e.add_field(name=f"🧭 진행 · {len(self.history)}수", value=self.route_text()[:1024],
                    inline=False)
        e.set_footer(text=f"{self.dictionary.name} 사전 · 표준두음법칙 적용 · "
                          f"🔵 {self.names[0]} · 🔴 {self.names[1]}")
        return e


class GameRegistry:
    """채널마다 대국 하나씩만 둡니다."""

    def __init__(self):
        self.games = {}

    def get(self, channel_id):
        return self.games.get(channel_id)

    def put(self, game):
        self.games[game.channel_id] = game

    def drop(self, channel_id):
        self.games.pop(channel_id, None)
