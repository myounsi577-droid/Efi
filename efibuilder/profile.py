"""Profil materiel: description de la machine cible + evaluation des conditions."""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from efibuilder import data_files
from efibuilder.util import BuildError

ETHERNET_CHOICES = [
    "auto", "none", "intel-i219", "intel-i218", "intel-i217", "intel-mausi",
    "intel-igb", "intel-i210", "intel-i211", "intel-i225", "rtl8111", "rtl8125",
    "atheros", "killer",
]
WIFI_CHOICES = ["none", "intel", "broadcom"]
BLUETOOTH_CHOICES = ["none", "intel", "broadcom"]
TOUCHPAD_CHOICES = ["none", "ps2", "i2c"]
DGPU_CHOICES = [
    "none", "amd-polaris", "amd-vega", "amd-navi", "amd-rdna2", "amd-apu",
    "nvidia-kepler", "nvidia-unsupported",
]
FEATURE_CHOICES = [
    "ota", "sidecar", "hibernation", "cpufriend", "light-sensor", "rtc-fix",
    "no-avx2", "gui", "audio-chime", "linux-boot", "windows-boot",
]


@dataclass
class Profile:
    """Tout ce que l'on sait de la machine, serialisable en JSON."""

    platform: str
    macos: str = "sequoia"
    name: str = "Mon PC"
    chipset: str = ""                 # z390, b550, hm370...
    motherboard_vendor: str = ""      # asus, gigabyte, msi, asrock, dell, hp, lenovo
    cpu_name: str = ""
    cpu_generation: str = ""          # 8, 9, 10... (utile pour SSDT-PMC sur portable)
    cpu_cores: int = 0                # coeurs physiques (patch AMD cpuid_cores_per_package)
    igpu: str = "none"                # uhd630, hd4600, none
    igpu_mode: str = "display"        # display | headless | none
    igpu_variant: str = ""            # cle de platforms.json -> igpu.options
    dgpu: str = "none"
    audio: str = "alc"                # alc | none
    audio_layout: int = 1
    ethernet: str = "auto"
    wifi: str = "none"
    bluetooth: str = "none"
    touchpad: str = "none"
    nvme: bool = True
    smbios: str = ""                  # vide = valeur recommandee par la plateforme
    serials: bool = True              # generer numero de serie / MLB / UUID
    usb_map_kind: str = "none"        # none | usbtoolbox | usbmap
    usb_map_file: str = ""            # UserUSBMap.plist ou USBMap JSON
    features: list[str] = field(default_factory=lambda: ["ota"])
    boot_args: list[str] = field(default_factory=list)
    debug: bool = False
    oc_version: str = "latest"
    cpuid_data: str = ""              # spoof CPUID (ex. Rocket Lake vers Comet Lake)
    cpuid_mask: str = ""

    def __post_init__(self) -> None:
        # Coherence de base: pas d'iGPU declare => pas de framebuffer a injecter.
        if self.igpu == "none":
            self.igpu_mode = "none"
        elif self.igpu_mode == "none":
            self.igpu = "none"

    # --------------------------------------------------------------- helpers
    @property
    def platform_data(self) -> dict:
        return data_files.platform(self.platform)

    @property
    def macos_data(self) -> dict:
        return data_files.macos(self.macos)

    @property
    def family(self) -> str:
        return self.platform_data["family"]

    @property
    def laptop(self) -> bool:
        return self.family == "intel-laptop"

    @property
    def darwin(self) -> int:
        return self.macos_data["darwin"]

    @property
    def chipset_series(self) -> str:
        """'6', '7', '300', '400'... deduit du nom de chipset (z390 -> 300)."""
        match = re.search(r"(\d+)", self.chipset or "")
        if not match:
            return ""
        digits = match.group(1)
        if len(digits) == 2:      # z77, h61
            return digits[0]
        if len(digits) == 3:      # z390, b550
            return digits[0] + "00"
        return digits

    @property
    def smbios_model(self) -> str:
        return self.smbios or self.platform_data["smbios"]["default"]

    def field_value(self, name: str):
        if name in {"family", "laptop", "darwin", "chipset_series", "smbios_model"}:
            return getattr(self, name)
        if hasattr(self, name):
            return getattr(self, name)
        raise BuildError(f"champ de condition inconnu: {name}")

    # ------------------------------------------------------------ conditions
    def matches(self, condition: dict | None) -> bool:
        """Evalue une condition de platforms.json / kexts.json."""
        if not condition:
            return True
        if "any" in condition:
            return any(self.matches(c) for c in condition["any"])
        if "all" in condition:
            return all(self.matches(c) for c in condition["all"])
        if "not" in condition:
            return not self.matches(condition["not"])
        value = self.field_value(condition["field"])
        if "eq" in condition:
            return value == condition["eq"]
        if "in" in condition:
            if isinstance(value, str):
                return value.lower() in [str(v).lower() for v in condition["in"]]
            return value in condition["in"]
        if "contains" in condition:
            return condition["contains"] in (value or [])
        raise BuildError(f"condition mal formee: {condition}")

    # ---------------------------------------------------------- (de)ser./val.
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Profile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise BuildError(f"champs inconnus dans {path}: {', '.join(sorted(unknown))}")
        return cls(**data)

    def validate(self) -> list[str]:
        """Retourne la liste des avertissements (les erreurs levent BuildError)."""
        warnings: list[str] = []
        plat = self.platform_data
        target = self.macos_data
        versions = [v["key"] for v in data_files.macos_versions()]
        idx = versions.index(target["key"])

        max_macos = plat.get("max_macos")
        if max_macos and idx > versions.index(max_macos):
            warnings.append(
                f"{plat['name']} n'est plus supporte au-dela de "
                f"{data_files.macos(max_macos)['name']} par le guide Dortania.")
        min_macos = plat.get("min_macos")
        if min_macos and idx < versions.index(min_macos):
            warnings.append(
                f"{plat['name']} demande au minimum {data_files.macos(min_macos)['name']}.")

        model = data_files.smbios_model(self.smbios_model)
        if model is None:
            warnings.append(f"SMBIOS {self.smbios_model} absent de la table de reference.")
        else:
            supported = _smbios_supports(model["board_id"], target)
            if supported is False:
                served = (_BOARDS_CACHE.get("boards") or data_files.boards()).get(
                    model["board_id"], "?")
                warnings.append(
                    f"le SMBIOS {model['model']} ne recoit pas {target['name']}: les serveurs "
                    f"Apple s'arretent a macOS {served} pour ce board-id. "
                    f"Choisissez-en un autre ('efibuild list smbios --macos "
                    f"{target['key']}').")

        if self.family == "amd" and self.cpu_cores <= 0:
            warnings.append(
                "nombre de coeurs inconnu: le patch AMD 'cpuid_cores_per_package' "
                "restera sur sa valeur par defaut, a corriger avant de demarrer "
                "(option --cores).")
        if self.igpu_mode == "display" and self.igpu == "none":
            warnings.append("igpu_mode=display alors qu'aucun iGPU n'est declare.")
        if self.usb_map_kind == "none" and self.darwin >= 20:
            warnings.append(
                "aucun mappage USB: XhciPortLimit n'est plus fiable a partir de macOS 11.3, "
                "generez une USBMap.kext (commande 'efibuild usbmap').")
        return warnings


def _smbios_supports(board_id: str, target: dict) -> bool | None:
    """Utilise boards.json d'OpenCorePkg (snapshot embarque ou release en cours)."""
    table = _BOARDS_CACHE.get("boards") or data_files.boards()
    if not table:
        return None
    value = table.get(board_id)
    if value is None:
        return None
    if value == "latest":
        return True
    major = float(value.split(".")[0]) if not value.startswith("10.") else 10
    release = target["release"]
    want = float(release.split(".")[0]) if not release.startswith("10.") else 10
    if want == 10 and major == 10:
        return float(value.split(".")[1]) >= float(release.split(".")[1])
    return major >= want


_BOARDS_CACHE: dict[str, dict] = {}


def set_boards_table(table: dict) -> None:
    """Renseigne boards.json (fourni par OpenCorePkg) pour la validation SMBIOS."""
    _BOARDS_CACHE["boards"] = table
