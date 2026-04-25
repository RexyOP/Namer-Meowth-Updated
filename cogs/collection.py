"""Collection management commands"""
import discord
import math
import asyncio
from discord.ext import commands
from typing import List
from utils import (
    load_pokemon_data,
    find_pokemon_by_name_flexible,
    normalize_pokemon_name,
    get_pokemon_with_variants,
    is_rare_pokemon,
    create_text_file
)
from config import EMBED_COLOR, ITEMS_PER_PAGE, MAX_DISPLAY_ITEMS

class CollectionPaginationView(discord.ui.View):
    def __init__(self, user_id, guild_id, current_page, total_pages, cog):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.cog = cog

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

class Collection(commands.Cog):
    """Collection management commands"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

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
        """
        names_list = [name.strip() for name in pokemon_names.split(",") if name.strip()]

        if not names_list:
            await ctx.reply("No valid Pokemon names provided", mention_author=False)
            return

        removed_pokemon = []
        not_found_pokemon = []

        for name in names_list:
            pokemon = find_pokemon_by_name_flexible(name, self.pokemon_data)

            if pokemon and pokemon.get('name'):
                removed_pokemon.append(pokemon['name'])
            else:
                not_found_pokemon.append(name)

        if not removed_pokemon:
            error_msg = "No valid Pokemon names found"
            if not_found_pokemon:
                error_msg += f". Invalid: {', '.join(not_found_pokemon[:30])}"
            await ctx.reply(error_msg, mention_author=False)
            return

        modified = await self.db.remove_pokemon_from_collection(
            ctx.author.id, ctx.guild.id, removed_pokemon
        )

        if modified:
            if len(removed_pokemon) <= MAX_DISPLAY_ITEMS:
                response = f"✅ Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon)}"
            else:
                response = f"✅ Removed {len(removed_pokemon)} Pokemon: {', '.join(removed_pokemon[:MAX_DISPLAY_ITEMS])} and {len(removed_pokemon) - MAX_DISPLAY_ITEMS} more..."

            if not_found_pokemon:
                if len(not_found_pokemon) <= 30:
                    response += f"\n❌ Invalid: {', '.join(not_found_pokemon)}"

            await ctx.reply(response, mention_author=False)
        else:
            await ctx.reply("No Pokemon were removed (they might not be in your collection)", mention_author=False)

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
                await ctx.reply(embed=embed, view=view, mention_author=False)
            else:
                await ctx.reply(embed=embed, mention_author=False)
        else:
            await ctx.reply(embed=embed, mention_author=False)

    @collection_group.command(name="raw")
    async def collection_raw(self, ctx):
        """View your collection as raw text (comma-separated)

        If collection is large, sends as a text file.
        """
        collection = await self.db.get_user_collection(ctx.author.id, ctx.guild.id)

        if not collection:
            await ctx.reply("Your collection is empty!", mention_author=False)
            return

        sorted_collection = sorted(collection)
        text_content = ", ".join(sorted_collection)

        # If content is too long for a message, send as file
        if len(text_content) > 1900:
            file = create_text_file(text_content, f"collection_{ctx.author.id}.txt")
            embed = discord.Embed(
                title="📦 Your Collection",
                description=f"Your collection has {len(sorted_collection)} Pokémon. View the attached file for the full list.",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, file=file, mention_author=False)
        else:
            embed = discord.Embed(
                title="📦 Your Collection",
                description=f"**{len(sorted_collection)} Pokémon:** {text_content}",
                color=EMBED_COLOR
            )
            await ctx.reply(embed=embed, mention_author=False)

async def setup(bot):
    await bot.add_cog(Collection(bot))
