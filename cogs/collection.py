"""Collection management commands"""
import csv
import discord
import math
import asyncio
import re
from discord import app_commands
from discord.ext import commands
from typing import List, Dict
from utils import (
    load_pokemon_data,
    find_pokemon_by_name_flexible,
    normalize_pokemon_name,
    get_pokemon_with_variants,
    is_rare_pokemon,
)
from config import EMBED_COLOR, ITEMS_PER_PAGE, MAX_DISPLAY_ITEMS

NO_MENTIONS = discord.AllowedMentions.none()

SR_DATA_PATH = "data/spawnrate.csv"

def load_spawnrate_data() -> Dict[int, List[str]]:
    """Load spawnrate.csv and return a dict of {denominator: [pokemon_names]}.

    The CSV has columns: Dex, Pokemon, Chance, Chance percentage
    The Chance column is formatted as '1/225', '1/337', etc.
    """
    sr_map: Dict[int, List[str]] = {}
    try:
        with open(SR_DATA_PATH, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                chance = row.get('Chance', '').strip()
                name = row.get('Pokemon', '').strip()
                if not chance or not name:
                    continue
                # Parse denominator from '1/225'
                parts = chance.split('/')
                if len(parts) == 2:
                    try:
                        denom = int(parts[1])
                        sr_map.setdefault(denom, []).append(name)
                    except ValueError:
                        pass
    except Exception as e:
        print(f"[DATA] Could not load spawnrate.csv: {e}")
    return sr_map

class CollectionPaginationView(discord.ui.View):
    def __init__(self, user_id, guild_id, current_page, total_pages, cog):
        super().__init__(timeout=60)  # reduced from 300
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.cog = cog
        self.message: discord.Message | None = None

        self.previous_button.disabled = (current_page <= 1)
        self.next_button.disabled = (current_page >= total_pages)

    @discord.ui.button(label="", emoji="◀️", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = max(1, self.current_page - 1)
        embed = await self.cog.create_collection_embed(self.user_id, self.guild_id, new_page)

        if embed:
            self.current_page = new_page
            self.previous_button.disabled = (new_page <= 1)
            self.next_button.disabled = (new_page >= self.total_pages)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="", emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        new_page = min(self.total_pages, self.current_page + 1)
        embed = await self.cog.create_collection_embed(self.user_id, self.guild_id, new_page)

        if embed:
            self.current_page = new_page
            self.previous_button.disabled = (new_page <= 1)
            self.next_button.disabled = (new_page >= self.total_pages)
            await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        self.clear_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.message = None
        self.cog = None

class RawPaginationView(discord.ui.View):
    """Paginator for cl raw output."""

    def __init__(self, user_id: int, pages: List[str], title: str, header: str):
        super().__init__(timeout=60)  # reduced from 300
        self.user_id = user_id
        self.pages = pages
        self.title = title
        self.header = header
        self.current_page = 1
        self.total_pages = len(pages)
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.previous_button.disabled = (self.current_page <= 1)
        self.next_button.disabled = (self.current_page >= self.total_pages)

    def build_embed(self, page: int) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=f"{self.header}\n{self.pages[page - 1]}",
            color=EMBED_COLOR
        )
        embed.set_footer(text=f"Page {page}/{self.total_pages}")
        return embed

    @discord.ui.button(label="", emoji="\u25c0\ufe0f", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        self.current_page = max(1, self.current_page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    @discord.ui.button(label="", emoji="\u25b6\ufe0f", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        self.current_page = min(self.total_pages, self.current_page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    async def on_timeout(self):
        self.clear_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.message = None
        self.pages = []  # release text page strings from memory


def _paginate_raw_text(text_content: str, max_chars: int = 3800) -> List[str]:
    """Split SR-grouped raw text into embed-sized pages.

    Never splits a tier line across pages. If a single tier line exceeds
    max_chars it goes on its own page.
    """
    tier_lines = text_content.split("\n\n")
    pages: List[str] = []
    current_chunks: List[str] = []
    current_len = 0

    for line in tier_lines:
        needed = len(line) + (2 if current_chunks else 0)  # +2 for \n\n separator
        if current_chunks and current_len + needed > max_chars:
            pages.append("\n\n".join(current_chunks))
            current_chunks = [line]
            current_len = len(line)
        else:
            current_chunks.append(line)
            current_len += needed

    if current_chunks:
        pages.append("\n\n".join(current_chunks))

    return pages


class Collection(commands.Cog):
    """Collection management commands"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()
        self.spawnrate_data = load_spawnrate_data()

    @property
    def db(self):
        """Get database from bot"""
        return self.bot.db

    async def create_collection_embed(self, user_id: int, guild_id: int, page: int = 1) -> discord.Embed:
        """Create paginated collection embed"""
        collection = await self.db.get_user_collection(user_id, guild_id)

        if not collection:
            embed = discord.Embed(
                title="📦 Your Collection",
                description="Your collection is empty! Start adding Pokémon with `p!cl add <pokemon>`",
                color=EMBED_COLOR
            )
            return embed

        pokemon_list = sorted(collection)
        total_pages = math.ceil(len(pokemon_list) / ITEMS_PER_PAGE)
        page = max(1, min(page, total_pages))

        start_index = (page - 1) * ITEMS_PER_PAGE
        end_index = start_index + ITEMS_PER_PAGE
        page_pokemon = pokemon_list[start_index:end_index]

        description = "\n".join([f"• {pokemon}" for pokemon in page_pokemon])

        embed = discord.Embed(
            title="📦 Your Collection for this Server",
            description=description,
            color=EMBED_COLOR
        )

        embed.set_footer(
            text=f"Showing {start_index + 1}-{min(end_index, len(pokemon_list))} of {len(pokemon_list)} Pokémon • Page {page}/{total_pages}"
        )

        return embed

    @commands.group(name="cl", invoke_without_command=True)
    async def collection_group(self, ctx):
        """Collection management commands"""
        if ctx.invoked_subcommand is None:
            await ctx.reply("Usage: `p!cl [add/remove/clear/list/raw]`", mention_author=False)

    @collection_group.command(name="add")
    async def collection_add(self, ctx, *, pokemon_names: str):
        """Add Pokemon to your collection

        Examples:
            p!cl add Pikachu
            p!cl add Pikachu, Charizard, Mewtwo
            p!cl add Furfrou all  (adds all Furfrou variants)
        """
        names_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not names_list:
            await ctx.reply("No valid Pokemon names provided", mention_author=False)
            return

        added_pokemon = []
        invalid_pokemon = []
        has_forms_hints = []  # Pokemon that have forms but were added as single

        for name in names_list:
            # Normalize: support both "furfrou all" and "all furfrou"
            name_lower = name.lower()
            is_all = name_lower.endswith(" all") or name_lower.startswith("all ")

            if is_all:
                # Strip "all" from either end
                if name_lower.startswith("all "):
                    base_name = name[4:].strip()
                else:
                    base_name = name[:-4].strip()

                variants = get_pokemon_with_variants(base_name, self.pokemon_data)

                if variants:
                    added_pokemon.extend(variants)
                else:
                    invalid_pokemon.append(name)
            else:
                # Single Pokemon
                pokemon = find_pokemon_by_name_flexible(name, self.pokemon_data)

                if pokemon and pokemon.get('name'):
                    added_pokemon.append(pokemon['name'])
                    # Check if this pokemon has other forms/variants
                    base_name = pokemon['name']
                    variants = get_pokemon_with_variants(base_name, self.pokemon_data)
                    if variants and len(variants) > 1:
                        has_forms_hints.append(base_name)
                else:
                    invalid_pokemon.append(name)

        if not added_pokemon:
            error_msg = "No valid Pokemon names found"
            if invalid_pokemon:
                error_msg += f". Invalid: {', '.join(invalid_pokemon[:10])}"
                if len(invalid_pokemon) > 10:
                    error_msg += f" and {len(invalid_pokemon) - 10} more..."
            await ctx.reply(error_msg, mention_author=False)
            return

        await self.db.add_pokemon_to_collection(ctx.author.id, ctx.guild.id, added_pokemon)

        # Format response with character limit safety
        response = f"✅ Added {len(added_pokemon)} Pokémon"

        # Show names: all if ≤ 10, otherwise first 10 + "and X more"
        if len(added_pokemon) <= 10:
            response += f": {', '.join(added_pokemon)}"
        else:
            response += f": {', '.join(added_pokemon[:10])} and {len(added_pokemon) - 10} more"

        # Add invalid pokemon info if any
        if invalid_pokemon:
            invalid_text = f"\n\n❌ Invalid: "
            if len(invalid_pokemon) <= 10:
                invalid_text += ", ".join(invalid_pokemon)
            else:
                invalid_text += f"{', '.join(invalid_pokemon[:10])} and {len(invalid_pokemon) - 10} more"

            if len(response) + len(invalid_text) < 1900:
                response += invalid_text
            else:
                response += f"\n❌ {len(invalid_pokemon)} invalid Pokémon names"

        # Hint about Pokemon with forms
        # Sort: pokemon whose variants include regional forms go to the end
        REGIONAL_KEYWORDS = {"alolan", "galarian", "hisuian", "paldean"}

        def has_only_regional_forms(base_name):
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)
            if not variants:
                return False
            non_base = [v.lower() for v in variants if v.lower() != base_name.lower()]
            return non_base and all(
                any(region in v for region in REGIONAL_KEYWORDS) for v in non_base
            )

        has_forms_hints.sort(key=lambda n: (1 if has_only_regional_forms(n) else 0, n))

        if has_forms_hints:
            hints = ", ".join(has_forms_hints)
            hint_cmds = ", ".join([f"{n} all" for n in has_forms_hints])
            forms_text = f"\n\n> -# **{hints}** {'has' if len(has_forms_hints) == 1 else 'have'} other forms! To add all forms use: `{hint_cmds}`"
            if len(response) + len(forms_text) < 1900:
                response += forms_text
            else:
                response += f"\n💡 {len(has_forms_hints)} Pokémon in your list have other forms. Use `<name> all` to add all forms."

        await ctx.reply(response, mention_author=False)

    @collection_group.command(name="remove")
    async def collection_remove(self, ctx, *, pokemon_names: str):
        """Remove Pokemon from your collection

        Examples:
            p!cl remove Pikachu
            p!cl remove Pikachu, Charizard
            p!cl remove Furfrou all          (removes all Furfrou variants)
            p!cl remove all Furfrou          (same as above)
            p!cl remove --sr 899             (removes all Pokemon with spawn rate 1/899)
            p!cl remove --sr 225 --sr 337    (multiple spawn rates at once)
            p!cl remove Pikachu, --sr 899    (mix of names and spawn rates)
            p!cl remove --user @someone      (removes everything that user has in their collection)
        """
        # ── 1. Extract --user flag ─────────────────────────────────────────
        # Accepts a mention (@user), or a raw user ID
        user_match = re.search(r'--user\s+(?:<@!?(\d+)>|(\d{15,20}))', pokemon_names)
        target_user_id = None
        if user_match:
            target_user_id = int(user_match.group(1) or user_match.group(2))
            pokemon_names = re.sub(r'--user\s+(?:<@!?\d+>|\d{15,20})', '', pokemon_names).strip().strip(',').strip()

        # ── 2. Extract --sr flags ──────────────────────────────────────────
        sr_values = [int(m) for m in re.findall(r'--sr\s+(\d+)', pokemon_names)]
        cleaned_input = re.sub(r'--sr\s+\d+', '', pokemon_names).strip().strip(',').strip()

        removed_pokemon = []
        not_found_pokemon = []
        unknown_sr = []

        # ── 3. Resolve --user → the overlap between your collection and theirs ─
        if target_user_id is not None:
            if target_user_id == ctx.author.id:
                await ctx.reply("You can't use `--user` with yourself.", mention_author=False)
                return
            other_collection = await self.db.get_user_collection(target_user_id, ctx.guild.id)
            if not other_collection:
                await ctx.reply(
                    f"<@{target_user_id}> has no Pokémon in their collection for this server, so nothing was removed from yours.",
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
                return

            # Only Pokemon that are in BOTH your collection and theirs should
            # be reported/removed - not their entire collection.
            own_collection = await self.db.get_user_collection(ctx.author.id, ctx.guild.id)
            own_lower = {p.lower() for p in (own_collection or [])}
            common_pokemon = [p for p in other_collection if p.lower() in own_lower]

            if not common_pokemon:
                await ctx.reply(
                    f"You and <@{target_user_id}> have no Pokémon in common, so nothing was removed.",
                    mention_author=False,
                    allowed_mentions=NO_MENTIONS,
                )
                return

            removed_pokemon.extend(common_pokemon)

        # ── 4. Resolve --sr values → Pokemon names ─────────────────────────
        for sr in sr_values:
            sr_names = self.spawnrate_data.get(sr)
            if sr_names:
                removed_pokemon.extend(sr_names)
            else:
                unknown_sr.append(sr)

        # ── 5. Resolve explicit Pokemon names (if any remain after stripping) ─
        if cleaned_input:
            names_list = [name.strip() for name in cleaned_input.split(",") if name.strip()]

            for name in names_list:
                name_lower = name.lower()
                is_all = name_lower.endswith(" all") or name_lower.startswith("all ")

                if is_all:
                    if name_lower.startswith("all "):
                        base_name = name[4:].strip()
                    else:
                        base_name = name[:-4].strip()

                    variants = get_pokemon_with_variants(base_name, self.pokemon_data)
                    if variants:
                        removed_pokemon.extend(variants)
                    else:
                        not_found_pokemon.append(name)
                else:
                    pokemon = find_pokemon_by_name_flexible(name, self.pokemon_data)
                    if pokemon and pokemon.get('name'):
                        removed_pokemon.append(pokemon['name'])
                    else:
                        not_found_pokemon.append(name)

        # ── 6. Validate we have something to remove ────────────────────────
        if not removed_pokemon:
            parts = []
            if not target_user_id and not sr_values and not cleaned_input:
                parts.append("No valid Pokemon names, `--sr` flags, or `--user` provided")
            else:
                parts.append("No valid Pokemon found to remove")
            if unknown_sr:
                parts.append(f"Unknown spawn rates: {', '.join(f'1/{s}' for s in unknown_sr)}")
            if not_found_pokemon:
                parts.append(f"Invalid names: {', '.join(not_found_pokemon[:30])}")
            await ctx.reply("\n".join(parts), mention_author=False)
            return

        # Deduplicate while preserving order
        seen = set()
        unique_removed = []
        for p in removed_pokemon:
            key = p.lower()
            if key not in seen:
                seen.add(key)
                unique_removed.append(p)
        removed_pokemon = unique_removed

        # ── 7. Remove from DB ──────────────────────────────────────────────
        modified = await self.db.remove_pokemon_from_collection(
            ctx.author.id, ctx.guild.id, removed_pokemon
        )

        # ── 8. Build response ──────────────────────────────────────────────
        if modified:
            sr_label = ""
            if sr_values:
                sr_label = f" (SR: {', '.join(f'1/{s}' for s in sr_values)})"
            if target_user_id:
                user_prefix = f"✅ Removed {len(removed_pokemon)}"
                user_prefix += f" Pokémon{sr_label} that <@{target_user_id}> has"
                if len(removed_pokemon) <= MAX_DISPLAY_ITEMS:
                    response = f"{user_prefix} from your collection: {', '.join(removed_pokemon)}"
                else:
                    response = (
                        f"{user_prefix} from your collection: "
                        f"{', '.join(removed_pokemon[:MAX_DISPLAY_ITEMS])} "
                        f"and {len(removed_pokemon) - MAX_DISPLAY_ITEMS} more…"
                    )
            else:
                if len(removed_pokemon) <= MAX_DISPLAY_ITEMS:
                    response = f"✅ Removed {len(removed_pokemon)} Pokémon{sr_label}: {', '.join(removed_pokemon)}"
                else:
                    response = (
                        f"✅ Removed {len(removed_pokemon)} Pokémon{sr_label}: "
                        f"{', '.join(removed_pokemon[:MAX_DISPLAY_ITEMS])} "
                        f"and {len(removed_pokemon) - MAX_DISPLAY_ITEMS} more…"
                    )

            if unknown_sr:
                response += f"\n⚠️ Unknown spawn rates (no matches): {', '.join(f'1/{s}' for s in unknown_sr)}"
            if not_found_pokemon:
                response += f"\n❌ Invalid names: {', '.join(not_found_pokemon[:30])}"

            await ctx.reply(response, mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            sr_label = f" with SR {', '.join(f'1/{s}' for s in sr_values)}" if sr_values else ""
            if target_user_id:
                msg = f"None of <@{target_user_id}>'s Pokémon{sr_label} were found in your collection — nothing was removed."
            else:
                msg = f"No Pokémon{sr_label} were removed (they might not be in your collection)."
            await ctx.reply(msg, mention_author=False, allowed_mentions=NO_MENTIONS)

    @collection_group.command(name="clear")
    async def collection_clear(self, ctx):
        """Clear your entire collection"""
        cleared = await self.db.clear_collection(ctx.author.id, ctx.guild.id)

        if cleared:
            await ctx.reply("✅ Collection cleared successfully", mention_author=False)
        else:
            await ctx.reply("Your collection is already empty", mention_author=False)

    @collection_group.command(name="list")
    async def collection_list(self, ctx):
        """List your Pokemon collection in a paginated embed"""
        embed = await self.create_collection_embed(ctx.author.id, ctx.guild.id, 1)

        collection = await self.db.get_user_collection(ctx.author.id, ctx.guild.id)

        if collection:
            total_pages = math.ceil(len(collection) / ITEMS_PER_PAGE)

            if total_pages > 1:
                view = CollectionPaginationView(ctx.author.id, ctx.guild.id, 1, total_pages, self)
                msg = await ctx.reply(embed=embed, view=view, mention_author=False)
                view.message = msg
            else:
                await ctx.reply(embed=embed, mention_author=False)
        else:
            await ctx.reply(embed=embed, mention_author=False)

    def _format_collection_by_sr(
        self, collection: List[str], sr_filter: List[int] = None
    ) -> str:
        """Format a collection grouped by spawn rate tier.

        Each tier becomes one line of comma-separated names with a trailing
        comma.  Tiers are separated by a blank line.  Order within a tier
        follows the CSV row order.  Pokemon not found in the CSV are placed
        last in an 'unknown' group (only shown when no sr_filter is active).

        Args:
            collection:  The user's full collection list.
            sr_filter:   If provided, only tiers whose denominator is in this
                         list are included.  e.g. [899] or [225, 337].

        Example output (no filter):
            Aron, Bramblin, Wurmple,

            Charmander, Squirtle, Bulbasaur,

            Amaura, Zorua, Meowth,

        Example output (sr_filter=[899]):
            Amaura, Zorua, Meowth,
        """
        # Build name->denominator lookup (case-insensitive)
        name_to_denom: Dict[str, int] = {}
        for denom, names in self.spawnrate_data.items():
            for name in names:
                name_to_denom[name.lower()] = denom

        # Build CSV position map for within-tier ordering
        csv_position: Dict[str, int] = {}
        pos = 0
        for names in self.spawnrate_data.values():
            for name in names:
                csv_position[name.lower()] = pos
                pos += 1

        # Bucket each collection entry by denominator
        denom_to_entries: Dict[int, List[str]] = {}
        unknown: List[str] = []

        for name_stored in collection:
            denom = name_to_denom.get(name_stored.lower())
            if denom is not None:
                denom_to_entries.setdefault(denom, []).append(name_stored)
            else:
                unknown.append(name_stored)

        # Sort within each tier by CSV row order
        for denom in denom_to_entries:
            denom_to_entries[denom].sort(
                key=lambda n: csv_position.get(n.lower(), 999999)
            )

        # Sort unknown alphabetically
        unknown.sort()

        # Determine which tiers to emit
        filter_set = set(sr_filter) if sr_filter else None

        lines = []
        for denom in sorted(denom_to_entries.keys()):
            if filter_set and denom not in filter_set:
                continue
            entries = denom_to_entries[denom]
            lines.append(", ".join(entries) + ",")

        # Only show unknown bucket when not filtering by specific SR
        if not filter_set and unknown:
            lines.append(", ".join(unknown) + ",")

        return "\n\n".join(lines)

    @collection_group.command(name="raw")
    async def collection_raw(self, ctx, *, args: str = ""):
        """View your collection as raw text, grouped by spawn rate tier.

        Each spawn rate tier is on its own line, names comma-separated with a
        trailing comma.  Tiers are separated by a blank line.  Sent as a text
        file when the output is large.

        Examples:
            p!cl raw
            p!cl raw --sr 899
            p!cl raw --sr 225 --sr 337
        """
        collection = await self.db.get_user_collection(ctx.author.id, ctx.guild.id)

        if not collection:
            await ctx.reply("Your collection is empty!", mention_author=False)
            return

        # Parse --sr flags
        sr_filter = [int(m) for m in re.findall(r'--sr\s+(\d+)', args)]

        # Validate requested SRs exist in the CSV
        unknown_srs = [sr for sr in sr_filter if sr not in self.spawnrate_data]
        if unknown_srs:
            await ctx.reply(
                f"❌ Unknown spawn rate(s): {', '.join(f'1/{s}' for s in unknown_srs)}",
                mention_author=False
            )
            return

        text_content = self._format_collection_by_sr(collection, sr_filter or None)
        total = len(collection)

        if not text_content:
            if sr_filter:
                sr_label = ", ".join(f"1/{s}" for s in sr_filter)
                await ctx.reply(
                    f"You have no Pokémon with spawn rate {sr_label} in your collection.",
                    mention_author=False
                )
            else:
                await ctx.reply("Your collection is empty!", mention_author=False)
            return

        # Title / header reflect filter state
        if sr_filter:
            sr_label = ", ".join(f"1/{s}" for s in sr_filter)
            matched_names = set()
            for sr in sr_filter:
                for name in (self.spawnrate_data.get(sr) or []):
                    matched_names.add(name.lower())
            shown = sum(1 for p in collection if p.lower() in matched_names)
            title = f"📦 Collection — SR {sr_label}"
            header = f"**{shown} Pokémon (SR {sr_label}):**"
        else:
            title = "📦 Your Collection"
            header = f"**{total} Pokémon:**"

        # Paginate and send
        pages = _paginate_raw_text(text_content)

        if len(pages) == 1:
            embed = discord.Embed(
                title=title,
                description=f"{header}\n{pages[0]}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)
        else:
            view = RawPaginationView(ctx.author.id, pages, title, header)
            msg = await ctx.reply(embed=view.build_embed(1), view=view, mention_author=False)
            view.message = msg

    @staticmethod
    def _build_who_embeds(title: str, user_ids: List[int], color=EMBED_COLOR) -> List[discord.Embed]:
        """Build one or more embeds mentioning every user_id given.

        Splits into multiple embeds if the mention list would exceed a
        single embed description's comfortable size.
        """
        if not user_ids:
            return []

        mentions = [f"<@{uid}>" for uid in user_ids]

        max_chars = 3800
        pages: List[List[str]] = []
        current: List[str] = []
        current_len = 0

        for mention in mentions:
            needed = len(mention) + (2 if current else 0)  # ", " separator
            if current and current_len + needed > max_chars:
                pages.append(current)
                current = [mention]
                current_len = len(mention)
            else:
                current.append(mention)
                current_len += needed

        if current:
            pages.append(current)

        total_pages = len(pages)
        embeds = []
        for i, page in enumerate(pages, start=1):
            embed_title = title if total_pages == 1 else f"{title} ({i}/{total_pages})"
            embed = discord.Embed(
                title=embed_title,
                description=", ".join(page),
                color=color,
            )
            embed.set_footer(text=f"{len(user_ids)} total")
            embeds.append(embed)

        return embeds

    @collection_group.command(name="who")
    async def collection_who(self, ctx, *, pokemon_name: str):
        """Check who in this server has a Pokemon in their collection

        Example:
            p!cl who Eevee
        """
        pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)

        if not pokemon or not pokemon.get('name'):
            await ctx.reply(f"❌ Invalid Pokemon name: {pokemon_name}", mention_author=False)
            return

        resolved_name = pokemon['name']

        afk_users = await self.db.get_collection_afk_users()
        user_ids = await self.db.get_collectors_for_pokemon(ctx.guild.id, [resolved_name], afk_users)

        if not user_ids:
            await ctx.reply(f"No one in this server is collecting **{resolved_name}**.", mention_author=False)
            return

        embeds = self._build_who_embeds(f"📦 Collectors of {resolved_name}", user_ids)

        await ctx.reply(
            embeds=embeds,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    # ------------------------------------------------------------------
    # Slash Commands  (registered automatically with the cog)
    # ------------------------------------------------------------------
    cl_group = app_commands.Group(name="cl", description="Manage your Pokémon collection for this server")

    @cl_group.command(name="add", description="Add Pokémon to your collection")
    @app_commands.describe(pokemon_names="Pokémon name(s), comma-separated. Append 'all' for all forms e.g. 'Furfrou all'")
    async def slash_collection_add(self, interaction: discord.Interaction, pokemon_names: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_add(ctx, pokemon_names=pokemon_names)

    @cl_group.command(name="remove", description="Remove Pokémon from your collection")
    @app_commands.describe(pokemon_names="Names (comma-sep), 'Furfrou all', or --sr <denom> flags e.g. '--sr 899 --sr 225'")
    async def slash_collection_remove(self, interaction: discord.Interaction, pokemon_names: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_remove(ctx, pokemon_names=pokemon_names)

    @cl_group.command(name="list", description="View your collection in a paginated embed")
    async def slash_collection_list(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_list(ctx)

    @cl_group.command(name="raw", description="View your collection as raw comma-separated text, grouped by SR")
    @app_commands.describe(args="Optional --sr flags to filter by spawn rate, e.g. '--sr 899' or '--sr 225 --sr 337'")
    async def slash_collection_raw(self, interaction: discord.Interaction, args: str = ""):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_raw(ctx, args=args)

    @cl_group.command(name="clear", description="Clear your entire Pokémon collection")
    async def slash_collection_clear(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_clear(ctx)

    @cl_group.command(name="who", description="See who in this server is collecting a Pokémon")
    @app_commands.describe(pokemon_name="The Pokémon to check, e.g. 'Eevee'")
    async def slash_collection_who(self, interaction: discord.Interaction, pokemon_name: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.collection_who(ctx, pokemon_name=pokemon_name)


async def setup(bot):
    await bot.add_cog(Collection(bot))
