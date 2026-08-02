"""Organize system — post a claimable-spot embed (Pokémon/categories with
optional prices), let members claim spots by clicking buttons, then bulk-add
every claimed spot into the existing reserve system when the event is done.

Templates are saved per-guild and can be reused/edited. A live "session" is
the actual posted message + its current claim state; sessions persist across
bot restarts (buttons keep working) because state lives in Mongo and the
views are re-registered on `on_ready`.
"""

import discord
from discord.ext import commands
from typing import List, Optional
from utils import (
    load_pokemon_data,
    find_all_pokemon_by_name_flexible,
    get_pokemon_with_variants,
)
from config import EMBED_COLOR

NO_MENTIONS = discord.AllowedMentions.none()

MAX_SPOTS = 25  # Discord hard limit: 5 rows x 5 buttons per message

OPEN_EMOJI = "🔓"
CLAIMED_EMOJI = "🔒"


# ---------------------------------------------------------------------------
# Spot helpers
# ---------------------------------------------------------------------------
def _spot_button_label(spot: dict) -> str:
    """Label shown on the button itself (short — Discord caps at 80 chars)."""
    label = spot["label"]
    if spot.get("price"):
        label = f"{label} — {spot['price']}"
    return label[:80]


def _spot_line(spot: dict) -> str:
    """One line of the embed description for a single spot."""
    emoji = CLAIMED_EMOJI if spot.get("reserved_by") else OPEN_EMOJI
    price_txt = f" ({spot['price']})" if spot.get("price") else ""
    line = f"{emoji} **{spot['label']}**{price_txt}"
    if spot.get("reserved_by"):
        name = spot.get("reserved_name") or "Unknown"
        line += f"\n> <@{spot['reserved_by']}> ({name})"
    return line


def build_session_embed(guild_name: str, template_name: str, spots: List[dict], status: str = "active") -> discord.Embed:
    claimed = sum(1 for s in spots if s.get("reserved_by"))
    title = f"📋 Organize — {template_name}"
    if status != "active":
        title += f" ({status.upper()})"
    embed = discord.Embed(
        title=title,
        description="\n\n".join(_spot_line(s) for s in spots),
        color=EMBED_COLOR,
    )
    embed.set_footer(text=f"{guild_name} • {claimed}/{len(spots)} claimed" + (
        "" if status == "active" else " • click-to-claim is closed"
    ))
    return embed


# ---------------------------------------------------------------------------
# Persistent button view for a live session
# ---------------------------------------------------------------------------
class SpotButton(discord.ui.Button):
    def __init__(self, session_id: str, index: int, spot: dict):
        style = discord.ButtonStyle.danger if spot.get("reserved_by") else discord.ButtonStyle.secondary
        super().__init__(
            label=_spot_button_label(spot),
            style=style,
            emoji=CLAIMED_EMOJI if spot.get("reserved_by") else OPEN_EMOJI,
            custom_id=f"org:{session_id}:{index}",
            row=index // 5,
        )
        self.session_id = session_id
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: OrganizeSessionView = self.view
        await view.cog.handle_spot_click(interaction, self.session_id, self.index)


class OrganizeSessionView(discord.ui.View):
    """Rebuilt fresh from DB state on every click and on bot startup, so it
    always reflects the latest claims. timeout=None + static custom_ids make
    it a persistent view that survives restarts."""

    def __init__(self, cog: "Organize", session_id: str, spots: List[dict], closed: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.session_id = session_id
        for i, spot in enumerate(spots[:MAX_SPOTS]):
            btn = SpotButton(session_id, i, spot)
            if closed:
                btn.disabled = True
            self.add_item(btn)


# ---------------------------------------------------------------------------
# Organize Cog
# ---------------------------------------------------------------------------
class Organize(commands.Cog):
    """Event-organizing system: claimable spots that feed into reserves."""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()
        self._restored = False

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------------
    # Permission check — reuses the same rule as the reserve system
    # ------------------------------------------------------------------
    async def _has_permission(self, ctx_or_interaction) -> bool:
        if isinstance(ctx_or_interaction, commands.Context):
            user, guild = ctx_or_interaction.author, ctx_or_interaction.guild
        else:
            user, guild = ctx_or_interaction.user, ctx_or_interaction.guild

        if await self.bot.is_owner(user):
            return True
        if user.id == guild.owner_id:
            return True
        if user.guild_permissions.administrator:
            return True

        gcache = getattr(self.bot.db, "gcache", None)
        if gcache:
            allowed = await gcache.get_reserve_allowed_roles(guild.id)
        else:
            allowed = await self.db.get_reserve_allowed_roles(guild.id)
        user_role_ids = {r.id for r in user.roles}
        return bool(user_role_ids & set(allowed))

    # ------------------------------------------------------------------
    # Restore persistent views on startup so buttons keep working
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_ready(self):
        if self._restored:
            return
        self._restored = True
        try:
            sessions = await self.db.get_all_active_organize_sessions()
        except Exception as e:
            print(f"⚠️ Organize: could not load active sessions: {e}")
            return
        for sess in sessions:
            view = OrganizeSessionView(self, str(sess["_id"]), sess["spots"])
            self.bot.add_view(view, message_id=sess.get("message_id"))
        if sessions:
            print(f"✅ Organize: restored {len(sessions)} active session view(s)")

    # ------------------------------------------------------------------
    # Spot parsing — one spot per line:
    #   pokemon | <name>            (auto-expands shared/event names)
    #   pokemon | <name> all        (all variants of a base species)
    #   category | <category name>
    # Optional trailing " | <price>" on either.
    # ------------------------------------------------------------------
    def _parse_spot_line(self, line: str) -> Optional[dict]:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            return None
        type_raw = parts[0].lower()
        value = parts[1]
        price = parts[2] if len(parts) > 2 and parts[2] else None

        if type_raw in ("pokemon", "poke", "p"):
            return {"type": "pokemon", "label": value, "value": value, "price": price}
        elif type_raw in ("cat", "category"):
            return {"type": "category", "label": value, "value": value, "price": price}
        return None

    async def _parse_template_body(self, ctx, body: str) -> tuple[List[dict], List[str]]:
        """Parse the multi-line spot definition block. Returns (spots, errors)."""
        spots, errors = [], []
        lines = [l for l in body.splitlines() if l.strip()]
        for line in lines:
            spot = self._parse_spot_line(line)
            if spot is None:
                errors.append(f"Couldn't parse: `{line}`")
                continue
            if spot["type"] == "category":
                cat = await self.db.get_category(ctx.guild.id, spot["value"])
                if not cat:
                    errors.append(f"Unknown category: `{spot['value']}`")
                    continue
            else:
                resolved = self._resolve_pokemon_spot(spot["value"])
                if not resolved:
                    errors.append(f"Unknown Pokémon: `{spot['value']}`")
                    continue
            spots.append(spot)
        return spots, errors

    def _resolve_pokemon_spot(self, value: str) -> List[str]:
        """Resolve a 'pokemon' spot's raw value to concrete Pokémon names.
        Supports 'X all' for every variant of a base species, and otherwise
        expands to every Pokémon sharing that display name (e.g. an event
        name shared by many form variants, like 'Pride Vivillon')."""
        low = value.lower()
        if low.endswith(" all") or low.startswith("all "):
            base = value[4:].strip() if low.startswith("all ") else value[:-4].strip()
            return get_pokemon_with_variants(base, self.pokemon_data)
        matches = find_all_pokemon_by_name_flexible(value, self.pokemon_data)
        names = []
        for m in matches:
            n = m.get("name")
            if n and n not in names:
                names.append(n)
        return names

    async def _resolve_spot_final(self, guild_id: int, spot: dict) -> List[str]:
        """Resolve a spot to its final Pokémon list at session-start time
        (categories are looked up live so edits to them are respected)."""
        if spot["type"] == "category":
            cat = await self.db.get_category(guild_id, spot["value"])
            return cat.get("pokemon", []) if cat else []
        return self._resolve_pokemon_spot(spot["value"])

    # ------------------------------------------------------------------
    # Main group
    # ------------------------------------------------------------------
    @commands.group(name="organize", aliases=["og", "event"], invoke_without_command=True)
    async def organize_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await self._send_help(ctx)

    async def _send_help(self, ctx):
        p = ctx.prefix
        embed = discord.Embed(
            title="🗂️ Organize System",
            color=EMBED_COLOR,
            description="Post a claimable list of spots (Pokémon/categories). Members claim by clicking; you commit everything to reserves when done.",
        )
        embed.add_field(
            name="📐 Templates (reusable, admin/allowed-role only)",
            value=(
                f"`{p}og template create <name>` — then on the next lines, one spot per line:\n"
                f"  `pokemon | Pride Pyroar | 250k pc`\n"
                f"  `pokemon | Pride Vivillon`\n"
                f"  `category | Rare`\n"
                f"`{p}og template edit <name>` — same format, replaces all spots\n"
                f"`{p}og template view <name>` — see a template's spots\n"
                f"`{p}og template list` — list saved templates\n"
                f"`{p}og template delete <name>`\n"
                f"`{p}og template setdefault <name>` — used by `{p}og start` with no argument"
            ),
            inline=False,
        )
        embed.add_field(
            name="🚀 Running an event (admin/allowed-role only)",
            value=(
                f"`{p}og start [template]` — posts the claim embed (uses the default template if omitted)\n"
                f"`{p}og view` — reposts the claim embed at the bottom of chat; disables the old message's buttons\n"
                f"`{p}og end` — commits every claimed spot to reserves, closes the embed\n"
                f"`{p}og cancel` — closes the embed without touching reserves"
            ),
            inline=False,
        )
        embed.add_field(
            name="👆 Everyone",
            value="Click a spot's button to claim it. Click it again to release it.",
            inline=False,
        )
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------
    @organize_group.group(name="template", aliases=["tmpl", "t"], invoke_without_command=True)
    async def template_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await self._template_list(ctx)

    @template_group.command(name="create")
    async def template_create(self, ctx, *, name: str):
        """p!og template create <name>  (spots go on the following lines of the SAME message)"""
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage templates.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        # Support the spot lines being in the same message after a newline,
        # e.g. "p!og template create MyEvent\npokemon | Pride Pyroar | 250k".
        if "\n" in name:
            name, body = name.split("\n", 1)
            name = name.strip()
        else:
            body = None

        if not name:
            await ctx.reply("❌ Please provide a template name.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        existing = await self.db.get_organize_template(ctx.guild.id, name)
        if existing:
            await ctx.reply(f"❌ A template named **{name}** already exists. Use `{ctx.prefix}og template edit {name}` instead.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        if not body:
            await ctx.reply(
                "❌ No spots provided. Put one spot per line right after the name, e.g.:\n"
                "```\np!og template create MyEvent\npokemon | Pride Pyroar | 250k pc\ncategory | Rare\n```",
                mention_author=False, allowed_mentions=NO_MENTIONS,
            )
            return

        spots, errors = await self._parse_template_body(ctx, body)
        if not spots:
            await ctx.reply("❌ No valid spots found.\n" + "\n".join(errors[:10]), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        if len(spots) > MAX_SPOTS:
            await ctx.reply(f"❌ Too many spots ({len(spots)}). Max is {MAX_SPOTS} per template.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        await self.db.create_organize_template(ctx.guild.id, name, spots, ctx.author.id)
        msg = f"✅ Template **{name}** created with {len(spots)} spot(s)."
        if errors:
            msg += "\n⚠️ Skipped:\n" + "\n".join(errors[:10])
        await ctx.reply(msg, mention_author=False, allowed_mentions=NO_MENTIONS)

    @template_group.command(name="edit")
    async def template_edit(self, ctx, *, name: str):
        """p!og template edit <name>  (new spot list on the following lines — replaces the old one)"""
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage templates.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        if "\n" in name:
            name, body = name.split("\n", 1)
            name = name.strip()
        else:
            body = None

        existing = await self.db.get_organize_template(ctx.guild.id, name)
        if not existing:
            await ctx.reply(f"❌ No template named **{name}**.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        if not body:
            await ctx.reply("❌ No spots provided. Put the new spot list on the lines right after the name.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        spots, errors = await self._parse_template_body(ctx, body)
        if not spots:
            await ctx.reply("❌ No valid spots found.\n" + "\n".join(errors[:10]), mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        if len(spots) > MAX_SPOTS:
            await ctx.reply(f"❌ Too many spots ({len(spots)}). Max is {MAX_SPOTS} per template.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        await self.db.update_organize_template(ctx.guild.id, name, spots)
        msg = f"✅ Template **{name}** updated — now has {len(spots)} spot(s)."
        if errors:
            msg += "\n⚠️ Skipped:\n" + "\n".join(errors[:10])
        await ctx.reply(msg, mention_author=False, allowed_mentions=NO_MENTIONS)

    @template_group.command(name="delete", aliases=["remove"])
    async def template_delete(self, ctx, *, name: str):
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage templates.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        ok = await self.db.delete_organize_template(ctx.guild.id, name)
        if ok:
            await ctx.reply(f"✅ Template **{name}** deleted.", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            await ctx.reply(f"❌ No template named **{name}**.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @template_group.command(name="view", aliases=["show"])
    async def template_view(self, ctx, *, name: str):
        tmpl = await self.db.get_organize_template(ctx.guild.id, name)
        if not tmpl:
            await ctx.reply(f"❌ No template named **{name}**.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        lines = []
        for s in tmpl["spots"]:
            price = f" — {s['price']}" if s.get("price") else ""
            lines.append(f"• [{s['type']}] {s['label']}{price}")
        embed = discord.Embed(
            title=f"📐 Template — {tmpl['name']}",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        embed.set_footer(text=f"{len(tmpl['spots'])} spot(s)")
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    async def _template_list(self, ctx):
        templates = await self.db.get_all_organize_templates(ctx.guild.id)
        default = await self.db.get_default_organize_template(ctx.guild.id)
        if not templates:
            await ctx.reply(f"No templates saved yet. Create one with `{ctx.prefix}og template create <name>`.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        lines = []
        for t in templates:
            star = " ⭐ (default)" if default and t["name"].lower() == default.lower() else ""
            lines.append(f"• **{t['name']}** — {len(t.get('spots', []))} spot(s){star}")
        embed = discord.Embed(title="📐 Saved Templates", description="\n".join(lines), color=EMBED_COLOR)
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    @template_group.command(name="setdefault", aliases=["default"])
    async def template_setdefault(self, ctx, *, name: str = None):
        """Set (or view, if no name given) the default template used by `p!og start` with no argument."""
        if name is None:
            current = await self.db.get_default_organize_template(ctx.guild.id)
            if current:
                await ctx.reply(f"⭐ Current default template: **{current}**", mention_author=False, allowed_mentions=NO_MENTIONS)
            else:
                await ctx.reply(f"No default template set. Use `{ctx.prefix}og template setdefault <name>`.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage templates.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        tmpl = await self.db.get_organize_template(ctx.guild.id, name)
        if not tmpl:
            await ctx.reply(f"❌ No template named **{name}**.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        await self.db.set_default_organize_template(ctx.guild.id, tmpl["name"])
        await ctx.reply(f"⭐ **{tmpl['name']}** is now the default — `{ctx.prefix}og start` will use it.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @organize_group.command(name="view", aliases=["status", "refresh", "bump"])
    async def organize_view(self, ctx):
        """Repost the live claim embed at the bottom of the channel — handy in
        a busy chat. The old message's buttons get disabled; the new one
        becomes the one people click going forward."""
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to repost the session.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session = await self.db.get_active_organize_session_in_channel(ctx.channel.id)
        if not session:
            await ctx.reply("No active session in this channel.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        spots = session["spots"]

        # Disable buttons on the old live message so only one message is
        # ever clickable at a time.
        if session.get("message_id"):
            try:
                old_msg = await ctx.channel.fetch_message(session["message_id"])
                old_embed = build_session_embed(ctx.guild.name, session["template_name"], spots, status="moved")
                disabled_view = OrganizeSessionView(self, session_id, spots, closed=True)
                await old_msg.edit(embed=old_embed, view=disabled_view)
            except (discord.NotFound, discord.HTTPException):
                pass

        # Post the fresh, clickable copy
        new_embed = build_session_embed(ctx.guild.name, session["template_name"], spots)
        new_view = OrganizeSessionView(self, session_id, spots)
        new_msg = await ctx.send(embed=new_embed, view=new_view)
        await self.db.set_organize_session_message(session_id, new_msg.id)

    # ------------------------------------------------------------------
    # Sessions: start / end / cancel
    # ------------------------------------------------------------------
    @organize_group.command(name="start")
    async def organize_start(self, ctx, *, template_name: str = None):
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to start an organize session.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        if not template_name:
            template_name = await self.db.get_default_organize_template(ctx.guild.id)
            if not template_name:
                await ctx.reply(
                    f"❌ No template specified and no default set.\n"
                    f"Use `{ctx.prefix}og start <template>`, or set a default once with "
                    f"`{ctx.prefix}og template setdefault <template>`.",
                    mention_author=False, allowed_mentions=NO_MENTIONS,
                )
                return

        active = await self.db.get_active_organize_session_in_channel(ctx.channel.id)
        if active:
            await ctx.reply(f"❌ There's already an active session in this channel. Run `{ctx.prefix}og end` or `{ctx.prefix}og cancel` first.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        tmpl = await self.db.get_organize_template(ctx.guild.id, template_name)
        if not tmpl:
            await ctx.reply(f"❌ No template named **{template_name}**.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        # Snapshot-resolve every spot now, so `end` doesn't need to re-parse.
        session_spots = []
        for s in tmpl["spots"]:
            resolved = await self._resolve_spot_final(ctx.guild.id, s)
            session_spots.append({
                "label": s["label"],
                "type": s["type"],
                "value": s["value"],
                "price": s.get("price"),
                "resolved": resolved,
                "reserved_by": None,
                "reserved_name": None,
            })

        session_id = await self.db.create_organize_session(
            ctx.guild.id, ctx.channel.id, tmpl["name"], session_spots, ctx.author.id
        )

        embed = build_session_embed(ctx.guild.name, tmpl["name"], session_spots)
        view = OrganizeSessionView(self, session_id, session_spots)
        msg = await ctx.send(embed=embed, view=view)
        await self.db.set_organize_session_message(session_id, msg.id)

    @organize_group.command(name="end", aliases=["finish", "commit"])
    async def organize_end(self, ctx):
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to end an organize session.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session = await self.db.get_active_organize_session_in_channel(ctx.channel.id)
        if not session:
            await ctx.reply("❌ No active session in this channel.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        added_summary = []
        for s in session["spots"]:
            if not s.get("reserved_by") or not s.get("resolved"):
                continue
            await self.db.add_pokemon_to_reserve(s["reserved_by"], ctx.guild.id, s["resolved"])
            price = f" ({s['price']})" if s.get("price") else ""
            added_summary.append(f"<@{s['reserved_by']}> → **{s['label']}**{price}")

        await self.db.set_organize_session_status(session_id, "ended")

        # Disable the buttons on the original message
        try:
            channel = ctx.guild.get_channel(session["channel_id"])
            msg = await channel.fetch_message(session["message_id"])
            closed_embed = build_session_embed(ctx.guild.name, session["template_name"], session["spots"], status="ended")
            closed_view = OrganizeSessionView(self, session_id, session["spots"], closed=True)
            await msg.edit(embed=closed_embed, view=closed_view)
        except (discord.NotFound, discord.HTTPException):
            pass

        # Everything worth keeping now lives in `reserves` — drop the
        # session doc so closed events don't pile up in Mongo.
        await self.db.delete_organize_session(session_id)

        if not added_summary:
            await ctx.reply("✅ Session ended. Nobody had claimed a spot, so nothing was added to reserves.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        embed = discord.Embed(
            title="✅ Organize session committed to reserves",
            description="\n".join(added_summary),
            color=EMBED_COLOR,
        )
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    @organize_group.command(name="cancel")
    async def organize_cancel(self, ctx):
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to cancel an organize session.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session = await self.db.get_active_organize_session_in_channel(ctx.channel.id)
        if not session:
            await ctx.reply("❌ No active session in this channel.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        await self.db.set_organize_session_status(session_id, "cancelled")

        try:
            channel = ctx.guild.get_channel(session["channel_id"])
            msg = await channel.fetch_message(session["message_id"])
            closed_embed = build_session_embed(ctx.guild.name, session["template_name"], session["spots"], status="cancelled")
            closed_view = OrganizeSessionView(self, session_id, session["spots"], closed=True)
            await msg.edit(embed=closed_embed, view=closed_view)
        except (discord.NotFound, discord.HTTPException):
            pass

        await self.db.delete_organize_session(session_id)

        await ctx.reply("✅ Session cancelled. Nothing was added to reserves.", mention_author=False, allowed_mentions=NO_MENTIONS)

    # ------------------------------------------------------------------
    # Button click handler
    # ------------------------------------------------------------------
    async def handle_spot_click(self, interaction: discord.Interaction, session_id: str, index: int):
        session = await self.db.get_organize_session(session_id)
        if not session or session.get("status") != "active":
            await interaction.response.send_message("⚠️ This organize session has ended.", ephemeral=True)
            return

        spots = session["spots"]
        if index >= len(spots):
            await interaction.response.send_message("⚠️ That spot no longer exists.", ephemeral=True)
            return

        spot = spots[index]
        user = interaction.user

        if spot.get("reserved_by") == user.id:
            # Release own claim
            await self.db.set_organize_session_spot(session_id, index, None, None)
            spot["reserved_by"] = None
            spot["reserved_name"] = None
        elif spot.get("reserved_by"):
            await interaction.response.send_message(
                f"⚠️ **{spot['label']}** is already claimed by <@{spot['reserved_by']}>.",
                ephemeral=True,
            )
            return
        else:
            await self.db.set_organize_session_spot(session_id, index, user.id, user.display_name)
            spot["reserved_by"] = user.id
            spot["reserved_name"] = user.display_name

        embed = build_session_embed(interaction.guild.name, session["template_name"], spots)
        view = OrganizeSessionView(self, session_id, spots)
        await interaction.response.edit_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Organize(bot))
