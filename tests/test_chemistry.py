import ast
import asyncio
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import chemistry_engine as engine
import chemistry_reactions as reactions
import chemistry_bot as bot


class FormulaTests(unittest.TestCase):
    def test_formula_reference_cases(self):
        cases = {
            "H2O": {"H": 2, "O": 1},
            "2H2O": {"H": 4, "O": 2},
            "Ca(OH)2": {"Ca": 1, "O": 2, "H": 2},
            "Al2(SO4)3": {"Al": 2, "S": 3, "O": 12},
            "MgSO4·7H2O": {"Mg": 1, "S": 1, "O": 11, "H": 14},
            "3MgSO4·7H2O": {"Mg": 3, "S": 3, "O": 33, "H": 42},
            "((H2O)2)3": {"H": 12, "O": 6},
            "K4[Fe(CN)6]": {"K": 4, "Fe": 1, "C": 6, "N": 6},
            "H₂O": {"H": 2, "O": 1},
            "C6H12O6": {"C": 6, "H": 12, "O": 6},
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(engine.parse_formula(expression).total_atoms, expected)

    def test_all_element_symbols(self):
        self.assertEqual(len(engine.ELEMENTS), 118)
        self.assertEqual(sorted(x["atomic_number"] for x in engine.ELEMENTS.values()), list(range(1, 119)))
        for symbol in engine.ELEMENTS:
            with self.subTest(symbol=symbol):
                self.assertEqual(engine.parse_formula(symbol).atoms, {symbol: 1})

    def test_charges_and_states(self):
        for expression, atoms, charge, phase in (
            ("Ca^2+(aq)", {"Ca": 1}, 2, "aq"),
            ("SO₄²⁻", {"S": 1, "O": 4}, -2, None),
            ("NH4+", {"N": 1, "H": 4}, 1, None),
            ("2SO4^2-", {"S": 1, "O": 4}, -4, None),
            ("2e^-", {}, -2, None),
            ("H2O(l)", {"H": 2, "O": 1}, 0, "l"),
        ):
            with self.subTest(expression=expression):
                actual = engine.parse_formula(expression)
                self.assertEqual((actual.atoms, actual.total_charge, actual.phase), (atoms, charge, phase))

    def test_invalid_and_unsupported_notation(self):
        cases = {
            "(H2O": "INVALID_INPUT", "Ca(OH]2": "INVALID_INPUT",
            "H0": "INVALID_INPUT", "()2": "INVALID_INPUT", "Xx2": "UNKNOWN_ELEMENT",
            "Fe3+": "AMBIGUOUS_CHARGE", "[13C]O2": "UNSUPPORTED_NOTATION",
            "(C2H4)n": "UNSUPPORTED_NOTATION", "MgSO4.7H2O": "UNSUPPORTED_NOTATION",
            "h2o": "INVALID_INPUT", "H^0+": "INVALID_INPUT", "2": "INVALID_INPUT",
            "H2O(s)(l)": "INVALID_INPUT", "H 2O": "INVALID_INPUT",
        }
        for expression, code in cases.items():
            with self.subTest(expression=expression), self.assertRaises(engine.ChemistryError) as caught:
                engine.parse_formula(expression)
            self.assertEqual(caught.exception.code, code)

    def test_input_resource_limits(self):
        for expression in ("H" * 401, "(" * 14 + "H2O" + ")" * 14, "H99999999", "1000000(H1000000)1000000"):
            with self.subTest(expression=expression[:40]), self.assertRaises(engine.ChemistryError) as caught:
                engine.parse_formula(expression)
            self.assertEqual(caught.exception.code, "INPUT_LIMIT")

    def test_molar_mass_and_coefficients(self):
        self.assertEqual(engine.parse_formula("H2O").molar_mass, Decimal("18.0150"))
        self.assertEqual(engine.parse_formula("9H2O").molar_mass, Decimal("18.0150"))
        self.assertEqual(engine.parse_formula("MgSO4·7H2O").molar_mass, Decimal("246.4660"))
        self.assertEqual(engine.ELEMENTS["Zr"]["weight"], "91.222")
        self.assertIsNone(engine.parse_formula("Og").molar_mass)
        self.assertIsNone(engine.parse_formula("e^-").molar_mass)

    def test_sums_and_positive_charge_separators(self):
        for text in ("Na^+ + Cl^-", "Na^++Cl^-", "Na+ + Cl-", "Na+(aq) + Cl^-(aq)"):
            with self.subTest(text=text):
                atoms, charge = engine.sum_composition(engine.parse_sum(text))
                self.assertEqual(atoms, {"Na": 1, "Cl": 1})
                self.assertEqual(charge, 0)
        atoms, charge = engine.sum_composition(engine.parse_sum("2H2O + CO2"))
        self.assertEqual(atoms, {"H": 4, "O": 4, "C": 1})
        self.assertEqual(charge, 0)


class BalanceTests(unittest.TestCase):
    def test_reference_coefficients_and_charge(self):
        cases = {
            "Mg(OH)2 -> Mg^2+ + OH^-": (1, 1, 2),
            "Ca3(PO4)2 -> Ca^2+ + PO4^3-": (1, 3, 2),
            "Fe^3+ + e^- -> Fe^2+": (1, 1, 1),
            "HCl + NaOH -> NaCl + H2O": (1, 1, 1, 1),
            "Al2(SO4)3 + Ca(OH)2 -> Al(OH)3 + CaSO4": (1, 3, 2, 3),
            "H2O -> H2O": (1, 1),
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                balanced = engine.balance_equation(expression)
                self.assertEqual(balanced.coefficients, expected)
                # Validate again via the independently exposed sum interface.
                sides = balanced.text.replace("→", "->").split("->")
                self.assertEqual(engine.sum_composition(engine.parse_sum(sides[0])), engine.sum_composition(engine.parse_sum(sides[1])))

    def test_existing_coefficients_are_recomputed(self):
        result = engine.balance_equation("8Mg(OH)2 -> 2Mg^2+ + 3OH^-")
        self.assertEqual(result.coefficients, (1, 1, 2))

    def test_reversible_arrow_is_preserved(self):
        self.assertIn("⇌", engine.balance_equation("Mg(OH)2 <=> Mg^2+ + OH^-").text)

    def test_atom_or_charge_impossible(self):
        for expression in ("H2O -> CO2", "Na^+ -> Na", "H2O -> H2O + O2"):
            with self.subTest(expression=expression), self.assertRaises(engine.ChemistryError) as caught:
                engine.balance_equation(expression)
            self.assertEqual(caught.exception.code, "BALANCE_IMPOSSIBLE_AS_WRITTEN")

    def test_more_than_one_independent_reaction(self):
        with self.assertRaises(engine.ChemistryError) as caught:
            engine.balance_equation("NaCl + KBr -> Na^+ + Cl^- + K^+ + Br^-")
        self.assertEqual(caught.exception.code, "BALANCE_NEEDS_CONSTRAINTS")

    def test_missing_products_or_multiple_arrows(self):
        for expression in ("H2O + CO2", "H2O ->", "H2O -> H2O -> H2O"):
            with self.subTest(expression=expression), self.assertRaises(engine.ChemistryError):
                engine.balance_equation(expression)


class AmountTests(unittest.TestCase):
    def setUp(self):
        self.equation = engine.balance_equation("HCl + NaOH -> NaCl + H2O")

    def test_limiting_reactant_and_remainder(self):
        result = engine.calculate_amounts(self.equation, {"HCl": "1mol", "NaOH": "2000mmol"})
        self.assertEqual(result["extent"], Fraction(1))
        self.assertEqual(result["limiting"], ["HCl"])
        self.assertEqual(dict(result["remaining"]), {"HCl": 0, "NaOH": 1})
        self.assertTrue(all(n == 1 for sp, n in result["products"]))

    def test_grams_and_milligrams(self):
        result = engine.calculate_amounts(self.equation, {"HCl": "36.458g", "NaOH": "39997mg"})
        self.assertEqual(result["extent"], Fraction(1))
        self.assertEqual(result["limiting"], ["HCl", "NaOH"])

    def test_zero_amount(self):
        result = engine.calculate_amounts(self.equation, {"HCl": "0mol", "NaOH": "1mol"})
        self.assertEqual(result["extent"], 0)

    def test_missing_and_extra_amounts(self):
        for values in ({"HCl": "1mol"}, {"HCl": "1mol", "NaOH": "1mol", "H2O": "1mol"}):
            with self.subTest(values=values), self.assertRaises(engine.ChemistryError):
                engine.calculate_amounts(self.equation, values)

    def test_bad_units_and_nonfinite_amounts(self):
        for value in ("1", "1L", "-1mol", "NaNmol", "Infinitymol", "1e999mol"):
            with self.subTest(value=value), self.assertRaises(engine.ChemistryError):
                engine.calculate_amounts(self.equation, {"HCl": value, "NaOH": "1mol"})


class ReactionTests(unittest.TestCase):
    def conditions(self, **more):
        return reactions.parse_conditions({"온도": "25", "용매": "물", **more})

    def test_data_stoichiometry(self):
        for name, ions in reactions.DISSOCIATION.items():
            with self.subTest(compound=name):
                expanded = [engine.parse_formula(f"{count}{ion}") for ion, count in ions.items()]
                atoms, charge = engine.sum_composition(expanded)
                self.assertEqual(atoms, engine.parse_formula(name).atoms)
                self.assertEqual(charge, 0)
        for solid in reactions.SOLIDS.values():
            with self.subTest(solid=solid["formula"]):
                self.assertGreater(Decimal(solid["ksp"]), 0)
                equation = engine.balance_equation(reactions.precipitation_equation(solid))
                self.assertEqual(equation.coefficients[-1], 1)
                self.assertIn(solid["source_id"], reactions.REACTION_DATA["sources"])

    def test_neutralization_both_orders(self):
        for expression in ("HCl + NaOH", "KOH + HCl", "H^+ + OH^-", "OH^- + H^+"):
            with self.subTest(expression=expression):
                result = reactions.predict_reaction(expression, self.conditions())
                self.assertEqual(result.status, "REACTION_RULE_APPLIED")
                self.assertIn("H^+(aq) + OH^-(aq) → H2O(l)", "\n".join(result.lines))

    def test_candidate_uses_ions_not_fixed_pair(self):
        for expression in ("CaCl2 + Na2CO3", "K2CO3 + CaCl2", "Ca^2+ + CO3^2-"):
            with self.subTest(expression=expression):
                result = reactions.predict_reaction(expression, self.conditions())
                self.assertEqual(result.status, "NEEDS_CONDITIONS")
                self.assertIn("CaCO3", "\n".join(result.lines))

    def test_saturation_directions(self):
        cases = [
            ({"Ca^2+": "0.001M", "CO3^2-": "0.001M"}, "SUPERSATURATED"),
            ({"Ca^2+": "1e-6M", "CO3^2-": "1e-6M"}, "UNDERSATURATED"),
            ({"Ca^2+": "0.001M", "CO3^2-": "8.7e-6M"}, "AT_SATURATION"),
            ({"Ca^2+": "0M", "CO3^2-": "0.001M"}, "UNDERSATURATED"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                result = reactions.saturation("CaCO3", self.conditions(**values))
                self.assertEqual(result.status, expected)

    def test_ion_exponents_are_used(self):
        result = reactions.saturation("Mg(OH)2", self.conditions(**{"Mg^2+": "0.001M", "OH^-": "0.00001M"}))
        self.assertEqual(result.status, "UNDERSATURATED")
        self.assertIn("1e-13", "\n".join(result.lines))

    def test_predict_with_free_concentrations(self):
        result = reactions.predict_reaction("CaCl2 + Na2CO3", self.conditions(**{"Ca^2+": "0.001M", "CO3^2-": "0.001M"}))
        self.assertEqual(result.status, "SUPERSATURATED")

    def test_dissolution_requires_present_solid(self):
        values = {"Ca^2+": "1e-6M", "CO3^2-": "1e-6M"}
        yes = reactions.saturation("CaCO3", self.conditions(**values, 고체="있음"))
        no = reactions.saturation("CaCO3", self.conditions(**values, 고체="없음"))
        self.assertIn("용해 방향", "\n".join(yes.lines))
        self.assertNotIn("용해 방향", "\n".join(no.lines))

    def test_missing_conditions_are_not_defaulted(self):
        result = reactions.predict_reaction("HCl + NaOH", reactions.parse_conditions({}))
        self.assertEqual(result.status, "NEEDS_CONDITIONS")
        result = reactions.saturation("CaCO3", self.conditions())
        self.assertEqual(result.status, "NEEDS_CONDITIONS")

    def test_outside_domain(self):
        for options in ({"온도": "50", "용매": "물"}, {"온도": "25", "용매": "다른용매"}, {"온도": "25", "용매": "물", "Ca^2+": "1M"}):
            with self.subTest(options=options):
                result = reactions.saturation("CaCO3", reactions.parse_conditions(options))
                self.assertEqual(result.status, "OUT_OF_DOMAIN")
        self.assertEqual(reactions.predict_reaction("HCl(g) + NaOH(s)", self.conditions()).status, "OUT_OF_DOMAIN")

    def test_unknown_reaction_does_not_claim_no_reaction(self):
        for text in ("C6H12O6 + H2O", "NaCl + KCl", "Xe + H2O"):
            with self.subTest(text=text):
                self.assertEqual(reactions.predict_reaction(text, self.conditions()).status, "UNSUPPORTED_REACTION")

    def test_unused_conditions_are_not_ignored(self):
        for options in ({"촉매": "있음"}, {"pH": "7"}, {"시간": "30"}, {"온도": "25", "T": "298.15K"}, {"온도": "NaN"}, {"Ca^2+": "-1M"}):
            with self.subTest(options=options), self.assertRaises(engine.ChemistryError):
                reactions.parse_conditions(options)
        with self.assertRaises(engine.ChemistryError):
            reactions.saturation("CaCO3", self.conditions(**{"Na^+": "0.001M"}))

    def test_kelvin_conversion(self):
        conditions = reactions.parse_conditions({"온도": "298.15K", "용매": "물"})
        self.assertEqual(conditions.temperature_C, Decimal("25"))

    def test_duplicate_options(self):
        for text in ("H2O | 온도=25 | 온도=30", "H2O | 용매", "H2O | 온도="):
            with self.subTest(text=text), self.assertRaises(engine.ChemistryError):
                reactions.split_options(text)


class CommandTests(unittest.TestCase):
    def test_help_and_auto_selection(self):
        self.assertIn("!원자", bot.evaluate("!화학").text)
        self.assertEqual(bot.evaluate("!화학 H2O").status, "COUNTED")
        self.assertEqual(bot.evaluate("!화학 원자 H2O").status, "COUNTED")
        self.assertEqual(bot.evaluate("!화학 Mg(OH)2 -> Mg^2+ + OH^-").status, "BALANCED_ONLY")
        self.assertEqual(bot.evaluate("!화학 CaCl2+Na2CO3").status, "NEEDS_CONDITIONS")

    def test_all_documented_commands(self):
        for text in (
            "!원자 2H2O + CO2", "!질량 MgSO4·7H2O",
            "!계수 Mg(OH)2 -> Mg^2+ + OH^-",
            "!양적 Mg(OH)2 -> Mg^2+ + OH^- | Mg(OH)2=1mol",
            "!반응 CaCl2 + Na2CO3 | 용매=물 | 온도=25",
            "!침전 CaCO3 | 용매=물 | 온도=25 | Ca^2+=0.001M | CO3^2-=0.001M",
            "!화학자료",
        ):
            with self.subTest(text=text):
                result = bot.evaluate(text)
                self.assertIsNotNone(result)
                self.assertNotEqual(result.status, "INVALID_INPUT")
                for embed in bot.build_embeds(result):
                    self.assertLessEqual(len(embed.description), 4096)
                    self.assertLessEqual(len(embed), 6000)

    def test_errors_are_user_facing(self):
        self.assertEqual(bot.evaluate("!원자 Xx2").status, "UNKNOWN_ELEMENT")
        self.assertEqual(bot.evaluate("!원자 " + "H" * 2000).status, "INPUT_LIMIT")
        self.assertEqual(bot.evaluate("!원자 H2O | 온도=25").status, "UNSUPPORTED_CONDITIONS")

    def test_unknown_chat_is_ignored(self):
        for text in ("안녕", "!체스", "!화학임", ""):
            self.assertIsNone(bot.evaluate(text))

    def test_embed_long_text_has_no_loss(self):
        reply = bot.Reply("long", "a" * 9000)
        embeds = bot.build_embeds(reply)
        self.assertEqual("".join(e.description.replace("\n", "") for e in embeds), reply.text)
        self.assertTrue(all(len(e) < 6000 for e in embeds))

    def test_results_are_reproducible(self):
        command = "!침전 CaCO3 | 온도=25 | 용매=물 | Ca^2+=0.001 | CO3^2-=0.001"
        self.assertEqual(bot.evaluate(command), bot.evaluate(command))


class DiscordRoutingTests(unittest.IsolatedAsyncioTestCase):
    CHANNEL = 1552593568357548032

    def setUp(self):
        bot._LAST_USE.clear()
        bot._IN_FLIGHT.clear()

    def message(self, content="!원자 H2O", channel=None, guild=1, is_bot=False):
        return SimpleNamespace(content=content, author=SimpleNamespace(bot=is_bot, id=10),
                               guild=SimpleNamespace(id=guild) if guild is not None else None,
                               channel=SimpleNamespace(id=channel or self.CHANNEL, send=AsyncMock()))

    async def test_adapter_sends_embed_with_no_mentions(self):
        msg = self.message()
        self.assertTrue(await bot.handle_message(msg, self.CHANNEL))
        msg.channel.send.assert_awaited_once()
        kwargs = msg.channel.send.await_args.kwargs
        self.assertIn("H 2개", kwargs["embed"].description)
        self.assertFalse(kwargs["allowed_mentions"].everyone)
        self.assertEqual(bot._IN_FLIGHT, set())

    async def test_adapter_rejects_other_channels_bots_and_dms(self):
        for msg in (self.message(channel=2), self.message(is_bot=True), self.message(guild=None), self.message(content="!체스")):
            self.assertFalse(await bot.handle_message(msg, self.CHANNEL))
            msg.channel.send.assert_not_awaited()

    async def test_cooldown(self):
        msg = self.message()
        await bot.handle_message(msg, self.CHANNEL)
        await bot.handle_message(msg, self.CHANNEL)
        msg.channel.send.assert_awaited_once()

    def main_handler(self, chemistry, guild_id=0, legacy_channel=2):
        # Execute the actual dispatch function without connecting a bot or
        # importing the repository's large word dictionaries.
        path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message")
        node.decorator_list = []
        namespace = {"GUILD_ID": guild_id, "CHANNEL_ID": legacy_channel,
                     "CHEMISTRY_CHANNEL_ID": self.CHANNEL, "chemistry": chemistry}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        return namespace["on_message"], namespace

    async def test_main_chemistry_bypasses_only_legacy_channel_filter(self):
        chemistry = SimpleNamespace(handle_message=AsyncMock())
        handler, _ = self.main_handler(chemistry)
        msg = self.message()
        await handler(msg)
        chemistry.handle_message.assert_awaited_once_with(msg, self.CHANNEL)

    async def test_main_still_enforces_guild_and_bot_filter(self):
        chemistry = SimpleNamespace(handle_message=AsyncMock())
        handler, _ = self.main_handler(chemistry, guild_id=99)
        await handler(self.message(guild=1))
        await handler(self.message(guild=99, is_bot=True))
        chemistry.handle_message.assert_not_awaited()

    async def test_other_disallowed_channel_is_unchanged(self):
        chemistry = SimpleNamespace(handle_message=AsyncMock())
        handler, _ = self.main_handler(chemistry)
        await handler(self.message(channel=3))
        chemistry.handle_message.assert_not_awaited()

    async def test_existing_channel_reaches_original_dispatch(self):
        class ReachedLegacyDispatch(Exception):
            pass
        def mode_of(_):
            raise ReachedLegacyDispatch
        chemistry = SimpleNamespace(handle_message=AsyncMock())
        handler, namespace = self.main_handler(chemistry)
        namespace["mode_of"] = mode_of
        with self.assertRaises(ReachedLegacyDispatch):
            await handler(self.message(channel=2, content="!체스"))
        chemistry.handle_message.assert_not_awaited()

    async def test_import_failure_has_visible_fallback(self):
        handler, _ = self.main_handler(None)
        msg = self.message()
        await handler(msg)
        msg.channel.send.assert_awaited_once()
        self.assertIn("불러오지", msg.channel.send.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
