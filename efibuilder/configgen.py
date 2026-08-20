"""Generation du config.plist a partir de Docs/Sample.plist."""
from __future__ import annotations

import copy
import plistlib
from pathlib import Path

from efibuilder.net import Downloader
from efibuilder.util import BuildError, hexdata, info, ok, step, warn

AMD_VANILLA_REPO = "AMD-OSX/AMD_Vanilla"
AMD_VANILLA_PATH = "patches.plist"
AM5_CHIPSETS = {"b650", "x670", "b840", "b850", "x870"}
NVRAM_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


def build_config(profile, sample: Path, acpi_add: list[dict], acpi_patch: list[dict],
                 kernel_add: list[dict], drivers: list[str], tools: list[str],
                 platform_info: dict, dl: Downloader) -> tuple[dict, list[str]]:
    """Assemble le config.plist complet. Retourne (config, avertissements)."""
    step("config.plist")
    with open(sample, "rb") as fh:
        config = plistlib.load(fh)
    for key in list(config):
        if key.startswith("#WARNING"):
            del config[key]

    warnings: list[str] = []
    plat = profile.platform_data
    quirks = plat.get("quirks", {})

    # ---------------------------------------------------------------- ACPI
    config["ACPI"]["Add"] = acpi_add
    config["ACPI"]["Delete"] = []
    config["ACPI"]["Patch"] = acpi_patch
    _apply_quirks(profile, config["ACPI"]["Quirks"], quirks.get("ACPI", {}))

    # -------------------------------------------------------------- Booter
    config["Booter"]["MmioWhitelist"] = []
    config["Booter"]["Patch"] = []
    _apply_quirks(profile, config["Booter"]["Quirks"], quirks.get("Booter", {}))

    # ---------------------------------------------------- DeviceProperties
    config["DeviceProperties"]["Add"] = _device_properties(profile, warnings)
    config["DeviceProperties"]["Delete"] = {}

    # -------------------------------------------------------------- Kernel
    config["Kernel"]["Add"] = kernel_add
    config["Kernel"]["Block"] = []
    config["Kernel"]["Force"] = []
    config["Kernel"]["Patch"] = _kernel_patches(profile, dl, warnings)
    kernel_quirks = dict(quirks.get("Kernel", {}))
    # DummyPowerManagement vit sous Kernel -> Emulate dans le schema OpenCore.
    dummy_pm = kernel_quirks.pop("DummyPowerManagement", None)
    config["Kernel"]["Emulate"] = _kernel_emulate(profile, config["Kernel"]["Emulate"], dummy_pm)
    _apply_quirks(profile, config["Kernel"]["Quirks"], kernel_quirks)
    if profile.darwin >= 20 and config["Kernel"]["Quirks"].get("XhciPortLimit"):
        if profile.usb_map_kind != "none":
            config["Kernel"]["Quirks"]["XhciPortLimit"] = False
            info("XhciPortLimit desactive: un mappage USB est fourni")
        else:
            config["Kernel"]["Quirks"]["XhciPortLimit"] = False
            warnings.append(
                "XhciPortLimit force a false: le quirk ne fonctionne plus a partir de "
                "macOS 11.3. Sans USBMap, certains ports USB resteront inactifs.")

    # ---------------------------------------------------------------- Misc
    misc = config["Misc"]
    misc["Boot"].update({
        "HideAuxiliary": True,
        "PickerMode": "External" if "gui" in profile.features else "Builtin",
        "PickerVariant": "Acidanthera\\GoldenGate",
        "ShowPicker": True,
        "Timeout": 5,
    })
    misc["Debug"].update({
        "AppleDebug": profile.debug,
        "ApplePanic": profile.debug,
        "DisableWatchDog": profile.debug,
        "Target": 67 if profile.debug else 3,
    })
    secure_boot = "Default"
    if "ota" in profile.features and profile.darwin >= 23:
        secure_boot = "Disabled"
        info("SecureBootModel=Disabled (requis pour les mises a jour OTA depuis 14.4)")
    misc["Security"].update({
        "AllowSetDefault": True,
        "BlacklistAppleUpdate": True,
        "ExposeSensitiveData": 6,
        "ScanPolicy": 0,
        "SecureBootModel": secure_boot,
        "Vault": "Optional",
    })
    misc["Tools"] = [
        {"Arguments": "", "Auxiliary": True, "Comment": name, "Enabled": True,
         "Flavour": "Auto", "FullNvramAccess": False, "Name": name, "Path": name,
         "RealPath": False, "TextMode": False}
        for name in tools
    ]
    misc["Entries"] = []
    misc["BlessOverride"] = []

    # --------------------------------------------------------------- NVRAM
    boot_args = _boot_args(profile)
    add = config["NVRAM"]["Add"].setdefault(NVRAM_GUID, {})
    add["boot-args"] = " ".join(boot_args)
    add["csr-active-config"] = hexdata("00000000")
    add["prev-lang:kbd"] = b"fr-FR:1"
    add["run-efi-updater"] = "No"
    config["NVRAM"]["Delete"] = {NVRAM_GUID: ["boot-args", "csr-active-config"]}
    config["NVRAM"]["WriteFlash"] = True
    config["NVRAM"]["LegacyOverwrite"] = False
    info(f"boot-args: {add['boot-args'] or '(aucun)'}")

    # -------------------------------------------------------- PlatformInfo
    config["PlatformInfo"] = platform_info

    # ---------------------------------------------------------------- UEFI
    uefi = config["UEFI"]
    uefi["Drivers"] = [
        {"Arguments": "", "Comment": "", "Enabled": True,
         "LoadEarly": False, "Path": name}
        for name in drivers
    ]
    uefi["ConnectDrivers"] = True
    uefi["APFS"].update({
        "EnableJumpstart": True,
        "MinDate": -1 if profile.darwin < 20 else 0,
        "MinVersion": -1 if profile.darwin < 20 else 0,
    })
    uefi["Output"]["ProvideConsoleGop"] = True
    if "audio-chime" in profile.features:
        uefi["Audio"].update({"AudioSupport": True, "PlayChime": "Auto"})
    _apply_quirks(profile, uefi["Quirks"], quirks.get("UEFI", {}))
    uefi["ReservedMemory"] = []

    ok("config.plist assemble")
    return config, warnings


def _apply_quirks(profile, target: dict, overrides: dict) -> None:
    """Applique les quirks de la plateforme; une valeur peut etre conditionnelle."""
    for key, value in overrides.items():
        if isinstance(value, dict) and "value" in value:
            if not profile.matches(value.get("when")):
                continue
            value = value["value"]
        if key not in target:
            warn(f"quirk inconnu dans platforms.json: {key}")
        target[key] = value


def _device_properties(profile, warnings: list[str]) -> dict:
    """DeviceProperties -> Add: iGPU et correctifs materiels connus."""
    props: dict[str, dict] = {}
    igpu = profile.platform_data.get("igpu")
    if igpu and profile.igpu != "none" and profile.igpu_mode != "none":
        entry: dict[str, object] = {}
        platform_id = None
        if profile.igpu_variant:
            platform_id = (igpu.get("options") or {}).get(profile.igpu_variant)
            if platform_id is None:
                warnings.append(
                    f"variante iGPU inconnue '{profile.igpu_variant}' pour "
                    f"{profile.platform}: valeur par defaut utilisee.")
        if platform_id is None:
            platform_id = igpu.get("headless") if profile.igpu_mode == "headless" \
                else igpu.get("display")
        if platform_id:
            entry[igpu.get("key", "AAPL,ig-platform-id")] = hexdata(platform_id)
        if profile.igpu_mode == "display":
            # Reserve de memoire video minimale quand le BIOS ne l'expose pas.
            if igpu.get("stolenmem"):
                entry["framebuffer-patch-enable"] = hexdata("01000000")
                entry["framebuffer-stolenmem"] = hexdata("00003001")
            if igpu.get("fbmem"):
                entry["framebuffer-fbmem"] = hexdata("00009000")
            if igpu.get("cursormem"):
                entry["framebuffer-cursormem"] = hexdata("00009000")
        for key, value in (igpu.get("props") or {}).items():
            entry[key] = hexdata(value)
        if entry:
            props[igpu["path"]] = entry
        for extra in igpu.get("extra_devices", []):
            if profile.matches(extra.get("when")):
                props[extra["path"]] = {k: hexdata(v) for k, v in extra["props"].items()}

    if profile.ethernet == "intel-i225":
        # Fait passer un I225-V pour un I225-LM, seul modele gere par Apple.
        props["PciRoot(0x0)/Pci(0x1C,0x1)/Pci(0x0,0x0)"] = {"device-id": hexdata("F2150000")}
        warnings.append(
            "Intel I225: si un kernel panic AppleIntelI210Ethernet apparait, le chemin PCI "
            "est probablement PciRoot(0x0)/Pci(0x1C,0x4)/Pci(0x0,0x0).")
    return props


def _kernel_emulate(profile, current: dict, dummy_pm: bool | None) -> dict:
    emulate = copy.deepcopy(current)
    emulate.setdefault("Cpuid1Data", b"")
    emulate.setdefault("Cpuid1Mask", b"")
    if dummy_pm is not None:
        emulate["DummyPowerManagement"] = bool(dummy_pm)
    if profile.cpuid_data:
        emulate["Cpuid1Data"] = hexdata(profile.cpuid_data)
        emulate["Cpuid1Mask"] = hexdata(profile.cpuid_mask or "FFFFFFFF")
    return emulate


def _kernel_patches(profile, dl: Downloader, warnings: list[str]) -> list[dict]:
    """Patches noyau: AMD_Vanilla pour les CPU AMD, rien pour Intel."""
    if profile.platform_data.get("kernel_patches") != "amd_vanilla":
        return []
    try:
        path = dl.github_raw(AMD_VANILLA_REPO, AMD_VANILLA_PATH)
    except Exception as exc:  # noqa: BLE001
        raise BuildError(
            f"patches AMD_Vanilla indisponibles ({exc}); un Hackintosh AMD ne demarre pas "
            f"sans eux") from exc
    with open(path, "rb") as fh:
        data = plistlib.load(fh)
    patches = data.get("Kernel", {}).get("Patch", [])
    cores = profile.cpu_cores
    patched = 0
    for patch in patches:
        comment = patch.get("Comment", "")
        if "cpuid_cores_per_package" in comment:
            replace = bytearray(patch["Replace"])
            if cores > 0:
                replace[1] = cores
                patch["Replace"] = bytes(replace)
                patched += 1
        if "IOPCIIsHotplugPort" in comment:
            enabled = (profile.chipset or "").lower() in AM5_CHIPSETS
            patch["Enabled"] = enabled
            if enabled:
                info("patch AM5 IOPCIIsHotplugPort active")
    if cores > 0:
        info(f"patches AMD_Vanilla: {len(patches)} entrees, "
             f"cpuid_cores_per_package = {cores} ({patched} variantes)")
    else:
        warnings.append(
            "patches AMD_Vanilla installes avec cpuid_cores_per_package = 0: "
            "relancez avec --cores <nombre de coeurs physiques> avant de demarrer.")
    return patches


def _boot_args(profile) -> list[str]:
    args: list[str] = []
    if profile.debug:
        args += ["-v", "debug=0x100", "keepsyms=1"]
    args += profile.platform_data.get("boot_args", [])
    if profile.audio != "none":
        args.append(f"alcid={profile.audio_layout}")
    if profile.dgpu == "amd-navi":
        args.append("agdpmod=pikera")
    if profile.dgpu == "nvidia-unsupported":
        args.append("-wegnoegpu")
    if "ota" in profile.features and profile.darwin >= 23:
        args.append("revpatch=sbvmm")
    if profile.bluetooth == "intel" and profile.darwin >= 25:
        args.append("-ibtcompatbeta")
    if "no-avx2" in profile.features:
        args.append("-nokcmismatchpanic")
    for extra in profile.boot_args:
        if extra not in args:
            args.append(extra)
    return args
