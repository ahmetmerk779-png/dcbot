"""Ekonomi: altın (🪙), günlük ödül, çalışma, kumar, rol marketi.
Kanal bazlı kapatılabilir: /kanal ozellik kanal:#x ozellik:Ekonomi acik:False"""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

COIN = "🪙"
DAILY_COOLDOWN = 86400
WORK_COOLDOWN = 3600
MAX_BET = 5000
NO_PING = discord.AllowedMentions.none()
BLOCKED = "Ekonomi komutları bu kanalda kapalı. Ekonomi için açık olan kanalı kullan."
WORK_TEXTS = [
    "Kafede garsonluk yaptın", "Pazarda tezgâh açtın", "Kargo dağıttın", "Bir bot hatasını buldun",
    "Komşunun bahçesini suladın", "Sunucuda gönüllü moderatörlük yaptın", "Bir logo tasarladın",
]
SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 25, 20, 12, 8, 5]
SLOT_PAYOUT = {"🍒": 4, "🍋": 4, "🍇": 5, "🔔": 6, "💎": 10, "7️⃣": 15}
MEDALS = ["🥇", "🥈", "🥉"]

COIN_SIDES = [app_commands.Choice(name="Yazı", value="yazi"), app_commands.Choice(name="Tura", value="tura")]
eco_only = utils.channel_feature("economy", BLOCKED)


def _block_bots(member):
    return member.bot


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="bakiye", description="Altın bakiyeni gösterir")
    @app_commands.describe(uye="Üye (boş = sen)")
    @app_commands.guild_only()
    @eco_only
    async def bakiye(self, interaction: discord.Interaction, uye: discord.Member | None = None):
        uye = uye or interaction.user
        if uye.bot:
            return await interaction.response.send_message("Botların cüzdanı yok 🤖", ephemeral=True)
        m = db.all_members(interaction.guild_id).get(str(uye.id), {})
        await interaction.response.send_message(
            f"💰 **{uye.display_name}** bakiyesi: **{m.get('coins', 0):,}** {COIN}")

    @app_commands.command(name="gunluk", description="Günlük altın ödülünü alır (üst üste alırsan artar)")
    @app_commands.guild_only()
    @eco_only
    async def gunluk(self, interaction: discord.Interaction):
        m = db.member(interaction.guild_id, interaction.user.id)
        now = int(time.time())
        last = m.get("daily_at", 0)
        if now - last < DAILY_COOLDOWN:
            return await interaction.response.send_message(
                f"⏳ Günlük ödülünü zaten aldın. Tekrar: <t:{last + DAILY_COOLDOWN}:R>", ephemeral=True)
        streak = m.get("streak", 0) + 1 if now - last <= DAILY_COOLDOWN * 2 else 1
        reward = 200 + min(streak, 30) * 20
        m["coins"] += reward
        m["daily_at"] = now
        m["streak"] = streak
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(
            f"🎁 Günlük ödülün: **{reward:,}** {COIN}  (🔥 seri: {streak} gün)\nBakiyen: **{m['coins']:,}** {COIN}")

    @app_commands.command(name="calis", description="Çalışıp altın kazan (saatte bir)")
    @app_commands.guild_only()
    @eco_only
    async def calis(self, interaction: discord.Interaction):
        m = db.member(interaction.guild_id, interaction.user.id)
        now = int(time.time())
        last = m.get("work_at", 0)
        if now - last < WORK_COOLDOWN:
            return await interaction.response.send_message(
                f"⏳ Yorgunsun, dinlen. Tekrar: <t:{last + WORK_COOLDOWN}:R>", ephemeral=True)
        reward = random.randint(30, 120)
        m["coins"] += reward
        m["work_at"] = now
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(
            f"💼 {random.choice(WORK_TEXTS)} ve **{reward}** {COIN} kazandın. Bakiyen: **{m['coins']:,}** {COIN}")

    @app_commands.command(name="ver", description="Başka bir üyeye altın gönderir")
    @app_commands.describe(uye="Alacak kişi", miktar="Gönderilecek miktar")
    @app_commands.guild_only()
    @eco_only
    async def ver(self, interaction: discord.Interaction, uye: discord.Member,
                  miktar: app_commands.Range[int, 1, 1_000_000]):
        if uye.bot or uye.id == interaction.user.id:
            return await interaction.response.send_message("⚠️ Geçerli bir kişi seç.", ephemeral=True)
        giver = db.member(interaction.guild_id, interaction.user.id)
        if giver["coins"] < miktar:
            return await interaction.response.send_message(
                f"⚠️ Yeterli altının yok. Bakiyen: {giver['coins']:,} {COIN}", ephemeral=True)
        receiver = db.member(interaction.guild_id, uye.id)
        giver["coins"] -= miktar
        receiver["coins"] += miktar
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} → {uye.mention}: **{miktar:,}** {COIN}",
            allowed_mentions=discord.AllowedMentions(users=[uye]))

    @app_commands.command(name="yazitura", description="Yazı tura at, kazanırsan bahsin ikiye katlanır")
    @app_commands.describe(miktar=f"Bahis (10-{MAX_BET})", secim="Yazı mı tura mı?")
    @app_commands.choices(secim=COIN_SIDES)
    @app_commands.guild_only()
    @eco_only
    async def yazitura(self, interaction: discord.Interaction, miktar: app_commands.Range[int, 10, MAX_BET],
                       secim: app_commands.Choice[str]):
        m = db.member(interaction.guild_id, interaction.user.id)
        if m["coins"] < miktar:
            return await interaction.response.send_message(
                f"⚠️ Yeterli altının yok. Bakiyen: {m['coins']:,} {COIN}", ephemeral=True)
        result = random.choice(["yazi", "tura"])
        won = result == secim.value
        m["coins"] += miktar if won else -miktar
        db.save_members(interaction.guild_id)
        label = "Yazı" if result == "yazi" else "Tura"
        text = (f"🪙 **{label}** geldi! **+{miktar:,}** {COIN} kazandın 🎉" if won
                else f"🪙 **{label}** geldi... **-{miktar:,}** {COIN} kaybettin 😢")
        await interaction.response.send_message(f"{text}\nBakiyen: **{m['coins']:,}** {COIN}")

    @app_commands.command(name="slot", description="Slot makinesi")
    @app_commands.describe(miktar=f"Bahis (10-{MAX_BET})")
    @app_commands.guild_only()
    @eco_only
    async def slot(self, interaction: discord.Interaction, miktar: app_commands.Range[int, 10, MAX_BET]):
        m = db.member(interaction.guild_id, interaction.user.id)
        if m["coins"] < miktar:
            return await interaction.response.send_message(
                f"⚠️ Yeterli altının yok. Bakiyen: {m['coins']:,} {COIN}", ephemeral=True)
        reels = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
        if reels[0] == reels[1] == reels[2]:
            gain = miktar * (SLOT_PAYOUT[reels[0]] - 1)
            text = f"🎰 JACKPOT! **+{gain:,}** {COIN}"
        elif len(set(reels)) == 2:
            gain = 0
            text = "🎰 İkili eşleşme, bahsin iade edildi."
        else:
            gain = -miktar
            text = f"🎰 Olmadı... **-{miktar:,}** {COIN}"
        m["coins"] += gain
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(
            f"**[ {' | '.join(reels)} ]**\n{text}\nBakiyen: **{m['coins']:,}** {COIN}")

    @app_commands.command(name="zenginler", description="En çok altını olan 10 kişi")
    @app_commands.guild_only()
    @eco_only
    async def zenginler(self, interaction: discord.Interaction):
        data = db.all_members(interaction.guild_id)
        top = sorted(((uid, v) for uid, v in data.items() if v.get("coins", 0) > 0),
                     key=lambda kv: kv[1]["coins"], reverse=True)[:10]
        if not top:
            return await interaction.response.send_message("Henüz kimsenin altını yok.", ephemeral=True)
        lines = [f"{MEDALS[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — **{v['coins']:,}** {COIN}"
                 for i, (uid, v) in enumerate(top)]
        embed = discord.Embed(title="💎 En Zenginler", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, allowed_mentions=NO_PING)

    # ---------- Rol marketi ----------
    market = app_commands.Group(name="market", description="Altınla rol satın al", guild_only=True)

    @market.command(name="liste", description="Marketteki rolleri gösterir")
    @eco_only
    async def market_liste(self, interaction: discord.Interaction):
        shop = db.get_config(interaction.guild_id).get("shop", {})
        if not shop:
            return await interaction.response.send_message("Market şu an boş.", ephemeral=True)
        lines = [f"<@&{rid}> — **{price:,}** {COIN}" for rid, price in sorted(shop.items(), key=lambda kv: kv[1])]
        embed = discord.Embed(title="🛒 Rol Marketi", description="\n".join(lines) + "\n\nSatın almak için `/market al`",
                              color=discord.Color.green())
        await interaction.response.send_message(embed=embed, allowed_mentions=NO_PING)

    @market.command(name="al", description="Marketten bir rol satın alır")
    @app_commands.describe(rol="Satın alınacak rol")
    @eco_only
    async def market_al(self, interaction: discord.Interaction, rol: discord.Role):
        shop = db.get_config(interaction.guild_id).get("shop", {})
        price = shop.get(str(rol.id))
        if price is None:
            return await interaction.response.send_message("⚠️ Bu rol markette satılmıyor.", ephemeral=True)
        if rol in interaction.user.roles:
            return await interaction.response.send_message("Bu role zaten sahipsin.", ephemeral=True)
        reason = utils.unsafe_role_reason(interaction.guild, rol)
        if reason:
            return await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
        m = db.member(interaction.guild_id, interaction.user.id)
        if m["coins"] < price:
            return await interaction.response.send_message(
                f"⚠️ Yetersiz bakiye. Fiyat: {price:,} {COIN}, bakiyen: {m['coins']:,} {COIN}", ephemeral=True)
        try:
            await interaction.user.add_roles(rol, reason="Market satın alımı")
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ Rolü veremedim, altının düşülmedi.", ephemeral=True)
        m["coins"] -= price
        db.save_members(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ {rol.mention} rolünü **{price:,}** {COIN} karşılığında aldın!", allowed_mentions=NO_PING)

    @market.command(name="ekle", description="Markete rol ekler (yönetici)")
    @app_commands.describe(rol="Satılacak rol", fiyat="Fiyat (altın)")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def market_ekle(self, interaction: discord.Interaction, rol: discord.Role,
                          fiyat: app_commands.Range[int, 1, 10_000_000]):
        reason = utils.unsafe_role_reason(interaction.guild, rol)
        if reason:
            return await interaction.response.send_message(f"⚠️ {reason}", ephemeral=True)
        db.get_config(interaction.guild_id).setdefault("shop", {})[str(rol.id)] = fiyat
        db.save_config(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ {rol.mention} markete eklendi: **{fiyat:,}** {COIN}", ephemeral=True, allowed_mentions=NO_PING)

    @market.command(name="sil", description="Marketten rol kaldırır (yönetici)")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def market_sil(self, interaction: discord.Interaction, rol: discord.Role):
        removed = db.get_config(interaction.guild_id).get("shop", {}).pop(str(rol.id), None)
        db.save_config(interaction.guild_id)
        await interaction.response.send_message(
            "🗑️ Marketten kaldırıldı." if removed is not None else "⚠️ Bu rol markette yok.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Economy(bot))
