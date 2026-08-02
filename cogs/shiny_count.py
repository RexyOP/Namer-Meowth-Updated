"""Shiny count tracking — per-guild shiny catch counter with an optional
channel that auto-renames itself to show the live count.

Commands (all live under p!shinycount, aliases: p!sc / p!shiny-count):

  p!sc                      — show the current shiny count
  p!sc edit <count>         — manually set the shiny count            (Admin only)
  p!sc channel [#ch | id]   — set/clear the auto-renaming channel      (Admin only)
                               (same setting is also available as
                               p!channel shinycount, see channelconfig.py)

Notes:
  - The count is only incremented from real, automatically-detected shiny
    catches (see the on_message listener in starboard_catch.py). Running
    p!catchcheck to preview/test a catch never touches the count or renames
    anything.
  - Channel renames go through a small per-channel queue so we never hammer
    Discord's channel-edit rate limit (roughly 2 renames per 10 minutes per
    channel). If several shinies are caught back-to-back, only the latest
    count ends up applied once the rate limit clears.
  - Renaming only ever touches the trailing "-<number>" of the channel name,
    so any emojis or special symbols before it (e.g. "🌟┃shiny·starboard")
    are left completely untouched.
"""
import asyncio
import re
import discord
from discord.ext import commands
from config import EMBED_COLOR

NO_MENTIONS = discord.AllowedMentions.none()

# Matches an optional space, a hyphen, an optional space, then digits at the
# very end of the channel name — e.g. "-65", " - 65", "-65 " all match.
_TRAILING_COUNT_RE = re.compile(r'\s*-\s*\d+$')


def build_new_channel_name(current_name: str, new_count: int) -> str:
    """Return current_name with its trailing '-<number>' swapped for new_count.

    Every emoji, symbol, and word before the trailing count is preserved
    exactly as-is. If there's no trailing "-<number>" to replace, the count
    is appended instead.
    """
    if _TRAILING_COUNT_RE.search(current_name):
        new_name = _TRAILING_COUNT_RE.sub(f"-{new_count}", current_name)
    else:
        new_name = f"{current_name}-{new_count}"
    return new_name[:100]  # Discord's channel name length cap


class ChannelRenameQueue:
    """Coalescing per-channel rename queue.

    Discord only allows a channel's name to change ~2 times per 10 minutes.
    Rather than firing a rename per shiny catch (and piling up 429s), each
    channel gets a single background worker that always applies whatever the
    *latest* requested name is — older, now-stale requests are simply
    dropped.
    """

    def __init__(self):
        self._pending: dict[int, str] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    def request_rename(self, channel: discord.abc.GuildChannel, new_name: str):
        self._pending[channel.id] = new_name
        existing = self._tasks.get(channel.id)
        if existing is None or existing.done():
            self._tasks[channel.id] = asyncio.create_task(self._worker(channel))

    async def _worker(self, channel: discord.abc.GuildChannel):
        try:
            while True:
                target = self._pending.get(channel.id)
                if target is None:
                    return
                if channel.name == target:
                    self._pending.pop(channel.id, None)
                    return
                try:
                    await channel.edit(name=target, reason="Shiny count update")
                except discord.HTTPException as e:
                    # Rate limited (or a transient error) — wait it out, then
                    # loop back around and re-check the pending name, since a
                    # newer count may have come in while we were waiting.
                    retry_after = getattr(e, "retry_after", None) or 30
                    await asyncio.sleep(retry_after + 1)
                    continue
                except discord.Forbidden:
                    self._pending.pop(channel.id, None)
                    return

                if self._pending.get(channel.id) == target:
                    self._pending.pop(channel.id, None)
        finally:
            self._tasks.pop(channel.id, None)


class ShinyCount(commands.Cog):
    """Tracks and displays each server's shiny catch count."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rename_queue = ChannelRenameQueue()

    @property
    def db(self):
        return self.bot.db

    # ── Shared logic used by both the auto-detector and the edit command ──

    async def _apply_channel_rename(self, guild: discord.Guild, new_count: int):
        """Queue a rename of the configured shiny-count channel, if any."""
        channel_id = await self.db.get_shiny_count_channel(guild.id)
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id)
        if not channel:
            return None

        new_name = build_new_channel_name(channel.name, new_count)
        if new_name != channel.name:
            self.rename_queue.request_rename(channel, new_name)
        return channel

    async def record_shiny_catch(self, guild: discord.Guild) -> int:
        """Increment the guild's shiny count and rename its shiny-count
        channel, if one is configured.

        Only call this from real, automatically-detected catches — never
        from manual test/preview commands like p!catchcheck.
        """
        new_count = await self.db.increment_shiny_count(guild.id)
        await self._apply_channel_rename(guild, new_count)
        return new_count

    # ══════════════════════════════════════════════════════════════════
    # p!shinycount  (aliases: sc, shiny-count)
    # ══════════════════════════════════════════════════════════════════

    @commands.group(name="shinycount", aliases=["sc", "shiny-count"], invoke_without_command=True)
    async def shinycount_group(self, ctx):
        """View this server's current shiny count."""
        count = await self.db.get_shiny_count(ctx.guild.id)
        embed = discord.Embed(
            description=f"✨ **Shiny Count:** {count:,}",
            color=EMBED_COLOR,
        )
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    @shinycount_group.error
    async def shinycount_group_error(self, ctx, error):
        print(f"Unexpected error in shinycount: {error}")
        await ctx.reply("❌ An unexpected error occurred. Please try again.", mention_author=False, allowed_mentions=NO_MENTIONS)

    # ── p!sc edit <count> ────────────────────────────────────────────────

    @shinycount_group.command(name="edit", aliases=["set"])
    @commands.has_permissions(administrator=True)
    async def shinycount_edit_cmd(self, ctx, count: int):
        """Manually set the shiny count for this server (Admin only).

        Example:
            p!sc edit 45
        """
        if count < 0:
            await ctx.reply("❌ Count can't be negative.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        await self.db.set_shiny_count(ctx.guild.id, count)
        channel = await self._apply_channel_rename(ctx.guild, count)

        description = f"✅ Shiny count set to **{count:,}**."
        if channel:
            description += f"\n{channel.mention} will update shortly."

        await ctx.reply(
            embed=discord.Embed(description=description, color=EMBED_COLOR),
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    @shinycount_edit_cmd.error
    async def shinycount_edit_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply(f"❌ Usage: `{ctx.prefix}sc edit <number>`", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            print(f"Unexpected error in shinycount edit: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.", mention_author=False, allowed_mentions=NO_MENTIONS)

    # ── p!sc channel [#ch | id] ──────────────────────────────────────────
    # (Also available as p!channel shinycount — see channelconfig.py)

    @shinycount_group.command(name="channel", aliases=["ch"])
    @commands.has_permissions(administrator=True)
    async def shinycount_channel_cmd(self, ctx, channel: discord.TextChannel = None):
        """Set or clear the channel that auto-renames itself with the shiny count (Admin only).

        Examples:
            p!sc channel #shiny-starboard   → set the channel
            p!sc channel 123456789012345678 → set by ID
            p!sc channel                    → clear (disables auto-renaming)
        """
        if channel is None:
            await self.db.set_shiny_count_channel(ctx.guild.id, None)
            await ctx.reply(
                "🔕 Shiny count channel cleared. Auto-renaming is now disabled.",
                mention_author=False,
                allowed_mentions=NO_MENTIONS,
            )
            return

        await self.db.set_shiny_count_channel(ctx.guild.id, channel.id)
        await ctx.reply(
            f"✅ Shiny count channel set to {channel.mention}. Its name will update on every shiny catch.",
            mention_author=False,
            allowed_mentions=NO_MENTIONS,
        )

    @shinycount_channel_cmd.error
    async def shinycount_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel. Mention a text channel or use its ID.", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            print(f"Unexpected error in shinycount channel: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.", mention_author=False, allowed_mentions=NO_MENTIONS)


async def setup(bot: commands.Bot):
    await bot.add_cog(ShinyCount(bot))
