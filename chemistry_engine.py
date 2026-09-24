"""Deterministic formula, charge, stoichiometry and amount calculations.

No network calls, LLMs, eval, or third-party numerical dependencies.
Balancing an equation does not establish that the reaction occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from functools import reduce
from math import gcd, lcm
from pathlib import Path
import json
import re


DATA_DIR = Path(__file__).resolve().parent / "chemistry_data"
ELEMENT_DATA = json.loads((DATA_DIR / "elements.json").read_text(encoding="utf-8"))
ELEMENTS = ELEMENT_DATA["elements"]
MAX_INPUT = 1200
MAX_FORMULA = 400
MAX_SPECIES = 16
MAX_DEPTH = 12
MAX_MULTIPLIER = 1_000_000
MAX_ATOMS = 1_000_000_000
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
ARROW = re.compile(r"<=>|<->|->|=>|⇌|↔|→|⟶|=")


class ChemistryError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def fail(code: str, message: str):
    raise ChemistryError(code, message)


def check_input(text: str, maximum: int = MAX_INPUT) -> str:
    if not isinstance(text, str) or not text.strip():
        fail("INVALID_INPUT", "계산할 화학식이나 반응식을 입력해 주세요.")
    if len(text) > maximum:
        fail("INPUT_LIMIT", f"입력은 {maximum}자까지 계산할 수 있습니다.")
    return text.strip()


def positive_integer(text: str) -> int:
    if len(text) > 7:
        fail("INPUT_LIMIT", "계수와 첨자가 너무 큽니다.")
    value = int(text)
    if value < 1:
        fail("INVALID_INPUT", "계수와 첨자는 1 이상의 정수여야 합니다.")
    if value > MAX_MULTIPLIER:
        fail("INPUT_LIMIT", "계수와 첨자는 1,000,000 이하여야 합니다.")
    return value


def _merge(target: dict[str, int], atoms: dict[str, int], multiplier: int = 1):
    for symbol, count in atoms.items():
        target[symbol] = target.get(symbol, 0) + count * multiplier
    if sum(target.values()) > MAX_ATOMS:
        fail("INPUT_LIMIT", "한 번에 계산할 원자 수의 한도를 넘었습니다.")


class _FormulaParser:
    PAIRS = {"(": ")", "[": "]", "{": "}"}

    def __init__(self, body: str):
        self.body = body
        self.index = 0

    def number(self) -> int:
        start = self.index
        while self.index < len(self.body) and self.body[self.index] in "0123456789":
            self.index += 1
        return positive_integer(self.body[start:self.index]) if self.index > start else 1

    def group(self, closing: str | None = None, depth: int = 0) -> dict[str, int]:
        if depth > MAX_DEPTH:
            fail("INPUT_LIMIT", "괄호 중첩은 12단계까지 지원합니다.")
        atoms: dict[str, int] = {}
        while self.index < len(self.body):
            ch = self.body[self.index]
            if ch in ")]}":
                if ch != closing:
                    fail("INVALID_INPUT", "괄호의 종류나 짝이 맞지 않습니다.")
                self.index += 1
                if not atoms:
                    fail("INVALID_INPUT", "빈 괄호는 사용할 수 없습니다.")
                return atoms
            if ch in self.PAIRS:
                self.index += 1
                inner = self.group(self.PAIRS[ch], depth + 1)
                _merge(atoms, inner, self.number())
            elif "A" <= ch <= "Z":
                self.index += 1
                symbol = ch
                if self.index < len(self.body) and "a" <= self.body[self.index] <= "z":
                    symbol += self.body[self.index]
                    self.index += 1
                if symbol not in ELEMENTS:
                    fail("UNKNOWN_ELEMENT", f"등록된 원소 기호가 아닙니다: {symbol}. 대소문자를 확인해 주세요.")
                _merge(atoms, {symbol: self.number()})
            else:
                fail("INVALID_INPUT", "원소 기호·정수 첨자·괄호만 입력해 주세요. 전하는 Ca^2+처럼 씁니다.")
        if closing is not None:
            fail("INVALID_INPUT", "닫히지 않은 괄호가 있습니다.")
        if not atoms:
            fail("INVALID_INPUT", "원소 기호가 필요합니다.")
        return atoms


@dataclass(frozen=True)
class Formula:
    body: str
    atoms: dict[str, int]
    coefficient: int = 1
    charge: int = 0
    phase: str | None = None

    @property
    def formula(self) -> str:
        if not self.charge:
            return self.body
        magnitude = str(abs(self.charge)) if abs(self.charge) != 1 else ""
        return self.body + "^" + magnitude + ("+" if self.charge > 0 else "-")

    @property
    def label(self) -> str:
        return self.formula + (f"({self.phase})" if self.phase else "")

    @property
    def total_atoms(self) -> dict[str, int]:
        return {key: value * self.coefficient for key, value in self.atoms.items()}

    @property
    def total_charge(self) -> int:
        return self.coefficient * self.charge

    @property
    def molar_mass(self) -> Decimal | None:
        if not self.atoms or any(ELEMENTS[e]["weight"] is None for e in self.atoms):
            return None
        return sum((Decimal(ELEMENTS[e]["weight"]) * n for e, n in self.atoms.items()), Decimal(0))


def parse_formula(text: str) -> Formula:
    text = check_input(text, MAX_FORMULA)
    if re.search(r"\s", text):
        fail("INVALID_INPUT", "한 화학식 내부에는 공백을 넣지 마세요.")
    text = text.translate(SUBSCRIPTS).replace("−", "-")
    phase = None
    phase_match = re.search(r"\((aq|s|l|g)\)$", text)
    if phase_match:
        phase = phase_match[1]
        text = text[:phase_match.start()]
    # Preserve the difference between subscripts, superscript charges and isotopes.
    unicode_charge = re.search(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻]$", text)
    if unicode_charge:
        text = text[:unicode_charge.start()] + "^" + unicode_charge[0].translate(SUPERSCRIPTS)
    if re.search(r"\[\d+[A-Z]|[⁰¹²³⁴⁵⁶⁷⁸⁹]|[)\]}]n(?:$|\^)", text):
        fail("UNSUPPORTED_NOTATION", "동위원소 표기나 변수 반복 단위는 아직 지원하지 않습니다.")
    if "." in text:
        fail("UNSUPPORTED_NOTATION", "결정수는 MgSO4·7H2O처럼 가운데점(·)으로 구분해 주세요. 비정수 조성은 미지원입니다.")
    coefficient = 1
    start = re.match(r"\d+", text)
    if start:
        coefficient = positive_integer(start[0])
        text = text[start.end():]
    charge = 0
    explicit_charge = re.search(r"\^(\d*)([+-])$", text)
    if explicit_charge:
        magnitude = positive_integer(explicit_charge[1]) if explicit_charge[1] else 1
        charge = magnitude if explicit_charge[2] == "+" else -magnitude
        text = text[:explicit_charge.start()]
    elif text.endswith(("+", "-")):
        body = text[:-1]
        if re.fullmatch(r"[A-Z][a-z]?\d+", body):
            fail("AMBIGUOUS_CHARGE", "원자 수와 전하가 모호합니다. Fe^3+ 또는 O2^-처럼 ^로 전하를 구분해 주세요.")
        charge = 1 if text[-1] == "+" else -1
        text = body
    if text == "e" and charge == -1:
        if phase:
            fail("INVALID_INPUT", "전자에는 물질 상태를 지정하지 마세요.")
        return Formula("e", {}, coefficient, -1)
    atoms: dict[str, int] = {}
    segments = text.split("·")
    for index, segment in enumerate(segments):
        factor = 1
        if index:
            match = re.match(r"\d+", segment)
            if match:
                factor = positive_integer(match[0])
                segment = segment[match.end():]
        _merge(atoms, _FormulaParser(segment).group(), factor)
    if sum(atoms.values()) * coefficient > MAX_ATOMS:
        fail("INPUT_LIMIT", "계수 적용 후 원자 수가 계산 한도를 넘었습니다.")
    return Formula(text, atoms, coefficient, charge, phase)


def split_side(text: str) -> list[str]:
    """Split a formula sum without splitting terminal ionic charge signs."""
    text = check_input(text)
    terms: list[str] = []
    current: list[str] = []
    depth = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "+" and depth == 0:
            prefix = "".join(current).rstrip()
            following = text[index + 1:].lstrip()
            is_charge = bool(re.search(r"\^\d*$", prefix)) or not following or following.startswith(("+", "(aq)", "(s)", "(g)", "(l)"))
            if not is_charge:
                if not prefix:
                    fail("INVALID_INPUT", "+ 앞뒤에 화학식이 필요합니다.")
                terms.append(prefix)
                current = []
                continue
        current.append(ch)
    last = "".join(current).strip()
    if not last:
        fail("INVALID_INPUT", "+ 뒤에 화학식이 필요합니다.")
    terms.append(last)
    if len(terms) > MAX_SPECIES:
        fail("INPUT_LIMIT", "한 번에 16개 물질까지 계산할 수 있습니다.")
    return terms


def parse_sum(text: str) -> list[Formula]:
    return [parse_formula(term) for term in split_side(text)]


def sum_composition(species: list[Formula]) -> tuple[dict[str, int], int]:
    atoms: dict[str, int] = {}
    for item in species:
        _merge(atoms, item.atoms, item.coefficient)
    return atoms, sum(item.total_charge for item in species)


@dataclass(frozen=True)
class BalancedEquation:
    reactants: tuple[Formula, ...]
    products: tuple[Formula, ...]
    coefficients: tuple[int, ...]
    reversible: bool = False

    @property
    def text(self) -> str:
        terms = [(str(c) if c != 1 else "") + s.label
                 for c, s in zip(self.coefficients, self.reactants + self.products)]
        n = len(self.reactants)
        return " + ".join(terms[:n]) + (" ⇌ " if self.reversible else " → ") + " + ".join(terms[n:])


def balance_equation(text: str) -> BalancedEquation:
    text = check_input(text)
    parts = ARROW.split(text)
    if len(parts) != 2:
        fail("INVALID_INPUT", "반응물과 생성물을 모두 써 주세요. 예: Mg(OH)2 -> Mg^2+ + OH^-")
    left, right = parse_sum(parts[0]), parse_sum(parts[1])
    all_species = left + right
    if len(all_species) > MAX_SPECIES:
        fail("INPUT_LIMIT", "반응식 양쪽을 합쳐 16개 물질까지 계산합니다.")
    elements = sorted({element for sp in all_species for element in sp.atoms})
    signs = [1] * len(left) + [-1] * len(right)
    original = [[sign * sp.atoms.get(element, 0) for sp, sign in zip(all_species, signs)] for element in elements]
    original.append([sign * sp.charge for sp, sign in zip(all_species, signs)])
    matrix = [[Fraction(value) for value in row] for row in original]
    row = 0
    pivots = []
    for col in range(len(all_species)):
        pivot = next((i for i in range(row, len(matrix)) if matrix[i][col]), None)
        if pivot is None:
            continue
        matrix[row], matrix[pivot] = matrix[pivot], matrix[row]
        divisor = matrix[row][col]
        matrix[row] = [x / divisor for x in matrix[row]]
        for i in range(len(matrix)):
            if i != row and matrix[i][col]:
                factor = matrix[i][col]
                matrix[i] = [x - factor * y for x, y in zip(matrix[i], matrix[row])]
        pivots.append(col)
        row += 1
        if row == len(matrix):
            break
    free = [i for i in range(len(all_species)) if i not in pivots]
    if not free:
        fail("BALANCE_IMPOSSIBLE_AS_WRITTEN", "현재 양쪽 물질로는 원자 수와 전하를 모두 맞출 수 없습니다.")
    if len(free) != 1:
        fail("BALANCE_NEEDS_CONSTRAINTS", "원소·전하 보존만으로 계수를 하나로 정할 수 없습니다. 독립된 반응을 나눠 입력해 주세요.")
    solution = [Fraction(0)] * len(all_species)
    solution[free[0]] = Fraction(1)
    for i, pivot in enumerate(pivots):
        solution[pivot] = -matrix[i][free[0]]
    scale = reduce(lcm, (x.denominator for x in solution), 1)
    integers = [int(x * scale) for x in solution]
    if any(x <= 0 for x in integers):
        fail("BALANCE_IMPOSSIBLE_AS_WRITTEN", "지정한 물질과 방향을 유지하는 양의 계수 해가 없습니다.")
    common = reduce(gcd, integers)
    coefficients = tuple(x // common for x in integers)
    if max(coefficients) > MAX_ATOMS:
        fail("INPUT_LIMIT", "계수가 너무 커 표시 한도를 넘었습니다.")
    if any(sum(x * c for x, c in zip(line, coefficients)) for line in original):
        raise ArithmeticError("Conservation verification failed")
    return BalancedEquation(tuple(left), tuple(right), coefficients, bool(re.search(r"<=>|<->|⇌|↔", text)))


NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?"


def decimal_number(text: str, maximum: Decimal = Decimal("1e12")) -> Decimal:
    if not isinstance(text, str) or len(text) > 40 or not re.fullmatch(NUMBER, text):
        fail("INVALID_INPUT", "0 이상의 유한한 숫자를 입력해 주세요.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        fail("INVALID_INPUT", "숫자를 해석하지 못했습니다.")
    if not value.is_finite() or value < 0 or value > maximum or (value != 0 and value < Decimal("1e-100")):
        fail("INPUT_LIMIT", "숫자가 지원 범위를 벗어났습니다.")
    return value


def parse_amount(text: str, species: Formula) -> Fraction:
    match = re.fullmatch(rf"\s*({NUMBER})\s*(mmol|mol|mg|g)\s*", text)
    if not match:
        fail("INVALID_INPUT", "양에는 mol, mmol, g, mg 단위를 붙여 주세요.")
    value = Fraction(decimal_number(match[1]))
    unit = match[2]
    if unit.startswith("m") and unit in ("mg", "mmol"):
        value /= 1000
    if unit in ("g", "mg"):
        mass = species.molar_mass
        if mass is None:
            fail("MISSING_REFERENCE_DATA", "이 물질의 질량을 몰수로 바꿀 원자량 정보가 없습니다.")
        value /= Fraction(mass)
    return value


def calculate_amounts(equation: BalancedEquation, inputs: dict[str, str]) -> dict:
    """Theoretical single-forward-reaction extent, never an experimental yield."""
    keys = [s.label for s in equation.reactants]
    if len(set(keys)) != len(keys):
        fail("INVALID_INPUT", "같은 반응물을 중복하지 말고 한 항으로 입력해 주세요.")
    if set(inputs) != set(keys):
        fail("NEEDS_AMOUNTS", "모든 반응물의 양을 입력해 주세요: " + ", ".join(keys))
    amounts = [parse_amount(inputs[sp.label], sp) for sp in equation.reactants]
    ratios = [amount / c for amount, c in zip(amounts, equation.coefficients)]
    extent = min(ratios)
    return {
        "extent": extent,
        "limiting": [sp.label for sp, ratio in zip(equation.reactants, ratios) if ratio == extent],
        "remaining": [(sp.label, n - extent * c) for sp, n, c in zip(equation.reactants, amounts, equation.coefficients)],
        "products": [(sp, extent * c) for sp, c in zip(equation.products, equation.coefficients[len(equation.reactants):])],
    }


def format_number(value: Fraction | Decimal | float | int, digits: int = 6) -> str:
    with localcontext() as ctx:
        ctx.prec = 32
        if isinstance(value, Fraction):
            value = Decimal(value.numerator) / Decimal(value.denominator)
        elif not isinstance(value, Decimal):
            value = Decimal(str(value))
        if value == 0:
            return "0"
        return format(value.normalize(), f".{digits}g")
