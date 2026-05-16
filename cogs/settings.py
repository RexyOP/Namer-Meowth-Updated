"""Server and user settings management"""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from config import EMBED_COLOR, Emojis

# ---------------------------------------------------------------------------
# AFK view – 4 toggles: ShinyHunt, Collection, TypePings, RegionPings
# ---------------------------------------------------------------------------
class AFKView(discord.ui.View):
    """AFK toggle buttons (global)"""

    def __init__(self, user_id, collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog = cog
        self.message: discord.Message | None = None
        self.update_buttons(collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk)

    def update_buttons(self, collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk):
        self.clear_items()

        def _btn(label, afk, custom_id):
            """Red = currently AFK (pings suppressed). Green = active (pings on)."""
            b = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.red if afk else discord.ButtonStyle.green,
                custom_id=custom_id,
            )
            return b

        shiny_btn = _btn("ShinyHunt", shiny_hunt_afk, "afk_shiny")
        shiny_btn.callback = self.toggle_shiny_hunt_afk
        self.add_item(shiny_btn)

        col_btn = _btn("Collection", collection_afk, "afk_collection")
        col_btn.callback = self.toggle_collection_afk
        self.add_item(col_btn)

        type_btn = _btn("TypePings", type_ping_afk, "afk_type")
        type_btn.callback = self.toggle_type_ping_afk
        self.add_item(type_btn)

        rgn_btn = _btn("RegionPings", region_ping_afk, "afk_region")
        rgn_btn.callback = self.toggle_region_ping_afk
        self.add_item(rgn_btn)

        # ── Row 2: bulk buttons ──────────────────────────────────────────
        all_afk = all([collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk])
        all_on  = not any([collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk])

        disable_all_btn = discord.ui.Button(
            label="AFK All",
            style=discord.ButtonStyle.danger,
            custom_id="afk_disable_all",
            disabled=all_afk,   # grey out if already fully AFK
            row=1,
        )
        disable_all_btn.callback = self.disable_all
        self.add_item(disable_all_btn)

        enable_all_btn = discord.ui.Button(
            label="Enable All",
            style=discord.ButtonStyle.success,
            custom_id="afk_enable_all",
            disabled=all_on,    # grey out if already all active
            row=1,
        )
        enable_all_btn.callback = self.enable_all
        self.add_item(enable_all_btn)

    def _create_embed(self, collection_afk, shiny_hunt_afk, type_ping_afk, region_ping_afk):
        def _dot(afk):
            return Emojis.GREY_DOT if afk else Emojis.GREEN_DOT

        embed = discord.Embed(
            title="Global AFK Status",
            description=(
                f"✨ ShinyHunt Pings: {_dot(shiny_hunt_afk)}\n"
                f"📚 Collection Pings: {_dot(collection_afk)}\n"
                f"🔷 Type Pings: {_dot(type_ping_afk)}\n"
                f"🌏 Region Pings: {_dot(region_ping_afk)}\n\n"
                "*AFK status applies across all servers*"
            ),
            color=EMBED_COLOR,
        )
        return embed

    async def _check_user(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return False
        return True

    async def toggle_collection_afk(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        new_col  = await self.cog.db.toggle_collection_afk(self.user_id)
        new_shy  = await self.cog.db.is_shiny_hunt_afk(self.user_id)
        new_type = await self.cog.db.is_type_ping_afk(self.user_id)
        new_rgn  = await self.cog.db.is_region_ping_afk(self.user_id)
        self.update_buttons(new_col, new_shy, new_type, new_rgn)
        await interaction.response.edit_message(embed=self._create_embed(new_col, new_shy, new_type, new_rgn), view=self)

    async def toggle_shiny_hunt_afk(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        new_shy  = await self.cog.db.toggle_shiny_hunt_afk(self.user_id)
        new_col  = await self.cog.db.is_collection_afk(self.user_id)
        new_type = await self.cog.db.is_type_ping_afk(self.user_id)
        new_rgn  = await self.cog.db.is_region_ping_afk(self.user_id)
        self.update_buttons(new_col, new_shy, new_type, new_rgn)
        await interaction.response.edit_message(embed=self._create_embed(new_col, new_shy, new_type, new_rgn), view=self)

    async def toggle_type_ping_afk(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        new_type = await self.cog.db.toggle_type_ping_afk(self.user_id)
        new_col  = await self.cog.db.is_collection_afk(self.user_id)
        new_shy  = await self.cog.db.is_shiny_hunt_afk(self.user_id)
        new_rgn  = await self.cog.db.is_region_ping_afk(self.user_id)
        self.update_buttons(new_col, new_shy, new_type, new_rgn)
        await interaction.response.edit_message(embed=self._create_embed(new_col, new_shy, new_type, new_rgn), view=self)

    async def toggle_region_ping_afk(self, interaction: discord.Interaction):
        if not await self._check_user(interaction):
            return
        new_rgn  = await self.cog.db.toggle_region_ping_afk(self.user_id)
        new_col  = await self.cog.db.is_collection_afk(self.user_id)
        new_shy  = await self.cog.db.is_shiny_hunt_afk(self.user_id)
        new_type = await self.cog.db.is_type_ping_afk(self.user_id)
        self.update_buttons(new_col, new_shy, new_type, new_rgn)
        await interaction.response.edit_message(embed=self._create_embed(new_col, new_shy, new_type, new_rgn), view=self)

    async def disable_all(self, interaction: discord.Interaction):
        """Set AFK = True on all 4 types at once."""
        if not await self._check_user(interaction):
            return
        await asyncio.gather(
            self.cog.db.set_collection_afk(self.user_id, True),
            self.cog.db.set_shiny_hunt_afk(self.user_id, True),
            self.cog.db.set_type_ping_afk(self.user_id, True),
            self.cog.db.set_region_ping_afk(self.user_id, True),
        )
        self.update_buttons(True, True, True, True)
        await interaction.response.edit_message(embed=self._create_embed(True, True, True, True), view=self)

    async def enable_all(self, interaction: discord.Interaction):
        """Set AFK = False on all 4 types at once."""
        if not await self._check_user(interaction):
            return
        await asyncio.gather(
            self.cog.db.set_collection_afk(self.user_id, False),
            self.cog.db.set_shiny_hunt_afk(self.user_id, False),
            self.cog.db.set_type_ping_afk(self.user_id, False),
            self.cog.db.set_region_ping_afk(self.user_id, False),
        )
        self.update_buttons(False, False, False, False)
        await interaction.response.edit_message(embed=self._create_embed(False, False, False, False), view=self)

    async def on_timeout(self):
        self.clear_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.message = None
        self.cog = None


# ---------------------------------------------------------------------------
# Confirm view for /clear-pings
# ---------------------------------------------------------------------------
class _ClearPingsConfirmView(discord.ui.View):
    def __init__(self, author_id, db, bot, guild, target_id, target_name):
        super().__init__(timeout=30)
        self.author_id   = author_id
        self.db          = db
        self.bot         = bot
        self.guild       = guild
        self.target_id   = target_id
        self.target_name = target_name

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not yours!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.stop()
        db_raw   = self.db.db
        guild_id = self.guild.id

        if self.target_id:
            col_res  = await db_raw.collections.delete_many( {"user_id": self.target_id, "guild_id": guild_id})
            shy_res  = await db_raw.shiny_hunts.delete_many( {"user_id": self.target_id, "guild_id": guild_id})
            type_res = await db_raw.type_pings.delete_many(  {"user_id": self.target_id, "guild_id": guild_id})
            rgn_res  = await db_raw.region_pings.delete_many({"user_id": self.target_id, "guild_id": guild_id})
            embed = discord.Embed(title="✅ User Ping Data Cleared", color=EMBED_COLOR)
            embed.add_field(name="User", value=f"{self.target_name} (`{self.target_id}`)", inline=False)
        else:
            col_res  = await db_raw.collections.delete_many( {"guild_id": guild_id})
            shy_res  = await db_raw.shiny_hunts.delete_many( {"guild_id": guild_id})
            type_res = await db_raw.type_pings.delete_many(  {"guild_id": guild_id})
            rgn_res  = await db_raw.region_pings.delete_many({"guild_id": guild_id})
            embed = discord.Embed(title="✅ Server Ping Data Cleared", color=EMBED_COLOR)

        embed.add_field(name="Server",       value=self.guild.name,                    inline=False)
        embed.add_field(name="Collections",  value=f"{col_res.deleted_count} removed",  inline=True)
        embed.add_field(name="Shiny Hunts",  value=f"{shy_res.deleted_count} removed",  inline=True)
        embed.add_field(name="Type Pings",   value=f"{type_res.deleted_count} removed",  inline=True)
        embed.add_field(name="Region Pings", value=f"{rgn_res.deleted_count} removed",  inline=True)
        embed.set_footer(text=f"Cleared by {interaction.user} • Guild ID: {guild_id}")
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled. No data was cleared.", view=None)

    async def on_timeout(self):
        pass  # ephemeral message — no edit needed


# ---------------------------------------------------------------------------
# Settings cog
# ---------------------------------------------------------------------------
class Settings(commands.Cog):
    """Server and user settings"""

    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------------
    # p!afk
    # ------------------------------------------------------------------
    @commands.command(name="afk", aliases=["away"])
    async def afk_command(self, ctx):
        """Toggle global AFK status for collection, shiny hunt, type, and region pings"""
        col_afk  = await self.db.is_collection_afk(ctx.author.id)
        shy_afk  = await self.db.is_shiny_hunt_afk(ctx.author.id)
        type_afk = await self.db.is_type_ping_afk(ctx.author.id)
        rgn_afk  = await self.db.is_region_ping_afk(ctx.author.id)

        def _dot(afk):
            return Emojis.GREY_DOT if afk else Emojis.GREEN_DOT

        embed = discord.Embed(
            title="Global AFK Status",
            description=(
                f"✨ ShinyHunt Pings: {_dot(shy_afk)}\n"
                f"📚 Collection Pings: {_dot(col_afk)}\n"
                f"🔷 Type Pings: {_dot(type_afk)}\n"
                f"🌏 Region Pings: {_dot(rgn_afk)}\n\n"
                "*AFK status applies across all servers*"
            ),
            color=EMBED_COLOR,
        )

        view = AFKView(ctx.author.id, col_afk, shy_afk, type_afk, rgn_afk, self)
        msg = await ctx.reply(embed=embed, view=view, mention_author=False)
        view.message = msg

    # ------------------------------------------------------------------
    # p!force-afk  (admin only)
    # ------------------------------------------------------------------

    _FORCE_AFK_TYPES = {"collection", "shinyhunt", "typepings", "regionpings", "all"}
    _FORCE_AFK_LABELS = {
        "collection":  "Collection",
        "shinyhunt":   "ShinyHunt",
        "typepings":   "TypePings",
        "regionpings": "RegionPings",
    }

    @commands.command(name="force-afk", aliases=["forceafk", "fafk"])
    @commands.has_permissions(administrator=True)
    async def force_afk_command(self, ctx, target: str = None, ping_type: str = None, state: str = None):
        """Force a user's AFK state on one or all ping types.

        Usage:
            p!force-afk @user all on          — force AFK on all 4 types
            p!force-afk @user all off         — remove AFK on all 4 types
            p!force-afk @user collection on   — force collection AFK only
            p!force-afk @user shinyhunt off   — remove shiny hunt AFK only
            p!force-afk @user typepings on
            p!force-afk @user regionpings off

        Ping types: collection, shinyhunt, typepings, regionpings, all
        State:      on / off
        """
        p = ctx.prefix

        # ── resolve user ──────────────────────────────────────────────
        if target is None:
            await ctx.reply(
                f"❌ Usage: `{p}force-afk @user <type> <on|off>`\n"
                f"Types: `collection` `shinyhunt` `typepings` `regionpings` `all`",
                mention_author=False,
            )
            return

        raw = target.strip("<@!>")
        if not raw.isdigit():
            await ctx.reply("❌ Invalid user. Use a @mention or numeric user ID.", mention_author=False)
            return
        uid = int(raw)

        # ── validate type & state ─────────────────────────────────────
        if ping_type is None or state is None:
            await ctx.reply(
                f"❌ Usage: `{p}force-afk @user <type> <on|off>`\n"
                f"Types: `collection` `shinyhunt` `typepings` `regionpings` `all`",
                mention_author=False,
            )
            return

        ping_type = ping_type.lower()
        state     = state.lower()

        if ping_type not in self._FORCE_AFK_TYPES:
            await ctx.reply(
                f"❌ Unknown type `{ping_type}`. Choose from: `collection` `shinyhunt` `typepings` `regionpings` `all`",
                mention_author=False,
            )
            return

        if state not in ("on", "off"):
            await ctx.reply("❌ State must be `on` or `off`.", mention_author=False)
            return

        afk = (state == "on")

        # ── resolve which types to update ────────────────────────────
        if ping_type == "all":
            types_to_set = list(self._FORCE_AFK_LABELS.keys())
        else:
            types_to_set = [ping_type]

        # ── write all changes concurrently ───────────────────────────
        _setters = {
            "collection":  self.db.set_collection_afk,
            "shinyhunt":   self.db.set_shiny_hunt_afk,
            "typepings":   self.db.set_type_ping_afk,
            "regionpings": self.db.set_region_ping_afk,
        }
        await asyncio.gather(*[_setters[t](uid, afk) for t in types_to_set])

        # ── build response embed ──────────────────────────────────────
        icon   = "🔴" if afk else "🟢"
        action = "forced AFK" if afk else "removed AFK"
        labels = [self._FORCE_AFK_LABELS[t] for t in types_to_set]

        embed = discord.Embed(
            title=f"{icon} Force-AFK — {'All Types' if ping_type == 'all' else labels[0]}",
            color=discord.Color.red() if afk else discord.Color.green(),
        )
        embed.add_field(name="User",   value=f"<@{uid}>",             inline=True)
        embed.add_field(name="State",  value=f"AFK **{'ON' if afk else 'OFF'}**", inline=True)
        embed.add_field(name="Types",  value="\n".join(f"• {l}" for l in labels), inline=False)
        embed.set_footer(text=f"Done by {ctx.author} • User can override with p!afk")
        await ctx.reply(embed=embed, mention_author=False)

    @force_afk_command.error
    async def force_afk_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)

    # ------------------------------------------------------------------
    # p!role  (group) — shows usage when invoked without subcommand
    # ------------------------------------------------------------------

    @commands.group(name="role", aliases=["roles"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def role_group(self, ctx):
        """View or configure server ping roles.

        Subcommands:
            p!role rare [@role]      — set/clear the rare Pokémon ping role
            p!role regional [@role]  — set/clear the regional Pokémon ping role

        Run without a subcommand to see currently configured roles.
        """
        settings = await self.db.get_guild_settings(ctx.guild.id)
        p = ctx.prefix

        rare_id     = settings.get("rare_role_id")
        regional_id = settings.get("regional_role_id")

        # Fetch incense and reserve allowed roles concurrently.
        # Incense allowed roles live in user_data keyed by f"incense_guild_{guild_id}".
        async def _get_incense_allowed_roles():
            doc = await self.db.db.user_data.find_one({"user_id": f"incense_guild_{ctx.guild.id}"})
            return (doc or {}).get("incense_allowed_roles", [])

        inc_role_ids, rsv_role_ids = await asyncio.gather(
            _get_incense_allowed_roles(),
            self.db.get_reserve_allowed_roles(ctx.guild.id),
        )

        def _fmt_roles(role_ids: list) -> str:
            if not role_ids:
                return "Not set"
            parts = []
            for rid in role_ids:
                role = ctx.guild.get_role(rid)
                parts.append(role.mention if role else f"*(unknown `{rid}`)*")
            return "\n".join(parts)

        embed = discord.Embed(
            title="📋 Server Ping Roles",
            color=EMBED_COLOR,
        )

        # ── Ping roles (row 1) ───────────────────────────────────────────
        embed.add_field(
            name="Rare Role",
            value=f"<@&{rare_id}>" if rare_id else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Regional Role",
            value=f"<@&{regional_id}>" if regional_id else "Not set",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        # ── Allowed roles (row 2) ────────────────────────────────────────
        embed.add_field(
            name="🔥 Incense Allowed Roles",
            value=_fmt_roles(inc_role_ids),
            inline=True,
        )
        embed.add_field(
            name="📌 Reserve Allowed Roles",
            value=_fmt_roles(rsv_role_ids),
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        embed.add_field(
            name="ℹ️ How to set",
            value=(
                f"`{p}role rare @Role` — set rare ping role  (omit @Role to clear)\n"
                f"`{p}role regional @Role` — set regional ping role  (omit @Role to clear)\n"
                f"`{p}inc allowedroles add @Role` — add incense allowed role\n"
                f"`{p}r allowedroles add @Role` — add reserve allowed role"
            ),
            inline=False,
        )
        await ctx.reply(embed=embed, mention_author=False)

    @role_group.error
    async def role_group_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)

    # ── p!role rare [@role] ────────────────────────────────────────────

    @role_group.command(name="rare", aliases=["r"])
    @commands.has_permissions(administrator=True)
    async def role_rare_cmd(self, ctx, role: discord.Role = None):
        """Set or clear the rare Pokémon ping role for this server (Admin only).

        Examples:
            p!role rare @Rare Hunters   → set the rare role
            p!role rare                  → clear / disable
        """
        if role is None:
            await self.db.set_rare_role(ctx.guild.id, None)
            await ctx.reply("✅ Rare role cleared.", mention_author=False)
        else:
            await self.db.set_rare_role(ctx.guild.id, role.id)
            await ctx.reply(f"✅ Rare role set to {role.mention}", mention_author=False)

    @role_rare_cmd.error
    async def role_rare_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            # Accept "none" explicitly typed
            if ctx.message.content.lower().split()[-1] == "none":
                await self.db.set_rare_role(ctx.guild.id, None)
                await ctx.reply("✅ Rare role cleared.", mention_author=False)
            else:
                await ctx.reply(
                    "❌ Invalid role. Mention a role, use its ID, or omit to clear.", mention_author=False
                )

    # ── p!role regional [@role] ────────────────────────────────────────

    @role_group.command(name="regional", aliases=["reg"])
    @commands.has_permissions(administrator=True)
    async def role_regional_cmd(self, ctx, role: discord.Role = None):
        """Set or clear the regional Pokémon ping role for this server (Admin only).

        Examples:
            p!role regional @Regional   → set the regional role
            p!role regional              → clear / disable
        """
        if role is None:
            await self.db.set_regional_role(ctx.guild.id, None)
            await ctx.reply("✅ Regional role cleared.", mention_author=False)
        else:
            await self.db.set_regional_role(ctx.guild.id, role.id)
            await ctx.reply(f"✅ Regional role set to {role.mention}", mention_author=False)

    @role_regional_cmd.error
    async def role_regional_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            if ctx.message.content.lower().split()[-1] == "none":
                await self.db.set_regional_role(ctx.guild.id, None)
                await ctx.reply("✅ Regional role cleared.", mention_author=False)
            else:
                await ctx.reply(
                    "❌ Invalid role. Mention a role, use its ID, or omit to clear.", mention_author=False
                )

    # ------------------------------------------------------------------
    # p!server-settings
    # ------------------------------------------------------------------
    @commands.command(name="server-settings", aliases=["ss", "ssettings", "serversettings"])
    async def server_settings_command(self, ctx):
        """View current server settings"""
        settings = await self.db.get_guild_settings(ctx.guild.id)
        p = ctx.prefix

        embed = discord.Embed(
            title=f"Server Settings — {ctx.guild.name}",
            color=EMBED_COLOR,
        )

        rare_role_id = settings.get("rare_role_id")
        embed.add_field(name="Rare Role",     value=f"<@&{rare_role_id}>" if rare_role_id else "Not set", inline=True)

        regional_role_id = settings.get("regional_role_id")
        embed.add_field(name="Regional Role", value=f"<@&{regional_role_id}>" if regional_role_id else "Not set", inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer row

        best_name_enabled = settings.get("best_name_enabled", False)
        embed.add_field(name="Best Name",        value="Enabled ✅" if best_name_enabled else "Disabled ❌", inline=True)

        only_pings = settings.get("only_pings", False)
        embed.add_field(name="Only-Pings",       value="Enabled ✅" if only_pings else "Disabled ❌", inline=True)

        catch_command_enabled = settings.get("catch_command_enabled", False)
        embed.add_field(name="Catch Command",    value="Enabled ✅" if catch_command_enabled else "Disabled ❌", inline=True)

        hint_solver_enabled = settings.get("hint_solver_enabled", True)
        embed.add_field(name="Hint Solver",      value="Enabled ✅" if hint_solver_enabled else "Disabled ❌", inline=True)

        embed.add_field(
            name="📺 Channel Config",
            value=f"Use `{p}channel settings` to view all configured channels",
            inline=False,
        )

        embed.set_footer(text=f"Guild ID: {ctx.guild.id}")
        await ctx.reply(embed=embed, mention_author=False)

    # ------------------------------------------------------------------
    # p!toggle <feature>
    # ------------------------------------------------------------------
    @commands.group(name="toggle", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def toggle_command(self, ctx, feature: str = None):
        """Toggle server features.

        Examples:
            p!toggle best_name
            p!toggle only_pings
            p!toggle catch_command
            p!toggle hint_solver
        """
        if feature is None:
            p = ctx.prefix
            embed = discord.Embed(
                title="⚙️ Toggle",
                description=(
                    f"`{p}toggle best_name` — Toggle best-name display\n"
                    f"`{p}toggle only_pings` — Toggle only-pings mode\n"
                    f"`{p}toggle catch_command` — Toggle catch command line in predictions\n"
                    f"`{p}toggle hint_solver` — Toggle automatic hint solving"
                ),
                color=EMBED_COLOR,
            )
            await ctx.reply(embed=embed, mention_author=False)
            return

        feature = feature.lower().replace("-", "_")

        if feature == "best_name":
            current = await self.db.get_best_name(ctx.guild.id)
            new_val = not current
            await self.db.set_best_name(ctx.guild.id, new_val)
            status = "enabled ✅" if new_val else "disabled ❌"
            await ctx.reply(f"Best Name display is now **{status}**", mention_author=False)

        elif feature == "only_pings":
            current = await self.db.get_only_pings(ctx.guild.id)
            new_val = not current
            await self.db.set_only_pings(ctx.guild.id, new_val)
            status = "enabled ✅" if new_val else "disabled ❌"
            await ctx.reply(f"Only-Pings mode is now **{status}**", mention_author=False)

        elif feature == "catch_command":
            current = await self.db.get_catch_command(ctx.guild.id)
            new_val = not current
            await self.db.set_catch_command(ctx.guild.id, new_val)
            status = "enabled ✅" if new_val else "disabled ❌"
            await ctx.reply(f"Catch command line is now **{status}**", mention_author=False)

        elif feature == "hint_solver":
            current = await self.db.get_hint_solver(ctx.guild.id)
            new_val = not current
            await self.db.set_hint_solver(ctx.guild.id, new_val)
            status = "enabled ✅" if new_val else "disabled ❌"
            await ctx.reply(f"Hint solver is now **{status}**", mention_author=False)

        else:
            await ctx.reply(
                f"❌ Unknown feature `{feature}`. Available: `best_name`, `only_pings`, `catch_command`, `hint_solver`",
                mention_author=False,
            )

    @toggle_command.error
    async def toggle_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.MissingRequiredArgument):
            p = ctx.prefix
            await ctx.reply(
                f"❌ Usage: `{p}toggle <feature>` (e.g. `{p}toggle best_name`, `{p}toggle only_pings`)",
                mention_author=False,
            )

    # ------------------------------------------------------------------
    # p!only-pings (kept for backward compat; thin wrapper over toggle)
    # ------------------------------------------------------------------
    @commands.command(name="only-pings", aliases=["op", "onlypings"])
    @commands.has_permissions(administrator=True)
    async def only_pings_command(self, ctx, enabled: bool = None):
        """Toggle or view only-pings mode. Also available as p!toggle only_pings"""
        if enabled is None:
            current_status = await self.db.get_only_pings(ctx.guild.id)
            status_text = "enabled ✅" if current_status else "disabled ❌"
            embed = discord.Embed(
                title="Only-Pings Mode",
                description=(
                    f"Current status: **{status_text}**\n\n"
                    "When enabled, predictions are only sent when there are collectors, "
                    "hunters, or rare/regional/type/region pings."
                ),
                color=EMBED_COLOR,
            )
            embed.set_footer(text="Use 'p!toggle only_pings' to toggle, or 'p!only-pings true/false' to set directly")
            await ctx.reply(embed=embed, mention_author=False)
            return

        await self.db.set_only_pings(ctx.guild.id, enabled)
        status = "enabled ✅" if enabled else "disabled ❌"
        await ctx.reply(f"Only-pings mode is now **{status}**", mention_author=False)

    @only_pings_command.error
    async def only_pings_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid argument. Use `true` or `false`", mention_author=False)

    # ------------------------------------------------------------------
    # p!clear-pings
    # ------------------------------------------------------------------
    @commands.command(name="clear-pings", aliases=["clearpings", "clearserverpings", "resetpings"])
    async def clear_server_pings_command(self, ctx, target: str = None):
        """Clear all ping data for a specific user or every user in this server.

        Usage:
            p!clear-pings             → clears ALL users in this server
            p!clear-pings @user       → clears only that user
            p!clear-pings <user_id>   → clears by raw ID (works even if user left)
        """
        # ── Resolve target user ID ─────────────────────────────────────
        target_id   = None
        target_name = None
        if target is not None:
            raw = target.strip("<@!>")
            if raw.isdigit():
                target_id = int(raw)
                user_obj = self.bot.get_user(target_id)
                if user_obj is None:
                    try:
                        user_obj = await self.bot.fetch_user(target_id)
                    except discord.NotFound:
                        pass
                target_name = str(user_obj) if user_obj else f"User {target_id}"
            else:
                await ctx.reply("❌ Invalid user. Use a @mention or numeric user ID.", mention_author=False)
                return

        # ── Permission check ───────────────────────────────────────────
        is_owner     = await self.bot.is_owner(ctx.author)
        is_srv_owner = ctx.author.id == ctx.guild.owner_id
        is_admin     = ctx.author.guild_permissions.administrator

        if not (is_owner or is_srv_owner or is_admin):
            await ctx.reply(
                "❌ You need to be the server owner, an administrator, or the bot owner to use this command.",
                mention_author=False,
            )
            return

        # ── Confirmation ───────────────────────────────────────────────
        if target_id:
            prompt_text = f"⚠️ This will clear **all ping data** for **{target_name}** (`{target_id}`) in **{ctx.guild.name}**."
        else:
            prompt_text = f"⚠️ This will clear **all ping data for every user** in **{ctx.guild.name}**."

        view = _ClearPingsConfirmView(
            author_id=ctx.author.id,
            db=self.db,
            bot=self.bot,
            guild=ctx.guild,
            target_id=target_id,
            target_name=target_name,
        )
        await ctx.reply(prompt_text, view=view, mention_author=False)

    @clear_server_pings_command.error
    async def clear_server_pings_error(self, ctx, error):
        await ctx.reply(f"❌ An unexpected error occurred: {error}", mention_author=False)

    # ------------------------------------------------------------------
    # Slash Commands
    # ------------------------------------------------------------------
    @app_commands.command(name="afk", description="Toggle your global AFK status for pings")
    async def slash_afk(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.afk_command(ctx)

    @app_commands.command(name="server-settings", description="View current server settings")
    async def slash_server_settings(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.server_settings_command(ctx)

    @app_commands.command(name="role-rare", description="Set or clear the rare Pokémon ping role (Admin only)")
    @app_commands.describe(role="The role to ping for rare Pokémon. Omit to clear.")
    @app_commands.default_permissions(administrator=True)
    async def slash_role_rare(self, interaction: discord.Interaction, role: discord.Role = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.role_rare_cmd(ctx, role=role)

    @app_commands.command(name="role-regional", description="Set or clear the regional Pokémon ping role (Admin only)")
    @app_commands.describe(role="The role to ping for regional Pokémon. Omit to clear.")
    @app_commands.default_permissions(administrator=True)
    async def slash_role_regional(self, interaction: discord.Interaction, role: discord.Role = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.role_regional_cmd(ctx, role=role)

    @app_commands.command(name="only-pings", description="Toggle or view only-pings mode (Admin only)")
    @app_commands.describe(enabled="true to enable, false to disable, omit to view current status")
    @app_commands.default_permissions(administrator=True)
    async def slash_only_pings(self, interaction: discord.Interaction, enabled: bool = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.only_pings_command(ctx, enabled=enabled)

    @app_commands.command(name="toggle-feature", description="Toggle a server feature (Admin only)")
    @app_commands.describe(feature="Feature to toggle: 'best_name', 'only_pings', 'catch_command', or 'hint_solver'")
    @app_commands.default_permissions(administrator=True)
    async def slash_toggle(self, interaction: discord.Interaction, feature: str):
        ctx = await commands.Context.from_interaction(interaction)
        await self.toggle_command(ctx, feature=feature)

    @app_commands.command(name="clear-pings", description="Clear all ping data for a user or the entire server (Admin only)")
    @app_commands.describe(target="@mention or user ID to clear a single user; leave blank to clear all users")
    @app_commands.default_permissions(administrator=True)
    async def slash_clear_pings(self, interaction: discord.Interaction, target: str = None):
        is_owner     = await self.bot.is_owner(interaction.user)
        is_srv_owner = interaction.user.id == interaction.guild.owner_id
        is_admin     = interaction.user.guild_permissions.administrator
        if not (is_owner or is_srv_owner or is_admin):
            return await interaction.response.send_message(
                "❌ You need to be the server owner, an administrator, or the bot owner.",
                ephemeral=True,
            )

        target_id = None
        target_name = None
        if target is not None:
            raw = target.strip("<@!>")
            if not raw.isdigit():
                return await interaction.response.send_message(
                    "❌ Invalid user. Use a @mention or numeric user ID.", ephemeral=True
                )
            target_id = int(raw)
            user_obj = self.bot.get_user(target_id)
            if user_obj is None:
                try:
                    user_obj = await self.bot.fetch_user(target_id)
                except discord.NotFound:
                    pass
            target_name = str(user_obj) if user_obj else f"User {target_id}"

        if target_id:
            prompt = f"⚠️ Clear **all ping data** for **{target_name}** (`{target_id}`) in **{interaction.guild.name}**?"
        else:
            prompt = f"⚠️ Clear **all ping data for every user** in **{interaction.guild.name}**?"

        view = _ClearPingsConfirmView(
            author_id=interaction.user.id,
            db=self.db,
            bot=self.bot,
            guild=interaction.guild,
            target_id=target_id,
            target_name=target_name,
        )
        await interaction.response.send_message(prompt, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))
