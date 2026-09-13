#!/usr/bin/env python3
#
#  Copyright (c) 2026, the edk2-msm8998 contributors. All rights reserved.
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#
"""Inspect a flattened device tree (.dtb) without needing dtc.

Prints the header, the /memory banks, the /reserved-memory carveouts with their
no-map/status flags, the board IDs used for QCDT matching, and the selected
primary panel. With --node it dumps every property of one node, which is what
you want when porting touch / panel / regulator definitions.

Everything is parsed straight from the big-endian FDT token stream, so there are
no dependencies.

Usage:
    python3 inspect-dtb.py Android-<device>.dtb
    python3 inspect-dtb.py Android-<device>.dtb --node /soc/i2c@c179000/synaptics@20
    python3 inspect-dtb.py Android-<device>.dtb --grep synaptics
"""

import argparse
import struct
import sys

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

INTERESTING = ("nokia", "fih", "msm8998", "synaptics", "goodix", "atmel", "touch",
               "panel", "dsi", "st,", "qcom,mdss", "battery")


def parse(path):
    with open(path, "rb") as handle:
        data = handle.read()

    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     lastcomp, bootcpu, size_strings, size_struct) = struct.unpack(">10I", data[:40])
    if magic != 0xD00DFEED:
        raise SystemExit("%s: not an FDT (magic %#x)" % (path, magic))

    print("== header ==")
    print("  file size    : %d (header totalsize=%d)" % (len(data), totalsize))
    print("  version      : %d (last compatible %d)" % (version, lastcomp))
    print("  struct block : @%#x +%#x" % (off_struct, size_struct))
    print("  strings      : @%#x +%#x" % (off_strings, size_strings))
    print("  rsvmap       : @%#x" % off_rsvmap)
    if totalsize != len(data):
        print("  NOTE         : file is %d bytes but header says %d"
              % (len(data), totalsize))

    strtab = data[off_strings:off_strings + size_strings]
    pos = off_struct
    stack = []
    props = {}
    node_count = 0
    while True:
        (token,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = data.index(b"\0", pos)
            stack.append(data[pos:end].decode("utf-8", "replace"))
            pos = (end + 4) & ~3
            node_count += 1
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            value = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
            end = strtab.index(b"\0", nameoff)
            node = "/" + "/".join(n for n in stack if n)
            props.setdefault(node, []).append((strtab[nameoff:end].decode(), value))
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            raise SystemExit("bad token %#x at %#x" % (token, pos - 4))
    return data, props, off_rsvmap, node_count


def cells(props, path):
    """Inherited #address-cells / #size-cells for a node."""
    parts = [p for p in path.split("/") if p]
    ac, sc = 2, 1
    for i in range(len(parts) + 1):
        for name, value in props.get("/" + "/".join(parts[:i]), []):
            if name == "#address-cells":
                ac = struct.unpack(">I", value[:4])[0]
            elif name == "#size-cells":
                sc = struct.unpack(">I", value[:4])[0]
    return ac, sc


def regs(props, path):
    """Decode a node's 'reg' property into (address, length) pairs."""
    out = []
    for name, value in props.get(path, []):
        if name != "reg":
            continue
        ac, sc = cells(props, path)
        words = list(struct.unpack(">%dI" % (len(value) // 4),
                                   value[:len(value) // 4 * 4]))
        step = ac + sc
        for i in range(0, len(words) - step + 1, step):
            addr = 0
            for word in words[i:i + ac]:
                addr = (addr << 32) | word
            length = 0
            for word in words[i + ac:i + step]:
                length = (length << 32) | word
            out.append((addr, length))
    return out


def text(value):
    return value.rstrip(b"\0").decode("utf-8", "replace")


def render(value):
    """Human-friendly rendering of a property value."""
    if not value:
        return "(boolean)"
    try:
        decoded = value.rstrip(b"\0").decode("utf-8")
        if decoded and all(31 < ord(c) < 127 for c in decoded):
            return '"%s"' % decoded
    except UnicodeDecodeError:
        pass
    if len(value) % 4 == 0:
        words = struct.unpack(">%dI" % (len(value) // 4), value)
        if len(words) <= 8:
            return " ".join("<%d>" % w for w in words)
    return "%d bytes: %s%s" % (len(value), value[:24].hex(),
                               "..." if len(value) > 24 else "")


def dump_node(props, path):
    print("\n== %s ==" % path)
    for name, value in props.get(path, []):
        print("  %-34s = %s" % (name, render(value)))


def main():
    parser = argparse.ArgumentParser(description="Inspect a .dtb without dtc.")
    parser.add_argument("dtb")
    parser.add_argument("--node", help="dump one node's properties")
    parser.add_argument("--grep", help="dump matching nodes/properties (case-insensitive)")
    parser.add_argument("--all-nodes", action="store_true",
                        help="list every node path")
    args = parser.parse_args()

    data, props, off_rsvmap, node_count = parse(args.dtb)

    if args.node:
        if args.node not in props:
            print("\nno such node: %s" % args.node)
            print("hint: --grep %s" % args.node.strip("/").split("/")[-1])
            return 1
        dump_node(props, args.node)
        return 0

    if args.grep:
        needle = args.grep.lower()
        print("\n== nodes/properties matching %r ==" % args.grep)
        for path in sorted(props):
            if needle in path.lower():
                for name, value in props[path]:
                    print("  %-46s %s = %s" % (path, name, render(value)))
            else:
                for name, value in props[path]:
                    if needle in name.lower() or needle in text(value).lower():
                        print("  %-46s %s = %s" % (path, name, render(value)))
        return 0

    if args.all_nodes:
        print("\n== all nodes (%d) ==" % len(props))
        for path in sorted(props):
            print("  %s" % path)
        return 0

    print("\n== root ==")
    for name, value in props.get("/", []):
        if name in ("model", "compatible"):
            print("  %-12s : %s" % (name, text(value)))
    print("  node count   : %d" % node_count)

    print("\n== /memory ==")
    for addr, length in regs(props, "/memory"):
        print("  0x%016X .. 0x%016X  (%d MiB)" % (addr, addr + length, length >> 20))

    print("\n== /reserved-memory ==")
    for path in sorted(props):
        if not path.startswith("/reserved-memory"):
            continue
        flags = []
        for name, value in props[path]:
            if name == "status":
                flags.append("status=" + text(value))
            elif name == "compatible":
                flags.append("compatible=" + text(value))
            elif name in ("no-map", "reusable", "shared-dma-pool"):
                flags.append(name)
        regions = regs(props, path)
        if regions:
            for addr, length in regions:
                print("  %-44s 0x%016X +0x%-9X %s"
                      % (path, addr, length, " ".join(flags)))
        elif flags:
            print("  %-44s %s" % (path, " ".join(flags)))

    print("\n== memory reservation block (pre-kernel reserves) ==")
    cursor = off_rsvmap
    empty = True
    while True:
        addr, length = struct.unpack_from(">QQ", data, cursor)
        if addr == 0 and length == 0:
            break
        print("  0x%016X +0x%X" % (addr, length))
        empty = False
        cursor += 16
    if empty:
        print("  (empty)")

    print("\n== board identification ==")
    for name, value in props.get("/", []):
        if name.startswith("qcom,") and name.endswith("id") and value:
            words = struct.unpack(">%dI" % (len(value) // 4),
                                  value[:len(value) // 4 * 4])
            print("  %-14s %s" % (name, " ".join("%d(%#x)" % (w, w) for w in words)))

    phandles = {}
    for path in props:
        for name, value in props[path]:
            if name in ("phandle", "linux,phandle"):
                phandles[struct.unpack(">I", value[:4])[0]] = path

    print("\n== primary panel selection ==")
    found = False
    for path in sorted(props):
        if not path.endswith("mdss_dsi_ctrl0@c994000"):
            continue
        for name, value in props[path]:
            if "prim-pan" in name:
                ph = struct.unpack(">I", value[:4])[0]
                target = phandles.get(ph, "<unresolved>")
                panel = ""
                for n2, v2 in props.get(target, []):
                    if n2 == "qcom,mdss-dsi-panel-name":
                        panel = text(v2)
                print("  %s = phandle %d -> %s" % (name, ph, target))
                print("      panel: %s" % panel)
                found = True
    if not found:
        print("  (no qcom,dsi-pref-prim-pan on mdss_dsi_ctrl0)")

    print("\n== notable properties ==")
    seen = set()
    for path in sorted(props):
        for name, value in props[path]:
            if name not in ("compatible", "status", "label",
                            "qcom,mdss-dsi-panel-name"):
                continue
            decoded = text(value)
            if any(key in decoded.lower() for key in INTERESTING):
                line = "  %-46s %s = %s" % (path, name, decoded.replace("\0", " | "))
                if line not in seen:
                    seen.add(line)
                    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
