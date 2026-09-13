#!/usr/bin/env python3
#
#  Copyright (c) 2026, the edk2-msm8998 contributors. All rights reserved.
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#
"""Compare candidate DTBs against a reference at the property level.

This is the tool for picking the right device tree out of a stock boot image.
Board IDs are NOT enough on their own: several DTBs in one image routinely share
the same qcom,msm-id / qcom,board-id and differ only in RAM size, panel or touch
wiring. Diffing against the live device tree (/sys/firmware/fdt, pulled from
/booted device) shows which candidate is the real match.

Rule of thumb for the true match: the only differences should be runtime
properties - /chosen:bootargs, /chosen:kaslr-seed, /chosen:linux,initrd-* - plus
vendor boot-time values. Any difference in /memory:reg, /:model or
/reserved-memory means a different hardware variant.

phandle / linux,phandle values are node-order artefacts, so they are counted
separately and excluded from the meaningful tally.

Usage:
    python3 compare-dtb.py reference.dtb candidate.dtb
    python3 compare-dtb.py reference.dtb 'outdir/*-dtb*.dtb' -v
"""

import argparse
import glob
import struct
import sys

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def parse(path):
    with open(path, "rb") as handle:
        data = handle.read()
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     lastcomp, bootcpu, size_strings, size_struct) = struct.unpack(">10I", data[:40])
    if magic != 0xD00DFEED:
        raise SystemExit("%s: not an FDT" % path)

    strtab = data[off_strings:off_strings + size_strings]
    pos = off_struct
    stack = []
    props = {}
    while True:
        (token,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = data.index(b"\0", pos)
            stack.append(data[pos:end].decode("utf-8", "replace"))
            pos = (end + 4) & ~3
        elif token == FDT_END_NODE:
            stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            value = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
            end = strtab.index(b"\0", nameoff)
            node = "/" + "/".join(n for n in stack if n)
            props[node + ":" + strtab[nameoff:end].decode()] = value
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
    return data, props


def root_words(props, name):
    value = props.get("/:" + name)
    if not value:
        return None
    return struct.unpack(">%dI" % (len(value) // 4), value[:len(value) // 4 * 4])


def is_noise(key):
    return key.endswith(":phandle") or key.endswith(":linux,phandle")


def describe(path):
    _, props = parse(path)
    model = props.get("/:model", b"").rstrip(b"\0").decode("utf-8", "replace")
    return props, model, root_words(props, "qcom,msm-id"), root_words(props, "qcom,board-id")


def main():
    parser = argparse.ArgumentParser(description="Diff DTBs at property level.")
    parser.add_argument("reference", help="known-good DTB, e.g. the live /sys/firmware/fdt")
    parser.add_argument("candidates", help="a .dtb path or a glob pattern")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="list differing properties")
    parser.add_argument("--limit", type=int, default=8,
                        help="max differences listed per candidate (default 8)")
    args = parser.parse_args()

    ref_props, ref_model, ref_mid, ref_bid = describe(args.reference)
    print("reference : %s" % args.reference)
    print("  model   : %s" % ref_model)
    print("  msm-id  : %s" % (ref_mid,))
    print("  board-id: %s" % (ref_bid,))
    print("  props   : %d\n" % len(ref_props))

    matches = sorted(glob.glob(args.candidates)) or [args.candidates]
    best = None

    for path in matches:
        props, model, mid, bid = describe(path)
        keys_ref, keys_cand = set(ref_props), set(props)
        only_ref = keys_ref - keys_cand
        only_cand = keys_cand - keys_ref
        changed = [k for k in keys_ref & keys_cand if ref_props[k] != props[k]]
        meaningful = [k for k in changed if not is_noise(k)]

        status = ""
        if mid == ref_mid and bid == ref_bid:
            status = "msm-id+board-id match"
        elif mid == ref_mid:
            status = "msm-id only"

        print("%s" % path)
        print("  msm-id=%s board-id=%s  %s" % (mid, bid, status))
        print("  missing=%d extra=%d changed=%d (meaningful changed=%d)"
              % (len(only_ref), len(only_cand), len(changed), len(meaningful)))

        if meaningful:
            for key in meaningful[:args.limit]:
                print("    ~ %s" % key)
            if len(meaningful) > args.limit:
                print("    ... %d more" % (len(meaningful) - args.limit))
        else:
            print("    -> no meaningful property differences: same hardware variant")

        if args.verbose:
            for key in sorted(only_ref)[:args.limit]:
                print("    only in reference: %s" % key)
            for key in sorted(only_cand)[:args.limit]:
                print("    only in candidate: %s" % key)

        if best is None or len(meaningful) < best[1]:
            best = (path, len(meaningful), len(only_ref))

    if best and len(matches) > 1:
        print("\nclosest match: %s (meaningful diffs=%d, missing=%d)"
              % (best[0], best[1], best[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
