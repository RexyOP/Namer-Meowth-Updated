"""Reserve system — server-specific Pokémon reservation for admins and allowed roles."""

import math
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Optional
from utils import (
    load_pokemon_data,
    find_pokemon_by_name_flexible,
    get_pokemon_with_variants,
)
from config import EMBED_COLOR

# Default categories (rare, regional, gigantamax) have moved to default_cats.py.
# Admins can import them into their server via `p!cat defaults`.
# Reserve only works with server-defined categories now.

ITEMS_PER_PAGE = 15  # pokemon per user section on the list embed
REPLY_EMOJI = "<:reply:1503236369126916117>"


# ---------------------------------------------------------------------------
# Pagination view for p!reserve list
# ---------------------------------------------------------------------------
class ReserveListView(discord.ui.View):
    def __init__(self, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=60)  # reduced from 300
        self.author_id = author_id
        self.pages = pages
        self.current = 0
        self.message: discord.Message | None = None
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current <= 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This button isn't for you!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def prev_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check(interaction):
            return
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def next_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self._check(interaction):
            return
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(
            embed=self.pages[self.current], view=self
        )

    async def on_timeout(self):
        self.clear_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.message = None


# ---------------------------------------------------------------------------
# Helper to build paginated reserve list embeds
# ---------------------------------------------------------------------------
def build_reserve_list_embeds(
    guild_name: str, reserve_docs: list[dict]
) -> list[discord.Embed]:
    """
    Build a list of Discord embeds for the reserve list.
    Each 'page' holds up to ITEMS_PER_PAGE pokemon entries across all users.
    First page starts with a summary of all users and their counts.
    Users are shown with their mention as a header, pokemon as bullet lines.
    """
    if not reserve_docs:
        embed = discord.Embed(
            title=f"📋 Reserve List — {guild_name}",
            description="No reserves set for this server.",
            color=EMBED_COLOR,
        )
        return [embed]

    # Flatten to (user_id, pokemon_list) pairs, sorted by pokemon count (ascending)
    pairs = [(doc["user_id"], sorted(doc.get("pokemon", []))) for doc in reserve_docs]
    pairs = [(uid, pokes) for uid, pokes in pairs if pokes]
    # Sort by count of pokemon (ascending - fewer reserves first)
    pairs.sort(key=lambda x: len(x[1]))

    if not pairs:
        embed = discord.Embed(
            title=f"📋 Reserve List — {guild_name}",
            description="No reserves set for this server.",
            color=EMBED_COLOR,
        )
        return [embed]

    # Build summary: user mentions with their counts
    summary_lines = []
    for uid, pokes in pairs:
        count = len(pokes)
        summary_lines.append(f"<@{uid}> — {count}")
    
    summary_text = "\n".join(summary_lines)

    # Build lines: "## <@uid>" header + "• pokemon" entries
    all_lines: list[tuple[str, bool]] = []  # (text, is_header)
    for uid, pokes in pairs:
        all_lines.append((f"<@{uid}>", True))
        for p in pokes:
            all_lines.append((f"{REPLY_EMOJI} {p}", False))

    # Paginate: at most ITEMS_PER_PAGE *pokemon* lines per page
    # But first page always starts with summary
    pages: list[discord.Embed] = []
    current_lines: list[str] = []
    pokemon_count = 0
    is_first_page = True

    def flush_page(lines, include_summary=False):
        if include_summary:
            content = f"**📊 Reserve Count**\n{summary_text}\n\n─────────────\n" + "\n".join(lines) if lines else summary_text
        else:
            content = "\n".join(lines) if lines else "—"
        
        embed = discord.Embed(
            title=f"📋 Reserve List — {guild_name}",
            description=content,
            color=EMBED_COLOR,
        )
        return embed

    for text, is_header in all_lines:
        if not is_header:
            pokemon_count += 1

        current_lines.append(text)

        if pokemon_count >= ITEMS_PER_PAGE and not is_header:
            pages.append(flush_page(current_lines, include_summary=is_first_page))
            is_first_page = False
            current_lines = []
            pokemon_count = 0

    if current_lines:
        pages.append(flush_page(current_lines, include_summary=is_first_page))

    total = len(pages)
    for i, embed in enumerate(pages):
        embed.set_footer(
            text=f"Page {i + 1}/{total} • {sum(len(d.get('pokemon', [])) for d in reserve_docs)} total reserved"
        )

    return pages


# ---------------------------------------------------------------------------
# Reserve Cog
# ---------------------------------------------------------------------------
class Reserve(commands.Cog):
    """Server-specific Pokémon reserve system."""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    @property
    def db(self):
        return self.bot.db

    @property
    def gcache(self):
        # gcache is attached to db by prediction.py on cog init
        return getattr(self.bot.db, "gcache", None)

    # ------------------------------------------------------------------
    # Permission check helper
    # ------------------------------------------------------------------
    async def _has_reserve_permission(self, ctx_or_interaction) -> bool:
        """
        Returns True if the user is an admin/server-owner/bot-owner
        OR has one of the guild's reserve allowed roles.
        """
        if isinstance(ctx_or_interaction, commands.Context):
            user = ctx_or_interaction.author
            guild = ctx_or_interaction.guild
            is_owner = await self.bot.is_owner(user)
        else:
            user = ctx_or_interaction.user
            guild = ctx_or_interaction.guild
            is_owner = await self.bot.is_owner(user)

        if is_owner:
            return True
        if user.id == guild.owner_id:
            return True
        if user.guild_permissions.administrator:
            return True

        # Check allowed roles
        if self.gcache:
            allowed = await self.gcache.get_reserve_allowed_roles(guild.id)
        else:
            allowed = await self.db.get_reserve_allowed_roles(guild.id)

        user_role_ids = {r.id for r in user.roles}
        return bool(user_role_ids & set(allowed))

    # ------------------------------------------------------------------
    # Pokemon resolution helpers
    # ------------------------------------------------------------------
    def _resolve_pokemon_names(self, raw_input: str) -> tuple[list[str], list[str]]:
        """
        Parse a comma-separated pokemon string.
        Supports 'furfrou all' / 'all furfrou' for all variants.
        Returns (valid_names, invalid_names).
        """
        parts = [p.strip() for p in raw_input.split(",") if p.strip()]
        valid, invalid = [], []

        for part in parts:
            low = part.lower()
            is_all = low.endswith(" all") or low.startswith("all ")

            if is_all:
                base = part[4:].strip() if low.startswith("all ") else part[:-4].strip()
                variants = get_pokemon_with_variants(base, self.pokemon_data)
                if variants:
                    valid.extend(variants)
                else:
                    invalid.append(part)
            else:
                mon = find_pokemon_by_name_flexible(part, self.pokemon_data)
                if mon and mon.get("name"):
                    valid.append(mon["name"])
                else:
                    invalid.append(part)

        return valid, invalid

    async def _resolve_category_pokemon(
        self, guild_id: int, category_key: str
    ) -> tuple[list[str], str]:
        """
        Resolve a category name to a list of pokemon from this server's categories.
        Returns (pokemon_list, source_description).

        Note: default categories (rare, regional, gigantamax) must be imported into
        the server first via `p!cat defaults` before they can be used here.
        """
        cat = await self.db.get_category(guild_id, category_key)
        if cat:
            return cat.get("pokemon", []), f"server category **{category_key}**"
        return [], ""

    # ------------------------------------------------------------------
    # Main group
    # ------------------------------------------------------------------
    @commands.group(name="reserve", aliases=["r"], invoke_without_command=True)
    async def reserve_group(self, ctx):
        """Reserve system — see `p!reserve help` for all subcommands."""
        if ctx.invoked_subcommand is None:
            await self._send_help(ctx)

    async def _send_help(self, ctx):
        p = ctx.prefix
        embed = discord.Embed(
            title="💾 Reserve System",
            color=EMBED_COLOR,
            description="Server-specific Pokémon reservation system. Users can reserve Pokemon they want to collect!",
        )

        embed.add_field(
            name="👥 **User Commands** (No permission needed)",
            value=(
                f"`{p}r list` — View all reserves in this server (sorted by count)\n"
                f"`{p}r list @user` — View a specific user's reserves\n"
                f"`{p}r remove p <pokemon,...>` — Remove Pokemon from your reserves\n"
                f"`{p}r remove pokemon <pokemon,...>` — Same as above\n"
                f"`{p}r remove cat <category>` — Remove a category from your reserves\n"
                f"`{p}r clear` — Clear all your reserves ⚠️"
            ),
            inline=False
        )

        embed.add_field(
            name="🔐 **Admin Commands** (Admin/Owner only)",
            value=(
                f"`{p}r add p @user <pokemon,...>` — Add Pokemon to user's reserves\n"
                f"`{p}r add pokemon @user <pokemon,...>` — Same as above\n"
                f"`{p}r add cat @user <category>` — Add category to user's reserves\n"
                f"`{p}r remove p @user <pokemon,...>` — Remove Pokemon from user's reserves\n"
                f"`{p}r remove cat @user <category>` — Remove category from user's reserves\n"
                f"`{p}r clear @user` — Clear a user's reserves\n"
                f"`{p}r clear --all` — Clear ALL reserves in server ⚠️"
            ),
            inline=False
        )

        embed.add_field(
            name="🛠️ **Allowed Roles** (Admin only)",
            value=(
                f"`{p}r allowedroles` — View allowed roles\n"
                f"`{p}r allowedroles add <@role|id>` — Add role to reserve permissions\n"
                f"`{p}r allowedroles remove <@role|id>` — Remove role\n"
                f"`{p}r allowedroles clear` — Clear all allowed roles"
            ),
            inline=False
        )

        embed.add_field(
            name="💡 **Tips**",
            value=(
                f"• Aliases: `p` = `pokemon`, `poke` | `cat` = `category`\n"
                f"• Use `{p}cat defaults` to add built-in categories (rare, regional, gigantamax)\n"
                f"• Use `{p}help reserve` for detailed help with examples"
            ),
            inline=False
        )

        await ctx.reply(embed=embed, mention_author=False)

    # ------------------------------------------------------------------
    # p!reserve add pokemon <user> <pokemon,...>
    # ------------------------------------------------------------------
    @reserve_group.command(name="add")
    async def reserve_add(
        self, ctx, subtype: str, user: discord.User, *, pokemon_input: str
    ):
        """
        Add pokemon or category to a user's reserves.
        Subtype: 'pokemon'/'poke'/'p' or 'cat'/'category'
        """
        if not await self._has_reserve_permission(ctx):
            await ctx.reply(
                "❌ You don't have permission to use reserve commands.",
                mention_author=False,
            )
            return

        subtype = subtype.lower()

        if subtype in ("pokemon", "poke", "p"):
            valid, invalid = self._resolve_pokemon_names(pokemon_input)
            if not valid:
                msg = "❌ No valid Pokémon names found."
                if invalid:
                    msg += f" Invalid: {', '.join(invalid[:10])}"
                await ctx.reply(msg, mention_author=False)
                return

            await self.db.add_pokemon_to_reserve(user.id, ctx.guild.id, valid)

            resp = f"✅ Added {len(valid)} Pokémon to {user.mention}'s reserve"
            if len(valid) <= 10:
                resp += f": {', '.join(valid)}"
            else:
                resp += f": {', '.join(valid[:10])} and {len(valid) - 10} more"
            if invalid:
                resp += f"\n❌ Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(resp, mention_author=False)

        elif subtype in ("cat", "category"):
            # Split by comma to handle multiple categories
            cat_names = [c.strip() for c in pokemon_input.split(",") if c.strip()]
            
            if not cat_names:
                await ctx.reply(
                    f"❌ Please provide at least one category name.",
                    mention_author=False,
                )
                return
            
            all_pokes = []
            all_sources = []
            not_found = []
            
            for cat_name in cat_names:
                pokes, source = await self._resolve_category_pokemon(
                    ctx.guild.id, cat_name
                )
                if pokes:
                    all_pokes.extend(pokes)
                    all_sources.append(source)
                else:
                    not_found.append(cat_name)
            
            if not all_pokes:
                await ctx.reply(
                    f"❌ No categories found: {', '.join(not_found)}\n"
                    f"Admins can add built-in categories with `{ctx.prefix}cat defaults`.",
                    mention_author=False,
                )
                return
            
            # Remove duplicates while preserving order
            all_pokes = list(dict.fromkeys(all_pokes))
            
            await self.db.add_pokemon_to_reserve(user.id, ctx.guild.id, all_pokes)
            
            resp = f"✅ Added {len(all_pokes)} Pokémon from {len(all_sources)} categor{'y' if len(all_sources) == 1 else 'ies'} to {user.mention}'s reserve"
            if all_sources:
                resp += f": {', '.join(all_sources)}"
            if not_found:
                resp += f"\n⚠️ Not found: {', '.join(not_found)}"
            
            await ctx.reply(resp, mention_author=False)
        else:
            await ctx.reply(
                f"❌ Unknown subtype `{subtype}`. Use `pokemon` or `cat`.",
                mention_author=False,
            )

    @reserve_add.error
    async def reserve_add_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}r add pokemon|poke|p <@user> <pokemon,...>` "
                f"or `{ctx.prefix}r add cat|category <@user> <category>`",
                mention_author=False,
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.reply(
                "❌ Could not find that user. Use a @mention or user ID.",
                mention_author=False,
            )

    # ------------------------------------------------------------------
    # p!reserve remove pokemon|poke|p <pokemon,...>
    # OR p!reserve remove pokemon|poke|p <@user> <pokemon,...>  (admin only)
    # ------------------------------------------------------------------
    @reserve_group.command(name="remove")
    async def reserve_remove(self, ctx, subtype: str = None, *, pokemon_input: str = None):
        """
        Remove pokemon or category from reserves.
        User can remove from their own: p!r remove p pikachu,meowth
        Admin can remove from others: p!r remove p @user pikachu,meowth
        """
        if subtype is None or pokemon_input is None:
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}r remove pokemon|poke|p <pokemon,...>` "
                f"(remove from yourself)\n"
                f"or `{ctx.prefix}r remove pokemon|poke|p <@user> <pokemon,...>` (admin only)",
                mention_author=False,
            )
            return

        subtype = subtype.lower()

        # Try to parse if there's a user mention in pokemon_input
        target_user = ctx.author  # Default to command author
        target_pokemon_input = pokemon_input
        
        # Check if first part of pokemon_input is a user mention or ID
        parts = pokemon_input.split(None, 1)  # Split on first space
        first_part = parts[0]
        
        # Check if it looks like a user mention or ID
        if first_part.startswith("<@") or (first_part.lstrip("<@!>").rstrip(">").isdigit()):
            # Might be a user mention/ID
            raw_user = first_part.strip("<@!>")
            if raw_user.isdigit():
                potential_uid = int(raw_user)
                # Check if this is a valid user in the guild
                try:
                    potential_user = await ctx.bot.fetch_user(potential_uid)
                    # Admin check for removing from other users
                    if not await self._has_reserve_permission(ctx):
                        await ctx.reply(
                            "❌ You don't have permission to remove reserves from other users.",
                            mention_author=False,
                        )
                        return
                    target_user = potential_user
                    target_pokemon_input = parts[1] if len(parts) > 1 else ""
                except:
                    # Not a valid user, treat as pokemon name
                    pass

        if not target_pokemon_input.strip():
            await ctx.reply(
                "❌ Please specify pokemon or category to remove.",
                mention_author=False,
            )
            return

        if subtype in ("pokemon", "poke", "p"):
            valid, invalid = self._resolve_pokemon_names(target_pokemon_input)
            if not valid:
                msg = "❌ No valid Pokémon names found."
                if invalid:
                    msg += f" Invalid: {', '.join(invalid[:10])}"
                await ctx.reply(msg, mention_author=False)
                return

            modified = await self.db.remove_pokemon_from_reserve(
                target_user.id, ctx.guild.id, valid
            )
            if modified:
                resp = f"✅ Removed {len(valid)} Pokémon from {target_user.mention}'s reserve"
                if len(valid) <= 10:
                    resp += f": {', '.join(valid)}"
                else:
                    resp += f": {', '.join(valid[:10])} and {len(valid) - 10} more"
            else:
                resp = (
                    f"⚠️ No changes — those Pokémon weren't in {target_user.mention}'s reserve."
                )
            if invalid:
                resp += f"\n❌ Invalid: {', '.join(invalid[:10])}"
            await ctx.reply(resp, mention_author=False)

        elif subtype in ("cat", "category"):
            # Split by comma to handle multiple categories
            cat_names = [c.strip() for c in target_pokemon_input.split(",") if c.strip()]
            
            if not cat_names:
                await ctx.reply(
                    f"❌ Please provide at least one category name.",
                    mention_author=False,
                )
                return
            
            all_pokes = []
            all_sources = []
            not_found = []
            
            for cat_name in cat_names:
                pokes, source = await self._resolve_category_pokemon(
                    ctx.guild.id, cat_name
                )
                if pokes:
                    all_pokes.extend(pokes)
                    all_sources.append(source)
                else:
                    not_found.append(cat_name)
            
            if not all_pokes:
                await ctx.reply(
                    f"❌ No categories found: {', '.join(not_found)}\n"
                    f"Admins can add built-in categories with `{ctx.prefix}cat defaults`.",
                    mention_author=False,
                )
                return
            
            # Remove duplicates while preserving order
            all_pokes = list(dict.fromkeys(all_pokes))
            
            await self.db.remove_pokemon_from_reserve(target_user.id, ctx.guild.id, all_pokes)
            
            resp = f"✅ Removed {len(all_pokes)} Pokémon from {len(all_sources)} categor{'y' if len(all_sources) == 1 else 'ies'} from {target_user.mention}'s reserve"
            if all_sources:
                resp += f": {', '.join(all_sources)}"
            if not_found:
                resp += f"\n⚠️ Not found: {', '.join(not_found)}"
            
            await ctx.reply(resp, mention_author=False)
        else:
            await ctx.reply(
                f"❌ Unknown subtype `{subtype}`. Use `pokemon|poke|p` or `cat|category`.",
                mention_author=False,
            )

    @reserve_remove.error
    async def reserve_remove_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}r remove pokemon|poke|p <pokemon,...>` (remove from yourself)\n"
                f"or `{ctx.prefix}r remove pokemon|poke|p <@user> <pokemon,...>` (admin only)\n"
                f"or `{ctx.prefix}r remove cat|category <category>`",
                mention_author=False,
            )
        elif isinstance(error, commands.BadArgument):
            await ctx.reply(
                "❌ Could not find that user. Use a @mention or user ID.",
                mention_author=False,
            )

    # ------------------------------------------------------------------
    # p!reserve clear [user]
    # ------------------------------------------------------------------
    @reserve_group.command(name="clear")
    async def reserve_clear(self, ctx, target: str = None):
        """
        Clear reserves.
        Without argument: clears your own reserves.
        With @user or user ID: if it's yourself, clears your own; if it's someone else, admin only.
        Admin only: p!r clear --all (clears entire server).
        """
        if target is None:
            # User clears their own reserves - no permission needed
            cleared = await self.db.clear_user_reserve(ctx.author.id, ctx.guild.id)
            if cleared:
                await ctx.reply(
                    f"✅ Cleared your reserves in **{ctx.guild.name}**.",
                    mention_author=False,
                )
            else:
                await ctx.reply(
                    f"⚠️ You had no reserves in this server.",
                    mention_author=False,
                )
        elif target.lower() == "--all":
            # Admin clears entire server
            if not await self._has_reserve_permission(ctx):
                await ctx.reply(
                    "❌ You don't have permission to clear server reserves.",
                    mention_author=False,
                )
                return
            
            count = await self.db.clear_all_reserves(ctx.guild.id)
            await ctx.reply(
                f"✅ Cleared all reserves in **{ctx.guild.name}** ({count} user entries removed).",
                mention_author=False,
            )
        else:
            # Check if target is the user themselves
            raw = target.strip("<@!>")
            if not raw.isdigit():
                await ctx.reply(
                    "❌ Invalid user. Use a @mention, user ID, or `--all` for whole server.",
                    mention_author=False,
                )
                return
            uid = int(raw)
            
            # If user mentions themselves, allow it without permission
            if uid == ctx.author.id:
                cleared = await self.db.clear_user_reserve(uid, ctx.guild.id)
                if cleared:
                    await ctx.reply(
                        f"✅ Cleared your reserves in **{ctx.guild.name}**.",
                        mention_author=False,
                    )
                else:
                    await ctx.reply(
                        f"⚠️ You had no reserves in this server.",
                        mention_author=False,
                    )
            else:
                # User mentioned someone else - need admin permission
                if not await self._has_reserve_permission(ctx):
                    await ctx.reply(
                        "❌ You don't have permission to clear other users' reserves.",
                        mention_author=False,
                    )
                    return
                
                cleared = await self.db.clear_user_reserve(uid, ctx.guild.id)
                if cleared:
                    await ctx.reply(
                        f"✅ Cleared reserves for <@{uid}> in this server.",
                        mention_author=False,
                    )
                else:
                    await ctx.reply(
                        f"⚠️ <@{uid}> had no reserves in this server.", mention_author=False
                    )

    # ------------------------------------------------------------------
    # p!reserve list [user]
    # ------------------------------------------------------------------
    @reserve_group.command(name="list")
    async def reserve_list(self, ctx, target: str = None):
        """
        Show reserves for this server or a specific user.
        Without argument: shows all reserves in the server.
        With @user or user ID: shows only that user's reserves.
        """
        if target is None:
            # Show all reserves for the server
            docs = await self.db.get_all_reserves(ctx.guild.id)
            # Filter out empty docs
            docs = [d for d in docs if d.get("pokemon")]
            guild_name = ctx.guild.name
        else:
            # Show reserves for a specific user
            raw = target.strip("<@!>")
            if not raw.isdigit():
                await ctx.reply(
                    "❌ Invalid user. Use a @mention or numeric user ID.",
                    mention_author=False,
                )
                return
            uid = int(raw)
            pokemon_list = await self.db.get_user_reserve(uid, ctx.guild.id)
            if not pokemon_list:
                await ctx.reply(
                    f"⚠️ <@{uid}> has no reserves in this server.",
                    mention_author=False,
                )
                return
            # Wrap the pokemon list in a doc structure for build_reserve_list_embeds
            docs = [{"user_id": uid, "pokemon": pokemon_list}]
            guild_name = f"{ctx.guild.name} — <@{uid}>"

        pages = build_reserve_list_embeds(guild_name, docs)

        if len(pages) == 1:
            await ctx.reply(embed=pages[0], mention_author=False)
        else:
            view = ReserveListView(ctx.author.id, pages)
            msg = await ctx.reply(embed=pages[0], view=view, mention_author=False)
            view.message = msg

    # ------------------------------------------------------------------
    # p!reserve allowedroles  (subgroup)
    # ------------------------------------------------------------------
    @reserve_group.group(
        name="allowedroles", aliases=["ar", "roles"], invoke_without_command=True
    )
    async def allowed_roles_group(self, ctx):
        """View or manage roles allowed to use reserve commands."""
        if ctx.invoked_subcommand is None:
            await self._show_allowed_roles(ctx)

    async def _show_allowed_roles(self, ctx):
        # Only admins/owner can view this
        is_admin = ctx.author.guild_permissions.administrator
        is_owner = await self.bot.is_owner(ctx.author)
        is_srv_owner = ctx.author.id == ctx.guild.owner_id
        if not (is_admin or is_owner or is_srv_owner):
            await ctx.reply(
                "❌ You need administrator permissions to view allowed roles.",
                mention_author=False,
            )
            return

        role_ids = await self.db.get_reserve_allowed_roles(ctx.guild.id)
        if not role_ids:
            embed = discord.Embed(
                title="🔐 Reserve — Allowed Roles",
                description="No extra roles set. Only admins and the server owner can use reserve commands.\n\n"
                f"Use `{ctx.prefix}r allowedroles add <@role|id>` to add a role.",
                color=EMBED_COLOR,
            )
        else:
            lines = []
            for rid in role_ids:
                role = ctx.guild.get_role(rid)
                lines.append(
                    f"• {role.mention} (`{rid}`)"
                    if role
                    else f"• ~~Unknown role~~ (`{rid}`) — deleted?"
                )
            embed = discord.Embed(
                title="🔐 Reserve — Allowed Roles",
                description="\n".join(lines),
                color=EMBED_COLOR,
            )
            embed.set_footer(
                text=f"{len(role_ids)} role(s) — these can use all reserve commands"
            )
        await ctx.reply(embed=embed, mention_author=False)

    @allowed_roles_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def allowed_roles_add(self, ctx, *, role_input: str):
        """Add a role to the reserve allowed list. Use @mention or role ID."""
        role = await self._resolve_role(ctx, role_input)
        if role is None:
            await ctx.reply(
                "❌ Could not find that role. Use @mention or role ID.",
                mention_author=False,
            )
            return
        await self.db.add_reserve_allowed_role(ctx.guild.id, role.id)
        await ctx.reply(
            f"✅ {role.mention} can now use reserve commands.", mention_author=False
        )

    @allowed_roles_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def allowed_roles_remove(self, ctx, *, role_input: str):
        """Remove a role from the reserve allowed list."""
        role = await self._resolve_role(ctx, role_input)
        if role is None:
            await ctx.reply(
                "❌ Could not find that role. Use @mention or role ID.",
                mention_author=False,
            )
            return
        await self.db.remove_reserve_allowed_role(ctx.guild.id, role.id)
        await ctx.reply(
            f"✅ {role.mention} removed from reserve allowed roles.",
            mention_author=False,
        )

    @allowed_roles_group.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def allowed_roles_clear(self, ctx):
        """Remove all allowed roles from the reserve system for this server."""
        await self.db.clear_reserve_allowed_roles(ctx.guild.id)
        await ctx.reply("✅ All reserve allowed roles cleared.", mention_author=False)

    async def _resolve_role(self, ctx, role_input: str) -> Optional[discord.Role]:
        """Resolve a role from a mention string or raw ID."""
        raw = role_input.strip("<@&> ")
        if raw.isdigit():
            return ctx.guild.get_role(int(raw))
        # Try name match
        low = role_input.lower().strip()
        for role in ctx.guild.roles:
            if role.name.lower() == low:
                return role
        return None

    # ------------------------------------------------------------------
    # Error handlers for allowed_roles subcommands
    # ------------------------------------------------------------------
    @allowed_roles_add.error
    @allowed_roles_remove.error
    @allowed_roles_clear.error
    async def allowed_roles_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply(
                "❌ You need administrator permissions to manage allowed roles.",
                mention_author=False,
            )
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(
                f"❌ Please provide a role mention or ID.", mention_author=False
            )

    # ------------------------------------------------------------------
    # Global error handler for the reserve group
    # ------------------------------------------------------------------
    @reserve_group.error
    async def reserve_group_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        await ctx.reply(
            f"❌ An error occurred: {str(error)[:200]}", mention_author=False
        )


async def setup(bot):
    await bot.add_cog(Reserve(bot))
