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
    # Strip leading/trailing whitespace. Note: we deliberately do NOT strip a
    # trailing "." here — some Pokémon names legitimately end in a period
    # (e.g. "Mime Jr."), and extract_hint() is responsible for making sure
    # only the real sentence-ending period (if any) is excluded already.
    cleaned = hint.strip()

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
        'The pokémon is \\_\\_\\_v\\_tar.'
    Pokétwo escapes underscores as \\_ to prevent Discord italic formatting,
    so we unescape them back to plain _ before returning.
    Returns the raw hint string (e.g. '___v_tar') or None if not found.
    """
    # Greedy capture: matches up to the LAST period in the message, so a
    # name containing its own period (e.g. "Mime Jr.") isn't cut short at
    # that internal period before reaching the sentence-ending one.
    match = re.search(
        r"[Tt]he\s+pok[eé]mon\s+is\s+(.+)\.",
        message_content,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        hint = match.group(1).strip()
        # Unescape Discord markdown: \_ → _
        hint = hint.replace("\\_", "_")
        return hint
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

        # Check if hint solver is enabled for this guild
        if message.guild:
            enabled = await self.bot.db.get_hint_solver(message.guild.id)
            if not enabled:
                return

        hint = extract_hint(content)
        if hint is None:
            return

        matches = solve_hint(hint, self.pokemon_data)

        if not matches:
            await message.reply(
                f"🔍 No matching Pokémon found for `{hint}`.",
                mention_author=False,
            )
            return

        if len(matches) == 1:
            english_name = matches[0]["pokemon"].get("name", matches[0]["matched_name"])
            matched_name = matches[0]["matched_name"]
            if matched_name.lower() != english_name.lower():
                await message.reply(
                    f"This pokémon is **{english_name}** ({matched_name})",
                    mention_author=False,
                )
            else:
                await message.reply(f"It's **{english_name}**", mention_author=False)

        else:
            parts = []
            for m in matches:
                english_name = m["pokemon"].get("name", m["matched_name"])
                matched_name = m["matched_name"]
                if matched_name.lower() != english_name.lower():
                    parts.append(f"{english_name} ({matched_name})")
                else:
                    parts.append(english_name)
            await message.reply(
                f"It's one of these: **{', '.join(parts)}**",
                mention_author=False,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(HintSolver(bot))
