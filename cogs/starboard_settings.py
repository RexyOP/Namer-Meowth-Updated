"""Starboard channel configuration and settings"""
import discord
from discord.ext import commands
from config import EMBED_COLOR

class StarboardSettings(commands.Cog):
    """Starboard channel configuration"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @property
    def db(self):
        """Get database from bot"""
        return self.bot.db
    
    # Set all starboard channels at once
    @commands.command(name="starboard-all")
    @commands.has_permissions(administrator=True)
    async def starboard_all_command(self, ctx, channel: str = None):
        """Set one channel for all starboard categories
        
        Example: p!starboard-all #starboard
        To remove all: p!starboard-all none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove all.", mention_author=False)
            return
        
        # Check if user wants to remove all channels
        if channel.lower() == "none":
            await self.db.set_starboard_catch_channel(ctx.guild.id, None)
            await self.db.set_starboard_egg_channel(ctx.guild.id, None)
            await self.db.set_starboard_unbox_channel(ctx.guild.id, None)
            await self.db.set_starboard_shiny_channel(ctx.guild.id, None)
            await self.db.set_starboard_gigantamax_channel(ctx.guild.id, None)
            await self.db.set_starboard_highiv_channel(ctx.guild.id, None)
            await self.db.set_starboard_lowiv_channel(ctx.guild.id, None)
            await self.db.set_starboard_missingno_channel(ctx.guild.id, None)
            await self.db.set_starboard_milestone_channel(ctx.guild.id, None)
            
            await ctx.reply("✅ All starboard channels have been removed", mention_author=False)
            return
        
        # Try to convert to TextChannel
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
            return
        
        # Set all starboard channels to the same channel
        await self.db.set_starboard_catch_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_egg_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_unbox_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_shiny_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_gigantamax_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_highiv_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_lowiv_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_missingno_channel(ctx.guild.id, text_channel.id)
        await self.db.set_starboard_milestone_channel(ctx.guild.id, text_channel.id)
        
        await ctx.reply(f"✅ All starboard channels set to {text_channel.mention}", mention_author=False)
    
    # Server starboard channels (admin only)
    @commands.command(name="starboard-catch")
    @commands.has_permissions(administrator=True)
    async def starboard_catch_command(self, ctx, channel: str = None):
        """Set the catch starboard channel for this server
        
        Example: p!starboard-catch #catches
        To remove: p!starboard-catch none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_catch_channel(ctx.guild.id, None)
            await ctx.reply("✅ Catch starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_catch_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Catch starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-egg")
    @commands.has_permissions(administrator=True)
    async def starboard_egg_command(self, ctx, channel: str = None):
        """Set the egg hatch starboard channel for this server
        
        Example: p!starboard-egg #egg-hatches
        To remove: p!starboard-egg none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_egg_channel(ctx.guild.id, None)
            await ctx.reply("✅ Egg starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_egg_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Egg starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-unbox")
    @commands.has_permissions(administrator=True)
    async def starboard_unbox_command(self, ctx, channel: str = None):
        """Set the unbox starboard channel for this server
        
        Example: p!starboard-unbox #unboxes
        To remove: p!starboard-unbox none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_unbox_channel(ctx.guild.id, None)
            await ctx.reply("✅ Unbox starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_unbox_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Unbox starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-shiny")
    @commands.has_permissions(administrator=True)
    async def starboard_shiny_command(self, ctx, channel: str = None):
        """Set the shiny catch starboard channel for this server
        
        Example: p!starboard-shiny #shinies
        To remove: p!starboard-shiny none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_shiny_channel(ctx.guild.id, None)
            await ctx.reply("✅ Shiny starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_shiny_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Shiny catch starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-gigantamax")
    @commands.has_permissions(administrator=True)
    async def starboard_gigantamax_command(self, ctx, channel: str = None):
        """Set the Gigantamax catch starboard channel for this server
        
        Example: p!starboard-gigantamax #gmax
        To remove: p!starboard-gigantamax none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_gigantamax_channel(ctx.guild.id, None)
            await ctx.reply("✅ Gigantamax starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_gigantamax_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Gigantamax starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-highiv")
    @commands.has_permissions(administrator=True)
    async def starboard_highiv_command(self, ctx, channel: str = None):
        """Set the high IV starboard channel for this server
        
        Example: p!starboard-highiv #high-ivs
        To remove: p!starboard-highiv none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_highiv_channel(ctx.guild.id, None)
            await ctx.reply("✅ High IV starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_highiv_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ High IV starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-lowiv")
    @commands.has_permissions(administrator=True)
    async def starboard_lowiv_command(self, ctx, channel: str = None):
        """Set the low IV starboard channel for this server
        
        Example: p!starboard-lowiv #low-ivs
        To remove: p!starboard-lowiv none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_lowiv_channel(ctx.guild.id, None)
            await ctx.reply("✅ Low IV starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_lowiv_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ Low IV starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @commands.command(name="starboard-missingno")
    @commands.has_permissions(administrator=True)
    async def starboard_missingno_command(self, ctx, channel: str = None):
        """Set the MissingNo catch starboard channel for this server
        
        Example: p!starboard-missingno #missingno
        To remove: p!starboard-missingno none
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel, provide a channel ID, or use 'none' to remove.", mention_author=False)
            return
        
        if channel.lower() == "none":
            await self.db.set_starboard_missingno_channel(ctx.guild.id, None)
            await ctx.reply("✅ MissingNo starboard channel removed", mention_author=False)
            return
        
        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_missingno_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(f"✅ MissingNo starboard channel set to {text_channel.mention}", mention_author=False)
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)

    @commands.command(name="starboard-milestone")
    @commands.has_permissions(administrator=True)
    async def starboard_milestone_command(self, ctx, channel: str = None):
        """Set the milestone catch starboard channel for this server.

        Logs catches when a user reaches exactly 100 / 1,000 / 10,000 / 100,000
        of any single Pokémon species.

        Example: p!starboard-milestone #milestones
        To remove: p!starboard-milestone none
        """
        if not channel:
            await ctx.reply(
                "❌ Please mention a channel, provide a channel ID, or use 'none' to remove.\n"
                "This channel logs 100 / 1,000 / 10,000 / 100,000 catches of a single Pokémon.",
                mention_author=False
            )
            return

        if channel.lower() == "none":
            await self.db.set_starboard_milestone_channel(ctx.guild.id, None)
            await ctx.reply("✅ Milestone starboard channel removed", mention_author=False)
            return

        try:
            converter = commands.TextChannelConverter()
            text_channel = await converter.convert(ctx, channel)
            await self.db.set_starboard_milestone_channel(ctx.guild.id, text_channel.id)
            await ctx.reply(
                f"✅ Milestone starboard channel set to {text_channel.mention}\n"
                f"Will log catches at **100 / 1,000 /10,000 / 100,000** of any Pokémon.",
                mention_author=False
            )
        except commands.BadArgument:
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    # Global starboard channels (bot owner only)
    @commands.command(name="global-starboard-catch")
    @commands.is_owner()
    async def global_starboard_catch_command(self, ctx, channel: discord.TextChannel = None):
        """Set the global catch starboard channel (bot owner only)
        
        Example: p!global-starboard-catch #global-catches
        """
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        
        await self.db.set_global_starboard_catch_channel(channel.id)
        await ctx.reply(f"✅ Global catch starboard channel set to {channel.mention}", mention_author=False)
    
    @commands.command(name="global-starboard-egg")
    @commands.is_owner()
    async def global_starboard_egg_command(self, ctx, channel: discord.TextChannel = None):
        """Set the global egg starboard channel (bot owner only)"""
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        
        await self.db.set_global_starboard_egg_channel(channel.id)
        await ctx.reply(f"✅ Global egg starboard channel set to {channel.mention}", mention_author=False)
    
    @commands.command(name="global-starboard-unbox")
    @commands.is_owner()
    async def global_starboard_unbox_command(self, ctx, channel: discord.TextChannel = None):
        """Set the global unbox starboard channel (bot owner only)"""
        if not channel:
            await ctx.reply("❌ Please mention a channel or provide a channel ID.", mention_author=False)
            return
        
        await self.db.set_global_starboard_unbox_channel(channel.id)
        await ctx.reply(f"✅ Global unbox starboard channel set to {channel.mention}", mention_author=False)
    
    # View starboard settings
    @commands.command(name="starboard-settings", aliases=["sbsettings", "starboard-config"])
    async def starboard_settings_command(self, ctx):
        """View current starboard channel settings for this server"""
        settings = await self.db.get_guild_settings(ctx.guild.id)
        
        embed = discord.Embed(
            title=f"⭐ Starboard Settings for {ctx.guild.name}",
            color=EMBED_COLOR
        )
        
        # Catch channels
        catch_channel_id = settings.get('starboard_catch_channel_id')
        if catch_channel_id:
            embed.add_field(name="Catch Channel", value=f"<#{catch_channel_id}>", inline=True)
        else:
            embed.add_field(name="Catch Channel", value="Not set", inline=True)
        
        # Shiny channel
        shiny_channel_id = settings.get('starboard_shiny_channel_id')
        if shiny_channel_id:
            embed.add_field(name="Shiny Channel", value=f"<#{shiny_channel_id}>", inline=True)
        else:
            embed.add_field(name="Shiny Channel", value="Not set", inline=True)
        
        # Gigantamax channel
        gmax_channel_id = settings.get('starboard_gigantamax_channel_id')
        if gmax_channel_id:
            embed.add_field(name="Gigantamax Channel", value=f"<#{gmax_channel_id}>", inline=True)
        else:
            embed.add_field(name="Gigantamax Channel", value="Not set", inline=True)
        
        # High IV channel
        highiv_channel_id = settings.get('starboard_highiv_channel_id')
        if highiv_channel_id:
            embed.add_field(name="High IV Channel", value=f"<#{highiv_channel_id}>", inline=True)
        else:
            embed.add_field(name="High IV Channel", value="Not set", inline=True)
        
        # Low IV channel
        lowiv_channel_id = settings.get('starboard_lowiv_channel_id')
        if lowiv_channel_id:
            embed.add_field(name="Low IV Channel", value=f"<#{lowiv_channel_id}>", inline=True)
        else:
            embed.add_field(name="Low IV Channel", value="Not set", inline=True)
        
        # MissingNo channel
        missingno_channel_id = settings.get('starboard_missingno_channel_id')
        if missingno_channel_id:
            embed.add_field(name="MissingNo Channel", value=f"<#{missingno_channel_id}>", inline=True)
        else:
            embed.add_field(name="MissingNo Channel", value="Not set", inline=True)

        # Milestone channel
        milestone_channel_id = settings.get('starboard_milestone_channel_id')
        if milestone_channel_id:
            embed.add_field(name="Milestone Channel", value=f"<#{milestone_channel_id}>", inline=True)
        else:
            embed.add_field(name="Milestone Channel", value="Not set", inline=True)
        
        # Egg channel
        egg_channel_id = settings.get('starboard_egg_channel_id')
        if egg_channel_id:
            embed.add_field(name="Egg Channel", value=f"<#{egg_channel_id}>", inline=True)
        else:
            embed.add_field(name="Egg Channel", value="Not set", inline=True)
        
        # Unbox channel
        unbox_channel_id = settings.get('starboard_unbox_channel_id')
        if unbox_channel_id:
            embed.add_field(name="Unbox Channel", value=f"<#{unbox_channel_id}>", inline=True)
        else:
            embed.add_field(name="Unbox Channel", value="Not set", inline=True)
        
        embed.set_footer(text=f"Guild ID: {ctx.guild.id}")
        await ctx.reply(embed=embed, mention_author=False)
    
    # Error handlers
    @starboard_all_command.error
    @starboard_catch_command.error
    @starboard_egg_command.error
    @starboard_unbox_command.error
    @starboard_shiny_command.error
    @starboard_gigantamax_command.error
    @starboard_highiv_command.error
    @starboard_lowiv_command.error
    @starboard_missingno_command.error
    @starboard_milestone_command.error
    async def starboard_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)
    
    @global_starboard_catch_command.error
    @global_starboard_egg_command.error
    @global_starboard_unbox_command.error
    async def global_starboard_command_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.reply("❌ Only the bot owner can use this command.", mention_author=False)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Invalid channel mention or ID.", mention_author=False)

async def setup(bot):
    await bot.add_cog(StarboardSettings(bot))
