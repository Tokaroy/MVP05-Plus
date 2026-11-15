import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mods as M  # noqa: E402


def put(root, rel, data=b"x"):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


class ModsTest(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.root = self.t.name
        for rel in ("assets/default.xbe", "assets/PUT-GAME-FILES-HERE.txt", "assets/data/stadium/fenwday.big",
                    "assets/data/stadium/lighting.csv", "assets/data/database/resign.csv",
                    "assets/data/fe/common.big", "assets/data/ingame/common.big"):
            put(self.root, rel)
        self.a = M.Assets(self.root)

    def tearDown(self):
        self.t.cleanup()

    def test_match(self):
        m = self.a.match
        self.assertEqual(m("data/stadium/fenwday.big"), ("path", ["data/stadium/fenwday.big"]))
        self.assertEqual(m("Cool Mod v2/Data/Stadium/FENWDAY.big"), ("path", ["data/stadium/fenwday.big"]))
        self.assertEqual(m("fenwday.big"), ("name", ["data/stadium/fenwday.big"]))
        self.assertEqual(m("stuff/lighting.csv"), ("name", ["data/stadium/lighting.csv"]))
        self.assertEqual(m("common.big"), ("pick", ["data/fe/common.big", "data/ingame/common.big"]))
        self.assertEqual(m("mod/data/fe/common.big"), ("path", ["data/fe/common.big"]))
        self.assertEqual(m("stadium/fenwday.big"), ("path", ["data/stadium/fenwday.big"]))
        self.assertEqual(m("x/fe/common.big"), ("path", ["data/fe/common.big"]))
        self.assertEqual(m("readme.txt"), ("unknown", []))
        self.assertEqual(m("default.xbe"), ("unknown", []))
        self.assertEqual(m("pack/data/stadium/newpark.big"), ("new", ["data/stadium/newpark.big"]))

    def test_zip_import_and_list(self):
        z = os.path.join(self.root, "Fenway Pack.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Fenway Pack/data/stadium/fenwday.big", b"day")
            zf.writestr("Fenway Pack/lighting.csv", b"light")
            zf.writestr("Fenway Pack/common.big", b"c")
            zf.writestr("Fenway Pack/readme.txt", b"hi")
            zf.writestr("__MACOSX/._fenwday.big", b"junk")
        src = M.from_zip(z)
        planned = M.plan(self.a, src)
        self.assertEqual(len(planned), 4)
        name, n = M.install(self.root, src, planned, {"Fenway Pack/common.big": ["data/ingame/common.big"]})
        src.close()
        self.assertEqual((name, n), ("Fenway Pack", 3))
        self.assertEqual(M.mod_files(self.root, name),
                         ["data/ingame/common.big", "data/stadium/fenwday.big", "data/stadium/lighting.csv"])
        self.assertEqual(M.read_list(self.root), [("Fenway Pack", True)])
        # a second mod with the same file: a clash, the first wins
        f = put(self.root, "in/fenwday.big", b"other")
        src = M.from_files([f])
        name2, _ = M.install(self.root, src, M.plan(self.a, src), {})
        self.assertEqual(name2, "fenwday")
        self.assertEqual(M.read_list(self.root), [("Fenway Pack", True), ("fenwday", True)])
        c = M.clashes(self.root, M.read_list(self.root))
        self.assertEqual(c, {"Fenway Pack": [("fenwday", 1, True)], "fenwday": [("Fenway Pack", 1, False)]})
        M.write_list(self.root, [("fenwday", True), ("Fenway Pack", False)])
        self.assertEqual(M.clashes(self.root, M.read_list(self.root)), {})
        with open(os.path.join(self.root, "mods", "mods.txt")) as fh:
            self.assertIn("on fenwday\noff Fenway Pack\n", fh.read())
        # same name again gets a number; nothing to copy makes no mod
        src = M.from_files([f])
        self.assertEqual(M.install(self.root, src, M.plan(self.a, src), {})[0], "fenwday (2)")
        r = put(self.root, "in/readme.txt")
        src = M.from_files([r])
        self.assertEqual(M.install(self.root, src, M.plan(self.a, src), {}), (None, 0))
        M.remove(self.root, "fenwday")
        self.assertEqual([n for n, _ in M.read_list(self.root)], ["Fenway Pack", "fenwday (2)"])

    def test_folder_and_unlisted(self):
        put(self.root, "pack/Data/Database/resign.csv", b"r")
        src = M.from_folder(os.path.join(self.root, "pack"))
        name, n = M.install(self.root, src, M.plan(self.a, src), {})
        self.assertEqual((name, n), ("pack", 1))
        os.makedirs(os.path.join(self.root, "mods", "Hand made"))
        self.assertEqual(M.read_list(self.root), [("pack", True), ("Hand made", False)])


if __name__ == "__main__":
    unittest.main()
