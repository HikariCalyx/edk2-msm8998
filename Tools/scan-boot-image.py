#!/usr/bin/env python3
#
#  Copyright (c) 2026, the edk2-msm8998 contributors. All rights reserved.
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#
"""Find and extract device tree blobs (FDT) from an Android boot image.

Accepts a stock boot.img or a raw `boot_a` / `boot` partition dump.

It deliberately does not depend on trusting the Android boot header, nor on a
QCDT table being present: it scans for the FDT magic (0xd00dfeed) and carves
each blob using that blob's own big-endian totalsize field. That works for
appended-DTB kernels, for QCDT tables, and for images repacked by third-party
tools that leave the header inconsistent.

The Android boot header itself is little-endian - mkbootimg.py writes the
os_version field with pack('I', ...) - so the header is parsed as '<' and its
sizes are validated against the file length before being believed.

Usage:
    python3 scan-boot-image.py boot.img            # list what is inside
    python3 scan-boot-image.py boot.img -o outdir  # also write the DTBs out
"""

import argparse
import os
import struct
import sys

FDT_MAGIC_BYTES = struct.pack(">I", 0xD00DFEED)
QCDT_MAGIC_BYTES = b"QCDT"
# Qualcomm dt_table_header (newer format than QCDT); fields are little-endian.
DT_TABLE_MAGIC_BYTES = struct.pack("<I", 0xD7B7AB1E)
BOOT_MAGIC = b"ANDROID!"


def round_up(value, page):
    return ((value + page - 1) // page) * page


def parse_boot_header(data):
    """Parse an Android boot image header as little-endian. Returns a dict or None."""
    if data[:8] != BOOT_MAGIC:
        print("no ANDROID! magic; treating the file as a raw partition dump")
        return None

    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size,
     second_addr, tags_addr, page_size, header_version,
     os_version) = struct.unpack_from("<10I", data, 8)

    ver = os_version >> 11
    patch = os_version & 0x7FF

    print("== android boot header (little-endian) ==")
    print("  page size      : %d" % page_size)
    print("  header version : %d" % header_version)
    print("  os version     : %d.%d.%d, patch %d-%02d"
          % ((ver >> 14) & 0x7F, (ver >> 7) & 0x7F, ver & 0x7F,
             2000 + (patch >> 4), patch & 0xF))
    print("  kernel         : %d bytes @ 0x%x" % (kernel_size, kernel_addr))
    print("  ramdisk        : %d bytes @ 0x%x" % (ramdisk_size, ramdisk_addr))
    print("  second         : %d bytes" % second_size)

    info = {"page_size": page_size, "header_version": header_version}

    if page_size and 0 < kernel_size < len(data) and 0 < ramdisk_size < len(data):
        predicted = (page_size
                     + round_up(kernel_size, page_size)
                     + round_up(ramdisk_size, page_size)
                     + round_up(second_size, page_size))
        print("  size check     : header predicts %d, file is %d (%+d)"
              % (predicted, len(data), len(data) - predicted))
    else:
        print("  size check     : sizes implausible - header may have been repacked;")
        print("                   relying on the FDT scan below")

    if header_version >= 1:
        dtbo_size, dtbo_offset, hdr_size = struct.unpack_from("<3I", data, 1632)
        print("  recovery_dtbo  : %d bytes @ %d" % (dtbo_size, dtbo_offset))
        info["recovery_dtbo_size"] = dtbo_size
    if header_version >= 2:
        dtb_size, dtb_addr = struct.unpack_from("<2I", data, 1648)
        print("  dtb (v2)       : %d bytes @ 0x%x" % (dtb_size, dtb_addr))
        info["dtb_size"] = dtb_size
    return info


def find_fdts(data):
    """Return (offset, totalsize, version) for every plausible FDT in the blob."""
    found = []
    pos = 0
    while True:
        pos = data.find(FDT_MAGIC_BYTES, pos)
        if pos < 0:
            return found
        if pos + 40 <= len(data):
            magic, totalsize, off_struct, off_strings, off_rsvmap, version, \
                lastcomp = struct.unpack_from(">7I", data, pos)
            # last_comp_version is the OLDEST version that can read this blob,
            # so it must not be newer than the version actually used.
            if totalsize >= 40 and pos + totalsize <= len(data) and lastcomp <= version:
                found.append((pos, totalsize, version))
        pos += 4


def find_qcdt(data):
    """Return the offsets of any QCDT tables."""
    hits = []
    pos = 0
    while True:
        pos = data.find(QCDT_MAGIC_BYTES, pos)
        if pos < 0:
            return hits
        hits.append(pos)
        pos += 4


def find_dt_tables(data):
    """Parse Qualcomm dt_table headers.

    This is the newer format: a header of little-endian u32s followed by
    dt_entry records, each carrying (platform_id, variant_id, soc_rev, offset,
    size, id). It is how stock images pack dozens of per-variant DTBs into one
    boot image, and it is not the same thing as the older QCDT magic.
    """
    tables = []
    pos = 0
    while True:
        pos = data.find(DT_TABLE_MAGIC_BYTES, pos)
        if pos < 0:
            return tables
        if pos + 32 <= len(data):
            (magic, total_size, header_size, entry_size,
             entry_count, entries_offset, page_size, version) = struct.unpack_from("<8I", data, pos)
            plausible = (32 <= header_size <= 4096
                         and 12 <= entry_size <= 64
                         and 0 < entry_count < 8192
                         and entries_offset + entry_count * entry_size <= len(data))
            if plausible:
                tables.append({
                    "offset": pos, "total_size": total_size, "header_size": header_size,
                    "entry_size": entry_size, "entry_count": entry_count,
                    "entries_offset": entries_offset, "page_size": page_size,
                    "version": version, "data": data,
                })
        pos += 4


def dt_table_entries(table):
    """Yield decoded dt_entry records for a parsed dt_table."""
    data = table["data"]
    for i in range(table["entry_count"]):
        off = table["entries_offset"] + i * table["entry_size"]
        platform_id, variant_id, soc_rev, dtb_offset, dtb_size, dtb_id = struct.unpack_from("<6I", data, off)
        yield platform_id, variant_id, soc_rev, dtb_offset, dtb_size, dtb_id


def context_hint(data, offset):
    """Best-effort readable hint about which tree this is (root model, etc.)."""
    blob = data[offset:offset + 6144]
    for probe in (b"FIH", b"NOKIA", b"Nokia", b"qcom,", b"Qualcomm"):
        idx = blob.find(probe)
        if idx >= 0:
            end = blob.find(b"\0", idx)
            return blob[idx:min(end, idx + 96)].decode("utf-8", "replace")
    return "?"


def main():
    parser = argparse.ArgumentParser(
        description="Find and extract DTBs from an Android boot image.")
    parser.add_argument("image", help="boot.img or raw partition dump")
    parser.add_argument("-o", "--outdir",
                        help="write each extracted DTB into this directory")
    args = parser.parse_args()

    with open(args.image, "rb") as handle:
        data = handle.read()

    print("file: %s (%d bytes / %.1f MiB)\n"
          % (args.image, len(data), len(data) / 1048576.0))
    parse_boot_header(data)

    qcdt = find_qcdt(data)
    print("\n== QCDT tables (legacy magic) ==")
    print("  none" if not qcdt else "  %d found, first @%#x"
          % (len(qcdt), qcdt[0]))

    tables = find_dt_tables(data)
    print("\n== Qualcomm dt_table headers ==")
    if not tables:
        print("  none - image carries bare appended DTB(s) instead")
    for table in tables:
        print("  @%#010x total_size=%d header_size=%d entry_size=%d entries=%d "
              "entries_offset=%d page_size=%d version=%d"
              % (table["offset"], table["total_size"], table["header_size"],
                 table["entry_size"], table["entry_count"], table["entries_offset"],
                 table["page_size"], table["version"]))
        valid = 0
        for entry in dt_table_entries(table):
            platform_id, variant_id, soc_rev, dtb_offset, dtb_size, dtb_id = entry
            ok = (dtb_offset + dtb_size <= len(data)
                  and data[dtb_offset:dtb_offset + 4] == FDT_MAGIC_BYTES)
            valid += 1 if ok else 0
            print("    platform_id=%-5d variant_id=%-4d soc_rev=%#-9x offset=%#-10x "
                  "size=%-7d id=%d %s"
                  % (platform_id, variant_id, soc_rev, dtb_offset, dtb_size, dtb_id,
                     "" if ok else "<-- not a valid FDT"))
        print("    %d/%d entries point at valid FDTs" % (valid, table["entry_count"]))

    fdts = find_fdts(data)
    print("\n== FDT blobs ==")
    if not fdts:
        print("  none found")
        return 0
    print("  %d found" % len(fdts))

    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)

    base = os.path.splitext(os.path.basename(args.image))[0]
    written = []
    for index, (offset, size, version) in enumerate(fdts):
        line = "  #%-3d @%#010x size=%-7d v%d  %s" % (
            index, offset, size, version, context_hint(data, offset))
        print(line)
        if args.outdir:
            path = os.path.join(args.outdir, "%s-dtb%d.dtb" % (base, index))
            with open(path, "wb") as handle:
                handle.write(data[offset:offset + size])
            written.append(path)

    if written:
        print("\nwrote %d file(s) to %s" % (len(written), args.outdir))
        print("note: several DTBs may share the same qcom,msm-id / qcom,board-id.")
        print("      use compare-dtb.py against the live /sys/firmware/fdt to pick")
        print("      the one that matches the actual hardware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
