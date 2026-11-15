"""Generated seasons: every length and interleague choice makes three checked seasons.
python tests/test_schedgen.py <tools/installer>"""
import os, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."))
import schedgen as G
import schedules as SC

n = 0
for games in (162, 141, 100, 64, 45, 31, 30, 15, 12):
    for mode in G.INTERLEAGUE:
        if mode != "off" and games < G.MIN_INTERLEAGUE:
            continue
        o = G.default_options()
        o.update(games=games, interleague=mode, all_star="alternate")
        if mode == "choose":
            o["pairing"] = {"AL East": "NL West", "AL Central": "NL East", "AL West": "NL Central"}
        for seed in (1,):
            ts = G.seasons(o, seed)
            assert SC.check_season(ts) == games, (games, mode)
            assert ts == G.seasons(o, seed), "the same choices and seed must give the same seasons"
            if mode != "off":  # every team plays some interleague
                for t in ts:
                    assert all(G.team_view(t, tm)[1]["interleague"] > 0 for tm in G.TEAMS), (games, mode)
            if games % 2 == 0:  # an even length: exactly half at home for every team
                for t in ts:
                    home = {}
                    for ln in t.decode().splitlines()[2:]:
                        f = ln.split(",")
                        if f[2] not in ("AL", "NL"):
                            home[f[2]] = home.get(f[2], 0) + 1
                    assert set(home.values()) == {games // 2}, (games, mode, sorted(set(home.values())))
            n += 1
o = G.default_options()
ts = G.seasons(o, 3)
assert [t.count(b",AL,NL,-,") for t in ts] == [1, 0, 1] and ts[1].count(b",NL,AL,-,") == 1  # the host takes turns
assert ts[0] != ts[1] != ts[2]
try:
    G.seasons(dict(G.default_options(), games=20), 1)
    raise AssertionError("20 games with interleague should be refused")
except G.GenError:
    pass
assert set(G.NAMES) == set(G.TEAMS)
print(f"schedgen tests passed ({n} season sets)")
