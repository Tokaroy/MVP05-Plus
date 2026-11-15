# MVP05-Plus 3.0: plan

3.0 is **owner mode save imports**, once everything in Beta 2.5 tests out. Everything else that was planned for Beta 3
has moved to *Future* below. Beta 2 was released on 2026-11-13.

## Owner mode imports (3.0)
Import owner mode saves from the PS2, GameCube, PC and Xbox, as dynasties are now. Owner mode is its own mode with its own save type. It needs matched pairs: a new owner mode save with the same team on each platform, saved straight away.
Goes with it: tywiggins' ChangeMoney (owner mode money) and the Owner Mode bank balance in the Tools menu
([[[0x657288]+0x34]+4]+0x12B7C, a float in dollars).

# Future

## Payroll budget (dynasty)
Not the Owner Mode bank balance. In memory the org table (vtable 0x5B13C0, 34 records of 0x54 bytes, SetField
0x444B60) has a dword at +0x38 that looks like payroll in dollars ($38.3M for one team, $173.2M for another); to
confirm against a team's budget screen. org.dat's CSV has org_budget.
From the save side: every team has a budget in dynasty mode. In a save, org record halfword s21 is the budget in $100K units (FORMAT_NOTES 3.7). Needs the other money figures from the budget screen. tywiggins' ChangeMoney is for owner mode and goes with the owner mode work.

## Stats editor
EA's Stat Pumper from their debug menu (constructor 0x4E5FF0, Execute 0x4B64E0; setters on 0x657288: 0x1ACBC0,
0x1AC250, 0x1AC210, 0x1AC310, 0x1ACC50, 0x1AC390, 0x1AC350; is-pitcher 0x1B8150): 7 stat categories, 0..10000.

## More Game Tweaks
- **Free camera.**
- **Sky and time of day:** the stadium loader 0x130250 has overrides at 0x653F24/28 (field, 0..2) and 0x653F2C/30
  (sky, 0..4).
- **Other datafile.big visuals:** fog, shadow alpha, fireworks.

## Draft class from MVP 06 (to look into)
Requested by a player: the college players from an MVP 06 dynasty become the draft class of an MVP 2005 dynasty, as
EA's NCAA Football draft classes went into Madden. In use: choose an 06 dynasty save (end of season) and one of your
05 dynasty saves in the Launcher; the draft-eligible players (juniors and seniors, or a pick) are converted to 2005's
player format and put in the 05 dynasty's draft pool. To work out first:
- **06 players:** where an 06 save keeps each player's name, position, year, ratings and appearance (the saves
  already convert between platforms, but the player records aren't decoded).
- **05 draft pool:** where an 05 dynasty keeps its draft prospects, and whether they're made from the disc's
  `database/rookie.big` or kept in the save. Needs 05 dynasty saves from just before and just after a draft.
- **Translation:** 06 and 05 ratings and looks don't line up one to one; each needs a rule (and how many players
  the pool takes).

## Also open
- **Stamina Changer:** tywiggins' spot (data + 0x231420) holds heap headers on the Xbox, so it needs its own search.
- **GameCube dynasty converter:** history merge by overlap rather than by year (see the save conversion notes, 4.4).
- **Dynasty export to GameCube** from the Launcher (the converter already does it).
- **Low latency for MVP06-Plus;** MVP 2004.

# Done

## Player of the day
Done in Beta 2.1 (tools/installer/potd.py): local date, counted from 2026-11-13 through a SHA-256 shuffle of all the players (each once per round of 731 days); the 30 franchises' default rosters in database/database.big with a picture in frontend/portrait.big (named by playerattrib_audioid), 731 players. The notes below were the plan.

A card across the empty bottom of the *Play* tab: a player's picture, name, team and position (maybe a line of ratings or 2004 stats), a different player each day and the same one for everyone.
- **Pick:** take a fixed hash of the date (for example SHA-256 of `2027-03-14`), modulo the number of eligible players. Don't use a random generator, whose output can change between Python versions. Decide whether the date is local (changes at each player's midnight) or UTC (changes for everyone at the same moment).
- **Players:** the disc's default MLB rosters (the same for everyone), sorted by player id. Never the player's own saves, which drift with trades, imports and edits. Only MLB rosters, and only players with a picture.
- **Picture:** read from the player's own installed game files at run time, like the title art. EA's art is never shipped. First, find where MVP 2005 keeps player headshots in its `.big` files and in what texture format, and whether every MLB player has one. That needs a listing of `assets\data` and a few `.big` files from a real install.
- **Layout:** the dog easter egg uses the bottom-right corner, so leave room for it or let it sit on top of the card.

## Create a schedule (Beta 2.5)
The Schedule tab's *Create a schedule…* (a window like *Import a schedule…*; the seasons from tools/installer/
schedgen.py): any even length from 12 to 162 games (30 or more with interleague, so every team plays some);
interleague shared out evenly as in 2005, chosen division matchups, a new matchup each
dynasty year, or none; natural rivals every year (or not); the All-Star Game hosted by the AL, the NL, or each in
turn; a different season for each of the three dynasty years, shown team by team and year by year, with Regenerate
for another one. *Save* adds it to the list under a name ("created by you"), kept with the imported ones in
schedules/imported/ (updates and Bring it over keep them), used and removed the same way. Every team plays the same
number of games in 2- to 4-game series, exactly half at home, with the disc's proportions of division, league and
interleague games, on 2005's calendar (opening day April 4, the All-Star Game July 12; 100+ games fill the
calendar, shorter seasons play a first half from opening day and a second half from August 1, after the trade
deadline). Our own code: nothing from Dylan Bradbury's Random Schedule Generator, whose readme forbids
redistributing or editing it.
**To test in the game:** a dynasty through a full created season into year 2, at 162 and at a short length (64), and
with interleague off; the All-Star Game hosted by the NL. Then Beta 3, or a 2.5.

## Short seasons end on their own (built, tested by spy_jam)
The game measures a season against its league's length (0x19D190: 162 for the majors, 144 AAA, 142 AA, 140 A;
asked from db_sec at 0x466692, 0x467008, 0x49174D and through 0x1AEC10). src/game/hooks.cpp gives the majors
the schedule's length, counted from the installed schedule.big when the game starts (src/common/season_length.cpp;
season_games from the Launcher only if it can't be counted), so a short season goes on to the playoffs by itself. The Short Season Advancer is now
the Standings Projector (not needed; for dynasties stuck from an older version). Ctrl+Shift+F9 in the game saves a
memory capture to logs (the menu button is gone). **Still open:** a schedule switched mid-season is counted at the next start
while the old season is still played (switch between seasons, as the Schedule tab says); the dynasty goals: their counting targets are now
scaled while the game reads them (hooks.cpp: the goal object, vtable 0x5B8BCC, 32 records of on/X/Y; readers 0x1DC8C0
met?, 0x1DC960 progress, 0x1DCB10 text, 0x1F63E0 screen line, 0x1F6650 progress figure; WinPct checked as X * 486 =
3 x 162 at 0x5B8C30). To check in game: the per-player goals (XWinsbyYP, XHRsYplayers) count players through the
stat tracker (0x49B0C0 → 0x1ACCB0), which may use its own threshold.
