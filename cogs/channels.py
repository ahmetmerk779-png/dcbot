"""Kanal bazlı ayarlar: /kanal ...  (bot hangi kanalda ne yapacak)"""
import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

AI_MODLARI = [
    app_commands.Choice(name="Kapalı (bu kanalda yapay zeka cevap vermez)", value="off"),
    app_commands.Choice(name="Sadece etiketlenince cevap ver", value="mention"),
    app_commands.Choice(name="Her mesaja cevap ver (sohbet kanalı)", value="always"),
]
OZELLIKLER = [
    app_commands.Choice(name="XP / seviye kazanımı", value="xp"),
    app_commands.Choice(name="Ekonomi komutları (/bakiye, /slot ...)", value="economy"),
    app_commands.Choice(name="Otomod (genel anahtar)", value="automod"),
    app_commands.Choice(name="Sadece medya/bağlantı kanalı", value="media_only"),
    app_commands.Choice(name="Davet bağlantısı filtresi", value="am_invites"),
    app_commands.Choice(name="Bağlantı filtresi", value="am_links"),
    app_commands.Choice(name="Spam filtresi", value="am_spam"),
    app_commands.Choice(name="Yasaklı kelime filtresi", value="am_badwords"),
]
SIFIRLA_SECENEKLERI = [app_commands.Choice(name="Yapay zeka modu", value="ai")] + OZELLIKLER
AI_ETIKET = {"off": "🔴 kapalı", "mention": "🟡 sadece etiketlenince", "always": "🟢 her mesaja cevap"}
AUTOMOD_KEYS = ("am_invites", "am_links", "am_spam", "am_badwords")
ADLAR = {c.value: c.name for c in SIFIRLA_SECENEKLERI}


def onoff(value) -> str:
    return "🟢 açık" if value else "🔴 kapalı"


def describe(guild_id: int, channel_id: int) -> str:
    ov = db.channel_overrides(guild_id, channel_id)

    def tag(key):
        return " ✏️" if key in ov else ""

    ai = db.channel_option(guild_id, channel_id, "ai")
    lines = [
        f"🧠 **Yapay zeka:** {AI_ETIKET.get(ai, ai)}{tag('ai')}",
        f"📈 **XP kazanımı:** {onoff(db.channel_option(guild_id, channel_id, 'xp'))}{tag('xp')}",
        f"🪙 **Ekonomi komutları:** {onoff(db.channel_option(guild_id, channel_id, 'economy'))}{tag('economy')}",
        f"🖼️ **Sadece medya/bağlantı:** {onoff(db.channel_option(guild_id, channel_id, 'media_only'))}{tag('media_only')}",
    ]
    automod_on = db.channel_option(guild_id, channel_id, "automod") is not False
    lines.append(f"🛡️ **Otomod:** {onoff(automod_on)}{tag('automod')}")
    if automod_on:
        for key in AUTOMOD_KEYS:
            lines.append(f"　• {ADLAR[key]}: {onoff(db.automod_flag(guild_id, channel_id, key))}{tag(key)}")
    lines.append("\n✏️ = bu kanala özel ayar. İşaretsizler varsayılan / sunucu ayarıdır.")
    return "\n".join(lines)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Channels(commands.GroupCog, group_name="kanal", group_description="Kanal bazlı bot ayarları (yönetici)"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ai", description="Bir kanalda yapay zekanın nasıl davranacağını ayarlar")
    @app_commands.describe(kanal="Ayarlanacak kanal", mod="Yapay zeka modu")
    @app_commands.choices(mod=AI_MODLARI)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ai(self, interaction: discord.Interaction, kanal: discord.TextChannel, mod: app_commands.Choice[str]):
        db.set_channel_option(interaction.guild_id, kanal.id, "ai", mod.value)
        await interaction.response.send_message(f"✅ {kanal.mention} → yapay zeka: **{mod.name}**", ephemeral=True)

    @app_commands.command(name="ozellik", description="Bir kanalda bir özelliği açar veya kapatır")
    @app_commands.describe(kanal="Ayarlanacak kanal", ozellik="Özellik", acik="Açık mı?")
    @app_commands.choices(ozellik=OZELLIKLER)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ozellik(self, interaction: discord.Interaction, kanal: discord.TextChannel,
                      ozellik: app_commands.Choice[str], acik: bool):
        db.set_channel_option(interaction.guild_id, kanal.id, ozellik.value, bool(acik))
        await interaction.response.send_message(
            f"{'🟢 Açıldı' if acik else '🔴 Kapatıldı'}: **{ozellik.name}** → {kanal.mention}", ephemeral=True)

    @app_commands.command(name="sifirla", description="Kanalın özel ayarlarını varsayılana döndürür")
    @app_commands.describe(kanal="Kanal", ozellik="Sadece bu ayarı sıfırla (boş = hepsi)")
    @app_commands.choices(ozellik=SIFIRLA_SECENEKLERI)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sifirla(self, interaction: discord.Interaction, kanal: discord.TextChannel,
                      ozellik: app_commands.Choice[str] | None = None):
        if ozellik is None:
            db.reset_channel(interaction.guild_id, kanal.id)
            text = f"↩️ {kanal.mention} kanalının tüm özel ayarları silindi."
        else:
            db.set_channel_option(interaction.guild_id, kanal.id, ozellik.value, None)
            text = f"↩️ {kanal.mention} → **{ozellik.name}** varsayılana döndü."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="goster", description="Bir kanalda botun hangi özelliklerinin açık olduğunu gösterir")
    @app_commands.describe(kanal="Kanal (boş = bu kanal)")
    async def goster(self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None):
        cid = kanal.id if kanal else utils.config_channel_id(interaction.channel)
        embed = discord.Embed(
            title="📍 Kanal ayarları", description=f"<#{cid}>\n\n{describe(interaction.guild_id, cid)}",
            color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="liste", description="Özel ayarı olan tüm kanalları listeler")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def liste(self, interaction: discord.Interaction):
        configured = db.list_configured_channels(interaction.guild_id)
        if not configured:
            return await interaction.response.send_message(
                "Hiçbir kanalda özel ayar yok. `/kanal ai` veya `/kanal ozellik` ile başlayabilirsin.", ephemeral=True)
        lines = []
        for cid, opts in configured.items():
            parts = []
            for key, value in opts.items():
                if key == "ai":
                    parts.append(f"yapay zeka: {AI_ETIKET.get(value, value)}")
                else:
                    parts.append(f"{ADLAR.get(key, key)}: {'açık' if value else 'kapalı'}")
            lines.append(f"<#{cid}> — " + "; ".join(parts))
        embed = discord.Embed(title="📍 Özel ayarlı kanallar", description="\n".join(lines)[:4000],
                              color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Channels(bot))
