"""Otomatik moderasyon: davet/bağlantı engeli, yasaklı kelime, spam, sadece-medya kanalı.
Her filtre sunucu geneli veya kanal bazlı (/kanal ozellik) ayarlanabilir."""
import re
import time
from collections import defaultdict
from datetime import timedelta

import discord
from discord.ext import commands

import db
import helpers
import utils

INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\w+", re.I)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)

SPAM_COUNT = 6      # bu kadar mesaj
SPAM_WINDOW = 6.0   # bu kadar saniye içinde
SPAM_TIMEOUT_MIN = 5
MENTION_LIMIT = 5   # tek mesajda bu kadar etiket = ihlal


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recent = defaultdict(list)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not isinstance(message.author, discord.Member):
            return

        perms = message.channel.permissions_for(message.author)
        if perms.manage_messages or perms.administrator:
            return  # Yetkililer filtrelerden muaf

        gid = message.guild.id
        cid = utils.config_channel_id(message.channel)
        content = message.content or ""

        # Sadece medya/bağlantı kanalı
        if db.channel_option(gid, cid, "media_only"):
            has_media = bool(message.attachments or message.stickers or message.embeds or URL_RE.search(content))
            if not has_media:
                await self._punish_message(message, "Bu kanalda sadece görsel, dosya veya bağlantı paylaşılabilir")
                return

        if db.channel_option(gid, cid, "automod") is False:
            return

        reason = None
        if db.automod_flag(gid, cid, "am_invites") and INVITE_RE.search(content):
            reason = "Davet bağlantısı paylaşmak yasak"
        elif db.automod_flag(gid, cid, "am_links") and URL_RE.search(content):
            reason = "Bağlantı paylaşmak yasak"
        elif db.automod_flag(gid, cid, "am_badwords"):
            lowered = content.casefold()
            for word in db.list_badwords(gid):
                if re.search(rf"(?<!\w){re.escape(word)}", lowered):
                    reason = "Yasaklı kelime kullanımı"
                    break

        if reason is None and db.automod_flag(gid, cid, "am_mentions"):
            if len(message.mentions) + len(message.role_mentions) >= MENTION_LIMIT:
                reason = "Çok fazla kişi/rol etiketlemek yasak"
        if reason is None and db.automod_flag(gid, cid, "am_caps") and helpers.is_shouting(content):
            reason = "Aşırı büyük harf kullanımı"

        if reason:
            await self._punish_message(message, reason)
            return

        if db.automod_flag(gid, cid, "am_spam"):
            await self._check_spam(message)

    async def _punish_message(self, message, reason):
        try:
            await message.delete()
        except discord.HTTPException:
            return
        try:
            await message.channel.send(
                f"{message.author.mention} ⚠️ {reason}.", delete_after=6,
                allowed_mentions=discord.AllowedMentions(users=[message.author]),
            )
        except discord.HTTPException:
            pass
        await utils.log_action(
            message.guild, "🛡️ Otomod",
            f"**Kullanıcı:** {message.author.mention}\n**Kanal:** {message.channel.mention}\n**Sebep:** {reason}",
        )

    async def _check_spam(self, message):
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        stamps = [t for t in self.recent[key] if now - t < SPAM_WINDOW]
        stamps.append(now)
        self.recent[key] = stamps
        if len(stamps) < SPAM_COUNT:
            return

        self.recent[key] = []
        try:
            await message.author.timeout(timedelta(minutes=SPAM_TIMEOUT_MIN), reason="Otomod: spam")
        except discord.HTTPException:
            return
        try:
            await message.channel.purge(limit=15, check=lambda m: m.author.id == message.author.id)
        except discord.HTTPException:
            pass
        try:
            await message.channel.send(
                f"{message.author.mention} 🔇 Spam yaptığın için {SPAM_TIMEOUT_MIN} dakika susturuldun.",
                delete_after=8, allowed_mentions=discord.AllowedMentions(users=[message.author]),
            )
        except discord.HTTPException:
            pass
        await utils.log_action(
            message.guild, "🛡️ Otomod: spam",
            f"**Kullanıcı:** {message.author.mention}\n**Kanal:** {message.channel.mention}\n"
            f"**İşlem:** {SPAM_TIMEOUT_MIN} dk susturma",
        )


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
