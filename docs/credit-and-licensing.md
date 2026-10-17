# Credit and licensing

Globowl's value is a large database of *real* dishes from *real* places. That only works if
the people and communities behind those dishes are credited, and if we have the right to
publish what we publish.

> This is a practical policy, not legal advice. Have a lawyer review the contributor terms and
> the database licence before launch.

## What is and isn't protected

- **Dishes and ingredient lists are generally not copyrightable.** No one owns jollof rice, and
  a list of ingredients with quantities is treated as facts in the US and most other places.
- **The written method, headnotes, stories and photos are.** Copying a blog's instructions or
  photos is infringement, even with credit.
- **Databases can be protected as a whole.** The EU has a separate database right, so bulk
  copying from someone else's collection is risky even if each recipe is factual.

So: re-writing a recipe in our own words, with our own structure, is fine. Copying text or
photos needs a licence. Bulk-importing a collection needs that collection's licence.

## Source types

Every recipe has `credit.source_type`:

| Type | When | Must include |
|---|---|---|
| `traditional` | A well-known traditional dish written up fresh by a Globowl contributor. | A `written-by` contributor. |
| `family` | A family or personal recipe shared by its keeper. | A `recipe-by` contributor: the cook (e.g. "Ama Owusu's grandmother, Kumasi"), with their consent. |
| `original` | A new creation. | The creator. |
| `adapted` | Based on a published recipe. The method must be rewritten. | `adapted_from` with title, author, URL and what changed. |
| `imported` | From an open dataset under its licence. | `dataset` with name, record id, URL and licence. |

### Contributor roles

`recipe-by`, `written-by`, `adapted-by`, `translated-by`, `tested-by`,
`culturally-reviewed-by`, `edited-by`, `photographed-by`. Several people can be credited.
Showing them all on the recipe page (e.g. "Recipe by Fatima's mother · Translated by Fatima ·
Tested by 14 Globowl cooks") is itself an incentive to contribute.

### AI assistance

`credit.ai_assisted: true` marks text that an AI drafted or substantially wrote. The 49 seed
recipes are marked this way and have `review.status: draft`. They are written from general
culinary knowledge, not copied from any source, but **no person has cooked or checked them
yet**. Recommendation: show AI-drafted recipes only once they reach `reviewed`, and badge them
until someone from that cuisine has done a `cultural_review`.

## Licences

Each recipe has a `credit.license` from `taxonomy.licenses`:

- **`CC-BY-4.0`** — the current default for Globowl-written recipes. Anyone may reuse it with
  credit. Good for reach and goodwill.
- **`CC-BY-SA-4.0`** — needed for anything imported from CC BY-SA sources such as Wikibooks.
  Derivatives must stay under the same licence.
- **`CC0-1.0`** — public domain.
- **`contributor-grant`** — a contributor grants Globowl a licence but not the public.

**Decision (2026-10-17): Globowl-written recipes are CC BY 4.0.** This makes the database a
public good that partners can build on. Contributors submitting their own recipes must accept
contributor terms that license their submission under CC BY 4.0. Changing the licence later
requires contributors' consent.

Media (photos) carry their own `credit` and `license`, separate from the recipe text.

## External sources — what's usable

Verify current terms before importing anything; they change. TheMealDB's terms were
re-checked on 2026-10-17; the other rows are as last known.

| Source | What it offers | Licence / terms (as last known) | Use it for |
|---|---|---|---|
| **Wikidata** | Dish items with country of origin, native names, images, links to Wikipedia in many languages | CC0 | The master list of dishes to cover; `wikidata` ids for dedup; native names. **Highest-value source.** |
| **Wikibooks Cookbook** | Several thousand recipes, many by cuisine | CC BY-SA 4.0 | Importing, with attribution and share-alike. |
| **Wikimedia Commons** | Food photos | Per file (CC BY, CC BY-SA, PD) | Images, with per-file credit. |
| **TheMealDB** | Around 300 recipes tagged by "area" | Test key `1` for development and educational use only; a publicly released app needs their paid supporter key; reselling the API is prohibited (checked 2026-10-17) | **Not imported.** Copying its records into a shipped database counts as production use. Revisit only if you buy a production key and its terms allow storing records. |
| **USDA FoodData Central** | Nutrition data | Public domain | Linking catalog ingredients for nutrition estimates. |
| **Open Food Facts** | Product ingredients and allergens | ODbL (database), share-alike | Checking brand-dependent `may_contain` flags. |
| **RecipeNLG / Food.com dumps** | Millions of scraped recipes | Non-commercial research only, or unclear | **Avoid** for a commercial product. |
| **Recipe blogs and cookbooks** | Great recipes | All rights reserved | Only as `adapted` with a rewritten method, or by permission and partnership. |

## Checklist before a recipe is published

- [ ] `source_type` matches how the recipe was obtained.
- [ ] Every person who contributed is credited with their consent.
- [ ] Adapted recipes: the method is in our own words and the source is cited.
- [ ] Imported recipes: the dataset licence allows our use and is recorded.
- [ ] Every photo has its own credit and licence.
- [ ] `ai_assisted` is set honestly.
