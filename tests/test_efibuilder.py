"""Tests hors ligne des regles de generation (aucun telechargement)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from efibuilder import acpi, configgen, data_files, kexts, smbios, usbmap
from efibuilder.profile import Profile
from efibuilder.util import ascii_comment


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
        self.assertNotIn("VoodooPS2Controller", ids)

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
