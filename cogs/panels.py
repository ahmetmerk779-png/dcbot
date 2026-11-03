"""Paneller: destek talebi (ticket) ve buton ile rol alma.
Butonlar bot yeniden başlasa da çalışmaya devam eder (DynamicItem)."""
import asyncio
import io
import re

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

NO_PING = discord.AllowedMentions.none()


# ---------------------------------------------------------------- Ticket
def _staff_role_id(guild):
    return db.get_channel_id(guild.id, "ticket_staff_role")


async def open_ticket(interaction: discord.Interaction):
    guild, user = interaction.guild, interaction.user
    if guild is None:
        return
    await interaction.response.defer(ephemeral=True)

    tickets = db.get_data(guild.id).setdefault("tickets", {})
    for cid, uid in list(tickets.items()):
        channel = guild.get_channel(int(cid))
        if channel is None:
            tickets.pop(cid, None)
            db.save_data(guild.id)
        elif uid == user.id:
            return await interaction.followup.send(f"⚠️ Zaten açık bir talebin var: {channel.mention}", ephemeral=True)

    cat_id = db.get_channel_id(guild.id, "ticket_category")
    category = guild.get_channel(cat_id) if cat_id else None
    if not isinstance(category, discord.CategoryChannel):
        category = None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                          attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                              manage_channels=True, embed_links=True),
    }
    staff_id = _staff_role_id(guild)
    staff = guild.get_role(staff_id) if staff_id else None
    if staff:
        overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                        read_message_history=True, manage_messages=True)

    slug = re.sub(r"[^a-z0-9-]", "", user.display_name.lower().replace(" ", "-"))[:20] or "kullanici"
    try:
        channel = await guild.create_text_channel(
            f"ticket-{slug}", category=category, overwrites=overwrites,
            topic=f"Destek talebi sahibi: {user} ({user.id})", reason=f"Ticket: {user}",
        )
    except discord.HTTPException as e:
        return await interaction.followup.send(f"⛔ Kanal oluşturulamadı: {e}", ephemeral=True)

    tickets[str(channel.id)] = user.id
    db.save_data(guild.id)

    embed = discord.Embed(
        title="🎫 Destek Talebi",
        description=f"Merhaba {user.mention}! Sorununu buraya yaz, yetkililer en kısa sürede yardımcı olacak.",
        color=discord.Color.green(),
    )
    view = discord.ui.View(timeout=None)
    view.add_item(TicketCloseButton())
    mention = staff.mention if staff else ""
    await channel.send(
        f"{user.mention} {mention}".strip(), embed=embed, view=view,
        allowed_mentions=discord.AllowedMentions(users=[user], roles=[staff] if staff else []),
    )
    await interaction.followup.send(f"✅ Talebin açıldı: {channel.mention}", ephemeral=True)


async def close_ticket(interaction: discord.Interaction):
    guild, channel, user = interaction.guild, interaction.channel, interaction.user
    if guild is None or channel is None:
        return
    tickets = db.get_data(guild.id).setdefault("tickets", {})
    owner_id = tickets.get(str(channel.id))
    if owner_id is None:
        return await interaction.response.send_message("⚠️ Bu bir destek talebi kanalı değil.", ephemeral=True)

    staff_id = _staff_role_id(guild)
    allowed = (
        user.id == owner_id
        or user.guild_permissions.manage_channels
        or bool(staff_id and any(r.id == staff_id for r in user.roles))
    )
    if not allowed:
        return await interaction.response.send_message("⛔ Bu talebi kapatma yetkin yok.", ephemeral=True)

    await interaction.response.send_message("🔒 Talep 5 saniye içinde kapatılıyor...")

    log_id = db.get_channel_id(guild.id, "log_channel")
    log_channel = guild.get_channel(log_id) if log_id else None
    if log_channel:
        try:
            lines = []
            async for m in channel.history(limit=500, oldest_first=True):
                extra = " ".join(a.url for a in m.attachments)
                lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {m.content} {extra}".rstrip())
            data = "\n".join(lines).encode("utf-8") or b"(bos)"
            await log_channel.send(
                f"📁 **{channel.name}** kapatıldı. Kapatan: {user.mention} — talep sahibi: <@{owner_id}>",
                file=discord.File(io.BytesIO(data), filename=f"{channel.name}.txt"), allowed_mentions=NO_PING,
            )
        except discord.HTTPException:
            pass

    await asyncio.sleep(5)
    tickets.pop(str(channel.id), None)
    db.save_data(guild.id)
    try:
        await channel.delete(reason=f"Ticket kapatıldı: {user}")
    except discord.HTTPException:
        pass


class TicketOpenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:open"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="Destek Talebi Aç", emoji="🎫", style=discord.ButtonStyle.success,
                                           custom_id="ticket:open"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await open_ticket(interaction)


class TicketCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:close"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="Talebi Kapat", emoji="🔒", style=discord.ButtonStyle.danger,
                                           custom_id="ticket:close"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await close_ticket(interaction)


# ---------------------------------------------------------------- Rol paneli
class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"rr:(?P<role>[0-9]+)"):
    def __init__(self, role_id: int, label: str = "Rol"):
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary,
                                           custom_id=f"rr:{role_id}"))
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["role"]), item.label or "Rol")

    async def callback(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        role = guild.get_role(self.role_id) if guild else None
        if role is None:
            return await interaction.response.send_message("⚠️ Bu rol artık yok.", ephemeral=True)
        reason = utils.unsafe_role_reason(guild, role)
        if reason:
            return await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Rol paneli")
                text = f"➖ {role.mention} rolü senden alındı."
            else:
                await member.add_roles(role, reason="Rol paneli")
                text = f"➕ {role.mention} rolü verildi."
        except discord.HTTPException:
            text = "⛔ Rolü ayarlayamadım. Bot rolünün üstte olduğundan emin olun."
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=NO_PING)


class Panels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(TicketOpenButton, TicketCloseButton, RoleButton)

    panel = app_commands.Group(
        name="panel", description="Ticket ve rol panelleri (yönetici)", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @panel.command(name="ticket", description="Destek talebi paneli gönderir")
    @app_commands.describe(kanal="Panelin gönderileceği kanal (boş = bu kanal)", baslik="Başlık", aciklama="Açıklama")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_ticket(self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None,
                           baslik: str = "🎫 Destek", aciklama: str = "Yardıma mı ihtiyacın var? Aşağıdaki butona basarak özel bir destek talebi aç."):
        kanal = kanal or interaction.channel
        embed = discord.Embed(title=baslik[:200], description=aciklama[:1500], color=discord.Color.blurple())
        view = discord.ui.View(timeout=None)
        view.add_item(TicketOpenButton())
        try:
            await kanal.send(embed=embed, view=view)
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ O kanala yazamıyorum.", ephemeral=True)
        await interaction.response.send_message(f"✅ Panel {kanal.mention} kanalına gönderildi.", ephemeral=True)

    @panel.command(name="ticket-ayar", description="Ticket kategorisini ve yetkili rolünü ayarlar")
    @app_commands.describe(kategori="Taleplerin açılacağı kategori", yetkili_rol="Talepleri görecek yetkili rolü",
                           sifirla="Her iki ayarı da sil")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_ticket_ayar(self, interaction: discord.Interaction,
                                kategori: discord.CategoryChannel | None = None,
                                yetkili_rol: discord.Role | None = None, sifirla: bool = False):
        gid = interaction.guild_id
        if sifirla:
            db.set_setting(gid, "ticket_category", None)
            db.set_setting(gid, "ticket_staff_role", None)
            return await interaction.response.send_message("↩️ Ticket ayarları sıfırlandı.", ephemeral=True)
        if kategori:
            db.set_setting(gid, "ticket_category", kategori.id)
        if yetkili_rol:
            db.set_setting(gid, "ticket_staff_role", yetkili_rol.id)
        cat = db.get_channel_id(gid, "ticket_category")
        staff = db.get_channel_id(gid, "ticket_staff_role")
        await interaction.response.send_message(
            f"🎫 **Kategori:** {f'<#{cat}>' if cat else 'yok'}\n**Yetkili rol:** {f'<@&{staff}>' if staff else 'yok'}",
            ephemeral=True, allowed_mentions=NO_PING)

    @panel.command(name="rol", description="Butonla rol alınan panel gönderir")
    @app_commands.describe(baslik="Panel başlığı", kanal="Gönderilecek kanal (boş = bu kanal)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def panel_rol(self, interaction: discord.Interaction, baslik: str, rol1: discord.Role,
                        rol2: discord.Role | None = None, rol3: discord.Role | None = None,
                        rol4: discord.Role | None = None, rol5: discord.Role | None = None,
                        kanal: discord.TextChannel | None = None):
        roles = []
        for r in (rol1, rol2, rol3, rol4, rol5):
            if r is not None and r not in roles:
                roles.append(r)
        for r in roles:
            reason = utils.unsafe_role_reason(interaction.guild, r)
            if reason:
                return await interaction.response.send_message(f"⚠️ {r.name}: {reason}", ephemeral=True)
        kanal = kanal or interaction.channel
        embed = discord.Embed(
            title=baslik[:200],
            description="Aşağıdaki butonlara basarak rol alabilir, tekrar basarak bırakabilirsin.\n\n"
                        + "\n".join(f"• {r.mention}" for r in roles),
            color=discord.Color.blurple(),
        )
        view = discord.ui.View(timeout=None)
        for r in roles:
            view.add_item(RoleButton(r.id, r.name))
        try:
            await kanal.send(embed=embed, view=view)
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ O kanala yazamıyorum.", ephemeral=True)
        await interaction.response.send_message(f"✅ Rol paneli {kanal.mention} kanalına gönderildi.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Panels(bot))
