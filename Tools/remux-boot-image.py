#!/usr/bin/env python3
#
#  Copyright (c) 2026, the edk2-msm8998 contributors. All rights reserved.
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#
"""Re-mux a built boot image with alternative Android boot header values.

Why this exists: some bootloaders refuse a boot image on the `fastboot boot`
path ("BootImage is Incomplete") while accepting the very same bytes via
`fastboot flash`. That refusal is about the *header*, not the payload, and it is
cheap to bisect: keep the kernel payload, vary only the header fields.

Variants (cumulative, so the first one a bootloader accepts tells you what it
objected to):

    page4096    page_size 4096. build.sh never passes --pagesize, so every
                image inherits mkbootimg.py's 2048 default, while stock images
                for these devices commonly use 4096.
    hdr0        + header_version 0 and the device's stock os_version.
    stocklike   + the load addresses used by the stock boot image.

The os_version values in the table are the stock Nokia 8 (NB1) ones, read out of
its factory boot image. For a different device, pass --os-version /
--os-patch-level or edit the table.

Usage:
    python3 Tools/remux-boot-image.py boot-nb1.img -o variants
    python3 Tools/remux-boot-image.py boot-nb1.img -o variants --variants page4096
"""

import argparse
import os
import struct
import subprocess
import sys

HEADER_FIELDS = ("kernel_size", "kernel_addr", "ramdisk_size", "ramdisk_addr",
                 "second_size", "second_addr", "tags_addr", "page_size",
                 "header_version", "os_version")

# name -> (description, mkbootimg overrides)
VARIANTS = {
    "page4096": (
        "page_size 4096 (stock uses 4096; default here is mkbootimg's 2048)",
        {"pagesize": 4096},
    ),
    "hdr0": (
        "+ header_version 0 and the stock os_version",
        {"pagesize": 4096, "header_version": 0,
         "os_version": "9.0.0", "os_patch_level": "2020-10"},
    ),
    "stocklike": (
        "+ the stock image's load addresses",
        {"pagesize": 4096, "header_version": 0,
         "os_version": "9.0.0", "os_patch_level": "2020-10",
         "base": 0x0, "kernel_offset": 0x8000, "ramdisk_offset": 0x1000000,
         "second_offset": 0xF00000, "tags_offset": 0x100},
    ),
}


def read_header(path):
    with open(path, "rb") as handle:
        head = handle.read(48)
    if head[:8] != b"ANDROID!":
        raise SystemExit("%s: no ANDROID! magic" % path)
    return dict(zip(HEADER_FIELDS, struct.unpack_from("<10I", head, 8)))


def extract_kernel(path, dest):
    """Copy the raw kernel payload (gzipped UEFI + appended DTB) out of the image."""
    header = read_header(path)
    with open(path, "rb") as handle:
        handle.seek(header["page_size"])
        payload = handle.read(header["kernel_size"])
    if len(payload) != header["kernel_size"]:
        raise SystemExit("%s: truncated kernel payload" % path)
    with open(dest, "wb") as handle:
        handle.write(payload)
    return payload, header


def decode_os_version(value):
    version, patch = value >> 11, value & 0x7FF
    return ("%d.%d.%d" % ((version >> 14) & 0x7F, (version >> 7) & 0x7F,
                          version & 0x7F),
            "%d-%02d" % (2000 + (patch >> 4), patch & 0xF))


def mux(mkbootimg, kernel, ramdisk, out, overrides, os_version, os_patch_level):
    """Invoke mkbootimg.py, mirroring build.sh but with the overrides applied."""
    opts = {
        "kernel": kernel,
        "ramdisk": ramdisk,
        "kernel_offset": "0x00000000",
        "ramdisk_offset": "0x00000000",
        "tags_offset": "0x00000000",
        "os_version": os_version,
        "os_patch_level": os_patch_level,
        "header_version": 1,
    }
    opts.update(overrides)

    args = [sys.executable, mkbootimg]
    for key, value in opts.items():
        args += ["--" + key, hex(value) if isinstance(value, int) else str(value)]
    args += ["-o", out]
    subprocess.run(args, check=True)


def describe(path):
    header = read_header(path)
    return ("page=%#x hdrver=%d kernel_addr=%#x ramdisk_addr=%#x tags_addr=%#x "
            "ramdisk_size=%d" % (header["page_size"], header["header_version"],
                                 header["kernel_addr"], header["ramdisk_addr"],
                                 header["tags_addr"], header["ramdisk_size"]))


def main():
    parser = argparse.ArgumentParser(
        description="Re-mux a boot image with alternative header values.")
    parser.add_argument("image", help="a boot image produced by build.sh")
    parser.add_argument("-o", "--outdir", default="variants",
                        help="where to write the variants (default: variants)")
    parser.add_argument("--variants", default=",".join(VARIANTS),
                        help="comma-separated subset (default: all)")
    parser.add_argument("--mkbootimg", default=None,
                        help="path to mkbootimg.py (default: repository root)")
    parser.add_argument("--os-version", default=None,
                        help="override the variant os_version, e.g. 9.0.0")
    parser.add_argument("--os-patch-level", default=None,
                        help="override the variant os patch level, e.g. 2020-10")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    mkbootimg = args.mkbootimg or os.path.join(os.path.dirname(here), "mkbootimg.py")
    if not os.path.isfile(mkbootimg):
        raise SystemExit("mkbootimg.py not found at %s (use --mkbootimg)" % mkbootimg)

    requested = [name.strip() for name in args.variants.split(",") if name.strip()]
    for name in requested:
        if name not in VARIANTS:
            raise SystemExit("unknown variant %r; choose from %s"
                             % (name, ", ".join(VARIANTS)))

    os.makedirs(args.outdir, exist_ok=True)
    payload = os.path.join(args.outdir, ".kernel-payload.bin")
    ramdisk = os.path.join(args.outdir, ".ramdisk")
    base = os.path.splitext(os.path.basename(args.image))[0]

    _, header = extract_kernel(args.image, payload)
    # build.sh creates this with `echo > ramdisk`, i.e. a single newline.
    with open(ramdisk, "wb") as handle:
        handle.write(b"\n")

    src_version, src_patch = decode_os_version(header["os_version"])
    print("source %s: %s" % (os.path.basename(args.image), describe(args.image)))
    print("          os_version=%s patch=%s\n" % (src_version, src_patch))

    for name in requested:
        description, overrides = VARIANTS[name]
        effective = dict(overrides)
        effective.setdefault("os_version", src_version)
        effective.setdefault("os_patch_level", src_patch)
        if args.os_version:
            effective["os_version"] = args.os_version
        if args.os_patch_level:
            effective["os_patch_level"] = args.os_patch_level

        out = os.path.join(args.outdir, "%s-%s.img" % (base, name))
        mux(mkbootimg, payload, ramdisk, out, effective, src_version, src_patch)
        print("%s" % os.path.basename(out))
        print("   %s" % description)
        print("   %s" % describe(out))

    os.remove(payload)
    os.remove(ramdisk)
    print("\nwrote %d variant(s) to %s" % (len(requested), args.outdir))
    print("test each with: fastboot boot <variant>.img")
    return 0


if __name__ == "__main__":
    sys.exit(main())
