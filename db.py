"""Discord sunucusunu veritabanı olarak kullanan depolama katmanı.

Her sunucuda gizli bir `bot-veritabani` kanalı açılır. Veriler bu kanaldaki mesajlara
JSON dosyası olarak yazılır, bot açılırken oradan okunur. Böylece Render gibi dosyaları
silen platformlarda bile veriler kaybolmaz.

Çalışma mantığı: veriler bellekte (cache) tutulur, değişiklikler birkaç saniyede bir
toplu olarak Discord'a yazılır (hız sınırlarına takılmamak için).
"""
import asyncio
import io
import json
import time

import discord

DB_CHANNEL_NAME = "bot-veritabani"
DOCS = ("config", "members", "data")

# Kanal ayarlarının varsayılanları (kanalda özel ayar yoksa bunlar geçerli)
CHANNEL_DEFAULTS = {
    "ai": "mention",      # off | mention | always
    "xp": True,
    "economy": True,
    "games": True,
    "automod": True,
    "media_only": False,
}


class Store:
    def __init__(self):
        self.bot = None
        self.cache = {}        # guild_id -> {belge_adı: dict}
        self.channels = {}     # guild_id -> veritabanı kanalı
        self.msgs = {}         # (guild_id, belge_adı) -> Discord mesajı
        self.dirty = set()     # yazılmayı bekleyen (guild_id, belge_adı)
        self.loaded = set()
        self.persistent = {}   # guild_id -> Discord'a kaydediliyor mu?
        self._lock = asyncio.Lock()

    def attach(self, bot):
        self.bot = bot

    # ---------- Bellek erişimi ----------
    def get(self, guild_id, doc):
        return self.cache.setdefault(guild_id, {}).setdefault(doc, {})

    def mark(self, guild_id, doc):
        self.dirty.add((guild_id, doc))

    # ---------- Discord'dan yükleme ----------
    async def _create_channel(self, guild):
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
        }
        try:
            return await guild.create_text_channel(
                DB_CHANNEL_NAME,
                overwrites=overwrites,
                topic="⚠️ Bot veritabanı. Bu kanalı silme, mesajları düzenleme veya buraya yazma!",
                reason="Bot veritabanı kanalı",
            )
        except discord.HTTPException as e:
            print(f"[DB] {guild.name}: veritabanı kanalı oluşturulamadı: {e}")
            return None

    async def load_guild(self, guild):
        gid = guild.id
        if gid in self.loaded:
            return
        self.dirty = {k for k in self.dirty if k[0] != gid}
        docs = {name: {} for name in DOCS}

        channel = discord.utils.get(guild.text_channels, name=DB_CHANNEL_NAME)
        if channel is None:
            channel = await self._create_channel(guild)
        if channel is None:
            self.cache[gid] = docs
            self.persistent[gid] = False
            self.loaded.add(gid)
            return

        found = {}
        try:
            async for m in channel.history(limit=200, oldest_first=True):
                if not (self.bot and m.author.id == self.bot.user.id and m.attachments):
                    continue
                if not m.content.startswith("DB:"):
                    continue
                name = m.content[3:].strip()
                if name not in DOCS:
                    continue
                try:
                    data = json.loads((await m.attachments[0].read()).decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("belge sözlük değil")
                    docs[name] = data
                    found[(gid, name)] = m
                except Exception as e:
                    print(f"[DB] {guild.name}: '{name}' okunamadı, yeni belge açılacak: {e}")
        except discord.HTTPException as e:
            # Okuma hatasında veriyi boş bir belgeyle ezmemek için sadece bellekte çalış
            print(f"[DB] {guild.name}: veritabanı okunamadı, bellekte çalışılıyor: {e}")
            self.cache[gid] = docs
            self.persistent[gid] = False
            self.loaded.add(gid)
            return

        self.cache[gid] = docs
        self.channels[gid] = channel
        self.msgs.update(found)
        self.persistent[gid] = True
        for name in DOCS:
            if (gid, name) not in self.msgs:
                self.dirty.add((gid, name))
        self.loaded.add(gid)
        print(f"[DB] {guild.name}: veritabanı yüklendi ({len(found)}/{len(DOCS)} belge bulundu).")

    # ---------- Discord'a yazma ----------
    async def flush(self):
        async with self._lock:
            for key in list(self.dirty):
                gid, name = key
                self.dirty.discard(key)
                channel = self.channels.get(gid)
                if gid not in self.loaded or channel is None:
                    continue
                payload = json.dumps(
                    self.cache.get(gid, {}).get(name, {}), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                file = discord.File(io.BytesIO(payload), filename=f"{name}.json")
                msg = self.msgs.get(key)
                try:
                    if msg is not None:
                        self.msgs[key] = await msg.edit(content=f"DB:{name}", attachments=[file])
                    else:
                        self.msgs[key] = await channel.send(f"DB:{name}", file=file)
                except discord.NotFound:
                    if msg is not None:
                        self.msgs.pop(key, None)  # mesaj silinmiş, yenisini oluştur
                        self.dirty.add(key)
                    else:
                        print(f"[DB] {gid}: veritabanı kanalı silinmiş, kayıt durdu.")
                        self.channels.pop(gid, None)
                        self.persistent[gid] = False
                except discord.HTTPException as e:
                    print(f"[DB] {gid}: '{name}' yazılamadı, tekrar denenecek: {e}")
                    self.dirty.add(key)

    def export(self, guild_id):
        return {
            name: json.dumps(self.cache.get(guild_id, {}).get(name, {}), ensure_ascii=False, indent=1).encode("utf-8")
            for name in DOCS
        }


store = Store()


# ---------- Ham belgelere erişim ----------
def get_config(gid):
    return store.get(gid, "config")


def save_config(gid):
    store.mark(gid, "config")


def get_data(gid):
    return store.get(gid, "data")


def save_data(gid):
    store.mark(gid, "data")


# ---------- Ayarlar ----------
def get_setting(guild_id, key, default=None):
    value = get_config(guild_id).get("settings", {}).get(key)
    return value if value is not None else default


def set_setting(guild_id, key, value):
    """value=None verilirse ayar silinir."""
    settings = get_config(guild_id).setdefault("settings", {})
    if value is None:
        settings.pop(key, None)
    else:
        settings[key] = str(value)
    save_config(guild_id)


def get_channel_id(guild_id, key):
    value = get_setting(guild_id, key)
    return int(value) if value else None


def flag(guild_id, key):
    return get_setting(guild_id, key) == "1"


# ---------- Kanal bazlı ayarlar ----------
def channel_overrides(guild_id, channel_id):
    return get_config(guild_id).get("channels", {}).get(str(channel_id), {})


def channel_option(guild_id, channel_id, key):
    overrides = channel_overrides(guild_id, channel_id)
    if key in overrides:
        return overrides[key]
    return CHANNEL_DEFAULTS.get(key)


def automod_flag(guild_id, channel_id, key):
    """Otomod özelliği bu kanalda açık mı? Kanalda özel ayar varsa o, yoksa sunucu ayarı."""
    overrides = channel_overrides(guild_id, channel_id)
    if key in overrides:
        return bool(overrides[key])
    return flag(guild_id, key)


def set_channel_option(guild_id, channel_id, key, value):
    """value=None verilirse kanal ayarı silinir (varsayılana döner)."""
    channels = get_config(guild_id).setdefault("channels", {})
    entry = channels.setdefault(str(channel_id), {})
    if value is None:
        entry.pop(key, None)
    else:
        entry[key] = value
    if not entry:
        channels.pop(str(channel_id), None)
    save_config(guild_id)


def reset_channel(guild_id, channel_id):
    get_config(guild_id).get("channels", {}).pop(str(channel_id), None)
    save_config(guild_id)


def list_configured_channels(guild_id):
    return {int(cid): opts for cid, opts in get_config(guild_id).get("channels", {}).items()}


# ---------- Seviye rolleri ----------
def level_roles(guild_id):
    return {int(lvl): rid for lvl, rid in get_config(guild_id).get("level_roles", {}).items()}


def set_level_role(guild_id, level, role_id):
    roles = get_config(guild_id).setdefault("level_roles", {})
    if role_id is None:
        roles.pop(str(level), None)
    else:
        roles[str(level)] = role_id
    save_config(guild_id)


# ---------- Üye verileri (XP, altın...) ----------
def member(guild_id, user_id):
    members = store.get(guild_id, "members")
    entry = members.get(str(user_id))
    if entry is None:
        entry = {"xp": 0, "level": 0, "coins": 0, "msgs": 0}
        members[str(user_id)] = entry
    return entry


def all_members(guild_id):
    return store.get(guild_id, "members")


def save_members(guild_id):
    store.mark(guild_id, "members")


# ---------- Uyarılar ----------
def add_warning(guild_id, user_id, mod_id, reason):
    """Uyarıyı ekler ve kullanıcının toplam uyarı sayısını döndürür."""
    data = get_data(guild_id)
    data["warn_seq"] = data.get("warn_seq", 0) + 1
    data.setdefault("warnings", []).append(
        {"id": data["warn_seq"], "user_id": user_id, "mod_id": mod_id, "reason": reason, "created_at": int(time.time())}
    )
    save_data(guild_id)
    return count_warnings(guild_id, user_id)


def count_warnings(guild_id, user_id):
    return sum(1 for w in get_data(guild_id).get("warnings", []) if w["user_id"] == user_id)


def list_warnings(guild_id, user_id):
    items = [w for w in get_data(guild_id).get("warnings", []) if w["user_id"] == user_id]
    return list(reversed(items))[:25]


def delete_warning(guild_id, warning_id):
    data = get_data(guild_id)
    before = len(data.get("warnings", []))
    data["warnings"] = [w for w in data.get("warnings", []) if w["id"] != warning_id]
    save_data(guild_id)
    return len(data["warnings"]) < before


def clear_warnings(guild_id, user_id):
    data = get_data(guild_id)
    before = len(data.get("warnings", []))
    data["warnings"] = [w for w in data.get("warnings", []) if w["user_id"] != user_id]
    save_data(guild_id)
    return before - len(data["warnings"])


# ---------- Yasaklı kelimeler ----------
def add_badword(guild_id, word):
    words = get_config(guild_id).setdefault("badwords", [])
    if word not in words:
        words.append(word)
        save_config(guild_id)


def remove_badword(guild_id, word):
    words = get_config(guild_id).setdefault("badwords", [])
    if word in words:
        words.remove(word)
        save_config(guild_id)
        return True
    return False


def list_badwords(guild_id):
    return list(get_config(guild_id).get("badwords", []))
