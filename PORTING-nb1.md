# Porting notes — `nb1` (Nokia 8)

Scaffolded from the `mata` (Essential Phone PH-1) port, same vendor-`Common`/shared-binaries
layout. The build tree is complete and will compile, but **two binary blobs are still
placeholders copied from `mata` and must be replaced before flashing anything.**

## Device matrix entry

| Item | Value |
|---|---|
| Codename | `nb1` |
| Vendor folder | `nokia` |
| SoC | MSM8998 (Snapdragon 835) |
| Panel | 1440x2560 |
| Files | `Config/nb1.conf`, `Platforms/Msm8998Pkg/Device/nokia/nb1/{nb1.dsc,nb1.fdf}` |
| ACPI | `Platforms/Msm8998ACPI/nokia/{Common,nb1}` |
| Binaries | none per-device — FDF reuses `Platforms/Msm8998Binaries/common/dxe.inc` |

## Device facts (verified on hardware, 2026-09-13)

Read from the live DTB (`/sys/firmware/fdt`) and the stock `boot_a` image (`NB1-515K-boot.img`).

| Fact | Value |
|---|---|
| Model string | `Qualcomm Technologies, Inc. MSM8998 v2.1 MTP, FIH NB1 PVT1 NEW_ROW` |
| SoC | MSM8998 **v2.1**, ODM FIH |
| Board IDs | `qcom,msm-id = <292 0x20001>` (platform 292, soc rev v2.1), `qcom,board-id = <8 0 1 0>` |
| RAM | **8 GB confirmed** — `/memory` = `0x80000000`+4 GiB, plus `0x180000000`+`0xFCBC0000` (ends `0x27CBC0000`) |
| Panel | JDI dual-MIPI 1440x2560 — `qcom,mdss_dsi_jdi_wqxga_dualmipi_cmd` ("JDI Dual nt36850 cmd mode dsi panel without DSC") → confirms the 1440x2560 PCDs |
| Touch | Synaptics DSX. Both buses are described, but only **SPI is enabled**: `i2c@c179000` = `disabled`, `spi@c179000` = `okay` (CS 0 @ 5 MHz). Reset GPIO 89, IRQ GPIO 125. This breaks the copied `mata` ACPI, which is I2C — see §2 |
| Fingerprint | Goodix `gf318m` (not used by UEFI) |
| Partition layout | A/B (`boot_a`/`boot_b`, `system_a`/`system_b`); **no `dtbo` partition** — DTBs are appended to the kernel |

The stock boot image (Android 9.0.0, patch 2020-10, little-endian boot header) carries
**82 appended DTBs**, and many share this unit's exact `msm-id`/`board-id` — so board ID alone
does not identify the right one. Ranking them against the live tree gives entry `dtb40` as the
closest match (6 differing properties; the next cluster is at 8+). `dtb40` differs only in
values the bootloader rewrites at boot — `/chosen` (`kaslr-seed`, `linux,initrd-start`/`-end`,
`bootargs`), the `fih_apr` power/reason values, and `/memory:reg` + `splash_region:reg`.
`/:model` is identical, which is what identifies it; a lookalike such as `dtb2` shares the same
IDs but has a different `/:model` and RAM configuration.

All of the above was measured with the scripts in `Tools/` — see `Tools/README.md`.

## Blob status

| Path | Status |
|---|---|
| `.../DeviceTreeBlob/Android/Android-nb1.dtb` | ✅ **real** — extracted from the device; see `DeviceTreeBlob/Android/README.md` |
| `.../DeviceTreeBlob/Linux/msm8998-generic-msd.dtb` | ✅ shared generic blob (SHA256 `24B17268…`, identical to `mata`/`nx563j`) |
| `Platforms/Msm8998ACPI/nokia/nb1/dsdt.aml` | ⚠️ **still `mata`'s compiled DSDT** — regenerate with `iasl -ve Platforms/Msm8998ACPI/nokia/nb1/dsdt.asl` (or build with `--acpi`) |

`build.sh` appends `Android-nb1.dtb` verbatim to the kernel image, so that filename is
load-bearing: `cat uefi-nb1.img.gz …/Android-<device>.dtb > …-dtb`.

## 1. Memory map — highest risk

`Silicon/QC/Msm8998/QcomPkg/Library/PlatformMemoryMapLib/PlatformMemoryMapLib.c` is shared by
**every** device; there is no per-device override mechanism and no `mata`/`nb1` conditionals
anywhere in `Silicon/` or `Msm8998FamilyPkg/`. Every carve-out is hard-coded:

- `HLOS 1` / `HLOS 2` / `HLOS 3`, `TZ`, `TZApps`, `SMEM`, `MPSS_EFS`, `Hypervisor`
- `PIL_REGION` — note the existing `#ifdef LG_PIL_FIXED` in this file as the established
  pattern for a vendor deviation (`joan` shrinks it by 0x100000 and grows `HLOS 3` to match)
- `Display Reserved` @ `0x9D400000` — must not collide with `PcdMipiFrameBufferAddress`
- `FV Region`, `ABOOT FV`, `UEFI FD`, `SEC Heap`, `MMU PageTables`, `DXE Heap`

Source the correct values from the device's downstream kernel `reserved-memory` nodes in the
`nb1` DTS, or from `aboot` logs. A wrong map here is what wipes UFS.

### Concrete deltas against this device's DTB

RAM is **8 GB**, so the `Mem8G` variants apply. Comparing the device's `reserved-memory`
nodes against `PlatformMemoryMapLib.c`:

| Device node | Project map | Verdict |
|---|---|---|
| `splash_region` `0x9D400000`+`0x2400000` | `Display Reserved` `0x9D400000`+`0x02400000` | ✅ exact match (also matches `PcdMipiFrameBufferAddress`) |
| `removed_regions` `0x85800000`+`0x3700000` | `Hypervisor`+`MPSS_EFS`+`SMEM`+`TZ`+`TZApps` (sum `0x3700000`, `0x85800000`..`0x88F00000`) | ✅ exact match |
| `fih_region@a0000000` `0xA0000000`+`0xB00000` | swallowed by `RAM Partition` `Mem8G` `0xA0000000`+`0xE0000000` | ✅ **fixed** — reserved as `FIH Region` |
| `ramoops_region@a0b00000` `0xA0B00000`+`0x200000` | same region as above | ✅ **fixed** — reserved as `Ramoops` |
| `/memory` ends `0x27CBC0000` | `RAM Partition` `Mem8G` `0x180000000`+`0xFCCC0000` (ends `0x27CCC0000`) | ✅ **fixed** — length corrected to `0xFCBC0000` |
| PIL/SSC block: `spss` `0x8AB00000`+`0x700000` … `pil_ipa_gpu` `0x95200000`+`0x100000` (ends `0x95300000`) | `PIL_REGION` `0x8AB00000`+`0x0B315000` (ends `0x95E15000`) | ⚠️ over-reserves `0xB15000` (~11 MiB), left as-is |

### How the fix is wired

The three fixed rows are applied in `PlatformMemoryMapLib.c` under `#ifdef NB1_FIXED`, mirroring
the existing `LG_PIL_FIXED` override used by `joan`:

| Change | Descriptor |
|---|---|
| Reserve `0xA0000000`+`0xB00000` | `{"FIH Region", …, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, NS_DEVICE}` |
| Reserve `0xA0B00000`+`0x200000` | `{"Ramoops", …, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, NS_DEVICE}` |
| Correct top of DRAM | `Mem8G` `RAM Partition` `0x180000000`+`0xFCBC0000` (was `0xFCCC0000`) |

`nb1.dsc` enables it with `[BuildOptions.common]` / `GCC:*_*_AARCH64_CC_FLAGS = -DNB1_FIXED=1`.
Adding that line is verified safe: `DscBuildData.py` **appends** rather than replaces options whose
toolchain tag ends in `_FLAGS`, so the base `-march=armv8-a+lse` and
`-DENABLE_LINUX_SIMPLE_MASS_STORAGE` flags from `Msm8998FamilyPkg.dsc.inc` survive.

Before this, the shared map handed `0xA0000000`..`0xA0D00000` to UEFI as free RAM, clobbering
Nokia's `fih_region` and the `ramoops` buffer. `fih_region` is FIH/Nokia-specific and appears in
no other device in this tree, which is why the shared map missed it.

All the carveouts are `compatible = "removed-dma-pool"; no-map;` in the DTB, i.e. genuinely
reserved, and the bootloader's legacy memory-reservation block is empty.

Tightening `PIL_REGION` is the one optional follow-up: it would reclaim ~11 MiB but requires
moving `HLOS 3` to `0x95300000` at the same time.

## 2. ACPI

`Platforms/Msm8998ACPI/nokia/nb1/` is currently `mata`'s ASL set. `nokia/Common/` holds the
shared includes (identical base set to `essential/Common`). Tune the device-specific files:

`cust_touch.asl`, `cust_touch_resources.asl`, `panelcfg.asl`, `graphics.asl`,
`cust_pmic_batt.asl`, `cust_sensors.asl`, `cust_camera*.asl`, `usb.asl`, `wcnss_wlan.asl`,
`cust_dsdt.asl`, `pep*.asl`.

Note `dsdt.asl` resolves includes relative to itself, hence the per-vendor `nokia/Common/`
copy for `../Common/*.asl`.

### Measured deltas vs the copied `mata` ASL

**Touch is on SPI, not I2C.** `mata` and NB1 are mirror images — mata has `i2c@c179000` =
`okay` / `spi@c179000` = `disabled`, NB1 is the reverse. `cust_touch.asl` declares
`I2cSerialBusV2 (0x0020, …, "\\_SB.I2C5")`, which is right for mata and wrong for NB1. The GPIOs,
however, are **already correct**: the ASL's `GpioInt` pin `0x7D` (125) and `GpioIo` pin `0x59`
(89) match NB1's `synaptics,irq-gpio = <123 125 8200>` / `synaptics,reset-gpio = <123 89 0>`
exactly. Only the bus needs changing:

- `spi@c179000` is the **same QUP block** as `I2C5` (`0xC179000`, length `0x600`), so a `SPI5`
  device in `buses.asl` can mirror `Device (I2C5)` — same `Memory32Fixed`, same GSI `131`
  (DT `interrupts = <0 99 0>` → SPI 99 → GSI 32+99 = 131, which is what `I2C5`'s `0x83`
  already encodes), same `\_SB.BAM3` / `\_SB.PEP0` dependencies.
- `cust_touch.asl`: `I2cSerialBusV2 (…)` → `SpiSerialBusV2` with CS 0 (`spi@c179000` child
  `reg = <0>`), 5 MHz (`spi-max-frequency = <5000000>`), controller `\\_SB.SPI5`.
- The ASL uses `GpioInt (Edge, ActiveLow, …)` while the DTB's `8200` is `IRQ_TYPE_LEVEL_LOW` —
  worth reconciling.

**This is blocked on driver work, not just ASL.** `SynapticsRmi4Dxe` is I2C-only: it includes
`EFII2C.h`, uses `gQcomI2cProtocolGuid` and `PcdTouchCtlrI2cDevice`, and its depex is
`gQcomI2cProtocolGuid AND gQcomTlmmProtocolGuid`. There is no SPI transport to enable, and no
MSM8998 device in this tree declares an SPI bus in ACPI to copy from. Touch is therefore a
post-boot milestone, not a bring-up blocker.

**Battery data is `mata`'s, not NB1's.** `cust_pmic_batt.asl` carries `BFCC 13110`, `VDD1 4335`,
`FCC1 2100` and JEITA 0/10/45/55. NB1's DTB ships three selectable profiles
(`qcom,batt-id-range-pct = <15>`, `max-voltage-uv = 4400000`, beta 3450):

| Profile | Capacity | `batt-id-kohm` | `fastchg-current-ma` | `fg-jeita-thresholds` |
|---|---|---|---|---|
| `NB1_ATL_3090mah_39K` | 3090 mAh | 39 | 3000 | 0 / 15 / 45 / 55 |
| `NB1_ATL_3150mah_68K` | 3150 mAh | 68 | 3000 | 0 / 20 / 50 / 55 |
| `NB1_Coslight_3150mah_100K` | 3150 mAh | 100 | 1500 | 0 / 20 / 50 / 55 |

Each also has a 224-byte `qcom,fg-profile-data` blob and its own `qcom,checksum` — these are
what the gauge needs, so the ACPI values should be taken from the DTB rather than tuned by hand.

**Panel** is the JDI dual-MIPI 1440x2560 nt36850 (no DSC); check `panelcfg.asl` / `graphics.asl`
against that.


## 3. Touch and panel

DXE drivers are device-agnostic; per-device behaviour comes from PCDs and the DTB. If the
Nokia 8 touch controller differs from `mata`'s, either add it to
`Platforms/Msm8998FamilyPkg/Drivers/SynapticsRmi4Dxe/` or fall back to
`KeypadDxe`/`GenericKeypadDeviceDxe`.

`PcdGuiDefaultDPI|550` in `nb1.dsc` is an eyeball guess for a 5.3" 1440x2560 panel — tune it,
it is not correctness-critical.

## 4. Build and boot

```bash
bash build.sh --device nb1 -r DEBUG
fastboot boot boot-nb1.img     # NEVER `flash` — verified-boot/partition risk
```

Bring-up order: framebuffer console (`SimpleFbDxe` / `FrameBufferSerialPortLib`) → memory map
→ UFS → USB → touch → ACPI.

## 5. Known upstream quirks inherited from `mata`

- `mata.dsc` had `VENDOR_NAME = ssential` (typo, inert — no FDF reads `VENDOR_NAME`; platform
  selection comes from `Config/<device>.conf` via `build.sh`). Written correctly as `nokia`
  here.
- `mata.dsc` reused `nx563j`'s `PLATFORM_GUID`. `nb1.dsc` uses a fresh one:
  `466e03d4-0a99-4548-916b-dd823e20ef6d`.
- The FDF includes `Platforms/Msm8998Binaries/common/dxe.inc` **twice** (once inside
  `APRIORI DXE {}`, once in the main FV). That is intentional and copied as-is.
