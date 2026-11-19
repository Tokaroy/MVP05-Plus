"""The Xbox app's tiles and splash screen, made from your own Xbox disc: default.xbe's title image (the MVP Baseball
2005 badge, as the Launcher makes mvp05.ico from it), on black. Package-Xbox.ps1 runs this into the package's Assets;
nothing of the game's is kept in the repository.

    python tools/xbox/make_tiles.py <default.xbe> <Assets folder>
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "installer"))
import title_icon  # noqa: E402

# file: (width, height, the badge's height as a share of the tile's)
TILES = {"Square150x150Logo.png": (150, 150, 0.9), "Square44x44Logo.png": (44, 44, 1.0),
         "StoreLogo.png": (50, 50, 1.0), "Wide310x150Logo.png": (310, 150, 0.9),
         "SplashScreen.png": (620, 300, 0.85)}


def make(xbe_path, out):
    from PIL import Image
    with open(xbe_path, "rb") as f:
        badge = title_icon.title_image(f.read())
    os.makedirs(out, exist_ok=True)
    for name, (w, h, share) in TILES.items():
        side = max(1, round(min(w, h) * share))
        im = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        b = badge.resize((side, side), Image.LANCZOS)
        im.alpha_composite(b, ((w - side) // 2, (h - side) // 2))
        im.save(os.path.join(out, name), optimize=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    try:
        make(sys.argv[1], sys.argv[2])
    except (OSError, title_icon.IconError) as e:
        sys.exit(f"No tiles from the disc: {e}")
    print("Tiles made from your disc's title image")
