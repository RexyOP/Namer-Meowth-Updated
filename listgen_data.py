"""
listgen_data.py
---------------
Centralised data loader for the list-generator cog.

All five data files are loaded once at import time so any cog that
imports from here shares the same in-memory objects without hitting
disk again.

Exports
-------
ALL_POKEMON          : list[dict]   – every row from typeandregions.csv as dicts
                       keys: dex_number (int), name (str), region (str),
                             type1 (str), type2 (str | None)

ALL_NAMES_ORDERED    : list[str]    – every Pokémon name in CSV row order
                       (used for name-extraction and alphabetical listings)

NAME_TO_ROW          : dict[str, dict]  – lowercase name → CSV row dict
                       Includes all variant names (Mega X, Alolan, …)

SPAWNRATE_DATA       : dict[int, list[str]]
                       denominator → [Pokémon names]  e.g. {225: ["Abra", …]}

NAME_TO_SR           : dict[str, int]   – lowercase name → SR denominator

POKEMON_DATA         : list[dict]   – pokemondata.json entries
                       keys: dex_number, name, other_names, is_variant

EVENT_DATA           : list[dict]   – eventdata.json entries

BEST_NAMES           : dict[str, str]   – canonical name → "best" display name

STAGE_DATA           : dict[str, int]  – lowercase name → stage (1/2/3)
                       Populated from data/stagelist.csv when available;
                       falls back to an empty dict.

Helper functions
----------------
get_all_names()          → list[str]  (fresh sorted copy, alphabetical)
get_names_by_type(t)     → list[str]
get_names_by_region(r)   → list[str]
get_names_by_sr(denom)   → list[str]
get_names_by_stage(s)    → list[str]
get_names_by_name_filter(query, all_forms) → list[str]
"""

from __future__ import annotations

import csv
import json
import os
from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Paths  (relative to the bot's working directory)
# ──────────────────────────────────────────────────────────────────────────────
_BASE = "data"
_TYPEANDREGIONS  = os.path.join(_BASE, "typeandregions.csv")
_SPAWNRATE       = os.path.join(_BASE, "spawnrate.csv")
_POKEMONDATA     = os.path.join(_BASE, "pokemondata.json")
_EVENTDATA       = os.path.join(_BASE, "eventdata.json")
_BESTNAMES       = os.path.join(_BASE, "best_names.json")
_STAGELIST       = os.path.join(_BASE, "stagelist.csv")


# ──────────────────────────────────────────────────────────────────────────────
# Internal loaders
# ──────────────────────────────────────────────────────────────────────────────

def _load_typeandregions() -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    name_to_row: dict[str, dict] = {}
    try:
        with open(_TYPEANDREGIONS, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                row = {
                    "dex_number": int(raw["dex_number"]) if raw.get("dex_number", "").strip().lstrip("-").isdigit() else 0,
                    "name":   raw["name"].strip(),
                    "region": raw.get("region", "").strip(),
                    "type1":  raw.get("type1", "").strip() or None,
                    "type2":  raw.get("type2", "").strip() or None,
                }
                rows.append(row)
                name_to_row[row["name"].lower()] = row
    except Exception as e:
        print(f"[listgen_data] Could not load typeandregions.csv: {e}")
    return rows, name_to_row


def _load_spawnrate() -> tuple[dict[int, list[str]], dict[str, int]]:
    sr_map: dict[int, list[str]] = {}
    name_to_sr: dict[str, int] = {}
    try:
        with open(_SPAWNRATE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                chance = raw.get("Chance", "").strip()
                name  = raw.get("Pokemon", "").strip()
                if not chance or not name:
                    continue
                parts = chance.split("/")
                if len(parts) == 2:
                    try:
                        denom = int(parts[1])
                        sr_map.setdefault(denom, []).append(name)
                        name_to_sr[name.lower()] = denom
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[listgen_data] Could not load spawnrate.csv: {e}")
    return sr_map, name_to_sr


def _load_json(path: str) -> list | dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[listgen_data] Could not load {path}: {e}")
        return []


def _load_stagelist() -> dict[str, int]:
    stage_map: dict[str, int] = {}
    try:
        with open(_STAGELIST, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                name  = raw.get("name", raw.get("pokemon", raw.get("Pokemon", ""))).strip()
                stage = raw.get("stage", raw.get("Stage", "")).strip()
                if name and stage:
                    try:
                        stage_map[name.lower()] = int(stage)
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass  # optional file – silence the error
    except Exception as e:
        print(f"[listgen_data] Could not load stagelist.csv: {e}")
    return stage_map


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singletons  (loaded once)
# ──────────────────────────────────────────────────────────────────────────────

ALL_POKEMON, NAME_TO_ROW   = _load_typeandregions()
ALL_NAMES_ORDERED: list[str] = [r["name"] for r in ALL_POKEMON]

SPAWNRATE_DATA, NAME_TO_SR = _load_spawnrate()

POKEMON_DATA: list[dict]   = _load_json(_POKEMONDATA)  # type: ignore[assignment]
EVENT_DATA:   list[dict]   = _load_json(_EVENTDATA)    # type: ignore[assignment]
BEST_NAMES:   dict         = _load_json(_BESTNAMES)    # type: ignore[assignment]

STAGE_DATA: dict[str, int] = _load_stagelist()


# ──────────────────────────────────────────────────────────────────────────────
# Convenience query helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_all_names() -> list[str]:
    """Alphabetically sorted list of every Pokémon name."""
    return sorted(ALL_NAMES_ORDERED)


def get_names_by_type(type_filter: str) -> list[str]:
    """Return names whose type1 or type2 matches (case-insensitive)."""
    t = type_filter.strip().lower()
    return [
        r["name"] for r in ALL_POKEMON
        if (r["type1"] or "").lower() == t or (r["type2"] or "").lower() == t
    ]


def get_names_by_region(region_filter: str) -> list[str]:
    """Return names whose region matches (case-insensitive)."""
    reg = region_filter.strip().lower()
    return [r["name"] for r in ALL_POKEMON if r["region"].lower() == reg]


def get_names_by_sr(denom: int) -> list[str]:
    """Return names that have the given spawn-rate denominator."""
    return list(SPAWNRATE_DATA.get(denom, []))


def get_names_by_stage(stage: int) -> list[str]:
    """Return names whose evolution stage matches (requires stagelist.csv)."""
    return [name for name, s in STAGE_DATA.items() if s == stage]


def get_names_by_name_filter(query: str, all_forms: bool = False) -> list[str]:
    """
    Match by exact name (case-insensitive).

    If all_forms is True, return every row whose name starts with <query>
    (e.g. "furfrou" → Furfrou, La Reine Furfrou, Kabuki Furfrou, …).
    """
    q = query.strip().lower()
    if all_forms:
        return [r["name"] for r in ALL_POKEMON if r["name"].lower().startswith(q) or q in r["name"].lower()]
    row = NAME_TO_ROW.get(q)
    return [row["name"]] if row else []


def apply_filters(args_str: str) -> list[str]:
    """
    Parse a filter string (same syntax as collection / listgen modals) and
    return the matching Pokémon names IN CSV ORDER (deduped).

    Supported flags (can be combined):
        --type / --t  <type>
        --region / --r <region>
        --sr / --spawnrate <denom>
        --stage <1|2|3>
        --name / --n  <name>  [all]
        --catchable             only Pokémon present in spawnrate data

    Multiple flags narrow the result (AND logic within one call).
    The caller combines results from multiple modal cells.
    """
    import re

    results: list[str] | None = None

    def _intersect(a: list[str], b: list[str]) -> list[str]:
        b_set = {x.lower() for x in b}
        return [x for x in a if x.lower() in b_set]

    def _apply(candidate: list[str]):
        nonlocal results
        if results is None:
            results = candidate
        else:
            results = _intersect(results, candidate)

    # ── --type / --t
    for m in re.finditer(r'--(?:type|t)\s+(\S+)', args_str, re.IGNORECASE):
        _apply(get_names_by_type(m.group(1)))

    # ── --region / --r
    for m in re.finditer(r'--(?:region|r)\s+(\S+)', args_str, re.IGNORECASE):
        _apply(get_names_by_region(m.group(1)))

    # ── --sr / --spawnrate
    for m in re.finditer(r'--(?:sr|spawnrate)\s+(\d+)', args_str, re.IGNORECASE):
        _apply(get_names_by_sr(int(m.group(1))))

    # ── --stage
    for m in re.finditer(r'--stage\s+(\d)', args_str, re.IGNORECASE):
        _apply([n.title() if n in STAGE_DATA else n
                for n in get_names_by_stage(int(m.group(1)))])

    # ── --name / --n  [all]
    for m in re.finditer(r'--(?:name|n)\s+(all\s+)?(\S+(?:\s+\S+)*?)(?=\s+--|$)',
                         args_str.strip(), re.IGNORECASE):
        all_flag = bool(m.group(1))
        query    = m.group(2).strip()
        _apply(get_names_by_name_filter(query, all_forms=all_flag))

    # ── --catchable  (no argument — Pokémon must have a spawnrate entry)
    if re.search(r'--catchable\b', args_str, re.IGNORECASE):
        _apply([n for n in ALL_NAMES_ORDERED if n.lower() in NAME_TO_SR])

    # Re-order by CSV position and deduplicate
    if results is None:
        return []
    csv_pos = {r["name"].lower(): i for i, r in enumerate(ALL_POKEMON)}
    seen: set[str] = set()
    ordered: list[str] = []
    for name in sorted(results, key=lambda n: csv_pos.get(n.lower(), 99999)):
        if name.lower() not in seen:
            seen.add(name.lower())
            ordered.append(name)
    return ordered
