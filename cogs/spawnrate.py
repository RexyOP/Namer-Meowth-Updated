"""Spawn rate command cog for Pokemon bot"""
import csv
import io
import math
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from typing import Optional, Dict
from utils import find_pokemon_by_name_flexible, load_pokemon_data, normalize_pokemon_name
from config import EMBED_COLOR

# Using the non-pinned raw URL so that reloading always pulls the latest revision
SPAWN_RATE_CSV_URL = (
    "https://gist.github.com/WitherredAway/1bc525b05f4cd52555a2a18c331e0cf9"
    "/raw/pokemon_chances.csv"
)

# Module-level cache so we only fetch once per bot session
_spawn_rate_cache: Optional[Dict[str, dict]] = None

# Shiny rate constants
BASE_SHINY_RATE = 4096
SHINY_CHARM_MULTIPLIER = 1.20


async def fetch_spawn_rates(force: bool = False) -> Dict[str, dict]:
    global _spawn_rate_cache
    if _spawn_rate_cache is not None and not force:
        return _spawn_rate_cache

    async with aiohttp.ClientSession() as session:
        async with session.get(SPAWN_RATE_CSV_URL) as response:
            response.raise_for_status()
            text = await response.text(encoding="utf-8")

    reader = csv.DictReader(io.StringIO(text))
    data: Dict[str, dict] = {}
    for row in reader:
        raw_name = row.get("Pokemon", "").strip()
        if not raw_name:
            continue
        key = normalize_pokemon_name(raw_name).lower()
        data[key] = {
            "dex": row.get("Dex", "").strip(),
            "name": raw_name,
            "chance": row.get("Chance", "").strip(),
            "chance_pct": row.get("Chance percentage", "").strip(),
        }

    _spawn_rate_cache = data
    return data


def find_spawn_rate(search_name: str, spawn_data: Dict[str, dict]) -> Optional[dict]:
    normalized = normalize_pokemon_name(search_name).lower()
    return spawn_data.get(normalized)


# ------------------------------------------------------------------ #
#  Shiny rate math                                                     #
# ------------------------------------------------------------------ #

def shiny_prob(streak: int) -> float:
    """Per-encounter shiny probability at a given streak, no charm."""
    if streak > 0:
        return (1 + math.sqrt(streak) / 7) / BASE_SHINY_RATE
    return 1 / BASE_SHINY_RATE


def shiny_prob_charm(streak: int) -> float:
    """Per-encounter shiny probability at a given streak, with Shiny Charm."""
    return shiny_prob(streak) * SHINY_CHARM_MULTIPLIER


def prob_to_fraction(p: float) -> str:
    return f"1/{round(1 / p)}"


def streak_for_target_pct(target_pct: float, charm: bool) -> int:
    """
    Binary-search for the smallest streak where the per-encounter shiny
    probability meets or exceeds target_pct (0–100).

    Formula: (1 + √streak/7) / 4096  [× 1.20 with charm]
    Solving for streak: streak = ((target * 4096 - 1) * 7)^2
    We use that as an upper bound and binary-search for exactness.
    Returns the streak, or -1 if unreachable within a safe upper bound.
    """
    target = target_pct / 100
    fn = shiny_prob_charm if charm else shiny_prob

    # Quick reachability check against an astronomically large streak
    hi = 10_000_000_000
    if fn(hi) < target:
        return -1

    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if fn(mid) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ------------------------------------------------------------------ #
#  Embed builders                                                      #
# ------------------------------------------------------------------ #

def _build_shiny_rate_embed(streak: int) -> discord.Embed:
    p_base  = shiny_prob(streak)
    p_charm = shiny_prob_charm(streak)

    embed = discord.Embed(title="✨ Shiny Rate", color=EMBED_COLOR)
    embed.add_field(name="Chain / Streak", value=str(streak), inline=False)
    embed.add_field(
        name="Without Shiny Charm",
        value=f"{prob_to_fraction(p_base)}  ({p_base * 100:.4f}%)",
        inline=False,
    )
    embed.add_field(
        name="With Shiny Charm ✨",
        value=f"{prob_to_fraction(p_charm)}  ({p_charm * 100:.4f}%)",
        inline=False,
    )

    footer = "Formula: 1/4096  ·  Charm ×1.20" if streak == 0 else \
             f"Formula: (1 + √{streak}/7) / 4096  ·  Charm ×1.20"
    embed.set_footer(text=footer)
    return embed


def _build_chain_target_embed(target_pct: float) -> discord.Embed:
    streak_base  = streak_for_target_pct(target_pct, charm=False)
    streak_charm = streak_for_target_pct(target_pct, charm=True)

    def fmt(s: int) -> str:
        return f"Streak **{s:,}**" if s >= 0 else "Unreachable"

    embed = discord.Embed(
        title=f"✨ Streak Needed for {target_pct:.2f}% Per-Encounter Shiny Chance",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Without Shiny Charm", value=fmt(streak_base),  inline=False)
    embed.add_field(name="With Shiny Charm ✨",  value=fmt(streak_charm), inline=False)
    embed.set_footer(text="Streak where your per-encounter shiny chance reaches the target.")
    return embed


def _usage_embed() -> discord.Embed:
    p_base  = shiny_prob(0)
    p_charm = shiny_prob_charm(0)

    embed = discord.Embed(title="✨ Shiny Rate — Usage", color=EMBED_COLOR)
    embed.description = (
        "**`p!shr [chain] [target%]`**  —  both values are optional\n\n"
        "`p!shr` — show this help + rates at chain 0\n"
        "`p!shr 50` — shiny rates at chain 50\n"
        "`p!shr 89%` — how many encounters for an 89% cumulative shiny chance\n"
        "`p!shr 50 89%` — both at once"
    )
    embed.add_field(
        name="Chain 0 — No Charm",
        value=f"{prob_to_fraction(p_base)}  ({p_base * 100:.4f}%)",
        inline=False,
    )
    embed.add_field(
        name="Chain 0 — With Charm ✨",
        value=f"{prob_to_fraction(p_charm)}  ({p_charm * 100:.4f}%)",
        inline=False,
    )
    return embed


# ------------------------------------------------------------------ #
#  Cog                                                                 #
# ------------------------------------------------------------------ #

class SpawnRate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    # ---- /spawnrate ------------------------------------------------- #

    @app_commands.command(name="spawnrate", description="Show the spawn rate for a Pokémon.")
    @app_commands.describe(pokemon="Pokémon name (English, Japanese, or other language)")
    async def spawnrate_slash(self, interaction: discord.Interaction, pokemon: str):
        await interaction.response.defer()

        matched = find_pokemon_by_name_flexible(pokemon, self.pokemon_data)
        canonical_name = matched["name"] if matched else pokemon.strip()

        try:
            spawn_data = await fetch_spawn_rates()
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to fetch spawn rate data: `{e}`")
            return

        entry = find_spawn_rate(canonical_name, spawn_data)
        if entry is None and canonical_name.lower() != pokemon.strip().lower():
            entry = find_spawn_rate(pokemon.strip(), spawn_data)

        if entry is None:
            await interaction.followup.send(
                f"❌ No spawn rate data found for **{canonical_name}**. It may not spawn in the wild."
            )
            return

        dex_num = entry["dex"]
        embed = discord.Embed(title=f"Spawn Rate — {entry['name']}", color=EMBED_COLOR)
        embed.set_thumbnail(url=f"https://cdn.poketwo.net/images/{dex_num}.png")
        embed.add_field(name="Dex",          value=f"#{dex_num}",      inline=True)
        embed.add_field(name="Spawn Chance", value=entry["chance"],    inline=True)
        embed.add_field(name="Percentage",   value=entry["chance_pct"], inline=True)
        if pokemon.strip().lower() != entry["name"].lower():
            embed.set_footer(text=f'Searched: "{pokemon.strip()}"')
        await interaction.followup.send(embed=embed)

    # ---- p!spawnrate / p!sr ----------------------------------------- #

    @commands.command(name="spawnrate", aliases=["sr"])
    async def spawnrate_prefix(self, ctx: commands.Context, *, pokemon_name: str = None):
        """Show the spawn rate for a Pokemon. Usage: p!sr <pokemon>"""
        if not pokemon_name:
            await ctx.send("Please provide a Pokémon name. Example: `p!sr geodude`")
            return

        async with ctx.typing():
            matched = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
            canonical_name = matched["name"] if matched else pokemon_name.strip()

            try:
                spawn_data = await fetch_spawn_rates()
            except Exception as e:
                await ctx.send(f"❌ Failed to fetch spawn rate data: `{e}`\nPlease try again later.")
                return

            entry = find_spawn_rate(canonical_name, spawn_data)
            if entry is None and canonical_name.lower() != pokemon_name.strip().lower():
                entry = find_spawn_rate(pokemon_name.strip(), spawn_data)

            if entry is None:
                await ctx.send(
                    f"❌ No spawn rate data found for **{canonical_name}**. It may not spawn in the wild."
                )
                return

            dex_num = entry["dex"]
            embed = discord.Embed(title=f"Spawn Rate — {entry['name']}", color=EMBED_COLOR)
            embed.set_thumbnail(url=f"https://cdn.poketwo.net/images/{dex_num}.png")
            embed.add_field(name="Dex",          value=f"#{dex_num}",       inline=True)
            embed.add_field(name="Spawn Chance", value=entry["chance"],     inline=True)
            embed.add_field(name="Percentage",   value=entry["chance_pct"], inline=True)
            if pokemon_name.strip().lower() != entry["name"].lower():
                embed.set_footer(text=f'Searched: "{pokemon_name.strip()}"')
            await ctx.send(embed=embed)

    # ---- /shinyrate ------------------------------------------------- #

    @app_commands.command(name="shinyrate", description="Show shiny rates or encounters needed for a target chance.")
    @app_commands.describe(
        chain="Your current catch streak / chain (optional)",
        target="Target cumulative shiny chance as a percentage, e.g. 89 (optional)",
    )
    async def shinyrate_slash(
        self,
        interaction: discord.Interaction,
        chain: Optional[int] = None,
        target: Optional[float] = None,
    ):
        if chain is not None and chain < 0:
            await interaction.response.send_message("❌ Chain cannot be negative.", ephemeral=True)
            return
        if target is not None and not (0 < target < 100):
            await interaction.response.send_message("❌ Target must be between 0 and 100.", ephemeral=True)
            return

        if chain is None and target is None:
            await interaction.response.send_message(embed=_usage_embed())
            return

        embeds = []
        if chain is not None:
            embeds.append(_build_shiny_rate_embed(chain))
        if target is not None:
            embeds.append(_build_chain_target_embed(target))

        await interaction.response.send_message(embeds=embeds)

    # ---- p!shinyrate / p!shr ---------------------------------------- #

    @commands.command(name="shinyrate", aliases=["shr"])
    async def shinyrate_prefix(self, ctx: commands.Context, *, args: str = None):
        """
        Show shiny rates or encounters needed for a target cumulative chance.
        Usage: p!shr [chain] [target%]
        """
        if not args:
            await ctx.send(embed=_usage_embed())
            return

        async with ctx.typing():
            chain: Optional[int] = None
            target: Optional[float] = None
            errors = []

            for token in args.split():
                if token.endswith("%"):
                    try:
                        val = float(token[:-1])
                        if not (0 < val < 100):
                            errors.append(f"Target `{token}` must be between 0% and 100%.")
                        else:
                            target = val
                    except ValueError:
                        errors.append(f"`{token}` is not a valid percentage.")
                else:
                    try:
                        val = int(token)
                        if val < 0:
                            errors.append("Chain cannot be negative.")
                        else:
                            chain = val
                    except ValueError:
                        errors.append(f"`{token}` is not a valid chain number.")

            if errors:
                await ctx.send("❌ " + "\n❌ ".join(errors))
                return

            embeds = []
            if chain is not None:
                embeds.append(_build_shiny_rate_embed(chain))
            if target is not None:
                embeds.append(_build_chain_target_embed(target))

            if not embeds:
                embeds.append(_usage_embed())

            await ctx.send(embeds=embeds)

    # ---- p!reloadsr (owner only) ------------------------------------ #

    @commands.command(name="reloadsr")
    @commands.is_owner()
    async def reloadsr(self, ctx: commands.Context):
        """Force-reload the spawn rate data from the gist. Owner only."""
        async with ctx.typing():
            try:
                old_count = len(_spawn_rate_cache) if _spawn_rate_cache else 0
                data = await fetch_spawn_rates(force=True)
                new_count = len(data)
            except Exception as e:
                await ctx.send(f"❌ Failed to reload spawn rate data: `{e}`")
                return

        embed = discord.Embed(title="✅ Spawn Rate Data Reloaded", color=EMBED_COLOR)
        embed.add_field(name="Entries before", value=str(old_count), inline=True)
        embed.add_field(name="Entries now",    value=str(new_count), inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SpawnRate(bot))
