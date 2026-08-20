"""Retro-ingenierie d'un EFI existant vers un profil efibuild."""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

from efibuilder import data_files
from efibuilder.profile import SIP_LEVELS, Profile
from efibuilder.util import BuildError, info, ok, step, warn

NVRAM_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"

# Un kext identifie sans ambiguite un composant materiel.
ETHERNET_BY_KEXT = {
    "IntelMausi.kext": "intel-i219", "AppleIGB.kext": "intel-igb",
    "LucyRTL8125Ethernet.kext": "rtl8125", "RealtekRTL8111.kext": "rtl8111",
    "AtherosE2200Ethernet.kext": "atheros",
}
WIFI_BY_KEXT = {
    "AirportItlwm.kext": "intel", "AirportBrcmFixup.kext": "broadcom",
    "rtw88.kext": "realtek", "Feixiao.kext": "realtek",
}
BLUETOOTH_BY_KEXT = {
    "IntelBluetoothFirmware.kext": "intel", "BrcmPatchRAM3.kext": "broadcom",
    "BrcmPatchRAM2.kext": "broadcom", "RealtekBluetoothFirmware.kext": "realtek",
}
# Un kext optionnel trahit la fonction qui l'a fait installer.
FEATURE_BY_KEXT = {
    "HibernationFixup.kext": "hibernation", "FeatureUnlock.kext": "sidecar",
    "CPUFriend.kext": "cpufriend", "SMCLightSensor.kext": "light-sensor",
    "RTCMemoryFixup.kext": "rtc-fix", "CryptexFixup.kext": "no-avx2",
    "CtlnaAHCIPort.kext": "sata-legacy",
}
FEATURE_BY_DRIVER = {
    "OpenCanopy.efi": "gui", "AudioDxe.efi": "audio-chime",
    "OpenLinuxBoot.efi": "linux-boot",
}
# Famille de CPU du tableau SMBIOS -> plateforme efibuild.
PLATFORM_BY_CPU = [
    ("comet lake", "comet-lake-desktop", "coffee-lake-plus-laptop"),
    ("coffee lake", "coffee-lake-desktop", "coffee-lake-laptop"),
    ("kaby lake", "kaby-lake-desktop", "kaby-lake-laptop"),
    ("amber lake", "kaby-lake-desktop", "kaby-lake-laptop"),
    ("skylake-w", "skylake-x-hedt", "skylake-x-hedt"),
    ("cascade lake", "skylake-x-hedt", "skylake-x-hedt"),
    ("skylake", "skylake-desktop", "skylake-laptop"),
    ("broadwell", "haswell-desktop", "broadwell-laptop"),
    ("haswell", "haswell-desktop", "haswell-laptop"),
    ("ivy bridge", "ivy-bridge-desktop", "ivy-bridge-laptop"),
    ("sandy bridge", "sandy-bridge-desktop", "sandy-bridge-laptop"),
    ("ice lake", "comet-lake-desktop", "icelake-laptop"),
    ("arrandale", "clarkdale-desktop", "arrandale-laptop"),
    ("penryn", "penryn-desktop", "arrandale-laptop"),
]
LAPTOP_SUFFIXES = ("(m)", "(u)", "(y)", "(h)", "(qm)", "(hq)")


def load_config(path: Path) -> tuple[dict, Path]:
    """Accepte un config.plist, un dossier EFI ou le dossier qui le contient."""
    path = Path(path).expanduser()
    if path.is_dir():
        for candidate in (path / "EFI" / "OC" / "config.plist",
                          path / "OC" / "config.plist",
                          path / "config.plist"):
            if candidate.exists():
                path = candidate
                break
        else:
            raise BuildError(f"aucun config.plist trouve sous {path}")
    if not path.exists():
        raise BuildError(f"fichier introuvable: {path}")
    with open(path, "rb") as fh:
        return plistlib.load(fh), path


def import_profile(config: dict, macos: str = "sequoia") -> tuple[Profile, list[str]]:
    """Deduit un profil du config.plist. Retourne (profil, remarques)."""
    notes: list[str] = []
    bundles = {e["BundlePath"] for e in config.get("Kernel", {}).get("Add", [])
               if e.get("Enabled", True) and "/" not in e["BundlePath"]}
    drivers = {d["Path"] if isinstance(d, dict) else d
               for d in config.get("UEFI", {}).get("Drivers", [])}
    generic = config.get("PlatformInfo", {}).get("Generic", {})
    smbios = generic.get("SystemProductName", "")

    is_amd = any("AuthenticAMD" in p.get("Comment", "") or "cpuid_cores_per_package"
                 in p.get("Comment", "")
                 for p in config.get("Kernel", {}).get("Patch", []))
    laptop = _looks_like_laptop(bundles, config, smbios)
    platform = _guess_platform(smbios, is_amd, laptop, notes)

    boot_args = (config.get("NVRAM", {}).get("Add", {})
                 .get(NVRAM_GUID, {}).get("boot-args", "")).split()
    profile = Profile(platform=platform, macos=macos, smbios=smbios)
    profile.name = f"Importe depuis {smbios or 'un EFI existant'}"
    profile.chassis = "laptop" if laptop else "desktop"
    profile.processor_type = int(generic.get("ProcessorType", 0) or 0)
    profile.serials = bool(generic.get("SystemSerialNumber"))
    profile.nvme = "NVMeFix.kext" in bundles
    profile.cpu_cores = _cores_from_amd_patches(config)

    profile.ethernet = _first(bundles, ETHERNET_BY_KEXT, "none")
    profile.wifi = _first(bundles, WIFI_BY_KEXT, "none")
    profile.bluetooth = _first(bundles, BLUETOOTH_BY_KEXT, "none")
    if "VoodooI2C.kext" in bundles:
        profile.touchpad = "i2c"
    elif "VoodooPS2Controller.kext" in bundles:
        profile.touchpad = "ps2"
    profile.audio = "alc" if "AppleALC.kext" in bundles else "none"

    if "NootedRed.kext" in bundles:
        profile.igpu, profile.igpu_mode = "amd-vega-apu", "display"
    else:
        _read_igpu(config, profile, notes)
    if "agdpmod=pikera" in boot_args:
        profile.dgpu = "amd-navi"
    elif "-wegnoegpu" in boot_args:
        profile.dgpu = "nvidia-unsupported"

    if "UTBMap.kext" in bundles or "USBToolBox.kext" in bundles:
        profile.usb_map_kind = "usbtoolbox"
        notes.append(
            "mappage USB detecte (USBToolBox): repassez votre UTBMap.kext avec "
            "--usb-map <chemin>, efibuild ne peut pas la reconstituer depuis le config.")
    elif "USBMap.kext" in bundles:
        profile.usb_map_kind = "usbmap"
        notes.append(
            "USBMap.kext detectee: repassez-la avec --usb-map <chemin>, "
            "ou regenerez-la avec 'efibuild usbmap'.")

    features = {FEATURE_BY_KEXT[k] for k in bundles if k in FEATURE_BY_KEXT}
    features |= {FEATURE_BY_DRIVER[d] for d in drivers if d in FEATURE_BY_DRIVER}
    if "revpatch=sbvmm" in boot_args or "RestrictEvents.kext" in bundles:
        features.add("ota")
    if config.get("PlatformInfo", {}).get("UpdateSMBIOSMode") == "Custom":
        features.add("custom-smbios")
    if "-vi2c-force-polling" in boot_args:
        features.add("i2c-polling")
    profile.features = sorted(features)

    profile.debug = "-v" in boot_args
    profile.audio_layout = _alcid(boot_args, config, profile.audio_layout)
    profile.sip = _sip_level(config, notes)
    profile.boot_args = _leftover_boot_args(boot_args, profile)

    notes.extend(_unmapped_kexts(bundles))
    notes.extend(_quirk_deltas(config, profile))
    return profile, notes


# --------------------------------------------------------------------- details
def _first(bundles: set[str], table: dict[str, str], default: str) -> str:
    for kext, value in table.items():
        if kext in bundles:
            return value
    return default


def _looks_like_laptop(bundles: set[str], config: dict, smbios: str) -> bool:
    if smbios.lower().startswith(("macbook",)):
        return True
    if {"SMCBatteryManager.kext", "VoodooPS2Controller.kext", "VoodooI2C.kext",
        "ECEnabler.kext", "BrightnessKeys.kext"} & bundles:
        return True
    return any("PNLF" in entry.get("Path", "")
               for entry in config.get("ACPI", {}).get("Add", []))


def _guess_platform(smbios: str, is_amd: bool, laptop: bool, notes: list[str]) -> str:
    if is_amd:
        return "amd-zen-laptop" if laptop else "amd-zen"
    reference = data_files.smbios_model(smbios) if smbios else None
    if reference:
        cpu = reference["cpu"].lower()
        mobile = laptop or any(s in cpu for s in LAPTOP_SUFFIXES)
        for keyword, desktop_id, laptop_id in PLATFORM_BY_CPU:
            if keyword in cpu:
                return laptop_id if mobile else desktop_id
    notes.append(
        f"plateforme non deduite depuis le SMBIOS {smbios or '(absent)'}: "
        f"verifiez le champ 'platform' du profil ('efibuild list platforms').")
    return "comet-lake-desktop"


def _read_igpu(config: dict, profile: Profile, notes: list[str]) -> None:
    """Retrouve le framebuffer injecte et le rapproche du catalogue."""
    igpu = profile.platform_data.get("igpu")
    if not igpu:
        return
    props = config.get("DeviceProperties", {}).get("Add", {}).get(igpu["path"])
    if not props:
        return
    raw = props.get(igpu.get("key", "AAPL,ig-platform-id"))
    if not isinstance(raw, bytes):
        return
    value = raw.hex().upper()
    profile.igpu = "igpu"
    if value == (igpu.get("headless") or "").upper():
        profile.igpu_mode = "headless"
    else:
        profile.igpu_mode = "display"
    for name, option in (igpu.get("options") or {}).items():
        if option.upper() == value:
            profile.igpu_variant = name
            break
    else:
        if value not in {(igpu.get("display") or "").upper(),
                         (igpu.get("headless") or "").upper()}:
            notes.append(
                f"framebuffer {value} absent du catalogue pour {profile.platform}: "
                f"il sera remplace par la valeur par defaut, ajoutez-le a la main.")


def _alcid(boot_args: list[str], config: dict, default: int) -> int:
    for arg in boot_args:
        if arg.startswith("alcid="):
            return int(arg.split("=", 1)[1])
    for props in config.get("DeviceProperties", {}).get("Add", {}).values():
        layout = props.get("layout-id")
        if isinstance(layout, int):
            return layout
        if isinstance(layout, bytes) and layout:
            return layout[0]
    return default


def _sip_level(config: dict, notes: list[str]) -> str:
    raw = config.get("NVRAM", {}).get("Add", {}).get(NVRAM_GUID, {}).get("csr-active-config")
    if not isinstance(raw, bytes):
        return "enabled"
    value = raw.hex().upper()
    for name, known in SIP_LEVELS.items():
        if value == known.upper():
            return name
    notes.append(f"csr-active-config {value} non standard: le profil retombe sur "
                 f"--sip enabled, ajustez si besoin.")
    return "enabled"


def _leftover_boot_args(boot_args: list[str], profile: Profile) -> list[str]:
    """Ne garde que les boot-args qu'efibuild ne sait pas regenerer seul."""
    generated = {"-v", "debug=0x100", "keepsyms=1", "revpatch=sbvmm", "-ibtcompatbeta",
                 "agdpmod=pikera", "-wegnoegpu", "-vi2c-force-polling",
                 "-nokcmismatchpanic"}
    generated |= set(profile.platform_data.get("boot_args", []))
    return [a for a in boot_args if a not in generated and not a.startswith("alcid=")]


def _cores_from_amd_patches(config: dict) -> int:
    """Relit le nombre de coeurs inscrit dans le patch cpuid_cores_per_package."""
    for patch in config.get("Kernel", {}).get("Patch", []):
        if "cpuid_cores_per_package" not in patch.get("Comment", ""):
            continue
        replace = patch.get("Replace", b"")
        if len(replace) > 1 and replace[1]:
            return replace[1]
    return 0


def _unmapped_kexts(bundles: set[str]) -> list[str]:
    known = {b for entry in data_files.kexts() for b in entry["bundles"]}
    # Les cartes USB sont gerees par usb_map_kind, pas par le catalogue.
    known |= {"USBMap.kext", "UTBMap.kext"}
    unknown = sorted(bundles - known)
    if not unknown:
        return []
    return [f"kext hors catalogue, il ne sera pas regenere: {name}" for name in unknown]


def _quirk_deltas(config: dict, profile: Profile) -> list[str]:
    """Signale les quirks du config source que la plateforme ne reproduirait pas."""
    deltas = []
    for section, values in profile.platform_data.get("quirks", {}).items():
        source = config.get(section, {}).get("Quirks", {})
        for key, expected in values.items():
            conditional = isinstance(expected, dict) and "value" in expected
            if conditional:
                if not profile.matches(expected.get("when")):
                    if source.get(key):
                        deltas.append(
                            f"{section}.Quirks.{key} est actif dans votre EFI mais la "
                            f"plateforme ne l'active que sous condition: completez le profil "
                            f"(champ 'motherboard_vendor' ou 'chipset') pour le retrouver.")
                    continue
                expected = expected["value"]
            # XhciPortLimit est recalcule au build (toujours faux depuis macOS 11.3).
            if key == "XhciPortLimit" and profile.darwin >= 20:
                continue
            if key in source and source[key] != expected:
                deltas.append(
                    f"{section}.Quirks.{key}: votre EFI a {source[key]}, la plateforme "
                    f"{profile.platform} genererait {expected}.")
    return deltas


def describe(profile: Profile, notes: list[str], source: Path) -> None:
    step(f"Profil deduit de {source}")
    info(f"plateforme  {profile.platform} ({profile.platform_data['name']})")
    info(f"chassis     {profile.chassis}")
    info(f"SMBIOS      {profile.smbios or '(absent)'}")
    info(f"reseau      ethernet={profile.ethernet} wifi={profile.wifi} "
         f"bluetooth={profile.bluetooth}")
    info(f"graphique   igpu={profile.igpu}/{profile.igpu_mode} dgpu={profile.dgpu}")
    info(f"audio       {profile.audio} (alcid={profile.audio_layout})")
    info(f"USB         {profile.usb_map_kind}")
    info(f"fonctions   {', '.join(profile.features) or '(aucune)'}")
    info(f"SIP         {profile.sip}")
    if profile.boot_args:
        info(f"boot-args conserves: {' '.join(profile.boot_args)}")
    if notes:
        print()
        for note in notes:
            warn(note)
