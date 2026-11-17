"""A created schedule exported as a zip and imported back (another Launcher's): the same seasons.
python tests/test_schedule_share.py <tools/installer>"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."))
import schedgen as G  # noqa: E402
import schedules as SC  # noqa: E402

mine, theirs = tempfile.mkdtemp(), tempfile.mkdtemp()
o = G.default_options()
o.update(games=64)
texts = G.seasons(o, 7)
e = SC.save_made(mine, texts, "My 64", o, 7, "64 games")
dest = os.path.join(mine, "My 64.zip")
assert SC.export_zip(e, dest) == 64
assert sorted(zipfile.ZipFile(dest).namelist()) == ["about.txt", *SC.SEASON_FILES]
back = SC.import_schedule(theirs, [dest], "Their 64")
for n, t in zip(SC.SEASON_FILES, texts):
    with open(os.path.join(back["folder"], n), "rb") as f:
        assert f.read() == t, n
try:  # the same one twice is refused
    SC.import_schedule(theirs, [dest], "Again")
    raise AssertionError("imported twice")
except SC.ScheduleError:
    pass
bad = os.path.join(mine, "not a schedule.zip")
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("readme.txt", "hello")
try:
    SC.import_schedule(theirs, [bad], "Nothing")
    raise AssertionError("a zip with no schedule was imported")
except SC.ScheduleError as err:
    assert "no schedule" in str(err)
try:
    SC.export_zip({"name": "162", "kind": "original", "folder": None}, dest)
    raise AssertionError("the disc's schedule was exported")
except SC.ScheduleError:
    pass
print("schedule sharing tests passed")
