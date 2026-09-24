"""Chemical conservation and regression tests for conditional product discovery."""
from itertools import combinations, permutations
import unittest

import chemistry_bot as bot
import chemistry_engine as engine
import chemistry_reactions as reactions


class ProductDiscoveryTests(unittest.TestCase):
    def predict(self, text, **options):
        return reactions.predict_reaction(text, reactions.parse_conditions(options))

    def assert_conserved(self, equation):
        left, right = equation.text.split(" → ")
        self.assertEqual(engine.sum_composition(engine.parse_sum(left)),
                         engine.sum_composition(engine.parse_sum(right)))

    def test_exact_screenshot_input_finds_products_and_accounts_for_water(self):
        result = bot.evaluate("!반응 C6H12O6 + 6O2 + 6H2O")
        self.assertEqual(result.status, "CONDITIONAL_PRODUCTS")
        self.assertIn("생성물 후보: CO2 + H2O", result.text)
        self.assertIn("C6H12O6 + 6O2 → 6CO2 + 6H2O", result.text)
        self.assertIn("입력한 물", result.text)
        self.assertIn("실제 투입량으로 사용하지 않았습니다", result.text)
        self.assertIn("완전 산화를 가정", result.text)
        self.assertNotIn("12H2O", result.text)

    def test_general_oxidation_is_derived_not_glucose_lookup(self):
        for expression, coefficients in (
            ("C12H22O11 + O2", (1, 12, 12, 11)),
            ("C6H12O6 + O2", (1, 6, 6, 6)),
            ("CH4 + O2", (1, 2, 1, 2)),
        ):
            with self.subTest(expression=expression):
                candidates = reactions.discover_candidates(engine.parse_sum(expression))
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0].equation.coefficients, coefficients)
                self.assert_conserved(candidates[0].equation)
                self.assertIn("분자 구조", candidates[0].note)

    def test_oxidation_requires_oxygen_and_supported_neutral_composition(self):
        for text in ("C6H12O6 + H2O", "C2H5NO2 + O2", "C2H3O2^- + O2", "H2CO3 + O2", "NaHCO3 + O2"):
            with self.subTest(text=text):
                self.assertFalse(reactions.discover_candidates(engine.parse_sum(text), "oxidation"))

    def test_three_reactants_and_spectator_do_not_block_precipitation(self):
        result = self.predict("CaCl2 + Na2CO3 + KCl")
        text = "\n".join(result.lines)
        self.assertEqual(result.status, "NEEDS_CONDITIONS")
        self.assertIn("CaCO3(s)", text)
        self.assertIn("CaCl2(aq) + Na2CO3(aq) → CaCO3(s) + 2NaCl(aq)", text)
        self.assertIn("계산하지 않은 입력: KCl", text)
        self.assertIn("용매=물", text)

    def test_entire_pool_is_searched_without_requiring_every_salt_to_participate(self):
        species = engine.parse_sum("CaCl2 + MgCl2 + Na2CO3 + KOH")
        solids = {c.solid for c in reactions.discover_candidates(species) if c.solid}
        self.assertEqual(solids, {"CaCO3", "Ca(OH)2", "Mg(OH)2"})

    def test_neutralization_does_not_hide_competing_precipitation(self):
        result = self.predict("HCl + NaOH + CaCl2 + Na2CO3", 용매="물", 온도="25")
        text = "\n".join(result.lines)
        self.assertEqual(result.status, "COMPETING_CANDIDATES")
        self.assertIn("강산·강염기 중화", text)
        self.assertIn("탄산칼슘 침전 후보", text)
        self.assertIn("합산하지 않았습니다", text)

    def test_carbonate_stages_are_alternatives_not_one_fixed_outcome(self):
        result = self.predict("HCl + Na2CO3")
        text = "\n".join(result.lines)
        self.assertEqual(result.status, "COMPETING_CANDIDATES")
        self.assertIn("HCO3^-(aq)", text)
        self.assertIn("CO2 + H2O(l)", text)
        self.assertIn("산의 양과 pH", text)

    def test_bicarbonate_products_and_molecular_form(self):
        result = self.predict("HCl + NaHCO3", 용매="물", 온도="25")
        self.assertEqual(result.status, "CONDITIONAL_PRODUCTS")
        self.assertIn("HCl(aq) + NaHCO3(aq) → CO2 + H2O(l) + NaCl(aq)", "\n".join(result.lines))

    def test_unknown_additive_is_not_dropped_or_called_inert(self):
        for text in ("CaCl2 + Na2CO3 + Xe", "C6H12O6 + O2 + NaCl"):
            with self.subTest(text=text):
                result = self.predict(text)
                self.assertEqual(result.status, "PARTIAL_CANDIDATES")
                self.assertIn("전체 반응에 대해 미판정인 입력", "\n".join(result.lines))
                self.assertIn("영향도 배제하지 않았습니다", "\n".join(result.lines))

    def test_solid_input_is_not_silently_dissolved(self):
        result = self.predict("CaCl2(s) + Na2CO3(aq)", 용매="물", 온도="25")
        self.assertEqual(result.status, "OUT_OF_DOMAIN")
        result = self.predict("HCl + NaOH + CaCO3(s)")
        self.assertEqual(result.status, "PARTIAL_CANDIDATES")
        self.assertIn("CaCO3(s)", "\n".join(result.lines))

    def test_two_solids_are_evaluated_with_their_own_ion_concentrations(self):
        result = self.predict("CaCl2 + MgCl2 + NaOH", **{
            "용매": "물", "온도": "25", "Ca^2+": "0.001M", "Mg^2+": "0.001M", "OH^-": "0.001M"})
        text = "\n".join(result.lines)
        self.assertEqual(result.status, "COMPETING_CANDIDATES")
        self.assertIn("0.000769231", text)
        self.assertIn("112.360", text)
        self.assertIn("불포화", text)
        self.assertIn("과포화", text)

    def test_unused_conditions_are_rejected(self):
        cases = [
            ("CaCl2 + Na2CO3", {"Na^+": "0.001M"}),
            ("HCl + NaOH", {"고체": "있음"}),
            ("CaCl2 + MgCl2 + NaOH", {"고체": "있음"}),
        ]
        for expression, extra in cases:
            with self.subTest(expression=expression), self.assertRaises(engine.ChemistryError):
                self.predict(expression, 용매="물", 온도="25", **extra)
        self.assertEqual(self.predict("C6H12O6 + O2", 온도="25").status, "UNSUPPORTED_CONDITIONS")
        with self.assertRaises(engine.ChemistryError):
            reactions.saturation("CaCO3", reactions.parse_conditions({"유형": "완전산화"}))

    def test_model_selection_and_duplicate_aliases(self):
        self.assertEqual(self.predict("C6H12O6 + O2", 유형="수용액").status, "UNSUPPORTED_REACTION")
        self.assertEqual(self.predict("C6H12O6 + O2", 유형="완전산화").status, "CONDITIONAL_PRODUCTS")
        for options in ({"유형": "가짜"}, {"유형": "자동", "type": "auto"}):
            with self.assertRaises(engine.ChemistryError):
                reactions.parse_conditions(options)

    def test_reordering_and_duplicate_input_are_deterministic(self):
        outputs = {self.predict(" + ".join(parts)) for parts in permutations(("CaCl2", "Na2CO3", "KCl"))}
        self.assertEqual(len(outputs), 1)
        result = self.predict("CaCl2 + CaCl2 + Na2CO3")
        self.assertIn("중복 입력", "\n".join(result.lines))
        self.assertEqual(sum("**후보 " in line for line in result.lines), 1)

    def test_rule_data_sources_and_conservation(self):
        for rule, equation in reactions.ION_RULES:
            with self.subTest(rule=rule["id"]):
                self.assert_conserved(equation)
                self.assertTrue(set(rule["sources"]) <= reactions.REACTION_DATA["sources"].keys())
        for left, right in combinations(reactions.DISSOCIATION, 2):
            species = engine.parse_sum(left + " + " + right)
            for candidate in reactions.discover_candidates(species, "aqueous"):
                self.assert_conserved(candidate.equation)
                for text in reactions.molecular_examples(candidate, species):
                    self.assert_conserved(engine.balance_equation(text))

    def test_hydrated_precipitate_includes_water(self):
        result = self.predict("CaCl2 + Na2SO4", 용매="물", 온도="25")
        self.assertIn("CaCl2(aq) + Na2SO4(aq) + 2H2O(l) → CaSO4·2H2O(s) + 2NaCl(aq)", "\n".join(result.lines))

    def test_maximum_mixture_and_discord_pages(self):
        terms = list(reactions.DISSOCIATION)[:16]
        result = bot.evaluate("!생성물 " + " + ".join(terms))
        self.assertEqual(result.status, "COMPETING_CANDIDATES")
        embeds = bot.build_embeds(result)
        self.assertTrue(all(len(e.description) <= 4096 and len(e) <= 6000 for e in embeds))
        self.assertEqual("".join(e.description.replace("\n", "") for e in embeds), result.text.replace("\n", ""))
        self.assertEqual(bot.evaluate("!반응 " + " + ".join(terms + ["NaHCO3"])).status, "INPUT_LIMIT")

    def test_new_alias_and_help_are_live(self):
        self.assertEqual(bot.evaluate("!생성물 C6H12O6 + O2"), bot.evaluate("!반응 C6H12O6 + O2"))
        self.assertEqual(bot.evaluate("!화학 생성물 C6H12O6 + O2"), bot.evaluate("!반응 C6H12O6 + O2"))
        self.assertIn("완전산화", bot.evaluate("!화학").text)


if __name__ == "__main__":
    unittest.main()
