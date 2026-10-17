# Globowl recipe database

A structured, credited, diet-aware database of recipes from around the world, built to power
the Globowl app ("cook your way across the globe").

**Now:** 49 recipes from 49 countries on every inhabited continent. See
[`dist/coverage.md`](dist/coverage.md).

## For the app: consume `dist/`

| File | Contents |
|---|---|
| `dist/recipes.json` | `{schema_version, count, recipes[]}` — every recipe, enriched with country name, continent, subregion, total time, ingredient names and derived `dietary` data |
| `dist/countries.json` | 238 countries and territories with ISO code, UN continent and subregion, and status (193 UN members, 2 observers, 3 others, 40 culinarily distinct territories) |
| `dist/ingredients.json` | The ingredient catalog (names, aliases, categories, allergen flags) |
| `dist/coverage.md` | Coverage and quality report |

Useful keys for app features:

- **Passport and map:** `origin.country` (plus `origin.also_claimed_by`) → stamp a country; `origin.continent` / `subregion` → milestones.
- **Journeys:** `dish_types`, `techniques`, `difficulty`, `occasions`, `origin.subregion`.
- **Filters:** `dietary.tags` (strict yes), `dietary.diets[*].status` (`yes` / `adaptable` / `check-labels` / `no`), `dietary.allergens`.
- **Pantry matching:** `ingredient_groups[].items[].ingredient` ids, with `optional` and `alt`.
- **Trust badges:** `review.status`, `review.cultural_review`, `credit.ai_assisted`.
- **Credit line:** `credit.contributors`, `credit.adapted_from`, `credit.dataset`, `credit.license`.

`id` is stable — key on it.

## Repository layout

```
recipes/<cc>/<slug>.yaml   one recipe per file (authored)
data/ingredients.yaml      ingredient catalog with allergen and animal-source flags
data/taxonomy.yaml         controlled vocabularies (units, courses, techniques, licences…)
data/countries.yaml        ISO countries with UN M49 regions
schema/recipe.schema.json  JSON Schema for authored recipes
tools/build.py             validator and builder → dist/
templates/                 starting point for a new recipe
docs/                      design docs (start here)
```

## Docs

- [Recipe structure](docs/recipe-structure.md) — every field and why it exists
- [Dietary tags and allergens](docs/dietary-tags.md) — how tags are derived, plus the deliberate edge cases
- [Credit and licensing](docs/credit-and-licensing.md) — source types, contributor roles, what you can import
- [Expansion plan](docs/expansion-plan.md) — how to get from 49 to 195 countries, and from one dish to many

## Adding a recipe

```bash
pip install -r requirements.txt
cp templates/recipe.template.yaml recipes/gh/kelewele.yaml   # edit it
python3 tools/build.py           # validates everything and rebuilds dist/
python3 -m pytest -q             # rules for dietary derivation and validation
```

The build tells you exactly what's wrong (unknown ingredient, a missing credit field, a
mismatched id). New ingredients go in `data/ingredients.yaml` with correct allergen flags.

## Status of the seed data

All 49 recipes have `credit.ai_assisted: true` and `review.status: draft`. They were written
from general culinary knowledge, not copied from any source, but nobody has cooked them yet.
Review and test them before showing them as trusted.
