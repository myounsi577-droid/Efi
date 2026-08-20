"""Construction d'une USBMap.kext a partir d'une description de ports."""
from __future__ import annotations

import json
import plistlib
import shutil
import struct
from pathlib import Path

from efibuilder.util import BuildError, info, ok, step, warn

# Valeurs UsbConnector de la specification ACPI, telles qu'utilisees par macOS.
CONNECTOR_TYPES = {
    0: "USB 2.0 Type-A",
    3: "USB 3.0 Type-A",
    8: "Type-C avec inversion (switch)",
    9: "Type-C sans inversion",
    10: "interne (carte Bluetooth, webcam, lecteur d'empreintes...)",
    255: "interne proprietaire",
}

TEMPLATE = {
    "_aide": [
        "Un port par entree. address = numero de port renvoye par IORegistry",
        "(macOS), USBToolBox (Windows) ou Hackintool. type = UsbConnector:",
        "0 USB2 Type-A, 3 USB3 Type-A, 8/9 Type-C, 10 interne (Bluetooth, webcam).",
        "macOS n'accepte que 15 ports par controleur: supprimez les ports inutilises.",
    ],
    "model": "iMac19,1",
    "controllers": [
        {
            "name": "XHC",
            "comment": "Controleur XHCI de la carte mere",
            "vendor_id": "8086",
            "device_id": "A36D",
            "ports": [
                {"name": "HS01", "address": 1, "type": 0, "comment": "USB2 arriere haut"},
                {"name": "HS02", "address": 2, "type": 0, "comment": "USB2 arriere bas"},
                {"name": "SS01", "address": 17, "type": 3, "comment": "USB3 arriere haut"},
                {"name": "HS10", "address": 10, "type": 10, "comment": "Bluetooth interne"},
            ],
        }
    ],
}


def write_template(path: Path) -> None:
    path.write_text(json.dumps(TEMPLATE, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok(f"modele ecrit dans {path}")
    info("Relevez vos ports avec USBToolBox (Windows), Hackintool ou IORegistryExplorer (macOS),")
    info("puis completez ce fichier et relancez 'efibuild usbmap build'.")


def _le32(value: int) -> bytes:
    return struct.pack("<I", value)


def build_usbmap(spec: dict, dest_dir: Path, bundle_name: str = "USBMap.kext") -> Path:
    """Genere une USBMap.kext (kext sans binaire, uniquement un Info.plist)."""
    step("USBMap")
    model = spec.get("model") or ""
    controllers = spec.get("controllers") or []
    if not controllers:
        raise BuildError("aucun controleur dans la description USB")

    personalities: dict[str, dict] = {}
    for controller in controllers:
        name = controller["name"]
        ports_out: dict[str, dict] = {}
        highest = 0
        for port in controller.get("ports", []):
            address = int(port["address"])
            highest = max(highest, address)
            entry = {
                "UsbConnector": int(port.get("type", 0)),
                "port": _le32(address),
            }
            if port.get("comment"):
                entry["#comment"] = port["comment"]
            ports_out[port["name"]] = entry
        if len(ports_out) > 15:
            warn(f"{name}: {len(ports_out)} ports declares, macOS n'en gere que 15")
        personality = {
            "CFBundleIdentifier": "com.apple.driver.AppleUSBHostMergeProperties",
            "IOClass": "AppleUSBHostMergeProperties",
            "IOProviderClass": "AppleUSBHostController",
            "IONameMatch": name,
            "IOProviderMergeProperties": {
                "port-count": _le32(highest),
                "ports": ports_out,
            },
        }
        if model:
            personality["model"] = model
        vendor, device = controller.get("vendor_id"), controller.get("device_id")
        if vendor and device:
            personality["IOParentMatch"] = {
                "IOPropertyMatch": {
                    "device-id": _le32(int(device, 16)),
                    "vendor-id": _le32(int(vendor, 16)),
                }
            }
        personalities[name] = personality
        info(f"{name}: {len(ports_out)} ports, port-count={highest}")

    info_plist = {
        "CFBundleDevelopmentRegion": "English",
        "CFBundleGetInfoString": "USBMap generee par efibuild",
        "CFBundleIdentifier": "com.efibuild.USBMap",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "USBMap",
        "CFBundlePackageType": "KEXT",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleSignature": "????",
        "CFBundleVersion": "1.0.0",
        "IOKitPersonalities": personalities,
        "OSBundleRequired": "Root",
    }
    bundle = dest_dir / bundle_name
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "Contents").mkdir(parents=True)
    with open(bundle / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump(info_plist, fh, sort_keys=True)
    ok(f"{bundle_name} generee dans {dest_dir}")
    return bundle


def load_spec(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "controllers" not in data:
        raise BuildError(f"{path}: cle 'controllers' manquante")
    return data


def import_existing(source: Path, dest_dir: Path) -> Path:
    """Copie une UTBMap.kext/USBMap.kext existante (sortie de USBToolBox)."""
    source = Path(source)
    if source.is_dir() and source.suffix == ".kext":
        target = dest_dir / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        ok(f"{source.name} importee")
        return target
    if source.suffix == ".plist":
        # UserUSBMap.plist de USBToolBox: on l'emballe dans UTBMap.kext.
        with open(source, "rb") as fh:
            personalities = plistlib.load(fh)
        bundle = dest_dir / "UTBMap.kext"
        if bundle.exists():
            shutil.rmtree(bundle)
        (bundle / "Contents").mkdir(parents=True)
        with open(bundle / "Contents" / "Info.plist", "wb") as fh:
            plistlib.dump({
                "CFBundleIdentifier": "com.efibuild.UTBMap",
                "CFBundleName": "UTBMap",
                "CFBundlePackageType": "KEXT",
                "CFBundleShortVersionString": "1.0.0",
                "CFBundleVersion": "1.0.0",
                "IOKitPersonalities": personalities,
                "OSBundleRequired": "Root",
            }, fh, sort_keys=True)
        ok("UTBMap.kext generee depuis UserUSBMap.plist")
        return bundle
    raise BuildError(f"format non reconnu: {source} (attendu: .kext ou UserUSBMap.plist)")
