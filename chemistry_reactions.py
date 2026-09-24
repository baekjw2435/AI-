"""Deterministic, conditional product discovery, independent of Discord.

Reaction candidates come from ion composition, not a lookup of reactant pairs.
Missing data never means 'no reaction'. Supersaturation is not an observed yield.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from itertools import combinations
import json
import re

from chemistry_engine import (
    DATA_DIR, NUMBER, BalancedEquation, ChemistryError, Formula, balance_equation, check_input,
    decimal_number, fail, format_number, parse_formula, parse_sum,
)


REACTION_DATA = json.loads((DATA_DIR / "aqueous.json").read_text(encoding="utf-8"))
RULE_DATA = json.loads((DATA_DIR / "reaction_rules.json").read_text(encoding="utf-8"))
REACTION_DATA["sources"].update(RULE_DATA["sources"])
SOLIDS = {row["formula"]: row for row in REACTION_DATA["solids"]}
DISSOCIATION = REACTION_DATA["dissociation"]
KNOWN_IONS = {ion for ions in DISSOCIATION.values() for ion in ions}
for _solid in SOLIDS.values():
    KNOWN_IONS.update(_solid["ions"])
ION_RULES = tuple((rule, balance_equation(rule["equation"])) for rule in RULE_DATA["aqueous_rules"])
for _rule, _equation in ION_RULES:
    KNOWN_IONS.update(sp.formula for sp in _equation.reactants + _equation.products if sp.charge)


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
    reaction_type: str = "auto"


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
    reaction_type = "auto"
    for key, value in options.items():
        lower = key.lower()
        if lower in ("유형", "반응유형", "type"):
            canonical = "type"
            kinds = {"자동": "auto", "auto": "auto", "수용액": "aqueous", "aqueous": "aqueous",
                     "완전산화": "oxidation", "완전 산화": "oxidation", "oxidation": "oxidation"}
            reaction_type = kinds.get(value.lower())
            if reaction_type is None:
                fail("UNSUPPORTED_CONDITIONS", "유형은 자동·수용액·완전산화 중 하나로 지정해 주세요.")
        elif lower in ("온도", "t", "temperature"):
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
                fail("UNSUPPORTED_CONDITIONS", "지원하는 조건은 유형·온도·용매·고체 유무·자유 이온 농도입니다. 촉매·압력·pH·시간을 바꾼 계산은 아직 지원하지 않습니다.")
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
    return Conditions(temperature, solvent, concentrations, solid_present, reaction_type)


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
    if conditions.reaction_type not in ("auto", "aqueous"):
        fail("UNSUPPORTED_CONDITIONS", "!침전은 수용액 포화 판정입니다. 완전산화 유형과 함께 사용할 수 없습니다.")
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


@dataclass(frozen=True)
class ProductCandidate:
    rule_id: str
    name: str
    equation: BalancedEquation
    participants: frozenset[str]
    note: str
    source_ids: tuple[str, ...]
    solid: str | None = None
    kind: str = "aqueous"


def _aqueous_pool(species: list[Formula]) -> dict[str, frozenset[str]]:
    """Only dissolve registered species in an explicitly conditional aq model."""
    pool = {}
    for sp in species:
        if sp.phase not in (None, "aq"):
            continue
        if sp.formula in DISSOCIATION:
            pool[sp.label] = frozenset(DISSOCIATION[sp.formula])
        elif sp.formula in KNOWN_IONS:
            pool[sp.label] = frozenset({sp.formula})
    return pool


def discover_candidates(species: list[Formula], reaction_type: str = "auto") -> tuple[ProductCandidate, ...]:
    """Search the whole input pool. Never chain candidates into a claimed yield.

    Matching a rule is distinct from checking its domain, saturation or rate.
    Repeated species and coefficients do not imply amounts in candidate search.
    """
    candidates = []
    if reaction_type in ("auto", "aqueous"):
        pool = _aqueous_pool(species)
        ions = set().union(*pool.values())
        for rule, equation in ION_RULES:
            required = {sp.formula for sp in equation.reactants}
            if required <= ions:
                participants = frozenset(name for name, part in pool.items() if part & required)
                candidates.append(ProductCandidate(rule["id"], rule["name"], equation,
                    participants, rule["note"], tuple(rule["sources"])))
        for solid in SOLIDS.values():
            required = set(solid["ions"])
            if required <= ions:
                participants = frozenset(name for name, part in pool.items() if part & required)
                candidates.append(ProductCandidate("precipitate:" + solid["formula"],
                    solid["name"] + " 침전 후보", balance_equation(precipitation_equation(solid)),
                    participants, "침전 후보입니다. 실제 포화 여부는 자유 이온 농도와 Ksp로 판정합니다.",
                    ("classification", "solubility", "equilibrium"), solid["formula"]))
    if reaction_type in ("auto", "oxidation"):
        oxygen = {sp.label for sp in species if sp.formula == "O2"}
        if oxygen:
            for sp in species:
                atoms = sp.atoms
                # This is a *conditional stoichiometric model*, not a claim that
                # all syntactically valid CHO compositions identify real fuels.
                if (sp.charge or not {"C", "H"} <= atoms.keys()
                        or not atoms.keys() <= {"C", "H", "O"}
                        or "·" in sp.body
                        or 4 * atoms["C"] + atoms["H"] - 2 * atoms.get("O", 0) <= 0):
                    continue
                equation = balance_equation(sp.formula + " + O2 -> CO2 + H2O")
                rule = RULE_DATA["oxidation"]
                candidates.append(ProductCandidate(rule["id"] + ":" + sp.label,
                    sp.formula + " 완전 산화 가정", equation,
                    frozenset({sp.label} | oxygen), rule["note"], tuple(rule["sources"]), kind="oxidation"))
    return tuple(candidates)


def _ionic_vector(equation: BalancedEquation) -> dict[str, int]:
    """Dissociate aq salts and cancel spectators to verify a molecular example."""
    vector = {}
    n = len(equation.reactants)
    for i, (sp, count) in enumerate(zip(equation.reactants + equation.products, equation.coefficients)):
        sign = -1 if i < n else 1
        parts = DISSOCIATION[sp.formula] if sp.phase == "aq" and sp.formula in DISSOCIATION else {sp.label: 1}
        for label, power in parts.items():
            if label in KNOWN_IONS:
                label += "(aq)"
            vector[label] = vector.get(label, 0) + sign * count * power
    return {name: n for name, n in vector.items() if n}


def molecular_examples(candidate: ProductCandidate, species: list[Formula]) -> tuple[str, ...]:
    """Conservative binary molecular forms, verified against the net ionic rule.

    Do not arbitrarily pair counterions across an underdetermined multicomponent
    mixture. These examples describe named input pairs, not the entire mixture.
    """
    if candidate.kind != "aqueous" or any(sp.charge for sp in candidate.equation.products):
        return ()
    eligible = sorted({sp.formula for sp in species
                       if sp.label in candidate.participants and sp.formula in DISSOCIATION})
    required = {sp.formula for sp in candidate.equation.reactants if sp.charge}
    examples = []
    for left, right in combinations(eligible, 2):
        a, b = set(DISSOCIATION[left]), set(DISSOCIATION[right])
        if not (a & required and b & required and required <= a | b):
            continue
        spectators = (a | b) - required
        salts = [name for name, ions in DISSOCIATION.items() if set(ions) == spectators]
        if len(salts) != 1:
            continue
        products = [sp.label for sp in candidate.equation.products] + [salts[0] + "(aq)"]
        reactants = [left + "(aq)", right + "(aq)"]
        if any(sp.formula == "H2O" for sp in candidate.equation.reactants):
            reactants.append("H2O(l)")
        try:
            equation = balance_equation(" + ".join(reactants) + " -> " + " + ".join(products))
        except ChemistryError:
            continue
        actual, expected = _ionic_vector(equation), _ionic_vector(candidate.equation)
        if actual.keys() != expected.keys():
            continue
        anchor = next(iter(expected))
        if actual[anchor] * expected[anchor] <= 0 or any(
                actual[k] * expected[anchor] != expected[k] * actual[anchor] for k in expected):
            continue
        examples.append(equation.text)
        # Full enumeration is unnecessary; the net ionic rule covers all donors.
        if len(examples) == 2:
            break
    return tuple(examples)


def predict_reaction(text: str, conditions: Conditions) -> ReactionResult:
    original = parse_sum(text)
    species = sorted({sp.label: replace(sp, coefficient=1) for sp in original}.values(), key=lambda sp: sp.label)
    if len(species) < 2:
        return ReactionResult("UNSUPPORTED_REACTION", (
            "생성물 탐색에는 서로 다른 물질을 두 개 이상 입력해 주세요(최대 16개). 단일 물질의 분해 반응은 아직 등록되어 있지 않습니다.",))
    candidates = discover_candidates(species, conditions.reaction_type)
    aqueous = [c for c in candidates if c.kind == "aqueous"]
    oxidation = [c for c in candidates if c.kind == "oxidation"]
    pool = _aqueous_pool(species)
    outside = _domain(conditions)
    # A deliberately limited domain must not be silently bypassed by another
    # rule family. Missing aqueous conditions are shown alongside candidates.
    if aqueous and outside and outside.status == "OUT_OF_DOMAIN":
        return outside
    if oxidation and (conditions.temperature_C is not None or conditions.solvent is not None
                      or conditions.concentrations or conditions.solid_present is not None):
        return ReactionResult("UNSUPPORTED_CONDITIONS", (
            "완전 산화 규칙은 생성물을 CO2·H2O로 가정한 총괄식만 계산합니다. 온도·용매·농도·고체 조건에 따른 실제 산화 진행은 판정하지 못합니다.",
            "총괄식 후보만 보려면 해당 조건을 빼고 | 유형=완전산화를, 수용액 규칙만 보려면 | 유형=수용액을 사용해 주세요.",))
    if not candidates:
        wrong_phase = [sp.label for sp in species if sp.formula in DISSOCIATION and sp.phase not in (None, "aq")]
        if wrong_phase:
            return ReactionResult("OUT_OF_DOMAIN", (
                "등록된 해리 규칙은 수용액용입니다. 지정한 상의 반응은 지원하지 않습니다: " + ", ".join(wrong_phase),))
        return ReactionResult("UNSUPPORTED_REACTION", (
            "입력: " + " + ".join(sp.label for sp in species),
            "현재의 산염기·침전·완전 산화 규칙에서 생성물 후보를 찾지 못했습니다. '반응 없음'을 뜻하지 않습니다.",
            "분자 구조, 반응 종류 또는 추가 반응 자료가 필요합니다. !화학자료에서 지원 범위를 확인할 수 있습니다.",))
    precipitates = [c for c in aqueous if c.solid]
    used_concentrations = set().union(*(set(SOLIDS[c.solid]["ions"]) for c in precipitates))
    unexpected = set(conditions.concentrations) - used_concentrations
    if unexpected:
        fail("UNSUPPORTED_CONDITIONS", "이번 포화식에 쓰이지 않는 자유 이온 농도입니다: " + ", ".join(sorted(unexpected)))
    if conditions.solid_present is not None and len(precipitates) != 1:
        fail("UNSUPPORTED_CONDITIONS", "고체 유무는 !침전 고체화학식 명령으로 고체 하나에 지정해 주세요.")
    lines = []
    source_ids = set()
    candidate_statuses = []
    for index, candidate in enumerate(candidates, 1):
        source_ids.update(candidate.source_ids)
        lines += [f"**후보 {index} · {candidate.name}**",
                  "생성물 후보: " + " + ".join(sp.label for sp in candidate.equation.products),
                  candidate.equation.text]
        examples = molecular_examples(candidate, species)
        for example in examples:
            lines.append("입력 물질 쌍의 분자식 예: " + example)
        lines.append(candidate.note)
        state = "CONDITIONAL_PRODUCTS"
        if candidate.kind == "aqueous":
            lines.append("적용 가정: 물, 25 °C, 희석 수용액. 상을 생략한 등록 물질은 이 가정에서 해리시킵니다.")
            if outside:
                state = "NEEDS_CONDITIONS"
                lines.extend(outside.lines)
            elif candidate.solid:
                required = set(SOLIDS[candidate.solid]["ions"])
                subset = {ion: value for ion, value in conditions.concentrations.items() if ion in required}
                result = saturation(candidate.solid, replace(conditions, concentrations=subset))
                state = result.status
                if state == "NEEDS_CONDITIONS":
                    lines.extend(result.lines[1:])
                else:
                    # Name and equation are already present above.
                    lines.extend(result.lines[2:])
            elif candidate.rule_id == "neutralization":
                state = "REACTION_RULE_APPLIED"
        else:
            lines.append("이 후보는 완전 산화를 가정하며, 물질을 섞기만 하면 이 반응이 일어난다는 뜻은 아닙니다.")
        candidate_statuses.append(state)
        lines.append("")
    participants = set().union(*(c.participants for c in candidates))
    water = [sp.label for sp in species if sp.formula == "H2O"]
    covered_pool = pool if aqueous else {}
    unhandled = [sp.label for sp in species if sp.label not in participants and sp.formula != "H2O" and sp.label not in covered_pool]
    if water:
        lines.append("입력한 물(" + ", ".join(water) + ")은 별도로 표시했습니다. 위 식은 각 반응의 순변화이며, 이미 있던 물을 새 생성량에 더하지 않았습니다.")
    unused = [sp.label for sp in species if sp.label not in participants and sp.formula != "H2O"]
    if unused:
        lines.append("표시된 후보에서 소비를 계산하지 않은 입력: " + ", ".join(unused))
    if unhandled:
        lines.append("전체 반응에 대해 미판정인 입력: " + ", ".join(unhandled) + ". 다른 물질과의 반응이나 영향도 배제하지 않았습니다.")
    if aqueous:
        all_ions = set().union(*pool.values())
        active = {sp.formula for c in aqueous for sp in c.equation.reactants if sp.charge}
        remaining = sorted(all_ions - active)
        if remaining:
            lines.append("표시된 순이온식에서 소거된 이온: " + ", ".join(remaining))
    if len(candidates) > 1:
        lines.append("후보들은 경쟁하거나 단계별로 이어질 수 있습니다. 전부 동시에 완결된다고 가정해 합산하지 않았습니다. 최종 생성물·비율에는 투입량과 결합된 평형/반응 경로가 필요합니다.")
    if any(sp.coefficient != 1 for sp in original):
        lines.append("입력 앞 계수는 후보 검색에서 실제 투입량으로 사용하지 않았습니다. 후보 반응식의 최소 정수 계수는 새로 계산했습니다.")
    if len(original) != len(species):
        lines.append("중복 입력한 화학종은 후보 탐색에서 한 번만 사용했습니다.")
    lines.append("지원 규칙에서 찾은 후보이며 모든 반응 경로를 망라하지 않습니다. 생성량은 !양적에 선택한 반응식과 실제 양을 입력해 계산할 수 있습니다.")
    if unhandled:
        status = "PARTIAL_CANDIDATES"
    elif len(candidates) > 1:
        status = "COMPETING_CANDIDATES"
    else:
        status = candidate_statuses[0]
    return ReactionResult(status, tuple(lines), tuple(sorted(source_ids)))
