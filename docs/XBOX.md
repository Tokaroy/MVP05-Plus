# MVP05-Plus on the Xbox (Dev Mode)

**Experimental: phase 1, getting the game to boot on the console.** The app runs MVP05-Plus's recompiled game as an
Xbox (UWP) app on an Xbox One or Series console in Dev Mode. It reads the game from your own MVP05-Plus folder; no game
files are in the app.

## What you need

* An Xbox in **Dev Mode** (a Microsoft developer account, and the Dev Mode Activation app on the console).
* A PC with Visual Studio's C++ tools, LLVM Clang, CMake and Ninja (as for `Build-Source.cmd`), plus in the Visual
  Studio Installer the **Universal Windows Platform development** workload with **C++ (v143) Universal Windows
  Platform tools**.
* Your extracted Xbox game in `assets` (as for the PC build).

## Build the app

From *x64 Native Tools Command Prompt for VS*, in the repository: `Build-Xbox.cmd`. It recompiles the game (as the PC
build does), builds the Xbox app and packs it in `out\xbox`:

* `MVP05-Plus-Xbox.appx`: the app
* `Microsoft.VCLibs.x64.14.00.appx`: the C++ runtime it needs
* `MVP05-Plus-Xbox.cer`: the certificate it's signed with

## Put your MVP05-Plus folder on a USB drive

1. Format the drive **NTFS** on the PC.
2. Give apps access to it: the drive's *Properties → Security → Advanced → Add → Select a principal*, type
   `ALL APPLICATION PACKAGES`, give it **Full control**, and apply it to everything on the drive. (Or, in a command
   prompt run as administrator: `icacls E:\ /grant "*S-1-15-2-1:(OI)(CI)F" /T /C`, with your drive's letter.)
   Dev Mode apps can only use a drive that allows them.
3. Unzip MVP05-Plus onto the drive and install the game from your discs with the Launcher, as on the PC. You can play
   it on the PC from the drive too: it's the same folder, saves and all.
4. On the Xbox, when you plug the drive in, choose to use it for **media** (not games and apps).

The app looks on every USB drive for a folder with `assets\default.xbe` in it (one named MVP05-Plus... first). Without
one, it uses its own storage: `LocalState\MVP05-Plus` (Device Portal's *File explorer* can upload a folder there).

## Install and run

1. Open Device Portal (the address Dev Home shows) in a browser on the PC.
2. *Add* → choose `MVP05-Plus-Xbox.appx` → add `Microsoft.VCLibs.x64.14.00.appx` as a dependency (and the `.cer`
   if it asks for a certificate) → install.
3. In Dev Home, select MVP05-Plus, *View details*, and set its type to **Game** (an app gets a fraction of the
   console's memory and GPU).
4. Start it from Dev Home.

## If it doesn't start

Send these (Device Portal's *File explorer*, the app's `LocalState`):

* `xbox-start.txt`: where it looked for the game and what it found.
* the game's log, `logs\mvp05.log` in your MVP05-Plus folder (on the USB drive, or in `LocalState`).

## Not yet

* A Launcher screen before the game (Saves, Mods, Settings, Launch), and the Launcher's work moved into the F10 menu.
* Save export and import with a USB drive, from the console.
* Output above 1080p.
