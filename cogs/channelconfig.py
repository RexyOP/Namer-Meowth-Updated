"""Channel configuration cog — centralises every 'set a channel for X' admin command.

All commands live under the p!channel group:

  Starboard channels (Admin only)
  ─────────────────────────────────
  p!channel starboard all [#ch | none]
  p!channel starboard catch [#ch | none]
  p!channel starboard egg [#ch | none]
  p!channel starboard unbox [#ch | none]
  p!channel starboard shiny [#ch | none]
  p!channel starboard gigantamax [#ch | none]
  p!channel starboard highiv [#ch | none]
  p!channel starboard lowiv [#ch | none]
  p!channel starboard missingno [#ch | none]
  p!channel starboard milestone [#ch | none]
  p!channel starboard settings

  Feature channels (Admin only)
  ─────────────────────────────────
  p!channel captcha [#ch]              — captcha alert channel
  p!channel autopred [#ch]             — auto-prediction output channel  (alias: p!channel auto-prediction)

  Global / owner-only channels
  ─────────────────────────────────
  p!channel lowpred [#ch]              — global low-confidence prediction log
  p!channel secondary [#ch]            — global secondary-model log

  View all
  ─────────────────────────────────
  p!channel settings                   — overview of every configured channel
"""
import discord
from discord import app_commands
from discord.ext import commands
from config import EMBED_COLOR


# ─────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────

async def _resolve_channel(ctx, raw: str | None) -> discord.TextChannel | None | str:
    """
    Returns:
      None        — caller passed no argument (show usage)
      "clear"     — caller passed 'none' (clear the channel)
      TextChannel — successfully resolved channel
    Raises BadArgument on invalid input.
    """
    if raw is None:
        return None
    if raw.lower() == "none":
        return "clear"
    converter = commands.TextChannelConverter()
    return await converter.convert(ctx, raw)


# ─────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────

class ChannelConfig(commands.Cog):
    """Centralised channel-configuration commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ══════════════════════════════════════════════════════════════════
    # Root group:  p!channel
    # ══════════════════════════════════════════════════════════════════

    @commands.group(name="channel", aliases=["ch"], invoke_without_command=True)
    async def channel_group(self, ctx):
        """Channel configuration — use a subcommand to set or view channels."""
        p = ctx.prefix
        embed = discord.Embed(
            title="📺 Channel Configuration",
            description=(
                f"Use `{p}channel settings` to view all configured channels.\n\n"
                "**Subcommands**"
            ),
            color=EMBED_COLOR,
        )
        embed.add_field(
            name="⭐ Starboard  *(Admin)*",
            value=(
                f"`{p}channel starboard settings` — view starboard channels\n"
                f"`{p}channel starboard all [#ch | none]` — set all at once\n"
                f"`{p}channel starboard catch/egg/unbox [#ch | none]`\n"
                f"`{p}channel starboard shiny/gigantamax/highiv/lowiv [#ch | none]`\n"
                f"`{p}channel starboard missingno/milestone [#ch | none]`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔐 Captcha  *(Admin)*",
            value=(
                f"`{p}channel captcha [#ch]` — set alert channel; omit to clear/disable"
            ),
            inline=False,
        )
        embed.add_field(
            name="👑 Owner-Only",
            value=(
                f"`{p}channel lowpred #ch` — global low-confidence prediction log\n"
                f"`{p}channel secondary #ch` — global secondary-model log"
            ),
            inline=False,
        )
        embed.add_field(
            name="📋 Overview",
            value=f"`{p}channel settings` — all configured channels at a glance",
            inline=False,
        )
        await ctx.reply(embed=embed, mention_author=False)

    @channel_group.error
    async def channel_group_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # Starboard sub-group:  p!channel starboard
    # ══════════════════════════════════════════════════════════════════

    @channel_group.group(name="starboard", aliases=["sb"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def starboard_group(self, ctx):
        """Starboard channel configuration — use a subcommand."""
        await ctx.invoke(self.starboard_settings_cmd)

    # ── p!channel starboard settings ──────────────────────────────────

    @starboard_group.command(name="settings", aliases=["config", "view"])
    async def starboard_settings_cmd(self, ctx):
        """View current starboard channel settings for this server."""
        settings = await self.db.get_guild_settings(ctx.guild.id)

        embed = discord.Embed(
            title=f"⭐ Starboard Channels — {ctx.guild.name}",
            color=EMBED_COLOR,
        )

        def _field(label, key):
            ch_id = settings.get(key)
            embed.add_field(
                name=label,
                value=f"<#{ch_id}>" if ch_id else "Not set",
                inline=True,
            )

        _field("Catch",      "starboard_catch_channel_id")
        _field("Shiny",      "starboard_shiny_channel_id")
        _field("Gigantamax", "starboard_gigantamax_channel_id")
        _field("High IV",    "starboard_highiv_channel_id")
        _field("Low IV",     "starboard_lowiv_channel_id")
        _field("MissingNo",  "starboard_missingno_channel_id")
        _field("Milestone",  "starboard_milestone_channel_id")
        _field("Egg",        "starboard_egg_channel_id")
        _field("Unbox",      "starboard_unbox_channel_id")

        embed.set_footer(text=f"Guild ID: {ctx.guild.id}")
        await ctx.reply(embed=embed, mention_author=False)

    # ── p!channel starboard all ────────────────────────────────────────

    @starboard_group.command(name="all")
    @commands.has_permissions(administrator=True)
    async def starboard_all_cmd(self, ctx, channel: str = None):
        """Set one channel for ALL starboard categories, or 'none' to clear all.

        Examples:
            p!channel starboard all #starboard
            p!channel starboard all none
        """
        result = await _resolve_channel(ctx, channel)
        if result is None:
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}channel starboard all #channel` or `none` to clear all.",
                mention_author=False,
            )
            return

        _all_setters = [
            self.db.set_starboard_catch_channel,
            self.db.set_starboard_egg_channel,
            self.db.set_starboard_unbox_channel,
            self.db.set_starboard_shiny_channel,
            self.db.set_starboard_gigantamax_channel,
            self.db.set_starboard_highiv_channel,
            self.db.set_starboard_lowiv_channel,
            self.db.set_starboard_missingno_channel,
            self.db.set_starboard_milestone_channel,
        ]

        if result == "clear":
            for setter in _all_setters:
                await setter(ctx.guild.id, None)
            await ctx.reply("✅ All starboard channels have been cleared.", mention_author=False)
        else:
            for setter in _all_setters:
                await setter(ctx.guild.id, result.id)
            await ctx.reply(f"✅ All starboard channels set to {result.mention}", mention_author=False)

    # ── Generic starboard channel setter (DRY helper) ──────────────────

    async def _set_starboard(self, ctx, label: str, setter, channel: str):
        result = await _resolve_channel(ctx, channel)
        if result is None:
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}channel starboard {label} #channel` or `none` to clear.",
                mention_author=False,
            )
            return
        if result == "clear":
            await setter(ctx.guild.id, None)
            await ctx.reply(f"✅ {label.title()} starboard channel cleared.", mention_author=False)
        else:
            await setter(ctx.guild.id, result.id)
            await ctx.reply(f"✅ {label.title()} starboard channel set to {result.mention}", mention_author=False)

    # ── Individual starboard subcommands ──────────────────────────────

    @starboard_group.command(name="catch")
    @commands.has_permissions(administrator=True)
    async def starboard_catch_cmd(self, ctx, channel: str = None):
        """Set the catch starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "catch", self.db.set_starboard_catch_channel, channel)

    @starboard_group.command(name="egg")
    @commands.has_permissions(administrator=True)
    async def starboard_egg_cmd(self, ctx, channel: str = None):
        """Set the egg hatch starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "egg", self.db.set_starboard_egg_channel, channel)

    @starboard_group.command(name="unbox")
    @commands.has_permissions(administrator=True)
    async def starboard_unbox_cmd(self, ctx, channel: str = None):
        """Set the unbox starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "unbox", self.db.set_starboard_unbox_channel, channel)

    @starboard_group.command(name="shiny")
    @commands.has_permissions(administrator=True)
    async def starboard_shiny_cmd(self, ctx, channel: str = None):
        """Set the shiny starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "shiny", self.db.set_starboard_shiny_channel, channel)

    @starboard_group.command(name="gigantamax", aliases=["gmax"])
    @commands.has_permissions(administrator=True)
    async def starboard_gigantamax_cmd(self, ctx, channel: str = None):
        """Set the Gigantamax starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "gigantamax", self.db.set_starboard_gigantamax_channel, channel)

    @starboard_group.command(name="highiv", aliases=["high-iv", "hiv"])
    @commands.has_permissions(administrator=True)
    async def starboard_highiv_cmd(self, ctx, channel: str = None):
        """Set the high-IV (≥90%) starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "highiv", self.db.set_starboard_highiv_channel, channel)

    @starboard_group.command(name="lowiv", aliases=["low-iv", "liv"])
    @commands.has_permissions(administrator=True)
    async def starboard_lowiv_cmd(self, ctx, channel: str = None):
        """Set the low-IV (≤10%) starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "lowiv", self.db.set_starboard_lowiv_channel, channel)

    @starboard_group.command(name="missingno", aliases=["mno"])
    @commands.has_permissions(administrator=True)
    async def starboard_missingno_cmd(self, ctx, channel: str = None):
        """Set the MissingNo starboard channel. Use 'none' to remove."""
        await self._set_starboard(ctx, "missingno", self.db.set_starboard_missingno_channel, channel)

    @starboard_group.command(name="milestone", aliases=["ms"])
    @commands.has_permissions(administrator=True)
    async def starboard_milestone_cmd(self, ctx, channel: str = None):
        """Set the milestone starboard channel (100 / 1K / 10K / 100K catches). Use 'none' to remove."""
        await self._set_starboard(ctx, "milestone", self.db.set_starboard_milestone_channel, channel)

    # Shared error handler for all starboard subcommands
    @starboard_group.error
    @starboard_all_cmd.error
    @starboard_catch_cmd.error
    @starboard_egg_cmd.error
    @starboard_unbox_cmd.error
    @starboard_shiny_cmd.error
    @starboard_gigantamax_cmd.error
    @starboard_highiv_cmd.error
    @starboard_lowiv_cmd.error
    @starboard_missingno_cmd.error
    @starboard_milestone_cmd.error
    async def starboard_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel. Mention a text channel, use its ID, or type `none`.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # Global starboard channels (bot owner only)
    # ══════════════════════════════════════════════════════════════════

    @channel_group.group(name="global-starboard", aliases=["gsb"], invoke_without_command=True)
    @commands.is_owner()
    async def global_starboard_group(self, ctx):
        """Global starboard channel configuration (bot owner only)."""
        p = ctx.prefix
        await ctx.reply(
            f"**Global Starboard Subcommands** (bot owner only)\n"
            f"`{p}channel global-starboard catch #channel`\n"
            f"`{p}channel global-starboard egg #channel`\n"
            f"`{p}channel global-starboard unbox #channel`",
            mention_author=False,
        )

    @global_starboard_group.command(name="catch")
    @commands.is_owner()
    async def global_starboard_catch_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set the global catch starboard channel (bot owner only)."""
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        await self.db.set_global_starboard_catch_channel(channel.id)
        await ctx.reply(f"✅ Global catch starboard channel set to {channel.mention}", mention_author=False)

    @global_starboard_group.command(name="egg")
    @commands.is_owner()
    async def global_starboard_egg_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set the global egg starboard channel (bot owner only)."""
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        await self.db.set_global_starboard_egg_channel(channel.id)
        await ctx.reply(f"✅ Global egg starboard channel set to {channel.mention}", mention_author=False)

    @global_starboard_group.command(name="unbox")
    @commands.is_owner()
    async def global_starboard_unbox_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set the global unbox starboard channel (bot owner only)."""
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        await self.db.set_global_starboard_unbox_channel(channel.id)
        await ctx.reply(f"✅ Global unbox starboard channel set to {channel.mention}", mention_author=False)

    @global_starboard_group.error
    @global_starboard_catch_cmd.error
    @global_starboard_egg_cmd.error
    @global_starboard_unbox_cmd.error
    async def global_starboard_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("❌ Only the bot owner can use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # p!channel captcha [#channel]   (Admin only)
    # ══════════════════════════════════════════════════════════════════

    @channel_group.command(name="captcha", aliases=["cap"])
    @commands.has_permissions(administrator=True)
    async def captcha_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set or clear the captcha alert channel for this server (Admin only).

        Examples:
            p!channel captcha #alerts   → set #alerts as the captcha alert channel
            p!channel captcha            → clear the channel (disables captcha alerts)
        """
        if channel is None:
            await self.db.set_captcha_channel(ctx.guild.id, None)
            embed = discord.Embed(
                description="🔕 Captcha alert channel cleared. Captcha alerts are now **disabled** for this server.",
                color=EMBED_COLOR,
            )
        else:
            await self.db.set_captcha_channel(ctx.guild.id, channel.id)
            embed = discord.Embed(
                description=(
                    f"✅ Captcha alert channel set to {channel.mention}.\n"
                    "Users will be pinged there when Pokétwo asks them to verify."
                ),
                color=EMBED_COLOR,
            )
        await ctx.reply(embed=embed, mention_author=False)

    @captcha_cmd.error
    async def captcha_cmd_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel. Mention a text channel or use its ID.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # p!channel lowpred #channel   (bot owner only)
    # ══════════════════════════════════════════════════════════════════

    @channel_group.command(name="lowpred", aliases=["low-prediction", "lowprediction"])
    @commands.is_owner()
    async def lowpred_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set the global low-confidence prediction log channel (bot owner only).

        Example:
            p!channel lowpred #low-predictions
        """
        if not channel:
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}channel lowpred #channel`",
                mention_author=False,
            )
            return
        await self.db.set_low_prediction_channel(channel.id)
        await ctx.reply(f"✅ Low-prediction channel set to {channel.mention}", mention_author=False)

    @lowpred_cmd.error
    async def lowpred_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("❌ Only the bot owner can use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # p!channel secondary #channel   (bot owner only)
    # ══════════════════════════════════════════════════════════════════

    @channel_group.command(name="secondary", aliases=["secondary-model", "secondarymodel"])
    @commands.is_owner()
    async def secondary_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set the global secondary-model log channel (bot owner only).

        Example:
            p!channel secondary #secondary-logs
        """
        if not channel:
            await ctx.reply(
                f"❌ Usage: `{ctx.prefix}channel secondary #channel`",
                mention_author=False,
            )
            return
        await self.db.set_secondary_model_channel(channel.id)
        await ctx.reply(f"✅ Secondary model channel set to {channel.mention}", mention_author=False)

    @secondary_cmd.error
    async def secondary_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("❌ Only the bot owner can use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)

    # ══════════════════════════════════════════════════════════════════
    # p!channel settings   (anyone)
    # ══════════════════════════════════════════════════════════════════

    @channel_group.command(name="settings", aliases=["view", "config"])
    async def channel_settings_cmd(self, ctx):
        """View every configured channel for this server at a glance."""
        settings = await self.db.get_guild_settings(ctx.guild.id)

        embed = discord.Embed(
            title=f"📺 Channel Settings — {ctx.guild.name}",
            color=EMBED_COLOR,
        )

        def _val(key):
            ch_id = settings.get(key)
            return f"<#{ch_id}>" if ch_id else "Not set"

        # ── Captcha ────────────────────────────────────────────────────
        embed.add_field(name="🔐 Captcha Alerts", value=_val("captcha_channel_id"), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        # ── Starboard ──────────────────────────────────────────────────
        embed.add_field(
            name="⭐ Starboard Channels",
            value=(
                f"Catch: {_val('starboard_catch_channel_id')}\n"
                f"Shiny: {_val('starboard_shiny_channel_id')}\n"
                f"Gigantamax: {_val('starboard_gigantamax_channel_id')}\n"
                f"High IV: {_val('starboard_highiv_channel_id')}\n"
                f"Low IV: {_val('starboard_lowiv_channel_id')}\n"
                f"MissingNo: {_val('starboard_missingno_channel_id')}\n"
                f"Milestone: {_val('starboard_milestone_channel_id')}\n"
                f"Egg: {_val('starboard_egg_channel_id')}\n"
                f"Unbox: {_val('starboard_unbox_channel_id')}"
            ),
            inline=False,
        )

        embed.set_footer(text=f"Guild ID: {ctx.guild.id} • Use p!channel <subcommand> to configure")
        await ctx.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelConfig(bot))
