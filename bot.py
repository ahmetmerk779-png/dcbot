import os
from collections import defaultdict, deque

import discord
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))  # kanal başına hatırlanan mesaj sayısı
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Sen bir Discord sunucusunda sohbet eden samimi ve yardımsever bir yapay zeka botusun. "
    "Kısa ve doğal cevaplar ver. Kullanıcı hangi dilde yazarsa o dilde cevap ver. "
    "Mesajlar 'KullanıcıAdı: mesaj' biçiminde gelir; farklı kişileri ayırt edebilirsin.",
)

groq_client = AsyncGroq()  # GROQ_API_KEY ortam değişkenini okur

intents = discord.Intents.default()
intents.message_content = True  # Developer Portal'dan da açılmalı!
client = discord.Client(intents=intents)

# Kanal bazlı sohbet geçmişi
history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


def split_message(text: str, limit: int = 1900):
    """Discord'un 2000 karakter sınırına göre mesajı böler."""
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def build_messages(channel_id: int):
    """Sistem mesajı + kanal geçmişini API formatında döndürür."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history[channel_id]:
        msgs.append({"role": role, "content": content})
    return msgs


@client.event
async def on_ready():
    print(f"{client.user} olarak giriş yapıldı.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    is_dm = message.guild is None
    mentioned = client.user in message.mentions
    if not (is_dm or mentioned):
        return  # Sadece DM'de veya etiketlenince cevap ver

    text = message.clean_content.replace(f"@{client.user.display_name}", "").strip()
    if not text:
        return

    cid = message.channel.id
    history[cid].append(("user", f"{message.author.display_name}: {text}"))

    async with message.channel.typing():
        try:
            response = await groq_client.chat.completions.create(
                model=MODEL,
                max_tokens=2000,  # gpt-oss düşünme token'ları da bu sınıra dahil
                messages=build_messages(cid),
            )
            reply = (response.choices[0].message.content or "").strip()
        except Exception as e:
            print("Hata:", e)
            history[cid].pop()
            await message.reply("Şu an cevap veremiyorum, biraz sonra tekrar dene. 😅")
            return

    history[cid].append(("assistant", reply))
    first = True
    for chunk in split_message(reply):
        if first:
            await message.reply(chunk, mention_author=False)
            first = False
        else:
            await message.channel.send(chunk)


# --- Render (ücretsiz Web Service) için küçük sağlık sunucusu ---
# Render PORT değişkenini verirse basit bir web sayfası açılır; UptimeRobot gibi
# bir servis buraya ping atarak botun uyumasını engelleyebilir.
# Background Worker kullanıyorsan PORT olmaz, bu kısım kendiliğinden devre dışı kalır.
async def start_web_server():
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


client.setup_hook = start_web_server

client.run(DISCORD_TOKEN)
