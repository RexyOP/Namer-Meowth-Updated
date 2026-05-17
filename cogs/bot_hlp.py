"""Help commands"""
import discord
from discord import app_commands
from discord.ext import commands
from config import EMBED_COLOR, BOT_PREFIX

class Help(commands.Cog):
    """Help and information commands"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["h"])
    async def help_command(self, ctx, category: str = None):
        """Show help information

        Categories: collection, category, hunt, pings, settings, prediction, starboard, helpful, incense, captcha, reserve, channels, listgen, owner, all
        """
        prefix = BOT_PREFIX[0]
        is_owner = await self.bot.is_owner(ctx.author)

        if not category:
            embed = discord.Embed(
                title="📚 Poketwo Helper Bot — Help",
                description=f"Use `{prefix}help <category>` for details  •  `{prefix}help all` to see everything",
                color=EMBED_COLOR,
            )
            embed.add_field(name="📦 Collection",       value=f"`{prefix}help collection` — Manage your Pokémon collection",              inline=False)
            embed.add_field(name="🗂️ Category",         value=f"`{prefix}help category` — Bulk collection management with categories",    inline=False)
            embed.add_field(name="✨ Shiny Hunt",        value=f"`{prefix}help hunt` — Set up shiny hunting",                              inline=False)
            embed.add_field(name="🔷 Type & Region",    value=f"`{prefix}help pings` — Get pinged by Pokémon type or region",             inline=False)
            embed.add_field(name="⚙️ Settings",         value=f"`{prefix}help settings` — Toggle features and AFK",                       inline=False)
            embed.add_field(name="🎭 Roles",            value=f"`{prefix}help roles` — Configure rare / regional ping roles",              inline=False)
            embed.add_field(name="📺 Channels",         value=f"`{prefix}help channels` — Configure all bot channels (starboard, captcha…)",inline=False)
            embed.add_field(name="🔮 Prediction",       value=f"`{prefix}help prediction` — Manual Pokémon prediction",                   inline=False)
            embed.add_field(name="🔍 Helpful",          value=f"`{prefix}help helpful` — Spawn rates, shiny rates & hint solver",          inline=False)
            embed.add_field(name="🔥 Incense",          value=f"`{prefix}help incense` — Manage Poketwo incense sessions",                 inline=False)
            embed.add_field(name="🔐 Captcha",          value=f"`{prefix}help captcha` — Captcha alert information",                       inline=False)
            embed.add_field(name="💾 Reserve",          value=f"`{prefix}help reserve` — Server-specific Pokémon reservation system",      inline=False)
            embed.add_field(name="📝 List Builder",      value=f"`{prefix}help listgen` — Build and export Pokémon name lists",              inline=False)
            if is_owner:
                embed.add_field(name="👑 Owner",        value=f"`{prefix}help owner` — Bot owner commands",                               inline=False)
            embed.add_field(name="ℹ️ About",            value=f"`{prefix}about` — Bot information and stats",                             inline=False)
            embed.add_field(name="🏓 Ping",             value=f"`{prefix}ping` — Check bot latency",                                      inline=False)
            embed.set_footer(text=f"Bot Prefix: {', '.join(BOT_PREFIX)}")
            await ctx.reply(embed=embed, mention_author=False)
            return

        category = category.lower()

        # ── Collection ────────────────────────────────────────────────
        if category in ["collection", "cl", "collect"]:
            embed = discord.Embed(
                title="📦 Collection Commands",
                description="Manage your Pokémon collection for this server. Get pinged when Pokémon you collect spawn!",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}cl add <pokemon>`",
                value=(
                    "Add Pokémon to your collection\n"
                    f"**Aliases:** `{prefix}collection add`\n"
                    f"• `{prefix}cl add Pikachu`\n"
                    f"• `{prefix}cl add Pikachu, Charizard, Mewtwo`\n"
                    f"• `{prefix}cl add Furfrou all` (adds all Furfrou variants)"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}cl remove <pokemon | --sr <rate> | --user <@user>>`",
                value=(
                    "Remove Pokémon from your collection\n"
                    f"• `{prefix}cl remove Pikachu`\n"
                    f"• `{prefix}cl remove --sr 899` (by spawn rate)\n"
                    f"• `{prefix}cl remove --user @someone`"
                ),
                inline=False,
            )
            embed.add_field(name=f"`{prefix}cl list`",  value="View your collection (paginated)",     inline=False)
            embed.add_field(name=f"`{prefix}cl raw`",   value="View as raw text grouped by SR tier",  inline=False)
            embed.add_field(name=f"`{prefix}cl clear`", value="⚠️ Clear your entire collection",      inline=False)
            embed.add_field(
                name="💡 How It Works",
                value=(
                    "• When a Pokémon you collect spawns, you get pinged\n"
                    "• Use cl add `Furfrou all` to add every Furfrou variant explicitly as adding only furfrou pings for furfrou only"
                ),
                inline=False,
            )

        # ── Category ──────────────────────────────────────────────────
        elif category in ["category", "cat", "categories"]:
            embed = discord.Embed(
                title="🗂️ Category Commands",
                description="Bulk collection management with categories. Admins create categories, users subscribe to them.",
                color=EMBED_COLOR,
            )
            embed.add_field(name=f"`{prefix}cat add <categories>`",    value="Add Pokémon from a category to your collection",  inline=False)
            embed.add_field(name=f"`{prefix}cat remove <categories>`", value="Remove Pokémon from a category from your collection", inline=False)
            embed.add_field(name=f"`{prefix}cat list`",                value="View all server categories with Pokémon counts",  inline=False)
            embed.add_field(name=f"`{prefix}cat info <name>`",         value="View Pokémon in a specific category (paginated)", inline=False)
            embed.add_field(
                name="📝 Admin Commands",
                value=(
                    f"`{prefix}cat create <name> <pokemon>` — Create a category\n"
                    f"`{prefix}cat edit <name> <pokemon>` — Replace all Pokémon in a category\n"
                    f"`{prefix}cat addpokemon <name> <pokemon>` — Add to an existing category\n"
                    f"`{prefix}cat removepokemon <name> <pokemon>` — Remove from a category\n"
                    f"`{prefix}cat defaults` — Add built-in category from default list\n"
                    f"`{prefix}cat delete <name>` — Delete a category"
                ),
                inline=False,
            )

        # ── Shiny Hunt ────────────────────────────────────────────────
        elif category in ["hunt", "sh", "shiny"]:
            embed = discord.Embed(
                title="✨ Shiny Hunt Commands",
                description="Get pinged when your hunt target Pokémon spawns!",
                color=EMBED_COLOR,
            )
            embed.add_field(name=f"`{prefix}sh`",               value="Check your current shiny hunt",               inline=False)
            embed.add_field(name=f"`{prefix}sh <pokemon>`",     value="Start hunting a Pokémon (`{prefix}sh Pikachu`)", inline=False)
            embed.add_field(name=f"`{prefix}sh clear`",         value="Stop hunting (also accepts `none` / `stop`)", inline=False)
            embed.add_field(name="💡 Note", value="You can hunt one or more Pokémon (same dex) at a time per server.", inline=False)

        # ── Settings ──────────────────────────────────────────────────
        elif category in ["settings", "setting", "config", "afk"]:
            embed = discord.Embed(
                title="⚙️ Settings Commands",
                description="Configure bot features for your server and personal preferences.",
                color=EMBED_COLOR,
            )
            embed.add_field(name="👤 User Settings", value="", inline=False)
            embed.add_field(
                name=f"`{prefix}afk`",
                value=(
                    "Toggle pings via interactive buttons — 4 toggles:\n"
                    f"**Aliases:** `{prefix}away`\n"
                    "🟢 Green = Pings ON  •  🔴 Red = Pings OFF\n"
                    "• **ShinyHunt** • **Collection** • **TypePings** • **RegionPings**\n"
                    "*AFK is global across all servers*"
                ),
                inline=False,
            )
            embed.add_field(name="🛠️ Server Settings", value="", inline=False)
            embed.add_field(
                name=f"`{prefix}server-settings`",
                value=(
                    "View all current server settings\n"
                    f"**Aliases:** `{prefix}ss`, `{prefix}ssettings`\n"
                    "Shows: Roles, feature toggles. Use `{prefix}channel settings` for channels."
                ),
                inline=False,
            )
            embed.add_field(name="📝 Admin Commands", value="", inline=False)
            embed.add_field(
                name=f"`{prefix}toggle <feature>`",
                value=(
                    "Toggle server features on/off\n"
                    f"• `{prefix}toggle best_name` — shortest name line in predictions\n"
                    f"• `{prefix}toggle only_pings` — only send predictions when someone has pings\n"
                    f"• `{prefix}toggle catch_command` — catch command line in predictions\n"
                    f"• `{prefix}toggle hint_solver` — automatic hint solving\n"
                    f"Also accessible via `{prefix}only-pings true/false`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}clear-pings [@user | user_id]`",
                value=(
                    "Clear all ping data for this server\n"
                    f"**Aliases:** `{prefix}clearpings`, `{prefix}resetpings`\n"
                    "• No argument → clears **all users**\n"
                    "• With @user → clears only that user\n"
                    "⚠️ Requires server owner, admin, or bot owner"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}force-afk @user <type> <on|off>`",
                value=(
                    "Forcefully set a user's AFK state on any ping type  **(Admin only)**\n"
                    f"**Aliases:** `{prefix}forceafk`, `{prefix}fafk`\n"
                    f"• `{prefix}force-afk @user all on` — AFK on all 4 types at once\n"
                    f"• `{prefix}force-afk @user all off` — remove AFK on all 4 types\n"
                    f"• `{prefix}force-afk @user collection on`\n"
                    f"• `{prefix}force-afk @user shinyhunt off`\n"
                    f"• `{prefix}force-afk @user typepings on`\n"
                    f"• `{prefix}force-afk @user regionpings off`\n"
                    "Types: `collection` `shinyhunt` `typepings` `regionpings` `all`\n"
                    "*User can still override with their own `p!afk`*"
                ),
                inline=False,
            )
            embed.add_field(
                name="📺 Channel & Role Config",
                value=(
                    f"See `{prefix}help channels` for channel configuration\n"
                    f"See `{prefix}help roles` for role configuration"
                ),
                inline=False,
            )

        # ── Roles ─────────────────────────────────────────────────────
        elif category in ["roles", "role"]:
            embed = discord.Embed(
                title="🎭 Role Commands",
                description=(
                    "Configure ping roles for rare and regional Pokémon, and manage which roles can use incense and reserve commands.\n"
                    f"`{prefix}role` shows **all four** role types at a glance."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}role`",
                value=(
                    "Show all configured roles — Rare, Regional, Incense Allowed, Reserve Allowed\n"
                    f"**Aliases:** `{prefix}roles`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}role rare [@role]`  *(Admin)*",
                value=(
                    "Set role to ping for rare Pokémon (Legendary / Mythical / Ultra Beast)\n"
                    f"**Aliases:** `{prefix}role r`\n"
                    f"• `{prefix}role rare @Rare Hunters` — set the role\n"
                    f"• `{prefix}role rare` (no args) — clear / disable"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}role regional [@role]`  *(Admin)*",
                value=(
                    "Set role to ping for regional Pokémon\n"
                    f"**Aliases:** `{prefix}role reg`\n"
                    f"• `{prefix}role regional @Regionals` — set the role\n"
                    f"• `{prefix}role regional` (no args) — clear / disable"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"🔥 `{prefix}inc allowedroles`  *(Manage Server)*",
                value=(
                    "Manage which roles can use incense pause/resume commands\n"
                    f"• `{prefix}inc allowedroles` / `{prefix}inc ar` — list current roles\n"
                    f"• `{prefix}inc allowedroles add @Role` — add a role\n"
                    f"• `{prefix}inc allowedroles remove @Role` — remove a role\n"
                    f"• `{prefix}inc allowedroles clear` — remove all"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"📌 `{prefix}r allowedroles`  *(Admin)*",
                value=(
                    "Manage which roles can use reserve commands\n"
                    f"• `{prefix}r allowedroles` / `{prefix}r ar` — list current roles\n"
                    f"• `{prefix}r allowedroles add @Role` — add a role\n"
                    f"• `{prefix}r allowedroles remove @Role` — remove a role\n"
                    f"• `{prefix}r allowedroles clear` — remove all"
                ),
                inline=False,
            )

        # ── Channels ──────────────────────────────────────────────────
        elif category in ["channels", "channel", "ch"]:
            embed = discord.Embed(
                title="📺 Channel Configuration",
                description=(
                    f"All channel settings live under the `{prefix}channel` group.\n"
                    f"Use `{prefix}channel settings` to see every configured channel at a glance."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}channel settings`",
                value="View all configured channels (captcha, starboard, etc.)",
                inline=False,
            )
            embed.add_field(
                name=f"⭐ `{prefix}channel starboard` — Starboard  *(Admin)*",
                value=(
                    f"`{prefix}channel starboard settings` — view starboard channels\n"
                    f"`{prefix}channel starboard all [#ch | none]` — set all at once\n"
                    f"`{prefix}channel starboard catch/egg/unbox [#ch | none]`\n"
                    f"`{prefix}channel starboard shiny/gigantamax/highiv/lowiv [#ch | none]`\n"
                    f"`{prefix}channel starboard missingno/milestone [#ch | none]`\n"
                    "Use `none` instead of `#channel` to clear."
                ),
                inline=False,
            )
            embed.add_field(
                name=f"🔐 `{prefix}channel captcha [#ch]` — Captcha Alerts  *(Admin)*",
                value=(
                    f"• `{prefix}channel captcha #alerts` — set captcha alert channel\n"
                    f"• `{prefix}channel captcha` (no args) — clear / disable\n"
                    "Users are pinged here when Pokétwo asks them to verify."
                ),
                inline=False,
            )
            embed.add_field(
                name=f"👑 `{prefix}channel lowpred #ch` / `{prefix}channel secondary #ch`  *(Owner)*",
                value=(
                    "Set global channels for low-confidence predictions and secondary model logs."
                ),
                inline=False,
            )
            embed.add_field(
                name="📋 What Gets Logged to Starboard?",
                value=(
                    "• Shiny / Gigantamax / MissingNo catches, hatches, unboxes\n"
                    "• High IV (≥90%) or Low IV (≤10%)\n"
                    "• Milestone catches (100 / 1K / 10K / 100K of a single species)\n"
                    "A Pokémon meeting multiple criteria is sent to multiple channels."
                ),
                inline=False,
            )

        # ── Type & Region Pings ───────────────────────────────────────
        elif category in ["pings", "ping", "typepings", "regionpings", "tp", "rp"]:
            embed = discord.Embed(
                title="🔷 Type & Region Ping Commands",
                description="Get pinged whenever a Pokémon of a specific type or region spawns!",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}tp`",
                value=(
                    "Open the interactive **Type Pings** menu with toggle buttons\n"
                    f"**Aliases:** `{prefix}typepings`\n"
                    "🟢 Green = enabled  •  ⚫ Grey = disabled\n"
                    "All 18 types available."
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}tp <types>`",
                value=(
                    "Directly toggle one or more types\n"
                    f"• `{prefix}tp bug` • `{prefix}tp bug grass fire`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}rp`",
                value=(
                    "Open the interactive **Region Pings** menu\n"
                    f"**Aliases:** `{prefix}regionpings`\n"
                    "All 9 regions: Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Paldea"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}rp <regions>`",
                value=f"`{prefix}rp kanto` • `{prefix}rp kanto johto hoenn`",
                inline=False,
            )
            embed.add_field(
                name="🔕 AFK for Type/Region",
                value=f"Use `{prefix}afk` → **TypePings** / **RegionPings** buttons",
                inline=False,
            )
            embed.add_field(
                name="💡 How It Works",
                value=(
                    "• Settings are per-server\n"
                    "• Bot checks types/region on every spawn and mentions you in the prediction"
                ),
                inline=False,
            )

        # ── Prediction ────────────────────────────────────────────────
        elif category in ["prediction", "predict", "pred"]:
            embed = discord.Embed(
                title="🔮 Prediction Commands",
                description="Manually predict Pokémon from images or view auto-detection info",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}predict <image_url>`",
                value=f"**Aliases:** `{prefix}pred`, `{prefix}p`",
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}predict` (reply to message)",
                value="Reply to a message with an image to predict it",
                inline=False,
            )
            embed.add_field(
                name="🤖 Auto-Detection",
                value=(
                    "The bot automatically predicts Poketwo spawns and shows collectors, "
                    "hunters, type/region pings, and role pings."
                ),
                inline=False,
            )
            embed.add_field(
                name="📊 Dual Model System",
                value=(
                    "• **Primary model** (224×224) — runs on every spawn\n"
                    "• **Secondary model** — runs when primary confidence < 94%\n"
                    "• Primary ≥ 94% → primary used; Secondary ≥ 90% → secondary used; else primary as fallback"
                ),
                inline=False,
            )

        # ── Starboard ─────────────────────────────────────────────────
        elif category in ["starboard", "star", "log"]:
            embed = discord.Embed(
                title="⭐ Starboard",
                description=(
                    f"Starboard channels are configured under `{prefix}channel starboard`.\n"
                    f"See `{prefix}help channels` for the full reference."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="Quick Reference",
                value=(
                    f"`{prefix}channel starboard settings` — view current starboard channels\n"
                    f"`{prefix}channel starboard all [#ch | none]` — set all at once\n"
                    f"`{prefix}channel starboard catch/egg/unbox [#ch | none]`\n"
                    f"`{prefix}channel starboard shiny/gigantamax/highiv/lowiv [#ch | none]`\n"
                    f"`{prefix}channel starboard missingno/milestone [#ch | none]`"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔍 Manual Checking  *(Admin)*",
                value=(
                    f"`{prefix}catchcheck` • `{prefix}eggcheck` • `{prefix}unboxcheck`\n"
                    "Reply to a message or provide a message ID."
                ),
                inline=False,
            )
            embed.add_field(
                name="📋 What Gets Logged?",
                value=(
                    "Shiny / Gigantamax / High IV / Low IV / MissingNo / Milestone catches, hatches, unboxes.\n"
                    "A Pokémon meeting multiple criteria is sent to multiple channels."
                ),
                inline=False,
            )

        # ── Helpful ───────────────────────────────────────────────────
        elif category in ["helpful", "util", "utils", "tools"]:
            embed = discord.Embed(
                title="🔍 Helpful Commands",
                description="Useful utility commands for Pokétwo players",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}spawnrate <pokemon>` / `{prefix}sr <pokemon>`",
                value="Show the wild spawn rate for a Pokémon",
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}shinyrate [chain] [target%]` / `{prefix}shr`",
                value=(
                    "Per-encounter shiny rate at a given chain, or chain needed for a target %\n"
                    f"• `{prefix}shr 50` — rates at chain 50\n"
                    f"• `{prefix}shr 89%` — chain needed for 89%\n"
                    f"• `{prefix}shr 50 89%` — both at once"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}timedifference` / `{prefix}timediff` / `{prefix}td`",
                value=(
                    "Find the time difference between two messages in seconds and milliseconds\n"
                    f"• Reply to a message + `{prefix}td` — compares it with the message above it\n"
                    f"• `{prefix}td <id>` — compares that message with the one above it\n"
                    f"• `{prefix}td <id1> <id2>` — compares two messages directly\n"
                    "Also available as `/timedifference`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}date` / `{prefix}caught` / `{prefix}catchdate`",
                value=(
                    "Show when a Pokémon was caught from its Pokétwo ObjectID\n"
                    f"• Reply to a Pokétwo `p!info` embed + `{prefix}date` — reads ObjectID from footer automatically\n"
                    f"• `{prefix}date <objectid>` — provide the ObjectID directly\n"
                    "Also available as `/date` and the **Get Caught Date** right-click context menu"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}extractids` / `{prefix}extract` / `{prefix}eids`",
                value=(
                    "Extract all Pokémon / listing IDs from a Pokétwo embed, space-separated\n"
                    f"• Reply to a Pokétwo `p!pokemon` or marketplace embed + `{prefix}extractids`\n"
                    f"• `{prefix}extractids <message_id>` — provide the message ID directly\n"
                    "Also available as `/extractids` and the **Extract IDs** right-click context menu"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔎 Hint Solver (Automatic)",
                value=(
                    "When Pokétwo sends a hint the bot automatically replies with matching Pokémon name(s).\n"
                    "Supports all languages. No command needed."
                ),
                inline=False,
            )

        # ── Owner ─────────────────────────────────────────────────────
        elif category in ["owner", "admin", "botowner"]:
            if not is_owner:
                await ctx.reply("❌ This category is only available to the bot owner.", mention_author=False)
                return

            embed = discord.Embed(
                title="👑 Owner Commands",
                description="Bot owner only commands for global settings",
                color=0xFFD700,
            )
            embed.add_field(
                name=f"`{prefix}model load` / `{prefix}model unload` / `{prefix}model reload`",
                value=(
                    "Load, unload, or force-re-download the AI prediction models.\n"
                    f"**Aliases:** `{prefix}lm`, `{prefix}um`, `{prefix}rm`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}model status`",
                value="Show model load state, RAM usage, and prediction stats",
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}reloadsr`",
                value="Force-reload spawn rate data from the remote CSV",
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}channel lowpred #channel`",
                value=(
                    "Set global channel for low-confidence predictions (< 90%)\n"
                    f"**Aliases:** `{prefix}channel low-prediction`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}channel secondary #channel`",
                value=(
                    "Set global channel for secondary model logs\n"
                    f"**Aliases:** `{prefix}channel secondary-model`"
                ),
                inline=False,
            )
            embed.add_field(
                name=f"`{prefix}channel global-starboard catch/egg/unbox #channel`",
                value="Set global starboard channels (across all servers)",
                inline=False,
            )

        # ── Incense ───────────────────────────────────────────────────
        elif category in ["incense", "inc", "incenses"]:
            embed = discord.Embed(
                title="🔥 Incense Commands",
                description=(
                    "Automatically restricts Poketwo the moment an Incense is purchased "
                    "in a monitored category channel — so your spawns stay exclusive."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="⚙️ Setup  *(Manage Server)*",
                value=(
                    f"`{prefix}inc toggle` — Enable/disable the incense watcher\n"
                    f"`{prefix}inc cat add SPAWN1 SPAWN2` — Add categories to monitor\n"
                    f"`{prefix}inc cat remove <name>` — Stop monitoring a category\n"
                    f"`{prefix}inc cat list` — View monitored categories & channel counts"
                ),
                inline=False,
            )
            embed.add_field(
                name="⏸️ Pause  *(Allowed Role required)*",
                value=(
                    f"`{prefix}inc pause` / `{prefix}inc p` — Pause **this** channel\n"
                    f"`{prefix}inc pause all` — Pause ALL monitored categories"
                ),
                inline=False,
            )
            embed.add_field(
                name="▶️ Resume  *(Allowed Role required)*",
                value=(
                    f"`{prefix}inc resume` / `{prefix}inc r` — Resume **this** channel\n"
                    f"`{prefix}inc resume all` — Resume ALL paused channels"
                ),
                inline=False,
            )
            embed.add_field(name="📋 Status", value=f"`{prefix}inc list` — View paused and active channels", inline=False)
            embed.add_field(
                name="🔐 Allowed Roles  *(Manage Server)*",
                value=(
                    f"`{prefix}inc allowedroles` — List allowed roles\n"
                    f"`{prefix}inc allowedroles add @Role` — Add a role\n"
                    f"`{prefix}inc allowedroles remove @Role` — Remove a role\n"
                    f"`{prefix}inc allowedroles clear` — Remove all"
                ),
                inline=False,
            )
            embed.add_field(
                name="🤖 How It Works",
                value=(
                    "• Poketwo sends `You purchased an Incense for X shards!`\n"
                    "• Bot instantly restricts Poketwo in that specific channel only\n"
                    f"• Use `{prefix}inc help` for a quick in-chat reference"
                ),
                inline=False,
            )

        # ── Captcha ───────────────────────────────────────────────────
        elif category in ["captcha", "cap", "verify"]:
            embed = discord.Embed(
                title="🔐 Captcha Alerts",
                description=(
                    "Automatically alerts users in a designated channel when Pokétwo asks them to verify. "
                    "Disabled per-server until a captcha channel is configured."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name=f"`{prefix}channel captcha #channel`  *(Admin)*",
                value=(
                    "Set the channel where captcha alerts will be sent\n"
                    f"• `{prefix}channel captcha #alerts` — set alert channel\n"
                    f"• `{prefix}channel captcha` (no args) — clear / disable"
                ),
                inline=False,
            )
            embed.add_field(
                name="🤖 How It Works",
                value=(
                    "• Bot watches every channel for Pokétwo's captcha message\n"
                    "• When detected, pings the flagged user in the alert channel\n"
                    "• Alert includes a **Verify** button linking to their captcha URL\n"
                    "• **5-minute cooldown** per user — won't re-ping within 5 minutes"
                ),
                inline=False,
            )

        # ── Reserve ───────────────────────────────────────────────────
        elif category in ["reserve", "res", "r"]:
            embed = discord.Embed(
                title="💾 Reserve Commands",
                description="Server-specific Pokémon reservation system.",
                color=EMBED_COLOR,
            )
            embed.add_field(name="📋 View",     value=f"`{prefix}r list` • `{prefix}r list @user`",                                 inline=False)
            embed.add_field(name="➕ Remove",   value=f"`{prefix}r remove p <pokemon>` • `{prefix}r remove cat <cat>` • `{prefix}r clear`", inline=False)
            embed.add_field(
                name="🔐 Admin: Add",
                value=f"`{prefix}r add p @user <pokemon>` • `{prefix}r add cat @user <cat>`",
                inline=False,
            )
            embed.add_field(
                name="🔐 Admin: Remove / Clear",
                value=f"`{prefix}r remove p @user <pokemon>` • `{prefix}r clear @user` • `{prefix}r clear --all`",
                inline=False,
            )
            embed.add_field(
                name="🛠️ Admin: Allowed Roles",
                value=f"`{prefix}r allowedroles` • `{prefix}r allowedroles add @role` • `{prefix}r allowedroles remove @role`",
                inline=False,
            )

        # ── All commands ──────────────────────────────────────────────
        elif category in ["listgen", "lg", "listbuilder", "list", "listbuilder"]:
            embed = discord.Embed(
                title="📝 List Builder",
                description=(
                    "Build, filter, and export Pokémon name lists with a button-driven UI.\n"
                    f"Start with `{prefix}listgen` (or `{prefix}lg` / `{prefix}listbuilder`).\n"
                    f"Reply to a message containing Pokémon names to extract them automatically — "
                    "the bot will watch that message for edits for 2 minutes."
                ),
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="🚀 Command",
                value=(
                    f"`{prefix}listgen` — open an empty list builder\n"
                    f"`{prefix}listgen` *(as a reply)* — extract names from the replied message"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔘 Buttons",
                value=(
                    "**➕ Add** — open a modal with up to 3 filter inputs\n"
                    "**➖ Remove** — remove names matching a filter\n"
                    "**🗑 Clear** — wipe the entire list\n"
                    "**📋 Format & Display** — choose output format, case, language, and sort order\n"
                    "**⚙️ Advanced Options** — set enclosure, find & replace, toggle event Pokémon\n"
                    "**📤 Send** — post the finished list (auto-paginates if too long)"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔍 Filter Syntax",
                value=(
                    f"`--type <type>` / `--t <type>` — filter by type\n"
                    f"`--region <region>` / `--r <region>` — filter by region\n"
                    f"`--sr <denom>` / `--spawnrate <denom>` — filter by spawn-rate denominator *(e.g. `--sr 225`)*\n"
                    f"`--stage <1|2|3>` — filter by evolution stage\n"
                    f"`--name <name>` / `--n <name>` — exact name match; prefix `all` for all forms *(e.g. `--n all furfrou`)*\n"
                    f"`--catchable` — only Pokémon with a spawn-rate entry\n"
                    f"`--notcatchable` — only Pokémon **without** a spawn-rate entry\n"
                    "Filters in a single cell are combined with AND logic. "
                    "Multiple modal cells are combined with OR logic."
                ),
                inline=False,
            )
            embed.add_field(
                name="📋 Format Options",
                value=(
                    "**Comma separated** — `Bulbasaur, Ivysaur, Venusaur`\n"
                    "**--n format** — `Bulbasaur --n Ivysaur --n Venusaur`\n"
                    "**--evo format** — `Bulbasaur --evo Ivysaur --evo Venusaur`\n"
                    "**One per line** — one name per line (supports bullet prefix)"
                ),
                inline=False,
            )
            embed.add_field(
                name="🌍 Language Options",
                value="English 🇬🇧 • German 🇩🇪 • French 🇫🇷 • Japanese 🇯🇵 • Best Name ⭐",
                inline=False,
            )
            embed.add_field(
                name="⏱️ Timeout",
                value="The UI closes automatically after **2 minutes of inactivity**.",
                inline=False,
            )

        elif category in ["all", "commands"]:
            embed = discord.Embed(
                title="📚 All Commands",
                description="Complete list of all bot commands",
                color=EMBED_COLOR,
            )
            embed.add_field(
                name="📦 Collection",
                value=f"`{prefix}cl add` • `{prefix}cl remove` • `{prefix}cl list` • `{prefix}cl raw` • `{prefix}cl clear`",
                inline=False,
            )
            embed.add_field(
                name="🗂️ Category",
                value=(
                    f"`{prefix}cat add/remove/list/info`\n"
                    f"**Admin:** `{prefix}cat create/edit/delete/addpokemon/removepokemon/defaults`"
                ),
                inline=False,
            )
            embed.add_field(name="✨ Shiny Hunt",     value=f"`{prefix}sh` • `{prefix}sh <pokemon>` • `{prefix}sh clear`",                     inline=False)
            embed.add_field(name="🔷 Type & Region",  value=f"`{prefix}tp` • `{prefix}tp <types>` • `{prefix}rp` • `{prefix}rp <regions>`",    inline=False)
            embed.add_field(
                name="⚙️ Settings",
                value=(
                    f"`{prefix}afk` • `{prefix}server-settings` • `{prefix}clear-pings [@user]`\n"
                    f"**Admin:** `{prefix}toggle <feature>` • `{prefix}only-pings` • `{prefix}force-afk @user <type> <on|off>`"
                ),
                inline=False,
            )
            embed.add_field(
                name="🎭 Roles  *(Admin)*",
                value=(
                    f"`{prefix}role` — view all configured roles\n"
                    f"`{prefix}role rare [@role]` • `{prefix}role regional [@role]`\n"
                    f"`{prefix}inc allowedroles add/remove/clear @Role` • `{prefix}r allowedroles add/remove/clear @Role`"
                ),
                inline=False,
            )
            embed.add_field(
                name="📺 Channels  *(Admin / Owner)*",
                value=(
                    f"`{prefix}channel settings`\n"
                    f"`{prefix}channel starboard all/catch/egg/unbox/shiny/gigantamax/highiv/lowiv/missingno/milestone [#ch | none]`\n"
                    f"`{prefix}channel captcha [#ch]`\n"
                    f"**Owner:** `{prefix}channel lowpred #ch` • `{prefix}channel secondary #ch`\n"
                    f"**Owner:** `{prefix}channel global-starboard catch/egg/unbox #ch`"
                ),
                inline=False,
            )
            embed.add_field(name="🔮 Prediction",     value=f"`{prefix}predict`",                                                              inline=False)
            embed.add_field(
                name="🔍 Helpful",
                value=(
                    f"`{prefix}sr <pokemon>` • `{prefix}shr [chain] [target%]`\n"
                    f"`{prefix}td` • `{prefix}td <id>` • `{prefix}td <id1> <id2>` — time difference between messages\n"
                    f"`{prefix}date [objectid]` / `{prefix}caught` — Pokémon caught date from ObjectID  •  **Right-click:** Get Caught Date\n"
                    f"`{prefix}extractids [msg_id]` / `{prefix}eids` — extract IDs from Pokétwo embed  •  **Right-click:** Extract IDs\n"
                    "Hint solver (automatic — no command needed)"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔥 Incense",
                value=(
                    f"`{prefix}inc toggle` • `{prefix}inc cat add/remove/list`\n"
                    f"`{prefix}inc pause [all]` • `{prefix}inc resume [all]` • `{prefix}inc list`\n"
                    f"**Admin:** `{prefix}inc allowedroles` • `{prefix}inc ar add/remove/clear`"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔐 Captcha  *(Admin)*",
                value=f"`{prefix}channel captcha [#channel]`",
                inline=False,
            )
            embed.add_field(
                name="💾 Reserve",
                value=(
                    f"`{prefix}r list` • `{prefix}r list @user`\n"
                    f"`{prefix}r remove p/cat` • `{prefix}r clear`\n"
                    f"**Admin:** `{prefix}r add p/cat @user` • `{prefix}r remove p/cat @user` • `{prefix}r clear @user` • `{prefix}r clear --all`"
                ),
                inline=False,
            )
            embed.add_field(
                name="📝 List Builder",
                value=(
                    f"`{prefix}listgen` / `{prefix}lg` / `{prefix}listbuilder`\n"
                    f"Filters: `--type` `--region` `--sr` `--stage` `--name` `--catchable` `--notcatchable`"
                ),
                inline=False,
            )
            embed.add_field(
                name="🔍 Starboard Manual Check  *(Admin)*",
                value=f"`{prefix}catchcheck` • `{prefix}eggcheck` • `{prefix}unboxcheck`",
                inline=False,
            )
            if is_owner:
                embed.add_field(
                    name="👑 Owner",
                    value=(
                        f"`{prefix}loadmodel` • `{prefix}unloadmodel` • `{prefix}reloadmodel`\n"
                        f"`{prefix}modelstatus` • `{prefix}reloadsr`\n"
                        f"`{prefix}channel lowpred #ch` • `{prefix}channel secondary #ch`\n"
                        f"`{prefix}channel global-starboard catch/egg/unbox #ch`"
                    ),
                    inline=False,
                )
            embed.add_field(name="ℹ️ Info", value=f"`{prefix}help` • `{prefix}about` • `{prefix}ping`", inline=False)

        else:
            await ctx.reply(
                f"❌ Unknown category: `{category}`\n"
                f"Available: `collection`, `category`, `hunt`, `pings`, `settings`, `roles`, `channels`, "
                f"`prediction`, `starboard`, `helpful`, `incense`, `captcha`, `reserve`, `listgen`, "
                f"{'`owner`, ' if is_owner else ''}`all`\n"
                f"Use `{prefix}help` to see the main help menu.",
                mention_author=False,
            )
            return

        embed.set_footer(text=f"Bot Prefix: {', '.join(BOT_PREFIX)}")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="about")
    async def about_command(self, ctx):
        """Show bot information and statistics"""
        prefix = BOT_PREFIX[0]

        embed = discord.Embed(
            title="ℹ️ About Pokémon Helper Bot",
            description="A comprehensive Pokémon collection and prediction bot for Poketwo",
            color=EMBED_COLOR,
        )
        embed.add_field(
            name="✨ Key Features",
            value=(
                "• 📦 **Collection Management** — Track and get pinged for Pokémon you collect\n"
                "• 🗂️ **Category System** — Bulk add Pokémon to collection\n"
                "• ✨ **Shiny Hunting** — Get notified when your hunt target spawns\n"
                "• 🔷 **Type & Region Pings** — Get pinged by Pokémon type or region\n"
                "• 🔮 **Dual Model Prediction** — Automatically identifies Poketwo spawns\n"
                "• ⭐ **Starboard Logging** — Log rare catches, hatches, and unboxes\n"
                "• 🔕 **AFK Mode** — Disable pings when you're away\n"
                "• 🏷️ **Best Name** — Optionally show shortest known name per prediction"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Statistics",
            value=(
                f"**Servers:** {len(self.bot.guilds)}\n"
                f"**Users:** {sum(g.member_count for g in self.bot.guilds)}\n"
                f"**Commands:** {len(self.bot.commands)}"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚙️ Technical",
            value=(
                f"**Prefix:** {', '.join(BOT_PREFIX)}\n"
                "**Library:** discord.py\n"
                "**Database:** MongoDB\n"
                "**AI Models:** Dual CNN (224×224)"
            ),
            inline=True,
        )
        embed.add_field(
            name="🚀 Getting Started",
            value=f"Use `{prefix}help` to see all available commands and features!",
            inline=False,
        )
        embed.set_footer(text="Made with ❤️ for the Poketwo community")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="ping", aliases=["latency", "pong"])
    async def ping_command(self, ctx):
        """Check bot's latency"""
        import time
        api_latency = round(self.bot.latency * 1000)
        start = time.perf_counter()
        message = await ctx.reply("🏓 Pinging...", mention_author=False)
        end = time.perf_counter()
        response_time = round((end - start) * 1000)

        embed = discord.Embed(title="🏓 Pong!", color=EMBED_COLOR)
        embed.add_field(name="API Latency",   value=f"{api_latency}ms",   inline=True)
        embed.add_field(name="Response Time", value=f"{response_time}ms", inline=True)

        if api_latency < 100:
            status = "🟢 Excellent"
        elif api_latency < 200:
            status = "🟡 Good"
        elif api_latency < 300:
            status = "🟠 Fair"
        else:
            status = "🔴 Poor"

        embed.add_field(name="Status", value=status, inline=True)
        embed.set_footer(text=f"Requested by {ctx.author.display_name}")
        await message.edit(content=None, embed=embed)

    @commands.command(name="commands", aliases=["cmds"])
    async def commands_command(self, ctx):
        """Quick alias to show all commands"""
        await ctx.invoke(self.help_command, category="all")

    # ------------------------------------------------------------------
    # Slash Commands
    # ------------------------------------------------------------------
    @app_commands.command(name="help", description="Show help information for the bot")
    @app_commands.describe(category="Category: collection, category, hunt, pings, settings, roles, channels, prediction, starboard, helpful, incense, captcha, reserve, listgen, all")
    async def slash_help(self, interaction: discord.Interaction, category: str = None):
        ctx = await commands.Context.from_interaction(interaction)
        await self.help_command(ctx, category=category)

    @app_commands.command(name="about", description="Show bot information and statistics")
    async def slash_about(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.about_command(ctx)

    @app_commands.command(name="ping", description="Check bot latency")
    async def slash_ping(self, interaction: discord.Interaction):
        ctx = await commands.Context.from_interaction(interaction)
        await self.ping_command(ctx)


async def setup(bot):
    await bot.add_cog(Help(bot))
