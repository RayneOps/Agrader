"""Draft crop knowledge for Minna, Niger State. Every value here is UNVERIFIED and is loaded
with approved = false, awaiting sign-off by our Crop Scientist."""

# name, also_called, scientific_name, family, fixes_nitrogen,
# ph_min, ph_ideal_low, ph_ideal_high, ph_max, n, p, k,
# water_low_mm, water_high_mm, days_min, days_max, temp_low, temp_high, planting_window
CROPS = [
    ("Yam", "White yam, Doya", "Dioscorea rotundata", "root_tuber", False,
     "5.0", "5.5", "6.5", "7.0", "medium", "low", "high", 1000, 1500, 210, 300, 25, 30, "Mar to May"),
    ("Maize", "Masara", "Zea mays", "cereal", False,
     "5.0", "5.8", "7.0", "8.0", "high", "medium", "medium", 500, 800, 90, 120, 20, 30, "May to Jun"),
    ("Beans (cowpea)", "Wake", "Vigna unguiculata", "legume", True,
     "5.0", "5.5", "6.5", "7.5", "low", "medium", "low", 300, 600, 60, 100, 25, 35, "Jul to Aug"),
    ("Guinea corn", "Sorghum, Dawa", "Sorghum bicolor", "cereal", False,
     "5.0", "5.5", "7.5", "8.5", "medium", "medium", "medium", 400, 650, 100, 180, 25, 32, "May to Jul"),
    ("Rice (lowland)", "Shinkafa, fadama rice", "Oryza sativa", "cereal", False,
     "5.0", "5.5", "6.5", "7.5", "high", "medium", "medium", 1000, 1500, 110, 150, 22, 32, "Jun to Jul"),
    ("Rice (upland)", "Shinkafa", "Oryza sativa", "cereal", False,
     "5.0", "5.5", "6.5", "7.5", "medium", "medium", "medium", 800, 1200, 90, 120, 22, 32, "May to Jun"),
    ("Groundnut", "Gyada", "Arachis hypogaea", "legume", True,
     "5.0", "5.8", "6.5", "7.5", "low", "medium", "low", 500, 700, 90, 130, 25, 30, "May to Jun"),
    ("Soya beans", "Waken soya", "Glycine max", "legume", True,
     "5.5", "6.0", "7.0", "7.5", "low", "high", "medium", 450, 700, 90, 120, 20, 30, "Jun to Jul"),
    ("Tomatoes", "Tumatir", "Solanum lycopersicum", "solanaceae", False,
     "5.5", "6.0", "6.8", "7.5", "high", "high", "high", 400, 600, 75, 120, 20, 27,
     "Oct to Feb irrigated; Jun to Jul rain-fed"),
    ("Pepper", "Tatashe, Rodo, Barkono", "Capsicum spp.", "solanaceae", False,
     "5.5", "6.0", "6.8", "7.5", "medium", "medium", "high", 600, 900, 90, 150, 20, 30,
     "Transplant Jun to Jul; also dry season irrigated"),
    ("Millet", "Pearl millet, Gero", "Pennisetum glaucum", "cereal", False,
     "5.0", "5.5", "7.0", "8.0", "low", "low", "low", 300, 600, 70, 110, 25, 35, "May to Jun"),
    ("Okro", "Okra, Kubewa", "Abelmoschus esculentus", "malvaceae", False,
     "5.5", "6.0", "6.8", "7.5", "medium", "medium", "medium", 400, 700, 50, 90, 24, 32, "Apr to Jun"),
]

REQUIRES_STANDING_WATER = {"Rice (lowland)"}
EXEMPT_FROM_SEASON_LENGTH = {"Yam"}

GOOD_PAIRS = [
    ("Yam", "Maize"), ("Yam", "Okro"), ("Yam", "Beans (cowpea)"), ("Maize", "Beans (cowpea)"),
    ("Maize", "Groundnut"), ("Maize", "Soya beans"), ("Maize", "Okro"), ("Guinea corn", "Beans (cowpea)"),
    ("Guinea corn", "Groundnut"), ("Guinea corn", "Soya beans"), ("Guinea corn", "Millet"),
    ("Millet", "Beans (cowpea)"), ("Millet", "Groundnut"), ("Okro", "Beans (cowpea)"),
    ("Tomatoes", "Beans (cowpea)"), ("Pepper", "Beans (cowpea)"), ("Pepper", "Maize"),
]

AVOID_PAIRS = [
    ("Maize", "Guinea corn"), ("Maize", "Millet"), ("Beans (cowpea)", "Groundnut"),
    ("Beans (cowpea)", "Soya beans"), ("Groundnut", "Soya beans"), ("Tomatoes", "Pepper"),
    ("Tomatoes", "Okro"), ("Pepper", "Okro"), ("Rice (upland)", "Maize"), ("Rice (upland)", "Guinea corn"),
] + [("Rice (lowland)", row[0]) for row in CROPS if row[0] != "Rice (lowland)"]

# code, previous (family or crop name), next (family or crop name), effect, reason.
# `None` sides mark the R8 special case. Crop names are told apart from families by FAMILIES.
FAMILIES = {"cereal", "legume", "root_tuber", "solanaceae", "malvaceae"}
ROTATION_RULES = [
    ("R1", "legume", "cereal", "bonus", "Residual nitrogen from the legume benefits the cereal."),
    ("R2", "legume", "root_tuber", "small_bonus", "Some nitrogen benefit for non-cereals."),
    ("R2", "legume", "solanaceae", "small_bonus", "Some nitrogen benefit for non-cereals."),
    ("R2", "legume", "malvaceae", "small_bonus", "Some nitrogen benefit for non-cereals."),
    ("R3", "cereal", "cereal", "penalty", "Repeated cereals deplete nitrogen and build up Striga."),
    ("R4", "legume", "legume", "penalty", "Shared pests and diseases."),
    ("R5", "solanaceae", "solanaceae", "block", "Bacterial wilt and nematodes carry over."),
    ("R6", "Okro", "solanaceae", "penalty", "Root-knot nematode carry-over."),
    ("R6", "solanaceae", "Okro", "penalty", "Root-knot nematode carry-over."),
    ("R7", "Yam", "Yam", "penalty", "Heavy feeder; nematodes and yield decline."),
    ("R8", None, None, "strong_penalty", "Safeguard against continuous monocropping."),
    ("R9", "cereal", "legume", "bonus", "Legume restores nitrogen after a cereal."),
]

# key, group, kind, value, description
SCORE_SETTINGS = [
    ("weight_ph", "weights", "number", "30", "Points for pH fit."),
    ("weight_nutrient", "weights", "number", "25", "Points for nutrient fit."),
    ("weight_rotation", "weights", "number", "25", "Points for rotation fit."),
    ("weight_season", "weights", "number", "10", "Points for season fit."),
    ("weight_water", "weights", "number", "10", "Points for water fit."),
    ("rainy_season_start", "calendar", "month_day", "04-25", "Rains begin (draft)."),
    ("rainy_season_end", "calendar", "month_day", "10-15", "Rains end (draft). End of the rainy season."),
    ("dry_season_start", "calendar", "month_day", "11-01", "Dry season begins (draft)."),
    ("dry_season_end", "calendar", "month_day", "03-31", "Dry season ends (draft), in the following year."),
    ("seasonal_rainfall_mm", "water", "number", "1200",
     "Total rainfall over a full rainy season, in mm. Used for water fit on rain-fed farms."),
    ("nutrient_share_n", "nutrients", "number", "1", "Relative share of nitrogen in nutrient fit."),
    ("nutrient_share_p", "nutrients", "number", "1", "Relative share of phosphorus in nutrient fit."),
    ("nutrient_share_k", "nutrients", "number", "1", "Relative share of potassium in nutrient fit."),
    ("n_medium_min_mg_kg", "thresholds", "number", "20",
     "PLACEHOLDER. Nitrogen at or above this is medium. Sensor units and accuracy not confirmed."),
    ("n_high_min_mg_kg", "thresholds", "number", "40",
     "PLACEHOLDER. Nitrogen at or above this is high. Sensor units and accuracy not confirmed."),
    ("p_medium_min_mg_kg", "thresholds", "number", "10",
     "PLACEHOLDER. Phosphorus at or above this is medium. Sensor units and accuracy not confirmed."),
    ("p_high_min_mg_kg", "thresholds", "number", "25",
     "PLACEHOLDER. Phosphorus at or above this is high. Sensor units and accuracy not confirmed."),
    ("k_medium_min_mg_kg", "thresholds", "number", "80",
     "PLACEHOLDER. Potassium at or above this is medium. Sensor units and accuracy not confirmed."),
    ("k_high_min_mg_kg", "thresholds", "number", "150",
     "PLACEHOLDER. Potassium at or above this is high. Sensor units and accuracy not confirmed."),
]
