# Tools

Helper scripts for bringing up a new MSM8998 device. Pure Python 3, standard
library only - no `dtc`, no `pip install`, nothing to build.

| Script | Purpose |
|---|---|
| `scan-boot-image.py` | Find and extract the DTBs packed inside a stock `boot` image |
| `inspect-dtb.py` | Dump a `.dtb`'s memory map, carveouts, board IDs and panel |
| `compare-dtb.py` | Property-level diff of DTBs, to pick the right one |
| `remux-boot-image.py` | Re-mux a built image with alternative boot header values |

## Why these exist

Porting a device starts with its device tree, and the firmware's
`PlatformMemoryMapLib.c` has to agree with what that tree says is reserved. These
scripts get the tree out of the phone and turn it into numbers you can check
against the source.

## Getting the device tree

The repository convention is the **post-bootloader** DTB - the one the running
kernel actually sees. `Android-mata.dtb` and `Android-nx563j.dtb` both contain
the `/chosen` `kaslr-seed` and `linux,initrd-start` / `linux,initrd-end`
properties that only exist after aboot patches the tree, so those come from a
booted device, not from a factory image.

On a rooted device:

```sh
adb shell "su -c 'cat /sys/firmware/fdt > /data/local/tmp/fdt.dtb; chmod 644 /data/local/tmp/fdt.dtb'"
adb pull /data/local/tmp/fdt.dtb
```

Stage the file on the device and `adb pull` it - do **not** redirect the binary
through a Windows PowerShell `>` pipe, which will corrupt it.

Some devices do not expose `/sys/firmware/fdt`. Fall back to the stock boot
image:

```sh
adb shell "su -c 'dd if=/dev/block/bootdevice/by-name/boot_a of=/data/local/tmp/boot.img bs=1048576'"
adb pull /data/local/tmp/boot.img
python3 Tools/scan-boot-image.py boot.img -o extracted
python3 Tools/compare-dtb.py /path/to/live-fdt.dtb 'extracted/*-dtb*.dtb'
```

Use `bs=1048576`, not `bs=1M` - toybox `dd` on Android rejects the `M` suffix.

## Picking the right DTB

Do not trust `qcom,msm-id` / `qcom,board-id` alone. A single Nokia 8 `boot_a`
carries **82** appended DTBs, and many of them share identical board IDs while
differing in RAM size, panel or touch wiring. Only the property diff against the
live tree identifies the real match.

For the correct candidate the only differences should be runtime ones:
`/chosen:bootargs`, `/chosen:kaslr-seed`, `/chosen:linux,initrd-*`, and the
vendor's boot-time values (e.g. FIH's `fih_apr` cause/reason properties and
`/:fih,hw-id`). If `/memory:reg`, `/:model` or `/reserved-memory` differ, it is a
different hardware variant.

## Checking the memory map

`inspect-dtb.py` prints every `/reserved-memory` child with its `no-map` /
`reusable` flags, which is exactly what has to be mirrored in
`Silicon/QC/Msm8998/QcomPkg/Library/PlatformMemoryMapLib/PlatformMemoryMapLib.c`.
That file is shared by every device in the tree, so device-specific deltas go
behind a per-device `#define`, following the existing `LG_PIL_FIXED` pattern:

```
[BuildOptions.common]
  GCC:*_*_AARCH64_CC_FLAGS = -D<DEVICE>_FIXED=1
```

`DscBuildData.py` appends options whose toolchain tag ends in `_FLAGS`, so this
is safe and will not clobber the base `-march` flags from
`Msm8998FamilyPkg.dsc.inc`.

## Bisecting a `fastboot boot` rejection

Some bootloaders refuse an image on the `fastboot boot` path with `BootImage is
Incomplete` while accepting the identical bytes via `fastboot flash`. That refusal is
about the *header*, and it is worth fixing: `fastboot boot` never writes to the device,
so it is a far cheaper and safer iteration loop than flashing.

`build.sh` never passes `--pagesize`, so every image inherits `mkbootimg.py`'s 2048
default, and it uses `--base 0x10000000` with zero offsets for the kernel, ramdisk and
tags. Stock images for these devices commonly differ on all of those.

`remux-boot-image.py` keeps the kernel payload and varies only the header, emitting
three cumulative variants:

| Variant | Change | If accepted, that field was the problem |
|---|---|---|
| `page4096` | `page_size` 2048 → 4096 | page size |
| `hdr0` | + `header_version` 0, stock `os_version` | header version / version check |
| `stocklike` | + stock load addresses | load addresses |

The os_version values in its table are the stock Nokia 8 (NB1) ones; pass
`--os-version` / `--os-patch-level` for another device.

It can also swap the appended device tree without rebuilding, which is the fastest way
to test whether a particular DTB is the reason a payload hangs:

```sh
python3 Tools/remux-boot-image.py boot-nb1.img -o variants \
    --dtb extracted/NB1-515K-boot-dtb40.dtb
```

Because `build.sh` always emits `gzip(firmware) + <device>.dtb`, the appended DTB is
located by looking for the last FDT whose declared totalsize reaches the end of the
payload, rather than assuming a fixed size.

```sh
python3 Tools/remux-boot-image.py boot-nb1.img -o variants
fastboot boot variants/boot-nb1-page4096.img
```

The CI workflow runs this automatically and ships the variants inside the same
artifact, so a single download contains the normal image plus all three variants.

Note that a RELEASE build is quiet by design - `Msm8998.dsc` sets `-DMDEPKG_NDEBUG`
and an errors-only debug level - so getting *past* the header rejection is the win;
expect a silent hang to remain until the payload itself is debugged with a DEBUG build.

## Example

```sh
python3 Tools/inspect-dtb.py Platforms/Msm8998Pkg/Device/nokia/nb1/DeviceTreeBlob/Android/Android-nb1.dtb
python3 Tools/inspect-dtb.py <dtb> --node /soc/i2c@c179000/synaptics@20
python3 Tools/inspect-dtb.py <dtb> --grep touch
python3 Tools/inspect-dtb.py <dtb> --all-nodes
```
