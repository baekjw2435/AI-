"""Hunmin lookup in two fixed dictionary channels; no game state required."""
from dataclasses import dataclass
from pathlib import Path
import re

import discord

from hunmin_engine import COMPLEX, STANDARD, WORD_FILES, HunminDictionary, normalize_pair


CHANNEL_MODES = {1553954061294772335: STANDARD, 1553954129712254976: COMPLEX}
HELP_COMMANDS = {"!훈민", "!도움", "!도움말", "!help", "!명령어", "!모드"}
DICTIONARIES = {}
PAGE_SIZE = 30


def load_dictionaries():
    loaded = {}
    for mode, filename in WORD_FILES.items():
        try:
            dictionary = HunminDictionary.from_file(Path(__file__).parent / filename)
        except (OSError, UnicodeError) as error:
            print(f"[경고] 훈민 {mode} 사전 로드 실패: {error}")
            continue
        loaded[mode] = dictionary
        print(f"[로드] 훈민 {mode} {dictionary.word_count:,}단어 · 원본 {dictionary.source_rows:,}행")
    DICTIONARIES.clear()
    DICTIONARIES.update(loaded)


def parse_request(content):
    parts = content.strip().split()
    if len(parts) not in (1, 2) or not parts[0].startswith("!"):
        raise ValueError("초성 두 글자를 붙여 입력해 주세요. 예: `!ㅎㅅ` · 다음 페이지: `!ㅎㅅ 2`")
    pair = normalize_pair(parts[0][1:])
    page = 1
    if len(parts) == 2:
        if not re.fullmatch(r"[1-9][0-9]{0,4}", parts[1]):
            raise ValueError("페이지는 1 이상의 정수로 입력해 주세요. 예: `!ㅎㅅ 2`")
        page = int(parts[1])
    return pair, page


def help_embed(mode):
    embed = discord.Embed(
        title=f"🔡 훈민정음 · {mode}사전",
        description=(
            "`!ㅎㅅ`처럼 초성 두 글자를 입력해 주세요.\n"
            "앞 초성이 한 번 이상 이어진 뒤, 뒤 초성이 한 번 이상 이어지는 단어를 찾습니다.\n"
            "예: `ㅎㅎㅎㅅ` · `ㅎㅎㅅㅅ` · `ㅎㅅㅅㅅ`\n\n"
            "`!ㅇㅇ` · `!ㅈㅈ`처럼 같은 초성도 가능합니다.\n"
            "두 글자 이상 단어를 **긴 순서**, 같은 길이는 **가나다순**으로 표시합니다.\n"
            "단어 뒤 숫자는 글자 수입니다. 예: `현수선상수5`\n\n"
            "한 페이지에 최대 30개씩 표시합니다. 이전·다음 버튼 또는 `!ㅎㅅ 2`로 넘겨 주세요."
        ),
        color=0xC2F74A,
    )
    embed.set_footer(text=f"이 채널은 {mode}사전 훈민정음 전용입니다.")
    return embed


@dataclass(frozen=True)
class SearchResult:
    mode: str
    pair: str
    total: int
    pages: tuple

    @property
    def page_count(self):
        return max(1, len(self.pages))

    def embed(self, page=0):
        if not 0 <= page < self.page_count:
            raise ValueError(f"페이지는 1~{self.page_count:,} 사이로 입력해 주세요.")
        description = f"검색 결과 **{self.total:,}개** · 긴 순서 · 같은 길이는 가나다순"
        description += "\n\n" + (self.pages[page] if self.pages else "해당하는 단어가 없습니다.")
        embed = discord.Embed(
            title=f"🔡 {self.pair} · {self.mode}사전 훈민정음",
            description=description,
            color=0xC2F74A,
        )
        embed.set_footer(text=f"숫자는 글자 수 · {page + 1}/{self.page_count}페이지 · !{self.pair} <페이지>")
        return embed


def build_result(dictionary, mode, pair):
    pair = normalize_pair(pair)
    words = dictionary.search(pair)
    pages, lines, length = [], [], 0
    for word in words:
        line = f"{word}{len(word)}"
        if lines and (len(lines) >= PAGE_SIZE or length + len(line) + 1 > 3500):
            pages.append("\n".join(lines))
            lines, length = [], 0
        lines.append(line)
        length += len(line) + 1
    if lines:
        pages.append("\n".join(lines))
    return SearchResult(mode, pair, len(words), tuple(pages))


class SearchView(discord.ui.View):
    def __init__(self, result, owner_id, channel_id, page=0):
        super().__init__(timeout=180)
        self.result, self.owner_id, self.channel_id = result, owner_id, channel_id
        self.page, self.message = page, None
        self.update_buttons()

    def update_buttons(self):
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page >= self.result.page_count - 1

    async def interaction_check(self, interaction):
        if interaction.channel_id != self.channel_id or interaction.user.id != self.owner_id:
            await interaction.response.send_message("검색한 사람만 페이지를 넘길 수 있습니다. 직접 검색해 주세요.", ephemeral=True)
            return False
        return True

    async def move(self, interaction, delta):
        self.page = max(0, min(self.page + delta, self.result.page_count - 1))
        self.update_buttons()
        await interaction.response.edit_message(embed=self.result.embed(self.page), view=self)

    @discord.ui.button(label="이전", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.move(interaction, -1)

    @discord.ui.button(label="다음", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        await self.move(interaction, 1)

    async def on_timeout(self):
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


async def handle_message(message):
    mode = CHANNEL_MODES.get(message.channel.id)
    if mode is None or message.author.bot or message.guild is None:
        return False
    content = message.content.strip()
    if not content.startswith("!"):
        return False
    if content in HELP_COMMANDS:
        await message.channel.send(embed=help_embed(mode))
        return True
    try:
        pair, page = parse_request(content)
        dictionary = DICTIONARIES.get(mode)
        if dictionary is None:
            await message.channel.send(f"훈민정음 {mode} 단어 자료를 불러오지 못했습니다. 운영자가 배포 로그를 확인해야 합니다.")
            return True
        result = build_result(dictionary, mode, pair)
        embed = result.embed(page - 1)
        if result.page_count > 1:
            view = SearchView(result, message.author.id, message.channel.id, page - 1)
            view.message = await message.channel.send(embed=embed, view=view)
        else:
            await message.channel.send(embed=embed)
    except ValueError as error:
        await message.channel.send(str(error))
    return True
