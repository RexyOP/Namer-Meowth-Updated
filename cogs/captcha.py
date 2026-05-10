"""Captcha alert cog — pings users in a designated channel when Pokétwo asks them to verify."""
import re
import time
import discord
from discord import app_commands
from discord.ext import commands
import config

# Pokétwo bot user ID (same constant used in incense.py)
POKETWO_USER_ID = 716390085896962058

# Matches: "Whoa there. Please tell us you're human! https://verify.poketwo.net/captcha/<user_id>"
CAPTCHA_PATTERN = re.compile(
    r"Whoa there\. Please tell us you're human!\s+https://verify\.poketwo\.net/captcha/(\d+)",
    re.IGNORECASE,
)

# Cooldown: don't re-ping the same user in the same guild within this many seconds
CAPTCHA_COOLDOWN_SECONDS = 300  # 5 minutes


class VerifyButton(discord.ui.View):
    """A persistent-ish View with a single link button pointing to the captcha URL."""

    def __init__(self, verify_url: str):
        super().__init__(timeout=600)  # disappear after 10 min
        self.add_item(
            discord.ui.Button(
                label="✅ Verify",
                style=discord.ButtonStyle.link,
                url=verify_url,
            )
        )


class Captcha(commands.Cog):
    """
    Watches every message in all guilds.
    When Pokétwo sends a captcha challenge, pings the affected user
    in the server's configured captcha alert channel.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { (guild_id, user_id): last_alerted_timestamp }
        self._cooldowns: dict[tuple[int, int], float] = {}

    @property
    def db(self):
        return self.bot.db

    # ── Listener ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Only care about Pokétwo messages in guilds
        if not message.guild:
            return
        if message.author.id != POKETWO_USER_ID:
            return

        content = message.content or ""
        match = CAPTCHA_PATTERN.search(content)
        if not match:
            return

        user_id = int(match.group(1))
        guild_id = message.guild.id
        verify_url = f"https://verify.poketwo.net/captcha/{user_id}"

        # Check if captcha channel is configured — if not, feature is disabled
        captcha_channel_id = await self.db.get_captcha_channel(guild_id)
        if not captcha_channel_id:
            return

        captcha_channel = message.guild.get_channel(captcha_channel_id)
        if not isinstance(captcha_channel, discord.TextChannel):
            return

        # Cooldown check
        now = time.monotonic()
        cooldown_key = (guild_id, user_id)
        last_alerted = self._cooldowns.get(cooldown_key, 0)
        if now - last_alerted < CAPTCHA_COOLDOWN_SECONDS:
            return  # Already alerted recently — skip

        self._cooldowns[cooldown_key] = now

        # Resolve a display name for the user
        member = message.guild.get_member(user_id)
        if member is None:
            try:
                member = await message.guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                member = None

        display_name = member.display_name if member else f"<@{user_id}>"

        # Build the alert
        embed = discord.Embed(
            title="🔐 Captcha Required!",
            description=(
                f"<@{user_id}> ({display_name}), you need to verify!\n\n"
                f"Pokétwo has flagged your account. Click the button below or visit:\n"
                f"{verify_url}"
            ),
            color=config.EMBED_COLOR,
        )
        embed.set_footer(text=f"Detected in #{message.channel.name}")

        try:
            await captcha_channel.send(
                content=f"<@{user_id}>",
                embed=embed,
                view=VerifyButton(verify_url),
            )
        except discord.Forbidden:
            pass  # Bot lacks permission to send in the captcha channel

    # ── Commands ─────────────────────────────────────────────────────

    @commands.command(name="captcha-channel", aliases=["captchachannel", "setcaptcha"])
    @commands.has_permissions(administrator=True)
    async def captcha_channel_command(self, ctx, channel: discord.TextChannel = None):
        """Set or clear the captcha alert channel for this server (Admin only).

        Examples:
            p!captcha-channel #alerts   → set #alerts as the captcha channel
            p!captcha-channel           → clear the captcha channel (disables alerts)
        """
        if channel is None:
            # Clear the channel → disable captcha alerts
            await self.db.set_captcha_channel(ctx.guild.id, None)
            embed = discord.Embed(
                description="🔕 Captcha alert channel cleared. Captcha alerts are now **disabled** for this server.",
                color=config.EMBED_COLOR,
            )
        else:
            await self.db.set_captcha_channel(ctx.guild.id, channel.id)
            embed = discord.Embed(
                description=(
                    f"✅ Captcha alert channel set to {channel.mention}.\n"
                    f"Users will be pinged there when Pokétwo asks them to verify."
                ),
                color=config.EMBED_COLOR,
            )

        await ctx.reply(embed=embed, mention_author=False)

    @captcha_channel_command.error
    async def captcha_channel_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel. Mention a text channel or use its ID.", mention_author=False)

    # ── Slash ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="captcha-channel",
        description="Set or clear the captcha alert channel (Admin only). Omit to disable."
    )
    @app_commands.describe(channel="The channel to send captcha alerts in. Omit to clear/disable.")
    @app_commands.default_permissions(administrator=True)
    async def slash_captcha_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        ctx = await commands.Context.from_interaction(interaction)
        await self.captcha_channel_command(ctx, channel=channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Captcha(bot))
