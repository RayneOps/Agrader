from datetime import date

from django.test import SimpleTestCase

from recommendations import engine
from recommendations.tests.builders import crop, make_input, pair, reading, rule, settings

MAIZE = crop("Maize", "cereal", n_demand="high")
COWPEA = crop("Cowpea", "legume", fixes_nitrogen=True, n_demand="low", days_min=60, days_max=100, water_low_mm=300)
GROUNDNUT = crop("Groundnut", "legume", fixes_nitrogen=True, n_demand="low")
SORGHUM = crop("Sorghum", "cereal", days_min=100, days_max=180, water_low_mm=400)
MILLET = crop("Millet", "cereal", n_demand="low", p_demand="low", k_demand="low", days_min=70, days_max=110)
TOMATO = crop("Tomato", "solanaceae", days_min=75)
PEPPER = crop("Pepper", "solanaceae")
YAM = crop("Yam", "root_tuber", days_min=210, days_max=300, water_low_mm=1000, exempt_from_season_length=True)
LOWLAND_RICE = crop("Lowland rice", "cereal", requires_standing_water=True)


def component(score_or_option, key):
    return next(c for c in score_or_option.components if c.key == key)


def single_score(c, **input_overrides):
    inp = make_input([c], **input_overrides)
    weights, _ = engine.effective_weights(inp)
    return engine.score_crop(c, inp, weights)


class HardRuleTests(SimpleTestCase):
    def removed(self, inp):
        _, removed = engine.apply_hard_rules(inp)
        return {(r.crop, r.rule) for r in removed}

    def test_ph_outside_min_and_max(self):
        self.assertEqual(self.removed(make_input([MAIZE], reading=reading(ph=4.9))), {("Maize", "ph")})
        self.assertEqual(self.removed(make_input([MAIZE], reading=reading(ph=8.1))), {("Maize", "ph")})
        self.assertEqual(self.removed(make_input([MAIZE], reading=reading(ph=5.0))), set())

    def test_standing_water_needs_more_than_rain(self):
        self.assertEqual(self.removed(make_input([LOWLAND_RICE])), {("Lowland rice", "standing_water")})
        self.assertEqual(self.removed(make_input([LOWLAND_RICE], water_source="fadama")), set())

    def test_season_length_uses_planting_date_and_exemptions(self):
        late = {"planting_date": date(2027, 8, 1)}  # 75 days to 15 Oct
        self.assertEqual(self.removed(make_input([MAIZE], **late)), {("Maize", "season_length")})
        self.assertEqual(self.removed(make_input([YAM], **late)), set(), "yam is exempt")
        self.assertEqual(self.removed(make_input([MAIZE], water_source="irrigated", **late)), set())
        _, removed = engine.apply_hard_rules(make_input([MAIZE], **late))
        self.assertIn("only 75 days remain", removed[0].reason)

    def test_rotation_block_on_any_previous_crop(self):
        r5 = rule("R5", "solanaceae", "solanaceae", "block", "Bacterial wilt carries over.")
        inp = make_input([TOMATO, MAIZE], previous={1: [MILLET, PEPPER]}, rotation_rules=[r5], has_history=True)
        survivors, removed = engine.apply_hard_rules(inp)
        self.assertEqual([c.name for c in survivors], ["Maize"])
        self.assertIn("Pepper last season blocks Tomato. R5: Bacterial wilt carries over.", removed[0].reason)

    def test_block_looks_only_at_last_season(self):
        r5 = rule("R5", "solanaceae", "solanaceae", "block")
        inp = make_input([TOMATO], previous={2: [PEPPER]}, rotation_rules=[r5], has_history=True)
        self.assertEqual(self.removed(inp), set())

    def test_dry_season_on_rain_fed_farm_removes_everything(self):
        inp = make_input([MILLET, COWPEA], season_label="dry", planting_date=date(2027, 11, 10),
                         season_start=date(2027, 11, 1), season_end=date(2028, 3, 31))
        result = engine.run(inp)
        self.assertEqual(result.options, [])
        self.assertTrue(all("No water source in the dry season" in r.reason
                            for r in result.removed if r.rule == "dry_rain_fed"))
        self.assertEqual({r.crop for r in result.removed}, {"Millet", "Cowpea"})

    def test_crop_without_requirements_is_removed(self):
        self.assertEqual(self.removed(make_input([crop("New crop", requirement=False)])), {("New crop", "no_requirements")})

    def test_every_failing_rule_is_recorded(self):
        inp = make_input([LOWLAND_RICE], reading=reading(ph=4), planting_date=date(2027, 9, 1))
        self.assertEqual({r for _, r in self.removed(inp)}, {"ph", "standing_water", "season_length"})


class PhFitTests(SimpleTestCase):
    def test_linear_from_ideal_to_limits(self):
        self.assertEqual(component(single_score(MAIZE, reading=reading(ph=6.5)), "ph").points, 30)
        self.assertEqual(component(single_score(MAIZE, reading=reading(ph=5.0)), "ph").points, 0)
        self.assertEqual(component(single_score(MAIZE, reading=reading(ph=5.4)), "ph").points, 15)  # halfway 5.0–5.8
        self.assertEqual(component(single_score(MAIZE, reading=reading(ph=7.5)), "ph").points, 15)  # halfway 7.0–8.0


class NutrientFitTests(SimpleTestCase):
    def points(self, c, **values):
        return component(single_score(c, reading=reading(**values)), "nutrient").points

    def test_levels(self):
        # Thresholds N 20/40, P 10/25, K 80/150. All demand medium except maize N high.
        self.assertEqual(self.points(MAIZE, nitrogen=45, phosphorus=15, potassium=100), 25)
        self.assertAlmostEqual(self.points(MAIZE, nitrogen=30, phosphorus=15, potassium=100), 25 * (0.5 + 1 + 1) / 3, places=1)
        self.assertAlmostEqual(self.points(MAIZE, nitrogen=5, phosphorus=15, potassium=100), 25 * (0 + 1 + 1) / 3, places=1)

    def test_nitrogen_fixers_get_full_nitrogen(self):
        demanding = crop("Fixer", "legume", fixes_nitrogen=True, n_demand="high")
        self.assertEqual(self.points(demanding, nitrogen=1, phosphorus=15, potassium=100), 25)
        self.assertEqual(self.points(demanding, nitrogen=None, phosphorus=15, potassium=100), 25)

    def test_missing_value_is_left_out_and_rest_rescaled(self):
        # Only P and K measured and both meet demand: full marks, not two thirds.
        self.assertEqual(self.points(MAIZE, nitrogen=None, phosphorus=15, potassium=100), 25)
        detail = component(single_score(MAIZE, reading=reading(nitrogen=None)), "nutrient").detail
        self.assertIn("N not measured", detail)

    def test_nothing_measured_drops_nutrient_fit_for_everyone(self):
        inp = make_input([MAIZE, COWPEA], reading=reading(nitrogen=None, phosphorus=None, potassium=None))
        result = engine.run(inp)
        for option in result.options:
            self.assertNotIn("nutrient", [c.key for c in option.components])
            self.assertAlmostEqual(sum(c.max_points for c in option.components), 100, places=0)
        self.assertEqual(component(result.options[0], "ph").max_points, 40)  # 30 of 75, scaled to 100
        self.assertTrue(any("nutrient fit is left out" in n for n in result.notices))

    def test_shares_come_from_settings(self):
        weighted = settings(nutrient_shares={"n": 2, "p": 1, "k": 1})
        score = single_score(MAIZE, reading=reading(nitrogen=5), settings=weighted)
        self.assertAlmostEqual(component(score, "nutrient").points, 25 * 2 / 4, places=1)


class RotationFitTests(SimpleTestCase):
    R1 = rule("R1", "legume", "cereal", "bonus")
    R3 = rule("R3", "cereal", "cereal", "penalty")
    R8 = rule("R8", None, None, "strong_penalty", match="repeat_third_season")

    def points(self, c, previous, rules):
        score = single_score(c, previous=previous, rotation_rules=rules, has_history=bool(previous))
        return component(score, "rotation")

    def test_base_without_history(self):
        c = self.points(MAIZE, {}, [self.R1, self.R3])
        self.assertEqual(c.points, 15)
        self.assertIn("No history", c.detail)

    def test_bonus_and_penalty(self):
        self.assertEqual(self.points(MAIZE, {1: [COWPEA]}, [self.R1]).points, 25)
        self.assertEqual(self.points(MAIZE, {1: [SORGHUM]}, [self.R3]).points, 7.5)

    def test_each_rule_counts_once_however_many_previous_crops_match(self):
        self.assertEqual(self.points(MAIZE, {1: [SORGHUM, MILLET]}, [self.R3]).points, 7.5)

    def test_different_rules_add_up_then_clamp(self):
        self.assertEqual(self.points(MAIZE, {1: [COWPEA, SORGHUM]}, [self.R1, self.R3]).points, 17.5)  # 60+40-30
        self.assertEqual(self.points(MAIZE, {1: [MAIZE], 2: [MAIZE]}, [self.R3, self.R8]).points, 0)  # 60-30-60

    def test_third_season_rule_needs_both_earlier_seasons(self):
        self.assertEqual(self.points(MAIZE, {1: [MAIZE], 2: [COWPEA]}, [self.R8]).points, 15)
        self.assertEqual(self.points(MAIZE, {1: [MAIZE], 2: [MAIZE]}, [self.R8]).points, 0)

    def test_single_crop_rule(self):
        okro = crop("Okro", "malvaceae")
        r6 = rule("R6", okro, "solanaceae", "penalty")
        self.assertEqual(self.points(TOMATO, {1: [okro]}, [r6]).points, 7.5)
        self.assertEqual(self.points(MAIZE, {1: [okro]}, [r6]).points, 15)


class SeasonAndWaterFitTests(SimpleTestCase):
    def test_season_fit(self):
        self.assertEqual(component(single_score(MAIZE), "season").points, 10)  # 148 days, needs up to 120
        self.assertEqual(component(single_score(SORGHUM), "season").points, 5)  # 148 days, 100–180
        self.assertEqual(component(single_score(YAM), "season").points, 0)  # exempt survivor, 148 < 210

    def test_water_fit(self):
        self.assertEqual(component(single_score(YAM), "water").points, 10)  # 1200 * 148/173 = 1027 mm
        self.assertEqual(component(single_score(YAM, water_source="irrigated"), "water").points, 10)
        late = {"planting_date": date(2027, 8, 1)}  # 1200 * 75/173 = 520 mm
        self.assertEqual(component(single_score(YAM, **late), "water").points, 0)
        thirsty = crop("Thirsty", water_low_mm=600, days_min=60)
        self.assertEqual(component(single_score(thirsty, **late), "water").points, 5)  # 520 >= 450

    def test_rainfall_comes_from_settings(self):
        dry_year = settings(seasonal_rainfall_mm=500)
        self.assertEqual(component(single_score(YAM, settings=dry_year), "water").points, 0)


class TotalsTests(SimpleTestCase):
    def test_components_add_up_to_the_score(self):
        score = single_score(MAIZE, previous={1: [COWPEA]}, rotation_rules=[RotationFitTests.R1], has_history=True)
        self.assertAlmostEqual(sum(c.points for c in score.components), score.total, places=1)
        self.assertEqual([c.key for c in score.components], ["ph", "nutrient", "rotation", "season", "water"])

    def test_weights_not_adding_to_100_are_scaled(self):
        odd = settings(weights={"ph": 60, "nutrient": 50, "rotation": 50, "season": 20, "water": 20})
        score = single_score(MAIZE, settings=odd)
        self.assertEqual(sum(c.max_points for c in score.components), 100)
        self.assertEqual(component(score, "ph").max_points, 30)


class MixedCroppingTests(SimpleTestCase):
    def test_mono_ranks_single_crops_best_first(self):
        result = engine.run(make_input([SORGHUM, MAIZE, COWPEA]))
        self.assertEqual(result.mode, "mono")
        self.assertTrue(all(o.is_single for o in result.options))
        scores = [o.score for o in result.options]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_combinations_of_two_and_three_without_avoid_pairs(self):
        inp = make_input([MAIZE, COWPEA, MILLET], cropping_method="mixed",
                         pair_rules=[pair(MAIZE, MILLET, "avoid"), pair(MAIZE, COWPEA, "good")])
        result = engine.run(inp)
        combos = {tuple(sorted(o.crops)) for o in result.options}
        self.assertEqual(combos, {("Cowpea", "Maize"), ("Cowpea", "Millet")})
        self.assertEqual(result.mode, "mixed")
        maize_cowpea = next(o for o in result.options if set(o.crops) == {"Maize", "Cowpea"})
        mean = sum(s.total for s in maize_cowpea.crop_scores) / 2
        self.assertAlmostEqual(maize_cowpea.score, min(100, mean + 5), places=1)
        self.assertEqual(maize_cowpea.good_pairs, ["Maize + Cowpea"])

    def test_three_crop_combination_gets_bonus_per_good_pair(self):
        inp = make_input([MAIZE, COWPEA, SORGHUM], cropping_method="mixed",
                         pair_rules=[pair(MAIZE, COWPEA, "good"), pair(SORGHUM, COWPEA, "good")])
        trio = next(o for o in engine.run(inp).options if len(o.crops) == 3)
        self.assertEqual(trio.pair_bonus, 10)

    def test_bonus_capped_at_100(self):
        perfect = crop("Perfect", water_low_mm=100, days_min=30, days_max=60, n_demand="low", p_demand="low", k_demand="low")
        other = crop("Other", water_low_mm=100, days_min=30, days_max=60, n_demand="low", p_demand="low", k_demand="low")
        r = rule("R1", "cereal", "cereal", "bonus")
        inp = make_input([perfect, other], cropping_method="mixed", pair_rules=[pair(perfect, other, "good")],
                         previous={1: [MAIZE]}, rotation_rules=[r], has_history=True)
        self.assertEqual(engine.run(inp).options[0].score, 100)

    def test_falls_back_to_singles_when_only_one_survives(self):
        result = engine.run(make_input([MAIZE, LOWLAND_RICE], cropping_method="mixed"))
        self.assertEqual(result.mode, "mixed_fallback")
        self.assertEqual([o.crops for o in result.options], [["Maize"]])
        self.assertTrue(any("Only Maize passed the rules" in n for n in result.notices))

    def test_falls_back_when_every_pair_is_avoid(self):
        inp = make_input([MAIZE, MILLET], cropping_method="mixed", pair_rules=[pair(MAIZE, MILLET, "avoid")])
        result = engine.run(inp)
        self.assertEqual(result.mode, "mixed_fallback")
        self.assertTrue(any("listed as a pairing to avoid" in n for n in result.notices))

    def test_zero_survivors_gives_no_options(self):
        result = engine.run(make_input([MAIZE], reading=reading(ph=3.5), cropping_method="mixed"))
        self.assertEqual(result.options, [])
        self.assertEqual(len(result.removed), 1)

    def test_only_top_five_options(self):
        crops = [crop(f"Crop {i}") for i in range(5)]  # 10 pairs + 10 trios
        result = engine.run(make_input(crops, cropping_method="mixed"))
        self.assertEqual(len(result.options), 5)
        self.assertEqual(result.total_options, 20)

    def test_combination_breakdown_is_the_average_of_its_crops(self):
        inp = make_input([MAIZE, COWPEA], cropping_method="mixed")
        option = engine.run(inp).options[0]
        for i, c in enumerate(option.components):
            expected = sum(s.components[i].points for s in option.crop_scores) / 2
            self.assertAlmostEqual(c.points, expected, places=1)
