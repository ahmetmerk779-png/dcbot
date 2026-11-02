"""XP ve seviye sistemi. Veriler Discord sunucusundaki gizli veritabanı kanalında saklanır."""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import db
import helpers
import utils

XP_MIN, XP_MAX = 15, 25
XP_COOLDOWN = 45   # saniye
MIN_LENGTH = 3
NO_PING = discord.AllowedMentions.none()
MEDALS = ["🥇", "🥈", "🥉"]


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_xp = {}

    async def apply_level_roles(self, member: discord.Member, level: int):
        to_add = []
        for lvl, rid in db.level_roles(member.guild.id).items():
            if lvl > level:
                continue
            role = member.guild.get_role(rid)
            if role and not role.managed and role not in member.roles and role < member.guild.me.top_role:
                to_add.append(role)
        if to_add:
            try:
                await member.add_roles(*to_add, reason="Seviye ödülü")
            except discord.HTTPException:
                pass

    async def announce(self, message: discord.Message, level: int):
        cid = db.get_channel_id(message.guild.id, "levelup_channel")
        channel = (message.guild.get_channel(cid) if cid else None) or message.channel
        try:
            await channel.send(
                f"🎉 {message.author.mention} **{level}. seviyeye** yükseldi! (+{25 * level} 🪙)",
                allowed_mentions=discord.AllowedMentions(users=[message.author]),
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not isinstance(message.author, discord.Member):
            return
        if len((message.content or "").strip()) < MIN_LENGTH:
            return
        gid = message.guild.id
        if db.channel_option(gid, utils.config_channel_id(message.channel), "xp") is False:
            return

        now = time.monotonic()
        key = (gid, message.author.id)
        if now - self.last_xp.get(key, 0) < XP_COOLDOWN:
            return
        if len(self.last_xp) > 5000:
            self.last_xp = {k: v for k, v in self.last_xp.items() if now - v < XP_COOLDOWN}
        self.last_xp[key] = now

        m = db.member(gid, message.author.id)
        m["xp"] += random.randint(XP_MIN, XP_MAX)
        m["msgs"] += 1
        level = helpers.level_from_xp(m["xp"])[0]
        if level > m["level"]:
            m["level"] = level
            m["coins"] += 25 * level
            db.save_members(gid)
            await self.announce(message, level)
            await self.apply_level_roles(message.author, level)
        db.save_members(gid)

    # ---------- Komutlar ----------
    @app_commands.command(name="seviye", description="Seviye ve XP durumunu gösterir")
    @app_commands.describe(uye="Üye (boş = sen)")
    @app_commands.guild_only()
    async def seviye(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or interaction.user
        if uye.bot:
            return await interaction.response.send_message("Botların seviyesi yok 🤖", ephemeral=True)
        data = db.all_members(interaction.guild_id)
        m = data.get(str(uye.id), {"xp": 0, "level": 0, "coins": 0, "msgs": 0})
        level, current, need = helpers.level_from_xp(m.get("xp", 0))
        rank = 1 + sum(1 for v in data.values() if v.get("xp", 0) > m.get("xp", 0))
        embed = discord.Embed(title=f"📈 {uye.display_name}", color=uye.color or discord.Color.blurple())
        embed.set_thumbnail(url=uye.display_avatar.url)
        embed.add_field(name="Seviye", value=str(level))
        embed.add_field(name="Sıralama", value=f"#{rank}")
        embed.add_field(name="Mesaj", value=str(m.get("msgs", 0)))
        embed.add_field(name=f"XP: {current}/{need}", value=helpers.progress_bar(current, need), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="liderlik", description="XP sıralamasında ilk 10 kişiyi gösterir")
    @app_commands.guild_only()
    async def liderlik(self, interaction: discord.Interaction):
        data = db.all_members(interaction.guild_id)
        top = sorted(((uid, v) for uid, v in data.items() if v.get("xp", 0) > 0),
                     key=lambda kv: kv[1]["xp"], reverse=True)[:10]
        if not top:
            return await interaction.response.send_message("Henüz kimse XP kazanmadı.", ephemeral=True)
        lines = []
        for i, (uid, v) in enumerate(top):
            medal = MEDALS[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{medal} <@{uid}> — seviye **{helpers.level_from_xp(v['xp'])[0]}** ({v['xp']} XP)")
        embed = discord.Embed(title="🏆 XP Liderlik Tablosu", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, allowed_mentions=NO_PING)

    seviye_rol = app_commands.Group(
        name="seviye-rol", description="Seviye ödülü rolleri (yönetici)", guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @seviye_rol.command(name="ekle", description="Bir seviyeye ulaşanlara verilecek rolü ayarlar")
    @app_commands.describe(seviye="Gereken seviye", rol="Verilecek rol")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def seviye_rol_ekle(self, interaction: discord.Interaction, seviye: app_commands.Range[int, 1, 200],
                              rol: discord.Role):
        reason = utils.unsafe_role_reason(interaction.guild, rol)
        if reason:
            return await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
        db.set_level_role(interaction.guild_id, seviye, rol.id)
        await interaction.response.send_message(
            f"✅ **{seviye}. seviyeye** ulaşanlara {rol.mention} verilecek.", ephemeral=True, allowed_mentions=NO_PING)

    @seviye_rol.command(name="sil", description="Bir seviye ödülünü kaldırır")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def seviye_rol_sil(self, interaction: discord.Interaction, seviye: app_commands.Range[int, 1, 200]):
        db.set_level_role(interaction.guild_id, seviye, None)
        await interaction.response.send_message(f"🗑️ {seviye}. seviye ödülü kaldırıldı.", ephemeral=True)

    @seviye_rol.command(name="liste", description="Seviye ödüllerini listeler")
    async def seviye_rol_liste(self, interaction: discord.Interaction):
        roles = db.level_roles(interaction.guild_id)
        if not roles:
            return await interaction.response.send_message("Seviye ödülü ayarlanmamış.", ephemeral=True)
        lines = [f"**{lvl}. seviye** → <@&{rid}>" for lvl, rid in sorted(roles.items())]
        await interaction.response.send_message("\n".join(lines), ephemeral=True, allowed_mentions=NO_PING)

    @app_commands.command(name="xp-ayarla", description="Bir üyenin XP değerini ayarlar (yönetici)")
    @app_commands.describe(uye="Üye", xp="Yeni toplam XP")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def xp_ayarla(self, interaction: discord.Interaction, uye: discord.Member,
                        xp: app_commands.Range[int, 0, 10_000_000]):
        if uye.bot:
            return await interaction.response.send_message("Botlara XP verilemez.", ephemeral=True)
        m = db.member(interaction.guild_id, uye.id)
        m["xp"] = xp
        m["level"] = helpers.level_from_xp(xp)[0]
        db.save_members(interaction.guild_id)
        await self.apply_level_roles(uye, m["level"])
        await interaction.response.send_message(
            f"✅ {uye.mention} → **{xp} XP** (seviye {m['level']})", ephemeral=True, allowed_mentions=NO_PING)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
