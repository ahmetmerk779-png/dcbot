import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

EXTENSIONS = [
    "cogs.ai_chat",
    "cogs.moderation",
    "cogs.automod",
    "cogs.welcome",
    "cogs.settings",
]

intents = discord.Intents.default()
intents.message_content = True  # Developer Portal'dan da açılmalı
intents.members = True  # Karşılama/görüşürüz için; Developer Portal'dan da açılmalı


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def process_commands(self, message):
        return  # Önek (!) komutları yok, sadece / komutları kullanılıyor

    async def setup_hook(self):
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        await self.start_web_server()
        synced = await self.tree.sync()
        print(f"{len(synced)} slash komutu senkronize edildi.")

    async def on_ready(self):
        print(f"{self.user} olarak giriş yapıldı. {len(self.guilds)} sunucuda.")
        await self.change_presence(activity=discord.Game("/yardim"))

    async def start_web_server(self):
        """Render ücretsiz Web Service için küçük sağlık sunucusu (PORT yoksa çalışmaz)."""
        port = os.getenv("PORT")
        if not port:
            return
        from aiohttp import web

        async def alive(_request):
            return web.Response(text="Bot çalışıyor ✅")

        app = web.Application()
        app.router.add_get("/", alive)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", int(port)).start()


bot = Bot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "⛔ Bu komutu kullanmak için yetkin yok."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "⛔ Benim bu işlem için yetkim yok. Bot izinlerini kontrol et."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "Bu komut sadece sunucularda kullanılabilir."
    else:
        print("Komut hatası:", repr(error))
        msg = "⚠️ Bir hata oluştu."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
