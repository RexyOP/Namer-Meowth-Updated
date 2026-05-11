"""Category management for bulk collection operations"""
import discord
import math
from discord import app_commands
from discord.ext import commands
from typing import List
from utils import (
    load_pokemon_data,
    find_pokemon_by_name_flexible,
    get_pokemon_with_variants,
)
from config import EMBED_COLOR, ITEMS_PER_PAGE
from default_cats import DEFAULT_CATEGORIES


# ---------------------------------------------------------------------------
# Pagination view for browsing a single category's Pokémon
# ---------------------------------------------------------------------------
class CategoryPaginationView(discord.ui.View):
    def __init__(self, user_id, category_name, pokemon_list, current_page, total_pages):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.category_name = category_name
        self.pokemon_list = pokemon_list
        self.current_page = current_page
        self.total_pages = total_pages

        self.previous_button.disabled = (current_page <= 1)
        self.next_button.disabled = (current_page >= total_pages)

    def create_embed(self, page):
        start_idx = (page - 1) * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_pokemon = self.pokemon_list[start_idx:end_idx]

        embed = discord.Embed(
            title=f"📦 Category: {self.category_name}",
            description="\n".join([f"• {p}" for p in page_pokemon]),
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=(
                f"Showing {start_idx + 1}–{min(end_idx, len(self.pokemon_list))} "
                f"of {len(self.pokemon_list)} Pokémon • Page {page}/{self.total_pages}"
            )
        )
        return embed

    @discord.ui.button(label="", emoji="◀️", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        new_page = max(1, self.current_page - 1)
        self.current_page = new_page
        self.previous_button.disabled = (new_page <= 1)
        self.next_button.disabled = (new_page >= self.total_pages)
        await interaction.response.edit_message(embed=self.create_embed(new_page), view=self)

    @discord.ui.button(label="", emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return
        new_page = min(self.total_pages, self.current_page + 1)
        self.current_page = new_page
        self.previous_button.disabled = (new_page <= 1)
        self.next_button.disabled = (new_page >= self.total_pages)
        await interaction.response.edit_message(embed=self.create_embed(new_page), view=self)


# ---------------------------------------------------------------------------
# Stage 1 — Default category list  (p!cat defaults)
# ---------------------------------------------------------------------------
class DefaultCategoryListView(discord.ui.View):
    """
    Sends one embed listing every default category with its Pokémon count.
    Each category gets an "Add <Name>" button. Pressing one transitions the
    message to Stage 2 (the preview + confirm view) in-place.
    """

    def __init__(self, cog: "Category", ctx: commands.Context, existing_names: set[str]):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.existing_names = existing_names  # category labels already on this guild

        for key, meta in DEFAULT_CATEGORIES.items():
            label = meta["label"]
            is_override = label in existing_names
            btn = discord.ui.Button(
                label=f"Add {label}",
                emoji="⚠️" if is_override else "➕",
                style=discord.ButtonStyle.danger if is_override else discord.ButtonStyle.success,
                custom_id=f"add_{key}",
                row=1,
            )
            btn.callback = self._make_add_callback(key)
            self.add_item(btn)

    def _make_add_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
                return
            # Hand off to the preview stage — edits this same message
            preview = DefaultCategoryPreviewView(
                cog=self.cog,
                ctx=self.ctx,
                key=key,
                existing_names=self.existing_names,
            )
            await interaction.response.edit_message(
                embed=preview.build_embed(page=1),
                view=preview,
            )
        return callback

    # ------------------------------------------------------------------
    @staticmethod
    def build_list_embed(existing_names: set[str]) -> discord.Embed:
        lines = []
        for meta in DEFAULT_CATEGORIES.values():
            label = meta["label"]
            count = len(meta["pokemon"])
            tag = " *(already added)*" if label in existing_names else ""
            lines.append(f"{meta['emoji']} **{label}** — {count} Pokémon{tag}")

        embed = discord.Embed(
            title="📋 Default Categories",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="Press a button below to preview and add a category to this server.")
        return embed

    @classmethod
    async def send(cls, cog: "Category", ctx: commands.Context):
        guild_cats = await cog.db.get_all_categories(ctx.guild.id)
        existing_names = {c["name"] for c in guild_cats}
        view = cls(cog, ctx, existing_names)
        await ctx.reply(embed=cls.build_list_embed(existing_names), view=view, mention_author=False)


# ---------------------------------------------------------------------------
# Stage 2 — Preview + confirm  (replaces the same message)
# ---------------------------------------------------------------------------
DEFAULTS_PREVIEW_PAGE_SIZE = 20


class DefaultCategoryPreviewView(discord.ui.View):
    """
    Paginated preview of one default category's Pokémon list.
    Row 0 — ◀ page counter ▶
    Row 1 — ← Back | [Add / ⚠️ Override] Confirm
    """

    def __init__(
        self,
        cog: "Category",
        ctx: commands.Context,
        key: str,
        existing_names: set[str],
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.key = key
        self.meta = DEFAULT_CATEGORIES[key]
        self.existing_names = existing_names
        self.pokemon = self.meta["pokemon"]
        self.total_pages = max(1, math.ceil(len(self.pokemon) / DEFAULTS_PREVIEW_PAGE_SIZE))
        self.current_page = 1
        self.is_override = self.meta["label"] in existing_names

        self._refresh_buttons()

    # ------------------------------------------------------------------
    def _refresh_buttons(self):
        self.clear_items()

        # Row 0 — pagination
        self.prev_page_btn = discord.ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page <= 1,
            row=0,
        )
        self.prev_page_btn.callback = self._prev_page

        self.page_counter_btn = discord.ui.Button(
            label=f"{self.current_page} / {self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0,
        )

        self.next_page_btn = discord.ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            disabled=self.current_page >= self.total_pages,
            row=0,
        )
        self.next_page_btn.callback = self._next_page

        self.add_item(self.prev_page_btn)
        self.add_item(self.page_counter_btn)
        self.add_item(self.next_page_btn)

        # Row 1 — back + confirm
        back_btn = discord.ui.Button(
            label="← Back",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        back_btn.callback = self._go_back

        confirm_label = (
            f"⚠️ Override {self.meta['label']}"
            if self.is_override
            else f"✅ Add {self.meta['label']}"
        )
        confirm_btn = discord.ui.Button(
            label=confirm_label,
            style=discord.ButtonStyle.danger if self.is_override else discord.ButtonStyle.success,
            row=1,
        )
        confirm_btn.callback = self._confirm

        self.add_item(back_btn)
        self.add_item(confirm_btn)

    # ------------------------------------------------------------------
    def build_embed(self, page: int) -> discord.Embed:
        start = (page - 1) * DEFAULTS_PREVIEW_PAGE_SIZE
        end = start + DEFAULTS_PREVIEW_PAGE_SIZE
        chunk = self.pokemon[start:end]

        warn = (
            f"\n> ⚠️ **This server already has a `{self.meta['label']}` category. "
            f"Adding will override it.**\n"
            if self.is_override
            else ""
        )

        embed = discord.Embed(
            title=f"{self.meta['emoji']} {self.meta['label']} — Preview",
            description=warn + "\n".join(f"• {p}" for p in chunk),
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=(
                f"{len(self.pokemon)} Pokémon total • "
                f"Page {page}/{self.total_pages} • "
                f"{self.meta['description']}"
            )
        )
        return embed

    # ------------------------------------------------------------------
    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
            return False
        return True

    async def _prev_page(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return
        self.current_page = max(1, self.current_page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    async def _next_page(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return
        self.current_page = min(self.total_pages, self.current_page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    async def _go_back(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return
        # Rebuild the list view so its existing_names stays accurate
        guild_cats = await self.cog.db.get_all_categories(interaction.guild.id)
        existing_names = {c["name"] for c in guild_cats}
        list_view = DefaultCategoryListView(self.cog, self.ctx, existing_names)
        await interaction.response.edit_message(
            embed=DefaultCategoryListView.build_list_embed(existing_names),
            view=list_view,
        )

    async def _confirm(self, interaction: discord.Interaction):
        if not await self._check(interaction):
            return

        meta = self.meta
        cat_name = meta["label"]
        pokemon = meta["pokemon"]

        # Always do a live DB check — is_override may be stale if the category
        # was added between the view being built and the button being pressed.
        existing = await self.cog.db.get_category(interaction.guild.id, cat_name)
        if existing:
            await self.cog.db.update_category(interaction.guild.id, cat_name, pokemon)
            verb = "overridden"
        else:
            await self.cog.db.create_category(interaction.guild.id, cat_name, pokemon)
            verb = "added"

        # Rebuild list view with fresh DB state
        guild_cats = await self.cog.db.get_all_categories(interaction.guild.id)
        existing_names = {c["name"] for c in guild_cats}
        list_view = DefaultCategoryListView(self.cog, self.ctx, existing_names)

        await interaction.response.edit_message(
            embed=DefaultCategoryListView.build_list_embed(existing_names),
            view=list_view,
        )
        await interaction.followup.send(
            f"✅ **{cat_name}** ({len(pokemon)} Pokémon) {verb} successfully.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Category Cog
# ---------------------------------------------------------------------------
class Category(commands.Cog):
    """Category management for bulk collection operations"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    @property
    def db(self):
        return self.bot.db

    def parse_pokemon_input(self, input_string: str) -> List[str]:
        """Parse pokemon input and return list of pokemon names.

        Handles:
        - Single pokemon: "pikachu"
        - Multiple pokemon: "pikachu, charizard, mewtwo"
        - All variants: "furfrou all", "arceus all", "all furfrou", "all arceus"
        """
        parts = [p.strip() for p in input_string.split(",") if p.strip()]
        all_pokemon = []
        invalid = []

        for part in parts:
            part_lower = part.lower()
            is_all = part_lower.endswith(" all") or part_lower.startswith("all ")

            if is_all:
                if part_lower.startswith("all "):
                    base_name = part[4:].strip()
                else:
                    base_name = part[:-4].strip()
                variants = get_pokemon_with_variants(base_name, self.pokemon_data)
                if variants:
                    all_pokemon.extend(variants)
                else:
                    invalid.append(part)
            else:
                pokemon = find_pokemon_by_name_flexible(part, self.pokemon_data)
                if pokemon and pokemon.get("name"):
                    all_pokemon.append(pokemon["name"])
                else:
                    invalid.append(part)

        return all_pokemon, invalid

    # ------------------------------------------------------------------
    # Command group
    # ------------------------------------------------------------------
    @commands.group(name="category", aliases=["cat"], invoke_without_command=True)
    async def category_group(self, ctx):
        """Category management commands"""
        if ctx.invoked_subcommand is None:
            await ctx.reply(
                "Usage: `p!cat [create/edit/delete]` or `p!cat [add/remove/list/info]` "
                "or `p!cat [addpokemon/removepokemon]` or `p!cat defaults`",
                mention_author=False,
            )

    # ------------------------------------------------------------------
    # p!cat defaults — browse and import built-in categories
    # ------------------------------------------------------------------
    @category_group.command(name="defaults", aliases=["default", "builtin"])
    @commands.has_permissions(administrator=True)
    async def category_defaults(self, ctx):
        """Browse built-in categories and add them to this server (Admin only).

        Shows all default categories (rare, regional, gigantamax) in an
        interactive browser. Press a tab to preview it, then hit
        "Add to Server" to import it. If the category already exists you'll
        be asked to confirm before overriding.

        Example:
            p!cat defaults
        """
        await DefaultCategoryListView.send(cog=self, ctx=ctx)

    # ------------------------------------------------------------------
    # Admin CRUD
    # ------------------------------------------------------------------
    @category_group.command(name="create")
    @commands.has_permissions(administrator=True)
    async def category_create(self, ctx, name: str, *, pokemon_input: str):
        """Create a new category (Admin only)

        Examples:
            p!cat create Rares articuno, moltres, zapdos
            p!cat create "Legendary Birds" articuno, moltres, zapdos
            p!cat create Furfrou furfrou all
            p!cat create Arceus arceus all
        """
        pokemon_list, invalid = self.parse_pokemon_input(pokemon_input)

        if not pokemon_list:
            error_msg = "No valid Pokémon found to add to category"
            if invalid:
                error_msg += f". Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(error_msg, mention_author=False)
            return

        existing = await self.db.get_category(ctx.guild.id, name)
        if existing:
            await ctx.reply(
                f"❌ Category `{name}` already exists. Use `p!cat edit` to modify it.",
                mention_author=False,
            )
            return

        await self.db.create_category(ctx.guild.id, name, pokemon_list)

        response = f"✅ Created category `{name}` with {len(pokemon_list)} Pokémon"
        if invalid:
            response += f"\n⚠️ Invalid: {', '.join(invalid[:30])}"
            if len(invalid) > 30:
                response += f" and {len(invalid) - 30} more..."
        await ctx.reply(response, mention_author=False)

    @category_group.command(name="edit")
    @commands.has_permissions(administrator=True)
    async def category_edit(self, ctx, name: str, *, pokemon_input: str):
        """Edit an existing category (Admin only) — replaces the entire list.

        Examples:
            p!cat edit Rares marshadow, lugia, moltres all
        """
        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(
                f"❌ Category `{name}` does not exist. Use `p!cat create` to create it.",
                mention_author=False,
            )
            return

        pokemon_list, invalid = self.parse_pokemon_input(pokemon_input)

        if not pokemon_list:
            error_msg = "No valid Pokémon found to add to category"
            if invalid:
                error_msg += f". Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(error_msg, mention_author=False)
            return

        await self.db.update_category(ctx.guild.id, name, pokemon_list)

        response = f"✅ Updated category `{name}` with {len(pokemon_list)} Pokémon"
        if invalid:
            response += f"\n⚠️ Invalid: {', '.join(invalid[:30])}"
            if len(invalid) > 30:
                response += f" and {len(invalid) - 30} more..."
        await ctx.reply(response, mention_author=False)

    @category_group.command(name="delete")
    @commands.has_permissions(administrator=True)
    async def category_delete(self, ctx, *, name: str):
        """Delete a category (Admin only)

        Examples:
            p!cat delete Rares
        """
        deleted = await self.db.delete_category(ctx.guild.id, name)
        if deleted:
            await ctx.reply(f"✅ Deleted category `{name}`", mention_author=False)
        else:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)

    # ------------------------------------------------------------------
    # User commands (add/remove from collection)
    # ------------------------------------------------------------------
    @category_group.command(name="add")
    async def category_add(self, ctx, *, category_names: str):
        """Add Pokémon from categories to your collection

        Examples:
            p!cat add Rares
            p!cat add Rares, Regionals, Gigantamax
        """
        names_list = list(dict.fromkeys(
            name.strip() for name in category_names.split(",") if name.strip()
        ))

        if not names_list:
            await ctx.reply("No category names provided", mention_author=False)
            return

        total_added = 0
        category_results = []
        not_found = []

        for cat_name in names_list:
            category = await self.db.get_category(ctx.guild.id, cat_name)
            if category:
                pokemon_list = category.get("pokemon", [])
                if pokemon_list:
                    await self.db.add_pokemon_to_collection(ctx.author.id, ctx.guild.id, pokemon_list)
                    total_added += len(pokemon_list)
                    category_results.append(f"Added {len(pokemon_list)} Pokémon from `{cat_name}`")
            else:
                not_found.append(cat_name)

        if not category_results:
            error_msg = "No valid categories found"
            if not_found:
                error_msg += f": {', '.join(not_found)}"
            await ctx.reply(error_msg, mention_author=False)
            return

        response = "✅ " + "\n".join(category_results)
        response += f"\n\n**Total added: {total_added} Pokémon**"
        if not_found:
            response += f"\n❌ Categories not found: {', '.join(not_found)}"
        await ctx.reply(response, mention_author=False)

    @category_group.command(name="remove")
    async def category_remove(self, ctx, *, category_names: str):
        """Remove Pokémon from categories from your collection

        Examples:
            p!cat remove Rares
            p!cat remove Rares, Regionals
        """
        names_list = list(dict.fromkeys(
            name.strip() for name in category_names.split(",") if name.strip()
        ))

        if not names_list:
            await ctx.reply("No category names provided", mention_author=False)
            return

        total_removed = 0
        category_results = []
        not_found = []

        for cat_name in names_list:
            category = await self.db.get_category(ctx.guild.id, cat_name)
            if category:
                pokemon_list = category.get("pokemon", [])
                if pokemon_list:
                    modified = await self.db.remove_pokemon_from_collection(
                        ctx.author.id, ctx.guild.id, pokemon_list
                    )
                    if modified:
                        total_removed += len(pokemon_list)
                        category_results.append(f"Removed {len(pokemon_list)} Pokémon from `{cat_name}`")
            else:
                not_found.append(cat_name)

        if not category_results:
            if not_found:
                error_msg = f"❌ Categories not found or were deleted by server admin: {', '.join(not_found)}"
            else:
                error_msg = "No Pokémon were removed"
            await ctx.reply(error_msg, mention_author=False)
            return

        response = "✅ " + "\n".join(category_results)
        response += f"\n\n**Total removed: {total_removed} Pokémon**"
        if not_found:
            response += f"\n❌ Categories not found or were deleted by server admin: {', '.join(not_found)}"
        await ctx.reply(response, mention_author=False)

    # ------------------------------------------------------------------
    # Admin Pokémon-level editing
    # ------------------------------------------------------------------
    @category_group.command(name="addpokemon", aliases=["addpoke"])
    @commands.has_permissions(administrator=True)
    async def category_addpokemon(self, ctx, name: str, *, pokemon_input: str):
        """Add Pokémon to an existing category (Admin only) — appends, does not replace.

        Examples:
            p!cat addpokemon Rares marshadow, hoopa
            p!cat addpokemon Furfrou furfrou all
        """
        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(
                f"❌ Category `{name}` does not exist. Use `p!cat create` to create it.",
                mention_author=False,
            )
            return

        pokemon_list, invalid = self.parse_pokemon_input(pokemon_input)

        if not pokemon_list:
            error_msg = "No valid Pokémon found"
            if invalid:
                error_msg += f". Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(error_msg, mention_author=False)
            return

        existing_pokemon = set(existing.get("pokemon", []))
        new_pokemon = [p for p in pokemon_list if p not in existing_pokemon]

        if not new_pokemon:
            await ctx.reply(f"All provided Pokémon are already in `{name}`.", mention_author=False)
            return

        merged = list(existing_pokemon) + new_pokemon
        await self.db.update_category(ctx.guild.id, name, merged)

        response = f"✅ Added {len(new_pokemon)} Pokémon to `{name}`"
        if len(new_pokemon) <= 20:
            response += f": {', '.join(new_pokemon)}"
        else:
            response += f": {', '.join(new_pokemon[:20])} and {len(new_pokemon) - 20} more"

        skipped = [p for p in pokemon_list if p in existing_pokemon]
        if skipped:
            response += f"\n> -# {len(skipped)} already in category (skipped)"
        if invalid:
            response += f"\n⚠️ Invalid: {', '.join(invalid[:30])}"
            if len(invalid) > 30:
                response += f" and {len(invalid) - 30} more..."
        await ctx.reply(response, mention_author=False)

    @category_group.command(name="removepokemon", aliases=["removepoke"])
    @commands.has_permissions(administrator=True)
    async def category_removepokemon(self, ctx, name: str, *, pokemon_input: str):
        """Remove specific Pokémon from an existing category (Admin only).

        Does NOT delete the category — only removes the listed Pokémon.

        Examples:
            p!cat removepokemon Rares marshadow, hoopa
            p!cat removepokemon Furfrou furfrou all
        """
        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ Category `{name}` does not exist.", mention_author=False)
            return

        pokemon_list, invalid = self.parse_pokemon_input(pokemon_input)

        if not pokemon_list:
            error_msg = "No valid Pokémon found"
            if invalid:
                error_msg += f". Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(error_msg, mention_author=False)
            return

        existing_pokemon = set(existing.get("pokemon", []))
        to_remove = set(pokemon_list)

        actually_removed = [p for p in pokemon_list if p in existing_pokemon]
        not_in_category = [p for p in pokemon_list if p not in existing_pokemon]

        if not actually_removed:
            await ctx.reply(f"None of the provided Pokémon are in `{name}`.", mention_author=False)
            return

        updated = [p for p in existing.get("pokemon", []) if p not in to_remove]
        await self.db.update_category(ctx.guild.id, name, updated)

        response = f"✅ Removed {len(actually_removed)} Pokémon from `{name}`"
        if len(actually_removed) <= 20:
            response += f": {', '.join(actually_removed)}"
        else:
            response += f": {', '.join(actually_removed[:20])} and {len(actually_removed) - 20} more"

        if not_in_category:
            response += f"\n> -# {len(not_in_category)} were not in the category (skipped)"
        if invalid:
            response += f"\n⚠️ Invalid: {', '.join(invalid[:30])}"
            if len(invalid) > 30:
                response += f" and {len(invalid) - 30} more..."
        await ctx.reply(response, mention_author=False)

    # ------------------------------------------------------------------
    # Info / listing
    # ------------------------------------------------------------------
    @category_group.command(name="list")
    async def category_list(self, ctx):
        """List all categories in this server"""
        categories = await self.db.get_all_categories(ctx.guild.id)

        if not categories:
            await ctx.reply(
                "This server has no categories yet. "
                "Use `p!cat defaults` to add built-in ones, or `p!cat create` to make your own.",
                mention_author=False,
            )
            return

        embed = discord.Embed(
            title=f"📦 Categories in {ctx.guild.name}",
            color=EMBED_COLOR,
        )
        lines = [
            f"• **{cat['name']}** ({len(cat.get('pokemon', []))} Pokémon)"
            for cat in sorted(categories, key=lambda x: x["name"].lower())
        ]
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Total categories: {len(categories)}")
        await ctx.reply(embed=embed, mention_author=False)

    @category_group.command(name="info")
    async def category_info(self, ctx, *, name: str):
        """View details of a specific category

        Examples:
            p!cat info Rares
        """
        category = await self.db.get_category(ctx.guild.id, name)

        if not category:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)
            return

        pokemon_list = sorted(category.get("pokemon", []))

        if not pokemon_list:
            await ctx.reply(f"Category `{name}` is empty", mention_author=False)
            return

        total_pages = math.ceil(len(pokemon_list) / ITEMS_PER_PAGE)

        if total_pages > 1:
            view = CategoryPaginationView(ctx.author.id, name, pokemon_list, 1, total_pages)
            await ctx.reply(embed=view.create_embed(1), view=view, mention_author=False)
        else:
            embed = discord.Embed(
                title=f"📦 Category: {name}",
                description="\n".join([f"• {p}" for p in pokemon_list]),
                color=EMBED_COLOR,
            )
            embed.set_footer(text=f"Total: {len(pokemon_list)} Pokémon")
            await ctx.reply(embed=embed, mention_author=False)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    @category_create.error
    @category_edit.error
    @category_delete.error
    @category_addpokemon.error
    @category_removepokemon.error
    @category_defaults.error
    async def category_admin_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply(
                "❌ You need administrator permissions to use this command.",
                mention_author=False,
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                f"❌ Missing required argument: `{error.param.name}`",
                mention_author=False,
            )

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------
    cat_group = app_commands.Group(name="cat", description="Category management for bulk collection operations")

    @cat_group.command(name="defaults", description="Browse built-in categories and add them to this server (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_defaults(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_defaults(ctx)

    @cat_group.command(name="add", description="Add Pokémon from categories to your collection")
    @app_commands.describe(category_names="Category name(s), comma-separated")
    async def slash_category_add(self, interaction: discord.Interaction, category_names: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_add(ctx, category_names=category_names)

    @cat_group.command(name="remove", description="Remove Pokémon from categories from your collection")
    @app_commands.describe(category_names="Category name(s), comma-separated")
    async def slash_category_remove(self, interaction: discord.Interaction, category_names: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_remove(ctx, category_names=category_names)

    @cat_group.command(name="list", description="List all categories in this server")
    async def slash_category_list(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_list(ctx)

    @cat_group.command(name="info", description="View details of a specific category")
    @app_commands.describe(name="Category name")
    async def slash_category_info(self, interaction: discord.Interaction, name: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_info(ctx, name=name)

    @cat_group.command(name="create", description="Create a new category (Admin only)")
    @app_commands.describe(name="Category name", pokemon_input="Pokémon names, comma-separated. Supports 'arceus all'")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_create(self, interaction: discord.Interaction, name: str, pokemon_input: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_create(ctx, name, pokemon_input=pokemon_input)

    @cat_group.command(name="edit", description="Replace all Pokémon in a category (Admin only)")
    @app_commands.describe(name="Category name", pokemon_input="New Pokémon list, comma-separated")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_edit(self, interaction: discord.Interaction, name: str, pokemon_input: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_edit(ctx, name, pokemon_input=pokemon_input)

    @cat_group.command(name="delete", description="Delete a category (Admin only)")
    @app_commands.describe(name="Category name to delete")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_delete(self, interaction: discord.Interaction, name: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_delete(ctx, name=name)

    @cat_group.command(name="addpokemon", description="Add Pokémon to an existing category (Admin only)")
    @app_commands.describe(name="Category name", pokemon_input="Pokémon to add, comma-separated. Supports 'furfrou all'")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_addpokemon(self, interaction: discord.Interaction, name: str, pokemon_input: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_addpokemon(ctx, name, pokemon_input=pokemon_input)

    @cat_group.command(name="removepokemon", description="Remove specific Pokémon from an existing category (Admin only)")
    @app_commands.describe(name="Category name", pokemon_input="Pokémon to remove, comma-separated. Supports 'furfrou all'")
    @app_commands.default_permissions(administrator=True)
    async def slash_category_removepokemon(self, interaction: discord.Interaction, name: str, pokemon_input: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.category_removepokemon(ctx, name, pokemon_input=pokemon_input)


async def setup(bot):
    await bot.add_cog(Category(bot))
