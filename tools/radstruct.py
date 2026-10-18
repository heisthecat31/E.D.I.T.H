"""Generic reader for RAD serialized structs (EchoCombat cr_table layout) that also accepts the
flag word 4 (Christmas 2018 animsets / live skeletons use 4 where component tables use 1).

A struct's arrays sit inline as 0x38-byte headers (+00 byte size, +08 0, +10 u32 0, +14 u32 flag,
+18 alignment, +20 count, +28 capacity, +30 u64); after the root, each array's elements follow in
field order, each element's own arrays right after the array's data (depth first)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

FLAGS = (1, 4)


@dataclass
class Arr:
    at: int
    count: int
    esize: int
    align: int
    data_at: int = 0
    elems: list = field(default_factory=list)


@dataclass
class Node:
    at: int
    raw: bytes
    arrays: list = field(default_factory=list)


def q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def is_header(b, o, end):
    if o + 0x30 > end:
        return False
    sz, p, z, fl, al, c, cap = (q(b, o), q(b, o + 8), struct.unpack_from("<I", b, o + 0x10)[0],
                                struct.unpack_from("<I", b, o + 0x14)[0], q(b, o + 0x18), q(b, o + 0x20), q(b, o + 0x28))
    return (p == 0 and z == 0 and fl in FLAGS and al in (0, 8, 0x10, 0x20) and c == cap and sz < len(b)
            and (c == 0) == (sz == 0) and (c == 0 or sz % c == 0))


def headers(b, start, size):
    out, o = [], start
    while o + 0x30 <= start + size:
        if is_header(b, o, start + size):
            c = q(b, o + 0x20)
            out.append(Arr(o - start, c, q(b, o) // c if c else 0, q(b, o + 0x18)))
            o += 0x30
        else:
            o += 8
    return out


def parse(b: bytes, root_size: int, align_rule=None) -> tuple[Node, int]:
    """Walk; returns (root, end offset). align_rule(arr) -> byte alignment of its data."""
    def al(a):
        if align_rule:
            return align_rule(a)
        return 8 if a.esize % 16 == 0 else 4

    def walk(at, size, pos):
        node = Node(at, b[at:at + size])
        node.arrays = headers(b, at, size)
        for a in node.arrays:
            if not a.count:
                continue
            n = al(a)
            pos = (pos + n - 1) // n * n
            a.data_at = pos
            pos += a.count * a.esize
            for i in range(a.count):
                e, pos = walk(a.data_at + i * a.esize, a.esize, pos)
                a.elems.append(e)
        return node, pos

    return walk(0, root_size, root_size)


def dump(node: Node, depth=0, maxel=2):
    for k, a in enumerate(node.arrays):
        print("  " * depth + f"arr{k} @+{a.at:#x} count {a.count} esize {a.esize} align {a.align} data@{a.data_at:#x}")
        for e in a.elems[:maxel]:
            if e.arrays:
                dump(e, depth + 1, maxel)
