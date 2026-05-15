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
        super().__init__(timeout=60)  # Reduced from 300s → 60s
        self.user_id = user_id
        self.category_name = category_name
        self.pokemon_list = pokemon_list
        self.current_page = current_page
        self.total_pages = total_pages
        self.message = None  # Store message ref for cleanup

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

    async def on_timeout(self):
        """Clean up message and references when view times out"""
        try:
            if self.message:
                await self.message.edit(view=None)
        except Exception:
            pass
        self.clear_items()
        self.message = None

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
        super().__init__(timeout=60)  # Reduced from 180s → 60s
        self.cog = cog
        self.ctx = ctx
        self.existing_names = existing_names  # category labels already on this guild
        self.message = None  # Store message ref for cleanup

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

    async def on_timeout(self):
        """Clean up message and references when view times out"""
        try:
            if self.message:
                await self.message.edit(view=None)
        except Exception:
            pass
        self.clear_items()
        self.message = None
        self.cog = None
        self.ctx = None

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
        message = await ctx.reply(embed=cls.build_list_embed(existing_names), view=view, mention_author=False)
        view.message = message  # Store message ref after send


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
        super().__init__(timeout=60)  # Reduced from 180s → 60s
        self.cog = cog
        self.ctx = ctx
        self.key = key
        self.meta = DEFAULT_CATEGORIES[key]
        self.existing_names = existing_names
        self.pokemon = self.meta["pokemon"]
        self.total_pages = max(1, math.ceil(len(self.pokemon) / DEFAULTS_PREVIEW_PAGE_SIZE))
        self.current_page = 1
        self.is_override = self.meta["label"] in existing_names
        self.message = None  # Store message ref for cleanup

        self._update_nav_buttons()
        self._update_confirm_button()

    def _update_nav_buttons(self):
        """Update prev/next button disabled states"""
        self.prev_page_btn.disabled = self.current_page <= 1
        self.next_page_btn.disabled = self.current_page >= self.total_pages

    def _update_confirm_button(self):
        """Update Add/Override button label and style"""
        label = f"⚠️ Override '{self.meta['label']}'" if self.is_override else f"➕ Add '{self.meta['label']}'"
        style = discord.ButtonStyle.danger if self.is_override else discord.ButtonStyle.success
        self.confirm_btn.label = label
        self.confirm_btn.style = style

    def build_embed(self, page: int) -> discord.Embed:
        start = (page - 1) * DEFAULTS_PREVIEW_PAGE_SIZE
        end = start + DEFAULTS_PREVIEW_PAGE_SIZE
        page_pokemon = self.pokemon[start:end]

        embed = discord.Embed(
            title=f"{self.meta['emoji']} {self.meta['label']}",
            description="\n".join([f"• {p}" for p in page_pokemon]),
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"Page {page}/{self.total_pages} • {len(self.pokemon)} Pokémon total"
        )
        return embed

    async def on_timeout(self):
        """Clean up references when view times out"""
        try:
            if self.message:
                await self.message.edit(view=None)
        except Exception:
            pass
        self.clear_items()
        self.message = None
        self.cog = None
        self.ctx = None

    @discord.ui.button(label="", emoji="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
            return
        if self.current_page > 1:
            self.current_page -= 1
            self._update_nav_buttons()
            await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    @discord.ui.button(label="", emoji="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
            return
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._update_nav_buttons()
            await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
            return
        # Go back to list view
        view = DefaultCategoryListView(self.cog, self.ctx, self.existing_names)
        await interaction.response.edit_message(
            embed=DefaultCategoryListView.build_list_embed(self.existing_names),
            view=view,
        )

    @discord.ui.button(label="", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't for you!", ephemeral=True)
            return

        label = self.meta["label"]
        pokemon_list = self.meta["pokemon"]

        try:
            existing = await self.cog.db.get_category(interaction.guild.id, label)
            if existing:
                # Override — replace Pokémon list
                await self.cog.db.update_category(interaction.guild.id, label, pokemon_list)
                msg = f"✅ **{label}** category updated with {len(pokemon_list)} Pokémon"
            else:
                # New — create category
                await self.cog.db.create_category(interaction.guild.id, label, pokemon_list)
                msg = f"✅ **{label}** category added with {len(pokemon_list)} Pokémon"
            await interaction.response.edit_message(content=msg, embed=None, view=None)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Error: {e}",
                embed=None,
                view=None,
            )


class Category(commands.Cog):
    """Category management for bulk collection operations"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    @property
    def db(self):
        """Get database from bot"""
        return self.bot.db

    # ------------------------------------------------------------------
    # Group definition
    # ------------------------------------------------------------------
    @commands.group(name="cat", invoke_without_command=True)
    async def category_group(self, ctx):
        """Manage categories for bulk collection operations
        Subcommands: create, add, remove, delete, edit, defaults, list, info
        """
        if ctx.invoked_subcommand is not None:
            return

        await ctx.send_help(self.category_group)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    @category_group.command(name="create")
    @commands.has_permissions(administrator=True)
    async def category_create(self, ctx, name: str, *, pokemon_input: str = None):
        """Create a new category and add Pokémon to it

        Examples:
            p!cat create Legendaries Zapdos, Articuno, Moltres
            p!cat create Mythicals arceus all
        """
        if not pokemon_input:
            await ctx.reply("❌ Please provide at least one Pokémon", mention_author=False)
            return

        # Check if category already exists
        existing = await self.db.get_category(ctx.guild.id, name)
        if existing:
            await ctx.reply(f"❌ Category `{name}` already exists", mention_author=False)
            return

        pokemon_to_add = []
        invalid = []

        # Check if using "all" keyword
        if pokemon_input.strip().lower().endswith(" all"):
            base_name = pokemon_input[:-4].strip()
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)
            if not variants:
                await ctx.reply(f"❌ Invalid Pokémon name: {base_name}", mention_author=False)
                return
            pokemon_to_add = variants
        else:
            # Parse comma-separated Pokémon names
            names = [n.strip() for n in pokemon_input.split(",") if n.strip()]
            for pokemon_name in names:
                pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
                if pokemon and pokemon.get("name"):
                    pokemon_to_add.append(pokemon["name"])
                else:
                    invalid.append(pokemon_name)

        if not pokemon_to_add:
            response = "❌ No valid Pokémon provided"
            if invalid:
                response += f": {', '.join(invalid[:10])}"
            await ctx.reply(response, mention_author=False)
            return

        # Create category
        await self.db.create_category(ctx.guild.id, name, pokemon_to_add)

        response = f"✅ Created category `{name}` with {len(pokemon_to_add)} Pokémon"
        if invalid:
            response += f"\n> ⚠️ Invalid: {', '.join(invalid[:10])}"
            if len(invalid) > 10:
                response += f" and {len(invalid) - 10} more"
        await ctx.reply(response, mention_author=False)

    # ------------------------------------------------------------------
    # Edit
    # ------------------------------------------------------------------
    @category_group.command(name="edit")
    @commands.has_permissions(administrator=True)
    async def category_edit(self, ctx, name: str, *, pokemon_input: str = None):
        """Replace all Pokémon in an existing category

        Examples:
            p!cat edit Legendaries Zapdos, Articuno, Moltres, Terrakion
        """
        if not pokemon_input:
            await ctx.reply("❌ Please provide at least one Pokémon", mention_author=False)
            return

        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)
            return

        pokemon_to_add = []
        invalid = []

        # Check if using "all" keyword
        if pokemon_input.strip().lower().endswith(" all"):
            base_name = pokemon_input[:-4].strip()
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)
            if not variants:
                await ctx.reply(f"❌ Invalid Pokémon name: {base_name}", mention_author=False)
                return
            pokemon_to_add = variants
        else:
            # Parse comma-separated Pokémon names
            names = [n.strip() for n in pokemon_input.split(",") if n.strip()]
            for pokemon_name in names:
                pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
                if pokemon and pokemon.get("name"):
                    pokemon_to_add.append(pokemon["name"])
                else:
                    invalid.append(pokemon_name)

        if not pokemon_to_add:
            response = "❌ No valid Pokémon provided"
            if invalid:
                response += f": {', '.join(invalid[:10])}"
            await ctx.reply(response, mention_author=False)
            return

        # Update category
        await self.db.update_category(ctx.guild.id, name, pokemon_to_add)

        response = f"✅ Updated `{name}` with {len(pokemon_to_add)} Pokémon"
        if invalid:
            response += f"\n> ⚠️ Invalid: {', '.join(invalid[:10])}"
            if len(invalid) > 10:
                response += f" and {len(invalid) - 10} more"
        await ctx.reply(response, mention_author=False)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    @category_group.command(name="delete")
    @commands.has_permissions(administrator=True)
    async def category_delete(self, ctx, *, name: str):
        """Delete a category

        Examples:
            p!cat delete Legendaries
        """
        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)
            return

        count = len(existing.get("pokemon", []))
        await self.db.delete_category(ctx.guild.id, name)
        await ctx.reply(f"✅ Deleted category `{name}` ({count} Pokémon)", mention_author=False)

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    @category_group.command(name="defaults")
    @commands.has_permissions(administrator=True)
    async def category_defaults(self, ctx):
        """Browse and add built-in categories to this server"""
        await DefaultCategoryListView.send(self, ctx)

    # ------------------------------------------------------------------
    # Add Pokémon to category
    # ------------------------------------------------------------------
    @category_group.command(name="addpokemon")
    @commands.has_permissions(administrator=True)
    async def category_addpokemon(self, ctx, name: str, *, pokemon_input: str = None):
        """Add Pokémon to an existing category

        Examples:
            p!cat addpokemon Legendaries Xerneas, Yveltal
            p!cat addpokemon Mythicals arceus all
        """
        if not pokemon_input:
            await ctx.reply("❌ Please provide at least one Pokémon", mention_author=False)
            return

        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)
            return

        pokemon_to_add = []
        invalid = []
        already_added = []

        existing_pokemon = set(existing.get("pokemon", []))

        # Check if using "all" keyword
        if pokemon_input.strip().lower().endswith(" all"):
            base_name = pokemon_input[:-4].strip()
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)
            if not variants:
                await ctx.reply(f"❌ Invalid Pokémon name: {base_name}", mention_author=False)
                return
            for p in variants:
                if p not in existing_pokemon:
                    pokemon_to_add.append(p)
                else:
                    already_added.append(p)
        else:
            # Parse comma-separated Pokémon names
            names = [n.strip() for n in pokemon_input.split(",") if n.strip()]
            for pokemon_name in names:
                pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
                if pokemon and pokemon.get("name"):
                    if pokemon["name"] not in existing_pokemon:
                        pokemon_to_add.append(pokemon["name"])
                    else:
                        already_added.append(pokemon["name"])
                else:
                    invalid.append(pokemon_name)

        if not pokemon_to_add:
            response = "❌ No new Pokémon to add"
            if already_added:
                response += f"\n> {len(already_added)} already in category: {', '.join(already_added[:10])}"
            if invalid:
                response += f"\n> ⚠️ Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(response, mention_author=False)
            return

        # Update category
        updated = existing_pokemon | set(pokemon_to_add)
        await self.db.update_category(ctx.guild.id, name, list(updated))

        response = f"✅ Added {len(pokemon_to_add)} Pokémon to `{name}`"
        if len(pokemon_to_add) <= 20:
            response += f": {', '.join(pokemon_to_add)}"
        else:
            response += f": {', '.join(pokemon_to_add[:20])} and {len(pokemon_to_add) - 20} more"

        if already_added:
            response += f"\n> {len(already_added)} already in category (skipped)"
        if invalid:
            response += f"\n> ⚠️ Invalid: {', '.join(invalid[:30])}"
            if len(invalid) > 30:
                response += f" and {len(invalid) - 30} more..."
        await ctx.reply(response, mention_author=False)

    # ------------------------------------------------------------------
    # Remove Pokémon from category
    # ------------------------------------------------------------------
    @category_group.command(name="removepokemon")
    @commands.has_permissions(administrator=True)
    async def category_removepokemon(self, ctx, name: str, *, pokemon_input: str = None):
        """Remove Pokémon from an existing category

        Examples:
            p!cat removepokemon Legendaries Xerneas, Yveltal
        """
        if not pokemon_input:
            await ctx.reply("❌ Please provide at least one Pokémon", mention_author=False)
            return

        existing = await self.db.get_category(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ Category `{name}` does not exist", mention_author=False)
            return

        to_remove = []
        invalid = []
        not_in_category = []

        existing_pokemon = set(existing.get("pokemon", []))

        # Check if using "all" keyword
        if pokemon_input.strip().lower().endswith(" all"):
            base_name = pokemon_input[:-4].strip()
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)
            if not variants:
                await ctx.reply(f"❌ Invalid Pokémon name: {base_name}", mention_author=False)
                return
            for p in variants:
                if p in existing_pokemon:
                    to_remove.append(p)
                else:
                    not_in_category.append(p)
        else:
            # Parse comma-separated Pokémon names
            names = [n.strip() for n in pokemon_input.split(",") if n.strip()]
            for pokemon_name in names:
                pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
                if pokemon and pokemon.get("name"):
                    if pokemon["name"] in existing_pokemon:
                        to_remove.append(pokemon["name"])
                    else:
                        not_in_category.append(pokemon["name"])
                else:
                    invalid.append(pokemon_name)

        actually_removed = [p for p in to_remove if p in existing_pokemon]

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
            message = await ctx.reply(embed=view.create_embed(1), view=view, mention_author=False)
            view.message = message  # Store message ref after send
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
