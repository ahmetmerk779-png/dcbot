"""Discord'dan bağımsız saf yardımcılar (test edilebilir): süre, seviye, oyunlar, tarih."""
import random
import re
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))  # Türkiye saati

UNITS = {"s": 1, "sn": 1, "m": 60, "dk": 60, "h": 3600, "sa": 3600, "d": 86400, "g": 86400}
_PART = re.compile(r"(\d+)\s*([a-zçğıöşü]+)")


def now_tr():
    return datetime.now(TZ)


# ---------- Süre ----------
def parse_duration(text):
    """'10m', '2sa', '1g', '1sa 30dk' gibi metni saniyeye çevirir. Geçersizse None."""
    text = (text or "").lower().strip()
    parts = _PART.findall(text)
    if not parts or _PART.sub("", text).strip():
        return None
    total = 0
    for number, unit in parts:
        if unit not in UNITS:
            return None
        total += int(number) * UNITS[unit]
    return total or None


def format_duration(seconds):
    seconds = int(seconds)
    parts = []
    for name, size in (("g", 86400), ("sa", 3600), ("dk", 60), ("sn", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size}{name}")
            seconds %= size
    return " ".join(parts) or "0sn"


def parse_hhmm(text):
    """'9:30', '09.30', '21:05' -> '09:30'. Geçersizse None."""
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def next_daily(hhmm, now=None):
    """Türkiye saatine göre bir sonraki HH:MM anının unix zamanı."""
    now = now or now_tr()
    h, m = (int(x) for x in hhmm.split(":"))
    cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= now:
        cand += timedelta(days=1)
    return int(cand.timestamp())


# ---------- Seviye ----------
def xp_for_level(level):
    """Bir seviyeden sonrakine geçmek için gereken XP."""
    return 5 * level * level + 50 * level + 100


def level_from_xp(xp):
    """(seviye, bu seviyedeki XP, sonraki seviye için gereken XP)"""
    level = 0
    xp = max(0, int(xp))
    while xp >= xp_for_level(level):
        xp -= xp_for_level(level)
        level += 1
    return level, xp, xp_for_level(level)


def progress_bar(current, total, width=10):
    filled = 0 if total <= 0 else min(width, int(width * current / total))
    return "█" * filled + "░" * (width - filled)


# ---------- Otomod ----------
def is_shouting(text, min_letters=12, ratio=0.7):
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) < min_letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= ratio


# ---------- Ekonomi / oyunlar ----------
def bank_interest(bank, days, rate=0.01, cap=5000):
    """Basit günlük faiz (en fazla 30 gün birikir), tek seferde en çok `cap` altın."""
    days = max(0, min(30, int(days)))
    return min(cap, int(bank * rate * days))


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_color(n):
    if n == 0:
        return "yesil"
    return "kirmizi" if n in RED_NUMBERS else "siyah"


def roulette_gain(bet, choice, n):
    """Net kazanç (kayıpta -bet). Kırmızı/siyah/tek/çift 2x, yeşil (0) 14x toplam geri ödeme."""
    color = roulette_color(n)
    if choice in ("kirmizi", "siyah"):
        return bet if color == choice else -bet
    if choice == "yesil":
        return bet * 13 if n == 0 else -bet
    if choice == "tek":
        return bet if n != 0 and n % 2 == 1 else -bet
    if choice == "cift":
        return bet if n != 0 and n % 2 == 0 else -bet
    return -bet


SUITS = ["♠️", "♥️", "♦️", "♣️"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def new_deck():
    deck = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def card_value(rank):
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_value(hand):
    total = sum(card_value(r) for r, _ in hand)
    aces = sum(1 for r, _ in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def format_hand(hand, hide_second=False):
    if hide_second and len(hand) >= 2:
        return f"{hand[0][0]}{hand[0][1]} ❓"
    return " ".join(f"{r}{s}" for r, s in hand)


# ---------- Doğum günü ----------
def valid_day_month(day, month):
    try:
        date(2000, month, day)  # 2000 artık yıl, 29 Şubat geçerli
        return True
    except ValueError:
        return False


def days_until_birthday(ddmm, today):
    """'DD-MM' biçimindeki doğum gününe kaç gün kaldı (bugünse 0)."""
    d, m = (int(x) for x in ddmm.split("-"))
    for year in (today.year, today.year + 1):
        try:
            cand = date(year, m, d)
        except ValueError:  # 29 Şubat artık olmayan yıl
            cand = date(year, 2, 28)
        if cand >= today:
            return (cand - today).days
    return 365
