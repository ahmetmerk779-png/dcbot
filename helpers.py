"""XP/seviye yardımcıları used by the leveling cog."""


def level_from_xp(xp: int) -> tuple[int, int, int]:
    """Return (level, XP earned in current level, XP needed for next level).

    Level 0 starts at 0 XP and requires 100 XP to reach level 1. Each
    subsequent level requires 25 more XP than the previous one.
    """
    remaining_xp = max(0, int(xp))
    level = 0
    needed = 100

    while remaining_xp >= needed:
        remaining_xp -= needed
        level += 1
        needed = 100 + level * 25

    return level, remaining_xp, needed


def progress_bar(current: int, need: int, width: int = 20) -> str:
    """Render current progress as a text bar."""
    width = max(1, int(width))
    need = int(need)
    current = max(0, int(current))

    if need <= 0:
        filled = width
    else:
        filled = min(width, current * width // need)

    return "█" * filled + "░" * (width - filled)
