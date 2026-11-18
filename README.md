# MVP05-Plus

MVP Baseball 2005 on Windows, and on SteamOS (Linux) through Proton, built on [Mad Dog's](#credits) PC port of the Original Xbox game. spy_jam's MVP05-Plus adds GameCube and PlayStation controllers with their full control layouts and button art, saves that move to and from the PS2, GameCube and PC versions, your own season schedules (short seasons included), mods, game tweaks, in-game tools, and **League News**: your dynasty as a 2006-style baseball website. All of it runs from one Launcher that installs from your own discs, backs up your saves and installs updates.

> **You need your own copy of the Xbox game.** No game files or game art are included. The Launcher builds what's needed from your own discs.

## Features

* **GameCube controllers** through a Wii U / Switch adapter: all 4 ports and rumble, with the GameCube release's full control layout, stick deadzones, C-stick and analog trigger handling.
* **PlayStation controllers** with the PS2 release's full control layout and stick handling, analog button pressure and rumble.
* **Button art to match your controller**: GameCube or PS2 buttons in menus and in-game, made from your own discs (optional).
* **League News** *(new)*: your dynasty or owner mode as an MVP Baseball website in your browser, laid out like a baseball front page from 2006. It has the standings and scores, box-score recaps with the winning, losing and saving pitchers, and the league leaders. There's a page for every club with its roster, schedule, season series and farm teams, and a page for every player with his stats, contract and transactions. It also has milestone watch, awards races, pennant race charts, power rankings, a farm report with the top prospects, and a transactions wire. Stats include OPS, OPS+ and ERA+. Each game day is kept as its own edition, so you can page back through the season.
* **Import and export saves**: rosters, dynasties and owner modes to and from the PS2, GameCube, PC and Xbox versions of MVP 2005. They go straight from and onto PCSX2 memory cards and Dolphin's cards (.raw cards, or its GCI folder), or as a zip to share.
* **More than four saves**: the game holds 4 saves of each type. The Launcher keeps as many as you like, with a checkbox on each for the ones in the game.
* **Custom season schedules**: the real 2005 season, or its 162 games shuffled each time you play. Create your own at any even length from 12 to 162 games, preview it team by team, and share or import schedules. A 64-game season made for MVP05-Plus balances division, league and interleague games, and 60, 30 and 15-game schedules are included. Shorter seasons end on their own and go on to the playoffs, and dynasty goals scale to the season's length.
* **Mods**: add a mod from a folder, files or a zip (or drag it onto the Mods tab), and each file goes in place of the game's own. Each mod has its own checkbox to turn it on or off, and there's an option to double the game's memory for big mods.
* **Game Tweaks**: optional changes to how the game plays, all off unless you pick them. Dynasty adjustments cover pitchers' rest, injury length, player development and aging, retirement, contract prices, re-signing and rookies. Graphics settings add more detailed players away from the play.
* **Tools**: in the Launcher's Tools tab and in the game (F10, or hold Back + Start / Z + Start). A Team Changer, a Playoffs Editor, a Stamina Changer, the Payroll Budget and an owner's bank balance, a Standings Projector, Unlock everything, Add MVP points, and EA's own debug menu.
* **MVP05-Plus Launcher**: install from your discs, launch the game, manage saves, mods and schedules, run the tools, open League News, adjust display settings, and update MVP05-Plus. It also shows a Player of the Day.
* **Save backups**: your saves are backed up automatically when the game starts, keeping the latest 30 by default, and every Launcher change to a save is backed up first. View and restore them by date in the Launcher.
* **Fixes**: a shader cache to prevent mid-game stutter, SteamOS support through Proton, and a fix for a crash during stolen bases, found while testing the original recomp.

## Compatible controllers

* **GameCube controllers** (official adapter, or a third-party adapter in Wii U mode) — GameCube button art and controls
* **DualSense, DualShock 4** — PS2 button art and controls
* **DualShock 3** — PS2 button art and controls, with pressure-sensitive buttons (on Windows, through [DsHidMini](https://github.com/nefarius/DsHidMini) in SDL mode)
* **Xbox 360, Xbox One and Xbox Series controllers** — Xbox button art and controls, as the original
* **Other controllers** (Switch Pro and most others SDL supports) — Xbox button art and controls

Button icons match the controller connected when the game starts. Without the art sets, PlayStation and GameCube controllers still use their own control layouts, with Xbox buttons shown.

## Coming from an earlier MVP05-Plus or Mad Dog's MVP05

From Beta 2 or later: *Settings → Updates* in the Launcher. From Beta 1 or Mad Dog's MVP05: unzip MVP05-Plus into a new folder and open the Launcher. It asks to bring over your game, saves and settings, so you don't need your discs again. Said no? Press **Ctrl+Shift+B** in the Launcher to be asked again.

## Install

1. Download the newest `MVP05-Plus-Beta-….zip` from [Releases](../../releases) and unzip it anywhere. Everything stays in that folder: nothing goes into Program Files or the registry, and desktop shortcuts are only made if you ask.
2. Run `MVP05-Plus-Launcher.exe` and choose your discs:

   * **Xbox** (required): a Redump `.iso`, `.xiso`, or a folder of extracted files.
   * **GameCube** (optional, for GameCube art): `.iso`, `.gcm`, `.gcz` or `.ciso`, or `.rvz` with Dolphin (the Launcher finds it, or asks where it is).
   * **PS2** (optional, for PS2 art): `.iso`, or `.chd` with MAME's `chdman` (found or asked for the same way).
   * Already have a `gc_icons` or `ps2_icons` set? Choose its folder or `.zip` instead of the disc.

   Only the files the art needs are read from the GameCube and PS2 discs.

3. Press **Launch MVP 05**. From then on, the Launcher opens on what's installed, with Launch. To quit the game, press **Esc** (it asks first).

Windows may warn that the Launcher is from an unknown publisher: choose *More info → Run anyway*.

## Setting up controllers

* **GameCube adapter on Windows:** give it the WinUSB driver with [Zadig](https://zadig.akeo.ie/), as for Dolphin (select *WUP-028*, *WinUSB*, *Replace Driver*). Third-party adapters: set the switch to *Wii U*.
* **PlayStation and Xbox controllers:** connect by USB or Bluetooth as usual.

### SteamOS (Proton)

Add `MVP05.exe` to Steam as a non-Steam game, run with Proton.

For the GameCube adapter, turn off Steam's own GameCube adapter support, then set up the bridge once. In desktop mode, open a terminal in the game's folder and run:

```
chmod +x gcbridge && ./gcbridge --install
```

It then starts with the system and waits: it takes the adapter when the game starts and gives it back when the game closes, so Dolphin still works in between. `~/.local/share/gcbridge/gcbridge --uninstall` takes it out. After a new release, run the install line again.

Or, without installing anything, start it from the game's Steam launch options (with your folder's path):

```
sh -c 'B="/home/deck/Games/MVP05-Plus/gcbridge"; chmod +x "$B"; "$B" & exec "$@"' sh %command%
```

## Adding to Steam (optional)

1. In Steam: *Games → Add a Non-Steam Game to My Library*, and choose `MVP05.exe`.
2. Playing with a PlayStation or Switch controller? In the game's *Properties → Controller*, choose *Disable Steam Input*. Otherwise Steam passes it to the game as an Xbox controller, with the Xbox layout and buttons.
3. On SteamOS, also follow the Proton steps above.

## MVP05-Plus Launcher

* **Install**, which becomes **Play** once the game's installed (coming from an older MVP05-Plus or Mad Dog's MVP05? The Launcher offers to bring its game, saves and settings over the first time it opens; **Ctrl+Shift+B** offers it again): your discs in, then what's installed (checked each start), **Launch MVP 05**, and which controllers Windows sees right now, including whether the GameCube adapter has the WinUSB driver it needs. At the bottom, the **Player of the Day**: an MLB player from the game's 2005 rosters, with his picture and 2004 season, the same for everyone each day.
* **League News**: the button at the bottom right of *Play* opens League News for your newest dynasty or owner mode in your browser. For any other save, right-click it in *Saves*. Each edition is saved in `league news` beside `MVP05.exe`, one for each game day, with the back issues linked.
* **Saves**: *Your saves*, with *Import a save…* for saves from the PS2, GameCube, PC or another Xbox (or as a new save), and *Export…* to send one of yours there. An export is built on a save of yours from that console: a .psu or PCSX2 card, a .gci, Dolphin's card or GCI folder (found from Dolphin's own settings), a PC .sav, or a zip to share. Each save has a checkbox, to keep more than the game's 4 of a type and swap them in and out. Right-click a save to copy, rename or delete it. *Backups* are listed by date: restore single saves or a whole date. Your saves become a backup first, so a restore can be undone. Saves can also be dragged onto the tab.
* **Mods**: *Add a mod…* from a folder, files or a zip, or drag one in. Each mod has a checkbox to turn it on or off, and there's an option to double the game's memory.
* **Schedule**: the season schedule new seasons play; *Create a schedule…* (any even number of games from 12 to 162, interleague as in 2005, matchups you choose, a new matchup each year or none, natural rivals, the All-Star Game's host, a different season each dynasty year, previewed team by team before you save it); *Import a schedule…*; and *Export…*, to share one as a small zip.
* **Tools**: Dynasty adjustments (pitchers' rest, injury length, development, aging, retirement, contract prices, re-signing, rookies), the Payroll Budget (and an owner mode's bank balance, changed in the save), the Team Changer, Playoffs Editor and Standings Projector. They run in the running game, or on a saved dynasty or owner mode (Payroll Budget, Playoffs Editor, Standings Projector). In the game, F10 also has the Stamina Changer, Unlock everything, Add MVP points, holding your manager rating, and EA's debug menu.
* **Settings**: *Unlock everything* (every stadium, team, player, jersey and Legend), *Graphics…* (more detailed players away from the play), display mode, aspect ratio (16:9, or 4:3 with black bars at the sides), resolution (default: fullscreen at your desktop's resolution), render scale, frame rate cap, texture filtering, VSync, low latency, Xbox 720p mode; desktop shortcuts for the game ("MVP 05 Plus") and the Launcher, if you want them; and *Updates*: check for a new release, install it, or go back to the version before.

For the least delay between a button and the screen, as on a console: turn on *Low latency* in Settings (turn it back off if the game stutters), and use your monitor's G-Sync / FreeSync or your TV's game mode if it has one.

Everything is also in `mvp05-settings.toml`. Plus adds `gamecube_layout`, `gamecube_icons`, `playstation_layout`, `playstation_icons` (all on) and `save_backups` (30).

## Reporting a problem

Send `mvp05.log` (the game's) and, for a Launcher problem such as a save import or export, `MVP05-Plus-Launcher.log`. Both are beside `MVP05.exe`.

## Building from source

Windows x64 with Visual Studio's C++ tools and Windows SDK, LLVM Clang, CMake 3.25+ and Ninja. Put your Xbox files in `assets/` and run `Build-Source.cmd` from an *x64 Native Tools Command Prompt*. Details: [`docs/MVP05-HANDOFF.md`](docs/MVP05-HANDOFF.md); making a release: [`docs/RELEASING.md`](docs/RELEASING.md).

Button art by hand (Python 3 with `pip install pillow numpy`):

```
python tools/gc_layout/make_icons.py assets/data <GameCube disc's data folder> gc_icons
python tools/ps2_layout/make_ps2_icons.py assets/data <PS2 disc's DATA folder> ps2_icons
```

## Credits

* [**Mad Dog**](https://github.com/maddog847): the MVP Baseball 2005 PC port this is built on, and the MVP Roster Toolkit, whose roster conversion the save import uses.
* [**TGP482**](https://github.com/TGP482): [XboxXBERecomp](https://github.com/TGP482/XboxXBERecomp), the static recompiler for original Xbox games that the port is made with.
* **tywiggins**: the MVP 2005 Team Changer, Playoffs Creator and Stamina Changer (2006, for the PC game), ported here.
* **MVP05-Plus**: spy_jam, including the GameCube save conversion and League News.
* Third-party libraries: see `THIRD_PARTY.txt`.

## Special Thanks

* Special thanks to Mad Dog and Kccitystar for their help in the MVP community and consultation on this project.
* Also RIP to MVPmods.com and a shout out to all the community members that had done valuable work on there over the years.

## Legal

MIT licensed (`SDK-LICENSE.txt`); MVP05-Plus's additions are Copyright 2026 spy_jam under the same license. MVP Baseball 2005 and its art belong to EA; none of it is included. The game's icon is made from your own Xbox disc by the Launcher. Not affiliated with or endorsed by EA, Nintendo, Sony or Microsoft. Microsoft's runtime DLLs and shader compiler are Microsoft's redistributable components, under their own terms.
