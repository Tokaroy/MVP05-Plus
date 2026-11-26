"""A holiday message for the Launcher's Play tab, with its emoji (holiday/<name>.png, drawn from Noto Color Emoji:
Tk can't show colour emoji as text).

  today(day)   (picture name, message) on a holiday, else None

New Year's Eve and Day, Opening Day, Easter Sunday, the 4th of July, Thanksgiving (the 4th Thursday of November),
Christmas Eve and Day.
"""
import datetime


def easter(year):
    """Easter Sunday (the Gregorian computus, Anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return datetime.date(year, month, day + 1)


def thanksgiving(year):
    """The 4th Thursday of November."""
    first = datetime.date(year, 11, 1)
    return first + datetime.timedelta(days=(3 - first.weekday()) % 7 + 21)


# Opening Day as MLB set it (its first full day of games, past any overseas opener), by year
OPENING_DAYS = {2025: datetime.date(2025, 3, 27), 2026: datetime.date(2026, 3, 26),
                2027: datetime.date(2027, 3, 24)}  # 2027: as scheduled in July 2026, if the labour deal allows


def opening_day(year):
    """MLB's Opening Day: as set, or for a year not in OPENING_DAYS its usual day, the Thursday from March 25 to 31."""
    if year in OPENING_DAYS:
        return OPENING_DAYS[year]
    first = datetime.date(year, 3, 25)
    return first + datetime.timedelta(days=(3 - first.weekday()) % 7)


def today(day=None):
    day = day or datetime.date.today()
    md = (day.month, day.day)
    if md == (12, 31):
        return "newyear", "Happy New Year's Eve!"
    if md == (1, 1):
        return "newyear", "Happy New Year!"
    if day == opening_day(day.year):
        return "openingday", "Happy Opening Day!"
    if day == easter(day.year):
        return "easter", "Happy Easter!"
    if md == (7, 4):
        return "july4", "Happy 4th of July!"
    if day == thanksgiving(day.year):
        return "thanksgiving", "Happy Thanksgiving!"
    if md == (12, 24):
        return "christmas", "Merry Christmas Eve!"
    if md == (12, 25):
        return "christmas", "Merry Christmas!"
    return None
