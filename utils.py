"""Moderasyon işlemleri. Hem / komutları hem de doğal dil araçları bunları kullanır."""
from datetime import timedelta

import discord

import db

MAX_TIMEOUT_MIN = 40320  # Discord sınırı: 28 gün
WARN_AUTO_TIMEOUT_EVERY = 3  # Her 3. uyarıda otomatik 1 saat susturma


def _audit(actor, reason: str) -> str:
    return f"{actor}: {reason}"[:500]


def check_target(guild: discord.Guild, actor: discord.Member, target: discord.Member):
    """İşlem yapılabilir mi? Yapılamazsa nedenini döndürür, yapılabilirse None."""
    if target.id == actor.id:
        return "Kendi üzerinde işlem yapamazsın."
    if target.id == guild.me.id:
        return "Bu işlemi bana uygulayamam."
    if target.id == guild.owner_id:
        return "Sunucu sahibine işlem yapılamaz."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "Bu kullanıcının rolü seninkinden yüksek veya eşit."
    if target.top_role >= guild.me.top_role:
        return "Bu kullanıcının rolü benim rolümden yüksek veya eşit. Bot rolünü rol listesinde yukarı taşı."
    return None


async def log_action(guild: discord.Guild, title: str, description: str, color=None):
    """Ayarlanmışsa mod-log kanalına kayıt düşer."""
    channel_id = db.get_channel_id(guild.id, "log_channel")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    embed = discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


async def _safe(coro_factory):
    """Discord hatalarını kullanıcıya anlaşılır mesaja çevirir."""
    try:
        return await coro_factory()
    except discord.Forbidden:
        return False, "⛔ Yetkim yetmiyor. Bot rolünün üstte olduğundan ve izinlerinin açık olduğundan emin ol."
    except discord.NotFound:
        return False, "⚠️ Bulunamadı."
    except discord.HTTPException as e:
        return False, f"⚠️ Discord hatası: {e}"


async def do_timeout(guild, actor, target, minutes: int, reason: str):
    if minutes < 1 or minutes > MAX_TIMEOUT_MIN:
        return False, f"⚠️ Süre 1 ile {MAX_TIMEOUT_MIN} dakika arasında olmalı."
    err = check_target(guild, actor, target)
    if err:
        return False, f"⚠️ {err}"

    async def run():
        await target.timeout(timedelta(minutes=minutes), reason=_audit(actor, reason))
        await log_action(
            guild, "🔇 Susturma",
            f"**Kullanıcı:** {target.mention}\n**Yetkili:** {actor.mention}\n**Süre:** {minutes} dk\n**Sebep:** {reason}",
        )
        return True, f"🔇 {target.mention} **{minutes} dakika** susturuldu. Sebep: {reason}"

    return await _safe(run)


async def do_untimeout(guild, actor, target, reason: str = "Susturma kaldırıldı"):
    async def run():
        await target.timeout(None, reason=_audit(actor, reason))
        await log_action(
            guild, "🔊 Susturma kaldırıldı",
            f"**Kullanıcı:** {target.mention}\n**Yetkili:** {actor.mention}", discord.Color.green(),
        )
        return True, f"🔊 {target.mention} kullanıcısının susturması kaldırıldı."

    return await _safe(run)


async def do_kick(guild, actor, target, reason: str):
    err = check_target(guild, actor, target)
    if err:
        return False, f"⚠️ {err}"

    async def run():
        await target.kick(reason=_audit(actor, reason))
        await log_action(
            guild, "👢 Atma",
            f"**Kullanıcı:** {target} ({target.id})\n**Yetkili:** {actor.mention}\n**Sebep:** {reason}",
            discord.Color.red(),
        )
        return True, f"👢 **{target}** sunucudan atıldı. Sebep: {reason}"

    return await _safe(run)


async def do_ban(guild, actor, target, reason: str, delete_days: int = 0):
    err = check_target(guild, actor, target)
    if err:
        return False, f"⚠️ {err}"

    async def run():
        await guild.ban(
            target, reason=_audit(actor, reason), delete_message_seconds=max(0, min(7, delete_days)) * 86400
        )
        await log_action(
            guild, "🔨 Yasaklama",
            f"**Kullanıcı:** {target} ({target.id})\n**Yetkili:** {actor.mention}\n**Sebep:** {reason}",
            discord.Color.dark_red(),
        )
        return True, f"🔨 **{target}** sunucudan yasaklandı. Sebep: {reason}"

    return await _safe(run)


async def do_warn(guild, actor, target, reason: str):
    err = check_target(guild, actor, target)
    if err:
        return False, f"⚠️ {err}"
    count = db.add_warning(guild.id, target.id, actor.id, reason)
    msg = f"⚠️ {target.mention} uyarıldı (toplam **{count}** uyarı). Sebep: {reason}"
    if count % WARN_AUTO_TIMEOUT_EVERY == 0:
        try:
            await target.timeout(timedelta(hours=1), reason=f"Otomatik: {count} uyarı")
            msg += f"\n🔇 {count} uyarıya ulaştığı için **1 saat** susturuldu."
        except discord.HTTPException:
            pass
    await log_action(
        guild, "⚠️ Uyarı",
        f"**Kullanıcı:** {target.mention}\n**Yetkili:** {actor.mention}\n**Toplam:** {count}\n**Sebep:** {reason}",
    )
    return True, msg


async def do_purge(channel, actor, count: int, member=None, before=None):
    count = max(1, min(100, count))
    check = (lambda m: m.author.id == member.id) if member else None

    async def run():
        deleted = await channel.purge(limit=count, check=check, before=before, reason=_audit(actor, "Toplu silme"))
        await log_action(
            channel.guild, "🧹 Mesaj temizleme",
            f"**Kanal:** {channel.mention}\n**Yetkili:** {actor.mention}\n**Silinen:** {len(deleted)}",
            discord.Color.blurple(),
        )
        return True, f"🧹 {len(deleted)} mesaj silindi."

    return await _safe(run)


async def do_slowmode(channel, actor, seconds: int):
    seconds = max(0, min(21600, seconds))

    async def run():
        await channel.edit(slowmode_delay=seconds, reason=_audit(actor, "Yavaş mod"))
        if seconds == 0:
            return True, "🐇 Yavaş mod kapatıldı."
        return True, f"🐢 Yavaş mod **{seconds} saniye** olarak ayarlandı."

    return await _safe(run)


async def do_lock(channel, actor, lock: bool):
    if not isinstance(channel, discord.TextChannel):
        return False, "⚠️ Bu işlem sadece metin kanallarında yapılabilir."

    async def run():
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False if lock else None
        await channel.set_permissions(
            channel.guild.default_role, overwrite=overwrite,
            reason=_audit(actor, "Kanal kilitlendi" if lock else "Kanal kilidi açıldı"),
        )
        await log_action(
            channel.guild, "🔒 Kanal kilidi" if lock else "🔓 Kanal kilidi açıldı",
            f"**Kanal:** {channel.mention}\n**Yetkili:** {actor.mention}",
        )
        return True, ("🔒 Kanal kilitlendi." if lock else "🔓 Kanalın kilidi açıldı.")

    return await _safe(run)


class ConfirmView(discord.ui.View):
    """Tehlikeli işlemler için onay butonları. Sadece komutu yazan kişi onaylayabilir."""

    def __init__(self, author_id: int, action):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.action = action  # async fonksiyon: action(interaction) -> (ok, mesaj)
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Bu onay sana ait değil.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.defer()
        ok, msg = await self.action(interaction)
        try:
            await interaction.edit_original_response(content=msg, view=None)
        except discord.NotFound:
            await interaction.followup.send(msg)

    @discord.ui.button(label="İptal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="❌ İşlem iptal edildi.", view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⌛ Onay süresi doldu, işlem yapılmadı.", view=None)
            except discord.HTTPException:
                pass
