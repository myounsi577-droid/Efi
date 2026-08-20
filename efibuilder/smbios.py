"""Generation du PlatformInfo (SMBIOS, numeros de serie, ROM)."""
from __future__ import annotations

import re
import secrets
import subprocess
import uuid
from pathlib import Path

from efibuilder import data_files
from efibuilder.util import BuildError, info, ok, step, warn


def generate_serials(macserial: Path | None, model: str) -> dict:
    """Genere un couple numero de serie / MLB via macserial, plus UUID et ROM."""
    serial = mlb = ""
    if macserial is not None:
        try:
            out = subprocess.run([str(macserial), "-m", model, "-n", "1"],
                                 capture_output=True, text=True, timeout=30, check=False)
            for line in out.stdout.splitlines():
                if "|" in line:
                    serial, mlb = (part.strip() for part in line.split("|", 1))
                    break
        except Exception as exc:  # noqa: BLE001
            warn(f"macserial indisponible ({exc}), numeros de serie a completer a la main")
    if not serial:
        warn("numeros de serie non generes: remplissez SystemSerialNumber / MLB manuellement")
    return {
        "SystemSerialNumber": serial,
        "MLB": mlb,
        "SystemUUID": str(uuid.uuid4()).upper(),
        "ROM": secrets.token_bytes(6),
    }


def platform_info(profile, macserial: Path | None) -> dict:
    """Section PlatformInfo complete du config.plist."""
    step("SMBIOS")
    model = profile.smbios_model
    reference = data_files.smbios_model(model)
    if reference:
        info(f"{model} - {reference['cpu']} / {reference['gpu']} "
             f"(board-id {reference['board_id']}, jusqu'a {reference['last_supported']})")
    else:
        warn(f"{model} absent de la table de reference Dortania")

    generic = {
        "AdviseFeatures": False,
        "MaxBIOSVersion": False,
        "ProcessorType": profile.processor_type,
        "SpoofVendor": True,
        "SystemMemoryStatus": "Auto",
        "SystemProductName": model,
    }
    if profile.serials:
        generic.update(generate_serials(macserial, model))
        ok(f"numeros de serie generes pour {model}")
    else:
        generic.update({"SystemSerialNumber": "", "MLB": "", "SystemUUID": "", "ROM": b""})
        info("generation des numeros de serie desactivee (--no-serials)")

    return {
        "Automatic": True,
        "CustomMemory": False,
        "UpdateDataHub": True,
        "UpdateNVRAM": True,
        "UpdateSMBIOS": True,
        "UpdateSMBIOSMode": "Create",
        "UseRawUuidEncoding": False,
        "Generic": generic,
    }


def check_model_supports(boards: dict, model: str, macos_entry: dict) -> str | None:
    """Verifie avec boards.json d'OpenCorePkg que le SMBIOS recoit cette version."""
    reference = data_files.smbios_model(model)
    if not reference or not boards:
        return None
    value = boards.get(reference["board_id"])
    if value is None:
        return f"board-id {reference['board_id']} absent de boards.json"
    if value == "latest":
        return None
    target = macos_entry["release"]
    if _release_tuple(value) < _release_tuple(target):
        return (f"{model} ne recoit plus les mises a jour au-dela de macOS {value}; "
                f"{macos_entry['name']} ne sera pas propose en recovery avec ce board-id")
    return None


def _release_tuple(value: str) -> tuple[int, ...]:
    parts = [int(p) for p in re.findall(r"\d+", value)]
    return tuple(parts[:2] if parts and parts[0] == 10 else parts[:1])


def models_for_macos(boards: dict, macos_entry: dict) -> list[str]:
    """Liste des SMBIOS capables de recevoir la version demandee."""
    result = []
    for entry in data_files.smbios_models():
        value = boards.get(entry["board_id"])
        if value == "latest" or (value and _release_tuple(value) >= _release_tuple(macos_entry["release"])):
            result.append(entry["model"])
    return result
