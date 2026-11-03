"""Veritabanı yönetimi: /veritabani durum | kaydet | yedek | geri-yukle
Veriler Discord sunucusundaki gizli #bot-veritabani kanalında saklanır."""
import io
import json

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

BELGELER = [
    app_commands.Choice(name="config (ayarlar, kanallar, market)", value="config"),
    app_commands.Choice(name="members (XP, altın)", value="members"),
    app_commands.Choice(name="data (uyarılar, ticket, çekiliş)", value="data"),
]
MAX_RESTORE_BYTES = 8_000_000


@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
class DatabaseCog(commands.GroupCog, group_name="veritabani", group_description="Bot veritabanı (yönetici)"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="durum", description="Veritabanının durumunu gösterir")
    @app_commands.checks.has_permissions(administrator=True)
    async def durum(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        store = db.store
        persistent = store.persistent.get(gid, False)
        channel = store.channels.get(gid)
        sizes = {name: len(raw) for name, raw in store.export(gid).items()}
        pending = sum(1 for k in store.dirty if k[0] == gid)
        embed = discord.Embed(title="🗄️ Veritabanı", color=discord.Color.green() if persistent else discord.Color.red())
        embed.add_field(name="Kayıt durumu",
                        value="🟢 Discord kanalına kaydediliyor" if persistent else
                              "🔴 KAYDEDİLMİYOR (sadece bellekte). Botun kanal oluşturma/yazma izni var mı?", inline=False)
        embed.add_field(name="Kanal", value=channel.mention if channel else "yok")
        embed.add_field(name="Bekleyen yazma", value=str(pending))
        embed.add_field(name="Belge boyutları", value="\n".join(f"`{n}`: {s / 1024:.1f} KB" for n, s in sizes.items()), inline=False)
        embed.add_field(name="Kayıtlar",
                        value=f"👥 {len(db.all_members(gid))} üye • ⚠️ {len(db.get_data(gid).get('warnings', []))} uyarı • "
                              f"📍 {len(db.list_configured_channels(gid))} özel kanal", inline=False)
        embed.set_footer(text="#bot-veritabani kanalını silme ve içindeki mesajları düzenleme!")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="kaydet", description="Bekleyen verileri hemen Discord'a yazar")
    @app_commands.checks.has_permissions(administrator=True)
    async def kaydet(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild_id
        for name in db.DOCS:
            db.store.mark(gid, name)
        await db.store.flush()
        ok = db.store.persistent.get(gid, False)
        await interaction.followup.send("💾 Kaydedildi." if ok else "⚠️ Kayıt yapılamadı (veritabanı kanalı yok).", ephemeral=True)

    @app_commands.command(name="yedek", description="Tüm verilerin JSON yedeğini sana gönderir")
    @app_commands.checks.has_permissions(administrator=True)
    async def yedek(self, interaction: discord.Interaction):
        files = [discord.File(io.BytesIO(raw), filename=f"{name}.json")
                 for name, raw in db.store.export(interaction.guild_id).items()]
        await interaction.response.send_message("📦 Yedek dosyaların (sadece sana görünür):", files=files, ephemeral=True)

    @app_commands.command(name="geri-yukle", description="Yedek JSON dosyasından bir belgeyi geri yükler")
    @app_commands.describe(belge="Hangi belge", dosya="Yedek .json dosyası")
    @app_commands.choices(belge=BELGELER)
    @app_commands.checks.has_permissions(administrator=True)
    async def geri_yukle(self, interaction: discord.Interaction, belge: app_commands.Choice[str],
                         dosya: discord.Attachment):
        if dosya.size > MAX_RESTORE_BYTES:
            return await interaction.response.send_message("⚠️ Dosya çok büyük.", ephemeral=True)
        try:
            data = json.loads((await dosya.read()).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return await interaction.response.send_message("⚠️ Geçerli bir yedek JSON dosyası değil.", ephemeral=True)

        gid = interaction.guild_id

        async def apply(i: discord.Interaction):
            db.store.cache.setdefault(gid, {})[belge.value] = data
            db.store.mark(gid, belge.value)
            await db.store.flush()
            return True, f"✅ **{belge.name}** geri yüklendi."

        view = utils.ConfirmView(interaction.user.id, apply)
        await interaction.response.send_message(
            f"⚠️ **{belge.name}** belgesinin üzerine yazılacak. Mevcut veriler kaybolur. Emin misin?",
            view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot):
    await bot.add_cog(DatabaseCog(bot))
