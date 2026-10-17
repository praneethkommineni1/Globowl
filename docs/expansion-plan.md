# Expansion plan: from 49 countries to the whole world

Current state: see [`dist/coverage.md`](../dist/coverage.md). Hand-written recipes cover
185 of 195 sovereign states with one dish each. Every hand-written recipe is an unreviewed AI
draft (`review.status: draft`).

**Still missing (10):** Central African Republic, Equatorial Guinea, Vatican City, Solomon
Islands, Kiribati, Marshall Islands, Federated States of Micronesia, Nauru, Palau and Tuvalu.
These were left empty on purpose. Published information about their home cooking is thin, and a
guessed recipe would be worse than none, so source them from people with first-hand knowledge.
Vatican City has no distinct cuisine of its own; the app could show it as "see Italy".

The goal isn't simply "more recipes". It's **every country well represented, with recipes
people can actually cook and trust**. That needs several sources working together.

## Phase 1 — Breadth: one dish for every country

1. **Build the target list from Wikidata (CC0).** Query dishes with a "country of origin"
   (P495) and an English Wikipedia article. That gives a ranked list of notable dishes per
   country, with native names and Q-ids. Store it as `data/dish-candidates.yaml` and use it to
   pick each country's signature dishes.
2. **Fill gaps in coverage order.** `coverage.md` lists the missing states by subregion.
   Prioritise:
   - large or diaspora-rich cuisines first (Pakistan, Bangladesh, Colombia, Haiti, Somalia, Afghanistan…);
   - then whole subregions, so journeys work (Central Asia, the Caribbean, Middle Africa, Micronesia).
3. **Draft, then review.** Draft with AI from the candidate list into the template. Each
   draft stays `draft` until an editor reviews it, and gets a `cultural_review` badge only from
   someone of that cuisine.
4. **Use the gaps for outreach.** "We don't have a single recipe from Burkina Faso yet" is a
   compelling call for contributors.

Target: 195 / 195 states with at least one `reviewed` recipe.

## Phase 2 — Depth: five or more dishes per country

One dish per country is a checklist; five is a cuisine. Per country, aim for:

- a staple (rice, bread, porridge), a main, a vegetable or vegetarian dish, a sweet, and a festive dish;
- a mix of difficulty levels (at least one difficulty 1–2 recipe for first-timers);
- regional variety for big countries (India, China, the US, Brazil, Nigeria and Indonesia
  deserve dozens of dishes, keyed by `origin.region`).

`coverage.md` already reports by course and difficulty; extend it to per-country depth once
the counts grow.

## Phase 3 — Community: real cooks, real stories

- **Submission form** that writes this schema directly: structured ingredient picker (search
  the catalog, with aliases), steps, story, photos, and the credit fields. New ingredients go to
  a moderation queue for catalog review.
- **Family recipes** (`source_type: family`) are the most valuable and least available
  content. Run themed drives ("Grandma's recipe month", diaspora communities, Ramadan,
  Lunar New Year).
- **Cook logs → `tested_count`.** Every "I made this" with a photo and rating is evidence. Auto-
  promote `reviewed` → `tested` after N good cook logs.
- **Cultural reviewers.** Recruit one or two trusted reviewers per cuisine, credited as
  `culturally-reviewed-by`.
- **Partners.** Cooking schools, cultural associations, embassies and tourism boards often
  want to share their food, and can license recipes and photos.

## Phase 4 — Imports (with licence discipline)

- **Wikibooks Cookbook** (CC BY-SA). Write an importer that parses the recipe pages, maps
  ingredients to catalog ids (fuzzy match on name and aliases, unmatched lines go to a review
  queue), and records `source_type: imported` with the page URL and revision.
- **TheMealDB** for development seeding only, unless a production licence is bought.
- Every importer must produce records that pass `tools/build.py`. Nothing goes around the gate.

### Status of the importers

- **Wikibooks:** `tools/import_wikibooks.py`.
  - `fetch` crawls `Category:Recipes by origin` and caches page wikitext to
    `imports/wikibooks/cache/`. It is resumable and deliberately slow: Wikimedia rate-limits
    hard, and cloud egress IPs are shared.
  - `convert` is offline. It promotes a page into `recipes/` only if every required fact is
    present in the source and every ingredient maps to the catalog. Everything else goes to
    `imports/wikibooks/review/` with its issues listed.
  - `imports/wikibooks/report.md` ranks the unmapped ingredients, so the catalog can grow where
    it matters most.
- **First Wikibooks run (2026-10-17):** of 1,850 pages, 85 were promoted and 1,764 queued.
  The main blockers are facts missing from the source: about 1,170 pages give no time and
  about 1,030 give no servings. Filling those in from the review queue is the cheapest way to
  add recipes.
- **Wikidata:** `tools/wikidata_dishes.py` writes `data/dish-candidates.yaml`: the best-known
  dishes per country, ranked by how many Wikipedia language editions cover them.
- **TheMealDB:** not imported (see the licensing doc).

Wikibooks quality varies. Some recent pages look machine-generated and contain plainly wrong
advice, e.g. "for a vegan version, omit the vegetable oil" on an already-vegan stew. Every
imported recipe starts as `draft` and `authenticity: unassessed`.

## Catalog growth

The ingredient catalog is the backbone. As it grows:

- add `aliases` aggressively (UK and US names, transliterations, regional names); this is what
  makes search and pantry matching work worldwide;
- add `substitutes` at the catalog level, e.g. "galangal → ginger + lime zest", so the app can
  suggest swaps for hard-to-find ingredients even when a recipe doesn't list an `alt`;
- link `fdc_id` (USDA FoodData Central) for nutrition;
- consider an `availability` hint (common / specialty store / online only), which powers
  "recipes you can make without a special shop".

## Quality gates (already enforced by `tools/build.py`)

- Schema-valid structure, with no unknown fields.
- Every ingredient, unit, technique, course, licence and contributor role is a known id.
- File path matches id and country.
- Credit rules: `adapted` needs a source, `imported` needs a dataset, `family` needs a `recipe-by` contributor.
- Dietary data can't be hand-authored.
- `dist/` must be rebuilt (CI `--check`).
