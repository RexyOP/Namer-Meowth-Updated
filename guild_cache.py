"""
guild_cache.py — In-memory TTL cache for all per-spawn DB lookups.

At 100 incense channels × 1 spawn/20s ≈ 5 spawns/second, the bot was
firing ~40 MongoDB queries/second for data that almost never changes
during a session.  This module reduces that to 0 DB queries on cache hits.

TTLs are short (20–60 s) so AFK toggles and admin setting changes are
reflected quickly without a bot restart.
"""

import asyncio
import time
from typing import Optional


class _TTLEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value, ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl

    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


# ---------------------------------------------------------------------------
# AFK Snapshot — one object, one DB query, all four AFK flags
# ---------------------------------------------------------------------------
class AFKSnapshot:
    """
    Replaces three separate DB fetches:
        get_shiny_hunt_afk_users()    → .shiny_afk      (set)
        get_collection_afk_users()   → .collection_afk  (set)
        get_type_region_afk_users()  → .type_ping_afk / .region_ping_afk (sets)

    Users can now be independently AFK for each ping type.
    """

    def __init__(self, shiny_list, coll_list, tr_map):
        all_uids: set = set(shiny_list) | set(coll_list) | set(tr_map.keys())
        self._flags: dict = {}
        for uid in all_uids:
            self._flags[uid] = {
                "shiny":       uid in shiny_list,
                "collection":  uid in coll_list,
                "type_ping":   tr_map.get(uid, {}).get("type",   False),
                "region_ping": tr_map.get(uid, {}).get("region", False),
            }

    @property
    def shiny_afk(self) -> set:
        return {uid for uid, f in self._flags.items() if f["shiny"]}

    @property
    def collection_afk(self) -> set:
        return {uid for uid, f in self._flags.items() if f["collection"]}

    @property
    def type_ping_afk(self) -> set:
        return {uid for uid, f in self._flags.items() if f["type_ping"]}

    @property
    def region_ping_afk(self) -> set:
        return {uid for uid, f in self._flags.items() if f["region_ping"]}


# ---------------------------------------------------------------------------
# Main cache
# ---------------------------------------------------------------------------
class GuildCache:
    TTL_AFK        = 30   # seconds — refreshes after any !afk command
    TTL_GUILD      = 60   # guild settings, roles
    TTL_HUNTS      = 20   # shiny hunts (users set these often during incense)
    TTL_COLLECTORS = 20   # collections
    TTL_TYPE_RGN   = 60   # type/region pingers (rarely change mid-session)
    TTL_RARE       = 60   # rare collectors
    TTL_RESERVES   = 20   # reserves (can change during session)
    TTL_RESERVE_ROLES = 60  # reserve allowed roles (rarely change)

    def __init__(self, db):
        self._db = db

        self._afk: Optional[_TTLEntry] = None
        self._afk_lock = asyncio.Lock()

        # Per-guild: {guild_id: _TTLEntry}
        self._guild_settings:  dict = {}
        self._shiny_hunts:     dict = {}
        self._rare_collectors: dict = {}

        # Keyed by (guild_id, sorted_tuple): _TTLEntry
        self._collectors:    dict = {}
        self._type_pingers:  dict = {}
        self._region_pingers:dict = {}

        # Per-guild asyncio locks to avoid thundering-herd on simultaneous spawns
        self._guild_locks: dict = {}

        # Reserves: {guild_id: _TTLEntry}  value = list of {user_id, pokemon:[...]}
        self._reserves:      dict = {}
        self._reserve_roles: dict = {}

    def _guild_lock(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._guild_locks:
            self._guild_locks[guild_id] = asyncio.Lock()
        return self._guild_locks[guild_id]

    # -----------------------------------------------------------------------
    # AFK Snapshot  (global)
    # -----------------------------------------------------------------------
    async def get_afk_snapshot(self) -> AFKSnapshot:
        async with self._afk_lock:
            if self._afk and self._afk.is_valid():
                return self._afk.value

            # Three DB queries in parallel → one AFKSnapshot
            shiny_list, coll_list, tr_map = await asyncio.gather(
                self._db.get_shiny_hunt_afk_users(),
                self._db.get_collection_afk_users(),
                self._db.get_type_region_afk_users(),
            )
            snapshot = AFKSnapshot(shiny_list, coll_list, tr_map)
            self._afk = _TTLEntry(snapshot, self.TTL_AFK)
            return snapshot

    def invalidate_afk(self):
        """Call after any AFK toggle so next spawn re-fetches."""
        self._afk = None

    # -----------------------------------------------------------------------
    # Guild settings  (only_pings, best_name_enabled, rare_role_id, …)
    # -----------------------------------------------------------------------
    async def get_guild_settings(self, guild_id: int) -> dict:
        entry = self._guild_settings.get(guild_id)
        if entry and entry.is_valid():
            return entry.value

        async with self._guild_lock(guild_id):
            entry = self._guild_settings.get(guild_id)
            if entry and entry.is_valid():
                return entry.value
            settings = await self._db.get_guild_settings(guild_id)
            self._guild_settings[guild_id] = _TTLEntry(settings, self.TTL_GUILD)
            return settings

    def invalidate_guild_settings(self, guild_id: int):
        self._guild_settings.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Shiny hunts  (all hunts for a guild cached together)
    # -----------------------------------------------------------------------
    async def _get_raw_shiny_hunts(self, guild_id: int) -> list:
        entry = self._shiny_hunts.get(guild_id)
        if entry and entry.is_valid():
            return entry.value

        async with self._guild_lock(guild_id):
            entry = self._shiny_hunts.get(guild_id)
            if entry and entry.is_valid():
                return entry.value
            raw = await self._db.db.shiny_hunts.find(
                {"guild_id": guild_id},
                {"user_id": 1, "pokemon": 1}
            ).to_list(length=None)
            self._shiny_hunts[guild_id] = _TTLEntry(raw, self.TTL_HUNTS)
            return raw

    async def get_shiny_hunters(self, guild_id: int, pokemon_names: list, afk_set: set) -> list:
        raw = await self._get_raw_shiny_hunts(guild_id)
        names_set = set(pokemon_names)
        result = []
        for hunt in raw:
            uid = hunt["user_id"]
            pokes = hunt.get("pokemon", [])
            if isinstance(pokes, str):
                pokes = [pokes]
            if any(p in pokes for p in names_set):
                result.append((uid, uid in afk_set))
        return result

    def invalidate_shiny_hunts(self, guild_id: int):
        self._shiny_hunts.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Collectors
    # -----------------------------------------------------------------------
    async def get_collectors(self, guild_id: int, pokemon_names: list, afk_set: set) -> list:
        key = (guild_id, tuple(sorted(pokemon_names)))
        entry = self._collectors.get(key)
        if not entry or not entry.is_valid():
            raw = await self._db.get_collectors_for_pokemon(guild_id, pokemon_names, [])
            self._collectors[key] = _TTLEntry(raw, self.TTL_COLLECTORS)
            entry = self._collectors[key]
        return [uid for uid in entry.value if uid not in afk_set]

    def invalidate_collectors(self, guild_id: int):
        to_del = [k for k in self._collectors if k[0] == guild_id]
        for k in to_del:
            del self._collectors[k]

    # -----------------------------------------------------------------------
    # Rare collectors
    # -----------------------------------------------------------------------
    async def get_rare_collectors(self, guild_id: int, afk_set: set) -> list:
        entry = self._rare_collectors.get(guild_id)
        if not entry or not entry.is_valid():
            async with self._guild_lock(guild_id):
                entry = self._rare_collectors.get(guild_id)
                if not entry or not entry.is_valid():
                    raw = await self._db.get_rare_collectors(guild_id, [])
                    self._rare_collectors[guild_id] = _TTLEntry(raw, self.TTL_RARE)
                    entry = self._rare_collectors[guild_id]
        return [uid for uid in entry.value if uid not in afk_set]

    def invalidate_rare_collectors(self, guild_id: int):
        self._rare_collectors.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Type pingers
    # -----------------------------------------------------------------------
    async def get_type_pingers(self, guild_id: int, types: list, afk_set: set) -> list:
        if not types:
            return []
        key = (guild_id, tuple(sorted(types)))
        entry = self._type_pingers.get(key)
        if not entry or not entry.is_valid():
            raw = await self._db.get_users_for_types(guild_id, types, set())
            self._type_pingers[key] = _TTLEntry(raw, self.TTL_TYPE_RGN)
            entry = self._type_pingers[key]
        return [uid for uid in entry.value if uid not in afk_set]

    def invalidate_type_pingers(self, guild_id: int):
        to_del = [k for k in self._type_pingers if k[0] == guild_id]
        for k in to_del:
            del self._type_pingers[k]

    # -----------------------------------------------------------------------
    # Region pingers
    # -----------------------------------------------------------------------
    async def get_region_pingers(self, guild_id: int, regions: list, afk_set: set) -> list:
        if not regions:
            return []
        key = (guild_id, tuple(sorted(regions)))
        entry = self._region_pingers.get(key)
        if not entry or not entry.is_valid():
            raw = await self._db.get_users_for_regions(guild_id, regions, set())
            self._region_pingers[key] = _TTLEntry(raw, self.TTL_TYPE_RGN)
            entry = self._region_pingers[key]
        return [uid for uid in entry.value if uid not in afk_set]

    def invalidate_region_pingers(self, guild_id: int):
        to_del = [k for k in self._region_pingers if k[0] == guild_id]
        for k in to_del:
            del self._region_pingers[k]

    # -----------------------------------------------------------------------
    # Reserves  (all docs for a guild cached together)
    # -----------------------------------------------------------------------
    async def _get_raw_reserves(self, guild_id: int) -> list:
        entry = self._reserves.get(guild_id)
        if entry and entry.is_valid():
            return entry.value

        async with self._guild_lock(guild_id):
            entry = self._reserves.get(guild_id)
            if entry and entry.is_valid():
                return entry.value
            raw = await self._db.get_all_reserves(guild_id)
            self._reserves[guild_id] = _TTLEntry(raw, self.TTL_RESERVES)
            return raw

    async def get_reserve_holders(self, guild_id: int, pokemon_names: list, afk_set: set) -> list:
        """Return user_ids who reserved any of the given pokemon (excluding AFK)."""
        raw = await self._get_raw_reserves(guild_id)
        names_set = set(pokemon_names)
        result = []
        seen = set()
        for doc in raw:
            uid = doc['user_id']
            if uid in seen or uid in afk_set:
                continue
            reserved = doc.get('pokemon', [])
            if any(p in names_set for p in reserved):
                result.append(uid)
                seen.add(uid)
        return result

    async def is_pokemon_reserved(self, guild_id: int, pokemon_names: list) -> bool:
        """Return True if any user has reserved any of these pokemon names in this guild."""
        raw = await self._get_raw_reserves(guild_id)
        names_set = set(pokemon_names)
        for doc in raw:
            if any(p in names_set for p in doc.get('pokemon', [])):
                return True
        return False

    def invalidate_reserves(self, guild_id: int):
        self._reserves.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Reserve allowed roles
    # -----------------------------------------------------------------------
    async def get_reserve_allowed_roles(self, guild_id: int) -> list:
        entry = self._reserve_roles.get(guild_id)
        if entry and entry.is_valid():
            return entry.value

        async with self._guild_lock(guild_id):
            entry = self._reserve_roles.get(guild_id)
            if entry and entry.is_valid():
                return entry.value
            roles = await self._db.get_reserve_allowed_roles(guild_id)
            self._reserve_roles[guild_id] = _TTLEntry(roles, self.TTL_RESERVE_ROLES)
            return roles

    def invalidate_reserve_roles(self, guild_id: int):
        self._reserve_roles.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Incense settings  (enabled flag + categories + paused channels)
    # Cached so incense.py on_message doesn't hit DB on every spawn
    # -----------------------------------------------------------------------
    TTL_INCENSE = 30  # seconds

    async def get_incense_settings(self, guild_id: int) -> dict:
        """Return the raw incense guild doc (or {}) from cache or DB."""
        if not hasattr(self, '_incense_settings'):
            self._incense_settings: dict = {}
        entry = self._incense_settings.get(guild_id)
        if entry and entry.is_valid():
            return entry.value
        async with self._guild_lock(guild_id):
            entry = self._incense_settings.get(guild_id)
            if entry and entry.is_valid():
                return entry.value
            doc = await self._db.db.user_data.find_one(
                {"user_id": f"incense_guild_{guild_id}"}
            ) or {}
            self._incense_settings[guild_id] = _TTLEntry(doc, self.TTL_INCENSE)
            return doc

    def invalidate_incense_settings(self, guild_id: int):
        """Call whenever incense settings are saved for a guild."""
        if hasattr(self, '_incense_settings'):
            self._incense_settings.pop(guild_id, None)

    # -----------------------------------------------------------------------
    # Cleanup — removes expired keys from all cache dicts to prevent bloat.
    # Call from memory_monitor every 60 s.
    # -----------------------------------------------------------------------
    def cleanup_expired(self):
        """
        Evict entries whose TTL has elapsed from every per-guild dict.
        Without this, dead keys accumulate forever because Python never
        shrinks dicts automatically.
        """
        dicts_to_clean = [
            self._guild_settings,
            self._shiny_hunts,
            self._rare_collectors,
            self._collectors,
            self._type_pingers,
            self._region_pingers,
            self._reserves,
            self._reserve_roles,
        ]
        if hasattr(self, '_incense_settings'):
            dicts_to_clean.append(self._incense_settings)

        total_removed = 0
        for d in dicts_to_clean:
            expired = [k for k, v in d.items() if not v.is_valid()]
            for k in expired:
                del d[k]
            total_removed += len(expired)

        # Also shrink the guild_locks dict — remove locks for guilds no
        # longer in any cache (avoids keeping asyncio.Lock objects forever)
        active_guilds: set = set()
        for d in dicts_to_clean:
            for k in d:
                gid = k[0] if isinstance(k, tuple) else k
                active_guilds.add(gid)
        stale_locks = [g for g in self._guild_locks if g not in active_guilds]
        for g in stale_locks:
            del self._guild_locks[g]

        if total_removed:
            print(f"[GUILD_CACHE] cleanup_expired: removed {total_removed} stale entries")

    # -----------------------------------------------------------------------
    # Warm-up — call on !loadmodel
    # -----------------------------------------------------------------------
    async def warm(self, guild_ids: list | None = None):
        print("[GUILD_CACHE] Warming AFK snapshot...")
        await self.get_afk_snapshot()
        if guild_ids:
            print(f"[GUILD_CACHE] Warming guild settings for {len(guild_ids)} guilds...")
            await asyncio.gather(*[self.get_guild_settings(gid) for gid in guild_ids])
        print("[GUILD_CACHE] Warm-up complete.")
