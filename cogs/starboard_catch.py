"""Starboard logging for Pokemon catches"""
import discord
import re
from datetime import datetime
from discord.ext import commands
from config import POKETWO_USER_ID, EMBED_COLOR, HIGH_IV_THRESHOLD, LOW_IV_THRESHOLD
from starboard_utils import (
    get_gender_emoji,
    find_pokemon_image_url,
    format_iv_display,
    create_jump_button_view
)

class StarboardCatch(commands.Cog):
    """Automatic logging of Pokemon catches to starboard channels"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @property
    def db(self):
        """Get database from bot"""
        return self.bot.db
    
    def parse_poketwo_catch_message(self, message_content: str) -> dict:
        """Parse Poketwo catch message to extract information"""
        catch_pattern = r"Congratulations <@!?(\d+)>! You caught a Level (\d+) (.+?)(?:\s+\((\d+\.?\d*)%\))?!"
        
        match = re.search(catch_pattern, message_content)
        if not match:
            return None
        
        user_id = match.group(1)
        level = match.group(2)
        pokemon_name_with_gender = match.group(3).strip()
        iv_str = match.group(4)
        
        iv = iv_str if iv_str else "Hidden"
        
        gender = None
        pokemon_name = pokemon_name_with_gender
        
        if re.search(r'<:male:\d+>', message_content):
            gender = 'male'
            pokemon_name = re.sub(r'<:male:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:female:\d+>', message_content):
            gender = 'female'
            pokemon_name = re.sub(r'<:female:\d+>', '', pokemon_name_with_gender).strip()
        elif re.search(r'<:unknown:\d+>', message_content):
            gender = 'unknown'
            pokemon_name = re.sub(r'<:unknown:\d+>', '', pokemon_name_with_gender).strip()
        
        is_shiny = "These colors seem unusual... ✨" in message_content
        is_gigantamax = "Woah! It seems that this pokémon has the Gigantamax Factor..." in message_content
        
        shiny_chain = None
        chain_pattern = r"Shiny streak reset\. \(\*\*(\d+)\*\*\)"
        chain_match = re.search(chain_pattern, message_content)
        if chain_match:
            shiny_chain = chain_match.group(1)
        
        return {
            'user_id': user_id,
            'level': level,
            'pokemon_name': pokemon_name,
            'iv': iv,
            'is_shiny': is_shiny,
            'is_gigantamax': is_gigantamax,
            'shiny_chain': shiny_chain,
            'gender': gender,
            'message_type': 'catch'
        }
    
    # Milestone catch counts that qualify for the milestone starboard
    MILESTONE_COUNTS = {100, 1_000, 10_000, 100_000}

    def parse_poketwo_milestone_message(self, message_content: str) -> dict:
        """Parse Poketwo milestone catch message.

        Matches lines like:
          'This is your 1,000th Zygarde!'
          'This is your 10000th Charizard!'
        Returns None if the count is not one of the three milestones.
        """
        # Allow optional commas in the number (1,000 / 10,000 / 100,000)
        milestone_pattern = r"This is your ([\d,]+)(?:st|nd|rd|th) (.+?)!"
        match = re.search(milestone_pattern, message_content)
        if not match:
            return None

        raw_count = match.group(1).replace(",", "")
        try:
            count = int(raw_count)
        except ValueError:
            return None

        if count not in self.MILESTONE_COUNTS:
            return None

        # Re-use the standard catch parser to get user/pokemon/level/iv data
        catch_data = self.parse_poketwo_catch_message(message_content)
        if not catch_data:
            return None

        catch_data['message_type'] = 'milestone'
        catch_data['milestone_count'] = count
        return catch_data

    def parse_poketwo_missingno_message(self, message_content: str) -> dict:
        """Parse Poketwo MissingNo catch message"""
        missingno_pattern1 = r"Congratulations <@!?(\d+)>! You caught a Level \?\?\? MissingNo\.(?:<:[^:]+:\d+>)? \(\?\?\?%\)!"
        missingno_pattern2 = r"Congratulations <@!?(\d+)>! You caught a Level \?\?\? MissingNo\.(?:<:[^:]+:\d+>)!"
        
        match = re.search(missingno_pattern1, message_content) or re.search(missingno_pattern2, message_content)
        if not match:
            return None
        
        user_id = match.group(1)
        
        gender = None
        if re.search(r'<:male:\d+>', message_content):
            gender = 'male'
        elif re.search(r'<:female:\d+>', message_content):
            gender = 'female'
        elif re.search(r'<:unknown:\d+>', message_content):
            gender = 'unknown'
        
        is_shiny = "These colors seem unusual... ✨" in message_content
        
        return {
            'user_id': user_id,
            'level': '???',
            'pokemon_name': 'MissingNo.',
            'iv': '???',
            'is_shiny': is_shiny,
            'is_gigantamax': False,
            'gender': gender,
            'message_type': 'missingno'
        }
    
    def create_catch_embed(self, catch_data: dict, original_message: discord.Message = None) -> discord.Embed:
        """Create embed for catch"""
        pokemon_name = catch_data['pokemon_name']
        level = catch_data['level']
        iv = catch_data['iv']
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        gender = catch_data.get('gender')
        user_id = catch_data['user_id']
        shiny_chain = catch_data.get('shiny_chain')
        message_type = catch_data.get('message_type', 'catch')
        
        iv_display = format_iv_display(iv)
        gender_emoji = get_gender_emoji(gender)
        
        # Build display name
        if is_gigantamax:
            # Eternatus with Gigantamax factor is called Eternamax Eternatus
            if pokemon_name.lower() == "eternatus":
                display_pokemon_name = "Eternamax Eternatus"
            else:
                display_pokemon_name = f"Gigantamax {pokemon_name}"
        else:
            display_pokemon_name = pokemon_name
        
        if gender_emoji:
            pokemon_display = f"{display_pokemon_name} {gender_emoji}"
        else:
            pokemon_display = display_pokemon_name
        
        # find_pokemon_image_url handles gigantamax/eternamax lookup internally
        image_url = find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)
        
        embed_timestamp = original_message.created_at if original_message else datetime.utcnow()
        embed = discord.Embed(color=EMBED_COLOR, timestamp=embed_timestamp)
        
        if message_type == 'missingno':
            if is_shiny:
                embed.title = "✨ Shiny MissingNo. Detected ✨"
            else:
                from config import Emojis
                embed.title = f"{Emojis.MISSINGNO} MissingNo. Detected {Emojis.MISSINGNO}"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_display}\n**Level:** ???\n**IV:** {iv_display}"
        
        else:
            title_parts = []
            
            if is_shiny:
                title_parts.append("✨ Shiny")
            
            if is_gigantamax:
                from config import Emojis
                if pokemon_name.lower() == "eternatus":
                    title_parts.append(f"{Emojis.GIGANTAMAX} Eternamax")
                else:
                    title_parts.append(f"{Emojis.GIGANTAMAX} Gigantamax")
            
            if iv != "Hidden" and iv != "???":
                try:
                    iv_value = float(iv)
                    if iv_value >= HIGH_IV_THRESHOLD:
                        title_parts.append("📈 High IV")
                    elif iv_value <= LOW_IV_THRESHOLD:
                        title_parts.append("📉 Low IV")
                except ValueError:
                    pass
            
            embed.title = (" ".join(title_parts) + " Catch Detected") if title_parts else "Rare Catch Detected"
            embed.description = f"**Caught By:** <@{user_id}>\n**Pokémon:** {pokemon_display}\n**Level:** {level}\n**IV:** {iv_display}"
            
            if shiny_chain:
                embed.description += f"\n**Chain:** {shiny_chain}"
        
        if image_url:
            embed.set_thumbnail(url=image_url)
        
        return embed
    
    # Witty footer lines for milestone embeds
    MILESTONE_FOOTER_LINES = [
    "unemployed final boss",
    "grinding pixels like rent depends on it",
    "sleep schedule left the chat",
    "breaking records and mental stability",
    "built different • runs on zero sunlight",
    "running purely on caffeine and bad choices",
    "this is why the wifi bill is high",
    "this is what happens when 'just one more' wins",
    "this could’ve been avoided at multiple points",
    "this is why parents check screen time",
    "this is the long-term effect of 'why not'",
    "unemployed but somehow still busy",
    "bro made this their 9–5",
    "this is why 'just one more' is dangerous",
    "social life: 0 — pokédex entries: many",
    "do not ask how many hours this took. just clap",
    "this person needs sunlight immediately",
]

    def create_milestone_embed(self, catch_data: dict, original_message: discord.Message = None) -> discord.Embed:
        """Create embed for a milestone catch (100 / 1k / 10k / 100k)"""
        import random

        pokemon_name = catch_data['pokemon_name']
        level = catch_data['level']
        iv = catch_data['iv']
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        gender = catch_data.get('gender')
        user_id = catch_data['user_id']
        count = catch_data['milestone_count']

        iv_display = format_iv_display(iv)
        gender_emoji = get_gender_emoji(gender)

        if is_gigantamax:
            if pokemon_name.lower() == "eternatus":
                display_pokemon_name = "Eternamax Eternatus"
            else:
                display_pokemon_name = f"Gigantamax {pokemon_name}"
        else:
            display_pokemon_name = pokemon_name

        pokemon_display = f"{display_pokemon_name} {gender_emoji}".strip() if gender_emoji else display_pokemon_name

        image_url = find_pokemon_image_url(pokemon_name, is_shiny, gender, is_gigantamax)

        if count >= 100_000:
            medal = "🏆"
        elif count >= 10_000:
            medal = "🥇"
        elif count >= 1_000:
            medal = "🥈"
        else:
            medal = "🌱"

        formatted_count = f"{count:,}"

        embed = discord.Embed(
            title=f"{medal} Milestone Catch Detected",
            description=(
                f"**Caught By:** <@{user_id}>\n"
                f"**Pokémon:** {pokemon_display}\n"
                f"**Level:** {level}\n"
                f"**IV:** {iv_display}\n"
                f"**Milestone:** {formatted_count}th caught"
            ),
            color=EMBED_COLOR,
            timestamp=(original_message.created_at if original_message else datetime.utcnow())
        )

        if image_url:
            embed.set_thumbnail(url=image_url)

        embed.set_footer(text=random.choice(self.MILESTONE_FOOTER_LINES))

        return embed

    async def send_to_milestone_starboard(self, guild: discord.Guild, catch_data: dict, original_message: discord.Message = None):
        """Send a milestone catch to the milestone starboard channel"""
        settings = await self.db.get_guild_settings(guild.id)
        milestone_channel_id = settings.get('starboard_milestone_channel_id')

        channels_to_send = []
        if milestone_channel_id:
            channels_to_send.append(milestone_channel_id)

        global_milestone_channel_id = await self.db.get_global_starboard_milestone_channel()
        embed = self.create_milestone_embed(catch_data, original_message)
        view = create_jump_button_view(original_message)

        for channel_id in channels_to_send:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to milestone starboard channel {channel_id}: {e}")

        if global_milestone_channel_id:
            global_channel = self.bot.get_channel(global_milestone_channel_id)
            if global_channel:
                try:
                    await global_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to global milestone starboard channel: {e}")

    async def send_to_starboard_channels(self, guild: discord.Guild, catch_data: dict, original_message: discord.Message = None):
        """Send catch to appropriate starboard channels"""
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']
        message_type = catch_data.get('message_type', 'catch')
        pokemon_name = catch_data['pokemon_name']
        
        settings = await self.db.get_guild_settings(guild.id)
        channels_to_send = []
        
        if message_type == 'missingno':
            missingno_channel_id = settings.get('starboard_missingno_channel_id')
            if missingno_channel_id:
                channels_to_send.append(missingno_channel_id)
        else:
            catch_channel_id = settings.get('starboard_catch_channel_id')
            if catch_channel_id:
                channels_to_send.append(catch_channel_id)
            
            if is_shiny:
                shiny_channel_id = settings.get('starboard_shiny_channel_id')
                if shiny_channel_id and shiny_channel_id not in channels_to_send:
                    channels_to_send.append(shiny_channel_id)
            
            if is_gigantamax:
                gmax_channel_id = settings.get('starboard_gigantamax_channel_id')
                if gmax_channel_id and gmax_channel_id not in channels_to_send:
                    channels_to_send.append(gmax_channel_id)
            
            # Eternatus doesn't show IV alongside Gigantamax factor
            if pokemon_name.lower() != "eternatus" and iv not in ["Hidden", "???"]:
                try:
                    iv_value = float(iv)
                    if iv_value >= HIGH_IV_THRESHOLD:
                        highiv_channel_id = settings.get('starboard_highiv_channel_id')
                        if highiv_channel_id and highiv_channel_id not in channels_to_send:
                            channels_to_send.append(highiv_channel_id)
                    elif iv_value <= LOW_IV_THRESHOLD:
                        lowiv_channel_id = settings.get('starboard_lowiv_channel_id')
                        if lowiv_channel_id and lowiv_channel_id not in channels_to_send:
                            channels_to_send.append(lowiv_channel_id)
                except ValueError:
                    pass
        
        embed = self.create_catch_embed(catch_data, original_message)
        view = create_jump_button_view(original_message)
        
        for channel_id in channels_to_send:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to starboard channel {channel_id}: {e}")
        
        global_catch_channel_id = await self.db.get_global_starboard_catch_channel()
        if global_catch_channel_id:
            global_channel = self.bot.get_channel(global_catch_channel_id)
            if global_channel:
                try:
                    await global_channel.send(embed=embed, view=view)
                except Exception as e:
                    print(f"Error sending to global starboard channel: {e}")
    
    def should_log_catch(self, catch_data: dict) -> bool:
        """Determine if catch should be logged based on criteria"""
        is_shiny = catch_data['is_shiny']
        is_gigantamax = catch_data['is_gigantamax']
        iv = catch_data['iv']
        message_type = catch_data.get('message_type', 'catch')
        
        if message_type == 'missingno':
            return True
        if is_shiny or is_gigantamax:
            return True
        if iv not in ["Hidden", "???"]:
            try:
                iv_value = float(iv)
                if iv_value >= HIGH_IV_THRESHOLD or iv_value <= LOW_IV_THRESHOLD:
                    return True
            except ValueError:
                pass
        return False
    
    async def _resolve_catch_message(self, ctx, message_id: int):
        """Fetch a message by ID (searching the whole guild if needed) and validate it's from Poketwo.

        Returns (original_message, catch_content, error_str). error_str is None on success.
        """
        try:
            try:
                original_message = await ctx.channel.fetch_message(message_id)
            except discord.NotFound:
                original_message = None
                for channel in ctx.guild.text_channels:
                    if channel.permissions_for(ctx.guild.me).read_message_history:
                        try:
                            original_message = await channel.fetch_message(message_id)
                            break
                        except (discord.NotFound, discord.Forbidden):
                            continue
                if not original_message:
                    return None, None, f"❌ Could not find message with ID `{message_id}` in this server."

            if original_message.author.id != POKETWO_USER_ID:
                return None, None, f"❌ The message with ID `{message_id}` is not from Poketwo."

            return original_message, original_message.content, None
        except Exception as e:
            return None, None, f"❌ Error fetching message `{message_id}`: {str(e)}"

    async def _process_catch(self, ctx, catch_message: str, original_message: discord.Message = None, quiet: bool = False):
        """Parse + log a single catch message and (optionally) reply with the outcome.

        Returns one of: 'sent', 'skipped', 'invalid', 'error' (the last only set by caller on fetch failure).
        """
        catch_data = self.parse_poketwo_missingno_message(catch_message)
        if not catch_data:
            catch_data = self.parse_poketwo_milestone_message(catch_message)
            if catch_data:
                await self.send_to_milestone_starboard(ctx.guild, catch_data, original_message)
                if not quiet:
                    await ctx.reply(
                        f"✅ Milestone catch sent to milestone starboard!\n"
                        f"**Pokémon:** {catch_data['pokemon_name']} (Level {catch_data['level']}, {format_iv_display(catch_data['iv'])})\n"
                        f"**Milestone:** {catch_data['milestone_count']:,}th caught",
                        mention_author=False
                    )
                return 'sent'
        if not catch_data:
            catch_data = self.parse_poketwo_catch_message(catch_message)

        if not catch_data:
            if not quiet:
                await ctx.reply("❌ Invalid message format. Please make sure it's a proper Poketwo catch message.", mention_author=False)
            return 'invalid'

        if not self.should_log_catch(catch_data):
            if not quiet:
                gender_emoji = get_gender_emoji(catch_data.get('gender'))
                pokemon_display = f"{catch_data['pokemon_name']} {gender_emoji}" if gender_emoji else catch_data['pokemon_name']
                iv_display = format_iv_display(catch_data['iv'])
                await ctx.reply(
                    f"❌ This catch doesn't meet starboard criteria.\n"
                    f"**Pokémon:** {pokemon_display}\n"
                    f"**Level:** {catch_data['level']}\n"
                    f"**IV:** {iv_display}\n"
                    f"**Shiny:** {'Yes' if catch_data['is_shiny'] else 'No'}\n"
                    f"**Gigantamax:** {'Yes' if catch_data['is_gigantamax'] else 'No'}\n\n"
                    f"**Criteria:** Shiny, Gigantamax, MissingNo, or IV ≥{HIGH_IV_THRESHOLD}% or ≤{LOW_IV_THRESHOLD}%",
                    mention_author=False
                )
            return 'skipped'

        await self.send_to_starboard_channels(ctx.guild, catch_data, original_message)

        if not quiet:
            criteria_met = []
            if catch_data.get('message_type') == 'missingno':
                criteria_met.append("❓ MissingNo.")
                if catch_data['is_shiny']:
                    criteria_met.append("✨ Shiny")
            else:
                if catch_data['is_shiny']:
                    criteria_met.append("✨ Shiny")
                if catch_data['is_gigantamax']:
                    from config import Emojis
                    criteria_met.append(f"{Emojis.GIGANTAMAX} Gigantamax")
                iv = catch_data['iv']
                if iv not in ["Hidden", "???"]:
                    try:
                        iv_value = float(iv)
                        if iv_value >= HIGH_IV_THRESHOLD:
                            criteria_met.append(f"📈 High IV ({iv}%)")
                        elif iv_value <= LOW_IV_THRESHOLD:
                            criteria_met.append(f"📉 Low IV ({iv}%)")
                    except ValueError:
                        pass

            gender_emoji = get_gender_emoji(catch_data.get('gender'))
            pokemon_display = f"{catch_data['pokemon_name']} {gender_emoji}" if gender_emoji else catch_data['pokemon_name']
            iv_display = format_iv_display(catch_data['iv'])

            await ctx.reply(
                f"✅ Catch sent to starboard!\n"
                f"**Criteria met:** {', '.join(criteria_met)}\n"
                f"**Pokémon:** {pokemon_display} (Level {catch_data['level']}, {iv_display})",
                mention_author=False
            )
        return 'sent'

    @commands.command(name="catchcheck", aliases=["cc", "checkcatch"])
    @commands.has_permissions(administrator=True)
    async def catch_check_command(self, ctx, *, input_data: str = None):
        """Manually check a Poketwo catch message and send to starboard
        
        Usage:
            p!catchcheck (reply to a message)
            p!catchcheck <message_id>
            p!catchcheck <message_id1> <message_id2> <message_id3> ...
            p!catchcheck Congratulations <@123>! You caught...
        """
        # Reply-based invocation: single message only
        if input_data is None:
            if ctx.message.reference and ctx.message.reference.resolved:
                original_message = ctx.message.reference.resolved
                await self._process_catch(ctx, original_message.content, original_message)
            else:
                await ctx.reply(
                    "Please provide a Poketwo catch message, one or more message IDs, or reply to one.\n"
                    "Examples:\n"
                    "`p!catchcheck 123456789012345678` (message ID)\n"
                    "`p!catchcheck 123456789012345678 234567890123456789` (multiple message IDs)\n"
                    "Or reply to a message with just `p!catchcheck`",
                    mention_author=False
                )
            return

        tokens = input_data.split()

        # All whitespace-separated tokens are digits -> treat as one or more message IDs
        if tokens and all(t.isdigit() for t in tokens):
            message_ids = [int(t) for t in tokens]

            if len(message_ids) == 1:
                original_message, catch_message, error = await self._resolve_catch_message(ctx, message_ids[0])
                if error:
                    await ctx.reply(error, mention_author=False)
                    return
                await self._process_catch(ctx, catch_message, original_message)
                return

            # Multiple IDs: resolve all first, then send oldest -> newest
            counts = {'sent': 0, 'skipped': 0, 'invalid': 0, 'error': 0}
            errors = []
            resolved = []
            for message_id in message_ids:
                original_message, catch_message, error = await self._resolve_catch_message(ctx, message_id)
                if error:
                    counts['error'] += 1
                    errors.append(f"`{message_id}`: {error.lstrip('❌ ')}")
                    continue
                resolved.append((original_message, catch_message))

            # Oldest first, based on each message's actual timestamp
            resolved.sort(key=lambda pair: pair[0].created_at)

            for original_message, catch_message in resolved:
                outcome = await self._process_catch(ctx, catch_message, original_message, quiet=True)
                counts[outcome] += 1

            summary = (
                f"✅ Checked {len(message_ids)} message(s) (sent oldest → newest):\n"
                f"**Sent to starboard:** {counts['sent']}\n"
                f"**Didn't meet criteria:** {counts['skipped']}\n"
                f"**Invalid/not a catch:** {counts['invalid']}\n"
                f"**Errors:** {counts['error']}"
            )
            if errors:
                summary += "\n\n" + "\n".join(errors[:10])
                if len(errors) > 10:
                    summary += f"\n...and {len(errors) - 10} more."

            await ctx.reply(summary, mention_author=False)
            return

        # Otherwise treat input as a raw Poketwo catch message
        await self._process_catch(ctx, input_data)
    
    @catch_check_command.error
    async def catch_check_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to use this command.", mention_author=False)
        else:
            print(f"Unexpected error in catchcheck: {error}")
            await ctx.reply("❌ An unexpected error occurred. Please try again.", mention_author=False)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for Poketwo catch messages"""
        if message.author.id != POKETWO_USER_ID:
            return
        
        catch_data = None

        if "MissingNo." in message.content:
            catch_data = self.parse_poketwo_missingno_message(message.content)
        elif message.content.startswith("Congratulations"):
            # Check for milestone first (the milestone phrase lives in the same message)
            milestone_data = self.parse_poketwo_milestone_message(message.content)
            if milestone_data:
                await self.send_to_milestone_starboard(message.guild, milestone_data, message)
                # Still fall through so a shiny/high-IV milestone also hits the normal starboard
                catch_data = milestone_data
            else:
                catch_data = self.parse_poketwo_catch_message(message.content)

        if not catch_data:
            return

        if self.should_log_catch(catch_data):
            await self.send_to_starboard_channels(message.guild, catch_data, message)

            # Real, auto-detected shiny catch — bump the shiny count and
            # (if configured) rename the shiny-count channel. Deliberately
            # NOT called from catch_check_command, so p!catchcheck previews
            # never affect the count.
            if catch_data.get('is_shiny'):
                shiny_count_cog = self.bot.get_cog('ShinyCount')
                if shiny_count_cog:
                    await shiny_count_cog.record_shiny_catch(message.guild)

async def setup(bot):
    await bot.add_cog(StarboardCatch(bot))
