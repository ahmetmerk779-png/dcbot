"""Çekiliş sistemi (buton ile katılım). Veriler Discord veritabanı kanalında saklanır."""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import helpers

MIN_SECONDS, MAX_SECONDS = 10, 30 * 86400
KEEP_ENDED_SECONDS = 14 * 86400
NO_PING = discord.AllowedMentions.none()


class JoinButton(discord.ui.DynamicItem[discord.ui.Button], template=r"giveaway:join"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="Katıl", emoji="🎉", style=discord.ButtonStyle.primary,
                                           custom_id="giveaway:join"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild_id is None or interaction.message is None:
            return
        g = db.get_data(interaction.guild_id).get("giveaways", {}).get(str(interaction.message.id))
        if not g or g.get("ended"):
            return await interaction.response.send_message("⌛ Bu çekiliş sona erdi.", ephemeral=True)
        uid = interaction.user.id
        if uid in g["entries"]:
            g["entries"].remove(uid)
            text = "👋 Çekilişten ayrıldın."
        else:
            g["entries"].append(uid)
            text = f"🎉 Çekilişe katıldın! Toplam katılımcı: **{len(g['entries'])}**"
        db.save_data(interaction.guild_id)
        await interaction.response.send_message(text, ephemeral=True)


def _embed(g, ended=False, winners=None):
    if ended:
        text = ", ".join(f"<@{u}>" for u in winners) if winners else "Katılımcı yok 😢"
        embed = discord.Embed(title="🎉 ÇEKİLİŞ BİTTİ", description=f"**Ödül:** {g['prize']}\n**Kazanan:** {text}",
                              color=discord.Color.dark_grey())
        embed.set_footer(text=f"{len(g['entries'])} katılımcı")
    else:
        embed = discord.Embed(
            title="🎉 ÇEKİLİŞ", color=discord.Color.gold(),
            description=(f"**Ödül:** {g['prize']}\n**Kazanan sayısı:** {g['winners']}\n"
                         f"**Bitiş:** <t:{g['end']}:R>\n**Düzenleyen:** <@{g['host']}>\n\nKatılmak için 🎉 butonuna bas!"),
        )
    return embed


class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(JoinButton)
        self.check_loop.start()

    async def cog_unload(self):
        self.check_loop.cancel()

    @tasks.loop(seconds=15)
    async def check_loop(self):
        now = int(time.time())
        for guild in self.bot.guilds:
            if guild.id not in db.store.loaded:
                continue
            giveaways = db.get_data(guild.id).get("giveaways", {})
            for mid, g in list(giveaways.items()):
                if g.get("ended"):
                    if g["end"] < now - KEEP_ENDED_SECONDS:
                        giveaways.pop(mid, None)
                        db.save_data(guild.id)
                elif g["end"] <= now:
                    try:
                        await self.finish(guild, mid)
                    except Exception as e:
                        print("Çekiliş bitirme hatası:", repr(e))

    @check_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def finish(self, guild: discord.Guild, mid: str):
        g = db.get_data(guild.id)["giveaways"][mid]
        pool = [uid for uid in g["entries"] if guild.get_member(uid)]
        winners = random.sample(pool, min(g["winners"], len(pool)))
        g["ended"] = True
        g["winner_ids"] = winners
        db.save_data(guild.id)  # önce kaydet, ağ hatası olsa da tekrar bitirilmesin

        channel = guild.get_channel(g["channel_id"])
        if channel is None:
            return winners
        try:
            message = await channel.fetch_message(int(mid))
            await message.edit(embed=_embed(g, ended=True, winners=winners), view=None)
        except discord.HTTPException:
            pass
        try:
            if winners:
                await channel.send(
                    f"🎉 Tebrikler {', '.join(f'<@{u}>' for u in winners)}! **{g['prize']}** kazandınız!",
                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=u) for u in winners]))
            else:
                await channel.send(f"😢 **{g['prize']}** çekilişine kimse katılmadı.")
        except discord.HTTPException:
            pass
        return winners

    cekilis = app_commands.Group(
        name="cekilis", description="Çekiliş yönetimi", guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @cekilis.command(name="baslat", description="Yeni bir çekiliş başlatır")
    @app_commands.describe(odul="Ödül", sure="Süre: 10m, 2sa, 1g, 1sa 30dk gibi", kazanan="Kazanan sayısı",
                           kanal="Kanal (boş = bu kanal)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def baslat(self, interaction: discord.Interaction, odul: app_commands.Range[str, 1, 200], sure: str,
                     kazanan: app_commands.Range[int, 1, 20] = 1, kanal: discord.TextChannel | None = None):
        seconds = helpers.parse_duration(sure)
        if seconds is None or not (MIN_SECONDS <= seconds <= MAX_SECONDS):
            return await interaction.response.send_message(
                "⚠️ Süre geçersiz. Örnek: `30m`, `2sa`, `1g`, `1sa 30dk` (10 saniye - 30 gün).", ephemeral=True)
        kanal = kanal or interaction.channel
        g = {"channel_id": kanal.id, "prize": odul, "end": int(time.time()) + seconds, "winners": kazanan,
             "host": interaction.user.id, "entries": [], "ended": False}
        view = discord.ui.View(timeout=None)
        view.add_item(JoinButton())
        try:
            message = await kanal.send(embed=_embed(g), view=view)
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ O kanala yazamıyorum.", ephemeral=True)
        db.get_data(interaction.guild_id).setdefault("giveaways", {})[str(message.id)] = g
        db.save_data(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ Çekiliş başladı: {message.jump_url}\nSüre: {helpers.format_duration(seconds)}", ephemeral=True)

    @cekilis.command(name="bitir", description="Çekilişi şimdi bitirir")
    @app_commands.describe(mesaj_id="Çekiliş mesajının ID'si")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bitir(self, interaction: discord.Interaction, mesaj_id: str):
        g = db.get_data(interaction.guild_id).get("giveaways", {}).get(mesaj_id.strip())
        if not g:
            return await interaction.response.send_message("⚠️ Böyle bir çekiliş yok.", ephemeral=True)
        if g.get("ended"):
            return await interaction.response.send_message("⚠️ Bu çekiliş zaten bitti. `/cekilis yeniden` kullan.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.finish(interaction.guild, mesaj_id.strip())
        await interaction.followup.send("✅ Çekiliş bitirildi.", ephemeral=True)

    @cekilis.command(name="yeniden", description="Bitmiş çekilişte yeniden kazanan seçer")
    @app_commands.describe(mesaj_id="Çekiliş mesajının ID'si")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def yeniden(self, interaction: discord.Interaction, mesaj_id: str):
        g = db.get_data(interaction.guild_id).get("giveaways", {}).get(mesaj_id.strip())
        if not g or not g.get("ended"):
            return await interaction.response.send_message("⚠️ Bitmiş böyle bir çekiliş yok.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.finish(interaction.guild, mesaj_id.strip())
        await interaction.followup.send("🔁 Yeni kazananlar seçildi.", ephemeral=True)

    @cekilis.command(name="liste", description="Devam eden çekilişleri listeler")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def liste(self, interaction: discord.Interaction):
        items = [(mid, g) for mid, g in db.get_data(interaction.guild_id).get("giveaways", {}).items()
                 if not g.get("ended")]
        if not items:
            return await interaction.response.send_message("Devam eden çekiliş yok.", ephemeral=True)
        lines = [f"`{mid}` — **{g['prize']}** — <#{g['channel_id']}> — bitiş <t:{g['end']}:R>" for mid, g in items]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
