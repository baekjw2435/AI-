# -*- coding: utf-8 -*-
"""체스 대국 모듈입니다.

사람 대 사람으로만 둡니다. 규칙은 python-chess 가 전부 맡습니다.
앙파상, 캐슬링, 승격, 스테일메이트, 50수 규칙, 3회 동형반복까지 들어 있습니다.

판은 서버에 올린 이모지로 그립니다. 이모지가 없으면 글자 판으로 대신합니다.
"""

import asyncio, re

import chess
import discord

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
    r"^(?:[KQRBN][a-h1-8]?x?[a-h][1-8]"          # Nf3, Nbd2, Qxe5
    r"|[a-h]x?[a-h]?[1-8](?:=[QRBNqrbn])?"       # e4, exd5, e8=Q
    r"|[a-h][1-8][a-h][1-8][qrbnQRBN]?"          # e2e4 (UCI)
    r"|[Oo0]-[Oo0](?:-[Oo0])?)"                  # O-O, O-O-O
    r"[+#]?$"
)

FILES = "abcdefgh"


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
        self.timer = None
        self.timer_token = 0

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
    def push(self, text):
        """한 수를 둡니다. 통과하면 (True, 기보), 아니면 (False, 사유) 입니다."""
        text = text.strip()
        move = None
        try:
            move = self.board.parse_san(text)
        except ValueError:
            try:
                candidate = chess.Move.from_uci(text.lower())
                if candidate in self.board.legal_moves:
                    move = candidate
            except ValueError:
                move = None
        if move is None:
            return False, (f"`{text}` 는 지금 둘 수 없는 수입니다. "
                           f"`e4`, `Nf3`, `O-O`, `e2e4` 처럼 입력해 주세요.")
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

    def embed(self, guild, notice="", flip=False):
        emojis = emoji_map(guild)
        if self.finished:
            if self.winner is None:
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
        parts.append(self.board_text(emojis, flip))
        e.description = "\n".join(parts)[:4096]

        if self.finished:
            e.add_field(name="🏁 결과", value=self.result, inline=False)
        else:
            side = "백" if self.board.turn == chess.WHITE else "흑"
            e.add_field(
                name="🎯 이번 수",
                value=(f"**{side}** 차례입니다 · {self.move_number()}수째\n"
                       f"`e4` `Nf3` `O-O` `e2e4` 처럼 채팅에 바로 적어 주세요."),
                inline=False)

        e.add_field(name="📜 기보", value=self.history_text()[:1024], inline=False)
        footer = f"⬜ {self.names[WHITE]} · ⬛ {self.names[BLACK]}"
        if not emojis:
            footer += " · 이모지가 없어 글자 판으로 보여 드립니다"
        e.set_footer(text=footer)
        return e


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
