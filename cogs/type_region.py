"""Type and Region ping management """
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from config import EMBED_COLOR
from utils import is_role_blacklisted, slash_blacklist_check

NO_MENTIONS = discord.AllowedMentions.none()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "dark", "steel", "fairy"
]

ALL_REGIONS = [
    "kanto", "johto", "hoenn", "sinnoh", "unova",
    "kalos", "alola", "galar", "paldea", "kitakami", "unknown", "hisui", "pokopia"
]

# One emoji per type for the button labels
TYPE_EMOJI = {
    "normal":   "⚪", "fire":     "🔥", "water":    "💧", "electric": "⚡",
    "grass":    "🌿", "ice":      "❄️",  "fighting": "🥊", "poison":   "☠️",
    "ground":   "🏔️",  "flying":   "🕊️",  "psychic":  "🔮", "bug":      "🐛",
    "rock":     "🪨", "ghost":    "👻", "dragon":   "🐉", "dark":     "🌑",
    "steel":    "⚙️",  "fairy":    "🧚",
}

REGION_EMOJI = {
    "kanto":  "1️⃣", "johto":  "2️⃣", "hoenn":  "3️⃣", "sinnoh": "4️⃣",
    "unova":  "5️⃣", "kalos":  "6️⃣", "alola":  "7️⃣", "galar":  "8️⃣", "paldea": "9️⃣", "unknown": "❓", "kitakami": "🌏", "hisui": "🌏", "pokopia": "🌏",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_type_args(args: str) -> list[str]:
    """Parse space/comma separated type names into canonical lowercase list."""
    raw = args.replace(",", " ").split()
    valid = []
    for t in raw:
        t_low = t.lower()
        if t_low in ALL_TYPES:
            valid.append(t_low)
    return valid


def _parse_region_args(args: str) -> list[str]:
    raw = args.replace(",", " ").split()
    valid = []
    for r in raw:
        r_low = r.lower()
        if r_low in ALL_REGIONS:
            valid.append(r_low)
    return valid


def _admin_disabled_notice(kind: str) -> str:
    return f"🚫 Server admins have disabled **{kind}** pings in this server. Ask them to enable it."


def _limit_reached_notice(kind: str, limit: int) -> str:
    return f"⚠️ You can only have **{limit}** {kind} ping(s) enabled in this server. Disable one first."


def _footer_status(count: int, total: int, limit: Optional[int], admin_enabled: bool) -> str:
    parts = [f"Click a button to toggle • {count}/{total} enabled"]
    if limit is not None:
        parts.append(f"limit: {limit}")
    if not admin_enabled:
        parts.append("⚠️ disabled by server admins")
    return " • ".join(parts)


def _type_embed(user: discord.User, enabled_types: list[str], limit: Optional[int] = None, admin_enabled: bool = True) -> discord.Embed:
    lines = []
    for t in ALL_TYPES:
        emoji = TYPE_EMOJI.get(t, "")
        dot = "🟢" if t in enabled_types else "⚫"
        lines.append(f"{dot} {emoji} {t.capitalize()}")

    # Two-column layout
    half = len(lines) // 2
    col1 = "\n".join(lines[:half])
    col2 = "\n".join(lines[half:])

    embed = discord.Embed(title="🔷 Type Pings", color=EMBED_COLOR)
    if not admin_enabled:
        embed.description = _admin_disabled_notice("type")
    embed.add_field(name="\u200b", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.set_footer(text=_footer_status(len(enabled_types), len(ALL_TYPES), limit, admin_enabled))
    return embed


def _region_embed(user: discord.User, enabled_regions: list[str], limit: Optional[int] = None, admin_enabled: bool = True) -> discord.Embed:
    lines = []
    for r in ALL_REGIONS:
        emoji = REGION_EMOJI.get(r, "")
        dot = "🟢" if r in enabled_regions else "⚫"
        lines.append(f"{dot} {emoji} {r.capitalize()}")

    embed = discord.Embed(
        title="🌏 Region Pings",
        description="\n".join(lines),
        color=EMBED_COLOR
    )
    if not admin_enabled:
        embed.description = _admin_disabled_notice("region") + "\n\n" + embed.description
    embed.set_footer(text=_footer_status(len(enabled_regions), len(ALL_REGIONS), limit, admin_enabled))
    return embed


# ---------------------------------------------------------------------------
# Type ping button view (18 buttons across 4 rows)
# Discord allows max 5 rows × 5 buttons = 25, we have 18 — fits fine.
# ---------------------------------------------------------------------------
class TypePingView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int, enabled_types: list[str], cog,
                 limit: Optional[int] = None, admin_enabled: bool = True):
        super().__init__(timeout=60)  # reduced from 300
        self.user_id = user_id
        self.guild_id = guild_id
        self.enabled_types = list(enabled_types)
        self.cog = cog
        self.limit = limit
        self.admin_enabled = admin_enabled
        self._message: discord.Message | None = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for pokemon_type in ALL_TYPES:
            is_on = pokemon_type in self.enabled_types
            btn = discord.ui.Button(
                label=f"{TYPE_EMOJI.get(pokemon_type, '')} {pokemon_type.capitalize()}",
                style=discord.ButtonStyle.success if is_on else discord.ButtonStyle.secondary,
                custom_id=f"tp_{pokemon_type}",
            )
            btn.callback = self._make_callback(pokemon_type)
            self.add_item(btn)

        # Enable All button — stays disabled whenever a per-user limit is
        # set (a limit and "enable everything" are contradictory) or when
        # server admins have disabled type pings entirely.
        enable_all_disabled = (self.limit is not None) or (not self.admin_enabled)
        enable_all_btn = discord.ui.Button(
            label="✅ Enable All",
            style=discord.ButtonStyle.primary,
            custom_id="tp_enable_all",
            row=4,
            disabled=enable_all_disabled,
        )
        enable_all_btn.callback = self._enable_all_callback
        self.add_item(enable_all_btn)

        # Disable All button
        disable_all_btn = discord.ui.Button(
            label="❌ Disable All",
            style=discord.ButtonStyle.danger,
            custom_id="tp_disable_all",
            row=4,
        )
        disable_all_btn.callback = self._disable_all_callback
        self.add_item(disable_all_btn)

    def _make_callback(self, pokemon_type: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't yours!", ephemeral=True)
                return

            is_currently_on = pokemon_type in self.enabled_types

            # Only gate the transition from OFF -> ON. Turning something
            # off is always allowed regardless of admin toggle or limit.
            if not is_currently_on:
                if not self.admin_enabled:
                    await interaction.response.send_message(_admin_disabled_notice("type"), ephemeral=True)
                    return
                if self.limit is not None and len(self.enabled_types) >= self.limit:
                    await interaction.response.send_message(_limit_reached_notice("type", self.limit), ephemeral=True)
                    return

            now_enabled = await self.cog.db.toggle_user_type_ping(
                self.user_id, self.guild_id, pokemon_type
            )

            if now_enabled:
                if pokemon_type not in self.enabled_types:
                    self.enabled_types.append(pokemon_type)
            else:
                if pokemon_type in self.enabled_types:
                    self.enabled_types.remove(pokemon_type)

            # Invalidate cache so next spawn sees the updated type pings
            if hasattr(self.cog, 'gcache'):
                self.cog.gcache.invalidate_type_pingers(self.guild_id)

            self._build_buttons()
            embed = _type_embed(interaction.user, self.enabled_types, limit=self.limit, admin_enabled=self.admin_enabled)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _enable_all_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't yours!", ephemeral=True)
            return

        if not self.admin_enabled:
            await interaction.response.send_message(_admin_disabled_notice("type"), ephemeral=True)
            return
        if self.limit is not None:
            await interaction.response.send_message(_limit_reached_notice("type", self.limit), ephemeral=True)
            return

        for t in ALL_TYPES:
            if t not in self.enabled_types:
                await self.cog.db.toggle_user_type_ping(self.user_id, self.guild_id, t)
        self.enabled_types = list(ALL_TYPES)

        if hasattr(self.cog, 'gcache'):
            self.cog.gcache.invalidate_type_pingers(self.guild_id)

        self._build_buttons()
        embed = _type_embed(interaction.user, self.enabled_types, limit=self.limit, admin_enabled=self.admin_enabled)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _disable_all_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't yours!", ephemeral=True)
            return

        for t in list(self.enabled_types):
            await self.cog.db.toggle_user_type_ping(self.user_id, self.guild_id, t)
        self.enabled_types = []

        if hasattr(self.cog, 'gcache'):
            self.cog.gcache.invalidate_type_pingers(self.guild_id)

        self._build_buttons()
        embed = _type_embed(interaction.user, self.enabled_types, limit=self.limit, admin_enabled=self.admin_enabled)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable all buttons when the view expires."""
        self.clear_items()
        if self._message:
            try:
                await self._message.edit(view=self)
            except discord.HTTPException:
                pass
        self._message = None
        self.cog = None


# ---------------------------------------------------------------------------
# Region ping button view
# ---------------------------------------------------------------------------
class RegionPingView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int, enabled_regions: list[str], cog,
                 limit: Optional[int] = None, admin_enabled: bool = True):
        super().__init__(timeout=60)  # reduced from 300
        self.user_id = user_id
        self.guild_id = guild_id
        self.enabled_regions = list(enabled_regions)
        self.cog = cog
        self.limit = limit
        self.admin_enabled = admin_enabled
        self._message: discord.Message | None = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for region in ALL_REGIONS:
            is_on = region in self.enabled_regions
            btn = discord.ui.Button(
                label=f"{REGION_EMOJI.get(region, '')} {region.capitalize()}",
                style=discord.ButtonStyle.success if is_on else discord.ButtonStyle.secondary,
                custom_id=f"rp_{region}",
            )
            btn.callback = self._make_callback(region)
            self.add_item(btn)

        # Enable All button — stays disabled whenever a per-user limit is
        # set, or when server admins have disabled region pings entirely.
        enable_all_disabled = (self.limit is not None) or (not self.admin_enabled)
        enable_all_btn = discord.ui.Button(
            label="✅ Enable All",
            style=discord.ButtonStyle.primary,
            custom_id="rp_enable_all",
            row=4,
            disabled=enable_all_disabled,
        )
        enable_all_btn.callback = self._enable_all_callback
        self.add_item(enable_all_btn)

        # Disable All button
        disable_all_btn = discord.ui.Button(
            label="❌ Disable All",
            style=discord.ButtonStyle.danger,
            custom_id="rp_disable_all",
            row=4,
        )
        disable_all_btn.callback = self._disable_all_callback
        self.add_item(disable_all_btn)

    def _make_callback(self, region: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't yours!", ephemeral=True)
                return

            is_currently_on = region in self.enabled_regions

            if not is_currently_on:
                if not self.admin_enabled:
                    await interaction.response.send_message(_admin_disabled_notice("region"), ephemeral=True)
                    return
                if self.limit is not None and len(self.enabled_regions) >= self.limit:
                    await interaction.response.send_message(_limit_reached_notice("region", self.limit), ephemeral=True)
                    return

            now_enabled = await self.cog.db.toggle_user_region_ping(
                self.user_id, self.guild_id, region
            )

            if now_enabled:
                if region not in self.enabled_regions:
                    self.enabled_regions.append(region)
            else:
                if region in self.enabled_regions:
                    self.enabled_regions.remove(region)

            # Invalidate cache so next spawn sees the updated region pings
            if hasattr(self.cog, 'gcache'):
                self.cog.gcache.invalidate_region_pingers(self.guild_id)

            self._build_buttons()
            embed = _region_embed(interaction.user, self.enabled_regions, limit=self.limit, admin_enabled=self.admin_enabled)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _enable_all_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't yours!", ephemeral=True)
            return

        if not self.admin_enabled:
            await interaction.response.send_message(_admin_disabled_notice("region"), ephemeral=True)
            return
        if self.limit is not None:
            await interaction.response.send_message(_limit_reached_notice("region", self.limit), ephemeral=True)
            return

        for r in ALL_REGIONS:
            if r not in self.enabled_regions:
                await self.cog.db.toggle_user_region_ping(self.user_id, self.guild_id, r)
        self.enabled_regions = list(ALL_REGIONS)

        if hasattr(self.cog, 'gcache'):
            self.cog.gcache.invalidate_region_pingers(self.guild_id)

        self._build_buttons()
        embed = _region_embed(interaction.user, self.enabled_regions, limit=self.limit, admin_enabled=self.admin_enabled)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _disable_all_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't yours!", ephemeral=True)
            return

        for r in list(self.enabled_regions):
            await self.cog.db.toggle_user_region_ping(self.user_id, self.guild_id, r)
        self.enabled_regions = []

        if hasattr(self.cog, 'gcache'):
            self.cog.gcache.invalidate_region_pingers(self.guild_id)

        self._build_buttons()
        embed = _region_embed(interaction.user, self.enabled_regions, limit=self.limit, admin_enabled=self.admin_enabled)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable all buttons when the view expires."""
        self.clear_items()
        if self._message:
            try:
                await self._message.edit(view=self)
            except discord.HTTPException:
                pass
        self._message = None
        self.cog = None


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------
class TypeRegionPings(commands.Cog):
    """Type and Region ping management"""

    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @property
    def gcache(self):
        pred_cog = self.bot.get_cog('Prediction')
        return pred_cog.gcache if pred_cog else None

    async def cog_check(self, ctx):
        """Block members holding a command-blacklisted role."""
        if ctx.guild is None:
            return True
        if await is_role_blacklisted(self.db, ctx.author):
            await ctx.reply(
                "🚫 You are blacklisted from using these commands in this server.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # p!tp / p!typepings
    # ------------------------------------------------------------------
    @commands.group(name="tp", aliases=["typepings", "typeping"], invoke_without_command=True)
    async def type_pings_command(self, ctx, *, args: str = None):
        """Manage your type pings for this server.

        With no args: opens the interactive button menu.
        With args: toggles the listed types directly.

        Examples:
            p!tp                          → open menu
            p!tp bug                      → toggle Bug
            p!tp bug grass fire           → toggle Bug, Grass, Fire
        """
        enabled = await self.db.get_user_type_pings(ctx.author.id, ctx.guild.id)
        admin_enabled = await self.db.get_type_pings_enabled(ctx.guild.id)
        limit = await self.db.get_type_ping_limit(ctx.guild.id)

        # Direct toggle via arguments
        if args:
            types_to_toggle = _parse_type_args(args)

            if not types_to_toggle:
                invalid = args.strip()
                await ctx.reply(
                    f"❌ No valid types found in `{invalid}`.\n"
                    f"Valid types: {', '.join(ALL_TYPES)}",
                    mention_author=False
                )
                return

            toggled = []
            blocked = []
            current = list(enabled)
            for t in types_to_toggle:
                is_on = t in current
                if not is_on:
                    if not admin_enabled:
                        blocked.append(t)
                        continue
                    if limit is not None and len(current) >= limit:
                        blocked.append(t)
                        continue

                now_on = await self.db.toggle_user_type_ping(ctx.author.id, ctx.guild.id, t)
                if now_on:
                    current.append(t)
                else:
                    current.remove(t)
                state = "✅" if now_on else "❌"
                toggled.append(f"{state} {TYPE_EMOJI.get(t, '')} {t.capitalize()}")

            if self.gcache:
                self.gcache.invalidate_type_pingers(ctx.guild.id)

            # Refresh enabled list
            enabled = await self.db.get_user_type_pings(ctx.author.id, ctx.guild.id)
            embed = _type_embed(ctx.author, enabled, limit=limit, admin_enabled=admin_enabled)

            reply_lines = []
            if toggled:
                reply_lines.append("Toggled:\n" + "\n".join(toggled))
            if blocked:
                if not admin_enabled:
                    reply_lines.append(_admin_disabled_notice("type"))
                elif limit is not None:
                    reply_lines.append(_limit_reached_notice("type", limit) + f" Skipped: {', '.join(blocked)}")
            await ctx.reply("\n".join(reply_lines) or "No changes made.", embed=embed, mention_author=False)
            return

        # Interactive menu
        view = TypePingView(ctx.author.id, ctx.guild.id, enabled, self, limit=limit, admin_enabled=admin_enabled)
        embed = _type_embed(ctx.author, enabled, limit=limit, admin_enabled=admin_enabled)
        msg = await ctx.reply(embed=embed, view=view, mention_author=False)
        view._message = msg

    # ------------------------------------------------------------------
    # p!rp / p!regionpings
    # ------------------------------------------------------------------
    @commands.group(name="rp", aliases=["regionpings", "regionping"], invoke_without_command=True)
    async def region_pings_command(self, ctx, *, args: str = None):
        """Manage your region pings for this server.

        With no args: opens the interactive button menu.
        With args: toggles the listed regions directly.

        Examples:
            p!rp                          → open menu
            p!rp kanto                    → toggle Kanto
            p!rp kanto johto hoenn        → toggle Kanto, Johto, Hoenn
        """
        enabled = await self.db.get_user_region_pings(ctx.author.id, ctx.guild.id)
        admin_enabled = await self.db.get_region_pings_enabled(ctx.guild.id)
        limit = await self.db.get_region_ping_limit(ctx.guild.id)

        if args:
            regions_to_toggle = _parse_region_args(args)

            if not regions_to_toggle:
                invalid = args.strip()
                await ctx.reply(
                    f"❌ No valid regions found in `{invalid}`.\n"
                    f"Valid regions: {', '.join(ALL_REGIONS)}",
                    mention_author=False
                )
                return

            toggled = []
            blocked = []
            current = list(enabled)
            for r in regions_to_toggle:
                is_on = r in current
                if not is_on:
                    if not admin_enabled:
                        blocked.append(r)
                        continue
                    if limit is not None and len(current) >= limit:
                        blocked.append(r)
                        continue

                now_on = await self.db.toggle_user_region_ping(ctx.author.id, ctx.guild.id, r)
                if now_on:
                    current.append(r)
                else:
                    current.remove(r)
                state = "✅" if now_on else "❌"
                toggled.append(f"{state} {REGION_EMOJI.get(r, '')} {r.capitalize()}")

            # Invalidate cache so next spawn sees the updated region pings
            if self.gcache:
                self.gcache.invalidate_region_pingers(ctx.guild.id)

            enabled = await self.db.get_user_region_pings(ctx.author.id, ctx.guild.id)
            embed = _region_embed(ctx.author, enabled, limit=limit, admin_enabled=admin_enabled)

            reply_lines = []
            if toggled:
                reply_lines.append("Toggled:\n" + "\n".join(toggled))
            if blocked:
                if not admin_enabled:
                    reply_lines.append(_admin_disabled_notice("region"))
                elif limit is not None:
                    reply_lines.append(_limit_reached_notice("region", limit) + f" Skipped: {', '.join(blocked)}")
            await ctx.reply("\n".join(reply_lines) or "No changes made.", embed=embed, mention_author=False)
            return

        # Interactive menu
        view = RegionPingView(ctx.author.id, ctx.guild.id, enabled, self, limit=limit, admin_enabled=admin_enabled)
        embed = _region_embed(ctx.author, enabled, limit=limit, admin_enabled=admin_enabled)
        msg = await ctx.reply(embed=embed, view=view, mention_author=False)
        view._message = msg

    # ------------------------------------------------------------------
    # p!tp limit — view/set/clear the per-user type ping cap (Admin only)
    # ------------------------------------------------------------------
    @type_pings_command.group(name="limit", invoke_without_command=True)
    async def type_ping_limit_group(self, ctx):
        """View, set, or clear how many type pings a single user may enable.

        Subcommands:
            p!tp limit set 5     — cap each user at 5 enabled types (Admin only)
            p!tp limit clear     — remove the cap
            p!tp limit reset     — same as clear

        Run without a subcommand to see the current limit. While a limit
        is set, the "Enable All" button stays disabled.
        """
        if ctx.invoked_subcommand is not None:
            return
        limit = await self.db.get_type_ping_limit(ctx.guild.id)
        if limit is None:
            await ctx.reply("No type ping limit is set for this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            await ctx.reply(f"Type ping limit for this server: **{limit}** type(s) per user.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @type_ping_limit_group.command(name="set")
    @commands.has_permissions(administrator=True)
    async def type_ping_limit_set(self, ctx, limit: int):
        """Set the max number of type pings a user may enable (Admin only)."""
        if limit <= 0:
            await ctx.reply("❌ Limit must be a positive number.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await self.db.set_type_ping_limit(ctx.guild.id, limit)
        await ctx.reply(
            f"✅ Type ping limit set to **{limit}** per user. The Enable All button is now disabled.",
            mention_author=False, allowed_mentions=NO_MENTIONS,
        )

    @type_ping_limit_set.error
    async def type_ping_limit_set_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.reply(f"❌ Usage: `{ctx.prefix}tp limit set <number>`", mention_author=False, allowed_mentions=NO_MENTIONS)

    @type_ping_limit_group.command(name="clear", aliases=["reset"])
    @commands.has_permissions(administrator=True)
    async def type_ping_limit_clear(self, ctx):
        """Remove the type ping limit for this server (Admin only)."""
        await self.db.clear_type_ping_limit(ctx.guild.id)
        await ctx.reply("✅ Type ping limit removed.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @type_ping_limit_clear.error
    async def type_ping_limit_clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)

    # ------------------------------------------------------------------
    # p!rp limit — view/set/clear the per-user region ping cap (Admin only)
    # ------------------------------------------------------------------
    @region_pings_command.group(name="limit", invoke_without_command=True)
    async def region_ping_limit_group(self, ctx):
        """View, set, or clear how many region pings a single user may enable.

        Subcommands:
            p!rp limit set 3     — cap each user at 3 enabled regions (Admin only)
            p!rp limit clear     — remove the cap
            p!rp limit reset     — same as clear

        Run without a subcommand to see the current limit. While a limit
        is set, the "Enable All" button stays disabled.
        """
        if ctx.invoked_subcommand is not None:
            return
        limit = await self.db.get_region_ping_limit(ctx.guild.id)
        if limit is None:
            await ctx.reply("No region ping limit is set for this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            await ctx.reply(f"Region ping limit for this server: **{limit}** region(s) per user.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @region_ping_limit_group.command(name="set")
    @commands.has_permissions(administrator=True)
    async def region_ping_limit_set(self, ctx, limit: int):
        """Set the max number of region pings a user may enable (Admin only)."""
        if limit <= 0:
            await ctx.reply("❌ Limit must be a positive number.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await self.db.set_region_ping_limit(ctx.guild.id, limit)
        await ctx.reply(
            f"✅ Region ping limit set to **{limit}** per user. The Enable All button is now disabled.",
            mention_author=False, allowed_mentions=NO_MENTIONS,
        )

    @region_ping_limit_set.error
    async def region_ping_limit_set_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.reply(f"❌ Usage: `{ctx.prefix}rp limit set <number>`", mention_author=False, allowed_mentions=NO_MENTIONS)

    @region_ping_limit_group.command(name="clear", aliases=["reset"])
    @commands.has_permissions(administrator=True)
    async def region_ping_limit_clear(self, ctx):
        """Remove the region ping limit for this server (Admin only)."""
        await self.db.clear_region_ping_limit(ctx.guild.id)
        await ctx.reply("✅ Region ping limit removed.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @region_ping_limit_clear.error
    async def region_ping_limit_clear_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)

    # ------------------------------------------------------------------
    # Slash Commands  (registered automatically with the cog)
    # ------------------------------------------------------------------
    @app_commands.command(name="tp", description="Open Type Pings menu or toggle types directly")
    @app_commands.check(slash_blacklist_check)
    @app_commands.describe(types="Type(s) to toggle, space or comma separated. Leave blank for interactive menu.")
    async def slash_type_pings(self, interaction: discord.Interaction, types: str = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.type_pings_command(ctx, args=types)

    @app_commands.command(name="rp", description="Open Region Pings menu or toggle regions directly")
    @app_commands.check(slash_blacklist_check)
    @app_commands.describe(regions="Region(s) to toggle, space or comma separated. Leave blank for interactive menu.")
    async def slash_region_pings(self, interaction: discord.Interaction, regions: str = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.region_pings_command(ctx, args=regions)


async def setup(bot):
    await bot.add_cog(TypeRegionPings(bot))
