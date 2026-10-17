import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import import_wikibooks as wb  # noqa: E402

# Ingredient lines from Wikibooks "Cookbook:Atkilt Wat (Ethiopian Cabbage and Potato Stew)",
# revision 4518570, CC BY-SA 4.0, https://en.wikibooks.org/w/index.php?oldid=4518570
SAMPLE = (ROOT / "tests" / "fixtures" / "wikibooks-atkilt-wat.wikitext").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ctx():
    return wb.load_config()


@pytest.mark.parametrize("raw, expected", [
    ("2 [[Cookbook:Tablespoon|tablespoons]] [[Cookbook:vegetable oil|vegetable oil]]",
     {"ingredient": "vegetable-oil", "qty": 2, "unit": "tbsp"}),
    ("3 cloves of [[Cookbook:Garlic|garlic]], [[Cookbook:Mince|minced]]",
     {"ingredient": "garlic", "qty": 3, "unit": "clove", "prep": "minced"}),
    ("1 tablespoon grated [[Cookbook:Ginger|ginger]]", {"ingredient": "ginger", "qty": 1, "unit": "tbsp"}),
    ("½ teaspoon [[Cookbook:coriander|coriander]]", {"ingredient": "ground-coriander", "qty": 0.5, "unit": "tsp"}),
    ("1 medium [[Cookbook:Cabbage|cabbage]], finely shredded",
     {"ingredient": "white-cabbage", "qty": 1, "prep": "finely shredded", "note": "medium"}),
    ("[[Cookbook:Salt|Salt]], to taste", {"ingredient": "salt", "note": "to taste"}),
    ("Fresh [[Cookbook:cilantro|cilantro]], chopped, for [[Cookbook:Garnish|garnish]]",
     {"ingredient": "cilantro", "prep": "chopped, for garnish"}),
    ("1 lb [[Cookbook:Potato|potatoes]]", {"ingredient": "potato", "qty": 454, "unit": "g"}),
    ("1 1/2 cups rice", {"ingredient": "long-grain-rice", "qty": 1.5, "unit": "cup"}),
    ("2–3 tbsp [[Cookbook:Olive Oil|olive oil]]", {"ingredient": "olive-oil", "qty": [2, 3], "unit": "tbsp"}),
    ("1 teaspoon cumin seeds", {"ingredient": "cumin-seeds", "qty": 1, "unit": "tsp"}),
    ("1 cup [[Cookbook:Coconut Milk|coconut milk]] (optional)", {"ingredient": "coconut-milk", "qty": 1, "unit": "cup", "optional": True}),
    ("2 oz [[Cookbook:Sherry|sherry]]", {"ingredient": "sherry", "qty": 59, "unit": "ml"}),
    ("8 oz [[Cookbook:Butter|butter]]", {"ingredient": "butter", "qty": 227, "unit": "g"}),
    ("4 [[Cookbook:Clove|cloves]]", {"ingredient": "whole-cloves", "qty": 4}),
    ("2 small pieces [[Cookbook:Cinnamon|cinnamon]]", {"ingredient": "cinnamon-stick", "qty": 2, "note": "small"}),
    ("3 cloves of [[Cookbook:Garlic|garlic]]", {"ingredient": "garlic", "qty": 3, "unit": "clove"}),
])
def test_parse_ingredient_line(ctx, raw, expected):
    _, matcher = ctx
    line, issue, _ = wb.parse_ingredient_line(raw, matcher)
    assert issue is None
    assert line == expected


def test_unmapped_ingredient_is_reported_not_guessed(ctx):
    _, matcher = ctx
    line, issue, name = wb.parse_ingredient_line("2 cups [[Cookbook:Unobtainium|unobtainium]]", matcher)
    assert line is None and "unmapped" in issue and name == "unobtainium"


def test_plain_strips_markup():
    assert wb.plain("Add '''[[Cookbook:Onion|onions]]''' and {{tmpl|x}} stir<ref>src</ref>.") == "Add onions and stir."


@pytest.mark.parametrize("text, minutes", [("1 hour 30 minutes", 90), ("45 min", 45), ("2 hours", 120), ("", None), ("varies", None),
                                           ("Prep: 15 minutes<br>Baking: 50-70 minutes", 65), ("½ hour", 30), ("1½ hours", 90)])
def test_parse_minutes(text, minutes):
    assert wb.parse_minutes(text) == minutes


def test_sample_page_converts_but_is_queued_for_missing_facts(ctx):
    cfg, matcher = ctx
    page = {"title": "Cookbook:Atkilt Wat (Ethiopian Cabbage and Potato Stew)", "revid": 4518570,
            "wikitext": SAMPLE, "categories": ["Category:Ethiopian recipes", "Category:Recipes for stew"]}
    recipe, issues, unmatched = wb.convert_page(page, cfg, matcher)
    assert recipe["id"] == "et-atkilt-wat"
    assert recipe["alternate_names"] == ["Ethiopian Cabbage and Potato Stew"]
    assert recipe["difficulty"] == 2 and recipe["course"] == "main"
    assert len(recipe["steps"]) == 9 and "sauteing" in recipe["techniques"]
    assert recipe["credit"]["license"] == "CC-BY-SA-4.0"
    assert "oldid=4518570" in recipe["credit"]["dataset"]["url"]
    # The source has no servings or time: those must be flagged, never invented.
    assert "no servings in recipe summary" in issues and "no time in recipe summary" in issues
    assert unmatched == []
    assert len(recipe["ingredient_groups"][0]["items"]) == 14


def test_complete_page_passes_the_build_validator(ctx, tmp_path):
    import build
    cfg, matcher = ctx
    text = SAMPLE.replace("| difficulty = 2", "| difficulty = 2\n| servings = 4\n| time = 45 minutes")
    page = {"title": "Cookbook:Atkilt Wat (Ethiopian Cabbage and Potato Stew)", "revid": 1,
            "wikitext": text, "categories": ["Category:Ethiopian recipes", "Category:Recipes for stew"]}
    recipe, issues, _ = wb.convert_page(page, cfg, matcher)
    assert issues == []
    assert recipe["yield"] == {"servings": 4} and recipe["time"] == {"total_min": 45}
    path = tmp_path / "recipes" / "et" / "atkilt-wat.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(wb.dump_recipe(recipe), encoding="utf-8")
    ref = build.load_reference(ROOT)
    validator = build.Draft202012Validator(build.json.loads((ROOT / "schema" / "recipe.schema.json").read_text()),
                                           format_checker=build.FormatChecker())
    assert build.check_recipe(path, yaml.safe_load(path.read_text()), ref, validator) == []


def test_breadcrumb_line_after_multiline_summary_is_not_the_summary(ctx):
    cfg, matcher = ctx
    text = ("__NOTOC__{{recipesummary|category=Bread recipes|servings=8|time=Prep: 15 minutes<br>Baking: 50 minutes|difficulty=2\n}}"
            "{{recipe}}| [[Cookbook:Cuisine of Ireland|Irish cuisine]] | [[Cookbook:Bread|Bread]]\n\n"
            "Soda bread is leavened with baking soda instead of yeast.\n== Ingredients ==\n* 2 cups flour\n== Procedure ==\n# Mix and bake it.\n")
    page = {"title": "Cookbook:Irish Soda Bread", "revid": 1, "wikitext": text, "categories": ["Category:Irish recipes", "Category:Bread recipes"]}
    recipe, issues, _ = wb.convert_page(page, cfg, matcher)
    assert recipe["summary"] == "Soda bread is leavened with baking soda instead of yeast."
    assert recipe["time"] == {"total_min": 65} and recipe["yield"] == {"servings": 8}


def test_several_cuisines_without_summary_cuisine_needs_review(ctx):
    cfg, matcher = ctx
    page = {"title": "Cookbook:Chicken Tikka", "revid": 1, "wikitext": SAMPLE,
            "categories": ["Category:Afghan recipes", "Category:Indian recipes"]}
    recipe, issues, _ = wb.convert_page(page, cfg, matcher)
    assert any("several cuisines" in i for i in issues)
