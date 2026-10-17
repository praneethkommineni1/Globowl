#!/usr/bin/env python3
"""Import recipes from the Wikibooks Cookbook (CC BY-SA 4.0) into Globowl's format.

    python3 tools/import_wikibooks.py fetch     # crawl cuisine categories + page wikitext into the cache
    python3 tools/import_wikibooks.py convert   # parse the cache; promote complete recipes, queue the rest

`fetch` is slow on purpose (Wikimedia rate-limits aggressively) and resumable. `convert` is
offline and deterministic, so parser and mapping improvements can be re-run freely.

A recipe is promoted into recipes/<cc>/ only when everything required can be filled from the
source: a mapped country, course, servings, time, difficulty, and every ingredient line
mapped to the catalog. Anything else lands in imports/wikibooks/review/ with the list of
issues, and imports/wikibooks/report.md ranks the unmapped ingredients so the catalog can grow
where it matters. Nothing is invented: missing facts stay missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "imports" / "wikibooks"
CACHE = WORK / "cache"
API = "https://en.wikibooks.org/w/api.php"
UA = "GlobowlBot/0.1 (https://github.com/praneethkommineni1/Globowl; recipe database import)"
LICENSE = "CC-BY-SA-4.0"
ROOT_CATEGORY = "Category:Recipes by origin"


# --- Fetching ----------------------------------------------------------------

class Client:
    def __init__(self, min_interval=3.0):
        self.min_interval, self.last = min_interval, 0.0

    def get(self, **params):
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        url = f"{API}?{urllib.parse.urlencode(params)}"
        for attempt in range(12):
            wait = self.min_interval - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                retry = e.headers.get("Retry-After")
                delay = int(retry) + 2 if retry and retry.isdigit() else 20 * (attempt + 1)
                print(f"  HTTP {e.code}; waiting {delay}s", file=sys.stderr, flush=True)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError) as e:
                print(f"  {e}; retrying", file=sys.stderr, flush=True)
                time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"giving up on {url}")

    def members(self, category):
        out, cont = [], {}
        while True:
            d = self.get(action="query", list="categorymembers", cmtitle=category,
                         cmlimit=500, cmtype="page|subcat", **cont)
            out += d["query"]["categorymembers"]
            if "continue" not in d:
                return out
            cont = d["continue"]


def fetch(max_depth=3):
    CACHE.mkdir(parents=True, exist_ok=True)
    client = Client()
    cats_path = CACHE / "categories.json"
    cats = json.loads(cats_path.read_text()) if cats_path.exists() else {}
    stack = [(ROOT_CATEGORY, 0)]
    while stack:
        cat, depth = stack.pop()
        if depth > max_depth:
            continue
        if cat not in cats:
            ms = client.members(cat)
            cats[cat] = {"pages": [m["title"] for m in ms if m["ns"] == 102],
                         "subcats": [m["title"] for m in ms if m["ns"] == 14]}
            cats_path.write_text(json.dumps(cats, indent=0, ensure_ascii=False))
            print(f"category {len(cats)}: {cat} ({len(cats[cat]['pages'])} pages)", flush=True)
        stack += [(s, depth + 1) for s in cats[cat]["subcats"]]

    pages_path = CACHE / "pages.jsonl"
    have = set()
    if pages_path.exists():
        have = {json.loads(line)["title"] for line in pages_path.open(encoding="utf-8")}
    todo = sorted({p for c in cats.values() for p in c["pages"]} - have)
    print(f"{len(have)} pages cached, {len(todo)} to fetch", flush=True)
    with pages_path.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), 50):
            batch = todo[i:i + 50]
            d = client.get(action="query", prop="revisions|categories", rvprop="content|ids|timestamp",
                           rvslots="main", cllimit="max", titles="|".join(batch))
            for p in d["query"]["pages"]:
                if "revisions" not in p:
                    continue
                rev = p["revisions"][0]
                f.write(json.dumps({
                    "title": p["title"], "pageid": p["pageid"], "revid": rev["revid"],
                    "timestamp": rev["timestamp"], "wikitext": rev["slots"]["main"]["content"],
                    "categories": [c["title"] for c in p.get("categories", [])],
                }, ensure_ascii=False) + "\n")
            f.flush()
            print(f"pages {min(i + 50, len(todo))}/{len(todo)}", flush=True)
    print("fetch complete", flush=True)


# --- Wikitext helpers ----------------------------------------------------------

LINK = re.compile(r"\[\[(?:[Cc]ookbook:)?([^\]|]+)(?:\|([^\]]*))?\]\]")


def strip_templates(text: str) -> str:
    for _ in range(10):
        text, n = re.subn(r"\{\{[^{}]*\}\}", "", text)
        if not n:
            break
    return text


def plain(text: str) -> str:
    """Strip wiki markup to readable plain text."""
    text = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = strip_templates(text)
    text = re.sub(r"__[A-Z]+__", "", text)
    text = re.sub(r"\[\[(?:File|Image|Category):[^\]]*\]\]", "", text, flags=re.I)
    text = LINK.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), text)
    text = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_params(body: str) -> list[str]:
    """Split template parameters on top-level pipes (not those inside [[links]] or {{templates}})."""
    parts, buf, depth, i = [], [], 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1; buf.append(two); i += 2; continue
        if two in ("]]", "}}") and depth:
            depth -= 1; buf.append(two); i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(body[i])
        i += 1
    parts.append("".join(buf))
    return parts


def summary_params(wikitext: str) -> dict:
    """Parameters of the {{recipe summary}} box (also written {{recipesummary}}), keys lower-cased."""
    m = re.search(r"\{\{\s*recipe\s*summary\s*\|", wikitext, flags=re.I)
    out = {}
    if not m:
        return out
    depth, i = 1, m.end()
    while i < len(wikitext) and depth:
        if wikitext.startswith("{{", i):
            depth += 1; i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1; i += 2
        else:
            i += 1
    for part in split_params(wikitext[m.end():i - 2]):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def sections(wikitext: str) -> dict[str, str]:
    """Top-level (==) sections keyed by lower-case heading; '' is the intro."""
    out, current, buf = {}, "", []
    for line in wikitext.splitlines():
        m = re.match(r"^==\s*([^=].*?)\s*==\s*$", line)
        if m:
            out[current] = "\n".join(buf)
            current, buf = m.group(1).strip().lower(), []
        else:
            buf.append(line)
    out[current] = "\n".join(buf)
    return out


def find_section(secs, *names):
    for key, body in secs.items():
        if any(key.startswith(n) for n in names):
            return body
    return None


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_minutes(text: str) -> int | None:
    """Total minutes from a free-text time. Labelled parts ("Prep: 15 min<br>Baking: 50 min") are
    summed; for a range ("50-70 minutes") the lower bound is used."""
    if not text:
        return None
    parts = [p for p in re.split(r"<br\s*/?>|;|\+|\n|,(?=\s*[a-z]+\s*:)", text, flags=re.I) if p.strip()]
    if len(parts) > 1:
        found = [parse_minutes(p) for p in parts]
        found = [f for f in found if f]
        return sum(found) or None
    t = plain(text).lower()
    for k, v in UNICODE_FRACTIONS.items():
        t = re.sub(rf"(\d)\s*{k}", lambda m: str(int(m.group(1)) + float(Fraction(v))), t).replace(k, str(float(Fraction(v))))
    rng = r"(?:\s*(?:-|–|to)\s*\d+(?:\.\d+)?)?"  # ranges: keep the lower bound
    hours = re.search(rf"(\d+(?:\.\d+)?){rng}\s*(?:h|hr|hrs|hour|hours)\b", t)
    mins = re.search(rf"(\d+){rng}\s*(?:m|min|mins|minute|minutes)\b", t)
    if not hours and not mins:
        return None
    total = (float(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
    return int(round(total)) or None


# --- Ingredient lines ----------------------------------------------------------

UNICODE_FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5",
                     "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅙": "1/6", "⅚": "5/6"}
NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
QTY = re.compile(rf"^\s*({NUM})(?:\s*(?:-|–|to)\s*({NUM}))?\s*")

# Words → (unit id or None, multiplier to that unit). None unit means "convert to grams/ml".
UNIT_WORDS = {
    "teaspoon": ("tsp", 1), "teaspoons": ("tsp", 1), "tsp": ("tsp", 1), "t": ("tsp", 1),
    "tablespoon": ("tbsp", 1), "tablespoons": ("tbsp", 1), "tbsp": ("tbsp", 1), "tbs": ("tbsp", 1), "tbl": ("tbsp", 1),
    "cup": ("cup", 1), "cups": ("cup", 1), "c": ("cup", 1),
    "g": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "gramme": ("g", 1), "grammes": ("g", 1),
    "kg": ("kg", 1), "kilogram": ("kg", 1), "kilograms": ("kg", 1),
    "ml": ("ml", 1), "millilitre": ("ml", 1), "milliliter": ("ml", 1), "millilitres": ("ml", 1), "milliliters": ("ml", 1),
    "l": ("l", 1), "litre": ("l", 1), "liter": ("l", 1), "litres": ("l", 1), "liters": ("l", 1),
    "oz": ("g", 28.35), "ounce": ("g", 28.35), "ounces": ("g", 28.35),
    "lb": ("g", 453.6), "lbs": ("g", 453.6), "pound": ("g", 453.6), "pounds": ("g", 453.6),
    "clove": ("clove", 1), "cloves": ("clove", 1), "pinch": ("pinch", 1), "pinches": ("pinch", 1),
    "slice": ("slice", 1), "slices": ("slice", 1), "sprig": ("sprig", 1), "sprigs": ("sprig", 1),
    "stalk": ("stalk", 1), "stalks": ("stalk", 1), "bunch": ("bunch", 1), "bunches": ("bunch", 1),
    "handful": ("handful", 1), "handfuls": ("handful", 1), "can": ("can", 1), "cans": ("can", 1),
    "tin": ("can", 1), "tins": ("can", 1), "leaf": ("leaf", 1), "leaves": ("leaf", 1),
}
FLUID_OZ = re.compile(r"^(?:fl\.?\s*oz|fluid\s+ounces?)\b", re.I)
SIZE_WORDS = {"small", "medium", "large", "big", "extra-large", "heaped", "heaping", "level", "rounded", "generous"}
# Wikibooks link targets that are techniques, units or equipment — never the ingredient.
NON_INGREDIENT_LINKS = {
    "chopping", "chop", "mince", "mincing", "slicing", "slice", "dice", "dicing", "cube", "cubing", "grate",
    "grating", "peel", "peeling", "garnish", "julienne", "crush", "crushing", "zest", "zesting", "boiling",
    "boil", "frying", "fry", "sautéing", "sauteing", "sauté", "simmering", "simmer", "roasting", "baking",
    "whisk", "whisking", "beat", "beating", "sifting", "sift", "mashing", "mash", "puree", "purée",
    "marinating", "marinade", "soaking", "seed", "drain", "rinse", "shred", "shredding", "toast", "toasting",
    "blanching", "steaming", "knead", "kneading", "melt", "melting", "cup", "teaspoon", "tablespoon", "gram",
    "kilogram", "ounce", "pound", "litre", "liter", "millilitre", "milliliter", "pinch", "dash", "can",
    "pots and pans", "knife", "cutting board", "frying pan", "saucepan", "measuring cup", "units of measurement",
    "g", "kg", "ml", "l", "quart", "pint", "inch", "tsp", "tbsp", "liter", "litre", "gallon", "grater", "ingredients",
    "fluid ounce", "centimetre", "centimeter", "degree", "oven", "skillet", "wok", "pot", "bowl", "blender",
}
# Generic Wikibooks pages whose link text, not target, names the ingredient.
GENERIC_LINKS = {"meat and poultry", "oil and fat", "broth and stock", "spices and herbs", "vegetable", "fruit",
                 "cheese", "dairy products", "seafood", "fish", "nuts and seeds", "legumes", "grains", "herbs", "spices"}
TECHNIQUE_LINKS = {
    "sautéing": "sauteing", "sauteing": "sauteing", "sauté": "sauteing", "simmering": "simmering",
    "simmer": "simmering", "boiling": "boiling", "boil": "boiling", "frying": "pan-frying",
    "deep fat frying": "deep-frying", "deep frying": "deep-frying", "deep-frying": "deep-frying",
    "baking": "baking", "bake": "baking", "roasting": "roasting", "roast": "roasting", "grilling": "grilling",
    "steaming": "steaming", "stir frying": "stir-frying", "stir-frying": "stir-frying", "stir fry": "stir-frying",
    "braising": "braising", "braise": "braising", "stewing": "stewing", "marinating": "marinating",
    "blanching": "blanching", "kneading": "dough-making", "knead": "dough-making", "whisk": "whisking",
    "whisking": "whisking", "pressure cooking": "pressure-cooking", "fermentation": "fermenting",
}


def to_number(s: str) -> float:
    s = s.strip()
    if " " in s:
        whole, frac = s.split(None, 1)
        return float(int(whole) + Fraction(frac))
    return float(Fraction(s)) if "/" in s else float(s)


def tidy_qty(x: float) -> float | int:
    x = round(x, 3)
    return int(x) if x == int(x) else x


def normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = re.sub(r"\s+", " ", s.replace("_", " "))
    return s


def singular(s: str) -> str:
    for suf, rep in (("ies", "y"), ("oes", "o"), ("ches", "ch"), ("shes", "sh"), ("ses", "s"), ("s", "")):
        if s.endswith(suf) and len(s) > len(suf) + 2:
            return s[: -len(suf)] + rep
    return s


class IngredientMatcher:
    def __init__(self, catalog: dict, mapping: dict):
        self.catalog = catalog
        self.index: dict[str, str] = {}
        for iid, ing in catalog.items():
            for name in [iid.replace("-", " "), ing["name"], *ing.get("aliases", [])]:
                key = normalize_name(re.sub(r"\(.*?\)", "", name))
                self.index.setdefault(key, iid)
                self.index.setdefault(singular(key), iid)
        self.mapping = {normalize_name(k): v for k, v in (mapping.get("names") or {}).items()}
        self.ground = {normalize_name(k): v for k, v in (mapping.get("ground_when_measured") or {}).items()}

    def match(self, name: str, unit: str | None, line_text: str) -> str | None:
        key = normalize_name(name)
        text = line_text.lower()
        if key in self.ground:
            rule = self.ground[key]
            seeds, ground = rule["seeds"], rule["ground"]
            if "fresh" in rule and re.search(r"\b(fresh|grated|minced|chopped|sliced|leaves|sprigs?|bunch|handful)\b", text):
                return rule["fresh"]
            if re.search(r"\b(seeds?|sticks?|pods?|whole|berries|quills?|pieces?|bark)\b", text) and "ground" not in text:
                return seeds
            if unit in ("tsp", "tbsp", "pinch") or "ground" in text:
                return ground
            return self.ground[key].get("default")
        for k in (key, singular(key)):
            if k in self.mapping:
                return self.mapping[k]
            if k in self.index:
                return self.index[k]
        return None


LIQUID_HINT = re.compile(r"juice|vinegar|milk|cream|sauce|syrup|oil|wine|water|stock|broth|beer|rum|brandy|sherry|extract|molasses|honey")


LIQUID_DAIRY = {"milk", "buttermilk", "heavy-cream", "evaporated-milk", "kefir"}


def is_liquid(iid: str, ing: dict) -> bool:
    """Whether "oz" on this ingredient means fluid ounces."""
    if ing["category"] in ("beverage", "stock", "water") or iid in LIQUID_DAIRY:
        return True
    return ing["category"] != "dairy" and bool(LIQUID_HINT.search(iid))


def parse_ingredient_line(raw: str, matcher: IngredientMatcher):
    """Return (line dict | None, issue | None, unmatched name | None)."""
    links = [(m.group(1).strip(), (m.group(2) or m.group(1)).strip()) for m in LINK.finditer(raw)]
    text = plain(raw).strip(" *")
    for k, v in UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d)\s*{k}", rf"\1 {v}", text).replace(k, v)
    if not text:
        return None, None, None

    optional_aside = bool(re.search(r"\(\s*optional\s*\)", text, flags=re.I))
    text = re.sub(r"\s*\([^)]*\)", "", text).strip()  # drop "(240 g)"-style equivalents and asides
    line, rest = {}, text
    m = QTY.match(rest)
    if m:
        lo = to_number(m.group(1))
        hi = to_number(m.group(2)) if m.group(2) else None
        rest = rest[m.end():]
        if FLUID_OZ.match(rest):
            unit, mult = "ml", 29.57
            rest = FLUID_OZ.sub("", rest, count=1)
        else:
            w = re.match(r"^([A-Za-z]+)\.?\b\s*(?:of\b\s*)?", rest)
            unit, mult = UNIT_WORDS.get(w.group(1).lower(), (None, 1)) if w else (None, 1)
            if unit:
                rest = rest[w.end():]
        rest = re.sub(r"^each\s+", "", rest)
        line["qty"], line["_mult"] = (lo, hi), mult
        if unit:
            line["unit"] = unit
    rest = rest.strip(" ,")

    # Split "name, prep" and pull leading size words into the note.
    words = rest.split(",", 1)
    head, prep = words[0].strip(), (words[1].strip() if len(words) > 1 else "")
    size = []
    while head.split(" ", 1)[0].lower() in SIZE_WORDS and " " in head:
        first, head = head.split(" ", 1)
        size.append(first.lower())

    candidates = []
    for target, label in links:
        t = normalize_name(target.split("#")[0])
        if t in NON_INGREDIENT_LINKS:
            continue
        candidates += [label, t] if t in GENERIC_LINKS else [t, label]
    candidates.append(head)
    iid = None
    for cand in candidates:
        iid = matcher.match(cand, line.get("unit"), text)
        if iid:
            break
    if not iid:
        return None, f"unmapped ingredient: {text}", normalize_name(candidates[0]) if candidates else text

    # Scale quantities now that we know the ingredient: weight ounces of a liquid are fluid ounces.
    if "qty" in line:
        (lo, hi), mult = line.pop("qty"), line.pop("_mult")
        if line.get("unit") == "g" and mult == 28.35 and is_liquid(iid, matcher.catalog[iid]):
            line["unit"], mult = "ml", 29.57
        lo *= mult
        hi = hi * mult if hi is not None else None
        if mult != 1:  # converted from imperial: round sensibly
            lo, hi = round(lo), round(hi) if hi is not None else None
        line["qty"] = [tidy_qty(lo), tidy_qty(hi)] if hi is not None and hi > lo else tidy_qty(lo)
    if line.get("unit") == "clove" and iid != "garlic":  # "4 cloves" of the spice: a count, not a unit
        del line["unit"]
    line = {"ingredient": iid, **line}
    lower = text.lower()
    notes = []
    if size:
        notes.append(" ".join(size))
    if prep:
        if re.fullmatch(r"(?:or\s+)?to taste", prep.lower()):
            notes.append("to taste")
        elif re.search(r"\boptional\b", prep.lower()):
            line["optional"] = True
            prep = re.sub(r"\(?\boptional\b\)?", "", prep, flags=re.I).strip(" ,;")
            if prep:
                line["prep"] = prep
        else:
            line["prep"] = prep
    if optional_aside or re.search(r"^optional\b", lower):
        line["optional"] = True
    if "qty" not in line and "to taste" in lower and "to taste" not in notes:
        notes.append("to taste")
    if notes:
        line["note"] = "; ".join(notes)
    return line, None, None


# --- Page → recipe ---------------------------------------------------------------

def load_config():
    cfg = yaml.safe_load((ROOT / "data" / "wikibooks-import.yaml").read_text(encoding="utf-8"))
    catalog = yaml.safe_load((ROOT / "data" / "ingredients.yaml").read_text(encoding="utf-8"))
    return cfg, IngredientMatcher(catalog, cfg.get("ingredients") or {})


def page_countries(page, cfg):
    """Return (country, other_countries). The summary box wins; otherwise categories, which the API
    returns alphabetically — so several distinct countries means the choice needs a human."""
    cuisines = cfg["cuisines"]
    params = summary_params(page["wikitext"])
    preferred = [plain(params.get("category", "")), f"{plain(params.get('cuisine', ''))} recipes"]
    from_cats = []
    for cat in page.get("categories", []):
        code = cuisines.get(cat.removeprefix("Category:"))
        if code and code not in from_cats:
            from_cats.append(code)
    for name in preferred:
        if name in cuisines:
            main = cuisines[name]
            return main, [c for c in from_cats if c != main]
    if not from_cats:
        return None, []
    return from_cats[0], from_cats[1:]


def page_course(page, cfg):
    for cat in page.get("categories", []):
        course = cfg["courses"].get(cat.removeprefix("Category:"))
        if course:
            return course
    return None


def convert_page(page, cfg, matcher):
    """Return (recipe, issues, unmatched_names)."""
    wt = page["wikitext"]
    issues, unmatched = [], []
    if re.match(r"\s*#redirect", wt, flags=re.I):
        return None, ["redirect"], []
    title_full = page["title"].removeprefix("Cookbook:")
    paren = re.match(r"^(.*?)\s*\((.+)\)\s*$", title_full)
    title, subtitle = (paren.group(1), paren.group(2)) if paren else (title_full, None)
    title = re.sub(r"\s+(?:I|II|III|IV|V|VI)$", "", title)  # Wikibooks numbers variants: "Anzac Biscuits I"

    country, other_countries = page_countries(page, cfg)
    if not country:
        issues.append("no country: cuisine category not mapped")
    elif other_countries and not summary_params(wt).get("cuisine"):
        issues.append(f"several cuisines ({', '.join([country, *other_countries])}): confirm the country of origin")
    params = summary_params(wt)
    secs = sections(wt)

    intro_lines = []
    for line in strip_templates(secs.get("", "")).splitlines():
        bare = LINK.sub("", re.sub(r"__[A-Z]+__", "", line))
        if re.fullmatch(r"[\s|•·,;:-]*", bare):  # breadcrumb/navigation lines: only links and separators
            continue
        intro_lines.append(line)
    intro = re.sub(r"^[\s|]+", "", plain("\n".join(intro_lines)))
    sentences = re.split(r"(?<=[.!?])\s+", intro)
    summary = ""
    for s in sentences:
        if len(summary) + len(s) + 1 > 280:
            break
        summary = f"{summary} {s}".strip()
    if len(summary) < 20:
        issues.append("no usable introduction for the summary")

    ing_body = find_section(secs, "ingredient")
    groups, techniques = [], set()
    if not ing_body:
        issues.append("no Ingredients section")
    else:
        current = {"items": []}
        for raw in ing_body.splitlines():
            h = re.match(r"^===+\s*(.*?)\s*===+\s*$", raw)
            if h:
                if current["items"]:
                    groups.append(current)
                current = {"name": plain(h.group(1)), "items": []}
                continue
            if not raw.lstrip().startswith(("*", "#")):
                continue
            line, issue, miss = parse_ingredient_line(raw.lstrip("*# "), matcher)
            if issue:
                issues.append(issue)
                unmatched.append(miss)
            elif line:
                current["items"].append(line)
        if current["items"]:
            groups.append(current)
        if not groups:
            issues.append("no ingredient lines parsed")

    proc = find_section(secs, "procedure", "method", "directions", "instructions", "preparation", "steps")
    steps = []
    if proc:
        for raw in proc.splitlines():
            if raw.lstrip().startswith(("#", "*")):
                txt = plain(raw.lstrip("#*: "))
                if len(txt) >= 5:
                    steps.append(txt)
            for m in LINK.finditer(raw):
                tech = TECHNIQUE_LINKS.get(normalize_name(m.group(1)))
                if tech:
                    techniques.add(tech)
    if not steps:
        issues.append("no procedure steps")

    tips = []
    notes = find_section(secs, "notes", "tips", "variations")
    if notes:
        tips = [plain(l.lstrip("*# ")) for l in notes.splitlines() if l.lstrip().startswith(("*", "#"))]
        tips = [t for t in tips if len(t) >= 5]

    equipment = []
    eq = find_section(secs, "equipment")
    if eq:
        equipment = [plain(l.lstrip("*# ")) for l in eq.splitlines() if l.lstrip().startswith("*")]
        equipment = [e for e in equipment if e]

    yield_ = {}
    servings = params.get("servings") or params.get("yield") or ""
    sm = re.search(r"\d+", plain(servings))
    if sm and int(sm.group()) > 0:
        yield_["servings"] = int(sm.group())
        if re.search(r"\d+\s*(?:-|–|to)\s*\d+", servings) or not re.fullmatch(r"\s*\d+\s*", plain(servings)):
            yield_["amount"] = plain(servings)
    else:
        issues.append("no servings in recipe summary")

    minutes = parse_minutes(params.get("time", ""))
    if not minutes:
        issues.append("no time in recipe summary")

    difficulty = None
    dm = re.search(r"[1-5]", params.get("difficulty", ""))
    if dm:
        difficulty = int(dm.group())
    else:
        issues.append("no difficulty in recipe summary")

    course = page_course(page, cfg)
    if not course:
        issues.append("course unknown from categories")

    slug = slugify(title) or slugify(title_full)
    revid = page["revid"]
    recipe = {
        "id": f"{(country or 'xx').lower()}-{slug}",
        "title": title,
        **({"alternate_names": [subtitle]} if subtitle else {}),
        "summary": summary or f"{title}.",
        "origin": {"country": country or "XX", **({"also_claimed_by": other_countries} if other_countries else {})},
        "course": course or "main",
        "authenticity": "unassessed",
        "yield": yield_ or {"servings": 1},
        "time": {"total_min": minutes or 1},
        "difficulty": difficulty or 1,
        **({"equipment": equipment} if equipment else {}),
        **({"techniques": sorted(techniques)} if techniques else {}),
        "ingredient_groups": groups or [{"items": [{"ingredient": "water"}]}],
        "steps": steps or ["(missing)"],
        **({"tips": tips} if tips else {}),
        "credit": {
            "source_type": "imported",
            "contributors": [{"name": "Wikibooks contributors", "role": "written-by",
                              "url": f"https://en.wikibooks.org/w/index.php?title={urllib.parse.quote(page['title'].replace(' ', '_'))}&action=history"}],
            "dataset": {"name": "Wikibooks Cookbook", "record_id": f"{page['title']}@{revid}",
                        "url": f"https://en.wikibooks.org/w/index.php?oldid={revid}", "license": LICENSE},
            "license": LICENSE,
            "notes": "Converted automatically into Globowl's structured format (ingredients mapped to the catalog, imperial weights converted to metric). Text adapted from the source revision.",
        },
        "review": {"status": "draft", "notes": "Imported from Wikibooks; not yet reviewed or tested."},
    }
    return recipe, issues, unmatched


def dump_recipe(recipe) -> str:
    class Dumper(yaml.SafeDumper):
        pass

    def flow_line(dumper, data):
        flow = "ingredient" in data
        return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=flow)

    Dumper.add_representer(dict, flow_line)
    return yaml.dump(recipe, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=1000)


def dish_key(name: str) -> str:
    return slugify(re.sub(r"\s+(?:I|II|III|IV|V|VI)$", "", re.sub(r"\(.*?\)", "", name)))


def handwritten_index():
    """Normalised dish names of hand-written recipes, per country, for duplicate detection."""
    index = {}
    for p in (ROOT / "recipes").glob("*/*.yaml"):
        r = yaml.safe_load(p.read_text(encoding="utf-8"))
        if r["credit"]["source_type"] == "imported":
            continue
        names = [r["title"], *r.get("alternate_names", [])]
        if r.get("native_name"):
            names += [r["native_name"]["text"], r["native_name"].get("romanized", "")]
        for country in [r["origin"]["country"], *r["origin"].get("also_claimed_by", [])]:
            for n in names:
                if dish_key(n):
                    index.setdefault((country, dish_key(n)), r["id"])
    return index


def convert():
    cfg, matcher = load_config()
    pages_path = CACHE / "pages.jsonl"
    if not pages_path.exists():
        sys.exit("no cache yet — run `fetch` first")
    pages = [json.loads(l) for l in pages_path.open(encoding="utf-8")]
    existing_ids = {f"{p.parent.name}-{p.stem}" for p in (ROOT / "recipes").glob("*/*.yaml")
                    if "source_type: imported" not in p.read_text(encoding="utf-8")}
    review_dir = WORK / "review"
    for old in list(review_dir.glob("*/*.yaml")) + [p for p in (ROOT / "recipes").glob("*/*.yaml")
                                                     if "Wikibooks Cookbook" in p.read_text(encoding="utf-8")]:
        old.unlink()

    promoted, queued, skipped = [], [], Counter()
    unmatched_all, issue_kinds = Counter(), Counter()
    seen_ids = set()
    dishes = handwritten_index()
    for page in sorted(pages, key=lambda p: p["title"]):
        recipe, issues, unmatched = convert_page(page, cfg, matcher)
        if recipe is None:
            skipped[issues[0]] += 1
            continue
        rid = recipe["id"]
        if rid in existing_ids:
            issues.append(f"duplicate of hand-written recipe {rid}")
        names = [recipe["title"], *recipe.get("alternate_names", [])]
        dup = next((dishes[(recipe["origin"]["country"], dish_key(n))] for n in names
                    if (recipe["origin"]["country"], dish_key(n)) in dishes), None)
        if dup and dup != rid:
            issues.append(f"possible duplicate of hand-written recipe {dup} — merge or keep as a variant")
        if rid in seen_ids:
            issues.append(f"duplicate id {rid} from another Wikibooks page")
        seen_ids.add(rid)
        unmatched_all.update(n for n in unmatched if n)
        for i in issues:
            issue_kinds[i.split(":")[0]] += 1
        cc = recipe["origin"]["country"].lower()
        slug = rid.split("-", 1)[1]
        if issues:
            path = review_dir / cc / f"{slug}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Import issues — fix these, then move the file to recipes/:\n"
                            + "".join(f"#  - {i}\n" for i in issues) + dump_recipe(recipe), encoding="utf-8")
            queued.append(rid)
        else:
            path = ROOT / "recipes" / cc / f"{slug}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dump_recipe(recipe), encoding="utf-8")
            promoted.append(rid)

    lines = ["# Wikibooks import report", "", "Generated by `tools/import_wikibooks.py convert`.", "",
             f"- Pages in cache: {len(pages)}",
             f"- Promoted to `recipes/`: **{len(promoted)}**",
             f"- Queued in `imports/wikibooks/review/`: **{len(queued)}**",
             f"- Skipped: {dict(skipped) or 0}", "",
             "## Why recipes were queued", "", "| Issue | Recipes |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in issue_kinds.most_common()]
    lines += ["", "## Most common unmapped ingredients", "",
              "Add these to `data/ingredients.yaml` (with allergen flags) or to the name map in "
              "`data/wikibooks-import.yaml`, then re-run `convert`.", "", "| Name | Lines |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in unmatched_all.most_common(80)]
    lines += ["", "## Promoted", ""] + [f"- {r}" for r in sorted(promoted)]
    (WORK / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"promoted {len(promoted)}, queued {len(queued)}, skipped {sum(skipped.values())}")
    print("top issues:", issue_kinds.most_common(6))
    print("top unmapped:", unmatched_all.most_common(25))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "convert"])
    args = ap.parse_args(argv)
    fetch() if args.command == "fetch" else convert()


if __name__ == "__main__":
    main()
