"""Selection et recuperation des SSDT prets a l'emploi de Dortania."""
from __future__ import annotations

import shutil
from pathlib import Path

from efibuilder.net import Downloader
from efibuilder.util import ascii_comment, info, ok, step, warn

ACPI_REPO = "dortania/Getting-Started-With-ACPI"
ACPI_PATH = "extra-files/compiled"

# Renommage _OSI -> XOSI, indissociable de SSDT-XOSI.
XOSI_PATCH = {
    "Base": "",
    "BaseSkip": 0,
    "Comment": "Change _OSI to XOSI (requis par SSDT-XOSI)",
    "Count": 0,
    "Enabled": True,
    "Find": bytes.fromhex("5F4F5349"),
    "Limit": 0,
    "Mask": b"",
    "OemTableId": b"",
    "Replace": bytes.fromhex("584F5349"),
    "ReplaceMask": b"",
    "Skip": 0,
    "TableLength": 0,
    "TableSignature": b"",
}


def select_ssdts(profile) -> list[dict]:
    """Retourne les SSDT retenus pour ce profil, avec la raison de chacun."""
    selected = []
    for entry in profile.platform_data.get("ssdt", []):
        if not profile.matches(entry.get("when")):
            continue
        selected.append(entry)
    return selected


def install_ssdts(profile, dl: Downloader, acpi_dir: Path) -> list[dict]:
    """Telecharge les .aml choisis et retourne les entrees ACPI -> Add."""
    step("ACPI / SSDT")
    entries = []
    for entry in select_ssdts(profile):
        name = entry["file"]
        try:
            src = dl.github_raw(ACPI_REPO, f"{ACPI_PATH}/{name}")
        except Exception as exc:  # noqa: BLE001
            warn(f"{name} non telecharge ({exc})")
            continue
        shutil.copy2(src, acpi_dir / name)
        info(f"{name} - {entry.get('reason', '')}")
        entries.append({
            "Comment": ascii_comment(entry.get("reason", name)),
            "Enabled": True,
            "Path": name,
        })
    if not entries:
        warn("aucun SSDT selectionne pour cette plateforme")
    else:
        ok(f"{len(entries)} SSDT installes dans {acpi_dir}")
    return entries


def acpi_patches(profile) -> list[dict]:
    """Patches ACPI implicites (aujourd'hui: _OSI -> XOSI)."""
    names = {e["file"] for e in select_ssdts(profile)}
    return [dict(XOSI_PATCH)] if "SSDT-XOSI.aml" in names else []
