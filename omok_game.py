# -*- coding: utf-8 -*-
"""오목 대국 모듈입니다.

사람 대 사람으로만 둡니다.
자유 오목 규칙입니다. 흑이 먼저 두고, 가로·세로·대각선으로 다섯 개를 먼저
잇는 쪽이 이깁니다. 금수(삼삼·사사·장목)는 두지 않습니다.

자리는 H8 처럼 적습니다. 가로는 왼쪽부터 A~O, 세로는 아래부터 1~15 입니다.
"""

import io, os, re

import discord

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

SIZE = 15                 # 판 한 변의 줄 수
NEED = 5                  # 이기는 데 필요한 개수
TURN_SECONDS = 300        # 한 수를 둘 수 있는 시간 (5분)

BLACK, WHITE = 0, 1       # players 목록에서의 자리
EMPTY = "."

COLOR_TURN = 0x5AC8FA
COLOR_WIN = 0xC2F74A
COLOR_DRAW = 0x9AA4B2

LETTERS = "ABCDEFGHIJKLMNO"[:SIZE]

# 자리처럼 생긴 글인지 가려 냅니다. 평범한 대화에 대꾸하지 않으려고 씁니다.
SPOT_LIKE = re.compile(rf"^([A-{LETTERS[-1]}])\s*([1-9]|1[0-{SIZE % 10}])$", re.IGNORECASE)

# ---------------------------------------------------------------------
# 판 그리기
# ---------------------------------------------------------------------

CELL = 62                          # 줄 간격
MARGIN = 48                        # 좌표를 적는 가장자리
BOARD_PX = CELL * (SIZE - 1) + MARGIN * 2

WOOD = (220, 179, 92)
LINE = (90, 62, 26)
LABEL = (60, 40, 16)
STONE_B = (24, 24, 28)
STONE_W = (248, 248, 246)
EDGE_B = (0, 0, 0)
EDGE_W = (110, 110, 105)
MARK = (220, 60, 50)

STARS = [(3, 3), (3, 11), (11, 3), (11, 11), (7, 7)] if SIZE == 15 else []

_font = None


def _label_font():
    global _font
    if _font is None:
        try:
            _font = ImageFont.load_default(size=max(12, MARGIN * 5 // 9))
        except Exception:
            _font = ImageFont.load_default()
    return _font


def spot_xy(col, row):
    """열·행 번호를 그림 위 좌표로 바꿉니다. 행 1이 맨 아래입니다."""
    return MARGIN + col * CELL, MARGIN + (SIZE - 1 - row) * CELL


def render_png(cells, last=None):
    """판을 그린 PNG 를 돌려줍니다. 그릴 수 없으면 None 입니다."""
    if not PIL_OK:
        return None
    img = Image.new("RGB", (BOARD_PX, BOARD_PX), WOOD)
    draw = ImageDraw.Draw(img)

    thin = max(1, CELL // 30)
    end = MARGIN + CELL * (SIZE - 1)
    for i in range(SIZE):
        pos = MARGIN + i * CELL
        draw.line([MARGIN, pos, end, pos], fill=LINE, width=thin)
        draw.line([pos, MARGIN, pos, end], fill=LINE, width=thin)
    draw.rectangle([MARGIN, MARGIN, end, end], outline=LINE, width=thin * 2)

    star = max(3, CELL // 10)
    for col, row in STARS:
        x, y = spot_xy(col, row)
        draw.ellipse([x - star, y - star, x + star, y + star], fill=LINE)

    font = _label_font()
    for i in range(SIZE):
        x, y = spot_xy(i, i)
        draw.text((x, MARGIN // 2), LETTERS[i], fill=LABEL, font=font, anchor="mm")
        draw.text((x, BOARD_PX - MARGIN // 2), LETTERS[i], fill=LABEL, font=font, anchor="mm")
        yy = MARGIN + (SIZE - 1 - i) * CELL
        draw.text((MARGIN // 2, yy), str(i + 1), fill=LABEL, font=font, anchor="mm")
        draw.text((BOARD_PX - MARGIN // 2, yy), str(i + 1), fill=LABEL, font=font, anchor="mm")

    r = CELL // 2 - 2
    for row in range(SIZE):
        for col in range(SIZE):
            stone = cells[row * SIZE + col]
            if stone == EMPTY:
                continue
            x, y = spot_xy(col, row)
            fill = STONE_B if stone == "b" else STONE_W
            edge = EDGE_B if stone == "b" else EDGE_W
            draw.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=edge,
                         width=max(1, CELL // 40))

    if last is not None:
        x, y = spot_xy(*last)
        m = CELL // 6
        draw.ellipse([x - m, y - m, x + m, y + m], outline=MARK, width=max(3, CELL // 14))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def parse_spot(text):
    """'H8' 을 (열, 행) 으로 바꿉니다. 못 읽으면 None 입니다."""
    m = SPOT_LIKE.match(text.strip())
    if not m:
        return None
    col = LETTERS.index(m.group(1).upper())
    row = int(m.group(2)) - 1
    if 0 <= row < SIZE:
        return col, row
    return None


def spot_name(col, row):
    return f"{LETTERS[col]}{row + 1}"


class OmokGame:
    """한 채널에서 진행 중인 오목 대국 하나입니다."""

    def __init__(self, channel_id, players, names):
        self.channel_id = channel_id
        self.players = players          # [흑 플레이어 id, 백 플레이어 id]
        self.names = names
        self.cells = [EMPTY] * (SIZE * SIZE)
        self.turn = BLACK               # 흑이 먼저 둡니다.
        self.history = []               # [(열, 행, 둔 사람 번호)]
        self.last = None
        self.finished = False
        self.result = ""
        self.winner = None
        self.win_line = []
        self.draw_offer = None
        self.message = None
        self.timer = None
        self.timer_token = 0

    # -- 상태 ------------------------------------------------------
    @property
    def actor(self):
        return self.players[self.turn]

    @property
    def actor_name(self):
        return self.names[self.turn]

    def side_of(self, user_id):
        if user_id == self.players[BLACK]:
            return BLACK
        if user_id == self.players[WHITE]:
            return WHITE
        return None

    def at(self, col, row):
        return self.cells[row * SIZE + col]

    # -- 수 두기 ---------------------------------------------------
    def place(self, text):
        """한 수를 둡니다. 통과하면 (True, 자리이름), 아니면 (False, 사유) 입니다."""
        spot = parse_spot(text)
        if spot is None:
            return False, (f"`{text}` 는 읽을 수 없는 자리입니다. "
                           f"`H8` 처럼 가로 글자와 세로 숫자를 붙여 적어 주세요.")
        col, row = spot
        if self.at(col, row) != EMPTY:
            return False, f"`{spot_name(col, row)}` 에는 이미 돌이 있습니다."
        self.cells[row * SIZE + col] = "b" if self.turn == BLACK else "w"
        self.history.append((col, row, self.turn))
        self.last = (col, row)
        self.draw_offer = None
        return True, spot_name(col, row)

    def check_over(self):
        """방금 둔 수로 대국이 끝났는지 봅니다."""
        if self.last is None:
            return False
        col, row = self.last
        stone = self.at(col, row)
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            line = [(col, row)]
            for sign in (1, -1):
                c, r = col + dc * sign, row + dr * sign
                while 0 <= c < SIZE and 0 <= r < SIZE and self.at(c, r) == stone:
                    line.append((c, r))
                    c += dc * sign
                    r += dr * sign
            if len(line) >= NEED:
                side = BLACK if stone == "b" else WHITE
                self.win_line = sorted(line)
                self.finish(side, f"{self.names[side]} 님이 {len(line)}개를 이었습니다.")
                return True
        if EMPTY not in self.cells:
            self.finish(None, "판이 다 찼습니다. 무승부입니다.")
            return True
        self.turn = 1 - self.turn
        return False

    def finish(self, winner, reason):
        self.finished = True
        self.winner = winner
        self.result = reason
        self.cancel_timer()

    def cancel_timer(self):
        if self.timer and not self.timer.done():
            self.timer.cancel()
        self.timer = None

    # -- 화면 ------------------------------------------------------
    def render(self):
        buf = render_png(self.cells, self.last)
        if buf is None:
            return None
        return discord.File(buf, filename="omok.png")

    def history_text(self, limit=10):
        if not self.history:
            return "아직 둔 수가 없습니다."
        rows = []
        for i, (col, row, side) in enumerate(self.history[-limit:], 1):
            mark = "⚫" if side == BLACK else "⚪"
            rows.append(f"{mark}{spot_name(col, row)}")
        text = " → ".join(rows)
        if len(self.history) > limit:
            text = "…  " + text
        return text

    def payload(self, notice=""):
        picture = self.render()
        return self.embed(notice, picture is not None), picture

    def embed(self, notice="", picture=False):
        if self.finished:
            if self.winner is None:
                color, title = COLOR_DRAW, "🤝  무승부입니다"
            else:
                color = COLOR_WIN
                title = f"🏁  {self.names[self.winner]} 님의 승리입니다"
        else:
            color = COLOR_TURN
            mark = "⚫" if self.turn == BLACK else "⚪"
            title = f"{mark}  {self.actor_name} 님의 차례입니다"

        e = discord.Embed(title=title, color=color)
        parts = []
        if notice:
            parts.append(notice)
        if picture:
            e.set_image(url="attachment://omok.png")
        else:
            parts.append("판 그림을 그릴 수 없어 기보만 보여 드립니다.")
        e.description = "\n".join(parts)[:4096] or None

        if self.finished:
            e.add_field(name="🏁 결과", value=self.result, inline=False)
            if self.win_line:
                spots = " ".join(spot_name(c, r) for c, r in self.win_line)
                e.add_field(name="⭐ 이은 자리", value=spots, inline=False)
        else:
            side = "흑 ⚫" if self.turn == BLACK else "백 ⚪"
            e.add_field(
                name="🎯 이번 수",
                value=(f"**{side}** 차례입니다 · {len(self.history) + 1}수째\n"
                       f"채팅에 `H8` 처럼 적어 주세요. "
                       f"가로는 왼쪽부터 A~{LETTERS[-1]}, 세로는 아래부터 1~{SIZE} 입니다."),
                inline=False)

        e.add_field(name="📜 기보", value=self.history_text()[:1024], inline=False)
        e.set_footer(text=f"⚫ {self.names[BLACK]} · ⚪ {self.names[WHITE]} · "
                          f"다섯 개를 먼저 이으면 이깁니다 · 빨간 표시는 직전 수입니다")
        return e


class OmokRegistry:
    """채널마다 대국 하나씩만 둡니다."""

    def __init__(self):
        self.games = {}

    def get(self, channel_id):
        return self.games.get(channel_id)

    def put(self, game):
        self.games[game.channel_id] = game

    def drop(self, channel_id):
        self.games.pop(channel_id, None)
