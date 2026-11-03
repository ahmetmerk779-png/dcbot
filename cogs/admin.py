"""Yönetici araçları: duyuru, rol verme/alma, takma ad."""
import discord
from discord import app_commands
from discord.ext import commands

import utils

NO_PING = discord.AllowedMentions.none()
ETIKET = [
    app_commands.Choice(name="Etiket yok", value="none"),
    app_commands.Choice(name="@here", value="here"),
    app_commands.Choice(name="@everyone", value="everyone"),
]


def _role_error(guild, actor, role):
    if role.is_default() or role.managed:
        return "Bu rol verilemez/alınamaz."
    if role >= guild.me.top_role:
        return "Bu rol benim rolümden yüksek veya eşit. Bot rolünü yukarı taşı."
    if actor.id != guild.owner_id and role >= actor.top_role:
        return "Bu rol seninkinden yüksek veya eşit."
    return None


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="duyuru", description="Bir kanala şık bir duyuru gönderir")
    @app_commands.describe(kanal="Kanal", mesaj="Duyuru metni", baslik="Başlık", etiket="Kimi etiketleyeyim?")
    @app_commands.choices(etiket=ETIKET)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def duyuru(self, interaction: discord.Interaction, kanal: discord.TextChannel,
                     mesaj: app_commands.Range[str, 1, 1800], baslik: app_commands.Range[str, 1, 200] = "📢 Duyuru",
                     etiket: app_commands.Choice[str] | None = None):
        ping = etiket.value if etiket else "none"
        if ping != "none" and not interaction.user.guild_permissions.mention_everyone:
            return await interaction.response.send_message("⛔ @everyone/@here etiketi için yetkin yok.", ephemeral=True)
        embed = discord.Embed(title=baslik, description=mesaj.replace("\\n", "\n"), color=discord.Color.blurple(),
                              timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"{interaction.user.display_name}")
        content = {"here": "@here", "everyone": "@everyone"}.get(ping)
        try:
            await kanal.send(content, embed=embed, allowed_mentions=discord.AllowedMentions(everyone=bool(content)))
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ O kanala yazamıyorum.", ephemeral=True)
        await interaction.response.send_message(f"✅ Duyuru {kanal.mention} kanalına gönderildi.", ephemeral=True)

    @app_commands.command(name="rol-ver", description="Bir üyeye rol verir")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rol_ver(self, interaction: discord.Interaction, uye: discord.Member, rol: discord.Role):
        err = _role_error(interaction.guild, interaction.user, rol)
        if err:
            return await interaction.response.send_message(f"⚠️ {err}", ephemeral=True)
        try:
            await uye.add_roles(rol, reason=f"{interaction.user}: rol-ver")
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ Yetkim yetmiyor.", ephemeral=True)
        await utils.log_action(interaction.guild, "➕ Rol verildi",
                               f"**Üye:** {uye.mention}\n**Rol:** {rol.mention}\n**Yetkili:** {interaction.user.mention}")
        await interaction.response.send_message(f"✅ {uye.mention} → {rol.mention}", allowed_mentions=NO_PING)

    @app_commands.command(name="rol-al", description="Bir üyeden rol alır")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def rol_al(self, interaction: discord.Interaction, uye: discord.Member, rol: discord.Role):
        err = _role_error(interaction.guild, interaction.user, rol)
        if err:
            return await interaction.response.send_message(f"⚠️ {err}", ephemeral=True)
        try:
            await uye.remove_roles(rol, reason=f"{interaction.user}: rol-al")
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ Yetkim yetmiyor.", ephemeral=True)
        await utils.log_action(interaction.guild, "➖ Rol alındı",
                               f"**Üye:** {uye.mention}\n**Rol:** {rol.mention}\n**Yetkili:** {interaction.user.mention}")
        await interaction.response.send_message(f"✅ {uye.mention} ← {rol.mention} alındı", allowed_mentions=NO_PING)

    @app_commands.command(name="takma-ad", description="Bir üyenin takma adını değiştirir (boş = sıfırla)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_nicknames=True)
    @app_commands.checks.has_permissions(manage_nicknames=True)
    async def takma_ad(self, interaction: discord.Interaction, uye: discord.Member,
                       isim: app_commands.Range[str, 1, 32] | None = None):
        err = utils.check_target(interaction.guild, interaction.user, uye)
        if err:
            return await interaction.response.send_message(f"⚠️ {err}", ephemeral=True)
        try:
            await uye.edit(nick=isim, reason=f"{interaction.user}: takma-ad")
        except discord.HTTPException:
            return await interaction.response.send_message("⛔ Yetkim yetmiyor.", ephemeral=True)
        await interaction.response.send_message(f"✅ {uye.mention} → **{isim or 'varsayılan ad'}**", allowed_mentions=NO_PING)


async def setup(bot):
    await bot.add_cog(Admin(bot))
