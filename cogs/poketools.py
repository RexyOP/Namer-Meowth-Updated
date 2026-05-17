"""PokeTools cog — spawn rates, shiny rates, and message utilities"""
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

# ------------------------------------------------------------------ #
#  Spawn rate data                                                     #
# ------------------------------------------------------------------ #

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


async def fetch_spawn_rates(session: aiohttp.ClientSession = None, force: bool = False) -> Dict[str, dict]:
    global _spawn_rate_cache
    if _spawn_rate_cache is not None and not force:
        return _spawn_rate_cache

    if session is not None:
        async with session.get(SPAWN_RATE_CSV_URL) as response:
            response.raise_for_status()
            text = await response.text(encoding="utf-8")
    else:
        async with aiohttp.ClientSession() as _tmp_session:
            async with _tmp_session.get(SPAWN_RATE_CSV_URL) as response:
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
    Returns the streak, or -1 if unreachable within a safe upper bound.
    """
    target = target_pct / 100
    fn = shiny_prob_charm if charm else shiny_prob

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
#  Shiny rate embed builders                                           #
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


def _shiny_usage_embed() -> discord.Embed:
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
#  Time difference helpers                                             #
# ------------------------------------------------------------------ #

async def _resolve_message(
    channel: discord.TextChannel, message_id: int
) -> Optional[discord.Message]:
    """Fetch a message by ID from the given channel. Returns None if not found."""
    try:
        return await channel.fetch_message(message_id)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _get_previous_message(
    channel: discord.TextChannel, reference_message: discord.Message
) -> Optional[discord.Message]:
    """
    Return the message posted immediately before `reference_message`.
    Uses channel.history(before=) — no manual cache needed.
    """
    async for msg in channel.history(before=reference_message, limit=1):
        return msg
    return None


def _build_timediff_embed(msg1: discord.Message, msg2: discord.Message) -> discord.Embed:
    """Build an embed showing the time difference between two messages."""
    earlier, later = (msg1, msg2) if msg1.created_at < msg2.created_at else (msg2, msg1)

    delta = later.created_at - earlier.created_at
    total_seconds = delta.total_seconds()
    total_ms = int(delta.total_seconds() * 1000)

    if total_seconds < 60:
        seconds_str = f"{total_seconds:.3f}s"
    elif total_seconds < 3600:
        minutes = int(total_seconds // 60)
        secs = total_seconds % 60
        seconds_str = f"{minutes}m {secs:.3f}s  ({total_seconds:.3f}s total)"
    else:
        hours = int(total_seconds // 3600)
        remaining = total_seconds % 3600
        minutes = int(remaining // 60)
        secs = remaining % 60
        seconds_str = f"{hours}h {minutes}m {secs:.3f}s  ({total_seconds:.3f}s total)"

    embed = discord.Embed(title="⏱️ Time Difference", color=EMBED_COLOR)
    embed.add_field(
        name="Earlier Message",
        value=(
            f"[Jump]({earlier.jump_url})\n"
            f"ID: `{earlier.id}`\n"
            f"By: {earlier.author.mention}\n"
            f"<t:{int(earlier.created_at.timestamp())}:F>"
        ),
        inline=True,
    )
    embed.add_field(
        name="Later Message",
        value=(
            f"[Jump]({later.jump_url})\n"
            f"ID: `{later.id}`\n"
            f"By: {later.author.mention}\n"
            f"<t:{int(later.created_at.timestamp())}:F>"
        ),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
    embed.add_field(name="Seconds",      value=f"`{seconds_str}`",   inline=True)
    embed.add_field(name="Milliseconds", value=f"`{total_ms:,} ms`", inline=True)
    return embed


# ------------------------------------------------------------------ #
#  Cog                                                                 #
# ------------------------------------------------------------------ #

class PokeTools(commands.Cog, name="PokeTools"):
    """Spawn rates, shiny rates, and message utilities for Pokétwo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    # ================================================================ #
    #  Spawn rate                                                        #
    # ================================================================ #

    @app_commands.command(name="spawnrate", description="Show the spawn rate for a Pokémon.")
    @app_commands.describe(pokemon="Pokémon name (English, Japanese, or other language)")
    async def spawnrate_slash(self, interaction: discord.Interaction, pokemon: str):
        await interaction.response.defer()

        matched = find_pokemon_by_name_flexible(pokemon, self.pokemon_data)
        canonical_name = matched["name"] if matched else pokemon.strip()

        try:
            spawn_data = await fetch_spawn_rates(session=self.bot.http_session)
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
        embed.add_field(name="Spawn Chance", value=entry["chance"],     inline=True)
        embed.add_field(name="Percentage",   value=entry["chance_pct"], inline=True)
        if pokemon.strip().lower() != entry["name"].lower():
            embed.set_footer(text=f'Searched: "{pokemon.strip()}"')
        await interaction.followup.send(embed=embed)

    @commands.command(name="spawnrate", aliases=["sr"])
    async def spawnrate_prefix(self, ctx: commands.Context, *, pokemon_name: str = None):
        """Show the spawn rate for a Pokémon. Usage: p!sr <pokemon>"""
        if not pokemon_name:
            await ctx.send("Please provide a Pokémon name. Example: `p!sr geodude`")
            return

        async with ctx.typing():
            matched = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
            canonical_name = matched["name"] if matched else pokemon_name.strip()

            try:
                spawn_data = await fetch_spawn_rates(session=self.bot.http_session)
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
            embed.add_field(name="Spawn Chance", value=entry["chance"],     inline=True)
            embed.add_field(name="Percentage",   value=entry["chance_pct"], inline=True)
            if pokemon_name.strip().lower() != entry["name"].lower():
                embed.set_footer(text=f'Searched: "{pokemon_name.strip()}"')
            await ctx.send(embed=embed)

    # ================================================================ #
    #  Shiny rate                                                        #
    # ================================================================ #

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
            await interaction.response.send_message(embed=_shiny_usage_embed())
            return

        embeds = []
        if chain is not None:
            embeds.append(_build_shiny_rate_embed(chain))
        if target is not None:
            embeds.append(_build_chain_target_embed(target))

        await interaction.response.send_message(embeds=embeds)

    @commands.command(name="shinyrate", aliases=["shr"])
    async def shinyrate_prefix(self, ctx: commands.Context, *, args: str = None):
        """
        Show shiny rates or encounters needed for a target cumulative chance.
        Usage: p!shr [chain] [target%]
        """
        if not args:
            await ctx.send(embed=_shiny_usage_embed())
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
                embeds.append(_shiny_usage_embed())

            await ctx.send(embeds=embeds)

    # ================================================================ #
    #  Time difference                                                   #
    # ================================================================ #

    async def _resolve_pair(
        self,
        channel: discord.TextChannel,
        id1: Optional[int],
        id2: Optional[int],
        reply_ref: Optional[discord.MessageReference],
    ) -> tuple[Optional[discord.Message], Optional[discord.Message], Optional[str]]:
        """
        Resolve the two messages to compare.
        Returns (msg_a, msg_b, error_string). error_string is None on success.

        Modes:
          - reply / one id  → target message + the message before it
          - two ids         → the two specified messages directly
        """
        # Two explicit IDs
        if id1 is not None and id2 is not None:
            msg_a = await _resolve_message(channel, id1)
            if msg_a is None:
                return None, None, f"❌ Could not find message with ID `{id1}` in this channel."
            msg_b = await _resolve_message(channel, id2)
            if msg_b is None:
                return None, None, f"❌ Could not find message with ID `{id2}` in this channel."
            return msg_a, msg_b, None

        # One explicit ID → find the message before it
        if id1 is not None:
            target = await _resolve_message(channel, id1)
            if target is None:
                return None, None, f"❌ Could not find message with ID `{id1}` in this channel."
            prev = await _get_previous_message(channel, target)
            if prev is None:
                return None, None, "❌ Could not find a message before that one."
            return target, prev, None

        # Reply mode → use the replied-to message and the one before it
        if reply_ref is not None:
            target = await _resolve_message(channel, reply_ref.message_id)
            if target is None:
                return None, None, "❌ Could not fetch the replied-to message."
            prev = await _get_previous_message(channel, target)
            if prev is None:
                return None, None, "❌ Could not find a message before the replied-to message."
            return target, prev, None

        return None, None, (
            "❌ Please either:\n"
            "• Reply to a message with `p!td`\n"
            "• Provide one message ID: `p!td <id>`\n"
            "• Provide two message IDs: `p!td <id1> <id2>`"
        )

    @app_commands.command(
        name="timedifference",
        description="Find the time difference between two messages.",
    )
    @app_commands.describe(
        message_id="A single message ID (finds the message before it), or leave blank when replying",
        message_id2="Second message ID — compare directly with message_id",
    )
    async def timedifference_slash(
        self,
        interaction: discord.Interaction,
        message_id: Optional[str] = None,
        message_id2: Optional[str] = None,
    ):
        await interaction.response.defer()

        id1, id2 = None, None
        if message_id is not None:
            try:
                id1 = int(message_id)
            except ValueError:
                await interaction.followup.send("❌ `message_id` must be a valid integer ID.")
                return
        if message_id2 is not None:
            try:
                id2 = int(message_id2)
            except ValueError:
                await interaction.followup.send("❌ `message_id2` must be a valid integer ID.")
                return

        msg_a, msg_b, error = await self._resolve_pair(interaction.channel, id1, id2, reply_ref=None)
        if error:
            await interaction.followup.send(error)
            return

        await interaction.followup.send(embed=_build_timediff_embed(msg_a, msg_b))

    @commands.command(name="timedifference", aliases=["timediff", "td"])
    async def timedifference_prefix(
        self,
        ctx: commands.Context,
        id1: Optional[int] = None,
        id2: Optional[int] = None,
    ):
        """
        Find the time difference between two messages.

        Usage:
          p!td                — reply to a message; compares it with the one above it
          p!td <id>           — compares <id> with the message above it
          p!td <id1> <id2>    — compares the two messages directly

        Aliases: p!timediff, p!timedifference
        """
        async with ctx.typing():
            reply_ref = ctx.message.reference if ctx.message.reference else None
            msg_a, msg_b, error = await self._resolve_pair(ctx.channel, id1, id2, reply_ref)
            if error:
                await ctx.send(error)
                return

            await ctx.send(embed=_build_timediff_embed(msg_a, msg_b))

    # ================================================================ #
    #  Owner utilities                                                   #
    # ================================================================ #

    @commands.command(name="reloadsr")
    @commands.is_owner()
    async def reloadsr(self, ctx: commands.Context):
        """Force-reload the spawn rate data from the gist. Owner only."""
        async with ctx.typing():
            try:
                old_count = len(_spawn_rate_cache) if _spawn_rate_cache else 0
                data = await fetch_spawn_rates(session=self.bot.http_session, force=True)
                new_count = len(data)
            except Exception as e:
                await ctx.send(f"❌ Failed to reload spawn rate data: `{e}`")
                return

        embed = discord.Embed(title="✅ Spawn Rate Data Reloaded", color=EMBED_COLOR)
        embed.add_field(name="Entries before", value=str(old_count), inline=True)
        embed.add_field(name="Entries now",    value=str(new_count), inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(PokeTools(bot))
