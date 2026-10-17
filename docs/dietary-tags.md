# Dietary tags and allergens

Dietary information is **computed** from the ingredient catalog at build time. Authors never
write tags by hand. A hand-maintained "vegan" tag goes wrong the moment someone adds butter
to a recipe; a derived one can't.

## How it works

Each ingredient in `data/ingredients.yaml` declares:

- `animal` — animal sources: `meat`, `poultry`, `fish`, `shellfish`, `dairy`, `egg`, `honey`, `gelatin`
- `contains` — allergens it always contains, plus the non-allergen markers `pork`, `alcohol`, `animal-rennet`
- `may_contain` — things that depend on the brand or recipe (soy sauce and gluten, cheese and rennet, stock and celery)

For each diet, every ingredient line in a recipe is checked:

| Line… | Effect |
|---|---|
| doesn't conflict | — |
| conflicts and is `optional` | diet becomes **adaptable**: "omit X" |
| conflicts but has a compliant `alt` | diet becomes **adaptable**: "use Y instead of X" |
| *may* conflict (`may_contain`) | diet becomes **check-labels**: "check X" |
| conflicts with no way out | diet is **no**, with `because: [X]` |

The worst result wins: `no` beats `adaptable`, which beats `check-labels`, which beats `yes`.
Only `yes` diets appear in the flat `tags` list. Apps should still show `adaptable` diets, since
"vegan with one swap" is a great prompt to try a dish.

```json
"dietary": {
  "tags": ["pescatarian", "gluten-free", "dairy-free", "egg-free", "nut-free", "pork-free", "alcohol-free"],
  "diets": {
    "vegan":       {"status": "adaptable", "changes": ["omit smoked fish"]},
    "vegetarian":  {"status": "adaptable", "changes": ["omit smoked fish"]},
    "pescatarian": {"status": "yes"},
    "gluten-free": {"status": "yes"}
  },
  "allergens": {"contains": [], "may_contain": [], "in_optional_ingredients": ["fish"]}
}
```

## Diets

| Diet | Excludes |
|---|---|
| vegan | any animal source, including honey |
| vegetarian | meat, poultry, fish, shellfish, gelatin, animal rennet |
| pescatarian | meat, poultry, gelatin, animal rennet |
| gluten-free | gluten-containing cereals |
| dairy-free | milk and milk products (butter, ghee, cheese, yogurt) |
| egg-free | eggs |
| nut-free | peanuts and tree nuts |
| pork-free | pork and pork products (lard, bacon, most chorizo) |
| alcohol-free | alcohol as an ingredient (wine, mirin, vanilla extract) |

### Deliberate choices

- **Animal rennet.** Pecorino Romano and Parmigiano Reggiano require animal rennet under their
  PDO rules, so they make a dish not vegetarian. Most other cheeses are `may_contain`, which
  gives "check labels".
- **No "halal" or "kosher" tag.** Those depend on certification and preparation (slaughter,
  separation of meat and dairy), not just ingredients. We provide the inputs people use to
  decide (`pork-free`, `alcohol-free`) and don't claim more than we know.
- **Coconut is not a tree nut.** The EU doesn't regulate it as one, and the US FDA removed it
  from its tree-nut list in 2025. The app may still want to show a note to nut-allergic users.
- **Oats are `may_contain: gluten`.** They are only safe when certified gluten-free.
- **Sugar is vegan.** Some cane sugar is refined with bone char. The catalog notes this rather
  than failing every dessert.

### Allergens

The 14 EU-regulated allergens, which also cover the US "big 9": gluten, crustacean, mollusc,
egg, fish, peanut, tree-nut, soy, milk, celery, mustard, sesame, sulphite, lupin.

## Safety wording for the app

Derived tags are only as good as the catalog, and brands vary. The app should:

- label these as "based on ingredients" rather than "certified";
- always show `check-labels` items to users who filter by that diet or allergen;
- never hide `may_contain` allergens behind a "yes".

## Fixing a wrong tag

Fix the **ingredient**, not the recipe. Every recipe using it is corrected at once, and
`tests/test_build.py` documents the rules. `dietary_overrides` exists for genuine one-offs, e.g.
a recipe that specifies certified gluten-free oats. It requires a written `reason`.

## Future: nutrition

Linking each catalog entry to a USDA FoodData Central id (public domain) would let the build
estimate calories and macros per serving from the same structured quantities.
