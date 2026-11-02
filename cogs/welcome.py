"""Karşılama ve görüşürüz mesajları, otomatik rol."""
import discord
from discord.ext import commands

import db

DEFAULT_WELCOME = "👋 Hoş geldin {user}! **{server}** sunucusuna katıldın, seninle birlikte {count} kişiyiz. İyi eğlenceler!"
DEFAULT_GOODBYE = "😢 **{name}** sunucudan ayrıldı. Görüşürüz!"


def render(template: str, member: discord.Member) -> str:
    return (
        template.replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send(self, member, channel_key, message_key, default, mention_member):
        guild = member.guild
        channel_id = db.get_channel_id(guild.id, channel_key)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        text = render(db.get_setting(guild.id, message_key, default), member)
        allowed = discord.AllowedMentions(users=[member]) if mention_member else discord.AllowedMentions.none()
        try:
            await channel.send(text, allowed_mentions=allowed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        role_id = db.get_setting(member.guild.id, "autorole")
        if role_id:
            role = member.guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Otomatik rol")
                except discord.HTTPException:
                    pass
        await self._send(member, "welcome_channel", "welcome_msg", DEFAULT_WELCOME, True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self._send(member, "goodbye_channel", "goodbye_msg", DEFAULT_GOODBYE, False)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
