import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402


CATALOG = {
    "rice": {"name": "rice", "category": "grain"},
    "butter": {"name": "butter", "category": "dairy", "animal": ["dairy"], "contains": ["milk"]},
    "olive-oil": {"name": "olive oil", "category": "fat"},
    "chicken": {"name": "chicken", "category": "poultry", "animal": ["poultry"]},
    "soy-sauce": {"name": "soy sauce", "category": "condiment", "contains": ["soy", "gluten"]},
    "oats": {"name": "oats", "category": "grain", "may_contain": ["gluten"]},
    "bacon": {"name": "bacon", "category": "meat", "animal": ["meat"], "contains": ["pork"]},
    "pecorino": {"name": "pecorino", "category": "dairy", "animal": ["dairy"], "contains": ["milk", "animal-rennet"]},
}


def recipe(*lines):
    return {"ingredient_groups": [{"items": list(lines)}]}


def test_repository_builds_cleanly():
    outputs, errors, _ = build.build()
    assert errors == []
    assert {"recipes.json", "ingredients.json", "countries.json", "coverage.md"} <= set(outputs)


def test_plain_plant_recipe_is_vegan():
    d = build.derive_dietary(recipe({"ingredient": "rice"}, {"ingredient": "olive-oil"}), CATALOG)
    assert "vegan" in d["tags"] and "gluten-free" in d["tags"]
    assert d["allergens"]["contains"] == []


def test_optional_animal_ingredient_makes_diet_adaptable():
    d = build.derive_dietary(recipe({"ingredient": "rice"}, {"ingredient": "butter", "optional": True}), CATALOG)
    assert d["diets"]["vegan"] == {"status": "adaptable", "changes": ["omit butter"]}
    assert d["diets"]["vegetarian"]["status"] == "yes"
    assert d["allergens"]["contains"] == []
    assert d["allergens"]["in_optional_ingredients"] == ["milk"]


def test_compliant_alternative_makes_diet_adaptable():
    d = build.derive_dietary(recipe({"ingredient": "butter", "alt": ["olive-oil"]}), CATALOG)
    assert d["diets"]["dairy-free"] == {"status": "adaptable", "changes": ["use olive oil instead of butter"]}


def test_required_ingredient_blocks_diet():
    d = build.derive_dietary(recipe({"ingredient": "chicken"}, {"ingredient": "soy-sauce"}), CATALOG)
    assert d["diets"]["vegetarian"] == {"status": "no", "because": ["chicken"]}
    assert d["diets"]["gluten-free"]["status"] == "no"
    assert d["diets"]["pescatarian"]["status"] == "no"
    assert d["allergens"]["contains"] == ["gluten", "soy"]


def test_may_contain_means_check_labels():
    d = build.derive_dietary(recipe({"ingredient": "oats"}), CATALOG)
    assert d["diets"]["gluten-free"] == {"status": "check-labels", "check": ["oats"]}
    assert "gluten-free" not in d["tags"]
    assert d["allergens"]["may_contain"] == ["gluten"]


def test_non_allergen_markers_are_not_listed_as_allergens():
    d = build.derive_dietary(recipe({"ingredient": "bacon"}, {"ingredient": "pecorino"}), CATALOG)
    assert d["diets"]["pork-free"]["status"] == "no"
    assert d["diets"]["vegetarian"]["because"] == ["bacon", "pecorino"]
    assert d["allergens"]["contains"] == ["milk"]


def test_override_wins_and_keeps_reason():
    r = recipe({"ingredient": "oats"})
    r["dietary_overrides"] = {"gluten-free": {"status": "yes", "reason": "certified oats specified"}}
    d = build.derive_dietary(r, CATALOG)
    assert d["diets"]["gluten-free"]["status"] == "yes"
    assert "gluten-free" in d["tags"]


@pytest.fixture
def repo_copy(tmp_path):
    for sub in ("data", "schema"):
        shutil.copytree(ROOT / sub, tmp_path / sub)
    (tmp_path / "recipes" / "et").mkdir(parents=True)
    shutil.copy(ROOT / "recipes" / "et" / "misir-wot.yaml", tmp_path / "recipes" / "et" / "misir-wot.yaml")
    return tmp_path


def write_recipe(root, rel, mutate):
    data = yaml.safe_load((ROOT / "recipes" / "et" / "misir-wot.yaml").read_text())
    mutate(data)
    path = root / "recipes" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True))


def test_copy_builds(repo_copy):
    _, errors, _ = build.build(repo_copy)
    assert errors == []


@pytest.mark.parametrize("rel, mutate, expected", [
    ("et/other.yaml", lambda r: None, "must be 'et-other'"),
    ("et/misir-wot.yaml", lambda r: r["ingredient_groups"][0]["items"].append({"ingredient": "unicorn"}), "unknown ingredient 'unicorn'"),
    ("et/misir-wot.yaml", lambda r: r.update(course="brunch"), "unknown course 'brunch'"),
    ("et/misir-wot.yaml", lambda r: r["credit"].update(source_type="adapted"), "requires credit.adapted_from"),
    ("et/misir-wot.yaml", lambda r: r["credit"].update(source_type="family"), "requires a contributor with role recipe-by"),
    ("et/misir-wot.yaml", lambda r: r["credit"].update(license="all-rights-reserved"), "unknown license"),
    ("et/misir-wot.yaml", lambda r: r.update(dietary={"tags": ["vegan"]}), "Additional properties"),
    ("et/misir-wot.yaml", lambda r: r["ingredient_groups"][0]["items"][2].pop("qty"), "a unit needs a qty"),
    ("et/misir-wot.yaml", lambda r: r["ingredient_groups"][0]["items"][2].update(qty=[3, 2]), "min < max"),
])
def test_invalid_recipes_are_rejected(repo_copy, rel, mutate, expected):
    write_recipe(repo_copy, rel, mutate)
    _, errors, _ = build.build(repo_copy)
    assert any(expected in e for e in errors), errors


def test_unquoted_comma_in_flow_mapping_is_caught(repo_copy):
    path = repo_copy / "recipes" / "et" / "misir-wot.yaml"
    text = path.read_text()
    assert 'prep: "very finely chopped"' in text
    path.write_text(text.replace('prep: "very finely chopped"', "prep: peeled, very finely chopped"))
    _, errors, _ = build.build(repo_copy)
    assert any("Additional properties" in e for e in errors)
