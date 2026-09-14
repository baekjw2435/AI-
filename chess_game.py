# -*- coding: utf-8 -*-
"""체스 대국 모듈입니다.

사람 대 사람으로만 둡니다. 규칙은 python-chess 가 전부 맡습니다.
앙파상, 캐슬링, 승격, 스테일메이트, 50수 규칙, 3회 동형반복까지 들어 있습니다.

판은 서버에 올린 이모지로 그립니다. 이모지가 없으면 글자 판으로 대신합니다.
"""

import asyncio, io, os, re

import chess
import discord

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except Exception:
    PIL_OK = False

TURN_SECONDS = 600        # 한 수를 둘 수 있는 시간 (10분)

COLOR_TURN = 0x5AC8FA
COLOR_WIN = 0xC2F74A
COLOR_DRAW = 0x9AA4B2

WHITE, BLACK = 0, 1       # players 목록에서의 자리

# 서버에 올려야 하는 이모지 이름입니다. 26개가 다 있어야 그림 판이 나옵니다.
EMOJI_NAMES = ["sq_l", "sq_d"] + [
    f"{side}{kind}_{tone}"
    for side in "wb" for kind in "pnbrqk" for tone in "ld"
]

# 글자 판에서 쓸 말 모양입니다.
UNICODE_PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

# 수처럼 생긴 글인지 가려 냅니다. 평범한 채팅에 일일이 대꾸하지 않으려고 씁니다.
MOVE_LIKE = re.compile(
    r"^(?:[KQRBN][A-Ha-h1-8]?x?[A-Ha-h][1-8]"    # Nf3, Nbd2, Qxe5
    r"|[A-Ha-h]x?[A-Ha-h]?[1-8](?:=[QRBN])?"     # e4, exd5, e8=Q
    r"|[A-Ha-h][1-8][A-Ha-h][1-8][QRBN]?"        # e2e4 (UCI)
    r"|[Oo0]-[Oo0](?:-[Oo0])?)"                  # O-O, O-O-O
    r"[+#]?$",
    re.IGNORECASE
)

FILES = "abcdefgh"


def _ro(word):
    """'로' 와 '으로' 를 가려 줍니다. 받침이 없거나 ㄹ 받침이면 '로' 입니다."""
    if not word:
        return "로"
    code = ord(word[-1]) - 0xAC00
    if code < 0 or code > 11171:
        return "로"
    final = code % 28
    return "로" if final in (0, 8) else "으로"


# ---------------------------------------------------------------------
# 그림 판 그리기
#   말 그림은 chess_pieces/ 에 미리 뽑아 둔 PNG 를 씁니다.
#   서버에 따로 깔 것이 없도록 붙이기만 합니다.
# ---------------------------------------------------------------------

PIECE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chess_pieces")
CELL = 116                     # 칸 한 변
MARGIN = 40                    # 좌표를 적는 가장자리
BOARD_PX = CELL * 8 + MARGIN * 2

LIGHT_SQ = (240, 217, 181)
DARK_SQ = (181, 136, 99)
EDGE = (101, 76, 56)
LABEL = (245, 238, 226)
MOVE_MARK = (205, 210, 106, 150)     # 직전 수 표시 (노랑)
CHECK_MARK = (220, 70, 60, 165)      # 체크 표시 (빨강)

_pieces = {}
_font = None


def _load_pieces():
    """말 그림을 한 번만 읽어 둡니다. 하나라도 없으면 그림 판을 포기합니다."""
    global _pieces
    if _pieces:
        return _pieces
    if not PIL_OK:
        return None
    loaded = {}
    for side in "wb":
        for kind in "pnbrqk":
            path = os.path.join(PIECE_DIR, f"{side}{kind}.png")
            if not os.path.exists(path):
                return None
            img = Image.open(path).convert("RGBA")
            pad = max(2, int(CELL * 0.05))
            size = CELL - pad * 2
            loaded[side + kind] = img.resize((size, size), Image.LANCZOS)
    _pieces = loaded
    return _pieces


def _label_font():
    global _font
    if _font is None:
        try:
            _font = ImageFont.load_default(size=max(12, MARGIN * 3 // 5))
        except Exception:
            _font = ImageFont.load_default()
    return _font


PICK_MARK = (100, 150, 220, 150)      # 고른 말 자리 (파랑)
DOT = (60, 110, 40, 150)              # 갈 수 있는 빈 칸
RING = (170, 50, 40, 175)             # 잡을 수 있는 칸


def render_png(board, last_move=None, flip=False, picked=None, targets=()):
    """판을 그린 PNG 를 돌려줍니다. 그릴 수 없으면 None 입니다.
    picked 는 고른 말의 자리, targets 는 갈 수 있는 칸들입니다."""
    pieces = _load_pieces()
    if pieces is None:
        return None

    img = Image.new("RGBA", (BOARD_PX, BOARD_PX), EDGE)
    draw = ImageDraw.Draw(img, "RGBA")

    ranks = range(8) if flip else range(7, -1, -1)
    files = range(7, -1, -1) if flip else range(8)

    check_sq = None
    if board.is_check():
        check_sq = board.king(board.turn)

    for row, rank in enumerate(ranks):
        for col, file in enumerate(files):
            square = chess.square(file, rank)
            x0 = MARGIN + col * CELL
            y0 = MARGIN + row * CELL
            box = [x0, y0, x0 + CELL, y0 + CELL]
            draw.rectangle(box, fill=LIGHT_SQ if (file + rank) % 2 else DARK_SQ)

            if last_move is not None and square in (last_move.from_square, last_move.to_square):
                draw.rectangle(box, fill=MOVE_MARK)
            if square == picked:
                draw.rectangle(box, fill=PICK_MARK)
            if square == check_sq:
                draw.rectangle(box, fill=CHECK_MARK)

            piece = board.piece_at(square)
            if piece is not None:
                side = "w" if piece.color == chess.WHITE else "b"
                key = side + chess.piece_symbol(piece.piece_type)
                art = pieces[key]
                off = (CELL - art.width) // 2
                img.alpha_composite(art, (x0 + off, y0 + off))

            if square in targets:
                cx, cy = x0 + CELL // 2, y0 + CELL // 2
                if piece is None:
                    r = CELL // 7
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT)
                else:
                    # 잡을 수 있는 칸은 말이 가리지 않도록 테두리로 표시합니다.
                    r = CELL // 2 - 3
                    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                                 outline=RING, width=max(4, CELL // 12))

    font = _label_font()
    for col, file in enumerate(files):
        text = FILES[file]
        x = MARGIN + col * CELL + CELL // 2
        draw.text((x, MARGIN // 2), text, fill=LABEL, font=font, anchor="mm")
        draw.text((x, BOARD_PX - MARGIN // 2), text, fill=LABEL, font=font, anchor="mm")
    for row, rank in enumerate(ranks):
        text = str(rank + 1)
        y = MARGIN + row * CELL + CELL // 2
        draw.text((MARGIN // 2, y), text, fill=LABEL, font=font, anchor="mm")
        draw.text((BOARD_PX - MARGIN // 2, y), text, fill=LABEL, font=font, anchor="mm")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf



def emoji_map(guild):
    """서버에서 체스 이모지를 찾아 {이름: 쓸 수 있는 형태} 로 돌려줍니다.
    하나라도 없으면 None 을 돌려주고, 그때는 글자 판을 씁니다."""
    if guild is None:
        return None
    found = {e.name: str(e) for e in guild.emojis if e.name in EMOJI_NAMES}
    if len(found) < len(EMOJI_NAMES):
        return None
    return found


class ChessGame:
    """한 채널에서 진행 중인 체스 대국 하나입니다."""

    def __init__(self, channel_id, players, names):
        self.channel_id = channel_id
        self.players = players          # [백 플레이어 id, 흑 플레이어 id]
        self.names = names              # 보여 줄 이름 두 개
        self.board = chess.Board()
        self.finished = False
        self.result = ""
        self.winner = None              # 0=백, 1=흑, None=무승부
        self.last_san = None
        self.draw_offer = None          # 무승부를 제안한 분의 id
        self.aborted = False            # 관리자가 세운 대국인지
        self.timer = None
        self.timer_token = 0
        self.message = None             # 마지막으로 보낸 판 메시지
        self.private = {}               # 사람 id -> 본인만 보이는 판을 고칠 수 있는 창구
        self.flip = False               # 모두가 보는 판은 늘 백 기준입니다.
                                        # 흑에서 본 판은 버튼으로 본인에게만 보여 드립니다.

    # -- 상태 ------------------------------------------------------
    @property
    def turn_index(self):
        return WHITE if self.board.turn == chess.WHITE else BLACK

    @property
    def actor(self):
        return self.players[self.turn_index]

    @property
    def actor_name(self):
        return self.names[self.turn_index]

    def side_of(self, user_id):
        """그분이 백인지 흑인지 봅니다. 대국자가 아니면 None 입니다."""
        if user_id == self.players[WHITE]:
            return WHITE
        if user_id == self.players[BLACK]:
            return BLACK
        return None

    def move_number(self):
        return self.board.fullmove_number

    # -- 수 두기 ---------------------------------------------------
    @staticmethod
    def spellings(text):
        """대소문자를 흔히 틀리시는 꼴을 몇 가지 만들어 봅니다.
        체스 표기는 B가 비숍, b가 b열이라 함부로 바꾸면 뜻이 달라집니다.
        그래서 바꾸지 않고, 여러 해석을 따로 시도해 볼 목록만 만듭니다."""
        t = text.strip()
        out = []

        def add(x):
            if x and x not in out:
                out.append(x)

        def fix_promo(x):
            return re.sub(r"=(.)", lambda m: "=" + m.group(1).upper(), x)

        add(t)
        if re.fullmatch(r"[0oO]-[0oO]", t):
            add("O-O")
        if re.fullmatch(r"[0oO]-[0oO]-[0oO]", t):
            add("O-O-O")
        low = t.lower()
        add(low)                      # E4 → e4,  E2E4 → e2e4
        add(fix_promo(low))           # e8=q → e8=Q
        if low and low[0] in "kqrbn":
            piece = low[0].upper() + low[1:]
            add(piece)                # nf3 → Nf3
            add(fix_promo(piece))
        return out

    def _read(self, text):
        """한 가지 적은 꼴을 수로 읽어 봅니다. 못 읽으면 None 입니다."""
        try:
            return self.board.parse_san(text)
        except ValueError:
            pass
        try:
            move = chess.Move.from_uci(text.lower())
        except ValueError:
            return None
        return move if move in self.board.legal_moves else None

    @staticmethod
    def _bare(san):
        """기보에서 어느 말인지 가려 주는 글자를 뺍니다. Rab8 → Rb8"""
        m = re.match(r"^([KQRBN])[a-h1-8]{0,2}(x?)([a-h][1-8])", san)
        if not m:
            return san.rstrip("+#")
        return m.group(1) + m.group(2) + m.group(3)

    def _same_named(self, text):
        """같은 말·같은 도착칸이라 어느 것인지 가릴 수 없는 수들을 모읍니다."""
        want = text.strip().rstrip("+#")
        out = []
        for move in self.board.legal_moves:
            san = self.board.san(move)
            if self._bare(san) == want:
                out.append(san)
        return sorted(out)

    def push(self, text):
        """한 수를 둡니다. 통과하면 (True, 기보), 아니면 (False, 사유) 입니다."""
        text = text.strip()

        # 적으신 그대로 읽히면 그것이 정답입니다. 고쳐 읽지 않습니다.
        exact = self._read(text)
        if exact is not None:
            return self._apply(exact)

        # 그대로는 안 읽힐 때만 대소문자를 고쳐서 다시 읽어 봅니다.
        found = []
        for spelling in self.spellings(text)[1:]:
            move = self._read(spelling)
            if move is not None and move not in found:
                found.append(move)

        if not found:
            # 같은 말이 둘 다 갈 수 있는 자리면 어느 쪽인지 짚어 드립니다.
            for spelling in self.spellings(text):
                same = self._same_named(spelling)
                if len(same) > 1:
                    names = " 또는 ".join(f"`{x}`" for x in same)
                    where = " · ".join(
                        f"`{chess.square_name(self.board.parse_san(x).from_square)}"
                        f"{chess.square_name(self.board.parse_san(x).to_square)}`"
                        for x in same)
                    return False, (f"`{text}` 로는 두 곳에서 갈 수 있어 어느 말인지 알 수 없습니다.\n"
                                   f"{names} 처럼 출발 줄을 넣어 적어 주세요. "
                                   f"칸 이름으로 {where} 처럼 적으셔도 됩니다.")
            return False, (f"`{text}` 는 지금 둘 수 없는 수입니다. "
                           f"`e4`, `Nf3`, `O-O`, `e2e4` 처럼 입력해 주세요.")
        if len(found) > 1:
            # 예를 들어 bxc6 는 b열 폰이 잡는 수, Bxc6 는 비숍이 잡는 수입니다.
            # 둘 다 둘 수 있는 자리라면 함부로 고르지 않습니다.
            names = " 와 ".join(f"`{self.board.san(m)}`" for m in found)
            return False, (f"`{text}` 는 {names} 둘 다로 읽힙니다. "
                           f"대문자와 소문자를 정확히 적어 주세요. "
                           f"(대문자 B는 비숍, 소문자 b는 b열입니다)")

        return self._apply(found[0])

    def _apply(self, move):
        san = self.board.san(move)
        self.board.push(move)
        self.last_san = san
        self.draw_offer = None          # 수를 두면 무승부 제안은 없던 일이 됩니다.
        return True, san

    def check_over(self):
        """대국이 끝났으면 마무리하고 True 를 돌려줍니다."""
        outcome = self.board.outcome(claim_draw=True)
        if outcome is None:
            return False
        if outcome.winner is None:
            reasons = {
                chess.Termination.STALEMATE: "스테일메이트입니다.",
                chess.Termination.INSUFFICIENT_MATERIAL: "남은 말로는 이길 수 없습니다.",
                chess.Termination.FIFTY_MOVES: "50수 동안 잡거나 폰을 움직이지 않았습니다.",
                chess.Termination.THREEFOLD_REPETITION: "같은 국면이 세 번 나왔습니다.",
                chess.Termination.SEVENTYFIVE_MOVES: "75수 규칙입니다.",
                chess.Termination.FIVEFOLD_REPETITION: "같은 국면이 다섯 번 나왔습니다.",
            }
            self.finish(None, reasons.get(outcome.termination, "무승부입니다."))
        else:
            side = WHITE if outcome.winner == chess.WHITE else BLACK
            self.finish(side, f"체크메이트입니다. {self.names[side]} 님의 승리입니다.")
        return True

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
    def board_text(self, emojis, flip=False):
        """판을 그립니다. 이모지가 있으면 그림으로, 없으면 글자로 그립니다."""
        ranks = range(8) if flip else range(7, -1, -1)
        files = range(7, -1, -1) if flip else range(8)
        lines = []
        for rank in ranks:
            row = []
            for file in files:
                square = chess.square(file, rank)
                tone = "l" if (file + rank) % 2 else "d"
                piece = self.board.piece_at(square)
                if emojis:
                    if piece is None:
                        row.append(emojis[f"sq_{tone}"])
                    else:
                        side = "w" if piece.color == chess.WHITE else "b"
                        kind = chess.piece_symbol(piece.piece_type)
                        row.append(emojis[f"{side}{kind}_{tone}"])
                else:
                    row.append(UNICODE_PIECES.get(piece.symbol(), "·") if piece else "·")
            if emojis:
                lines.append("".join(row) + f" `{rank + 1}`")
            else:
                lines.append(f"`{rank + 1}` " + " ".join(row))
        labels = [FILES[f] for f in files]
        if emojis:
            lines.append("`" + "  ".join(labels) + "`")
            return "\n".join(lines)
        lines.append("`  " + " ".join(labels) + "`")
        return "```\n" + "\n".join(lines).replace("`", "") + "\n```"

    def status_line(self):
        if self.board.is_check():
            return f"⚠ **체크!** {self.actor_name} 님의 킹이 위험합니다."
        return ""

    def history_text(self, limit=12):
        """최근 기보를 '1. e4 e5' 모양으로 보여 줍니다."""
        moves = []
        replay = chess.Board()
        for move in self.board.move_stack:
            moves.append(replay.san(move))
            replay.push(move)
        if not moves:
            return "아직 둔 수가 없습니다."
        pairs = []
        for i in range(0, len(moves), 2):
            num = i // 2 + 1
            white = moves[i]
            black = moves[i + 1] if i + 1 < len(moves) else ""
            pairs.append(f"{num}. {white} {black}".strip())
        shown = pairs[-limit:]
        text = "  ".join(shown)
        if len(pairs) > limit:
            text = "…  " + text
        return text

    def render(self, flip=None, picked=None):
        """판 그림을 discord.File 로 돌려줍니다. 못 그리면 None 입니다."""
        if flip is None:
            flip = self.flip
        last = self.board.peek() if self.board.move_stack else None
        square = None
        targets = ()
        if picked:
            try:
                square = chess.parse_square(picked)
                targets = {m.to_square for m in self.board.legal_moves
                           if m.from_square == square}
            except ValueError:
                square = None
        buf = render_png(self.board, last, flip, square, targets)
        if buf is None:
            return None
        return discord.File(buf, filename="board.png")

    def payload(self, guild, notice="", picked=None):
        """(임베드, 그림파일) 을 함께 돌려줍니다. 그림이 안 되면 글자 판으로 갑니다."""
        picture = self.render(picked=picked)
        return self.embed(guild, notice, self.flip, picture is not None), picture

    def embed(self, guild, notice="", flip=False, picture=False):
        emojis = None if picture else emoji_map(guild)
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
            title = f"♟  {self.actor_name} 님의 차례입니다"

        e = discord.Embed(title=title, color=color)

        parts = []
        if notice:
            parts.append(notice)
        status = self.status_line()
        if status and not self.finished:
            parts.append(status)
        if picture:
            e.set_image(url="attachment://board.png")
        else:
            parts.append(self.board_text(emojis, flip))
        e.description = "\n".join(parts)[:4096] or None

        if self.finished:
            e.add_field(name="🏁 결과", value=self.result, inline=False)
        else:
            side = "백" if self.board.turn == chess.WHITE else "흑"
            e.add_field(
                name="🎯 이번 수",
                value=(f"**{side}** 차례입니다 · {self.move_number()}수째\n"
                       f"채팅에 `e4` `Nf3` `O-O` `e2e4` 처럼 적어 주세요."),
                inline=False)

        e.add_field(name="📜 기보", value=self.history_text()[:1024], inline=False)
        footer = f"⬜ {self.names[WHITE]} · ⬛ {self.names[BLACK]}"
        if picture:
            footer += " · 노란 칸=직전 수 · 빨간 칸=체크"
        elif not emojis:
            footer += " · 그림을 못 그려 글자 판으로 보여 드립니다"
        e.set_footer(text=footer)
        return e


    # -- 버튼용 목록 ------------------------------------------------
    KOREAN = {"p": "폰", "n": "나이트", "b": "비숍", "r": "룩", "q": "퀸", "k": "킹"}
    SYMBOL = {"p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚"}

    def movable_squares(self):
        """지금 움직일 수 있는 말들의 자리입니다. (자리, 보여 줄 이름) 목록입니다."""
        seen = {}
        for move in self.board.legal_moves:
            seen.setdefault(move.from_square, 0)
            seen[move.from_square] += 1
        rows = []
        for square, count in seen.items():
            piece = self.board.piece_at(square)
            kind = chess.piece_symbol(piece.piece_type)
            name = chess.square_name(square)
            rows.append((name,
                         f"{self.SYMBOL[kind]} {name}  {self.KOREAN[kind]}",
                         f"갈 수 있는 곳 {count}군데"))
        rows.sort(key=lambda r: r[0])
        return rows

    def destinations(self, from_name):
        """고른 말이 갈 수 있는 곳입니다. (수 표기, 보여 줄 이름, 설명) 목록입니다."""
        try:
            origin = chess.parse_square(from_name)
        except ValueError:
            return []
        rows = []
        for move in self.board.legal_moves:
            if move.from_square != origin:
                continue
            san = self.board.san(move)
            target = chess.square_name(move.to_square)
            note = []
            if self.board.is_capture(move):
                note.append("잡기")
            if self.board.gives_check(move):
                note.append("체크")
            if move.promotion:
                name = self.KOREAN[chess.piece_symbol(move.promotion)]
                note.append(f"{name}{_ro(name)} 승격")
            label = f"{target}  {san}"
            rows.append((move.uci(), label[:100], (" · ".join(note) or "이동")[:100]))
        rows.sort(key=lambda r: r[1])
        return rows


class ChessRegistry:
    """채널마다 체스 대국 하나씩만 둡니다."""

    def __init__(self):
        self.games = {}

    def get(self, channel_id):
        return self.games.get(channel_id)

    def put(self, game):
        self.games[game.channel_id] = game

    def drop(self, channel_id):
        self.games.pop(channel_id, None)
