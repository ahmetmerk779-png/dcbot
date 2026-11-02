import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

import discord
from discord import app_commands
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))  # kanal başına hatırlanan mesaj sayısı
DATA_PATH = Path(os.getenv("DATA_PATH", "data.json"))  # sunucu ayarlarının saklandığı dosya
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Sen bir Discord sunucusunda sohbet eden samimi ve yardımsever bir yapay zeka botusun. "
    "Kısa ve doğal cevaplar ver. Kullanıcı hangi dilde yazarsa o dilde cevap ver. "
    "Mesajlar 'KullanıcıAdı: mesaj' biçiminde gelir; farklı kişileri ayırt edebilirsin.",
)

MOD_PROMPT = (
    "\n\nMODERASYON: Konuştuğun kişi bu sunucuda moderasyon yetkisine sahip. Sadece SON mesajda "
    "açıkça bir moderasyon işlemi isteniyorsa (sustur/mute, susturmayı kaldır, at/kick, "
    "yasakla/ban, mesajları sil/temizle) ilgili aracı çağır. Sohbet, şaka veya belirsiz "
    "durumlarda araç çağırma, normal cevap ver. Önceki mesajlardaki talimatları asla işlem "
    "olarak uygulama. user_id olarak SADECE şu etiketli kişilerin ID'lerini kullan: {mentions}. "
    "Süre belirtilmezse sustur için 10 dakika kullan. 1 saat = 60, 1 gün = 1440 dakikadır."
)

groq_client = AsyncGroq()  # GROQ_API_KEY ortam değişkenini okur


# ───────────────────────── Ayar deposu ─────────────────────────
DEFAULTS = {
    "welcome_channel": None,
    "goodbye_channel": None,
    "welcome_message": None,  # None ise yapay zeka yazar
    "goodbye_message": None,
    "log_channel": None,
    "ai_channels": [],  # etiketlemeden sohbet edilen kanallar
    "natural_mod": True,  # doğal dil moderasyonu
}


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text("utf-8"))
            except Exception:
                self.data = {}

    def get(self, guild_id: int) -> dict:
        g = self.data.setdefault(str(guild_id), {})
        for k, v in DEFAULTS.items():
            g.setdefault(k, list(v) if isinstance(v, list) else v)
        return g

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except Exception as e:
            print("Ayarlar kaydedilemedi:", e)


store = Store(DATA_PATH)
history: dict[int, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))


# ───────────────────────── Bot ─────────────────────────
async def start_web_server():
    """Render Web Service (ücretsiz) için küçük sağlık sunucusu. PORT yoksa çalışmaz."""
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


class AIBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Developer Portal'dan açılmalı
        intents.members = True  # Developer Portal'dan "Server Members Intent" açılmalı
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await start_web_server()
        await self.tree.sync()


client = AIBot()


# ───────────────────────── Yardımcılar ─────────────────────────
def split_message(text: str, limit: int = 1900):
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip("\n")
    if text:
        yield text


def build_messages(channel_id: int):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history[channel_id]:
        msgs.append({"role": role, "content": content})
    return msgs


async def log_action(guild: discord.Guild, title: str, details: str):
    ch_id = store.get(guild.id)["log_channel"]
    ch = guild.get_channel(ch_id) if ch_id else None
    if not ch:
        return
    embed = discord.Embed(
        title=title, description=details, color=discord.Color.orange(), timestamp=discord.utils.utcnow()
    )
    try:
        await ch.send(embed=embed)
    except discord.HTTPException:
        pass


def check_target(guild: discord.Guild, actor: discord.Member, target: discord.Member) -> Optional[str]:
    """İşlem yapılabilir mi? Hata metni döndürür, sorun yoksa None."""
    if target.id == actor.id:
        return "Kendine bu işlemi yapamazsın."
    if target.id == client.user.id:
        return "Bana bu işlemi yapamam."
    if target.id == guild.owner_id:
        return "Sunucu sahibine işlem yapılamaz."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "Bu kişinin rolü seninkiyle aynı veya senden yüksek."
    if target.top_role >= guild.me.top_role:
        return "Bu kişinin rolü benimkinden yüksek veya eşit. Bot rolünü rol listesinde yukarı taşı."
    return None


def short(reason: str) -> str:
    return (reason or "Belirtilmedi")[:200]


# ───────────────────────── Moderasyon eylemleri (hem / hem doğal dil) ─────────────────────────
async def do_timeout(guild, actor, target: discord.Member, minutes: int, reason: str) -> str:
    err = check_target(guild, actor, target)
    if err:
        return f"❌ {err}"
    minutes = max(1, min(int(minutes), 40320))  # Discord sınırı: 28 gün
    try:
        await target.timeout(timedelta(minutes=minutes), reason=f"{actor}: {short(reason)}")
    except discord.Forbidden:
        return "❌ Yetkim yetmedi (Üyeleri Zaman Aşımına Uğrat izni veya rol sırası)."
    await log_action(guild, "🔇 Susturuldu", f"{target.mention} — {minutes} dk\nYetkili: {actor.mention}\nSebep: {short(reason)}")
    return f"🔇 {target.mention} **{minutes} dakika** susturuldu. Sebep: {short(reason)}"


async def do_untimeout(guild, actor, target: discord.Member, reason: str) -> str:
    err = check_target(guild, actor, target)
    if err:
        return f"❌ {err}"
    try:
        await target.timeout(None, reason=f"{actor}: {short(reason)}")
    except discord.Forbidden:
        return "❌ Yetkim yetmedi."
    await log_action(guild, "🔊 Susturma kaldırıldı", f"{target.mention}\nYetkili: {actor.mention}")
    return f"🔊 {target.mention} için susturma kaldırıldı."


async def do_kick(guild, actor, target: discord.Member, reason: str) -> str:
    err = check_target(guild, actor, target)
    if err:
        return f"❌ {err}"
    try:
        await target.kick(reason=f"{actor}: {short(reason)}")
    except discord.Forbidden:
        return "❌ Yetkim yetmedi (Üyeleri At izni veya rol sırası)."
    await log_action(guild, "👢 Atıldı", f"**{target}** ({target.id})\nYetkili: {actor.mention}\nSebep: {short(reason)}")
    return f"👢 **{target.display_name}** sunucudan atıldı. Sebep: {short(reason)}"


async def do_ban(guild, actor, target: discord.Member, reason: str, delete_days: int = 0) -> str:
    err = check_target(guild, actor, target)
    if err:
        return f"❌ {err}"
    try:
        await guild.ban(target, reason=f"{actor}: {short(reason)}", delete_message_seconds=delete_days * 86400)
    except discord.Forbidden:
        return "❌ Yetkim yetmedi (Üyeleri Yasakla izni veya rol sırası)."
    await log_action(guild, "🔨 Yasaklandı", f"**{target}** ({target.id})\nYetkili: {actor.mention}\nSebep: {short(reason)}")
    return f"🔨 **{target.display_name}** yasaklandı. Sebep: {short(reason)}"


async def do_purge(channel, actor, count: int, before: Optional[discord.Message] = None) -> str:
    if not channel.permissions_for(actor).manage_messages:
        return "❌ Mesajları silmek için yetkin yok."
    count = max(1, min(int(count), 100))
    try:
        deleted = await channel.purge(limit=count, before=before)
    except discord.Forbidden:
        return "❌ Bu kanalda mesaj silme iznim yok."
    await log_action(channel.guild, "🗑️ Mesajlar silindi", f"{actor.mention}, {channel.mention} kanalında **{len(deleted)}** mesaj sildi.")
    return f"🗑️ {len(deleted)} mesaj silindi."


# ───────────────────────── Doğal dil: araçlar ─────────────────────────
def tool(name, desc, props, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


_uid = {"type": "string", "description": "Etiketlenen kişinin Discord kullanıcı ID'si"}
_reason = {"type": "string", "description": "Kısa sebep (isteğe bağlı)"}

TOOLS = [
    tool("timeout_member", "Üyeyi belirli süre sustur (mute / zaman aşımı).",
         {"user_id": _uid, "minutes": {"type": "integer", "description": "Süre, dakika"}, "reason": _reason},
         ["user_id", "minutes"]),
    tool("untimeout_member", "Üyenin susturmasını kaldır (unmute).",
         {"user_id": _uid, "reason": _reason}, ["user_id"]),
    tool("kick_member", "Üyeyi sunucudan at (kick).",
         {"user_id": _uid, "reason": _reason}, ["user_id"]),
    tool("ban_member", "Üyeyi sunucudan yasakla (ban).",
         {"user_id": _uid, "reason": _reason}, ["user_id"]),
    tool("delete_messages", "Bu kanaldaki son N mesajı sil (en fazla 100).",
         {"count": {"type": "integer", "description": "Silinecek mesaj sayısı"}}, ["count"]),
]

TOOL_PERMS = {
    "timeout_member": "moderate_members",
    "untimeout_member": "moderate_members",
    "kick_member": "kick_members",
    "ban_member": "ban_members",
    "delete_messages": "manage_messages",
}


def has_tool_perm(actor: discord.Member, channel, tool_name: str) -> bool:
    return getattr(channel.permissions_for(actor), TOOL_PERMS[tool_name], False)


@dataclass
class Plan:
    desc: str  # onay penceresinde gösterilen açıklama
    confirm: bool  # True ise butonla onay gerekir
    run: Callable[[Optional[discord.Message]], Awaitable[str]]


def plan_tool(message: discord.Message, name: str, args: dict, mentioned: dict):
    guild, actor, channel = message.guild, message.author, message.channel
    if name not in TOOL_PERMS or not has_tool_perm(actor, channel, name):
        return "❌ Bu işlem için yetkin yok."
    reason = short(str(args.get("reason") or "Belirtilmedi"))

    if name == "delete_messages":
        try:
            count = max(1, min(int(args.get("count")), 100))
        except (TypeError, ValueError):
            return "❌ Kaç mesaj silineceğini anlayamadım."
        return Plan(f"🗑️ Bu kanaldaki son **{count}** mesaj silinsin mi?", True,
                    lambda before: do_purge(channel, actor, count, before))

    try:
        uid = int(args.get("user_id"))
    except (TypeError, ValueError):
        return "❌ Kimin etiketlendiğini anlayamadım."
    target = mentioned.get(uid)
    if target is None:
        return "❌ İşlem yapılacak kişiyi etiketlemelisin."
    err = check_target(guild, actor, target)
    if err:
        return f"❌ {err}"

    if name == "timeout_member":
        try:
            minutes = int(args.get("minutes", 10))
        except (TypeError, ValueError):
            minutes = 10
        return Plan("", False, lambda before: do_timeout(guild, actor, target, minutes, reason))
    if name == "untimeout_member":
        return Plan("", False, lambda before: do_untimeout(guild, actor, target, reason))
    if name == "kick_member":
        return Plan(f"👢 **{target.display_name}** sunucudan atılsın mı?", True,
                    lambda before: do_kick(guild, actor, target, reason))
    if name == "ban_member":
        return Plan(f"🔨 **{target.display_name}** yasaklansın mı?", True,
                    lambda before: do_ban(guild, actor, target, reason))
    return "❌ Bilinmeyen işlem."


class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int, plans: list):
        super().__init__(timeout=45)
        self.author_id = author_id
        self.plans = plans
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Bu onay sana ait değil.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Onayla", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="⏳ Uygulanıyor...", view=None)
        results = [await p.run(self.message) for p in self.plans]
        await interaction.edit_original_response(content="\n".join(results))

    @discord.ui.button(label="İptal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="İptal edildi.", view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⌛ Onay süresi doldu, işlem yapılmadı.", view=None)
            except discord.HTTPException:
                pass


# ───────────────────────── Olaylar ─────────────────────────
@client.event
async def on_ready():
    print(f"{client.user} olarak giriş yapıldı.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    guild = message.guild
    is_dm = guild is None
    mentioned_me = client.user in message.mentions
    settings = store.get(guild.id) if guild else None
    in_ai_channel = bool(settings and message.channel.id in settings["ai_channels"])
    if not (is_dm or mentioned_me or in_ai_channel):
        return

    me_name = guild.me.display_name if guild else client.user.name
    text = message.clean_content.replace(f"@{me_name}", "").strip()
    if not text:
        return

    mentioned = {
        m.id: m for m in message.mentions
        if isinstance(m, discord.Member) and m.id != client.user.id
    }

    # Moderasyon araçları: sadece botu etiketleyen ve yetkisi olan kişiler için
    tools = []
    if guild and mentioned_me and settings["natural_mod"] and isinstance(message.author, discord.Member):
        tools = [t for t in TOOLS if has_tool_perm(message.author, message.channel, t["function"]["name"])]

    cid = message.channel.id
    history[cid].append(("user", f"{message.author.display_name}: {text}"))

    messages = build_messages(cid)
    kwargs = {}
    if tools:
        names = ", ".join(f"{m.display_name}={m.id}" for m in mentioned.values()) or "(kimse etiketlenmedi)"
        messages[0]["content"] += MOD_PROMPT.format(mentions=names)
        kwargs = {"tools": tools, "tool_choice": "auto"}

    async with message.channel.typing():
        try:
            response = await groq_client.chat.completions.create(
                model=MODEL,
                max_tokens=2000,  # gpt-oss düşünme token'ları da bu sınıra dahil
                messages=messages,
                **kwargs,
            )
            msg = response.choices[0].message
            reply = (msg.content or "").strip()
            tool_calls = msg.tool_calls or []
        except Exception as e:
            print("Hata:", e)
            history[cid].pop()
            await message.reply("Şu an cevap veremiyorum, biraz sonra tekrar dene. 😅")
            return

    # ── Araç çağrısı varsa: işlemleri planla ──
    if tool_calls:
        plans, lines = [], []
        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                lines.append("❌ İsteği anlayamadım.")
                continue
            plan = plan_tool(message, call.function.name, args, mentioned)
            if isinstance(plan, str):
                lines.append(plan)
            else:
                plans.append(plan)

        for p in [p for p in plans if not p.confirm]:
            lines.append(await p.run(None))
        needs = [p for p in plans if p.confirm]

        if needs:
            view = ConfirmView(message.author.id, needs)
            body = "\n".join(lines + ["⚠️ **Onay gerekiyor:**"] + [p.desc for p in needs])
            view.message = await message.reply(body, view=view, mention_author=False)
        else:
            body = "\n".join(lines) or "🤔 Ne yapmam gerektiğini anlayamadım."
            await message.reply(body, mention_author=False)
        history[cid].append(("assistant", body[:500]))
        return

    # ── Normal sohbet ──
    if not reply:
        reply = "🤔 Bir şey diyemedim, tekrar dener misin?"
    history[cid].append(("assistant", reply))
    first = True
    for chunk in split_message(reply):
        if first:
            await message.reply(chunk, mention_author=False)
            first = False
        else:
            await message.channel.send(chunk)


# ───────────────────────── Karşılama / uğurlama ─────────────────────────
DEFAULT_GREETING = {
    "welcome": "👋 Hoş geldin {user}! **{server}** sunucusuna katıldığın için çok mutluyuz.",
    "goodbye": "😢 {user} aramızdan ayrıldı. Görüşürüz!",
}


def fill(template: str, member: discord.Member, kind: str) -> str:
    user = member.mention if kind == "welcome" else f"**{member.display_name}**"
    return (template.replace("{user}", user)
            .replace("{server}", member.guild.name)
            .replace("{count}", str(member.guild.member_count)))


async def greeting_text(kind: str, member: discord.Member) -> str:
    template = store.get(member.guild.id)[f"{kind}_message"]
    if template:
        return fill(template, member, kind)
    try:
        what = "karşılama" if kind == "welcome" else "veda"
        r = await groq_client.chat.completions.create(
            model=MODEL,
            max_tokens=600,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"'{member.guild.name}' Discord sunucusu için {what} mesajı yaz. "
                    f"Kişinin adı yerine tam olarak {{user}} yaz. En fazla 2 kısa cümle, samimi, "
                    "1-2 emoji. Sadece mesajı yaz."
                )},
            ],
        )
        text = (r.choices[0].message.content or "").strip()
        if text:
            if "{user}" not in text:
                text = "{user} " + text
            return fill(text, member, kind)
    except Exception as e:
        print("Karşılama hatası:", e)
    return fill(DEFAULT_GREETING[kind], member, kind)


async def send_greeting(kind: str, member: discord.Member):
    ch_id = store.get(member.guild.id)[f"{kind}_channel"]
    ch = member.guild.get_channel(ch_id) if ch_id else None
    if not ch:
        return
    try:
        await ch.send(await greeting_text(kind, member))
    except discord.HTTPException as e:
        print("Mesaj gönderilemedi:", e)


@client.event
async def on_member_join(member: discord.Member):
    if not member.bot:
        await send_greeting("welcome", member)


@client.event
async def on_member_remove(member: discord.Member):
    if not member.bot:
        await send_greeting("goodbye", member)


# ───────────────────────── Slash komutları: moderasyon ─────────────────────────
async def respond(interaction: discord.Interaction, msg: str):
    await interaction.response.send_message(msg, ephemeral=msg.startswith("❌"))


@client.tree.command(name="sustur", description="Bir üyeyi belirli süre sustur (zaman aşımı)")
@app_commands.describe(uye="Susturulacak üye", dakika="Süre (dakika, en fazla 40320)", sebep="Sebep")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_timeout(interaction: discord.Interaction, uye: discord.Member,
                      dakika: app_commands.Range[int, 1, 40320] = 10, sebep: str = "Belirtilmedi"):
    await respond(interaction, await do_timeout(interaction.guild, interaction.user, uye, dakika, sebep))


@client.tree.command(name="susturmayi-kaldir", description="Bir üyenin susturmasını kaldır")
@app_commands.describe(uye="Üye", sebep="Sebep")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_untimeout(interaction: discord.Interaction, uye: discord.Member, sebep: str = "Belirtilmedi"):
    await respond(interaction, await do_untimeout(interaction.guild, interaction.user, uye, sebep))


@client.tree.command(name="at", description="Bir üyeyi sunucudan at")
@app_commands.describe(uye="Atılacak üye", sebep="Sebep")
@app_commands.guild_only()
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
async def cmd_kick(interaction: discord.Interaction, uye: discord.Member, sebep: str = "Belirtilmedi"):
    await respond(interaction, await do_kick(interaction.guild, interaction.user, uye, sebep))


@client.tree.command(name="yasakla", description="Bir üyeyi sunucudan yasakla")
@app_commands.describe(uye="Yasaklanacak üye", sebep="Sebep", mesaj_sil_gun="Son kaç günün mesajları silinsin (0-7)")
@app_commands.guild_only()
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_ban(interaction: discord.Interaction, uye: discord.Member, sebep: str = "Belirtilmedi",
                  mesaj_sil_gun: app_commands.Range[int, 0, 7] = 0):
    await respond(interaction, await do_ban(interaction.guild, interaction.user, uye, sebep, mesaj_sil_gun))


@client.tree.command(name="yasagi-kaldir", description="Bir kullanıcının yasağını kaldır (ID ile)")
@app_commands.describe(kullanici_id="Kullanıcı ID'si", sebep="Sebep")
@app_commands.guild_only()
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
async def cmd_unban(interaction: discord.Interaction, kullanici_id: str, sebep: str = "Belirtilmedi"):
    try:
        uid = int(kullanici_id.strip())
    except ValueError:
        return await respond(interaction, "❌ Geçerli bir kullanıcı ID'si gir.")
    try:
        await interaction.guild.unban(discord.Object(id=uid), reason=f"{interaction.user}: {short(sebep)}")
    except discord.NotFound:
        return await respond(interaction, "❌ Bu ID yasaklı listesinde yok.")
    except discord.Forbidden:
        return await respond(interaction, "❌ Yetkim yetmedi.")
    await log_action(interaction.guild, "♻️ Yasak kaldırıldı", f"ID: {uid}\nYetkili: {interaction.user.mention}")
    await respond(interaction, f"♻️ `{uid}` kullanıcısının yasağı kaldırıldı.")


@client.tree.command(name="temizle", description="Bu kanaldaki son N mesajı sil")
@app_commands.describe(adet="Silinecek mesaj sayısı (1-100)")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_purge(interaction: discord.Interaction, adet: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    msg = await do_purge(interaction.channel, interaction.user, adet)
    await interaction.followup.send(msg, ephemeral=True)


@client.tree.command(name="yavasmod", description="Bu kanalın yavaş modunu ayarla (0 = kapat)")
@app_commands.describe(saniye="Mesajlar arası bekleme süresi (0-21600 sn)")
@app_commands.guild_only()
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
async def cmd_slowmode(interaction: discord.Interaction, saniye: app_commands.Range[int, 0, 21600]):
    try:
        await interaction.channel.edit(slowmode_delay=saniye, reason=f"{interaction.user}")
    except (discord.Forbidden, AttributeError):
        return await respond(interaction, "❌ Bu kanalda yavaş modu ayarlayamadım (Kanalları Yönet izni?).")
    await log_action(interaction.guild, "🐢 Yavaş mod", f"{interaction.channel.mention}: {saniye} sn\nYetkili: {interaction.user.mention}")
    await respond(interaction, "🐢 Yavaş mod kapatıldı." if saniye == 0 else f"🐢 Yavaş mod **{saniye} sn** yapıldı.")


@client.tree.command(name="sifirla", description="Botun bu kanaldaki sohbet hafızasını sıfırla")
@app_commands.guild_only()
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
async def cmd_reset(interaction: discord.Interaction):
    history.pop(interaction.channel_id, None)
    await respond(interaction, "🧹 Bu kanaldaki sohbet hafızamı sıfırladım.")


@client.tree.command(name="yardim", description="Botun neler yapabildiğini göster")
async def cmd_help(interaction: discord.Interaction):
    e = discord.Embed(title="🤖 Yapay Zeka Botu", color=discord.Color.blurple())
    e.add_field(name="💬 Sohbet", value="Beni etiketle veya DM'den yaz. Yöneticiler bazı kanalları etiketsiz sohbete açabilir.", inline=False)
    e.add_field(
        name="🛡️ Doğal dil moderasyonu (yetkililer)",
        value="Beni etiketleyip yaz:\n`@Bot @Ali'yi 10 dakika sustur`\n`@Bot @Veli'yi at, spam yapıyor`\n`@Bot son 20 mesajı sil`\nAt / yasakla / silme işlemleri buton onayı ister.",
        inline=False,
    )
    e.add_field(
        name="⚙️ Moderasyon komutları",
        value="`/sustur` `/susturmayi-kaldir` `/at` `/yasakla` `/yasagi-kaldir` `/temizle` `/yavasmod` `/sifirla`",
        inline=False,
    )
    e.add_field(
        name="🔧 Ayarlar (Sunucuyu Yönet)",
        value="`/ayar goster` `/ayar hosgeldin-kanali` `/ayar gorusuruz-kanali` `/ayar hosgeldin-mesaji` `/ayar gorusuruz-mesaji` `/ayar log-kanali` `/ayar yz-kanali` `/ayar dogal-dil` `/ayar kapat` `/ayar test`",
        inline=False,
    )
    await interaction.response.send_message(embed=e, ephemeral=True)


# ───────────────────────── Slash komutları: ayarlar ─────────────────────────
ayar = app_commands.Group(
    name="ayar",
    description="Bot ayarları (Sunucuyu Yönet yetkisi gerekir)",
    guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True),
)
client.tree.add_command(ayar)


def ch_text(ch_id) -> str:
    return f"<#{ch_id}>" if ch_id else "Kapalı"


@ayar.command(name="goster", description="Mevcut ayarları göster")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_show(interaction: discord.Interaction):
    s = store.get(interaction.guild_id)
    e = discord.Embed(title="⚙️ Sunucu Ayarları", color=discord.Color.blurple())
    e.add_field(name="Hoş geldin kanalı", value=ch_text(s["welcome_channel"]))
    e.add_field(name="Görüşürüz kanalı", value=ch_text(s["goodbye_channel"]))
    e.add_field(name="Log kanalı", value=ch_text(s["log_channel"]))
    e.add_field(name="Hoş geldin mesajı", value=s["welcome_message"] or "Yapay zeka yazar", inline=False)
    e.add_field(name="Görüşürüz mesajı", value=s["goodbye_message"] or "Yapay zeka yazar", inline=False)
    e.add_field(name="Etiketsiz sohbet kanalları", value=", ".join(f"<#{c}>" for c in s["ai_channels"]) or "Yok", inline=False)
    e.add_field(name="Doğal dil moderasyonu", value="Açık ✅" if s["natural_mod"] else "Kapalı ❌")
    await interaction.response.send_message(embed=e, ephemeral=True)


def _set_channel(key: str, label: str):
    async def impl(interaction: discord.Interaction, kanal: discord.TextChannel):
        store.get(interaction.guild_id)[key] = kanal.id
        store.save()
        await interaction.response.send_message(f"✅ {label}: {kanal.mention}", ephemeral=True)
    return impl


@ayar.command(name="hosgeldin-kanali", description="Yeni gelenlerin karşılanacağı kanalı seç")
@app_commands.describe(kanal="Kanal")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_welcome_ch(interaction: discord.Interaction, kanal: discord.TextChannel):
    await _set_channel("welcome_channel", "Hoş geldin kanalı")(interaction, kanal)


@ayar.command(name="gorusuruz-kanali", description="Ayrılanlara veda edilecek kanalı seç")
@app_commands.describe(kanal="Kanal")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_goodbye_ch(interaction: discord.Interaction, kanal: discord.TextChannel):
    await _set_channel("goodbye_channel", "Görüşürüz kanalı")(interaction, kanal)


@ayar.command(name="log-kanali", description="Moderasyon kayıtlarının yazılacağı kanalı seç")
@app_commands.describe(kanal="Kanal")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_log_ch(interaction: discord.Interaction, kanal: discord.TextChannel):
    await _set_channel("log_channel", "Log kanalı")(interaction, kanal)


@ayar.command(name="hosgeldin-mesaji", description="Özel hoş geldin mesajı yaz ({user} {server} {count})")
@app_commands.describe(mesaj="Örn: Hoş geldin {user}! Sen {count}. üyesin. 'sifirla' yazarsan yapay zeka yazar.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_welcome_msg(interaction: discord.Interaction, mesaj: app_commands.Range[str, 1, 500]):
    value = None if mesaj.strip().lower() == "sifirla" else mesaj
    store.get(interaction.guild_id)["welcome_message"] = value
    store.save()
    await interaction.response.send_message("✅ Hoş geldin mesajı güncellendi." if value else "✅ Artık yapay zeka yazacak.", ephemeral=True)


@ayar.command(name="gorusuruz-mesaji", description="Özel veda mesajı yaz ({user} {server} {count})")
@app_commands.describe(mesaj="Örn: {user} aramızdan ayrıldı. 'sifirla' yazarsan yapay zeka yazar.")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_goodbye_msg(interaction: discord.Interaction, mesaj: app_commands.Range[str, 1, 500]):
    value = None if mesaj.strip().lower() == "sifirla" else mesaj
    store.get(interaction.guild_id)["goodbye_message"] = value
    store.save()
    await interaction.response.send_message("✅ Veda mesajı güncellendi." if value else "✅ Artık yapay zeka yazacak.", ephemeral=True)


@ayar.command(name="yz-kanali", description="Botun etiketlenmeden sohbet edeceği kanalları ekle/kaldır")
@app_commands.describe(islem="Ekle veya kaldır", kanal="Kanal")
@app_commands.choices(islem=[
    app_commands.Choice(name="Ekle", value="add"),
    app_commands.Choice(name="Kaldır", value="remove"),
])
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_ai_ch(interaction: discord.Interaction, islem: app_commands.Choice[str], kanal: discord.TextChannel):
    s = store.get(interaction.guild_id)
    if islem.value == "add":
        if kanal.id not in s["ai_channels"]:
            s["ai_channels"].append(kanal.id)
        msg = f"✅ Artık {kanal.mention} kanalında etiketsiz sohbet ederim."
    else:
        s["ai_channels"] = [c for c in s["ai_channels"] if c != kanal.id]
        msg = f"✅ {kanal.mention} kanalında artık sadece etiketlenince cevap veririm."
    store.save()
    await interaction.response.send_message(msg, ephemeral=True)


@ayar.command(name="dogal-dil", description="Doğal dil ile moderasyonu aç/kapat")
@app_commands.describe(durum="Açık mı olsun?")
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_natural(interaction: discord.Interaction, durum: bool):
    store.get(interaction.guild_id)["natural_mod"] = durum
    store.save()
    await interaction.response.send_message("✅ Doğal dil moderasyonu " + ("açıldı." if durum else "kapatıldı."), ephemeral=True)


@ayar.command(name="kapat", description="Bir kanal ayarını kapat")
@app_commands.describe(ayar="Kapatılacak ayar")
@app_commands.choices(ayar=[
    app_commands.Choice(name="Hoş geldin mesajları", value="welcome_channel"),
    app_commands.Choice(name="Görüşürüz mesajları", value="goodbye_channel"),
    app_commands.Choice(name="Log kanalı", value="log_channel"),
])
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_off(interaction: discord.Interaction, ayar: app_commands.Choice[str]):
    store.get(interaction.guild_id)[ayar.value] = None
    store.save()
    await interaction.response.send_message(f"✅ {ayar.name} kapatıldı.", ephemeral=True)


@ayar.command(name="test", description="Hoş geldin / görüşürüz mesajını sana göstererek dene")
@app_commands.describe(tur="Hangisi?")
@app_commands.choices(tur=[
    app_commands.Choice(name="Hoş geldin", value="welcome"),
    app_commands.Choice(name="Görüşürüz", value="goodbye"),
])
@app_commands.checks.has_permissions(manage_guild=True)
async def ayar_test(interaction: discord.Interaction, tur: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    text = await greeting_text(tur.value, interaction.user)
    await interaction.followup.send(f"**Önizleme:**\n{text}", ephemeral=True)


# ───────────────────────── Hata yakalama ─────────────────────────
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Bu komut için yetkin yok."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ Benim bu işlem için iznim eksik."
    else:
        print("Komut hatası:", error)
        msg = "❌ Bir hata oluştu."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
