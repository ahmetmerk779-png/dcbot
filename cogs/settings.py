"""Yönetici ayarları: /ayar ...  (sunucu geneli)"""
import discord
from discord import app_commands
from discord.ext import commands

import db
from cogs.welcome import DEFAULT_GOODBYE, DEFAULT_WELCOME

KANAL_TURLERI = [
    app_commands.Choice(name="Karşılama kanalı", value="welcome_channel"),
    app_commands.Choice(name="Görüşürüz kanalı", value="goodbye_channel"),
    app_commands.Choice(name="Moderasyon log kanalı", value="log_channel"),
    app_commands.Choice(name="Seviye atlama duyuru kanalı", value="levelup_channel"),
]
MESAJ_TURLERI = [
    app_commands.Choice(name="Karşılama mesajı", value="welcome_msg"),
    app_commands.Choice(name="Görüşürüz mesajı", value="goodbye_msg"),
]
OTOMOD_TURLERI = [
    app_commands.Choice(name="Davet bağlantıları", value="am_invites"),
    app_commands.Choice(name="Tüm bağlantılar", value="am_links"),
    app_commands.Choice(name="Spam", value="am_spam"),
    app_commands.Choice(name="Yasaklı kelimeler", value="am_badwords"),
]
ISLEMLER = [
    app_commands.Choice(name="Ekle", value="ekle"),
    app_commands.Choice(name="Sil", value="sil"),
    app_commands.Choice(name="Listele", value="liste"),
]
ETIKETLER = {c.value: c.name for c in KANAL_TURLERI + OTOMOD_TURLERI}


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Settings(commands.GroupCog, group_name="ayar", group_description="Bot ayarları (yönetici)"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kanal", description="Özel kanalları ayarlar (kanal seçmezsen özellik kapanır)")
    @app_commands.describe(tur="Hangi kanal ayarlanacak", kanal="Kanal (boş bırakırsan kapatılır)")
    @app_commands.choices(tur=KANAL_TURLERI)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def kanal(self, interaction: discord.Interaction, tur: app_commands.Choice[str],
                    kanal: discord.TextChannel | None = None):
        db.set_setting(interaction.guild_id, tur.value, kanal.id if kanal else None)
        if kanal:
            await interaction.response.send_message(f"✅ **{tur.name}** → {kanal.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"🚫 **{tur.name}** kapatıldı.", ephemeral=True)

    @app_commands.command(name="mesaj", description="Karşılama / görüşürüz mesajını özelleştirir")
    @app_commands.describe(
        tur="Hangi mesaj",
        metin="Yer tutucular: {user} {name} {server} {count}. Boş bırakırsan varsayılana döner.",
    )
    @app_commands.choices(tur=MESAJ_TURLERI)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mesaj(self, interaction: discord.Interaction, tur: app_commands.Choice[str], metin: str | None = None):
        db.set_setting(interaction.guild_id, tur.value, metin[:1000] if metin else None)
        if metin:
            await interaction.response.send_message(f"✅ **{tur.name}** güncellendi:\n{metin[:1000]}", ephemeral=True)
        else:
            await interaction.response.send_message(f"↩️ **{tur.name}** varsayılana döndü.", ephemeral=True)

    @app_commands.command(name="otorol", description="Sunucuya katılanlara otomatik verilecek rolü ayarlar")
    @app_commands.describe(rol="Rol (boş bırakırsan kapatılır)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def otorol(self, interaction: discord.Interaction, rol: discord.Role | None = None):
        if rol and rol >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "⚠️ Bu rol benim rolümden yüksek veya eşit. Bot rolünü yukarı taşı.", ephemeral=True)
        db.set_setting(interaction.guild_id, "autorole", rol.id if rol else None)
        text = f"✅ Otomatik rol: {rol.mention}" if rol else "🚫 Otomatik rol kapatıldı."
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="otomod", description="Otomatik moderasyonu sunucu genelinde açar/kapatır")
    @app_commands.describe(ozellik="Özellik", acik="Açık mı?")
    @app_commands.choices(ozellik=OTOMOD_TURLERI)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def otomod(self, interaction: discord.Interaction, ozellik: app_commands.Choice[str], acik: bool):
        db.set_setting(interaction.guild_id, ozellik.value, "1" if acik else None)
        await interaction.response.send_message(
            f"{'🟢 Açıldı' if acik else '🔴 Kapatıldı'}: **{ozellik.name}**\n"
            "ℹ️ Mesajları yönet yetkisi olanlar filtrelerden muaftır. Tek bir kanalda farklı olsun istersen "
            "`/kanal ozellik` kullan.", ephemeral=True)

    @app_commands.command(name="kufur", description="Yasaklı kelime listesini yönetir")
    @app_commands.describe(islem="Ne yapılacak", kelime="Kelime (ekle/sil için)")
    @app_commands.choices(islem=ISLEMLER)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def kufur(self, interaction: discord.Interaction, islem: app_commands.Choice[str], kelime: str | None = None):
        gid = interaction.guild_id
        if islem.value == "liste":
            words = db.list_badwords(gid)
            text = "📃 Yasaklı kelimeler: " + (", ".join(f"`{w}`" for w in words) if words else "yok")
            return await interaction.response.send_message(text[:1900], ephemeral=True)
        if not kelime or len(kelime.strip()) < 2:
            return await interaction.response.send_message("⚠️ En az 2 harfli bir kelime yaz.", ephemeral=True)
        word = kelime.strip().casefold()
        if islem.value == "ekle":
            db.add_badword(gid, word)
            await interaction.response.send_message(f"✅ Eklendi: `{word}`", ephemeral=True)
        else:
            ok = db.remove_badword(gid, word)
            await interaction.response.send_message("🗑️ Silindi." if ok else "⚠️ Listede yok.", ephemeral=True)

    @app_commands.command(name="kisilik", description="Yapay zekanın bu sunucudaki kişiliğini ayarlar")
    @app_commands.describe(metin="Örn: 'Sen esprili bir korsansın.' Boş bırakırsan varsayılana döner.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def kisilik(self, interaction: discord.Interaction, metin: app_commands.Range[str, 10, 800] | None = None):
        db.set_setting(interaction.guild_id, "ai_persona", metin)
        if metin:
            await interaction.response.send_message(f"🎭 Kişilik güncellendi:\n{metin}", ephemeral=True)
        else:
            await interaction.response.send_message("↩️ Kişilik varsayılana döndü.", ephemeral=True)

    @app_commands.command(name="goster", description="Mevcut sunucu ayarlarını gösterir")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def goster(self, interaction: discord.Interaction):
        gid = interaction.guild_id

        def ch(key):
            cid = db.get_channel_id(gid, key)
            return f"<#{cid}>" if cid else "kapalı"

        def on(key):
            return "🟢 açık" if db.flag(gid, key) else "🔴 kapalı"

        role_id = db.get_setting(gid, "autorole")
        embed = discord.Embed(title="⚙️ Sunucu ayarları", color=discord.Color.blurple())
        embed.add_field(name="Kanallar", value="\n".join(f"**{ETIKETLER[k]}:** {ch(k)}" for k in
                        ("welcome_channel", "goodbye_channel", "log_channel", "levelup_channel")), inline=False)
        embed.add_field(name="Otomod (sunucu geneli)", value="\n".join(f"**{ETIKETLER[k]}:** {on(k)}" for k in
                        ("am_invites", "am_links", "am_spam", "am_badwords")), inline=False)
        embed.add_field(name="Otomatik rol", value=f"<@&{role_id}>" if role_id else "kapalı", inline=False)
        embed.add_field(name="Karşılama mesajı", value=db.get_setting(gid, "welcome_msg", DEFAULT_WELCOME)[:500], inline=False)
        embed.add_field(name="Görüşürüz mesajı", value=db.get_setting(gid, "goodbye_msg", DEFAULT_GOODBYE)[:500], inline=False)
        persona = db.get_setting(gid, "ai_persona")
        embed.add_field(name="Yapay zeka kişiliği", value=persona[:500] if persona else "varsayılan", inline=False)
        embed.set_footer(text="Kanala özel ayarlar için: /kanal liste ve /kanal goster")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))
