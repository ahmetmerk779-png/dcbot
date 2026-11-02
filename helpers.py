
# helpers.py
def level_from_xp(xp: int):
    xp = max(0, xp)
    level = 0
    total_before = 0
    next_need = 100

    while xp >= next_need:
        total_before += next_need
        level += 1
        next_need = 100 + (level * 25)

    current = xp - total_before
    return level, current, next_need


def progress_bar(current: int, need: int, width: int = 20) -> str:
    if need <= 0:
        return "█" * width
    ratio = max(0, min(1, current / need))
    filled = int(ratio * width)
    return "█" * filled + "░" * (width - filled)
