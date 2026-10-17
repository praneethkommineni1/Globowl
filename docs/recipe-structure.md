# Recipe structure

Each recipe is one YAML file at `recipes/<cc>/<slug>.yaml`, where `<cc>` is the lower-case
ISO 3166-1 code of the dish's country of origin. The formal contract is
[`schema/recipe.schema.json`](../schema/recipe.schema.json); `tools/build.py` adds checks the
schema can't express (vocabularies, ingredient ids, credit rules). Copy
[`templates/recipe.template.yaml`](../templates/recipe.template.yaml) to start a new one.

## Design principles

1. **Structured ingredients, not strings.** Every ingredient line points to an id in
   `data/ingredients.yaml` and has a numeric `qty` and a `unit`. This makes scaling, unit
   conversion, shopping lists, "what can I cook with my pantry" and dietary tagging possible.
   A free-text line like "2 cups flour, sifted" can't do any of that.
2. **Derive, don't declare.** Dietary tags, allergens, total time and region are computed at
   build time. Authors can't get them wrong or let them drift out of date.
3. **Credit is required.** No recipe builds without a source type, at least one named
   contributor and a licence. See [credit-and-licensing.md](credit-and-licensing.md).
4. **Honest provenance.** `authenticity`, `review.status` and `credit.ai_assisted` tell readers
   how traditional the recipe is, whether a person has checked it, and who wrote it.
5. **Controlled vocabularies.** Courses, units, techniques, allergens and licences come from
   `data/taxonomy.yaml`, so filters stay consistent across thousands of recipes.

## Fields

| Field | Required | Notes |
|---|---|---|
| `id` | ✓ | `<cc>-<slug>`; must match the file path. Stable forever — the app should key on it. |
| `title` | ✓ | The name most English-speaking cooks would search for. |
| `native_name` | | `{text, lang, romanized}` — the name in its own script, with a BCP 47 language tag. |
| `alternate_names` | | Other names for search. |
| `summary` | ✓ | 20–280 characters; one appetising sentence. |
| `origin.country` | ✓ | ISO alpha-2. The build adds country name, continent and UN subregion. |
| `origin.region` / `origin.community` | | Where within the country, and whose dish (e.g. Cape Malay, Louisiana Creole). |
| `origin.also_claimed_by` | | Countries where the dish is equally at home, or that dispute its origin (jollof, pavlova). Lets the app show the dish on more than one passport. |
| `wikidata` | | Wikidata Q-id of the dish — the best key for deduplicating and linking. |
| `course` | ✓ | From `taxonomy.courses`. |
| `dish_types` | | Free-form kebab-case (`dumpling`, `flatbread`, `stew`). Powers "dumplings of the world"-style journeys. |
| `occasions` | | Holidays and occasions — for seasonal recommendations. |
| `authenticity` | ✓ | `traditional`, `home-style`, `regional-variant`, `diaspora`, `fusion`, `modern`. |
| `yield` | ✓ | `servings` and/or `amount` ("about 40 pierogi"). |
| `time` | ✓ | `prep_min`, `cook_min`, `inactive_min` (soaking, marinating, rising). The build adds `total_min`. |
| `difficulty` | ✓ | 1–5. 1 = anyone; 3 = needs attention (emulsions, flipping a tortilla); 5 = real practice. |
| `equipment`, `techniques` | | Techniques come from `taxonomy.techniques` — used for skill-based journeys. |
| `ingredient_groups` | ✓ | Ordered groups (`name` optional) of ingredient lines; see below. |
| `steps` | ✓ | Plain strings, or `{text, timer_min, section}` when a step has a meaningful timer. |
| `tips`, `serving`, `culture` | | Cooking tips, how the dish is eaten, and its story. `culture` is what makes a dish feel like a place. |
| `credit` | ✓ | See credit doc. |
| `media` | | Images, each with its own `credit` and `license`. |
| `review` | ✓ | `status` (`draft` → `reviewed` → `tested`), `tested_count`, `cultural_review`. |
| `dietary_overrides` | | Rare escape hatch; requires a `reason`. |

### Ingredient lines

```yaml
- {ingredient: chicken-stock, qty: 750, unit: ml, alt: [vegetable-stock]}
- {ingredient: scotch-bonnet, qty: [1, 2], note: to taste}
- {ingredient: smoked-fish, qty: 50, unit: g, prep: flaked, optional: true}
- {ingredient: salt, note: to taste}
```

- `qty` is a number or a `[min, max]` range. Omit both `qty` and `unit` for "to taste".
- Omit `unit` for counted items ("2 eggs"). A `unit` without a `qty` is rejected.
- Prefer metric mass and volume. The app converts for display.
- `prep` describes what to do to the ingredient; `note` holds everything else.
- `optional` and `alt` are what make a recipe **adaptable**: "vegan if you omit the smoked fish".
- **Quote any `prep` or `note` containing a comma.** In YAML flow mappings, an unquoted
  comma starts a new key. The schema rejects the result, so the build will tell you.

## Build output (`dist/`)

`python3 tools/build.py` writes:

- `dist/recipes.json` — `{schema_version, count, recipes: [...]}`. Each recipe is the authored
  data plus:
  - `origin.country_name`, `origin.continent`, `origin.subregion`
  - `time.total_min`
  - `name` on every ingredient line
  - `steps` normalised to objects
  - a `dietary` block (see [dietary-tags.md](dietary-tags.md))
- `dist/ingredients.json`, `dist/countries.json` — the reference data.
- `dist/coverage.md` — progress by continent, diet, course and the list of countries still missing.

`dist/` is committed so the app can consume it directly. CI runs `tools/build.py --check` to
make sure it is never stale.
