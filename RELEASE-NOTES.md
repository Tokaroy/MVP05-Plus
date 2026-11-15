# MVP05-Plus Beta 2.5

Make your own season schedules, and short seasons now finish on their own.

## Highlights
- **Create a schedule** (*Schedule → Create a schedule…*): a season of any even number of games from 12 to 162. Every team plays the same number of games, exactly half at home, in 2 to 4-game series. Interleague as in 2005, matchups you choose, a new matchup each dynasty year, or none (with interleague, 30 games or more). Natural rivals every year if you like, and the All-Star Game hosted by the AL, the NL, or each in turn. A different season for each of the three dynasty years, previewed team by team before you save it to your list.
- **Dynasty goals fit the season:** goals that count games or stats (home and road wins, total wins, team home runs, pitchers' wins, players' home runs) are scaled to your season's length, and so is the win percentage goal (its target and the figure shown beside it). A 40/40 season counts at the same pace (about 11 home runs and 11 steals in 46 games). A 3-year goal of 100 home wins is 28 in a 46-game season.
- **Short seasons end on their own:** a season shorter than 162 games goes on to the playoffs by itself. The game counts the games in your schedule when it starts, so it works whichever schedule is installed and however it got there.
- **Game Tweaks**: changes to how the game plays, built into MVP05-Plus: *Gameplay adjustments* and *Dynasty adjustments* in the Tools tab, *Graphics and memory…* in the Settings tab. The first is **Pitchers' rest**: slow down how fast pitchers get their stamina back between games, so a starter needs about four days like a five-man rotation and a busy bullpen tires. Also **Injury length**: injured players out half as long, or longer (up to twice). And **Memory**: double the Xbox's 64 MB to 128 MB, growing the game's heap from 41 MB to 97 MB, for mods that load more than the Xbox could hold. And **Graphics**: every player's most detailed model, day games in daylight at Fenway, Turner Field and the other parks EA lit as dusk, and EA's depth of field (off on the Xbox; being tested). And **Weather**: rain in every game (EA's rain, still in the game; being tested). And **Dynasty** (its own tab): how fast players develop and decline with age, how often they retire, free agents' asking prices, the chance your players re-sign, neutral park factors in simulated games, and more star-level rookies, all through EA's own data tables. All are off unless you pick them (MVP 05 Default).
- **Extras** (in-game Tools menu, F10): **Unlock everything** and **Add MVP points**, EA's own from their debug menu, for the profile you're signed in with.
- **Dynasty** (in-game Tools menu): set your **Owner Mode bank balance**, and **hold your manager rating** so you keep your job.

## Changed
- **Standings Projector** (was the Short Season Advancer): no longer needed for short seasons. It's kept for a dynasty stuck at the end of a short season from an older version.

## Known issues
- **Switching schedules mid-season:** a new schedule starts with the next season. Switching in the middle of one changes that season's length from the next time the game starts, so switch between seasons.

## Updating
From Beta 2 or 2.1: *Settings → Updates*. From Beta 1: unzip into a new folder and bring your old one over when the Launcher asks.

# MVP05-Plus Beta 2.1

- **Player of the Day** on the *Play* tab: an MLB player from the game's 2005 rosters, with his picture and 2004 season, the same for everyone each day. It's read from your own installed game.
- Updating from Beta 2: *Settings → Updates*.

# MVP05-Plus Beta 2

Bring your saves over from the other versions of MVP 2005, pick the season you play, run tools inside the game, and update from the Launcher.

## Highlights
- **Import saves from the PS2, GameCube, PC and Xbox** (*Saves → Import a save…*): rosters and dynasties, converted into one of your MVP05-Plus saves so they play here. Your save is backed up first.
- **Custom season schedules** (*Schedule* tab): the real 2005 season, or its 162 games shuffled each time you play. A 64-game season made for MVP05-Plus balances division, league and interleague games. Basic 60, 30 and 15-game schedules are included, or you can import your own.
- **Tools** (the Launcher's *Tools* tab, and in the game: F10, or hold Back + Start / Z + Start): a Short Season Advancer, a Team Changer and a Playoffs Editor.
- **Updates from the Launcher** (*Settings → Updates*): check, install and undo, from this version on.

## Import saves
*Saves → Your saves → Import a save…*: choose the save, pick which of your saves it goes into (it's backed up first, in *Saves → Backups*), and import. Save your rosters, or start a dynasty and save it, in the game once so you have a save of that kind to import into.
- **PS2:** rosters and dynasties, from a `.psu`, a PCSX2 memory card (`.ps2`: you pick the save on it), or the `.sav` from a save.
- **GameCube:** rosters and dynasties, from the `.gci` Dolphin exports.
- **PC:** rosters and dynasties (`.sav`).
- **Xbox:** rosters and dynasties from another Xbox (its `data.dat`).
- Owner mode saves aren't imported yet (planned for 3.0).

Roster conversion is **Mad Dog**'s, from his MVP Roster Toolkit (the same file it makes). GameCube conversion, rosters and dynasties, is **spy_jam**'s. PS2 and PC dynasties use both.

## Custom season schedules
The *Schedule* tab sets the schedule new seasons play. Only the three MLB schedules in your game's `schedule.big` change (the minor leagues and spring training stay the game's own), and your original is kept.
- **162 games:** the MVP 2005 disc's, the real 2005 season.
- **162 games, shuffled:** the 2005 schedule with the teams in each division dealt one another's seasons. Every team keeps 81 home games and the same division, league and interleague games, against opponents in a new order; dates and the All-Star break stay put. A new shuffle every time the Launcher starts the game; a season already under way keeps its own.
- **64 games,** made for MVP05-Plus: 6 games against each division rival, 2 or 3 against the rest of the league, every interleague team once (the natural rival twice), even home and away, the All-Star Game in July and a real trade deadline.
- **60, 30 and 15 games:** basic short seasons.
- **Import a schedule:** a `schedule.big`, or its `mlb162_1/2/3.dat` files, from any version of MVP 2005 (they're the same on every platform). It's checked (all 30 teams, the same number of games each), joins the list, can be removed again, and updates never touch it.

## Tools
In the game's Tools menu (F10, or hold Back + Start for a second, Z + Start on a GameCube controller; any controller or the mouse moves around it, and the game gets no input while it's open) and in the Launcher's *Tools* tab:
- **Short Season Advancer:** a season shorter than 162 games stops at the end of the regular season until the standings are 162 games long. At its end, it finds the standings and writes them projected to 162 games, every team keeping its winning percentage, so the season goes on to the playoffs. The season's length comes from the *Schedule* tab. In the Launcher it also works on a saved dynasty with the game closed.
- **Team Changer:** take over another organization in your dynasty or owner mode; save to keep it. A port of **tywiggins'** MVP 2005 Team Changer (2006, for the PC game).
- **Playoffs Editor:** choose who plays in the playoffs. When a playoff round has started, before its first game, swap any team in it for another organization; each series keeps its dates and home field. In the running game or on a saved dynasty. Based on **tywiggins'** MVP 2005 Playoffs Creator (2006, for the PC game).

tywiggins' tools were made for the PC game; the Xbox game keeps its database in memory the same way, so they carry over.

## Launcher
- **Updates** (*Settings → Updates*): shows your version, checks GitHub for a newer release (also when the Launcher opens, unless you turn that off), shows what's new and installs it: the program files only, checked against the release's manifest. Your game files, saves, backups, button art, shader cache and imported schedules are never touched, and your settings are kept, with new options added. *Back to …* undoes the last update.
- **A tidier layout:** *Play*, *Saves* (your saves and backups), *Schedule*, *Tools* (a list: open the one you want) and *Settings* (desktop shortcuts and updates side by side).
- **Your game's title art** on the *Play* tab, from your own Xbox disc.
- **Controllers:** an Xbox-style controller, or a GameCube controller on the adapter (with its WinUSB driver), moves around the Launcher: d-pad or stick, A presses, B goes back, LB / RB (L / R) switch tabs, Start launches the game from *Play*.
- **Bring over an older install:** the first time the Launcher opens in a new folder (or on Ctrl+Shift+B), it offers to bring MVP05-Plus Beta 1 or Mad Dog's MVP05 over: its game, saves and settings, copied or moved in.
- **Install progress:** one bar across the whole install ("Step 2 of 3: making the PS2 button art") with the time so far.
- *Launch MVP 05* minimizes the Launcher instead of closing it, so it's an alt-tab away while you play; it closes when the game does, unless you've brought it back up.

## Game
- **Low latency** (*Settings*, off by default): one finished frame waits for the screen instead of up to three, for up to about two frames (~33 ms at 60 Hz) less delay between a button and the screen. It can stutter on a slower PC, so it starts off.
- **Esc** asks "Quit MVP05-Plus?".

## Fixed
- The Launcher's *Settings* no longer drops the note after a text setting (such as `display_mode`) in `mvp05-settings.toml`.

## Coming from Beta 1 or Mad Dog's MVP05
Unzip MVP05-Plus into a new folder and open the Launcher. It asks to bring over your game, saves and settings, so you don't need your discs again. Said no? Press **Ctrl+Shift+B** in the Launcher to be asked again. From Beta 2 on, *Settings → Updates* updates MVP05-Plus for you.

## Thanks
**Mad Dog** for MVP05 and his MVP Roster Toolkit, **tywiggins** for his MVP 2005 tools, and **TGP482** for XboxXBERecomp.

# MVP05-Plus Beta 1

First release of MVP05-Plus by spy_jam, built on Mad Dog's MVP05 Public Beta 3 (made with TGP482's XboxXBERecomp).

## New
- **GameCube controllers** through a Wii U / Switch GameCube adapter (official or compatible, in Wii U mode), all 4 ports, with rumble. Stick, C-stick and triggers handled as the GameCube release does. Hold X + Y + Start for 3 seconds to recentre.
- **PlayStation controllers** with the PS2 release's stick handling, analog button pressure and rumble.
- **Native control layouts:** GameCube controllers use the GameCube release's layout, PlayStation controllers the PS2 release's.
- **Button art:** GameCube or PS2 button pictures in menus, help bars and in-game, picked from the controller connected at start. Built by the Launcher from your own discs (optional).
- **MVP05-Plus Launcher** (`MVP05-Plus-Launcher.exe`): installs from your discs (the Xbox game into `assets/`, and the button art from only the files it needs on your GameCube and PS2 discs), then opens on *Play*, with Launch and which controllers Windows sees, including whether the GameCube adapter has its WinUSB driver. Also *Saves* and *Settings* (display mode, aspect ratio, resolution and more, and desktop shortcuts if you want them). Portable: everything stays in the game folder.
- **Shader cache** in `shader_cache/`, so shaders compile once instead of every run.
- **The game's icon**, made from your own Xbox disc by the Launcher.
- **Save backups** at startup, in `save backups/` (30 kept by default), listed in the Launcher's *Saves* tab, where you can restore single saves or a whole date.
- **Esc quits** after asking (Alt+F4 still works). Don't quit while the game is saving.
- **Fullscreen by default**, at your desktop's own resolution (Mad Dog's release starts windowed at 1920 x 1080); change it in the Launcher's *Settings* tab.

## Fixed
- A crash during stolen bases, found in testing.
- SteamOS (through Proton): the black screen; the GameCube adapter through `gcbridge` (see the README for the launch option).

## Known issues
- Under Proton, the GameCube adapter needs the Steam launch option; the game can't start `gcbridge` by itself yet.
- Display issues from the base recompilation (for example 720p fonts) are unchanged.

## Requirements
Windows 10/11 x64 (or SteamOS with Proton), a DirectX 12 graphics card, about 4 GB free, and your own MVP Baseball 2005 Xbox disc image. GameCube and PS2 discs are optional, for button art. Nothing else to install.
