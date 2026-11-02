"""Moderasyon / komutları."""
import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

NO_PING = discord.AllowedMentions.none()


async def _send(interaction: discord.Interaction, result):
    ok, msg = result
    await interaction.response.send_message(msg, ephemeral=not ok, allowed_mentions=NO_PING)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- Ban / Kick ----------
    @app_commands.command(name="ban", description="Bir üyeyi sunucudan yasaklar")
    @app_commands.describe(kullanici="Yasaklanacak üye", sebep="Sebep", mesaj_sil_gun="Son kaç günün mesajları silinsin (0-7)")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, kullanici: discord.Member,
                  sebep: str = "Sebep belirtilmedi", mesaj_sil_gun: app_commands.Range[int, 0, 7] = 0):
        await _send(interaction, await utils.do_ban(interaction.guild, interaction.user, kullanici, sebep, mesaj_sil_gun))

    @app_commands.command(name="unban", description="Yasağı kaldırır (kullanıcı ID'si ile)")
    @app_commands.describe(kullanici_id="Yasağı kaldırılacak kullanıcının ID'si")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, kullanici_id: str):
        try:
            uid = int(kullanici_id.strip())
        except ValueError:
            return await interaction.response.send_message("⚠️ Geçerli bir kullanıcı ID'si gir.", ephemeral=True)
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"{interaction.user}: unban")
        except discord.NotFound:
            return await interaction.response.send_message("⚠️ Bu kullanıcı yasaklı değil.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message("⛔ Yetkim yetmiyor.", ephemeral=True)
        await utils.log_action(
            interaction.guild, "✅ Yasak kaldırıldı", f"**Kullanıcı ID:** {uid}\n**Yetkili:** {interaction.user.mention}",
            discord.Color.green(),
        )
        await interaction.response.send_message(f"✅ `{uid}` kullanıcısının yasağı kaldırıldı.")

    @app_commands.command(name="kick", description="Bir üyeyi sunucudan atar")
    @app_commands.describe(kullanici="Atılacak üye", sebep="Sebep")
    @app_commands.guild_only()
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, kullanici: discord.Member, sebep: str = "Sebep belirtilmedi"):
        await _send(interaction, await utils.do_kick(interaction.guild, interaction.user, kullanici, sebep))

    # ---------- Susturma ----------
    @app_commands.command(name="sustur", description="Bir üyeyi belirli süre susturur (timeout)")
    @app_commands.describe(kullanici="Susturulacak üye", sure="Dakika cinsinden süre (en fazla 40320 = 28 gün)", sebep="Sebep")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def sustur(self, interaction: discord.Interaction, kullanici: discord.Member,
                     sure: app_commands.Range[int, 1, 40320] = 10, sebep: str = "Sebep belirtilmedi"):
        await _send(interaction, await utils.do_timeout(interaction.guild, interaction.user, kullanici, sure, sebep))

    @app_commands.command(name="sustur-kaldir", description="Bir üyenin susturmasını kaldırır")
    @app_commands.describe(kullanici="Susturması kaldırılacak üye")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def sustur_kaldir(self, interaction: discord.Interaction, kullanici: discord.Member):
        await _send(interaction, await utils.do_untimeout(interaction.guild, interaction.user, kullanici))

    # ---------- Uyarılar ----------
    @app_commands.command(name="uyar", description="Bir üyeyi uyarır (her 3 uyarıda 1 saat otomatik susturma)")
    @app_commands.describe(kullanici="Uyarılacak üye", sebep="Sebep")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def uyar(self, interaction: discord.Interaction, kullanici: discord.Member, sebep: str = "Sebep belirtilmedi"):
        await _send(interaction, await utils.do_warn(interaction.guild, interaction.user, kullanici, sebep))

    @app_commands.command(name="uyarilar", description="Bir üyenin uyarı geçmişini gösterir")
    @app_commands.describe(kullanici="Üye")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def uyarilar(self, interaction: discord.Interaction, kullanici: discord.Member):
        rows = db.list_warnings(interaction.guild_id, kullanici.id)
        if not rows:
            return await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısının uyarısı yok.", ephemeral=True, allowed_mentions=NO_PING)
        lines = [f"`#{r['id']}` <t:{r['created_at']}:d> — <@{r['mod_id']}>: {r['reason']}" for r in rows]
        embed = discord.Embed(title=f"⚠️ {kullanici.display_name} uyarıları ({len(rows)})", description="\n".join(lines)[:4000], color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="uyari-sil", description="Tek bir uyarıyı ID'si ile siler")
    @app_commands.describe(uyari_id="Silinecek uyarının numarası (/uyarilar ile görürsün)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def uyari_sil(self, interaction: discord.Interaction, uyari_id: int):
        if db.delete_warning(interaction.guild_id, uyari_id):
            await interaction.response.send_message(f"🗑️ `#{uyari_id}` numaralı uyarı silindi.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Böyle bir uyarı bulunamadı.", ephemeral=True)

    @app_commands.command(name="uyari-temizle", description="Bir üyenin tüm uyarılarını siler")
    @app_commands.describe(kullanici="Üye")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    async def uyari_temizle(self, interaction: discord.Interaction, kullanici: discord.Member):
        n = db.clear_warnings(interaction.guild_id, kullanici.id)
        await interaction.response.send_message(f"🗑️ {kullanici.mention} için {n} uyarı silindi.", ephemeral=True, allowed_mentions=NO_PING)

    # ---------- Kanal yönetimi ----------
    @app_commands.command(name="temizle", description="Bu kanaldaki son mesajları siler")
    @app_commands.describe(adet="Taranacak mesaj sayısı (1-100)", kullanici="Sadece bu üyenin mesajlarını sil")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    async def temizle(self, interaction: discord.Interaction, adet: app_commands.Range[int, 1, 100],
                      kullanici: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, msg = await utils.do_purge(interaction.channel, interaction.user, adet, kullanici)
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="yavas-mod", description="Bu kanalın yavaş modunu ayarlar (0 = kapat)")
    @app_commands.describe(saniye="Mesajlar arası bekleme süresi (0-21600 sn)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def yavas_mod(self, interaction: discord.Interaction, saniye: app_commands.Range[int, 0, 21600]):
        await _send(interaction, await utils.do_slowmode(interaction.channel, interaction.user, saniye))

    @app_commands.command(name="kilitle", description="Bu kanalı kilitler (üyeler yazamaz)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def kilitle(self, interaction: discord.Interaction):
        await _send(interaction, await utils.do_lock(interaction.channel, interaction.user, True))

    @app_commands.command(name="kilidi-ac", description="Bu kanalın kilidini açar")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def kilidi_ac(self, interaction: discord.Interaction):
        await _send(interaction, await utils.do_lock(interaction.channel, interaction.user, False))


async def setup(bot):
    await bot.add_cog(Moderation(bot))
