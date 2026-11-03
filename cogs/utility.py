"""Genel araçlar: ping, sunucu/kullanıcı bilgisi, anket, hatırlatıcı, AFK, zar..."""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import helpers

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
MAX_REMINDERS = 20


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    # ---------- Hatırlatıcılar ----------
    @tasks.loop(seconds=15)
    async def reminder_loop(self):
        now = int(time.time())
        for guild in self.bot.guilds:
            if guild.id not in db.store.loaded:
                continue
            data = db.get_data(guild.id)
            items = data.get("reminders", [])
            due = [r for r in items if r["at"] <= now]
            if not due:
                continue
            data["reminders"] = [r for r in items if r["at"] > now]
            db.save_data(guild.id)
            for r in due:
                await self.deliver(guild, r)

    @reminder_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def deliver(self, guild, r):
        text = f"⏰ <@{r['user_id']}> hatırlatma: **{r['text']}**"
        mentions = discord.AllowedMentions(users=[discord.Object(id=r["user_id"])])
        channel = guild.get_channel(r["channel_id"])
        try:
            if channel is None:
                raise discord.HTTPException
            await channel.send(text, allowed_mentions=mentions)
        except discord.HTTPException:
            member = guild.get_member(r["user_id"])
            if member:
                try:
                    await member.send(f"⏰ Hatırlatma: **{r['text']}** ({guild.name})")
                except discord.HTTPException:
                    pass

    @app_commands.command(name="hatirlat", description="Belirli süre sonra seni hatırlatır")
    @app_commands.describe(sure="Süre: 10m, 2sa, 1g, 1sa 30dk gibi", mesaj="Neyi hatırlatayım?")
    @app_commands.guild_only()
    async def hatirlat(self, interaction: discord.Interaction, sure: str, mesaj: app_commands.Range[str, 1, 300]):
        seconds = helpers.parse_duration(sure)
        if seconds is None or not (10 <= seconds <= 30 * 86400):
            return await interaction.response.send_message(
                "⚠️ Süre geçersiz. Örnek: `30m`, `2sa`, `1g` (en fazla 30 gün).", ephemeral=True)
        data = db.get_data(interaction.guild_id)
        items = data.setdefault("reminders", [])
        if sum(1 for r in items if r["user_id"] == interaction.user.id) >= MAX_REMINDERS:
            return await interaction.response.send_message(f"⚠️ En fazla {MAX_REMINDERS} hatırlatıcın olabilir.", ephemeral=True)
        at = int(time.time()) + seconds
        items.append({"user_id": interaction.user.id, "channel_id": interaction.channel_id, "at": at, "text": mesaj})
        db.save_data(interaction.guild_id)
        await interaction.response.send_message(f"✅ Tamam, <t:{at}:R> hatırlatacağım: **{mesaj}**", ephemeral=True)

    # ---------- AFK ----------
    @app_commands.command(name="afk", description="AFK moduna geçer; etiketlenince bot haber verir")
    @app_commands.describe(sebep="Sebep")
    @app_commands.guild_only()
    async def afk(self, interaction: discord.Interaction, sebep: app_commands.Range[str, 1, 100] = "AFK"):
        m = db.member(interaction.guild_id, interaction.user.id)
        m["afk"] = {"reason": sebep, "since": int(time.time())}
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(f"💤 AFK moduna geçtin: **{sebep}**", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        gid = message.guild.id
        members = db.all_members(gid)
        entry = members.get(str(message.author.id))
        if entry and entry.get("afk"):
            entry.pop("afk", None)
            db.save_members(gid)
            try:
                await message.channel.send(f"👋 Hoş geldin {message.author.mention}, AFK modun kapatıldı.",
                                           delete_after=8, allowed_mentions=discord.AllowedMentions(users=[message.author]))
            except discord.HTTPException:
                pass
        for user in message.mentions[:5]:
            info = (members.get(str(user.id)) or {}).get("afk")
            if info and user.id != message.author.id:
                try:
                    await message.reply(f"💤 **{user.display_name}** AFK: {info['reason']} (<t:{info['since']}:R>)",
                                        delete_after=10, mention_author=False,
                                        allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

    # ---------- Bilgi komutları ----------
    @app_commands.command(name="ping", description="Botun gecikmesini gösterir")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🏓 Pong! **{round(self.bot.latency * 1000)} ms**")

    @app_commands.command(name="sunucu", description="Sunucu bilgilerini gösterir")
    @app_commands.guild_only()
    async def sunucu(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=g.name, color=discord.Color.blurple())
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="👑 Sahip", value=f"<@{g.owner_id}>")
        embed.add_field(name="👥 Üye", value=str(g.member_count))
        embed.add_field(name="💬 Kanal", value=str(len(g.channels)))
        embed.add_field(name="🎭 Rol", value=str(len(g.roles)))
        embed.add_field(name="🚀 Boost", value=f"{g.premium_subscription_count} (seviye {g.premium_tier})")
        embed.add_field(name="📅 Kuruluş", value=discord.utils.format_dt(g.created_at, "D"))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kullanici", description="Bir üyenin bilgilerini gösterir")
    @app_commands.describe(uye="Üye (boş = sen)")
    @app_commands.guild_only()
    async def kullanici(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or interaction.user
        roles = [r.mention for r in reversed(uye.roles) if not r.is_default()][:10]
        embed = discord.Embed(title=str(uye), color=uye.color or discord.Color.blurple())
        embed.set_thumbnail(url=uye.display_avatar.url)
        embed.add_field(name="ID", value=str(uye.id), inline=False)
        embed.add_field(name="📅 Hesap", value=discord.utils.format_dt(uye.created_at, "D"))
        embed.add_field(name="📥 Katılım", value=discord.utils.format_dt(uye.joined_at, "D") if uye.joined_at else "?")
        embed.add_field(name="🎭 Roller", value=" ".join(roles) or "yok", inline=False)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="avatar", description="Bir üyenin profil fotoğrafını gösterir")
    @app_commands.guild_only()
    async def avatar(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or interaction.user
        embed = discord.Embed(title=f"{uye.display_name} avatarı", color=discord.Color.blurple())
        embed.set_image(url=uye.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ---------- Eğlence / pratik ----------
    @app_commands.command(name="anket", description="Tepkilerle oylanan anket açar")
    @app_commands.describe(soru="Soru", secenekler="Seçenekleri | ile ayır (en az 2, en çok 9). Boş = Evet/Hayır")
    @app_commands.guild_only()
    async def anket(self, interaction: discord.Interaction, soru: app_commands.Range[str, 1, 250],
                    secenekler: str | None = None):
        if secenekler:
            options = [o.strip() for o in secenekler.split("|") if o.strip()][:9]
            if len(options) < 2:
                return await interaction.response.send_message("⚠️ En az 2 seçenek yaz: `A | B | C`", ephemeral=True)
            emojis = NUMBER_EMOJIS[:len(options)]
            body = "\n".join(f"{e} {o[:100]}" for e, o in zip(emojis, options))
        else:
            emojis = ["👍", "👎"]
            body = "👍 Evet\n👎 Hayır"
        embed = discord.Embed(title=f"📊 {soru}", description=body, color=discord.Color.blurple())
        embed.set_footer(text=f"Anketi açan: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for e in emojis:
            try:
                await message.add_reaction(e)
            except discord.HTTPException:
                break

    @app_commands.command(name="zar", description="Zar atar")
    @app_commands.describe(yuz="Zarın yüz sayısı", adet="Kaç zar")
    async def zar(self, interaction: discord.Interaction, yuz: app_commands.Range[int, 2, 1000] = 6,
                  adet: app_commands.Range[int, 1, 10] = 1):
        rolls = [random.randint(1, yuz) for _ in range(adet)]
        await interaction.response.send_message(f"🎲 {', '.join(map(str, rolls))}" + (f" (toplam **{sum(rolls)}**)" if adet > 1 else ""))

    @app_commands.command(name="sec", description="Verdiğin seçenekler arasından rastgele seçer")
    @app_commands.describe(secenekler="Virgül veya | ile ayır")
    async def sec(self, interaction: discord.Interaction, secenekler: str):
        options = [o.strip() for o in secenekler.replace("|", ",").split(",") if o.strip()]
        if len(options) < 2:
            return await interaction.response.send_message("⚠️ En az 2 seçenek yaz.", ephemeral=True)
        await interaction.response.send_message(f"🎯 Seçimim: **{random.choice(options)[:200]}**")


async def setup(bot):
    await bot.add_cog(Utility(bot))
