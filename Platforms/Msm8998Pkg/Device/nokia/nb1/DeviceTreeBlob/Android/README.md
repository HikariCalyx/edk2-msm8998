# `Android-nb1.dtb` — Nokia 8 (TA-1052 / NB1)

Real device tree, extracted from the hardware. **Not a placeholder.**

| | |
|---|---|
| Source | `/sys/firmware/fdt` on the live device (via `su`), 2026-09-13 |
| Device | Nokia 8 `TA-1052` — model string `Qualcomm Technologies, Inc. MSM8998 v2.1 MTP, FIH NB1 PVT1 NEW_ROW` |
| Size | 402503 bytes, FDT version 17, 2324 nodes |
| SHA256 | `D56602022558AD30DB413B5A41BCABEC73D40979A58343D5DE9497432B8EC0ED` |
| Board IDs | `qcom,msm-id = <292 0x20001>`, `qcom,board-id = <8 0 1 0>` |

`build.sh` appends this file verbatim to the kernel image, so the filename is load-bearing:

```
cat uefi-nb1.img.gz Platforms/Msm8998Pkg/Device/nokia/nb1/DeviceTreeBlob/Android/Android-nb1.dtb \
    > uefi-nb1.img.gz-dtb
```

## Provenance

This is the **post-bootloader DTB** — it contains the `/chosen` `kaslr-seed` and
`linux,initrd-start`/`linux,initrd-end` properties that aboot/the kernel add at boot. That
matches the convention already used in this repository: `Android-mata.dtb` and
`Android-nx563j.dtb` both contain the same runtime nodes.

The pristine pre-fixup equivalent is entry `dtb40` inside the stock `boot_a` image
(`NB1-515K-boot.img`, which carries 82 appended DTBs). It is the closest match by a clear
margin - 6 differing properties versus 8+ for the next candidates - and all 6 are values the
bootloader rewrites at boot: `/chosen` (`kaslr-seed`, `linux,initrd-start` / `-end`,
`bootargs`), the `fih_apr` power/reason values, and `/memory:reg` + `splash_region:reg`.
`/:model` is identical, which is what identifies it. Lookalike entries such as `dtb2` share the
same msm-id/board-id but differ in `/:model` and RAM configuration - a different hardware
variant. Use `Tools/compare-dtb.py` to reproduce this.

See `PORTING-nb1.md` at the repository root for the memory-map caveats that still apply.
