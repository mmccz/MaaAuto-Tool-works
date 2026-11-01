"""BSDIFF40 patch applier (stdlib only, no third-party dependency).

Why hand-rolled: ``upgrade.exe`` currently depends only on the stdlib + psutil
(7.5 MB); adding a bsdiff binary dependency would bloat it and drag in
architecture/AV problems. Patch **generation** happens on the build machine with
``bsdiff4`` (affects CI/local packaging only), **applying** happens here with
``bz2``.

File format (Colin Percival bsdiff, commonly called BSDIFF40)::

    "BSDIFF40" | ctrl_len:int64 | diff_len:int64 | new_size:int64
    ctrl_block  = bz2( control triples:  (x, y, z) * n )
    diff_block  = bz2( byte-wise difference added to the x segment )
    extra_block = bz2( new bytes for the y segment )

    new = 0
    old = 0
    for each triple:
        new[new:new+x] = old[old:old+x] + diff[x segment]     # byte-wise add
        new[new+x:new+x+y] = extra[y segment]
        old += x + z;  new += x + y

int64 uses the high bit as the sign bit (see ``_offtin``), matching the original
bsdiff implementation.
"""

import bz2
from typing import Callable, Optional

MAGIC = b"BSDIFF40"


def _offtin(buf: bytes) -> int:
    """bsdiff 8-byte integer: little-endian magnitude plus the sign in the high bit."""
    if len(buf) != 8:
        raise ValueError("int64 长度必须为 8")
    y = buf[7] & 0x7F
    for i in range(6, -1, -1):
        y = y * 256 + buf[i]
    return -y if buf[7] & 0x80 else y


def _offtout(value: int) -> bytes:
    """Inverse of ``_offtin`` (for tests/self-checks)."""
    if value < 0:
        y = -value
        sign = 0x80
    else:
        y = value
        sign = 0
    out = bytearray(8)
    for i in range(8):
        out[i] = y & 0xFF
        y >>= 8
    out[7] |= sign
    return bytes(out)


def _read_exact(f, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise ValueError(f"补丁被截断：期望 {n} 字节，实际 {len(data)}")
    return data


def apply_patch(old: bytes, patch: bytes,
                progress: Optional[Callable[[int, int], None]] = None) -> bytes:
    """Apply ``patch`` to ``old`` and return the new content (raises ``ValueError`` when invalid)."""
    if len(patch) < 32 or patch[:8] != MAGIC:
        raise ValueError("不是 BSDIFF40 补丁")
    ctrl_len = _offtin(patch[8:16])
    diff_len = _offtin(patch[16:24])
    new_size = _offtin(patch[24:32])
    if ctrl_len < 0 or diff_len < 0 or new_size < 0:
        raise ValueError("补丁头损坏（长度为负）")

    pos = 32
    ctrl_end = pos + ctrl_len
    diff_end = ctrl_end + diff_len
    if diff_end > len(patch):
        raise ValueError("补丁长度与声明不符")

    ctrl = bz2.decompress(patch[pos:ctrl_end])
    diff = bz2.decompress(patch[ctrl_end:diff_end])
    extra = bz2.decompress(patch[diff_end:])

    out = bytearray(new_size)
    oldpos = 0
    newpos = 0
    cpos = dpos = epos = 0
    old_len = len(old)

    def _byte(i: int) -> int:
        return old[i] if 0 <= i < old_len else 0

    while newpos < new_size:
        if cpos + 24 > len(ctrl):
            raise ValueError("控制块提前结束")
        x = _offtin(ctrl[cpos:cpos + 8])
        y = _offtin(ctrl[cpos + 8:cpos + 16])
        z = _offtin(ctrl[cpos + 16:cpos + 24])
        cpos += 24
        if x < 0 or y < 0 or newpos + x + y > new_size:
            raise ValueError("控制块数值越界")

        for i in range(x):
            out[newpos + i] = (_byte(oldpos + i) + diff[dpos + i]) & 0xFF
        dpos += x
        oldpos += x
        newpos += x

        out[newpos:newpos + y] = extra[epos:epos + y]
        epos += y
        newpos += y

        oldpos += z
        if progress:
            progress(newpos, new_size)

    return bytes(out)


def apply_patch_file(old_path, patch_path, out_path,
                     progress: Optional[Callable[[int, int], None]] = None) -> int:
    """File variant: read the old file + patch, write the new file, return its byte count."""
    with open(patch_path, "rb") as f:
        patch = f.read()
    with open(old_path, "rb") as f:
        old = f.read()
    new = apply_patch(old, patch, progress=progress)
    with open(out_path, "wb") as f:
        f.write(new)
    return len(new)
