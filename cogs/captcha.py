"""Captcha alert cog — pings users in a designated channel when Pokétwo asks them to verify.

Channel configuration has been moved to channel_config.py → p!channel captcha #channel
"""
import re
import time
import asyncio
import discord
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
    """A persistent-ish View with a Verify link button and a Jump to Message button."""

    def __init__(self, verify_url: str, message_url: str):
        super().__init__(timeout=120)  # reduced from 600 — verify link is one-time use
        self.add_item(
            discord.ui.Button(
                label="✅ Verify",
                style=discord.ButtonStyle.link,
                url=verify_url,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="🔗 Jump to Message",
                style=discord.ButtonStyle.link,
                url=message_url,
            )
        )


class Captcha(commands.Cog):
    """
    Watches every message in all guilds.
    When Pokétwo sends a captcha challenge, pings the affected user
    in the server's configured captcha alert channel.

    Channel setup is handled by the ChannelConfig cog:
        p!channel captcha #channel   → set captcha alert channel
        p!channel captcha             → clear / disable
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { (guild_id, user_id): last_alerted_timestamp }
        self._cooldowns: dict[tuple[int, int], float] = {}
        # Start background task that prunes stale cooldown entries every 5 min
        self._cleanup_task = asyncio.create_task(self._cleanup_cooldowns_loop())

    def cog_unload(self):
        self._cleanup_task.cancel()

    async def _cleanup_cooldowns_loop(self):
        """Periodically remove expired cooldown entries to prevent unbounded growth."""
        await asyncio.sleep(60)  # initial delay
        while True:
            try:
                now = time.monotonic()
                stale = [
                    k for k, ts in self._cooldowns.items()
                    if now - ts >= CAPTCHA_COOLDOWN_SECONDS
                ]
                for k in stale:
                    del self._cooldowns[k]
                if stale:
                    print(f"[CAPTCHA] Cleaned {len(stale)} expired cooldown entries")
            except Exception as e:
                print(f"[CAPTCHA] Cleanup error: {e}")
            await asyncio.sleep(300)  # run every 5 minutes

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
                view=VerifyButton(verify_url, message.jump_url),
            )
        except discord.Forbidden:
            pass  # Bot lacks permission to send in the captcha channel


async def setup(bot: commands.Bot):
    await bot.add_cog(Captcha(bot))
