"""Tests hors ligne des regles de generation (aucun telechargement)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from efibuilder import (acpi, configgen, data_files, importer, kexts, menu,
                        smbios, usbflash, usbmap)
from efibuilder.profile import Profile
from efibuilder.util import BuildError, ascii_comment


def ssdt_names(profile: Profile) -> list[str]:
    return [entry["file"] for entry in acpi.select_ssdts(profile)]


def kext_ids(profile: Profile) -> list[str]:
    return [entry["id"] for entry in kexts.select_kexts(profile)[0]]


class ConditionTests(unittest.TestCase):
    def test_chipset_series_deduction(self):
        self.assertEqual(Profile(platform="coffee-lake-desktop", chipset="Z390").chipset_series, "300")
        self.assertEqual(Profile(platform="ivy-bridge-desktop", chipset="H61").chipset_series, "6")
        self.assertEqual(Profile(platform="ivy-bridge-desktop", chipset="").chipset_series, "")

    def test_conditions(self):
        profile = Profile(platform="comet-lake-desktop", motherboard_vendor="Asus")
        self.assertTrue(profile.matches({"field": "motherboard_vendor", "in": ["asus"]}))
        self.assertFalse(profile.matches({"not": {"field": "motherboard_vendor", "in": ["asus"]}}))
        self.assertTrue(profile.matches(None))


class AcpiTests(unittest.TestCase):
    def test_pmc_only_on_true_300_series(self):
        z390 = Profile(platform="coffee-lake-desktop", chipset="z390")
        z370 = Profile(platform="coffee-lake-desktop", chipset="z370")
        self.assertIn("SSDT-PMC.aml", ssdt_names(z390))
        self.assertNotIn("SSDT-PMC.aml", ssdt_names(z370))

    def test_rhub_only_on_asus_400(self):
        asus = Profile(platform="comet-lake-desktop", motherboard_vendor="asus")
        giga = Profile(platform="comet-lake-desktop", motherboard_vendor="gigabyte")
        self.assertIn("SSDT-RHUB.aml", ssdt_names(asus))
        self.assertNotIn("SSDT-RHUB.aml", ssdt_names(giga))

    def test_xosi_patch_follows_xosi_ssdt(self):
        laptop = Profile(platform="skylake-laptop")
        desktop = Profile(platform="skylake-desktop")
        self.assertEqual(len(acpi.acpi_patches(laptop)), 1)
        self.assertEqual(acpi.acpi_patches(laptop)[0]["Find"], bytes.fromhex("5F4F5349"))
        self.assertEqual(acpi.acpi_patches(desktop), [])

    def test_cpur_only_on_b550_and_newer(self):
        b550 = Profile(platform="amd-zen", chipset="b550")
        x570 = Profile(platform="amd-zen", chipset="x570")
        self.assertIn("SSDT-CPUR.aml", ssdt_names(b550))
        self.assertNotIn("SSDT-CPUR.aml", ssdt_names(x570))


class KextTests(unittest.TestCase):
    def test_amd_has_no_intel_cpu_sensor(self):
        amd = Profile(platform="amd-zen", chipset="b550", cpu_cores=8)
        self.assertNotIn("SMCProcessor", kext_ids(amd))
        self.assertIn("RestrictEvents", kext_ids(amd))

    def test_laptop_gets_battery_and_ec(self):
        laptop = Profile(platform="kaby-lake-laptop", touchpad="i2c")
        ids = kext_ids(laptop)
        self.assertIn("SMCBatteryManager", ids)
        self.assertIn("ECEnabler", ids)
        self.assertIn("VoodooI2C", ids)
        # Le clavier d'un portable reste en PS2 meme avec un trackpad I2C.
        self.assertIn("VoodooPS2Controller", ids)

    def test_broadcom_wifi_dropped_after_ventura(self):
        ventura = Profile(platform="coffee-lake-desktop", macos="ventura", wifi="broadcom")
        sonoma = Profile(platform="coffee-lake-desktop", macos="sonoma", wifi="broadcom")
        self.assertIn("AirportBrcmFixup", kext_ids(ventura))
        self.assertNotIn("AirportBrcmFixup", kext_ids(sonoma))
        self.assertTrue(any("AirportBrcmFixup" in w for w in kexts.select_kexts(sonoma)[1]))

    def test_bluetooth_fixup_requires_big_sur(self):
        catalina = Profile(platform="coffee-lake-desktop", macos="catalina", bluetooth="intel")
        sequoia = Profile(platform="coffee-lake-desktop", macos="sequoia", bluetooth="intel")
        self.assertNotIn("BlueToolFixup", kext_ids(catalina))
        self.assertIn("BlueToolFixup", kext_ids(sequoia))

    def test_itlwm_build_matches_target_macos(self):
        profile = Profile(platform="coffee-lake-desktop", macos="tahoe", wifi="intel")
        entry = next(e for e in kexts.select_kexts(profile)[0] if e["id"] == "AirportItlwm")
        self.assertIn("Tahoe", entry["asset_by_macos"]["tahoe"])


class BootArgTests(unittest.TestCase):
    def test_ota_boot_arg_only_from_sonoma(self):
        sonoma = Profile(platform="coffee-lake-desktop", macos="sonoma", features=["ota"])
        ventura = Profile(platform="coffee-lake-desktop", macos="ventura", features=["ota"])
        self.assertIn("revpatch=sbvmm", configgen._boot_args(sonoma))
        self.assertNotIn("revpatch=sbvmm", configgen._boot_args(ventura))

    def test_intel_bluetooth_boot_arg_on_tahoe(self):
        tahoe = Profile(platform="coffee-lake-desktop", macos="tahoe", bluetooth="intel")
        sequoia = Profile(platform="coffee-lake-desktop", macos="sequoia", bluetooth="intel")
        self.assertIn("-ibtcompatbeta", configgen._boot_args(tahoe))
        self.assertNotIn("-ibtcompatbeta", configgen._boot_args(sequoia))

    def test_navi_gets_agdpmod(self):
        profile = Profile(platform="coffee-lake-desktop", dgpu="amd-navi")
        self.assertIn("agdpmod=pikera", configgen._boot_args(profile))


class SmbiosTests(unittest.TestCase):
    def test_tahoe_models(self):
        models = smbios.models_for_macos(data_files.boards(), data_files.macos("tahoe"))
        self.assertEqual(sorted(models), sorted([
            "MacBookPro16,1", "MacBookPro16,2", "MacBookPro16,4",
            "MacPro7,1", "iMac20,1", "iMac20,2"]))

    def test_warning_when_model_too_old(self):
        profile = Profile(platform="coffee-lake-desktop", macos="tahoe", chipset="z390")
        self.assertTrue(any("ne recoit pas" in w for w in profile.validate()))


class CompatibilityTests(unittest.TestCase):
    def test_amd_laptop_is_warned_not_blocked(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2)
        self.assertEqual(profile.blockers(), [])
        self.assertTrue(any("portable AMD" in w for w in profile.validate()))

    def test_amd_laptop_platform_uses_nootedred_instead_of_weg(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2, igpu="vega3")
        ids = kext_ids(profile)
        self.assertIn("NootedRed", ids)
        self.assertNotIn("WhateverGreen", ids)

    def test_amd_desktop_with_dgpu_keeps_weg(self):
        profile = Profile(platform="amd-zen", chipset="b550", cpu_cores=8, dgpu="amd-navi")
        ids = kext_ids(profile)
        self.assertIn("WhateverGreen", ids)
        self.assertNotIn("NootedRed", ids)

    def test_amd_uses_forged_invariant_not_cputscsync(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2)
        ids = kext_ids(profile)
        self.assertIn("ForgedInvariant", ids)
        self.assertNotIn("CpuTscSync", ids)

    def test_manual_kexts_are_reported_not_downloaded(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2, wifi="realtek")
        entry = next(e for e in kexts.select_kexts(profile)[0] if e["id"] == "rtw88")
        self.assertTrue(entry["manual"])
        self.assertIn("Feixiao", entry["source"])

    def test_realtek_wifi_points_at_community_driver(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2, wifi="realtek")
        self.assertTrue(any("rtw88" in w for w in profile.validate()))

    def test_hp_gets_unblockfsconnect(self):
        hp = Profile(platform="amd-zen-laptop", motherboard_vendor="hp")
        other = Profile(platform="amd-zen-laptop", motherboard_vendor="lenovo")
        quirk = hp.platform_data["quirks"]["UEFI"]["UnblockFsConnect"]
        self.assertTrue(hp.matches(quirk["when"]))
        self.assertFalse(other.matches(quirk["when"]))

    def test_amd_desktop_is_not_blocked(self):
        profile = Profile(platform="amd-zen", chassis="desktop", cpu_cores=8)
        self.assertEqual(profile.blockers(), [])

    def test_chassis_overrides_family_detection(self):
        self.assertTrue(Profile(platform="amd-zen", chassis="laptop").laptop)
        self.assertFalse(Profile(platform="kaby-lake-laptop", chassis="desktop").laptop)

    def test_amd_laptop_still_gets_battery_kexts(self):
        profile = Profile(platform="amd-zen-laptop", cpu_cores=2)
        self.assertIn("SMCBatteryManager", kext_ids(profile))

    def test_realtek_wifi_is_flagged(self):
        profile = Profile(platform="coffee-lake-desktop", wifi="realtek")
        self.assertTrue(any("Realtek" in w for w in profile.validate()))
        self.assertEqual(profile.blockers(), [])

    def test_pre_haswell_blocked_on_ventura(self):
        profile = Profile(platform="ivy-bridge-desktop", macos="ventura")
        self.assertTrue(any("AVX2" in b for b in profile.blockers()))


def amd_laptop_config() -> dict:
    """Config minimal representatif d'un portable AMD a APU Vega."""
    return {
        "ACPI": {"Add": [{"Path": "SSDT-PNLF.aml", "Enabled": True}]},
        "Kernel": {
            "Add": [{"BundlePath": n, "Enabled": True} for n in (
                "Lilu.kext", "NootedRed.kext", "VirtualSMC.kext", "SMCBatteryManager.kext",
                "VoodooI2C.kext", "RealtekRTL8111.kext", "rtw88.kext", "UTBMap.kext",
                "RestrictEvents.kext", "SMCLightSensor.kext", "MonKextInconnu.kext")],
            "Patch": [{"Comment": "algrey | Force cpuid_cores_per_package to constant",
                       "Replace": bytes.fromhex("ba06000000")}],
            "Quirks": {"LapicKernelPanic": True, "DisableRtcChecksum": True},
        },
        "UEFI": {"Drivers": [{"Path": "OpenCanopy.efi"}], "Quirks": {}},
        "Booter": {"Quirks": {}},
        "DeviceProperties": {"Add": {"PciRoot(0x0)/Pci(0x8,0x1)/Pci(0x0,0x6)":
                                     {"layout-id": 55}}},
        "PlatformInfo": {"UpdateSMBIOSMode": "Custom",
                         "Generic": {"SystemProductName": "MacBookPro16,2",
                                     "ProcessorType": 1537,
                                     "SystemSerialNumber": "C02XXXXXXXXX"}},
        "NVRAM": {"Add": {importer.NVRAM_GUID: {
            "boot-args": "-vi2c-force-polling npci=0x3000",
            "csr-active-config": bytes.fromhex("030A0000")}}},
    }


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.notes = importer.import_profile(amd_laptop_config())

    def test_platform_and_chassis(self):
        self.assertEqual(self.profile.platform, "amd-zen-laptop")
        self.assertEqual(self.profile.chassis, "laptop")

    def test_core_count_read_from_amd_patch(self):
        self.assertEqual(self.profile.cpu_cores, 6)

    def test_hardware_from_kexts(self):
        self.assertEqual(self.profile.ethernet, "rtl8111")
        self.assertEqual(self.profile.wifi, "realtek")
        self.assertEqual(self.profile.touchpad, "i2c")
        self.assertEqual(self.profile.usb_map_kind, "usbtoolbox")

    def test_smbios_and_processor_type(self):
        self.assertEqual(self.profile.smbios, "MacBookPro16,2")
        self.assertEqual(self.profile.processor_type, 1537)

    def test_audio_layout_from_device_properties(self):
        self.assertEqual(self.profile.audio_layout, 55)

    def test_sip_level(self):
        self.assertEqual(self.profile.sip, "partial")

    def test_features(self):
        for feature in ("custom-smbios", "gui", "i2c-polling", "light-sensor", "ota"):
            self.assertIn(feature, self.profile.features)

    def test_unknown_kext_is_reported_but_usb_map_is_not(self):
        joined = " ".join(self.notes)
        self.assertIn("MonKextInconnu.kext", joined)
        self.assertNotIn("UTBMap.kext n", joined)

    def test_generated_boot_args_are_not_duplicated(self):
        self.assertEqual(self.profile.boot_args, [])


class UsbMapTests(unittest.TestCase):
    def test_generated_kext(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = usbmap.build_usbmap(usbmap.TEMPLATE, Path(tmp))
            import plistlib
            with open(bundle / "Contents" / "Info.plist", "rb") as fh:
                data = plistlib.load(fh)
            xhc = data["IOKitPersonalities"]["XHC"]
            self.assertEqual(xhc["IOClass"], "AppleUSBHostMergeProperties")
            self.assertEqual(xhc["IOProviderMergeProperties"]["port-count"],
                             bytes.fromhex("11000000"))
            self.assertEqual(
                xhc["IOParentMatch"]["IOPropertyMatch"]["vendor-id"],
                bytes.fromhex("86800000"))


def fake_key(mountpoints=()) -> usbflash.UsbDevice:
    return usbflash.UsbDevice("/dev/sdz", "Cle de test", 8 * 1024**3, "usb",
                              removable=True, system=False, mountpoints=list(mountpoints))


class UsbSafetyTests(unittest.TestCase):
    def test_removable_key_is_accepted(self):
        self.assertIsNone(fake_key().safety_problem())

    def test_system_disk_is_refused(self):
        disk = fake_key()
        disk.system = True
        self.assertIn("systeme", disk.safety_problem())

    def test_internal_disk_is_refused(self):
        disk = fake_key()
        disk.removable = False
        self.assertIn("amovible", disk.safety_problem())

    def test_oversized_disk_is_refused(self):
        disk = fake_key()
        disk.size = 2 * 1024**4
        self.assertIn("inhabituelle", disk.safety_problem())

    def test_format_commands_per_system(self):
        original = usbflash.SYSTEM
        try:
            for system, expected in (("Darwin", "diskutil"), ("Linux", "mkfs.vfat"),
                                     ("Windows", "diskpart")):
                usbflash.SYSTEM = system
                joined = " ".join(" ".join(c) for c in usbflash.format_commands(fake_key()))
                self.assertIn(expected, joined)
        finally:
            usbflash.SYSTEM = original

    def test_windows_refuses_fat32_above_32gb(self):
        original = usbflash.SYSTEM
        usbflash.SYSTEM = "Windows"
        try:
            big = fake_key()
            big.size = 64 * 1024**3
            with self.assertRaises(BuildError):
                usbflash.format_device(big, dry_run=True)
        finally:
            usbflash.SYSTEM = original

    def test_backup_archives_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "CLE"
            (root / "sub").mkdir(parents=True)
            (root / "a.txt").write_text("donnees")
            (root / "sub" / "b.bin").write_bytes(b"\x00" * 16)
            archive = usbflash.backup_device(fake_key([str(root)]), Path(tmp) / "dl")
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(sorted(zf.namelist()), ["CLE/a.txt", "CLE/sub/b.bin"])

    def test_backup_without_mountpoint_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(usbflash.backup_device(fake_key(), Path(tmp)))

    def test_copy_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            efi = Path(tmp) / "EFI" / "OC"
            efi.mkdir(parents=True)
            (efi / "config.plist").write_text("<plist/>")
            mount = Path(tmp) / "mount"
            mount.mkdir()
            usbflash.copy_payload(mount, Path(tmp) / "EFI", None)
            self.assertTrue((mount / "EFI" / "OC" / "config.plist").exists())


class ZipappTests(unittest.TestCase):
    """Le .pyz distribue doit savoir lire ses tables JSON depuis l'archive."""

    def test_zipapp_runs_and_reads_data(self):
        import subprocess
        import sys
        import zipapp

        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp) / "src"
            shutil.copytree(root / "efibuilder", staging / "efibuilder",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (staging / "__main__.py").write_text(
                "import sys\nfrom efibuilder.cli import main\n"
                "sys.exit(main())\n", encoding="utf-8")
            pyz = Path(tmp) / "efibuild.pyz"
            zipapp.create_archive(staging, pyz, compressed=True)
            result = subprocess.run([sys.executable, str(pyz), "list", "macos"],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("tahoe", result.stdout)
            self.assertIn("sequoia", result.stdout)


class MenuTests(unittest.TestCase):
    def _with_input(self, answers, call):
        import builtins
        original = builtins.input
        queue = list(answers)
        builtins.input = lambda *a, **k: queue.pop(0)
        try:
            return call()
        finally:
            builtins.input = original

    def test_choose_returns_index(self):
        options = [("a", ""), ("b", ""), ("c", "")]
        self.assertEqual(self._with_input(["2"], lambda: menu.choose("t", options)), 2)

    def test_choose_uses_default_on_empty_input(self):
        options = [("a", ""), ("b", "")]
        self.assertEqual(
            self._with_input([""], lambda: menu.choose("t", options, default=2)), 2)

    def test_choose_rejects_out_of_range_then_accepts(self):
        options = [("a", ""), ("b", "")]
        self.assertEqual(self._with_input(["9", "x", "1"],
                                          lambda: menu.choose("t", options)), 1)

    def test_zero_cancels(self):
        with self.assertRaises(menu.Cancelled):
            self._with_input(["0"], lambda: menu.choose("t", [("a", "")]))

    def test_pick_returns_value(self):
        self.assertEqual(
            self._with_input(["3"], lambda: menu.pick("t", ["x", "y", "z"], "x")), "z")


class ProfileTests(unittest.TestCase):
    def test_roundtrip(self):
        profile = Profile(platform="amd-zen", chipset="b550", cpu_cores=6, macos="sequoia")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            profile.save(path)
            self.assertEqual(Profile.load(path).to_dict(), profile.to_dict())

    def test_igpu_normalisation(self):
        self.assertEqual(Profile(platform="coffee-lake-desktop").igpu_mode, "none")


class UtilTests(unittest.TestCase):
    def test_ascii_comment(self):
        self.assertEqual(ascii_comment("acceleration reglee a 100%"),
                         "acceleration reglee a 100%")
        self.assertEqual(ascii_comment("accélération"), "acceleration")


class DataIntegrityTests(unittest.TestCase):
    def test_every_platform_has_a_valid_smbios(self):
        for entry in data_files.platforms():
            model = entry["smbios"]["default"]
            self.assertIsNotNone(data_files.smbios_model(model),
                                 f"{entry['id']}: SMBIOS {model} inconnu")

    def test_every_kext_reason_is_ascii(self):
        for entry in data_files.kexts():
            reason = entry.get("reason", "")
            self.assertEqual(reason, ascii_comment(reason), entry["id"])

    def test_every_ssdt_reason_is_ascii(self):
        for entry in data_files.platforms():
            for ssdt in entry.get("ssdt", []):
                reason = ssdt.get("reason", "")
                self.assertEqual(reason, ascii_comment(reason), ssdt["file"])


if __name__ == "__main__":
    unittest.main()
