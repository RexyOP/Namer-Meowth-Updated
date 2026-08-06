"""Organize system — post a claimable-spot embed (Pokémon/categories with
optional prices), let members claim spots by clicking buttons, then bulk-add
every claimed spot into the existing reserve system when the event is done.

Templates are saved per-guild and can be reused/edited. A live "session" is
the actual posted message + its current claim state; sessions persist across
bot restarts (buttons keep working) because state lives in Mongo and the
views are re-registered on `on_ready`.
"""

import asyncio
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

OPEN_EMOJI = "<:isee:1498926586685034539>"
CLAIMED_EMOJI = "<:pepethumbup:1504344280435789965>"

PING_AUTO_DISABLE_SECONDS = 300  # ping button self-disables 5 min after `og end`


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


class PingButton(discord.ui.Button):
    """Shown only on the closed embed after `og end`. Pings everyone who had
    a claimed spot. Restricted to the same allowed-roles/admin check as the
    rest of organize, single-use, and auto-disabled after
    PING_AUTO_DISABLE_SECONDS by the cog (see _auto_disable_ping)."""

    def __init__(self, cog: "Organize", session_id: str, user_ids: List[int]):
        super().__init__(
            label="🔔 Ping claimers",
            style=discord.ButtonStyle.success,
            custom_id=f"orgping:{session_id}",
        )
        self.cog = cog
        self.session_id = session_id
        self.user_ids = user_ids

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_ping_click(interaction, self)


class OrganizeSessionView(discord.ui.View):
    """Rebuilt fresh from DB state on every click and on bot startup, so it
    always reflects the latest claims. timeout=None + static custom_ids make
    it a persistent view that survives restarts.

    ping_user_ids, when passed, adds a PingButton for those user ids and
    reserves a slot for it — spot buttons are capped at MAX_SPOTS - 1 in
    that case so the row/column limit (5x5) is never exceeded."""

    def __init__(
        self,
        cog: "Organize",
        session_id: str,
        spots: List[dict],
        closed: bool = False,
        ping_user_ids: Optional[List[int]] = None,
    ):
        super().__init__(timeout=None)
        self.cog = cog
        self.session_id = session_id
        self.ping_button: Optional[PingButton] = None

        spot_cap = (MAX_SPOTS - 1) if ping_user_ids else MAX_SPOTS
        for i, spot in enumerate(spots[:spot_cap]):
            btn = SpotButton(session_id, i, spot)
            if closed:
                btn.disabled = True
            self.add_item(btn)

        if ping_user_ids:
            self.ping_button = PingButton(cog, session_id, ping_user_ids)
            self.add_item(self.ping_button)


# ---------------------------------------------------------------------------
# Organize Cog
# ---------------------------------------------------------------------------
class Organize(commands.Cog):
    """Event-organizing system: claimable spots that feed into reserves."""

    def __init__(self, bot):
        self.bot = bot
        self.pokemon_data = load_pokemon_data()
        self._restored = False
        self._ping_tasks = {}  # session_id -> asyncio.Task (auto-disable timers)

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
        embed.add_field(
            name="🔧 Manual spot management (admin/allowed-role only)",
            value=(
                f"`{p}og spot` — numbered list of every spot and who holds it\n"
                f"`{p}og spot set <#> <@member>` — assign a spot to someone, replacing whoever's there\n"
                f"`{p}og spot clear <#>` — remove whoever holds a spot, opening it back up"
            ),
            inline=False,
        )
        embed.add_field(
            name="🚫 Blacklist (Admin only)",
            value=(
                f"`{p}og blacklist` — view blocked roles\n"
                f"`{p}og blacklist add <@role|id>` — block a role from claiming spots\n"
                f"`{p}og blacklist remove <@role|id>` — unblock a role\n"
                f"`{p}og blacklist clear` — clear the blacklist"
            ),
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

        session = await self.db.get_active_organize_session_in_guild(ctx.guild.id)
        if not session:
            await ctx.reply("No active session in this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        spots = session["spots"]

        # Disable buttons on the old live message so only one message is
        # ever clickable at a time. It may be sitting in a different
        # channel than the one this command was run in.
        if session.get("message_id"):
            try:
                old_channel = ctx.guild.get_channel(session["channel_id"]) or ctx.channel
                old_msg = await old_channel.fetch_message(session["message_id"])
                old_embed = build_session_embed(ctx.guild.name, session["template_name"], spots, status="moved")
                disabled_view = OrganizeSessionView(self, session_id, spots, closed=True)
                await old_msg.edit(embed=old_embed, view=disabled_view)
            except (discord.NotFound, discord.HTTPException):
                pass

        # Post the fresh, clickable copy — wherever this command was run
        new_embed = build_session_embed(ctx.guild.name, session["template_name"], spots)
        new_view = OrganizeSessionView(self, session_id, spots)
        new_msg = await ctx.send(embed=new_embed, view=new_view)
        await self.db.set_organize_session_message(session_id, new_msg.id, channel_id=ctx.channel.id)

    # ------------------------------------------------------------------
    # Manual spot management — let an admin/allowed-role replace, add, or
    # remove a claim on any spot directly, without the member clicking.
    # Every change here is saved to Mongo the same way a button click is
    # (write confirmed before the live message is touched), then the live
    # message is refreshed immediately so it never goes stale.
    # ------------------------------------------------------------------
    async def _get_active_session_or_reply(self, ctx) -> Optional[dict]:
        session = await self.db.get_active_organize_session_in_guild(ctx.guild.id)
        if not session:
            await ctx.reply("❌ No active session in this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return None
        return session

    async def _refresh_live_message(self, ctx, session: dict, session_id: str, spots: List[dict]):
        """Re-render the live message after a manual change. The DB write
        itself already happened (and was confirmed) before this is called."""
        try:
            channel = ctx.guild.get_channel(session["channel_id"]) or ctx.channel
            msg = await channel.fetch_message(session["message_id"])
        except (discord.NotFound, discord.HTTPException, AttributeError):
            return
        embed = build_session_embed(ctx.guild.name, session["template_name"], spots)
        view = OrganizeSessionView(self, session_id, spots)
        try:
            await msg.edit(embed=embed, view=view)
        except discord.HTTPException:
            pass

    @organize_group.group(name="spot", aliases=["s"], invoke_without_command=True)
    async def spot_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await self._spot_list(ctx)

    async def _spot_list(self, ctx):
        session = await self._get_active_session_or_reply(ctx)
        if not session:
            return
        lines = []
        for i, s in enumerate(session["spots"], start=1):
            if s.get("reserved_by"):
                who = f"<@{s['reserved_by']}> ({s.get('reserved_name') or 'Unknown'})"
            else:
                who = "*open*"
            lines.append(f"`{i}.` **{s['label']}** — {who}")
        embed = discord.Embed(
            title="📋 Organize — Spot numbers",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        embed.set_footer(text=f"{ctx.prefix}og spot set <#> <@member>  •  {ctx.prefix}og spot clear <#>")
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    @spot_group.command(name="set", aliases=["assign", "replace", "add"])
    async def spot_set(self, ctx, index: int, member: discord.Member):
        """Force-assign a spot to a member — replaces whoever currently holds it, or claims an open one."""
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage spots.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session = await self._get_active_session_or_reply(ctx)
        if not session:
            return

        spots = session["spots"]
        i = index - 1
        if i < 0 or i >= len(spots):
            await ctx.reply(f"❌ Invalid spot number. Run `{ctx.prefix}og spot` to see the numbered list (1-{len(spots)}).", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        previous = spots[i].get("reserved_by")

        try:
            saved = await self.db.set_organize_session_spot(session_id, i, member.id, member.display_name)
        except Exception as e:
            print(f"⚠️ Organize: failed to save manual spot set (session {session_id}, index {i}): {e}")
            saved = False
        if not saved:
            await ctx.reply("❌ Failed to save — the session may have just ended. Nothing changed.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        spots[i]["reserved_by"] = member.id
        spots[i]["reserved_name"] = member.display_name
        await self._refresh_live_message(ctx, session, session_id, spots)

        if previous and previous != member.id:
            await ctx.reply(f"✅ **{spots[i]['label']}** moved from <@{previous}> to {member.mention}.", mention_author=False, allowed_mentions=NO_MENTIONS)
        else:
            await ctx.reply(f"✅ **{spots[i]['label']}** assigned to {member.mention}.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @spot_group.command(name="clear", aliases=["remove", "unclaim", "open"])
    async def spot_clear(self, ctx, index: int):
        """Remove whoever currently holds a spot, opening it back up."""
        if not await self._has_permission(ctx):
            await ctx.reply("❌ You don't have permission to manage spots.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session = await self._get_active_session_or_reply(ctx)
        if not session:
            return

        spots = session["spots"]
        i = index - 1
        if i < 0 or i >= len(spots):
            await ctx.reply(f"❌ Invalid spot number. Run `{ctx.prefix}og spot` to see the numbered list (1-{len(spots)}).", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        session_id = str(session["_id"])
        previous = spots[i].get("reserved_by")
        if not previous:
            await ctx.reply(f"ℹ️ **{spots[i]['label']}** is already open.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        try:
            saved = await self.db.set_organize_session_spot(session_id, i, None, None)
        except Exception as e:
            print(f"⚠️ Organize: failed to save manual spot clear (session {session_id}, index {i}): {e}")
            saved = False
        if not saved:
            await ctx.reply("❌ Failed to save — the session may have just ended. Nothing changed.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return

        spots[i]["reserved_by"] = None
        spots[i]["reserved_name"] = None
        await self._refresh_live_message(ctx, session, session_id, spots)
        await ctx.reply(f"✅ **{spots[i]['label']}** cleared — was <@{previous}>, now open.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @spot_set.error
    @spot_clear.error
    async def spot_error(self, ctx, error):
        if isinstance(error, commands.MemberNotFound):
            await ctx.reply("❌ Couldn't find that member. Use an @mention or their user ID.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"❌ Usage: `{ctx.prefix}og spot set <#> <@member>` or `{ctx.prefix}og spot clear <#>`.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, commands.BadArgument):
            await ctx.reply("❌ Spot number must be a number — check it with `{}og spot`.".format(ctx.prefix), mention_author=False, allowed_mentions=NO_MENTIONS)

    # ------------------------------------------------------------------
    # Blacklisted roles — can't claim spots
    # ------------------------------------------------------------------
    @organize_group.group(name="blacklist", aliases=["bl"], invoke_without_command=True)
    async def blacklist_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await self._show_blacklist(ctx)

    async def _show_blacklist(self, ctx):
        role_ids = await self.db.get_organize_blacklisted_roles(ctx.guild.id)
        if not role_ids:
            embed = discord.Embed(
                title="🚫 Organize — Blacklisted Roles",
                description=f"No roles blacklisted. Everyone can claim spots.\n\nUse `{ctx.prefix}og blacklist add <@role|id>` to block a role.",
                color=EMBED_COLOR,
            )
        else:
            lines = []
            for rid in role_ids:
                role = ctx.guild.get_role(rid)
                lines.append(f"• {role.mention} (`{rid}`)" if role else f"• ~~Unknown role~~ (`{rid}`) — deleted?")
            embed = discord.Embed(
                title="🚫 Organize — Blacklisted Roles",
                description="\n".join(lines),
                color=EMBED_COLOR,
            )
            embed.set_footer(text=f"{len(role_ids)} role(s) — members with these can't claim organize spots")
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=NO_MENTIONS)

    @blacklist_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def blacklist_add(self, ctx, *, role_input: str):
        """Block a role from claiming organize spots. Use @mention or role ID."""
        role = await self._resolve_role(ctx, role_input)
        if role is None:
            await ctx.reply("❌ Could not find that role. Use @mention or role ID.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await self.db.add_organize_blacklisted_role(ctx.guild.id, role.id)
        await ctx.reply(f"✅ {role.mention} can no longer claim organize spots.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @blacklist_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def blacklist_remove(self, ctx, *, role_input: str):
        """Unblock a role from claiming organize spots."""
        role = await self._resolve_role(ctx, role_input)
        if role is None:
            await ctx.reply("❌ Could not find that role. Use @mention or role ID.", mention_author=False, allowed_mentions=NO_MENTIONS)
            return
        await self.db.remove_organize_blacklisted_role(ctx.guild.id, role.id)
        await ctx.reply(f"✅ {role.mention} removed from the organize blacklist.", mention_author=False, allowed_mentions=NO_MENTIONS)

    @blacklist_group.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def blacklist_clear(self, ctx):
        """Clear the entire organize blacklist."""
        await self.db.clear_organize_blacklisted_roles(ctx.guild.id)
        await ctx.reply("✅ Organize blacklist cleared.", mention_author=False, allowed_mentions=NO_MENTIONS)

    async def _resolve_role(self, ctx, role_input: str) -> Optional[discord.Role]:
        raw = role_input.strip("<@&> ")
        if raw.isdigit():
            return ctx.guild.get_role(int(raw))
        low = role_input.lower().strip()
        for role in ctx.guild.roles:
            if role.name.lower() == low:
                return role
        return None

    @blacklist_add.error
    @blacklist_remove.error
    @blacklist_clear.error
    async def blacklist_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ You need administrator permissions to manage the organize blacklist.", mention_author=False, allowed_mentions=NO_MENTIONS)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply("❌ Please provide a role mention or ID.", mention_author=False, allowed_mentions=NO_MENTIONS)

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

        active = await self.db.get_active_organize_session_in_guild(ctx.guild.id)
        if active:
            await ctx.reply(f"❌ There's already an active session in this server. Run `{ctx.prefix}og end` or `{ctx.prefix}og cancel` first. To view current session run `{ctx.prefix}og view`.", mention_author=False, allowed_mentions=NO_MENTIONS)
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

        session = await self.db.get_active_organize_session_in_guild(ctx.guild.id)
        if not session:
            await ctx.reply("❌ No active session in this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
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

        # Users who actually claimed a spot, deduped, order preserved —
        # this is who the ping button will notify.
        reserved_user_ids = list(dict.fromkeys(
            s["reserved_by"] for s in session["spots"] if s.get("reserved_by")
        ))

        # Disable the claim buttons on the original message, and (if anyone
        # claimed a spot) add a ping button for allowed roles/admins.
        try:
            channel = ctx.guild.get_channel(session["channel_id"])
            msg = await channel.fetch_message(session["message_id"])
            closed_embed = build_session_embed(ctx.guild.name, session["template_name"], session["spots"], status="ended")
            closed_view = OrganizeSessionView(
                self, session_id, session["spots"], closed=True,
                ping_user_ids=reserved_user_ids or None,
            )
            await msg.edit(embed=closed_embed, view=closed_view)

            if closed_view.ping_button:
                task = asyncio.create_task(
                    self._auto_disable_ping(msg, closed_view, closed_view.ping_button, session_id)
                )
                self._ping_tasks[session_id] = task
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

        session = await self.db.get_active_organize_session_in_guild(ctx.guild.id)
        if not session:
            await ctx.reply("❌ No active session in this server.", mention_author=False, allowed_mentions=NO_MENTIONS)
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
            # Release own claim — always allowed, even if later blacklisted,
            # so nobody gets stuck holding a spot they can't undo.
            new_by, new_name = None, None
        elif spot.get("reserved_by"):
            await interaction.response.send_message(
                f"⚠️ **{spot['label']}** is already claimed by <@{spot['reserved_by']}>.",
                ephemeral=True,
            )
            return
        else:
            blacklisted = await self.db.get_organize_blacklisted_roles(interaction.guild.id)
            if blacklisted and {r.id for r in user.roles} & set(blacklisted):
                await interaction.response.send_message(
                    "⚠️ You have a role that's blacklisted from claiming organize spots.",
                    ephemeral=True,
                )
                return
            new_by, new_name = user.id, user.display_name

        # Save to Mongo FIRST — and confirm it actually wrote — before ever
        # touching the message. This is what makes a claim durable across
        # restarts: if the write fails or matches nothing, we bail out
        # without editing the message, so the button and the DB can never
        # end up disagreeing (this is what caused stale state to show up
        # via `og view` after a restart before).
        try:
            saved = await self.db.set_organize_session_spot(session_id, index, new_by, new_name)
        except Exception as e:
            print(f"⚠️ Organize: failed to save spot claim (session {session_id}, index {index}): {e}")
            saved = False

        if not saved:
            await interaction.response.send_message(
                "⚠️ Couldn't save that claim just now — please try clicking again.",
                ephemeral=True,
            )
            return

        spot["reserved_by"] = new_by
        spot["reserved_name"] = new_name

        embed = build_session_embed(interaction.guild.name, session["template_name"], spots)
        view = OrganizeSessionView(self, session_id, spots)
        await interaction.response.edit_message(embed=embed, view=view)

    # ------------------------------------------------------------------
    # Ping button — allowed roles/admins only, single-use, self-disabling
    # ------------------------------------------------------------------
    async def handle_ping_click(self, interaction: discord.Interaction, button: "PingButton"):
        if not await self._has_permission(interaction):
            await interaction.response.send_message(
                "❌ You don't have permission to ping claimers.", ephemeral=True
            )
            return

        if button.disabled:
            await interaction.response.send_message(
                "⚠️ This ping button has already been used or has expired.", ephemeral=True
            )
            return

        if not button.user_ids:
            await interaction.response.send_message(
                "⚠️ Nobody claimed a spot in this session.", ephemeral=True
            )
            return

        # Disable immediately so it can't be double-clicked, and cancel the
        # scheduled auto-disable timer since we're editing the message now.
        button.disabled = True
        task = self._ping_tasks.pop(button.session_id, None)
        if task:
            task.cancel()

        await interaction.response.edit_message(view=button.view)

        mentions = " ".join(f"<@{uid}>" for uid in button.user_ids)
        await interaction.followup.send(
            f"📣 {mentions} — your claimed spot is ready, please check in!",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def _auto_disable_ping(
        self, message: discord.Message, view: discord.ui.View, button: "PingButton", session_id: str
    ):
        """Background timer: disables the ping button on its own after
        PING_AUTO_DISABLE_SECONDS if nobody's clicked it, so it doesn't
        stick around indefinitely (e.g. use is skipped, message forgotten).
        Note: like other in-memory timers, this doesn't survive a bot
        restart within the window — the button just stops working then,
        since the session doc is already deleted and won't be restored."""
        try:
            await asyncio.sleep(PING_AUTO_DISABLE_SECONDS)
        except asyncio.CancelledError:
            return
        finally:
            self._ping_tasks.pop(session_id, None)

        if button.disabled:
            return
        button.disabled = True
        try:
            await message.edit(view=view)
        except (discord.NotFound, discord.HTTPException):
            pass


async def setup(bot):
    await bot.add_cog(Organize(bot))
