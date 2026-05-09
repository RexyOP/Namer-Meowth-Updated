"""Shiny hunt management commands"""
import discord
from discord import app_commands
from discord.ext import commands
from utils import (
    load_pokemon_data, 
    find_pokemon_by_name_flexible,
    get_pokemon_with_variants,
    normalize_pokemon_name
)
from config import EMBED_COLOR

class ShinyHunt(commands.Cog):
    """Shiny hunt management commands"""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()

    @property
    def db(self):
        """Get database from bot"""
        return self.bot.db

    def get_base_dex_number(self, pokemon_name: str) -> int:
        """Get the base dex number for a Pokemon (ignoring forms)"""
        pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
        if not pokemon:
            return None

        return pokemon.get('dex_number')

    def has_variants(self, pokemon_name: str) -> bool:
        """Check if a Pokemon has multiple variants/forms"""
        variants = get_pokemon_with_variants(pokemon_name, self.pokemon_data)
        return variants and len(variants) > 1

    def get_base_name_from_variant(self, pokemon_name: str) -> str:
        """Get the base Pokemon name, removing form/variant prefixes"""
        pokemon = find_pokemon_by_name_flexible(pokemon_name, self.pokemon_data)
        if not pokemon:
            return pokemon_name

        # If it's a variant, return what it's a variant of
        if pokemon.get('is_variant') and pokemon.get('variant_of'):
            return pokemon['variant_of']

        # Otherwise return the Pokemon's name
        return pokemon.get('name', pokemon_name)

    @commands.command(name="sh", aliases=["hunt", "shinyhunt"])
    async def shiny_hunt_command(self, ctx, *, args: str = None):
        """Manage shiny hunt

        Examples:
            p!sh                                    (check current hunt)
            p!sh Meowth                            (hunt only base Meowth)
            p!sh Meowth all                        (hunt all Meowth variants)
            p!sh Alolan Meowth, Galarian Meowth   (hunt specific variants)
            p!sh clear                              (clear hunt)
        """
        if not args:
            # Check current hunt
            current_hunts = await self.db.get_user_shiny_hunt(ctx.author.id, ctx.guild.id)

            if current_hunts:
                # current_hunts should be a list now
                if isinstance(current_hunts, str):
                    current_hunts = [current_hunts]

                hunt_list = ", ".join(f"**{hunt}**" for hunt in current_hunts)
                await ctx.reply(f"You are currently hunting: {hunt_list}", mention_author=False)
            else:
                await ctx.reply("You are not hunting anything", mention_author=False)
            return

        args_lower = args.strip().lower()

        # Clear hunt
        if args_lower in ["clear", "none", "stop"]:
            cleared = await self.db.clear_shiny_hunt(ctx.author.id, ctx.guild.id)

            if cleared:
                await ctx.reply("✅ Shiny hunt cleared successfully", mention_author=False)
            else:
                await ctx.reply("You are not hunting anything", mention_author=False)
            return

        # Parse Pokemon names
        pokemon_to_hunt = []
        using_all = False

        # Check if using "all" keyword (support both "furfrou all" and "all furfrou")
        if args_lower.endswith(" all") or args_lower.startswith("all "):
            using_all = True
            if args_lower.startswith("all "):
                base_name = args[4:].strip()
            else:
                base_name = args[:-4].strip()
            variants = get_pokemon_with_variants(base_name, self.pokemon_data)

            if not variants:
                await ctx.reply(f"❌ Invalid Pokemon name: {base_name}", mention_author=False)
                return

            pokemon_to_hunt = variants

        else:
            # Split by comma for multiple Pokemon
            pokemon_names = [name.strip() for name in args.split(",") if name.strip()]

            for name in pokemon_names:
                pokemon = find_pokemon_by_name_flexible(name, self.pokemon_data)

                if not pokemon or not pokemon.get('name'):
                    await ctx.reply(f"❌ Invalid Pokemon name: {name}", mention_author=False)
                    return

                pokemon_to_hunt.append(pokemon['name'])

        if not pokemon_to_hunt:
            await ctx.reply("Please provide a Pokemon name to hunt, or use 'clear' to stop hunting.", mention_author=False)
            return

        # Check if all Pokemon have the same dex number
        dex_numbers = set()
        for poke_name in pokemon_to_hunt:
            dex = self.get_base_dex_number(poke_name)
            if dex is None:
                await ctx.reply(f"❌ Could not determine dex number for: {poke_name}", mention_author=False)
                return
            dex_numbers.add(dex)

        if len(dex_numbers) > 1:
            await ctx.reply("❌ You can only hunt Pokemon with the same Pokédex number! All variants must be from the same base Pokemon.", mention_author=False)
            return

        # Warning for Pokemon with variants when not using "all"
        if len(pokemon_to_hunt) == 1 and not using_all:
            hunted_pokemon = pokemon_to_hunt[0]
            if self.has_variants(hunted_pokemon):
                # Get the base name for the warning message
                base_name = self.get_base_name_from_variant(hunted_pokemon)

                embed = discord.Embed(
                    title="⚠️ Variant Warning",
                    description=f"**{hunted_pokemon}** has multiple forms/variants!\n\n"
                                f"You will **only** be pinged for **{hunted_pokemon}**, not its other forms.\n\n"
                                f"To hunt all variants, use:\n"
                                f"`p!sh {base_name} all`\n\n"
                                f"Or specify the exact variants you want:\n"
                                f"`p!sh Alolan {base_name}, Galarian {base_name}` <- just an example",
                    color=0xFFA500  # Orange color for warning
                )
                await ctx.reply(embed=embed, mention_author=False)

        # Set the shiny hunt (now supporting multiple variants)
        await self.db.set_shiny_hunt(ctx.author.id, ctx.guild.id, pokemon_to_hunt)

        # Format response
        if len(pokemon_to_hunt) == 1:
            await ctx.reply(f"✅ Now hunting: **{pokemon_to_hunt[0]}**", mention_author=False)
        else:
            hunt_list = ", ".join(f"**{p}**" for p in pokemon_to_hunt)
            await ctx.reply(f"✅ Now hunting **{len(pokemon_to_hunt)}** variants: {hunt_list}", mention_author=False)

    # ------------------------------------------------------------------
    # Slash Commands  (registered automatically with the cog)
    # ------------------------------------------------------------------
    @app_commands.command(name="sh", description="Manage your shiny hunt")
    @app_commands.describe(pokemon="Pokémon to hunt, e.g. 'Furfrou all'. Leave blank to check current hunt, or type 'clear' to stop.")
    async def slash_shiny_hunt(self, interaction: discord.Interaction, pokemon: str = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.shiny_hunt_command(ctx, args=pokemon)




async def setup(bot):
    await bot.add_cog(ShinyHunt(bot))
