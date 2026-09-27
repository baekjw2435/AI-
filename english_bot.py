"""Discord commands for the two dedicated English lookup channels."""
from dataclasses import dataclass
import re

import discord

from english_engine import CLASSIC, KKUTU, EnglishDictionary, long_first, short_first


CHANNEL_MODES = {1553662302371319891: CLASSIC, 1553662388752883792: KKUTU}
COMMANDS = {"!장문", "!돌림", "!종결", "!장문종결", "!공격", "!한방"}
HELP_COMMANDS = {"!도움", "!help", "!명령어", "!영어", "!모드"}
LONG_COMMANDS = {"!장문", "!장문종결"}
DICTIONARY = None


def load_dictionary():
    global DICTIONARY
    DICTIONARY = EnglishDictionary.from_file()
    print(f"[로드] 영어 사전 {len(DICTIONARY.words):,}단어 (2글자 이상)")


def chunks(lines, *, limit=3500, size=30):
    pages, current, length = [], [], 0
    for line in lines:
        if current and (len(current) >= size or length + len(line) + 1 > limit):
            pages.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        pages.append("\n".join(current))
    return tuple(pages)


@dataclass(frozen=True)
class SearchResult:
    mode: str
    title: str
    summary: str
    body: tuple = ()
    groups: tuple = ()

    @property
    def page_count(self):
        return max([1, len(self.body), *(len(pages) for _, pages in self.groups)])

    def embed(self, page=0):
        if not 0 <= page < self.page_count:
            raise ValueError(f"페이지는 1~{self.page_count:,} 사이로 입력해 주세요.")
        description = self.summary
        if self.body:
            description += "\n\n" + self.body[page]
        embed = discord.Embed(title=self.title, description=description, color=0x5AC8FA)
        for label, pages in self.groups:
            if page < len(pages):
                embed.add_field(name=label, value=pages[page], inline=False)
        embed.set_footer(text=(f"{self.mode} · {page + 1}/{self.page_count}페이지"
                               " · 사용한 단어는 직접 제외해 주세요."))
        return embed


def help_embed(mode):
    if mode == CLASSIC:
        explanation = "앞 단어의 끝 **1글자**로 잇습니다. 예: `apple → elephant`"
        examples = "`!장문 n` · `!돌림 n` · `!종결 n` · `!장문종결 n`"
    else:
        explanation = ("2글자 단어는 끝 **2글자**, 3글자 이상은 끝 **3글자 또는 2글자**로 잇습니다.\n"
                       "예: `crawl → awl` 가능 · `ab → b…` 불가")
        examples = ("`!장문 ad` · `!장문 abc` · `!공격 ab` · `!공격 abc`\n"
                    "`!돌림 ab` · `!한방 ab` · `!종결 ght` · `!장문종결 ght`")
    text = (f"{explanation}\n\n{examples}\n\n"
            "**장문 / 장문종결**: 긴 순서 TOP 30. 뒤에 개수를 붙이면 1~100개 표시합니다.\n"
            "예: `!장문 " + ("n" if mode == CLASSIC else "ad") + " 50`\n"
            "**돌림**: 검색한 글자로 시작하고 같은 글자로 끝나는 단어.\n"
            "**종결**: 검색한 글자로 끝나는 단어를 짧은 순서로 표시합니다.\n"
            "이전·다음 버튼으로 넘길 수 있습니다. 종결·돌림·공격·한방 뒤 숫자는 페이지입니다.")
    if mode == KKUTU:
        text += ("\n\n**공격 분류**: ⚡ 한방 = 이을 수 있는 단어 0개 · 🗡️ 공격 = 1~5개 · 🔄 돌림.\n"
                 "이을 수 있는 단어는 끝 2·3글자로 시작하는 단어를 합쳐 찾으며, 사용 이력을 반영하지 않은 사전 기준입니다.\n"
                 "2글자 단어도 포함합니다. 한 단어가 공격과 돌림에 함께 표시될 수 있습니다.")
    embed = discord.Embed(title=f"🔤 {mode} 검색 도움말", description=text, color=0x5AC8FA)
    embed.set_footer(text="대소문자 구분 없음 · 영어 단어 2글자 이상")
    return embed


def parse_request(content, mode):
    parts = content.strip().split()
    command = parts[0] if parts else ""
    if command not in COMMANDS:
        raise ValueError("영어 검색 명령은 `!도움`에서 확인해 주세요.")
    if mode == CLASSIC and command in {"!공격", "!한방"}:
        raise ValueError("공격·한방 검색은 영어 끄투 채널 <#1553662388752883792>에서 사용해 주세요.")
    example = "n" if mode == CLASSIC else ("ght" if command in {"!종결", "!장문종결"} else "ab")
    if len(parts) not in (2, 3):
        raise ValueError(f"검색할 글자를 입력해 주세요. 예: `{command} {example}`")
    query = parts[1].lower()
    if not re.fullmatch(r"[a-z]{1,64}", query):
        raise ValueError("검색 글자는 영문 A~Z로 입력해 주세요. 대소문자는 구분하지 않습니다.")
    if command not in {"!종결", "!장문종결"}:
        lengths = {1} if mode == CLASSIC else {2, 3}
        if len(query) not in lengths:
            expected = "1글자" if mode == CLASSIC else "2글자 또는 3글자"
            raise ValueError(f"{mode}의 시작 글자는 {expected}로 입력해 주세요. 예: `{command} {example}`")
    number = 30 if command in LONG_COMMANDS else 1
    if len(parts) == 3:
        if not re.fullmatch(r"[1-9][0-9]{0,4}", parts[2]):
            raise ValueError("표시 개수 또는 페이지는 양의 정수로 입력해 주세요.")
        number = int(parts[2])
    if command in LONG_COMMANDS and number > 100:
        raise ValueError("장문 표시 개수는 1~100 사이로 입력해 주세요.")
    return command, query, number


def build_result(dictionary, mode, command, query, number):
    if command in {"!공격", "!한방"}:
        found = dictionary.attacks(query)
        groups = [("⚡ 한방", found.kills)]
        if command == "!공격":
            groups += [("🗡️ 공격 · 이을 수 있는 단어 1~5개", found.attacks), ("🔄 돌림", found.loops)]
        loop_set = set(found.loops)

        def line(word):
            count = dictionary.reply_count(word)
            tag = " · 🔄" if word in loop_set else ""
            return f"`{word}` · 이을 수 있는 단어 **{count}개**{tag}"

        fields = tuple((f"{label} · {len(words):,}개", chunks(map(line, words), limit=950, size=20))
                       for label, words in groups if words)
        summary = " · ".join(f"{label.split(' · ')[0]} **{len(words):,}**" for label, words in groups)
        if not fields:
            summary += "\n해당하는 단어가 없습니다."
        else:
            summary += "\n이을 수 있는 단어의 수는 사전을 기준으로 계산하며, 같은 단어는 한 번만 셉니다."
        return SearchResult(mode, f"🎯 {query}- 분석 · {mode}", summary, groups=fields)

    if command == "!돌림":
        matched = dictionary.loops(query)
        words = matched
        title = f"🔄 {query}…{query} 돌림"
    elif command in {"!종결", "!장문종결"}:
        matched = dictionary.ending(query)
        words = tuple(sorted(matched, key=long_first if command in LONG_COMMANDS else short_first))
        title = f"🏁 -{query} 종결" if command == "!종결" else f"📏 -{query} 장문종결"
    else:
        matched = dictionary.starting(query)
        words = tuple(sorted(matched, key=long_first))
        title = f"📏 {query}- 장문"
    summary = f"검색 결과 **{len(matched):,}개**"
    if command in LONG_COMMANDS:
        words = words[:number]
        title += f" · TOP {len(words)}"
        summary += " · 긴 순서"
    else:
        summary += " · 짧은 순서"
    if not words:
        summary += "\n해당하는 단어가 없습니다."
    pages = chunks(f"**{i}.** `{word}` · {len(word)}자" for i, word in enumerate(words, 1))
    return SearchResult(mode, title + f" · {mode}", summary, body=pages)


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
    if not mode or message.author.bot or message.guild is None:
        return False
    content = message.content.strip()
    if not content.startswith("!"):
        return False
    if content in HELP_COMMANDS:
        await message.channel.send(embed=help_embed(mode))
        return True
    try:
        command, query, number = parse_request(content, mode)
        if DICTIONARY is None:
            await message.channel.send("영어 단어 자료를 불러오지 못했습니다. 운영자가 배포 로그를 확인해야 합니다.")
            return True
        result = build_result(DICTIONARY, mode, command, query, number)
        page = 0 if command in LONG_COMMANDS else number - 1
        embed = result.embed(page)
        if result.page_count > 1:
            view = SearchView(result, message.author.id, message.channel.id, page)
            view.message = await message.channel.send(embed=embed, view=view)
        else:
            await message.channel.send(embed=embed)
    except ValueError as exc:
        await message.channel.send(str(exc))
    return True
