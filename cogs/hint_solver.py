"""Hint solver cog — automatically solves Pokétwo hint messages"""
import re
import discord
from discord.ext import commands
from typing import List, Optional
from utils import load_pokemon_data, normalize_pokemon_name
from config import POKETWO_USER_ID


def build_hint_regex(hint: str) -> re.Pattern:
    """
    Convert a Pokétwo hint string like "V_ro__." into a regex that
    matches candidate names character-by-character.

    Rules:
      - Revealed characters match exactly (case-insensitive).
      - '_' matches exactly one character (any).
      - Spaces, hyphens and apostrophes in the hint match the same
        literal character in the name (Pokétwo preserves them).
      - The trailing punctuation (period / exclamation mark) is stripped
        before processing.
    """
    # Strip leading/trailing whitespace and remove trailing sentence punctuation
    cleaned = hint.strip().rstrip(".!")

    pattern_parts = []
    for ch in cleaned:
        if ch == "_":
            # Wildcard — one of any character
            pattern_parts.append(r".")
        elif ch in (" ", "-", "'", "\u2019"):
            # Literal separator — escape and require exact match
            pattern_parts.append(re.escape(ch))
        else:
            # Revealed letter — match exactly (case-insensitive flag set later)
            pattern_parts.append(re.escape(ch))

    return re.compile("^" + "".join(pattern_parts) + "$", re.IGNORECASE)


def extract_hint(message_content: str) -> Optional[str]:
    """
    Pull the hint pattern out of a Pokétwo message such as:
        'The pokémon is V_ro__.'
    Returns the raw hint string (e.g. 'V_ro__') or None if not found.
    """
    # Match the standard Pokétwo hint format in any language direction
    match = re.search(
        r"[Tt]he\s+pok[eé]mon\s+is\s+(.+?)\.",
        message_content,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return None


def get_all_names(pokemon: dict) -> List[str]:
    """
    Return every name (English + all other_names entries) for a Pokémon
    so we can match hints written in any language.
    """
    names: List[str] = []

    english_name = pokemon.get("name", "")
    if english_name:
        names.append(english_name)

    other = pokemon.get("other_names")
    if isinstance(other, dict):
        for value in other.values():
            if isinstance(value, str):
                names.append(value)
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, str):
                        names.append(v)

    return names


def solve_hint(hint: str, pokemon_data: list) -> List[dict]:
    """
    Return all Pokémon whose name (in any language) matches the hint pattern.
    Each result dict contains the matched Pokémon entry plus which name matched.
    """
    pattern = build_hint_regex(hint)
    matches = []

    for pokemon in pokemon_data:
        for name in get_all_names(pokemon):
            if pattern.match(name):
                matches.append({
                    "pokemon": pokemon,
                    "matched_name": name,
                })
                break  # one match per Pokémon is enough

    return matches


class HintSolver(commands.Cog):
    """Automatically solves Pokétwo hint messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Only react to messages from Pokétwo
        if message.author.id != POKETWO_USER_ID:
            return

        content = message.content
        if not content:
            return

        hint = extract_hint(content)
        if hint is None:
            return

        matches = solve_hint(hint, self.pokemon_data)

        if not matches:
            await message.reply(
                f"🔍 Hint: `{hint}` — no matching Pokémon found.",
                mention_author=False,
            )
            return

        if len(matches) == 1:
            poke = matches[0]["pokemon"]
            matched_name = matches[0]["matched_name"]
            english_name = poke.get("name", matched_name)
            dex = poke.get("dex_number", "?")

            embed = discord.Embed(
                title=f"💡 It's **{english_name}**!",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Pokédex #", value=f"#{dex}", inline=True)
            embed.add_field(name="Hint", value=f"`{hint}`", inline=True)

            # Show the matched non-English name if the hint was in another language
            if matched_name.lower() != english_name.lower():
                embed.add_field(
                    name="Matched name",
                    value=matched_name,
                    inline=True,
                )

            embed.set_thumbnail(url=f"https://cdn.poketwo.net/images/{dex}.png")
            await message.reply(embed=embed, mention_author=False)

        else:
            # Multiple candidates — list them all
            lines = []
            for m in matches:
                poke = m["pokemon"]
                english_name = poke.get("name", m["matched_name"])
                dex = poke.get("dex_number", "?")
                matched_name = m["matched_name"]

                line = f"• **{english_name}** (#{dex})"
                if matched_name.lower() != english_name.lower():
                    line += f" — matched as *{matched_name}*"
                lines.append(line)

            embed = discord.Embed(
                title=f"💡 {len(matches)} possible matches for `{hint}`",
                description="\n".join(lines),
                color=discord.Color.orange(),
            )
            await message.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(HintSolver(bot))
