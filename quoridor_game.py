# -*- coding: utf-8 -*-
"""쿼리도 대국 모듈입니다.

9×9 판에서 둘이 둡니다. 아래쪽 말은 맨 윗줄에, 위쪽 말은 맨 아랫줄에
먼저 닿는 쪽이 이깁니다.

한 차례에 둘 중 하나를 합니다.
  · 말을 한 칸 움직입니다 (위·아래·왼쪽·오른쪽)
  · 벽을 하나 놓습니다 (각자 10개)

벽은 두 칸 길이입니다. 상대의 길을 아예 막아 버리는 자리에는 놓을 수 없습니다.
말이 서로 맞닿으면 뛰어넘을 수 있고, 뒤가 막혀 있으면 옆으로 비켜 갑니다.

자리 적는 법
  e2      말을 e2 로 옮깁니다
  e5ㅡ    e5 와 f5 의 위쪽에 가로벽을 놓습니다  (e5h 로 적어도 됩니다)
  e5|     e5 와 e6 의 오른쪽에 세로벽을 놓습니다 (e5v 로 적어도 됩니다)
"""

import io, re
from collections import deque

import discord

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

SIZE = 9                  # 판 한 변의 칸 수
WALLS = 10                # 한 사람이 가진 벽 개수
TURN_SECONDS = 300        # 한 수를 둘 수 있는 시간 (5분)

LOWER, UPPER = 0, 1       # players 목록에서의 자리. LOWER 가 아래쪽에서 시작합니다.
LETTERS = "abcdefghi"[:SIZE]

COLOR_TURN = 0x5AC8FA
COLOR_WIN = 0xC2F74A
COLOR_DRAW = 0x9AA4B2

# 말을 옮기는 수인지, 벽을 놓는 수인지 가려 냅니다.
MOVE_LIKE = re.compile(rf"^([A-{LETTERS[-1].upper()}a-{LETTERS[-1]}])\s*([1-{SIZE}])"
                       rf"\s*([hvHV\-ㅡ|ㅣ/])?$")

WALL_H = "h"
WALL_V = "v"

# 사람들이 적기 쉬운 여러 글자를 두 가지로 모읍니다.
WALL_MARKS = {"h": WALL_H, "-": WALL_H, "ㅡ": WALL_H,
              "v": WALL_V, "|": WALL_V, "ㅣ": WALL_V, "/": WALL_V}


# ---------------------------------------------------------------------
# 판 그리기
# ---------------------------------------------------------------------

CELL = 84                 # 칸 한 변
GAP = 16                  # 칸 사이 홈. 벽이 여기 놓입니다.
MARGIN = 46
PITCH = CELL + GAP
BOARD_PX = MARGIN * 2 + SIZE * CELL + (SIZE - 1) * GAP

BG = (238, 228, 210)
CELL_C = (247, 241, 228)
GOAL_LOWER = (226, 236, 248)
GOAL_UPPER = (250, 232, 228)
GROOVE = (214, 202, 180)
WALL_C = (122, 82, 44)
LABEL = (96, 78, 54)
PAWN_L = (44, 92, 168)
PAWN_U = (196, 66, 58)
PAWN_EDGE = (250, 250, 248)

_font = None


def _label_font():
    global _font
    if _font is None:
        try:
            _font = ImageFont.load_default(size=26)
        except Exception:
            _font = ImageFont.load_default()
    return _font


def cell_box(col, row):
    """칸 하나가 차지하는 네모입니다. row 0 이 맨 아래입니다."""
    x = MARGIN + col * PITCH
    y = MARGIN + (SIZE - 1 - row) * PITCH
    return [x, y, x + CELL, y + CELL]


def render_png(game):
    """판을 그린 PNG 를 돌려줍니다. 그릴 수 없으면 None 입니다."""
    if not PIL_OK:
        return None
    img = Image.new("RGB", (BOARD_PX, BOARD_PX), BG)
    draw = ImageDraw.Draw(img)

    inner = MARGIN - GAP // 2
    draw.rectangle([inner, inner, BOARD_PX - inner, BOARD_PX - inner], fill=GROOVE)

    for row in range(SIZE):
        for col in range(SIZE):
            fill = CELL_C
            if row == SIZE - 1:
                fill = GOAL_LOWER          # 아래쪽 말이 닿아야 하는 줄
            elif row == 0:
                fill = GOAL_UPPER          # 위쪽 말이 닿아야 하는 줄
            draw.rounded_rectangle(cell_box(col, row), radius=8, fill=fill)

    for (row, col), kind in game.walls.items():
        if kind == WALL_H:
            x0 = MARGIN + col * PITCH
            x1 = MARGIN + (col + 1) * PITCH + CELL
            y = MARGIN + (SIZE - 2 - row) * PITCH + CELL
            box = [x0, y + 1, x1, y + GAP - 1]
        else:
            y0 = MARGIN + (SIZE - 2 - row) * PITCH
            y1 = MARGIN + (SIZE - 1 - row) * PITCH + CELL
            x = MARGIN + col * PITCH + CELL
            box = [x + 1, y0, x + GAP - 1, y1]
        draw.rounded_rectangle(box, radius=GAP // 3, fill=WALL_C)

    for side, (row, col) in enumerate(game.pawns):
        x0, y0, x1, y1 = cell_box(col, row)
        pad = CELL // 6
        color = PAWN_L if side == LOWER else PAWN_U
        draw.ellipse([x0 + pad, y0 + pad, x1 - pad, y1 - pad],
                     fill=color, outline=PAWN_EDGE, width=4)

    font = _label_font()
    for col in range(SIZE):
        x = MARGIN + col * PITCH + CELL // 2
        draw.text((x, MARGIN // 2), LETTERS[col].upper(), fill=LABEL, font=font, anchor="mm")
        draw.text((x, BOARD_PX - MARGIN // 2), LETTERS[col].upper(),
                  fill=LABEL, font=font, anchor="mm")
    for row in range(SIZE):
        y = MARGIN + (SIZE - 1 - row) * PITCH + CELL // 2
        draw.text((MARGIN // 2, y), str(row + 1), fill=LABEL, font=font, anchor="mm")
        draw.text((BOARD_PX - MARGIN // 2, y), str(row + 1), fill=LABEL, font=font, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def spot_name(row, col):
    return f"{LETTERS[col]}{row + 1}"


class QuoridorGame:
    """한 채널에서 진행 중인 쿼리도 대국 하나입니다."""

    def __init__(self, channel_id, players, names):
        self.channel_id = channel_id
        self.players = players
        self.names = names
        mid = SIZE // 2
        self.pawns = [(0, mid), (SIZE - 1, mid)]      # [아래쪽 말, 위쪽 말]
        self.walls = {}                               # (행, 열) -> 'h' 또는 'v'
        self.left = [WALLS, WALLS]                    # 남은 벽 개수
        self.turn = LOWER
        self.history = []
        self.finished = False
        self.result = ""
        self.winner = None
        self.aborted = False
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
        if user_id == self.players[LOWER]:
            return LOWER
        if user_id == self.players[UPPER]:
            return UPPER
        return None

    def goal_row(self, side):
        return SIZE - 1 if side == LOWER else 0

    # -- 벽과 길 ---------------------------------------------------
    def blocked(self, frm, to):
        """두 칸 사이가 벽으로 막혔는지 봅니다. 맞닿은 칸끼리만 묻습니다."""
        (r1, c1), (r2, c2) = frm, to
        if r1 == r2:                                   # 좌우로 움직입니다.
            col = min(c1, c2)
            return any(self.walls.get((rr, col)) == WALL_V for rr in (r1, r1 - 1))
        row = min(r1, r2)                              # 위아래로 움직입니다.
        return any(self.walls.get((row, cc)) == WALL_H for cc in (c1, c1 - 1))

    def steps(self, spot):
        """벽을 빼고 갈 수 있는 맞닿은 칸들입니다."""
        row, col = spot
        out = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = row + dr, col + dc
            if 0 <= nr < SIZE and 0 <= nc < SIZE and not self.blocked(spot, (nr, nc)):
                out.append((nr, nc))
        return out

    def has_path(self, side):
        """그 사람이 아직 닿을 길이 남아 있는지 봅니다."""
        goal = self.goal_row(side)
        start = self.pawns[side]
        seen = {start}
        queue = deque([start])
        while queue:
            spot = queue.popleft()
            if spot[0] == goal:
                return True
            for nxt in self.steps(spot):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return False

    def wall_conflict(self, row, col, kind):
        """이미 놓인 벽과 겹치거나 엇갈리는지 봅니다."""
        if (row, col) in self.walls:
            return True
        if kind == WALL_H:
            return any(self.walls.get((row, cc)) == WALL_H for cc in (col - 1, col + 1))
        return any(self.walls.get((rr, col)) == WALL_V for rr in (row - 1, row + 1))

    # -- 말이 갈 수 있는 곳 ------------------------------------------
    def pawn_moves(self, side):
        """뛰어넘기까지 넣은, 말이 갈 수 있는 칸들입니다."""
        here = self.pawns[side]
        there = self.pawns[1 - side]
        out = []
        for nxt in self.steps(here):
            if nxt != there:
                out.append(nxt)
                continue
            # 상대 말과 맞닿았습니다. 먼저 곧장 뛰어넘어 봅니다.
            dr, dc = nxt[0] - here[0], nxt[1] - here[1]
            over = (nxt[0] + dr, nxt[1] + dc)
            if (0 <= over[0] < SIZE and 0 <= over[1] < SIZE
                    and not self.blocked(nxt, over)):
                out.append(over)
                continue
            # 뒤가 막혔으면 옆으로 비켜 갑니다.
            for sr, sc in (((0, 1), (0, -1)) if dr else ((1, 0), (-1, 0))):
                side_spot = (nxt[0] + sr, nxt[1] + sc)
                if (0 <= side_spot[0] < SIZE and 0 <= side_spot[1] < SIZE
                        and not self.blocked(nxt, side_spot)):
                    out.append(side_spot)
        return sorted(set(out))

    # -- 수 두기 ---------------------------------------------------
    def play(self, text):
        """한 수를 둡니다. 통과하면 (True, 적은 것), 아니면 (False, 사유) 입니다."""
        m = MOVE_LIKE.match(text.strip())
        if not m:
            return False, (f"`{text}` 는 읽을 수 없습니다. 말은 `e2`, "
                           f"벽은 `e5ㅡ` 나 `e5|` 처럼 적어 주세요.")
        col = LETTERS.index(m.group(1).lower())
        row = int(m.group(2)) - 1
        mark = m.group(3)

        if not mark:
            return self._move_pawn(row, col)
        return self._place_wall(row, col, WALL_MARKS[mark.lower()])

    def _move_pawn(self, row, col):
        side = self.turn
        if (row, col) not in self.pawn_moves(side):
            return False, (f"`{spot_name(row, col)}` 로는 갈 수 없습니다. "
                           f"지금 갈 수 있는 곳은 "
                           f"{', '.join('`' + spot_name(*s) + '`' for s in self.pawn_moves(side))} 입니다.")
        self.pawns[side] = (row, col)
        name = spot_name(row, col)
        self.history.append((side, name))
        return True, name

    def _place_wall(self, row, col, kind):
        side = self.turn
        if self.left[side] <= 0:
            return False, "남은 벽이 없습니다. 말을 옮겨 주세요."
        if not (0 <= row <= SIZE - 2 and 0 <= col <= SIZE - 2):
            return False, (f"벽은 `{LETTERS[0]}1` 부터 `{LETTERS[SIZE - 2]}{SIZE - 1}` "
                           f"사이에만 놓을 수 있습니다.")
        if self.wall_conflict(row, col, kind):
            return False, "그 자리에는 이미 벽이 있거나 다른 벽과 엇갈립니다."

        self.walls[(row, col)] = kind
        if not (self.has_path(LOWER) and self.has_path(UPPER)):
            del self.walls[(row, col)]
            return False, "길을 아예 막는 자리에는 놓을 수 없습니다."

        self.left[side] -= 1
        name = spot_name(row, col) + ("ㅡ" if kind == WALL_H else "|")
        self.history.append((side, name))
        return True, name

    def check_over(self):
        """방금 둔 수로 끝났는지 봅니다."""
        for side in (LOWER, UPPER):
            if self.pawns[side][0] == self.goal_row(side):
                self.finish(side, f"{self.names[side]} 님이 건너편에 닿았습니다.")
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
        buf = render_png(self)
        if buf is None:
            return None
        return discord.File(buf, filename="quoridor.png")

    def history_text(self, limit=10):
        if not self.history:
            return "아직 둔 수가 없습니다."
        rows = []
        for side, name in self.history[-limit:]:
            rows.append(("🔵" if side == LOWER else "🔴") + name)
        text = " → ".join(rows)
        if len(self.history) > limit:
            text = "…  " + text
        return text

    def payload(self, notice=""):
        picture = self.render()
        return self.embed(notice, picture is not None), picture

    def embed(self, notice="", picture=False):
        if self.finished:
            if self.aborted:
                color, title = COLOR_DRAW, "⛔  중단된 대국입니다"
            elif self.winner is None:
                color, title = COLOR_DRAW, "🤝  무승부입니다"
            else:
                color = COLOR_WIN
                title = f"🏁  {self.names[self.winner]} 님의 승리입니다"
        else:
            color = COLOR_TURN
            mark = "🔵" if self.turn == LOWER else "🔴"
            title = f"{mark}  {self.actor_name} 님의 차례입니다"

        e = discord.Embed(title=title, color=color)
        parts = []
        if notice:
            parts.append(notice)
        if picture:
            e.set_image(url="attachment://quoridor.png")
        else:
            parts.append("판 그림을 그릴 수 없어 기보만 보여 드립니다.")
        e.description = "\n".join(parts)[:4096] or None

        if self.finished:
            e.add_field(name="🏁 결과", value=self.result, inline=False)
        else:
            spots = ", ".join(f"`{spot_name(*s)}`" for s in self.pawn_moves(self.turn))
            e.add_field(
                name="🎯 이번 수",
                value=(f"{len(self.history) + 1}수째 · 갈 수 있는 곳 {spots}\n"
                       f"벽을 놓으시려면 `e5ㅡ` (가로) 나 `e5|` (세로) 처럼 적어 주세요."),
                inline=False)

        e.add_field(
            name="🧱 남은 벽",
            value=f"🔵 {self.names[LOWER]} **{self.left[LOWER]}개** · "
                  f"🔴 {self.names[UPPER]} **{self.left[UPPER]}개**",
            inline=False)
        e.add_field(name="📜 기보", value=self.history_text()[:1024], inline=False)
        e.set_footer(text=f"🔵 {self.names[LOWER]} 는 맨 윗줄, "
                          f"🔴 {self.names[UPPER]} 는 맨 아랫줄에 닿으면 이깁니다")
        return e


class QuoridorRegistry:
    """채널마다 대국 하나씩만 둡니다."""

    def __init__(self):
        self.games = {}

    def get(self, channel_id):
        return self.games.get(channel_id)

    def put(self, game):
        self.games[game.channel_id] = game

    def drop(self, channel_id):
        self.games.pop(channel_id, None)
