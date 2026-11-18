# MVP Baseball 2005 dynasty save: GameCube vs Xbox format notes

Notes behind `mvp_gc2xb.py` (GameCube `.gci` -> Xbox `data.dat`, mid-season dynasty saves). Written so a later
session can pick the work up without redoing the reverse engineering. Offsets are for a fresh Dodgers dynasty
(`MATCHED` GC save / its Xbox template) unless noted; sections after the rosters move with roster size.

Evidence used: the GameCube decomp (`mvp2005-decomp-main`, struct layouts and stream code), three fresh
GC/Xbox dynasty saves (Dodgers, Yankees, Red Sox), the KC dynasty at April 2007 (two copies) and at the start of
2008, and a native Xbox Houston dynasty in its 2006 season (the only Xbox save with game-generated history,
trades and injuries). In-game tests on the recomp: v3-v15 builds, v15/v16 confirmed working mid-season.

## 1. Containers

| | GameCube `.gci` | Xbox `data.dat` |
|---|---|---|
| payload offset / length | 0x2138 / 0x186C00 | 0x108 / 0x222C00 |
| byte order | big-endian | little-endian |
| bitfields | MSB-first | LSB-first, same field order |
| checks | file starts `GV4E`; s32 at file 0x2084 = sum of the signed bytes 0x40..0x2083 (comment/icon area, contains the dynasty name, so it changes on rename); EA CRCs at 0x2088 for header body and payload | header + payload signatures (`containers.build_xbox` / `verify_xbox`) |

The payload is one continuous stream. Seven `0xBEEFF00D` markers (each followed by a u32) split it:
0 and 1 in the header, 2 = schedules, 3/4 = user section, 5 = player history, 6 = stream end (its value is
rewritten when the stream length changes; the trailing `55 BB` filler absorbs the difference).

Conversion rule of thumb: a field converts by its declared type. u32 -> swap 4 bytes, u16 -> swap 2, u8 and
byte arrays -> copy, bitfields -> same field values re-packed LSB-first. Every bug found in testing was a
field converted with the wrong one of these (4-byte swap over bytes or u16 pairs, raw copy over u32 keys).

**Xbox save folders** (`hdd/E/UDATA/45410056/<12 hex>`): the folder's name is the Xbox library's hash of the
save's name as SaveMeta.xbx has it, "NAME (Type)" (default.xbe 0x3F36B5: for each UTF-16 character c,
h = (h * 65536 + c) mod (2^48 - 59); 12 upper-case hex digits). "KCRTEST (Dynasty)" -> 8D58821E7335. The roster
saves' Xbox header is laid out as the dynasties' (name at 0x68, type at 0x88, "name (type)" at 0xA8, the two
HMAC-SHA1s over 0x50..0x108 and 0x108..). MVP05-Plus `tools/saves/saves05.py` (`folder_id`, `renamed`, `new_save`).

## 2. Stream layout (GC offset / Xbox offset in the fresh pair)

| Section | GC | Xbox | Contents / conversion | Status |
|---|---|---|---|---|
| Settings header | 0x000-0x2D2 | 0x000-0x2CF | 72 ints (swap32); 2 flag bytes (GC has 3 pad bytes between); UTF-16 name buffer, 19 units (swap16); 2 ints; slider byte arrays (copy); 3 ints + marker 0 + value; 7 bytes (copy) | converted, exact on fresh pair |
| Org keylist | 0x2D2-0x47A | 0x2CF-0x477 | 34 x (key, idx, idx) | identical in every save, kept |
| Org records | 0x47A | 0x477 | 34 x 0x54 `Unk8052E9C4_Rec`: 14 ints, 16-bit bitfield group (1,5,3,1,2,3,1), 11 halfwords, last word (15,15,2) | converted (`structconv.ORG54`) |
| Team season records | 0xFA2 | 0xF9F | tag + 30 x 16 B `Unk8052F5CC_Rec` (7,7,7,7,4 / 7,7,7,7,4 / 7,7,7,11 / 11,21) + plain words + 1 byte-bitfield word + plain words | converted (that one word kept) |
| Team table | 0x1B42 | 0x1B3F | 126 x 60 B, 4 packed words | converted (`teamconv`, bit map learned on the fresh pair) |
| Roster blocks | 0x38CE- | 0x38CB- | 126 variable-length blocks, see 3.1 | converted |
| Post-roster tables | after rosters | | 3 per-team tables [tag][504 B]; keylist; 36 managers (48 B GC / 44 B Xbox) | converted, see 3.2 |
| Tagged tables | 25 tags `F58F3C1B` | | see 3.3 | converted |
| 1 KB block | tag 2 - 1056 | | zeros except: 80, 1, and one u32 that differs per dynasty and never changes during it (seed or creation stamp) | kept from template |
| 704 B block | before marker 2 | | identical in every save | kept |
| Schedules | marker 2 | | see 3.4 | converted |
| Trades / moves / injuries | after schedules (2870 B GC / 2798 B Xbox) | | see 3.5 | converted except 9 values |
| User section | marker 3, 4 | | m3 + u32 + 20 zero bytes; m4 + count (1) + **user team key** + UTF-16 profile name (swap16) | converted |
| Player history | marker 5 | | see 3.6 | converted |

## 3. Details

### 3.1 Roster block (per team, 126 teams: 30 MLB, 2 All-Star, minors, specials)
- 4 lineup units x 48 B: 10 bytes copy, u16, 9 x u32.
- 25 u32 player keys, u32 n, u32, then n u32 player keys.
- 5 "rings": [cap bytes of roster-slot indices][u32 count][u32 index]. The caps vary per team and are found by
  search; the block always ends in a 45-byte tail, which fixes the chain. All-Star teams 30/31 (fresh saves)
  and team 125 allow several chains, and all of them give byte-identical output.
- 45-byte tail: u8, 3 x u32, then 4 x (player key u32, return date u16 day number in a u32). This is the
  injured list. Copying it raw broke 21 players (they turned into free agents, with "D. Default" in their slots).

### 3.2 Per-team tables after the rosters (126 x 4 B each)
- Table 0: current record, bytes [W][L][0][0], same byte order on both platforms -> copy. (A 4-byte swap
  showed 10-0 as 0-10.) This is also the table the standings patcher edits in memory.
- Table 1: byte pairs -> copy.
- Table 2: last season's record as u16 W, u16 L -> swap16 each.

### 3.3 Tagged tables (tag `F58F3C1B` / Xbox `1B3C8FF5`, 25 of them)
- Tables 2-5: plain ints. Region 6-8: 404 B preamble + player keylist [n=3250][n][3250 x (key, row, row)];
  keys are sorted as signed ints.
- Table 8: 3250 player rows of 60 B (`Unk8008CE64_PackE`, `player_conv`). The row frame starts 23 bytes (GC) /
  24 bytes (Xbox) into the table and the last row wraps to the table start.
- Tables 9-15: per-player packs (PackF 16 B, 4 B words, `Unk80070004_Rec` 12 B), bit-permuted from the decomp
  structs (`bitconv`, `tablesconv.PM`).
- Region 16-18 (fixed 0x34288 B): Rec70004 table, 5 x 4 B word tables, 16 B `Unk80071170_Rec` table, an
  1800-entry stats keylist, PackD table (20 B).
- Tables 18-24: 1800 x 12 B season-stat packs (PackC/PackB/Pack). Player stats show correctly in game.

### 3.4 Schedules (marker 2) and the current date
- Four tables, MLB + three minor leagues, with fixed capacities 2442, 2172, 2140, 2112. Each is a u32 count
  followed by **all** capacity entries (the game streams the whole array, so the section size never changes;
  shortening it crashed the game).
- Entry 28 B: u16 day number (days since 1948-01-01, +1); 16-bit bitfield (10, 1, 5: the 5-bit field is
  non-zero once the game is played); 2 x side, the **home team first** (+4), the visitors second (+16):
  team key u32, runs u8, hits u8, then 4 + 6 four-bit inning
  scores and a u8. The inning nibbles swap within each byte (MSB-first vs LSB-first).
  On the Xbox (MVP05-Plus, League News): side byte +10 low nibble = errors, high nibble = inning 1; +11..+14 =
  innings 2-8 and then the **last inning played**, low nibble first; +15 = 0. The innings of an extra-inning game
  between the 9th and the last aren't kept by inning: they're the runs less all nine (checked: every one of 22
  extra-inning games is tied going into its last inning; the nine slots sum to the runs in 994 of 1024 sides, the
  30 others all extra-inning). Home first: a home team ahead after the top of the 9th has an empty 9th
  slot in 270 of 270 games (read the other way round, 204 of 283), and in the playoffs the higher seed hosts
  games 1, 2 and 5 (as playoffs05's notes, from tywiggins, have it).
  No pitchers of record are kept per game: only the season totals (tables 18-24).
- **The game has no stored "current date".** It uses the first unplayed game across the four tables. Converting
  only the MLB table left the minors at 2005, so the game showed April 7, 2005 and crashed on game start.

- In the postseason the schedule holds only the playoff games (41 at most: four Division Series of 5, two LCS of 7,
  the World Series once the LCS are done), the earlier rounds' results kept. A game a series didn't need has both
  teams 0 and is marked played (KCR, after the Division Series). The standings (3.2 table 0) are then the playoffs'
  records.

### 3.5 After the schedules (2870 B GC / 2798 B Xbox)
- 0: u32 trade count, u32 roster-move count, u32 0.
- 12: 30 x 42 B trades: 2 x (3 player keys, u8 count + 3 pad bytes, team key) + u16 date.
- 1272: 60 x 10 B roster moves: player key, team key, u16 date.
- 1872: u32 count + 32 x 20 B injuries: player key, u32, u32, packed word (1,1,6,6,6,6,6), u16 date, u16 date.
- 2516: object records whose sizes differ per platform (GC entries hold GC pointers 0x8068xxxx), kept from
  the template, ending in 9 x u16 (GC +2840, Xbox +2777). Those 9 are zero in fresh dynasties and filled after a
  season (KC: 38,66,26,99,22,8,93,11,24; Houston 2006: 40,156,60,220,48,16,205,17,44). Meaning unknown; kept as
  the template's zeros at the user's request.

### 3.6 Player history (marker 5)
- Groups: player key u32, u8 n, n x 20 B rows. GC keeps the last 6 rows per player, Xbox up to 16.
- Row (`Unk80082248_Rec`): link u32 (zeroed by the loader), u16 year, u8 team, byte bitfield (2,2,3,1), then
  3 packed words. The packing is not in the decomp; it was read off game-generated rows by bit frequency on both
  platforms, and matches all 5757 shared rows in the fresh pair exactly:
  - batter: (10,8,7,7) (9,8,8,7) (9,8,8,7)
  - pitcher: (8,8,9,7) (9,2,6,6,9) (7,25). The last 25 bits look like filler on both platforms.
  - What they hold (MVP05-Plus League News, checked against the game's League Leaders screen on the KCR dynasty;
    the row of the current year is the season so far; flags & 3: 1 batter, 2 pitcher):
    batter (AB, G, SB, CS) (H, RBI, R, HR) (TB, SO, BB with HBP, SF); pitcher (ER, BB, SO, G) (IP, thirds, W, L, -)
    (SV, -). The batters' word 2 is zero in the real seasons before 2005. This season's big-league totals of H, R,
    HR, TB, SO, BB+HBP and SF equal the pitching tables' exactly (KCR, 421 games).
  - Tables 18-24 hold pitching too (21: this season, G / IP / thirds / W / L / - / R / ER / SV ...; 22-23 its
    splits, BB / - / SO / ... / 1B / 2B / 3B / HR / ... / BF; 18-20 last season; 24 career): this season's runs
    and hits allowed equal the schedule's exactly.
- The converter puts the GC rows after the template's rows that come before them, found by overlap: the longest run
  at the end of the template's list that the GC rows begin with (`postconv.hist_merge`). A list isn't always in year
  order, and a traded player has two rows for one year, which the earlier by-year rule could drop. Only when the two
  lists share no row does it fall back to that rule (template rows older than the oldest GC year; pre-2005 real
  history is the same in every dynasty). Template-only groups are appended. This can change a converted save's
  history bytes, so tests/test_vectors.json's t1 hash may need regenerating from a save checked in the game.

### 3.7 Team / budget / user identification
- User team: the key in the marker-4 section (only place that differs between fresh saves of different teams).
- Budget: org record halfword s21, in $100K units (KC 877 = $87.7M). CPU teams change by fixed or small steps,
  the user team by performance. Using the template's 2005 budget against a 2007 payroll showed -$20M.
- Org bitfield f15 (5 bits) is set only on the user org (KC: 2 in April 2007, 3 at the start of 2008; Houston 1
  in 2006); probably contract year. Halfwords s27/s28 are set only on the user org (KC 52/276, Houston 1/160;
  0 at the start of 2008), meaning unknown. All of these are converted as plain fields.

### 3.8 Owner mode (MVP05-Plus, from spy_jam's matched Yankees saves from all four consoles, 2026-11-17)
An owner mode body is a dynasty body 0x13800 bytes longer (Xbox payload and PC body 0x236400, PS2 and GameCube
0x19A400). Its stream has 9 markers: 0 to 3 as a dynasty's, then 4 the owner's finances (0x132C9 bytes on the Xbox),
5 the owner (0x140: his name in UTF-16, six records of u16s, the team key), then the dynasty's user section,
history and stream end. The managers' list has one slot fewer in use than its slots (the owner has no manager); the
tables are by slots (`_slots` in gc2xb_v0 / xb2gc, and the dynasty readers in MVP05-Plus). The two owner sections
are the same on every console but for: 4 bytes of padding on the PC and PS2 at 0x12B90, 15 bytes on the PS2 and
GameCube before a u32 at Xbox 0x1321F, 3 before the float at Xbox 0x132C4, a final flag kept in 1 byte (Xbox, PC) or
4 (PS2, GameCube), 82 more true/false fields kept the same ways (the last field of the 16-byte records from Xbox
0x12CD0), and in section 5, 2 bytes of GameCube padding at 0x2E and 6 (PS2) or 4 (GameCube) before the team key.
GameCube byte order: 4-byte values throughout section 4 (a byte or a u16 followed by padding stays one), u16s in
section 5. The owner's bank balance is the float at section 4 + 0x12B80 (the game's owner object +0x12B7C: the
section is that object from its +0 on, 4 bytes in); $2,000,000 in a new owner mode. MVP05-Plus `tools/saves/owner05.py`
converts it: the dynasty part as a dynasty, the two owner sections by those maps. Checked by round trips (PC exact;
PS2 and GameCube exact up to the history, whose link words are written as zero). The long table at the start of
section 4 is empty in a new owner mode, so its GameCube byte order is assumed (4-byte values). The Xbox game's
serializer for the owner object (0x451440, thiscall: stream, writer) writes section 4's first 0x12B90 bytes as
blobs in this order: +4 0x340, +0x344 0x100, +0x444 0x340, +0x784 0x100, +0x884 0xFC00, +0x109C4 0x2100, +0x10484
0x540 (these two swapped), +0x12AC4 0xB0, then seven u32 from +0x12B74 (+0x12B7C the bank balance), then the rest
from +0x12B90 elsewhere. The long table at +0x884 is 12-byte records read as (float, u32, int32) at 0x4515D0, and
+0x10484 and +0x12AC4 are 16-byte records starting with an int32 (0x451570): 4-byte values, as assumed. A new
owner mode sets +0x12B7C and +0x12B80 to the float 2,000,000.0 (0x46A6AA, from 0x5B1D84): the bank balance and,
beside it, most likely the starting one; income is added to +0x12B7C as a float (0x450755).

### 3.9 Memory card images (MVP05-Plus)
- **PCSX2 (.ps2, `tools/saves/ps2card.py`):** 512-byte pages, each followed by 16 error-correcting bytes in a full
  8 MB image (8,650,752 bytes): 3 per 128 bytes of the page (a column parity, starting 0x77, and two line parities,
  starting 0x7F; the Hamming code of mymc's ps2mc_ecc) and 4 zeros. Erased pages are all 0xFF, their code too.
  Checked on spy_jam's card: every written page's code matches. An export replaces the chosen save's file in a copy
  of the card, in its own clusters (the same length), and writes those pages' codes again.
- **Dolphin GameCube (.raw, `tools/saves/gccard.py`):** 8 KB blocks; the header's megabits at 0x22 (times 0x20000 is
  the image's length); blocks 1 and 2 the directory and its backup, 3 and 4 the block table and its backup (the
  higher update counter, at 0x1FFA and at 4, is the one in use); 127 directory entries of 64 bytes (first block at
  0x36, block count at 0x38); the table's map from 0xA gives the next block for each block from 5 (0xFFFF last). A
  .gci is the entry followed by the file's blocks. File blocks carry no card checksum, so an export writes the new
  .gci's blocks over the old save's in a copy of the card and leaves the directory and table alone. Checked on
  made-up cards only.

### 3.10 What League News reads (MVP05-Plus `tools/saves/news05.py`)
- **Player records** (tagged table 8: 3250 x 60 B from 24 bytes in, the last wrapping; found by the key list's row):
  first name at 8 (12 B), last name at 20 (16 B), latin-1. Field 0x1E is the injury's kind, 0x1F its days left
  (`packe_decomp_layout`; the fields the in-game injury hook reads).
- **Injury names:** default.xbe 0x1E03A0 maps kind 0..49 to a text id: 0 none, 1..22 = 19700..19721, 23 = 23753
  ("a bruised ankle"), 24..48 = 19722..19746, 49 = 17990 ("suspension").
- **feeng.loc** (assets/data): LOCH (20 B), LOCI (u32 count at 8, then (id u16, index u16) pairs from 16), LOCL (u32
  count at 12, then u32 offsets from the section's start; UTF-16 strings ending in 00 00).
- **logos.big** (assets/data/frontend): l000..l125.xsh, a team each in the team table's order (l007 Kansas City),
  SHPX with 7 pictures (l, j wordmarks; i 64x64 and a 128x128 logos; g cap; e, d stripes), kind 0x61 = DXT3.
- **Roster blocks:** 30 big-league clubs first, in the franchises' order; their 25 player keys after the 4 lineup
  units.
- **Standings table 0:** [W][L] before the All-Star break, [W][L] after (0-0 until then); the record is the sum.
- **The news list** (32 x 20 B after the moves): the game's own League News events, kind in bits 2..7 of the word
  (2..13 seen: 13 weekly, a batter and a pitcher: player of the week). Not read yet.

### 3.11 The four save slots of each kind (Xbox default.xbe, MVP05-Plus)
The game shows at most four saves of a kind (four dynasties, four owner modes ...). The four is built into the save
screen, not only checked:
- The save screen is one object, made once (constructor 0x28E080, called at 0x1EAA39). It holds four pointers to
  slot objects at +0x0C..+0x18 and the chosen slot's index at +0x1C. About 20 reads index them as
  `[obj + 0x0C + i*4]` (0x28D4F8, 0x28E474, 0x28F307 ...).
- The slots are filled by a job that is given the array and the count: `push 4; lea 0xC(esi)` at 0x28EF6B and
  0x28F036 (into 0x28D090 and 0x28BF30, which stores them at job+0x2C / +0x30).
- Before a save, 0x28EC40 walks the four slots (`mov [ebp-0x10], 4` at 0x28EC60). A slot object has an in-use
  byte at +4 and its name (UTF-16) at +0xC0. When all four are in use and the screen is saving (+0x58 == 1), it sets
  the "no slots" byte at +0x4E (`cmp dword [ebp-8], 4` at 0x28ED42).
- 0x28E7F0 turns that byte into error 8 (9 for type 0x200000); 0x28C0A0's jump table (0x28C218) sends 8 to
  0x28C0E3, which shows text 0x691 or 0x685: "No available %5 save slots remaining ..." (feeng.loc id 1681).
Raising the cap means a bigger slot array somewhere else (the object's fields run on from +0x1C, so it can't grow
in place), every indexed read and both counts changed to match, and a save screen list that scrolls past four; only
changing the compare at 0x28ED42 would let the game try to save with no free slot.

## 4. Converter files (`lib/`)
`gc2xb_v0.py` (driver: replacement list applied back to front), `tablesconv.py` (tagged tables, header,
org/team-season records), `postconv.py` (schedules, user section, after-schedules section, history merge),
`histrow.py` (history row layout), `rosterblock.py`, `teamconv.py` + `team_bitmap.json`, `mgrconv.py` /
`manager_conv.py`, `player_conv.py` / `packe_decomp_layout.py`, `bitconv.py` / `fitstruct.py` +
`packstructs.json` / `allbitstructs.json`, `structconv.py`, `sched_conv.py`, `containers.py` /
`gc_checksums.py`. `hist_conv.py` is used only to parse history groups. Its learned bit map (`hist_maps.json`)
is superseded by `histrow.py`.

## 5. Xbox -> GameCube (`mvp_xb2gc.py`, `lib/xb2gc.py`)
Every section is converted with the inverse of the GC->Xbox rule. A GC dynasty `.gci` is the template for
the kept pieces (GC pad bytes, the per-dynasty word, the object block in 3.5) and for the memory card header.
History keeps the last 6 rows per player, as GameCube does. The stream-end marker value is its own offset + 4,
and the filler after it is `BB` at even and `55` at odd payload offsets. Checksums [0]/[1] are recomputed
(`gc_checksums`). Checks:
- Round trip GC -> Xbox -> GC on the three KC saves: identical up to the history section, except the
  template-kept pieces.
- History differs because GC->Xbox fills in older real-life seasons from the Xbox template. The GameCube save
  had already dropped them; KC had dropped them for 828 players.
- The fresh Xbox template, the native Houston 2006 dynasty and a converted save all built valid .gci files,
  and the GC->Xbox converter reads each one back.
- In-game test in Dolphin: works. The KC round trip, the Astros (native Xbox, 2006) dynasty and a renamed fresh save all load.
  Renaming needs the s32 at 0x2084 recomputed: without it the game says the file is corrupt.

## 6. Open items
- The 9 values in 3.5, s27/s28 and f15 in 3.7, and the per-dynasty word in the 1 KB block are unidentified.
- Only mid-season saves are tested. The game does not save in the offseason; playoff saves are untested.
- The team table map (`teamconv`) is learned, not from a struct: bits that were constant in the fresh pair
  are written as 0. No visible problem so far.
