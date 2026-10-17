#!/usr/bin/env python3
"""Validate the Globowl recipe database and build the app-ready output.

    python3 tools/build.py            # validate, then write dist/
    python3 tools/build.py --check    # validate and fail if dist/ is out of date (for CI)

Authored sources live in recipes/<cc>/<slug>.yaml and data/*.yaml. Dietary data
is derived here from the ingredient catalog; it is never hand-written.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

DIET_IDS = ["vegan", "vegetarian", "pescatarian", "gluten-free", "dairy-free",
            "egg-free", "nut-free", "pork-free", "alcohol-free"]

# Which ingredient flags break which diet. `animal` is matched against an
# ingredient's animal sources; `markers` against its contains / may_contain.
DIET_RULES = {
    "vegan":        {"animal": {"meat", "poultry", "fish", "shellfish", "dairy", "egg", "honey", "gelatin"}},
    "vegetarian":   {"animal": {"meat", "poultry", "fish", "shellfish", "gelatin"}, "markers": {"animal-rennet"}},
    "pescatarian":  {"animal": {"meat", "poultry", "gelatin"}, "markers": {"animal-rennet"}},
    "gluten-free":  {"markers": {"gluten"}},
    "dairy-free":   {"markers": {"milk"}},
    "egg-free":     {"markers": {"egg"}},
    "nut-free":     {"markers": {"peanut", "tree-nut"}},
    "pork-free":    {"markers": {"pork"}},
    "alcohol-free": {"markers": {"alcohol"}},
}
NON_ALLERGEN_MARKERS = {"pork", "alcohol", "animal-rennet"}


class BuildError(Exception):
    pass


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_reference(root: Path):
    taxonomy = load_yaml(root / "data" / "taxonomy.yaml")
    countries = {c["code"]: c for c in load_yaml(root / "data" / "countries.yaml")}
    ingredients = load_yaml(root / "data" / "ingredients.yaml")
    return taxonomy, countries, ingredients


def check_ingredients(ingredients: dict, taxonomy: dict) -> list[str]:
    errors = []
    markers = set(taxonomy["allergens"]) | NON_ALLERGEN_MARKERS
    for iid, ing in ingredients.items():
        where = f"data/ingredients.yaml: {iid}"
        if not isinstance(ing, dict) or "name" not in ing or "category" not in ing:
            errors.append(f"{where}: needs at least name and category")
            continue
        unknown_keys = set(ing) - {"name", "category", "animal", "contains", "may_contain", "aliases", "note"}
        if unknown_keys:
            errors.append(f"{where}: unknown keys {sorted(unknown_keys)}")
        if ing["category"] not in taxonomy["ingredient_categories"]:
            errors.append(f"{where}: unknown category {ing['category']!r}")
        for a in ing.get("animal", []):
            if a not in taxonomy["animal_sources"]:
                errors.append(f"{where}: unknown animal source {a!r}")
        for key in ("contains", "may_contain"):
            for m in ing.get(key, []):
                if m not in markers:
                    errors.append(f"{where}: unknown {key} marker {m!r}")
        # Consistency between animal source and allergen markers.
        animal = set(ing.get("animal", []))
        contains = set(ing.get("contains", []))
        if "dairy" in animal and "milk" not in contains:
            errors.append(f"{where}: dairy ingredient must list `milk` in contains")
        if "egg" in animal and "egg" not in contains:
            errors.append(f"{where}: egg ingredient must list `egg` in contains")
        if "fish" in animal and "fish" not in contains:
            errors.append(f"{where}: fish ingredient must list `fish` in contains")
        if "shellfish" in animal and not contains & {"crustacean", "mollusc"}:
            errors.append(f"{where}: shellfish must list crustacean or mollusc in contains")
    return errors


def line_violation(ing: dict, diet: str) -> str | None:
    """Return 'contains', 'may' or None for one ingredient against one diet."""
    rule = DIET_RULES[diet]
    markers = rule.get("markers", set())
    if set(ing.get("animal", [])) & rule.get("animal", set()) or set(ing.get("contains", [])) & markers:
        return "contains"
    if set(ing.get("may_contain", [])) & markers:
        return "may"
    return None


def derive_dietary(recipe: dict, ingredients: dict) -> dict:
    lines = [ln for g in recipe["ingredient_groups"] for ln in g["items"]]
    diets = {}
    for diet in DIET_IDS:
        blocking, changes, check = [], [], []
        for ln in lines:
            ing = ingredients[ln["ingredient"]]
            v = line_violation(ing, diet)
            if v is None:
                continue
            name = ing["name"]
            if v == "may":
                check.append(name)
                continue
            ok_alts = [a for a in ln.get("alt", []) if line_violation(ingredients[a], diet) is None]
            if ln.get("optional"):
                changes.append(f"omit {name}")
            elif ok_alts:
                changes.append(f"use {ingredients[ok_alts[0]]['name']} instead of {name}")
            else:
                blocking.append(name)
        if blocking:
            entry = {"status": "no", "because": sorted(set(blocking))}
        elif changes:
            entry = {"status": "adaptable", "changes": list(dict.fromkeys(changes))}
            if check:
                entry["check"] = sorted(set(check))
        elif check:
            entry = {"status": "check-labels", "check": sorted(set(check))}
        else:
            entry = {"status": "yes"}
        diets[diet] = entry

    for diet, ov in (recipe.get("dietary_overrides") or {}).items():
        diets[diet] = {"status": ov["status"], "override_reason": ov["reason"]}

    contains, may, optional_only = set(), set(), set()
    for ln in lines:
        ing = ingredients[ln["ingredient"]]
        allergens = set(ing.get("contains", [])) - NON_ALLERGEN_MARKERS
        target = optional_only if ln.get("optional") else contains
        target |= allergens
        may |= set(ing.get("may_contain", [])) - NON_ALLERGEN_MARKERS
    may -= contains
    optional_only -= contains
    return {
        "tags": [d for d in DIET_IDS if diets[d]["status"] == "yes"],
        "diets": diets,
        "allergens": {
            "contains": sorted(contains),
            "may_contain": sorted(may),
            "in_optional_ingredients": sorted(optional_only),
        },
    }


def check_recipe(path: Path, recipe: dict, ref, validator) -> list[str]:
    taxonomy, countries, ingredients = ref
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    errors = [f"{rel}: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
              for e in validator.iter_errors(recipe)]
    if errors:
        return errors  # semantic checks assume a structurally valid recipe

    def err(msg):
        errors.append(f"{rel}: {msg}")

    cc = recipe["origin"]["country"]
    expected_id = f"{path.parent.name}-{path.stem}"
    if recipe["id"] != expected_id:
        err(f"id {recipe['id']!r} must be {expected_id!r} (from its path)")
    if path.parent.name != cc.lower():
        err(f"file is in recipes/{path.parent.name}/ but origin.country is {cc}")
    if cc not in countries:
        err(f"unknown country {cc}")
    for c in recipe["origin"].get("also_claimed_by", []):
        if c not in countries:
            err(f"unknown country in also_claimed_by: {c}")

    def vocab(value, table, label):
        if value not in taxonomy[table]:
            err(f"unknown {label} {value!r} (add it to data/taxonomy.yaml → {table})")

    vocab(recipe["course"], "courses", "course")
    vocab(recipe["authenticity"], "authenticity", "authenticity")
    for t in recipe.get("techniques", []):
        vocab(t, "techniques", "technique")
    vocab(recipe["review"]["status"], "review_statuses", "review status")

    for g in recipe["ingredient_groups"]:
        for ln in g["items"]:
            iid = ln["ingredient"]
            if iid not in ingredients:
                err(f"unknown ingredient {iid!r} (add it to data/ingredients.yaml)")
            for a in ln.get("alt", []):
                if a not in ingredients:
                    err(f"unknown alt ingredient {a!r}")
            if "unit" in ln:
                vocab(ln["unit"], "units", "unit")
                if "qty" not in ln:
                    err(f"{iid}: a unit needs a qty")
            q = ln.get("qty")
            if isinstance(q, list) and q[0] >= q[1]:
                err(f"{iid}: range {q} must be [min, max] with min < max")

    credit = recipe["credit"]
    vocab(credit["source_type"], "source_types", "source type")
    vocab(credit["license"], "licenses", "license")
    for c in credit["contributors"]:
        vocab(c["role"], "contributor_roles", "contributor role")
    st = credit["source_type"]
    if st == "adapted" and not credit.get("adapted_from"):
        err("source_type adapted requires credit.adapted_from")
    if st == "imported" and not credit.get("dataset"):
        err("source_type imported requires credit.dataset")
    if st == "family" and not any(c["role"] == "recipe-by" for c in credit["contributors"]):
        err("source_type family requires a contributor with role recipe-by")
    for m in recipe.get("media", []):
        vocab(m["license"], "licenses", "media license")

    for diet in recipe.get("dietary_overrides") or {}:
        if diet not in DIET_IDS:
            err(f"dietary_overrides: unknown diet {diet!r}")
    return errors


def enrich(recipe: dict, ref) -> dict:
    taxonomy, countries, ingredients = ref
    out = dict(recipe)
    c = countries[recipe["origin"]["country"]]
    out["origin"] = {**recipe["origin"], "country_name": c["name"],
                     "continent": c["continent"], "subregion": c["subregion"]}
    t = recipe["time"]
    if "total_min" not in t:
        t = {**t, "total_min": t["prep_min"] + t["cook_min"] + t.get("inactive_min", 0)}
    out["time"] = t
    out["ingredient_groups"] = [
        {**g, "items": [{**ln, "name": ingredients[ln["ingredient"]]["name"]} for ln in g["items"]]}
        for g in recipe["ingredient_groups"]
    ]
    out["steps"] = [s if isinstance(s, dict) else {"text": s} for s in recipe["steps"]]
    out.pop("dietary_overrides", None)
    out["dietary"] = derive_dietary(recipe, ingredients)
    return out


def coverage_report(built: list[dict], countries: dict) -> str:
    target = {k: v for k, v in countries.items() if v["status"] in ("un-member", "un-observer")}
    covered = Counter(r["origin"]["country"] for r in built)
    lines = ["# Coverage report", "",
             "Generated by `tools/build.py` — do not edit by hand.", "",
             f"**{len(built)} recipes** from **{len(covered)} countries/territories**. "
             f"Covers **{len(set(covered) & set(target))} of {len(target)}** sovereign states "
             f"(193 UN members + 2 observers).", "",
             "## By continent", "",
             "| Continent | States covered | Recipes |", "|---|---|---|"]
    by_cont = defaultdict(list)
    for code, c in target.items():
        by_cont[c["continent"]].append(code)
    for cont in sorted(by_cont):
        codes = by_cont[cont]
        n_cov = sum(1 for c in codes if c in covered)
        n_rec = sum(1 for r in built if r["origin"]["continent"] == cont)
        lines.append(f"| {cont} | {n_cov} / {len(codes)} | {n_rec} |")

    lines += ["", "## Diets (recipes that qualify as written)", "", "| Diet | Yes | Adaptable | Check labels |", "|---|---|---|---|"]
    for d in DIET_IDS:
        s = Counter(r["dietary"]["diets"][d]["status"] for r in built)
        lines.append(f"| {d} | {s['yes']} | {s['adaptable']} | {s['check-labels']} |")

    lines += ["", "## Courses", ""]
    for course, n in Counter(r["course"] for r in built).most_common():
        lines.append(f"- {course}: {n}")
    lines += ["", "## Difficulty", ""]
    for d, n in sorted(Counter(r["difficulty"] for r in built).items()):
        lines.append(f"- {d}: {n}")
    lines += ["", "## Review status", ""]
    for s, n in Counter(r["review"]["status"] for r in built).most_common():
        lines.append(f"- {s}: {n}")

    lines += ["", "## Sovereign states with no recipe yet", ""]
    missing = defaultdict(list)
    for code, c in target.items():
        if code not in covered:
            missing[(c["continent"], c["subregion"])].append(c["name"])
    for (cont, sub) in sorted(missing):
        lines.append(f"- **{sub}** ({cont}): {', '.join(sorted(missing[(cont, sub)]))}")
    return "\n".join(lines) + "\n"


def build(root: Path = ROOT):
    """Return (outputs: dict[relative path -> text], errors, warnings)."""
    ref = load_reference(root)
    taxonomy, countries, ingredients = ref
    errors = check_ingredients(ingredients, taxonomy)
    warnings = []
    schema = json.loads((root / "schema" / "recipe.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    recipes, seen = [], {}
    for path in sorted((root / "recipes").glob("*/*.yaml")):
        try:
            recipe = load_yaml(path)
        except yaml.YAMLError as e:
            errors.append(f"{path}: YAML error: {e}")
            continue
        errs = check_recipe(path, recipe, ref, validator)
        errors += errs
        if errs:
            continue
        if recipe["id"] in seen:
            errors.append(f"{path}: duplicate id {recipe['id']} (also in {seen[recipe['id']]})")
            continue
        seen[recipe["id"]] = path
        recipes.append(recipe)
    if errors:
        return {}, errors, warnings

    used = {ln["ingredient"] for r in recipes for g in r["ingredient_groups"] for ln in g["items"]}
    used |= {a for r in recipes for g in r["ingredient_groups"] for ln in g["items"] for a in ln.get("alt", [])}
    unused = sorted(set(ingredients) - used)
    if unused:
        warnings.append(f"{len(unused)} catalog ingredients unused: {', '.join(unused)}")

    built = [enrich(r, ref) for r in recipes]
    dump = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    outputs = {
        "recipes.json": dump({"schema_version": 1, "count": len(built), "recipes": built}),
        "ingredients.json": dump(ingredients),
        "countries.json": dump(list(countries.values())),
        "coverage.md": coverage_report(built, countries),
    }
    return outputs, errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if dist/ is not up to date")
    args = ap.parse_args(argv)

    outputs, errors, warnings = build()
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"\n{len(errors)} error(s)", file=sys.stderr)
        return 1

    if args.check:
        stale = [name for name, text in outputs.items()
                 if not (DIST / name).exists() or (DIST / name).read_text(encoding="utf-8") != text]
        if stale:
            print(f"dist/ is out of date ({', '.join(stale)}); run python3 tools/build.py", file=sys.stderr)
            return 1
        print("OK: sources valid and dist/ up to date")
        return 0

    DIST.mkdir(exist_ok=True)
    for name, text in outputs.items():
        (DIST / name).write_text(text, encoding="utf-8")
    n = json.loads(outputs["recipes.json"])["count"]
    print(f"OK: built {n} recipes into dist/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
