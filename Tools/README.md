# Tools

Helper scripts for bringing up a new MSM8998 device. Pure Python 3, standard
library only - no `dtc`, no `pip install`, nothing to build.

| Script | Purpose |
|---|---|
| `scan-boot-image.py` | Find and extract the DTBs packed inside a stock `boot` image |
| `inspect-dtb.py` | Dump a `.dtb`'s memory map, carveouts, board IDs and panel |
| `compare-dtb.py` | Property-level diff of DTBs, to pick the right one |

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

## Example

```sh
python3 Tools/inspect-dtb.py Platforms/Msm8998Pkg/Device/nokia/nb1/DeviceTreeBlob/Android/Android-nb1.dtb
python3 Tools/inspect-dtb.py <dtb> --node /soc/i2c@c179000/synaptics@20
python3 Tools/inspect-dtb.py <dtb> --grep touch
python3 Tools/inspect-dtb.py <dtb> --all-nodes
```
