[Defines]
  VENDOR_NAME                    = nokia
  PLATFORM_NAME                  = nb1
  PLATFORM_GUID                  = 466e03d4-0a99-4548-916b-dd823e20ef6d
  PLATFORM_VERSION               = 0.1
  DSC_SPECIFICATION              = 0x00010019
  OUTPUT_DIRECTORY               = Build/$(PLATFORM_NAME)
  SUPPORTED_ARCHITECTURES        = AARCH64
  BUILD_TARGETS                  = DEBUG|RELEASE
  SKUID_IDENTIFIER               = DEFAULT
  FLASH_DEFINITION               = Platforms/Msm8998Pkg/Device/nokia/nb1/nb1.fdf

!include Platforms/Msm8998Pkg/Msm8998.dsc

[BuildOptions.common]
  # Reserves the FIH / ramoops carveouts and fixes the top of DRAM for NB1.
  GCC:*_*_AARCH64_CC_FLAGS = -DNB1_FIXED=1

[PcdsFixedAtBuild.common]

  # UI scale hint only; tune by eye, not correctness critical.
  gSimpleInitTokenSpaceGuid.PcdGuiDefaultDPI|550

  gMSM8998PkgTokenSpaceGuid.PcdMipiFrameBufferWidth|1440
  gMSM8998PkgTokenSpaceGuid.PcdMipiFrameBufferHeight|2560

  # Device Info
  gMSM8998PkgTokenSpaceGuid.PcdDeviceVendor|"Nokia"
  gMSM8998PkgTokenSpaceGuid.PcdDeviceProduct|"8"
  gMSM8998PkgTokenSpaceGuid.PcdDeviceCodeName|"nb1"
