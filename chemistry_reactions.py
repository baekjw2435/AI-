"""Small, explicitly scoped aqueous reaction model, independent of Discord.

Reaction candidates come from ion composition, not a lookup of reactant pairs.
Missing data never means 'no reaction'. Supersaturation is not an observed yield.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import json
import re

from chemistry_engine import (
    DATA_DIR, NUMBER, ChemistryError, balance_equation, check_input,
    decimal_number, fail, format_number, parse_formula, parse_sum,
)


REACTION_DATA = json.loads((DATA_DIR / "aqueous.json").read_text(encoding="utf-8"))
SOLIDS = {row["formula"]: row for row in REACTION_DATA["solids"]}
DISSOCIATION = REACTION_DATA["dissociation"]
KNOWN_IONS = {ion for ions in DISSOCIATION.values() for ion in ions}
for _solid in SOLIDS.values():
    KNOWN_IONS.update(_solid["ions"])


@dataclass(frozen=True)
class ReactionResult:
    status: str
    lines: tuple[str, ...]
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Conditions:
    temperature_C: Decimal | None
    solvent: str | None
    concentrations: dict[str, Decimal]
    solid_present: bool | None


def split_options(text: str) -> tuple[str, dict[str, str]]:
    text = check_input(text)
    pieces = text.split("|")
    options = {}
    for item in pieces[1:]:
        if "=" not in item:
            fail("INVALID_INPUT", "조건은 | 온도=25 | 용매=물처럼 입력해 주세요.")
        key, value = (part.strip() for part in item.split("=", 1))
        if not key or not value or key in options:
            fail("INVALID_INPUT", "조건 이름과 값을 확인해 주세요. 같은 조건을 중복 지정할 수 없습니다.")
        options[key] = value
    return pieces[0].strip(), options


def parse_conditions(options: dict[str, str]) -> Conditions:
    temperature = None
    solvent = None
    solid_present = None
    concentrations = {}
    seen = set()
    for key, value in options.items():
        lower = key.lower()
        if lower in ("온도", "t", "temperature"):
            canonical = "temperature"
            m = re.fullmatch(rf"([+-]?{NUMBER})\s*(°?C|K|℃)?", value, re.I)
            if not m or len(m[1]) > 40:
                fail("INVALID_INPUT", "온도는 25C 또는 298.15K처럼 입력해 주세요.")
            temperature = Decimal(m[1])
            if (m[2] or "C").upper() == "K":
                temperature -= Decimal("273.15")
            if not temperature.is_finite() or temperature < Decimal("-273.15") or temperature > 10000:
                fail("INVALID_INPUT", "온도 값이 유효하지 않습니다.")
        elif lower in ("용매", "solvent"):
            canonical = "solvent"
            solvent = "water" if value.lower() in ("물", "수용액", "water", "h2o", "aq") else value
        elif lower in ("고체", "solid"):
            canonical = "solid"
            if value.lower() in ("있음", "있다", "yes", "true"):
                solid_present = True
            elif value.lower() in ("없음", "없다", "no", "false"):
                solid_present = False
            else:
                fail("INVALID_INPUT", "고체는 있음 또는 없음으로 지정해 주세요.")
        else:
            # These are FREE-ion concentrations in the final solution, not stock
            # solution concentrations or total elemental concentrations.
            try:
                ion = parse_formula(key)
            except ChemistryError:
                fail("UNSUPPORTED_CONDITIONS", "지원하는 조건은 온도·용매·고체 유무·자유 이온 농도입니다. 촉매·압력·pH·시간을 바꾼 계산은 아직 지원하지 않습니다.")
            if ion.formula not in KNOWN_IONS or ion.coefficient != 1 or ion.phase not in (None, "aq"):
                fail("INVALID_INPUT", "농도는 Ca^2+=0.001M처럼 등록된 자유 이온에 지정해 주세요.")
            canonical = "ion:" + ion.formula
            match = re.fullmatch(rf"({NUMBER})\s*(M|mol/L|mol/l)?", value)
            if not match:
                fail("INVALID_INPUT", "자유 이온 농도는 0.001M처럼 입력해 주세요.")
            concentrations[ion.formula] = decimal_number(match[1], Decimal("100"))
        if canonical in seen:
            fail("INVALID_INPUT", "같은 조건을 다른 이름으로 중복 지정했습니다.")
        seen.add(canonical)
    return Conditions(temperature, solvent, concentrations, solid_present)


def _domain(conditions: Conditions) -> ReactionResult | None:
    missing = []
    if conditions.solvent is None:
        missing.append("용매=물")
    elif conditions.solvent != "water":
        return ReactionResult("OUT_OF_DOMAIN", ("현재 반응 모델은 물을 용매로 하는 수용액만 다룹니다.",))
    if conditions.temperature_C is None:
        missing.append("온도=25")
    elif conditions.temperature_C != Decimal("25"):
        return ReactionResult("OUT_OF_DOMAIN", ("현재 등록된 반응 자료는 25 °C 기준입니다. 다른 온도로 임의 환산하지 않습니다.",))
    if missing:
        return ReactionResult("NEEDS_CONDITIONS", ("필요한 조건: " + " | ".join(missing),))
    # An intentionally conservative UI limit for the ideal-dilute approximation,
    # not a universal physical boundary between dilute and concentrated solutions.
    if any(c > Decimal("0.01") for c in conditions.concentrations.values()):
        return ReactionResult("OUT_OF_DOMAIN", ("이 계산은 희석 용액 근사이며, 자유 이온 농도 0.01 M 이하만 받도록 제한했습니다. 높은 농도에는 활동도 모델이 필요합니다.",))
    return None


def precipitation_equation(solid: dict) -> str:
    ions = " + ".join(ion + "(aq)" for ion in solid["ions"])
    if solid["waters"]:
        ions += " + H2O(l)"
    return balance_equation(ions + " -> " + solid["formula"] + "(s)").text


def saturation(solid_name: str, conditions: Conditions) -> ReactionResult:
    name = parse_formula(solid_name)
    if name.coefficient != 1 or name.charge or name.phase not in (None, "s"):
        fail("INVALID_INPUT", "침전 판정에는 고체 화학식 하나를 계수 없이 입력해 주세요.")
    solid = SOLIDS.get(name.formula)
    if solid is None:
        return ReactionResult("UNSUPPORTED_REACTION", ("이 고체의 용해도곱 자료는 아직 등록되어 있지 않습니다.", "지원 고체: " + ", ".join(SOLIDS)))
    outside = _domain(conditions)
    if outside:
        return outside
    required = set(solid["ions"])
    unexpected = set(conditions.concentrations) - required
    if unexpected:
        fail("UNSUPPORTED_CONDITIONS", "이 고체의 식에 쓰지 않는 농도 항목이 있습니다: " + ", ".join(sorted(unexpected)))
    missing = required - set(conditions.concentrations)
    if missing:
        return ReactionResult("NEEDS_CONDITIONS", (
            "후보 고체: " + solid["formula"],
            "자유 이온 농도가 필요합니다: " + ", ".join(sorted(missing)),
            "각 값은 최종 용액에서 다른 평형을 고려한 자유 이온 농도입니다. 원액 농도나 총농도를 그대로 넣지 마세요.",
        ), ("solubility", "equilibrium"))
    with localcontext() as context:
        context.prec = 40
        q = Decimal(1)
        for ion, power in solid["ions"].items():
            q *= conditions.concentrations[ion] ** power
        ksp = Decimal(solid["ksp"])
        ratio = q / ksp
    if abs(ratio - 1) <= Decimal("0.000001"):
        status, judgment = "AT_SATURATION", "주어진 근사 모델에서 포화 경계입니다."
    elif ratio > 1:
        status, judgment = "SUPERSATURATED", "이 고체에 대해 과포화입니다. 모델상 침전 방향의 구동력이 있습니다."
    else:
        status = "UNDERSATURATED"
        judgment = "이 고체에 대해 불포화이며 침전 조건을 충족하지 않습니다."
        if conditions.solid_present is True:
            judgment += " 해당 고체가 있으므로 용해 방향의 구동력이 있습니다."
        elif conditions.solid_present is None:
            judgment += " 용해 여부를 보려면 고체의 존재를 지정해 주세요."
    factors = " × ".join(f"[{ion}]" + (f"^{n}" if n != 1 else "") for ion, n in solid["ions"].items())
    lines = (
        f"{solid['name']} · {solid['formula']}",
        precipitation_equation(solid),
        f"Q = {factors} = {format_number(q)}",
        f"Ksp(25 °C) = {format_number(ksp)} · Q/Ksp = {format_number(ratio)}",
        judgment,
        "가정: 물, 25 °C, 희석 용액, 자유 이온 농도로 활동도를 근사. 물의 활동도는 1.",
        "출처 표의 화학종 기준 판정입니다. 실제 침전량·걸리는 시간·다른 결정형의 거동은 계산하지 않았습니다.",
    )
    return ReactionResult(status, lines, ("solubility", "equilibrium"))


def predict_reaction(text: str, conditions: Conditions) -> ReactionResult:
    species = parse_sum(text)
    if len(species) != 2:
        return ReactionResult("UNSUPPORTED_REACTION", ("조건별 반응 판정은 물질 두 개부터 지원합니다. 여러 물질의 원자 수 합산과 반응식 계수 계산은 따로 사용할 수 있습니다.",))
    if any(sp.coefficient != 1 for sp in species):
        fail("INVALID_INPUT", "반응 후보를 찾을 때는 앞의 계수를 빼 주세요. 입력 계수는 실제 투입량이 아닙니다.")
    if any(sp.phase not in (None, "aq") for sp in species):
        return ReactionResult("OUT_OF_DOMAIN", ("현재 후보 생성 규칙은 수용액 속 물질을 대상으로 합니다. 입력한 기체·고체·액체의 반응은 따로 모델링해야 합니다.",))
    ion_sets = []
    for sp in species:
        if sp.formula in KNOWN_IONS:
            ion_sets.append({sp.formula})
        elif sp.formula in DISSOCIATION:
            ion_sets.append(set(DISSOCIATION[sp.formula]))
        else:
            return ReactionResult("UNSUPPORTED_REACTION", (
                f"{sp.formula}의 반응 판정 규칙이 아직 없습니다.",
                "반응하지 않는다는 뜻은 아닙니다. 분자식만으로 구조가 정해지지 않는 물질도 있습니다.",
            ))
    outside = _domain(conditions)
    if outside:
        return outside
    ions = set.union(*ion_sets)
    if "H^+" in ions and "OH^-" in ions:
        # Only the registered strong acid/base pair or the free ions themselves.
        if not any("H^+" in a and "OH^-" in b for a, b in (ion_sets, ion_sets[::-1])):
            return ReactionResult("UNSUPPORTED_REACTION", ("이 조합의 전체 반응을 현재 규칙으로 정할 수 없습니다.",))
        if conditions.concentrations or conditions.solid_present is not None:
            return ReactionResult("UNSUPPORTED_CONDITIONS", ("중화 규칙은 순이온 반응 후보만 제공합니다. 농도·남는 양은 !양적 명령에 완성된 반응식과 반응물의 양을 지정해 계산해 주세요.",))
        equation = balance_equation("H^+(aq) + OH^-(aq) -> H2O(l)").text
        spectator = sorted(ions - {"H^+", "OH^-"})
        lines = [equation, "수용액의 수소 이온과 수산화 이온에 대한 중화 반응식입니다."]
        if spectator:
            lines.append("이 규칙에서 구경꾼 이온: " + ", ".join(spectator))
        lines += ["가정: 물, 25 °C, 희석 수용액에서 등록된 강산·강염기의 해리.", "생성량·잔류량·pH는 이 반응식만으로 결정하지 않았습니다."]
        return ReactionResult("REACTION_RULE_APPLIED", tuple(lines), ("classification",))
    candidates = [s for s in SOLIDS.values()
                  if set(s["ions"]).issubset(ions)
                  and all(set(s["ions"]) & part for part in ion_sets)]
    if not candidates:
        return ReactionResult("UNSUPPORTED_REACTION", ("등록된 중화·침전 규칙으로 이 조합의 결과를 정할 수 없습니다. 자료가 없다는 이유로 '반응 없음'이라고 단정하지 않습니다.",))
    if len(candidates) > 1:
        return ReactionResult("COMPETING_CANDIDATES", (
            "경쟁할 수 있는 고체 후보: " + ", ".join(s["formula"] for s in candidates),
            "여러 평형을 함께 풀어야 전체 혼합물의 결과를 정할 수 있습니다.",
        ), ("solubility",))
    solid = candidates[0]
    if not conditions.concentrations:
        return ReactionResult("NEEDS_CONDITIONS", (
            "이온 조합으로 찾은 고체 후보: " + solid["formula"],
            precipitation_equation(solid),
            "실제 포화 여부에는 자유 이온 농도가 필요합니다: " + ", ".join(solid["ions"]),
            "후보 식은 침전이 반드시 생긴다는 뜻이 아닙니다. !침전 명령에서 농도를 지정해 판정할 수 있습니다.",
        ), ("classification", "solubility"))
    return saturation(solid["formula"], conditions)
