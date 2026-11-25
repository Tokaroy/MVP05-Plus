"""A GameCube font (.gfn) in the Xbox's font format (.xfn).

Both are EA's font file: a header, the glyph table (12 bytes a glyph), the kerning pairs, then the picture of the
glyphs (EA's ERTS texture: a header, the 8-bit pixels, then a 256-colour palette). The GameCube's is big-endian, its
pixels in 8x4 tiles and its palette IA8 (alpha, grey); the Xbox's little-endian, its pixels swizzled (Morton order)
and its palette BGRA. The glyph table's x and y are pixels in the picture, so a GameCube picture that isn't a power
of two (au20b's is 512x196) goes in the top left of a 512x512 one, with the scale in the header 1/512 both ways.
"""
import struct

from .shp import unswizzle


def _u16(b, o): return struct.unpack_from('>H', b, o)[0]
def _u32(b, o): return struct.unpack_from('>I', b, o)[0]


def gc_font_to_xbox(gfn, xfn):
    """gfn: the GameCube font; xfn: the Xbox's own copy of the same font (its texture header, kerning and palette
    header are taken from it). Returns the GameCube font as an Xbox .xfn."""
    assert gfn[:4] == b'FntG' and xfn[:4] == b'FntX', (gfn[:4], xfn[:4])
    count = _u16(gfn, 0xa)
    assert count == struct.unpack_from('<H', xfn, 0xa)[0], 'not the same font'
    table, kern_at, tex_at = _u32(gfn, 0x14), _u32(gfn, 0x18), _u32(gfn, 0x30)
    assert (table, kern_at, tex_at) == struct.unpack_from('<III', xfn, 0x14)[:2] + (struct.unpack_from('<I', xfn, 0x30)[0],)
    kerns = _u32(gfn, kern_at)
    assert kerns == struct.unpack_from('<I', xfn, kern_at)[0], 'not the same kerning'

    # the GameCube's picture: its header (as the Xbox's, big-endian), 8-bit pixels in 8x4 tiles, then the palette
    w, h = _u32(gfn, tex_at + 0x18), _u32(gfn, tex_at + 0x1c)
    pix_at = tex_at + 0x30
    tiles = gfn[pix_at:pix_at + w * h]
    pal_at = pix_at + w * h + 0x40
    pal = gfn[pal_at:pal_at + 512]
    assert gfn[tex_at] == 0x19 and len(tiles) == w * h and len(pal) == 512, (hex(gfn[tex_at]), w, h)
    img = bytearray(w * h)
    i = 0
    for ty in range(0, h, 4):
        for tx in range(0, w, 8):
            for y in range(4):
                for x in range(8):
                    img[(ty + y) * w + tx + x] = tiles[i]
                    i += 1

    size = 512
    assert w <= size and h <= size
    full = bytearray(size * size)
    for y in range(h):
        full[y * size:y * size + w] = img[y * w:(y + 1) * w]
    idx = unswizzle(size, size)
    pixels = bytearray(size * size)
    for p in range(size * size):
        pixels[idx[p]] = full[p]

    # the Xbox's texture header, as its 512x512 copies have it (widescrn.big's): the pixel count and the size
    th = bytearray(xfn[tex_at - 0x10:tex_at + 0x30])
    old = struct.unpack_from('<I', xfn, tex_at + 0x18)[0]
    n = size * size
    struct.pack_into('<I', th, 0x10 + 0x04, (n & ~0xffff) | (struct.unpack_from('<I', th, 0x14)[0] & 0xffff))
    struct.pack_into('<I', th, 0x10 + 0x0c, n)
    struct.pack_into('<II', th, 0x10 + 0x18, size, size)
    th[0x10 + 0x23] = n >> 16
    struct.pack_into('<HH', th, 0x10 + 0x24, size, size)
    assert old in (256, 512)

    # the palette: the Xbox's palette header, then each IA8 entry as BGRA (grey, grey, grey, alpha)
    x_pal_at = tex_at + 0x30 + old * old
    ph = xfn[x_pal_at:x_pal_at + 0x40]
    colours = bytearray()
    for k in range(256):
        a, g = pal[2 * k], pal[2 * k + 1]
        colours += bytes((g, g, g, a))
    tail = xfn[x_pal_at + 0x40 + 1024:]

    # the header: the Xbox's, with the GameCube's values (sizes, the line's height, the scale of the picture)
    hdr = bytearray(xfn[:table])
    struct.pack_into('<H', hdr, 0x8, _u16(gfn, 0x8))
    struct.pack_into('<I', hdr, 0xc, _u32(gfn, 0xc))
    hdr[0x10:0x14] = gfn[0x10:0x14]
    struct.pack_into('<I', hdr, 0x24, _u32(gfn, 0x24))
    struct.pack_into('<ff', hdr, 0x40, 1.0 / size, 1.0 / size)

    glyphs = bytearray()
    for k in range(count):
        r = gfn[table + 12 * k:table + 12 * k + 12]
        glyphs += struct.pack('<H', _u16(r, 0)) + r[2:4] + struct.pack('<HH', _u16(r, 4), _u16(r, 6)) + r[8:12]
    kerning = xfn[kern_at:tex_at - 0x10]  # (the same pairs on both, as the asserts check)

    out = hdr + glyphs + kerning + th + pixels + ph + colours + tail
    struct.pack_into('<I', out, 0x4, len(out) - 1088)
    return bytes(out)
