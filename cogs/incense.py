import discord
from discord.ext import commands
from discord import app_commands
import re
import shlex
import config

POKETWO_ID = 716390085896962058
INCENSE_PATTERN = re.compile(
    r"You purchased an Incense for \d+ shards!",
    re.IGNORECASE
)

# ─────────────────────────────────────────────
#  DB helpers  (use bot.db passed from the cog)
# ─────────────────────────────────────────────

def _guild_key(guild_id: int) -> str:
    return f"incense_guild_{guild_id}"

async def _get_guild_doc(db, guild_id: int) -> dict:
    doc = await db.db.user_data.find_one({"user_id": _guild_key(guild_id)})
    return doc or {}

async def _save_guild_doc(db, guild_id: int, data: dict):
    await db.db.user_data.update_one(
        {"user_id": _guild_key(guild_id)},
        {"$set": data},
        upsert=True
    )
    # Invalidate cached incense settings so next on_message re-fetches
    gcache = getattr(db, 'gcache', None)
    if gcache:
        gcache.invalidate_incense_settings(guild_id)

async def _get_enabled(db, guild_id: int) -> bool:
    doc = await _get_guild_doc(db, guild_id)
    return doc.get("incense_enabled", True)

async def _set_enabled(db, guild_id: int, value: bool):
    await _save_guild_doc(db, guild_id, {"incense_enabled": value})

async def _get_categories(db, guild_id: int) -> list[int]:
    doc = await _get_guild_doc(db, guild_id)
    return doc.get("incense_categories", [])

async def _set_categories(db, guild_id: int, cats: list[int]):
    await _save_guild_doc(db, guild_id, {"incense_categories": cats})

async def _get_paused_channels(db, guild_id: int) -> list[int]:
    doc = await _get_guild_doc(db, guild_id)
    return doc.get("incense_paused_channels", [])

async def _set_paused_channels(db, guild_id: int, channels: list[int]):
    await _save_guild_doc(db, guild_id, {"incense_paused_channels": channels})

async def _get_allowed_roles(db, guild_id: int) -> list[int]:
    doc = await _get_guild_doc(db, guild_id)
    return doc.get("incense_allowed_roles", [])

async def _set_allowed_roles(db, guild_id: int, roles: list[int]):
    await _save_guild_doc(db, guild_id, {"incense_allowed_roles": roles})


# ─────────────────────────────────────────────
#  Permission helpers
# ─────────────────────────────────────────────

async def _get_poketwo(guild: discord.Guild) -> discord.Member | None:
    """Return Poketwo as a Member, fetching if not cached."""
    member = guild.get_member(POKETWO_ID)
    if member is None:
        try:
            member = await guild.fetch_member(POKETWO_ID)
        except (discord.NotFound, discord.HTTPException):
            member = None
    return member

async def _deny_poketwo_in_channel(channel: discord.TextChannel):
    """Deny Poketwo send_messages + view_channel in a single channel."""
    poketwo = await _get_poketwo(channel.guild)
    if poketwo is None:
        return
    overwrite = channel.overwrites_for(poketwo)
    overwrite.send_messages = False
    overwrite.view_channel = False
    await channel.set_permissions(poketwo, overwrite=overwrite)

async def _deny_poketwo_in_category(category: discord.CategoryChannel):
    """
    Deny Poketwo send_messages + view_channel at the category level,
    then sync all channels in that category to inherit.
    Returns (synced_count, already_synced_count).
    """
    poketwo = await _get_poketwo(category.guild)
    if poketwo is None:
        return 0, 0

    overwrite = category.overwrites_for(poketwo)
    overwrite.send_messages = False
    overwrite.view_channel = False
    await category.set_permissions(poketwo, overwrite=overwrite)

    synced = 0
    already_synced = 0
    for ch in category.text_channels:
        if ch.permissions_synced:
            already_synced += 1
        else:
            await ch.edit(sync_permissions=True)
            synced += 1

    return synced, already_synced

async def _restore_poketwo_in_category(category: discord.CategoryChannel):
    """
    Remove Poketwo overwrite from the category (restore to neutral),
    then sync all channels in that category.
    Returns (synced_count, already_synced_count).
    """
    poketwo = await _get_poketwo(category.guild)
    if poketwo is None:
        return 0, 0

    overwrite = category.overwrites_for(poketwo)
    overwrite.send_messages = None
    overwrite.view_channel = None
    if overwrite.is_empty():
        await category.set_permissions(poketwo, overwrite=None)
    else:
        await category.set_permissions(poketwo, overwrite=overwrite)

    synced = 0
    already_synced = 0
    for ch in category.text_channels:
        if ch.permissions_synced:
            already_synced += 1
        else:
            await ch.edit(sync_permissions=True)
            synced += 1

    return synced, already_synced


# ─────────────────────────────────────────────
#  Incense allowed-roles check
# ─────────────────────────────────────────────

async def _member_has_allowed_role(db, member: discord.Member) -> bool:
    """Return True if the member is an admin or has at least one role in the guild's allowed list."""
    # Admins bypass the role requirement entirely
    if member.guild_permissions.manage_guild:
        return True
    allowed = await _get_allowed_roles(db, member.guild.id)
    if not allowed:
        return False
    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & set(allowed))

def incense_control_check():
    """Prefix command check: user must have an allowed incense role."""
    async def predicate(ctx: commands.Context) -> bool:
        if not await _member_has_allowed_role(ctx.bot.db, ctx.author):
            raise commands.CheckFailure("incense_no_role")
        return True
    return commands.check(predicate)

def incense_control_check_slash():
    """Slash command check: user must have an allowed incense role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not await _member_has_allowed_role(interaction.client.db, interaction.user):
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ You don't have a role that's allowed to use incense commands.\nAsk an admin to run `inc allowedroles add <role>`.",
                    color=config.EMBED_COLOR
                ),
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


# ─────────────────────────────────────────────
#  Utility: parse multi-name strings
# ─────────────────────────────────────────────

def _parse_category_names(raw: str) -> list[str]:
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()

def _resolve_category(guild: discord.Guild, name: str):
    name = name.strip()
    if name.isdigit():
        ch = guild.get_channel(int(name))
        if isinstance(ch, discord.CategoryChannel):
            return ch
    return discord.utils.find(
        lambda c: c.name.lower() == name.lower(),
        guild.categories
    )


# ─────────────────────────────────────────────
#  List pagination — one category per page,
#  up to 50 channels shown, no "(cont.)" labels
# ─────────────────────────────────────────────

MAX_CHANNELS_PER_PAGE = 50

def _build_list_pages(
    guild: discord.Guild,
    cats: list[int],
    paused_ids: set[int],
    showing_paused: bool,
) -> tuple[list[discord.Embed], int]:
    """
    One embed per category. Each embed shows up to MAX_CHANNELS_PER_PAGE
    channel mentions in its description. No field splitting, no "(cont.)".
    Returns (pages, total_channel_count).
    """
    icon = "⏸️" if showing_paused else "▶️"
    label = "Paused" if showing_paused else "Active"

    pages: list[discord.Embed] = []
    total = 0

    for cat_id in cats:
        cat_obj = guild.get_channel(cat_id)
        if not isinstance(cat_obj, discord.CategoryChannel):
            continue

        # Collect matching channels
        matching = []
        for ch in cat_obj.text_channels:
            is_paused = ch.id in paused_ids
            if showing_paused and is_paused:
                matching.append(ch.mention)
            elif not showing_paused and not is_paused:
                matching.append(ch.mention)

        if not matching:
            continue

        total += len(matching)

        # Cap display at MAX_CHANNELS_PER_PAGE
        displayed = matching[:MAX_CHANNELS_PER_PAGE]
        hidden = len(matching) - len(displayed)

        lines = [f"{icon} {m}" for m in displayed]
        if hidden:
            lines.append(f"*…and {hidden} more channel{'s' if hidden != 1 else ''}*")

        embed = discord.Embed(
            title=f"{icon} {label} Channels — {cat_obj.name}",
            description="\n".join(lines),
            color=config.EMBED_COLOR,
        )
        embed.set_footer(
            text=f"{len(matching)} {label.lower()} channel{'s' if len(matching) != 1 else ''} in this category"
        )
        pages.append(embed)

    # Add page numbers now that we know the total
    for idx, embed in enumerate(pages):
        existing_footer = embed.footer.text or ""
        embed.set_footer(text=f"Page {idx + 1}/{len(pages)} · {existing_footer}")

    return pages, total


class IncenseListView(discord.ui.View):
    """
    Pagination view for inc list.
    Holds both paused and active page sets.
    Toggle button switches between them; Prev/Next flips pages within the current set.
    Only the invoking user can interact.
    """

    def __init__(
        self,
        paused_pages: list[discord.Embed],
        active_pages: list[discord.Embed],
        paused_total: int,
        active_total: int,
        author_id: int,
    ):
        super().__init__(timeout=60)  # reduced from 120
        self.paused_pages = paused_pages
        self.active_pages = active_pages
        self.paused_total = paused_total
        self.active_total = active_total
        self.author_id = author_id
        self.showing_paused = True
        self.current = 0
        self.message: discord.Message | None = None
        self._inject_summary()
        self._update_buttons()

    def _inject_summary(self):
        """Add the ⏸️ total / ▶️ total summary line to the first embed of each set."""
        summary = (
            f"⏸️ **{self.paused_total}** paused channel{'s' if self.paused_total != 1 else ''}  ·  "
            f"▶️ **{self.active_total}** active channel{'s' if self.active_total != 1 else ''}"
        )
        for page_list in (self.paused_pages, self.active_pages):
            if page_list:
                embed = page_list[0]
                embed.description = f"{summary}\n\n{embed.description or ''}"

    @property
    def current_pages(self) -> list[discord.Embed]:
        return self.paused_pages if self.showing_paused else self.active_pages

    def _update_buttons(self):
        pages = self.current_pages
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(pages) - 1
        # Toggle button label reflects what clicking it will switch TO
        if self.showing_paused:
            self.toggle_btn.label = "Show Active ▶️"
            self.toggle_btn.style = discord.ButtonStyle.success
        else:
            self.toggle_btn.label = "Show Paused ⏸️"
            self.toggle_btn.style = discord.ButtonStyle.danger
        # Disable toggle if the other side has no pages
        other_pages = self.active_pages if self.showing_paused else self.paused_pages
        self.toggle_btn.disabled = len(other_pages) == 0

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can interact with this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.current_pages[self.current], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.current_pages[self.current], view=self)

    @discord.ui.button(label="Show Active ▶️", style=discord.ButtonStyle.success)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        self.showing_paused = not self.showing_paused
        self.current = 0
        self._update_buttons()
        pages = self.current_pages
        if not pages:
            # Shouldn't happen (button is disabled when empty) but guard anyway
            await interaction.response.send_message("No channels to show.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=pages[self.current], view=self)

    async def on_timeout(self):
        self.clear_items()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.message = None


# ─────────────────────────────────────────────
#  The Cog
# ─────────────────────────────────────────────

class Incense(commands.Cog):
    """
    Poketwo incense helper – restricts Poketwo the moment someone
    purchases an Incense in a monitored category channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ── internal helpers ─────────────────────

    async def _channel_in_monitored_category(self, channel: discord.TextChannel) -> bool:
        cats = await _get_categories(self.db, channel.guild.id)
        return channel.category_id in cats

    async def _is_paused(self, channel: discord.TextChannel) -> bool:
        paused = await _get_paused_channels(self.db, channel.guild.id)
        return channel.id in paused

    async def _pause_channel(self, channel: discord.TextChannel):
        """Pause a single channel (used when incense is detected in that channel)."""
        paused = await _get_paused_channels(self.db, channel.guild.id)
        if channel.id not in paused:
            paused.append(channel.id)
            await _set_paused_channels(self.db, channel.guild.id, paused)
        await _deny_poketwo_in_channel(channel)

    async def _resume_channel(self, channel: discord.TextChannel):
        """Resume a single channel by removing Poketwo's overwrite entirely."""
        paused = await _get_paused_channels(self.db, channel.guild.id)
        if channel.id in paused:
            paused.remove(channel.id)
            await _set_paused_channels(self.db, channel.guild.id, paused)
        poketwo = await _get_poketwo(channel.guild)
        if poketwo is not None:
            await channel.set_permissions(poketwo, overwrite=None)

    def _bot_mention(self) -> str:
        return self.bot.user.mention if self.bot.user else "@MiniMeowth"

    async def cog_command_error(self, ctx: commands.Context, error: Exception):
        """Handle check failures from incense_control_check cleanly (one message only)."""
        if isinstance(error, commands.CheckFailure) and str(error) == "incense_no_role":
            embed = discord.Embed(
                description="❌ You don't have a role that's allowed to use incense commands.\nAsk an admin to run `inc allowedroles add <role>`.",
                color=config.EMBED_COLOR
            )
            await ctx.send(embed=embed, reference=ctx.message, mention_author=False)
            return
        # Re-raise anything else so the global error handler still sees it
        raise error

    # ── listener ─────────────────────────────

    def _get_gcache(self):
        """Return GuildCache if available (attached by prediction cog on startup)."""
        return getattr(self.db, 'gcache', None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.id != POKETWO_ID:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        guild_id = message.guild.id
        gcache = self._get_gcache()

        if gcache:
            # Single cached doc — 0 DB queries on cache hit (TTL=30s)
            doc = await gcache.get_incense_settings(guild_id)
        else:
            doc = await _get_guild_doc(self.db, guild_id)

        if not doc.get("incense_enabled", True):
            return

        monitored_cats = doc.get("incense_categories", [])
        if message.channel.category_id not in monitored_cats:
            return

        paused = doc.get("incense_paused_channels", [])
        if message.channel.id in paused:
            return

        content = message.content or ""
        if INCENSE_PATTERN.search(content):
            await self._pause_channel(message.channel)
            # Invalidate cache so next on_message sees the updated paused list
            if gcache:
                gcache.invalidate_incense_settings(guild_id)
            try:
                await message.channel.send(
                    f"Incense purchased! Poketwo has been restricted in this channel. "
                    f"Use `{self._bot_mention()} incense help` to learn about the commands."
                )
            except discord.Forbidden:
                pass

    # ══════════════════════════════════════════
    #  Slash group: /inc
    # ══════════════════════════════════════════

    inc_group = app_commands.Group(name="inc", description="Incense management commands")

    # ── /inc toggle ──────────────────────────

    @inc_group.command(name="toggle", description="Enable or disable the incense watcher for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def inc_toggle(self, interaction: discord.Interaction):
        current = await _get_enabled(self.db, interaction.guild_id)
        new_val = not current
        await _set_enabled(self.db, interaction.guild_id, new_val)
        embed = discord.Embed(
            title="Incense Watcher",
            description=f"The incense watcher is now {'**enabled** ✅' if new_val else '**disabled** 🔴'}.",
            color=config.EMBED_COLOR
        )
        await interaction.response.send_message(embed=embed)

    # ── /inc cat ─────────────────────────────

    cat_group = app_commands.Group(
        name="cat",
        description="Manage monitored categories",
        parent=inc_group
    )

    @cat_group.command(name="add", description="Add a category to monitor (one at a time via slash; use prefix for multiple)")
    @app_commands.describe(category="The category to monitor")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def inc_cat_add(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cats = await _get_categories(self.db, interaction.guild_id)
        if category.id in cats:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"⚠️ **{category.name}** is already being monitored.",
                    color=config.EMBED_COLOR
                ), ephemeral=True
            )
        cats.append(category.id)
        await _set_categories(self.db, interaction.guild_id, cats)
        ch_count = len(category.text_channels)
        embed = discord.Embed(
            description=f"✅ Added category **{category.name}** ({ch_count} channel{'s' if ch_count != 1 else ''})",
            color=config.EMBED_COLOR
        )
        await interaction.response.send_message(embed=embed)

    @cat_group.command(name="remove", description="Stop monitoring a category")
    @app_commands.describe(category="The category to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def inc_cat_remove(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        cats = await _get_categories(self.db, interaction.guild_id)
        if category.id not in cats:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"⚠️ **{category.name}** is not in the monitored list.",
                    color=config.EMBED_COLOR
                ), ephemeral=True
            )
        cats.remove(category.id)
        await _set_categories(self.db, interaction.guild_id, cats)
        embed = discord.Embed(
            description=f"🗑️ Removed **{category.name}** from monitoring.",
            color=config.EMBED_COLOR
        )
        await interaction.response.send_message(embed=embed)

    @cat_group.command(name="list", description="List all monitored categories with channel counts")
    async def inc_cat_list(self, interaction: discord.Interaction):
        cats = await _get_categories(self.db, interaction.guild_id)
        embed = discord.Embed(title="📋 Monitored Categories", color=config.EMBED_COLOR)
        if not cats:
            embed.description = "No categories are being monitored.\nAdd one with `/inc cat add` or `inc cat add <n>`."
        else:
            lines = []
            total_ch = 0
            for cid in cats:
                cat_obj = interaction.guild.get_channel(cid)
                if cat_obj:
                    ch_count = len(cat_obj.text_channels)
                    total_ch += ch_count
                    lines.append(f"• **{cat_obj.name}** — {ch_count} channel{'s' if ch_count != 1 else ''}")
                else:
                    lines.append(f"• *(Unknown — ID {cid})*")
            embed.description = "\n".join(lines)
            embed.set_footer(
                text=f"{len(cats)} categor{'ies' if len(cats) != 1 else 'y'} · {total_ch} total channels"
            )
        await interaction.response.send_message(embed=embed)

    # ── /inc pause ───────────────────────────

    @inc_group.command(
        name="pause",
        description="Pause Poketwo in this channel, or all monitored categories."
    )
    @app_commands.describe(scope="Leave empty to pause this channel, or type 'all' to pause every monitored category.")
    @app_commands.choices(scope=[
        app_commands.Choice(name="all", value="all"),
    ])
    @incense_control_check_slash()
    async def inc_pause(self, interaction: discord.Interaction, scope: str = None):
        await interaction.response.defer()
        cats = await _get_categories(self.db, interaction.guild_id)
        bot_mention = self._bot_mention()

        if scope == "all":
            placeholder = await interaction.followup.send(
                embed=discord.Embed(
                    description="⏳ Pausing Incenses. This may take some seconds.",
                    color=config.EMBED_COLOR
                )
            )

            total_synced = 0
            total_already = 0
            for cat_id in cats:
                cat_obj = interaction.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                synced, already = await _deny_poketwo_in_category(cat_obj)
                total_synced += synced
                total_already += already

            paused = []
            for cat_id in cats:
                cat_obj = interaction.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                for ch in cat_obj.text_channels:
                    paused.append(ch.id)
            await _set_paused_channels(self.db, interaction.guild_id, paused)

            embed = discord.Embed(
                description=(
                    f"⏸️ Paused all monitored categories.\n\n"
                    f"🔄 **Synced:** {total_synced} channel{'s' if total_synced != 1 else ''}\n"
                    f"✅ **Already synced:** {total_already} channel{'s' if total_already != 1 else ''}\n\n"
                    f"Use `{bot_mention} incense resume all` to resume."
                ),
                color=config.EMBED_COLOR
            )
            return await placeholder.edit(embed=embed)

        channel = interaction.channel
        if not await self._channel_in_monitored_category(channel):
            return await interaction.followup.send(
                embed=discord.Embed(
                    description=f"⚠️ {channel.mention} is not inside a monitored category.",
                    color=config.EMBED_COLOR
                ), ephemeral=True
            )
        already = await self._is_paused(channel)
        await self._pause_channel(channel)
        embed = discord.Embed(
            description=(
                f"⏸️ {'Already paused — refreshed permissions in' if already else 'Paused incense in'} {channel.mention}.\n"
                f"Use `{bot_mention} incense resume` to resume."
            ),
            color=config.EMBED_COLOR
        )
        await interaction.followup.send(embed=embed)

    # ── /inc resume ──────────────────────────

    @inc_group.command(
        name="resume",
        description="Resume Poketwo in this channel, or all paused monitored categories."
    )
    @app_commands.describe(scope="Leave empty to resume this channel, or type 'all' to resume every paused channel.")
    @app_commands.choices(scope=[
        app_commands.Choice(name="all", value="all"),
    ])
    @incense_control_check_slash()
    async def inc_resume(self, interaction: discord.Interaction, scope: str = None):
        await interaction.response.defer()
        cats = await _get_categories(self.db, interaction.guild_id)

        if scope == "all":
            placeholder = await interaction.followup.send(
                embed=discord.Embed(
                    description="⏳ Resuming Incenses. This may take some seconds.",
                    color=config.EMBED_COLOR
                )
            )

            total_synced = 0
            total_already = 0
            for cat_id in cats:
                cat_obj = interaction.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                synced, already = await _restore_poketwo_in_category(cat_obj)
                total_synced += synced
                total_already += already

            await _set_paused_channels(self.db, interaction.guild_id, [])

            embed = discord.Embed(
                description=(
                    f"▶️ Resumed all monitored categories.\n\n"
                    f"🔄 **Synced:** {total_synced} channel{'s' if total_synced != 1 else ''}\n"
                    f"✅ **Already synced:** {total_already} channel{'s' if total_already != 1 else ''}"
                ),
                color=config.EMBED_COLOR
            )
            return await placeholder.edit(embed=embed)

        channel = interaction.channel
        if not await self._channel_in_monitored_category(channel):
            return await interaction.followup.send(
                embed=discord.Embed(
                    description=f"⚠️ {channel.mention} is not inside a monitored category.",
                    color=config.EMBED_COLOR
                ), ephemeral=True
            )
        await self._resume_channel(channel)
        embed = discord.Embed(
            description=f"▶️ Resumed {channel.mention} — synced to category permissions.",
            color=config.EMBED_COLOR
        )
        await interaction.followup.send(embed=embed)

    # ── /inc list ────────────────────────────

    @inc_group.command(name="list", description="Show paused and active channels across monitored categories")
    async def inc_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cats = await _get_categories(self.db, interaction.guild_id)
        paused_ids = set(await _get_paused_channels(self.db, interaction.guild_id))

        if not cats:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description="No categories are being monitored. Use `/inc cat add` first.",
                    color=config.EMBED_COLOR
                )
            )

        paused_pages, paused_total = _build_list_pages(interaction.guild, cats, paused_ids, True)
        active_pages, active_total = _build_list_pages(interaction.guild, cats, paused_ids, False)

        if paused_total == 0 and active_total == 0:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description="No channels found in monitored categories.",
                    color=config.EMBED_COLOR
                )
            )

        view = IncenseListView(
            paused_pages=paused_pages,
            active_pages=active_pages,
            paused_total=paused_total,
            active_total=active_total,
            author_id=interaction.user.id,
        )
        if paused_total == 0:
            view.showing_paused = False
            view._update_buttons()

        await interaction.followup.send(embed=view.current_pages[0], view=view)

    # ── /inc help ────────────────────────────

    @inc_group.command(name="help", description="Show all incense commands and how to use them")
    async def inc_help(self, interaction: discord.Interaction):
        p = config.BOT_PREFIX[0]
        bot_mention = self._bot_mention()
        embed = discord.Embed(
            title="🔥 Incense Help",
            description=(
                "Automatically restricts Poketwo the moment someone buys an Incense "
                "in a monitored category — so your spawns stay exclusive."
            ),
            color=config.EMBED_COLOR
        )
        embed.add_field(
            name="⚙️ Setup  *(Manage Server)*",
            value=(
                f"`/inc toggle` — Enable / disable the watcher\n"
                f"`/inc cat add <category>` — Monitor a category\n"
                f"`{p}inc cat add SPAWN1 SPAWN2` — Add multiple at once\n"
                f"`{p}inc cat add \"Incense 1\" \"Incense 2\"` — Names with spaces\n"
                f"`/inc cat remove <category>` — Stop monitoring\n"
                f"`/inc cat list` — View all categories & channel counts"
            ),
            inline=False
        )
        embed.add_field(
            name="⏸️ Pause  *(Allowed Role required)*",
            value=(
                f"`/inc pause` — Pause **this** channel\n"
                f"`/inc pause all` — Pause ALL channels in monitored categories\n"
                f"`{p}inc pause` · `{p}inc p` · `{p}incense pause`\n"
                f"`{p}inc pause all` · `{p}inc p all`"
            ),
            inline=False
        )
        embed.add_field(
            name="▶️ Resume  *(Allowed Role required)*",
            value=(
                f"`/inc resume` — Resume **this** channel\n"
                f"`/inc resume all` — Resume ALL paused channels\n"
                f"`{p}inc resume` · `{p}inc r` · `{p}incense resume`\n"
                f"`{p}inc resume all` · `{p}inc r all`\n"
                f"*(also: `{bot_mention} incense resume all`)*"
            ),
            inline=False
        )
        embed.add_field(
            name="📋 Status",
            value=(
                f"`/inc list` — View paused and active channels across monitored categories\n"
                f"`{p}inc list` — same"
            ),
            inline=False
        )
        embed.add_field(
            name="🔐 Allowed Roles  *(Manage Server)*",
            value=(
                f"`{p}inc allowedroles` / `{p}inc ar` — List roles allowed to pause/resume\n"
                f"`{p}inc allowedroles add @Role` — Add a role (also accepts role ID)\n"
                f"`{p}inc allowedroles remove @Role` — Remove a role\n"
                f"`{p}inc allowedroles clear` — Remove all allowed roles"
            ),
            inline=False
        )
        embed.add_field(
            name="🤖 How it works",
            value=(
                "Poketwo sends `You purchased an Incense for X shards!`\n"
                "→ Bot restricts Poketwo in **that specific channel** only.\n"
                f"→ Use `{bot_mention} incense resume` when your session is over.\n"
                "→ `pause all` / `resume all` operates at the **category level** for speed."
            ),
            inline=False
        )
        embed.set_footer(text="Allowed Role required for pause/resume · Manage Server for setup/allowedroles")
        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════
    #  Prefix commands  (p!inc / p!incense)
    # ══════════════════════════════════════════

    @commands.group(name="inc", aliases=["incense"], invoke_without_command=True, case_insensitive=True)
    async def inc_prefix(self, ctx: commands.Context):
        """Incense management. Use `inc help` for details."""
        await ctx.invoke(self.inc_prefix_help)

    # ── toggle ───────────────────────────────

    @inc_prefix.command(name="toggle")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_toggle(self, ctx: commands.Context):
        current = await _get_enabled(self.db, ctx.guild.id)
        new_val = not current
        await _set_enabled(self.db, ctx.guild.id, new_val)
        embed = discord.Embed(
            title="Incense Watcher",
            description=f"The incense watcher is now {'**enabled** ✅' if new_val else '**disabled** 🔴'}.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    # ── cat ──────────────────────────────────

    @inc_prefix.group(name="cat", invoke_without_command=True, case_insensitive=True)
    async def inc_prefix_cat(self, ctx: commands.Context):
        p = config.BOT_PREFIX[0]
        embed = discord.Embed(
            description=(
                f"**Usage:**\n"
                f"`{p}inc cat add SPAWN1 SPAWN2`\n"
                f"`{p}inc cat add \"Incense 1\" \"Incense 2\"`\n"
                f"`{p}inc cat remove <n>`\n"
                f"`{p}inc cat list`"
            ),
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_cat.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_cat_add(self, ctx: commands.Context, *, raw: str):
        """
        Add one or more categories to monitor.
        Usage:  inc cat add SPAWN1 SPAWN2
                inc cat add "Incense 1" "Incense 2"
        """
        names = _parse_category_names(raw)
        cats = await _get_categories(self.db, ctx.guild.id)

        added_lines = []
        skipped_lines = []

        for name in names:
            cat = _resolve_category(ctx.guild, name)
            if not cat:
                skipped_lines.append(f"❌ `{name}` — not found")
                continue
            if cat.id in cats:
                skipped_lines.append(f"⚠️ **{cat.name}** — already monitored")
                continue
            cats.append(cat.id)
            ch_count = len(cat.text_channels)
            added_lines.append(
                f"✅ **{cat.name}** ({ch_count} channel{'s' if ch_count != 1 else ''})"
            )

        await _set_categories(self.db, ctx.guild.id, cats)

        parts = []
        if added_lines:
            parts.append("**Added:**\n" + "\n".join(added_lines))
        if skipped_lines:
            parts.append("**Skipped:**\n" + "\n".join(skipped_lines))

        embed = discord.Embed(
            description="\n\n".join(parts) if parts else "Nothing to add.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_cat.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_cat_remove(self, ctx: commands.Context, *, raw: str):
        """
        Remove one or more categories from monitoring.
        Usage:  inc cat remove SPAWN1
                inc cat remove "Incense 1" "Incense 2"
        """
        names = _parse_category_names(raw)
        cats = await _get_categories(self.db, ctx.guild.id)

        removed_lines = []
        skipped_lines = []

        for name in names:
            cat = _resolve_category(ctx.guild, name)
            if not cat:
                skipped_lines.append(f"❌ `{name}` — not found")
                continue
            if cat.id not in cats:
                skipped_lines.append(f"⚠️ **{cat.name}** — not being monitored")
                continue
            cats.remove(cat.id)
            removed_lines.append(f"🗑️ **{cat.name}**")

        await _set_categories(self.db, ctx.guild.id, cats)

        parts = []
        if removed_lines:
            parts.append("**Removed:**\n" + "\n".join(removed_lines))
        if skipped_lines:
            parts.append("**Skipped:**\n" + "\n".join(skipped_lines))

        embed = discord.Embed(
            description="\n\n".join(parts) if parts else "Nothing to remove.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_cat.command(name="list")
    async def inc_prefix_cat_list(self, ctx: commands.Context):
        cats = await _get_categories(self.db, ctx.guild.id)
        embed = discord.Embed(title="📋 Monitored Categories", color=config.EMBED_COLOR)
        if not cats:
            p = config.BOT_PREFIX[0]
            embed.description = f"No categories monitored. Add some with `{p}inc cat add <n>`."
        else:
            lines = []
            total_ch = 0
            for cid in cats:
                cat_obj = ctx.guild.get_channel(cid)
                if cat_obj:
                    ch_count = len(cat_obj.text_channels)
                    total_ch += ch_count
                    lines.append(f"• **{cat_obj.name}** — {ch_count} channel{'s' if ch_count != 1 else ''}")
                else:
                    lines.append(f"• *(Unknown — ID {cid})*")
            embed.description = "\n".join(lines)
            embed.set_footer(
                text=f"{len(cats)} categor{'ies' if len(cats) != 1 else 'y'} · {total_ch} total channels"
            )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    # ── allowedroles ─────────────────────────

    @inc_prefix.group(name="allowedroles", aliases=["ar"], invoke_without_command=True, case_insensitive=True)
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_allowedroles(self, ctx: commands.Context):
        """List all roles allowed to use pause/resume. Subcommands: add, remove, clear."""
        allowed = await _get_allowed_roles(self.db, ctx.guild.id)
        embed = discord.Embed(title="🔐 Incense Allowed Roles", color=config.EMBED_COLOR)
        if not allowed:
            p = config.BOT_PREFIX[0]
            embed.description = f"No roles set. Add one with `{p}inc allowedroles add <role>`."
        else:
            lines = []
            for rid in allowed:
                role = ctx.guild.get_role(rid)
                lines.append(f"• {role.mention} (`{rid}`)" if role else f"• *(Unknown — ID {rid})*")
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(allowed)} role{'s' if len(allowed) != 1 else ''} allowed")
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_allowedroles.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_allowedroles_add(self, ctx: commands.Context, *, raw: str):
        """
        Add one or more roles (by mention or ID) to the allowed list.
        Usage:  inc allowedroles add @Role1 @Role2
                inc allowedroles add 123456789
        """
        # Collect role IDs from mentions and raw IDs
        allowed = await _get_allowed_roles(self.db, ctx.guild.id)
        added, skipped = [], []

        candidates = [r.id for r in ctx.message.role_mentions]
        if not candidates:
            for token in raw.split():
                token = token.strip("<@&>")
                if token.isdigit():
                    candidates.append(int(token))

        if not candidates:
            embed = discord.Embed(
                description="❌ No valid roles found. Mention a role or provide a role ID.",
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        for rid in candidates:
            role = ctx.guild.get_role(rid)
            if not role:
                skipped.append(f"❌ `{rid}` — role not found")
            elif rid in allowed:
                skipped.append(f"⚠️ {role.mention} — already allowed")
            else:
                allowed.append(rid)
                added.append(f"✅ {role.mention}")

        await _set_allowed_roles(self.db, ctx.guild.id, allowed)

        parts = []
        if added:
            parts.append("**Added:**\n" + "\n".join(added))
        if skipped:
            parts.append("**Skipped:**\n" + "\n".join(skipped))
        embed = discord.Embed(
            description="\n\n".join(parts) if parts else "Nothing changed.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_allowedroles.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_allowedroles_remove(self, ctx: commands.Context, *, raw: str):
        """
        Remove one or more roles from the allowed list.
        Usage:  inc allowedroles remove @Role
                inc allowedroles remove 123456789
        """
        allowed = await _get_allowed_roles(self.db, ctx.guild.id)
        removed, skipped = [], []

        candidates = [r.id for r in ctx.message.role_mentions]
        if not candidates:
            for token in raw.split():
                token = token.strip("<@&>")
                if token.isdigit():
                    candidates.append(int(token))

        if not candidates:
            embed = discord.Embed(
                description="❌ No valid roles found. Mention a role or provide a role ID.",
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        for rid in candidates:
            role = ctx.guild.get_role(rid)
            name = role.mention if role else f"`{rid}`"
            if rid not in allowed:
                skipped.append(f"⚠️ {name} — not in allowed list")
            else:
                allowed.remove(rid)
                removed.append(f"🗑️ {name}")

        await _set_allowed_roles(self.db, ctx.guild.id, allowed)

        parts = []
        if removed:
            parts.append("**Removed:**\n" + "\n".join(removed))
        if skipped:
            parts.append("**Skipped:**\n" + "\n".join(skipped))
        embed = discord.Embed(
            description="\n\n".join(parts) if parts else "Nothing changed.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    @inc_prefix_allowedroles.command(name="clear")
    @commands.has_permissions(manage_guild=True)
    async def inc_prefix_allowedroles_clear(self, ctx: commands.Context):
        """Remove all roles from the allowed list."""
        allowed = await _get_allowed_roles(self.db, ctx.guild.id)
        count = len(allowed)
        await _set_allowed_roles(self.db, ctx.guild.id, [])
        embed = discord.Embed(
            description=f"🗑️ Cleared all **{count}** allowed role{'s' if count != 1 else ''}. Nobody can use pause/resume until new roles are added.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    # ── pause  (alias: p) ────────────────────

    @inc_prefix.command(name="pause", aliases=["p"])
    @incense_control_check()
    async def inc_prefix_pause(self, ctx: commands.Context, target: str = None):
        """
        Pause incense for this channel, or all monitored categories.
        Usage:  inc pause          ← pauses the current channel
                inc pause all      ← pauses ALL monitored categories
                inc p              ← shorthand
        """
        cats = await _get_categories(self.db, ctx.guild.id)
        bot_mention = self._bot_mention()
        p = config.BOT_PREFIX[0]

        if target and target.lower() == "all":
            placeholder = await ctx.send(
                embed=discord.Embed(
                    description="⏳ Pausing Incenses. This may take some seconds.",
                    color=config.EMBED_COLOR
                ),
                reference=ctx.message,
                mention_author=False
            )

            total_synced = 0
            total_already = 0
            for cat_id in cats:
                cat_obj = ctx.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                synced, already = await _deny_poketwo_in_category(cat_obj)
                total_synced += synced
                total_already += already

            paused = []
            for cat_id in cats:
                cat_obj = ctx.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                for ch in cat_obj.text_channels:
                    paused.append(ch.id)
            await _set_paused_channels(self.db, ctx.guild.id, paused)

            embed = discord.Embed(
                description=(
                    f"⏸️ Paused all monitored categories.\n\n"
                    f"🔄 **Synced:** {total_synced} channel{'s' if total_synced != 1 else ''}\n"
                    f"✅ **Already synced:** {total_already} channel{'s' if total_already != 1 else ''}\n\n"
                    f"Use `{bot_mention} incense resume all` to resume."
                ),
                color=config.EMBED_COLOR
            )
            return await placeholder.edit(embed=embed)

        channel = ctx.channel

        if not await self._channel_in_monitored_category(channel):
            embed = discord.Embed(
                description=(
                    f"⚠️ {channel.mention} is not inside a monitored category.\n"
                    f"Use `{p}inc cat add <category>` to add its category first."
                ),
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        already = await self._is_paused(channel)
        await self._pause_channel(channel)
        embed = discord.Embed(
            description=(
                f"⏸️ {'Already paused — refreshed permissions in' if already else 'Paused incense in'} {channel.mention}.\n"
                f"Use `{bot_mention} incense resume` to resume."
            ),
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    # ── resume  (alias: r) ───────────────────

    @inc_prefix.command(name="resume", aliases=["r"])
    @incense_control_check()
    async def inc_prefix_resume(self, ctx: commands.Context, target: str = None):
        """
        Resume incense for this channel, or all channels.
        Usage:  inc resume          ← resumes the current channel
                inc resume all      ← resumes ALL monitored categories
                inc r               ← shorthand
        """
        cats = await _get_categories(self.db, ctx.guild.id)
        p = config.BOT_PREFIX[0]

        if target and target.lower() == "all":
            placeholder = await ctx.send(
                embed=discord.Embed(
                    description="⏳ Resuming Incenses. This may take some seconds.",
                    color=config.EMBED_COLOR
                ),
                reference=ctx.message,
                mention_author=False
            )

            total_synced = 0
            total_already = 0
            for cat_id in cats:
                cat_obj = ctx.guild.get_channel(cat_id)
                if not isinstance(cat_obj, discord.CategoryChannel):
                    continue
                synced, already = await _restore_poketwo_in_category(cat_obj)
                total_synced += synced
                total_already += already

            await _set_paused_channels(self.db, ctx.guild.id, [])

            embed = discord.Embed(
                description=(
                    f"▶️ Resumed all monitored categories.\n\n"
                    f"🔄 **Synced:** {total_synced} channel{'s' if total_synced != 1 else ''}\n"
                    f"✅ **Already synced:** {total_already} channel{'s' if total_already != 1 else ''}"
                ),
                color=config.EMBED_COLOR
            )
            return await placeholder.edit(embed=embed)

        channel = ctx.channel

        if not await self._channel_in_monitored_category(channel):
            embed = discord.Embed(
                description=(
                    f"⚠️ {channel.mention} is not inside a monitored category.\n"
                    f"Use `{p}inc cat add <category>` to add its category first."
                ),
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        await self._resume_channel(channel)
        embed = discord.Embed(
            description=f"▶️ Resumed {channel.mention} — synced to category permissions.",
            color=config.EMBED_COLOR
        )
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

    # ── list ─────────────────────────────────

    @inc_prefix.command(name="list")
    async def inc_prefix_list(self, ctx: commands.Context):
        """Show paused and active channels across monitored categories."""
        cats = await _get_categories(self.db, ctx.guild.id)
        paused_ids = set(await _get_paused_channels(self.db, ctx.guild.id))

        if not cats:
            embed = discord.Embed(
                description="No categories are being monitored.",
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        paused_pages, paused_total = _build_list_pages(ctx.guild, cats, paused_ids, True)
        active_pages, active_total = _build_list_pages(ctx.guild, cats, paused_ids, False)

        if paused_total == 0 and active_total == 0:
            embed = discord.Embed(
                description="No channels found in monitored categories.",
                color=config.EMBED_COLOR
            )
            return await ctx.send(embed=embed, reference=ctx.message, mention_author=False)

        view = IncenseListView(
            paused_pages=paused_pages,
            active_pages=active_pages,
            paused_total=paused_total,
            active_total=active_total,
            author_id=ctx.author.id,
        )
        if paused_total == 0:
            view.showing_paused = False
            view._update_buttons()

        msg = await ctx.send(embed=view.current_pages[0], view=view, reference=ctx.message, mention_author=False)
        view.message = msg

    # ── help ─────────────────────────────────

    @inc_prefix.command(name="help")
    async def inc_prefix_help(self, ctx: commands.Context):
        p = config.BOT_PREFIX[0]
        bot_mention = self._bot_mention()
        embed = discord.Embed(
            title="🔥 Incense Help",
            description=(
                "Automatically restricts Poketwo the moment an Incense is purchased "
                "in a monitored category channel — so your spawns stay exclusive."
            ),
            color=config.EMBED_COLOR
        )
        embed.add_field(
            name="⚙️ Setup  *(Manage Server)*",
            value=(
                f"`{p}inc toggle` — Enable/disable the watcher\n"
                f"`{p}inc cat add SPAWN1 SPAWN2` — Add multiple categories at once\n"
                f"`{p}inc cat add \"Incense 1\" \"Incense 2\"` — Names with spaces\n"
                f"`{p}inc cat remove <n>` — Stop monitoring a category\n"
                f"`{p}inc cat list` — View all categories & channel counts"
            ),
            inline=False
        )
        embed.add_field(
            name="⏸️ Pause  *(Allowed Role required)*",
            value=(
                f"`{p}inc pause` / `{p}inc p` — Pause **this** channel\n"
                f"`{p}inc pause all` / `{p}inc p all` — Pause ALL monitored categories\n"
                f"`{p}incense pause` also works"
            ),
            inline=False
        )
        embed.add_field(
            name="▶️ Resume  *(Allowed Role required)*",
            value=(
                f"`{p}inc resume` / `{p}inc r` — Resume **this** channel\n"
                f"`{p}inc resume all` / `{p}inc r all` — Resume ALL paused channels\n"
                f"`{p}incense resume` also works\n"
                f"*(also: `{bot_mention} incense resume all`)*"
            ),
            inline=False
        )
        embed.add_field(
            name="📋 Status",
            value=f"`{p}inc list` — View paused and active channels across monitored categories",
            inline=False
        )
        embed.add_field(
            name="🔐 Allowed Roles  *(Manage Server)*",
            value=(
                f"`{p}inc allowedroles` / `{p}inc ar` — List roles allowed to pause/resume\n"
                f"`{p}inc allowedroles add @Role` — Add a role (also accepts role ID)\n"
                f"`{p}inc allowedroles remove @Role` — Remove a role\n"
                f"`{p}inc allowedroles clear` — Remove all allowed roles"
            ),
            inline=False
        )
        embed.add_field(
            name="🤖 Trigger",
            value=(
                "Poketwo sends `You purchased an Incense for X shards!`\n"
                "→ Bot restricts Poketwo in **that specific channel** only.\n"
                "→ `pause all` / `resume all` operates at the **category level** for speed.\n"
                f"→ Use `{bot_mention} incense resume` to resume for current channel."
            ),
            inline=False
        )
        embed.set_footer(text="Allowed Role required for pause/resume · Manage Server for setup/allowedroles · Slash: /inc <subcommand>")
        await ctx.send(embed=embed, reference=ctx.message, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Incense(bot))
