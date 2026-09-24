"""Prefix-command adapter for the existing discord.Client bot."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
import asyncio
import logging
import time

import discord

from chemistry_engine import (
    ARROW, ELEMENT_DATA, ELEMENTS, MAX_INPUT, ChemistryError,
    balance_equation, calculate_amounts, check_input, format_number,
    parse_formula, parse_sum, sum_composition,
)
from chemistry_reactions import (
    DISSOCIATION, REACTION_DATA, RULE_DATA, SOLIDS, ReactionResult,
    parse_conditions, predict_reaction, saturation, split_options,
)


LOGGER = logging.getLogger(__name__)
COOLDOWN_SECONDS = 1.0
_LAST_USE: OrderedDict[tuple[int, int], float] = OrderedDict()
_IN_FLIGHT: set[tuple[int, int]] = set()
COMMANDS = {
    "!화학": "auto", "!원자": "atoms", "!질량": "mass",
    "!계수": "balance", "!균형": "balance", "!양적": "amounts",
    "!반응": "reaction", "!생성물": "reaction", "!침전": "precipitation",
    "!화학자료": "sources", "!도움": "help", "!help": "help",
    "!명령어": "help", "!화학도움": "help",
}
SUBCOMMANDS = {key.removeprefix("!"): value for key, value in COMMANDS.items() if key != "!화학"}
HELP = (
    "**화학 계산기**\n"
    "`!원자 Ca(OH)2` — 원소별 개수·전하·몰질량\n"
    "`!원자 2H2O + CO2` — 여러 화학식의 원자 수 합산\n"
    "`!질량 MgSO4·7H2O` — 화학식 단위의 몰질량\n"
    "`!계수 Mg(OH)2 -> Mg^2+ + OH^-` — 주어진 반응식의 계수\n"
    "`!양적 Mg(OH)2 -> Mg^2+ + OH^- | Mg(OH)2=1mol` — 지정한 식의 이론적 양\n"
    "`!반응 C6H12O6 + 6O2 + 6H2O` — 완전 산화를 가정한 생성물·총괄식\n"
    "`!반응 CaCl2 + Na2CO3 + KCl` — 여러 물질에서 생성물 후보 탐색\n"
    "`!생성물 HCl + NaHCO3` — 산염기 반응의 생성물 후보\n"
    "`!침전 CaCO3 | 용매=물 | 온도=25 | Ca^2+=0.001M | CO3^2-=0.001M` — 자유 이온 농도로 포화 여부 계산\n"
    "`!화학자료` — 출처와 지원 범위\n\n"
    "`!화학 H2O`처럼 쓰면 식을 읽고, 화살표가 있으면 계수를, +만 있으면 반응 후보를 확인합니다.\n"
    "생성물 탐색은 **최대 16개 물질**을 받으며, 조건을 생략해도 후보와 적용 가정을 보여줍니다. 수용액 판정은 `| 용매=물 | 온도=25`를 지정하세요.\n"
    "`| 유형=수용액` 또는 `| 유형=완전산화`로 탐색 범위를 고를 수 있습니다. 여러 후보는 경쟁·단계별 반응일 수 있으며 최종 혼합물로 확정하지 않습니다.\n"
    "전하는 `Ca^2+`, 결정수는 `·`로 표시해 주세요. 실제 생성량·반응 경로·구조에 따른 모든 반응을 예측하는 도구는 아닙니다."
)


@dataclass(frozen=True)
class Reply:
    title: str
    text: str
    status: str = "OK"


def _atom_line(atoms: dict[str, int]) -> str:
    return " · ".join(f"{symbol} {count:,}개" for symbol, count in sorted(atoms.items(), key=lambda x: ELEMENTS[x[0]]["atomic_number"])) or "원자 없음(전자)"


def _formula_reply(expression: str, mass_only: bool = False) -> Reply:
    species = parse_sum(expression)
    lines = []
    for sp in species:
        lines.append(f"**{sp.label}**" + (f" · 앞의 계수 {sp.coefficient}" if sp.coefficient != 1 else ""))
        if not mass_only:
            lines.append("단위당: " + _atom_line(sp.atoms) + f" · 전하 {sp.charge:+d}")
            if sp.coefficient != 1:
                lines.append("계수 적용: " + _atom_line(sp.total_atoms) + f" · 총전하 {sp.total_charge:+d}")
        mass = sp.molar_mass
        if mass is None:
            lines.append("몰질량: 표준 원자량만으로 계산할 수 없습니다(동위원소 정보 등이 필요).")
        else:
            lines.append(f"몰질량 ≈ {format_number(mass, 8)} g/mol")
        lines.append("")
    if len(species) > 1:
        atoms, charge = sum_composition(species)
        lines += ["**입력 전체 합계**", _atom_line(atoms), f"총전하 {charge:+d}", "각 화학식의 원자 수를 합산했으며, 새 물질의 생성을 판정한 결과는 아닙니다."]
    lines.append("몰질량은 CIAAW 2024 표의 근삿값입니다. 식 앞 계수는 물질 자체의 몰질량을 바꾸지 않습니다.")
    return Reply("몰질량 계산" if mass_only else "원자 수 계산", "\n".join(lines), "COUNTED")


def _balance_reply(expression: str) -> Reply:
    equation = balance_equation(expression)
    n = len(equation.reactants)
    totals = {}
    charge = 0
    for sp, c in zip(equation.reactants, equation.coefficients[:n]):
        for symbol, count in sp.atoms.items():
            totals[symbol] = totals.get(symbol, 0) + count * c
        charge += sp.charge * c
    return Reply("반응식 계수 계산", "\n".join((
        equation.text,
        "최소 정수 계수: " + " : ".join(map(str, equation.coefficients)),
        "양쪽 원자 수: " + _atom_line(totals),
        f"양쪽 전하: {charge:+d}",
        "원소·전하 보존을 확인했습니다. 입력한 생성물이 실제로 생기는지, 반응이 진행되는지는 별도 판정이 필요합니다.",
    )), "BALANCED_ONLY")


def _amounts_reply(text: str) -> Reply:
    expression, options = split_options(text)
    equation = balance_equation(expression)
    result = calculate_amounts(equation, options)
    lines = [equation.text, "**지정한 단일 반응이 정방향으로 진행할 때의 이론적 최대치**",
             "제한 반응물: " + ", ".join(result["limiting"])]
    for species, amount in result["products"]:
        line = f"{species.label}: {format_number(amount)} mol"
        if species.molar_mass is not None:
            line += f" (약 {format_number(amount * Fraction(species.molar_mass))} g)"
        lines.append(line)
    lines.append("반응물 잔류량: " + " · ".join(f"{name} {format_number(n)} mol" for name, n in result["remaining"]))
    lines.append("실제 수율·평형 도달량·반응 시간은 계산하지 않았습니다. 실제 반응 가능성을 보증하는 결과는 아닙니다.")
    return Reply("양적 관계 계산", "\n".join(lines), "THEORETICAL_STOICHIOMETRY")


def _reaction_reply(result: ReactionResult) -> Reply:
    names = {
        "NEEDS_CONDITIONS": "조건을 더 입력해 주세요",
        "OUT_OF_DOMAIN": "현재 모델의 범위를 벗어났습니다",
        "UNSUPPORTED_REACTION": "등록된 규칙으로 판단할 수 없습니다",
        "UNSUPPORTED_CONDITIONS": "현재 계산에서 다루지 않는 조건입니다",
        "REACTION_RULE_APPLIED": "조건별 반응식",
        "COMPETING_CANDIDATES": "여러 반응 후보가 있습니다",
        "CONDITIONAL_PRODUCTS": "가정에 따른 생성물 후보",
        "PARTIAL_CANDIDATES": "일부 물질의 생성물 후보 · 전체 반응 미확정",
        "SUPERSATURATED": "모델상 과포화",
        "UNDERSATURATED": "모델상 불포화",
        "AT_SATURATION": "모델상 포화 경계",
    }
    lines = list(result.lines)
    if result.source_ids:
        sources = REACTION_DATA["sources"]
        lines.append("\n근거: " + " · ".join(f"[{sources[s]['title']}]({sources[s]['url']})" for s in result.source_ids))
    title = names.get(result.status, "반응 계산")
    if result.status == "NEEDS_CONDITIONS" and any(line.startswith("**후보 ") for line in lines):
        title = "생성물 후보 · 조건 확인 필요"
    return Reply(title, "\n".join(lines), result.status)


def evaluate(content: str) -> Reply | None:
    """Pure command evaluation, also used by tests without a Discord connection."""
    parts = content.strip().split(maxsplit=1)
    if not parts or parts[0] not in COMMANDS:
        return None
    mode = COMMANDS[parts[0]]
    argument = parts[1].strip() if len(parts) == 2 else ""
    try:
        if len(content) > MAX_INPUT + 30:
            raise ChemistryError("INPUT_LIMIT", "한 번의 명령은 1,200자 안으로 입력해 주세요.")
        if mode == "auto":
            if not argument:
                mode = "help"
            else:
                sub = argument.split(maxsplit=1)
                if sub[0] in SUBCOMMANDS:
                    mode = SUBCOMMANDS[sub[0]]
                    argument = sub[1] if len(sub) == 2 else ""
                else:
                    expression = argument.split("|", 1)[0]
                    if ARROW.search(expression):
                        mode = "balance"
                    else:
                        mode = "reaction" if len(parse_sum(expression)) > 1 else "atoms"
        if mode == "help":
            return Reply("화학 채널 도움말", HELP)
        if mode == "sources":
            return Reply("계산 자료와 지원 범위", "\n".join((
                f"원소 기호 {len(ELEMENTS)}개 · 중첩 괄호·결정수·이온·전자·원자 수 합산",
                "유리수 연산으로 반응식 계수 및 전하 보존 확인",
                f"수용액 해리 기록 {len(DISSOCIATION)}개 · 포화 판정용 고체 {len(SOLIDS)}개",
                f"산염기 규칙 {len(RULE_DATA['aqueous_rules'])}개 · C/H/O 조성의 조건부 완전 산화 총괄식",
                "2~16개 물질을 함께 검색하고 각 후보의 생성물·균형식·가정·미판정 입력을 표시합니다.",
                "수용액 후보: 강산·강염기 중화, 탄산·탄산수소·인산 이온의 단계별 산염기 반응, 등록 고체 침전",
                "지원 고체: " + ", ".join(SOLIDS),
                f"[원자량: CIAAW 2024]({ELEMENT_DATA['source']['url']})",
                *[f"[{s['title']}]({s['url']})" for s in REACTION_DATA["sources"].values()],
                "모든 반응을 예측하는 도구는 아닙니다. 표준 원자량이 없는 원소는 원자 수만 계산합니다.",
                "생성형 AI·외부 조회 API 없이 저장된 데이터와 계산 규칙으로 작동합니다.",
            )))
        check_input(argument)
        if mode in ("atoms", "mass", "balance") and "|" in argument:
            raise ChemistryError("UNSUPPORTED_CONDITIONS", "이 명령은 식 자체를 계산합니다. 조건은 !반응 또는 !침전 명령에 입력해 주세요.")
        if mode in ("atoms", "mass"):
            return _formula_reply(argument, mode == "mass")
        if mode == "balance":
            return _balance_reply(argument)
        if mode == "amounts":
            return _amounts_reply(argument)
        expression, options = split_options(argument)
        conditions = parse_conditions(options)
        result = saturation(expression, conditions) if mode == "precipitation" else predict_reaction(expression, conditions)
        return _reaction_reply(result)
    except ChemistryError as error:
        return Reply("입력을 확인해 주세요", str(error) + "\n`!화학`으로 사용법을 볼 수 있습니다.", error.code)


def build_embeds(reply: Reply) -> list[discord.Embed]:
    """Keep every individual embed below Discord's description/total limits."""
    pages = []
    current = ""
    for line in reply.text.splitlines():
        # A pathological single long line is also split; never silently truncated.
        pieces = [line[i:i + 3600] for i in range(0, len(line), 3600)] or [""]
        for piece in pieces:
            if len(current) + len(piece) + 1 > 3800:
                pages.append(current.rstrip())
                current = ""
            current += piece + "\n"
    if current.strip() or not pages:
        pages.append(current.rstrip() or "결과가 없습니다.")
    embeds = []
    for index, page in enumerate(pages, 1):
        suffix = f" ({index}/{len(pages)})" if len(pages) > 1 else ""
        embed = discord.Embed(title="🧪 " + reply.title + suffix, description=page, color=0x55B7A5)
        embed.set_footer(text="화학 계산기 · 저장된 규칙과 데이터로 계산")
        embeds.append(embed)
    return embeds


async def handle_message(message, channel_id: int) -> bool:
    if message.author.bot or message.guild is None or message.channel.id != channel_id:
        return False
    parts = message.content.strip().split(maxsplit=1)
    if not parts or parts[0] not in COMMANDS:
        return False
    key = (message.channel.id, message.author.id)
    now = time.monotonic()
    if key in _IN_FLIGHT or now - _LAST_USE.get(key, -1e30) < COOLDOWN_SECONDS:
        return True
    if len(_IN_FLIGHT) >= 8:
        await message.channel.send("계산 요청이 많습니다. 잠시 뒤 다시 입력해 주세요.", allowed_mentions=discord.AllowedMentions.none())
        return True
    _LAST_USE[key] = now
    _LAST_USE.move_to_end(key)
    while len(_LAST_USE) > 2048:
        _LAST_USE.popitem(last=False)
    _IN_FLIGHT.add(key)
    try:
        reply = await asyncio.to_thread(evaluate, message.content)
        if reply:
            for embed in build_embeds(reply):
                await message.channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        LOGGER.exception("Chemistry response could not be delivered")
    except Exception:
        LOGGER.exception("Chemistry calculation failed")
        try:
            await message.channel.send("계산 중 오류가 발생했습니다. 입력을 줄여 다시 시도해 주세요.", allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            LOGGER.exception("Chemistry error response could not be delivered")
    finally:
        _IN_FLIGHT.discard(key)
    return True
