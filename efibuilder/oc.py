"""Recuperation d'OpenCorePkg et construction du squelette EFI."""
from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from efibuilder.net import Downloader, Resolved
from efibuilder.util import BuildError, info, ok, step, warn

OPENCORE_REPO = "acidanthera/OpenCorePkg"
OPENCORE_ASSET = r"^OpenCore-[0-9.]+-RELEASE\.zip$"
OCBINARYDATA = "acidanthera/OcBinaryData"

# Pilotes UEFI conserves selon le profil. La regle Dortania: on ne garde que
# le strict necessaire, tout pilote inutile est une source de plantage.
BASE_DRIVERS = ["OpenRuntime.efi"]
OPTIONAL_DRIVERS = {
    "gui": ["OpenCanopy.efi"],
    "audio-chime": ["AudioDxe.efi"],
    "linux-boot": ["OpenLinuxBoot.efi", "Ext4Dxe.efi"],
    "reset-nvram": ["ResetNvramEntry.efi"],
    "toggle-sip": ["ToggleSipEntry.efi"],
}


@dataclass
class OpenCorePackage:
    root: Path            # racine du zip extrait
    version: str
    resolved: Resolved

    @property
    def efi_x64(self) -> Path:
        return self.root / "X64" / "EFI"

    @property
    def sample_plist(self) -> Path:
        return self.root / "Docs" / "Sample.plist"

    @property
    def utilities(self) -> Path:
        return self.root / "Utilities"

    @property
    def macrecovery(self) -> Path:
        return self.utilities / "macrecovery" / "macrecovery.py"

    @property
    def boards_json(self) -> Path:
        return self.utilities / "macrecovery" / "boards.json"

    def boards(self) -> dict:
        if self.boards_json.exists():
            return json.loads(self.boards_json.read_text(encoding="utf-8"))
        return {}

    def tool(self, name: str) -> Path | None:
        """Retourne le binaire ocvalidate/macserial adapte a l'hote."""
        import platform as _platform

        system = _platform.system()
        suffix = {"Linux": ".linux", "Windows": ".exe"}.get(system, "")
        candidate = self.utilities / name / f"{name}{suffix}"
        if candidate.exists():
            candidate.chmod(0o755)
            return candidate
        return None


def fetch_opencore(dl: Downloader, version: str = "latest",
                   work_dir: Path | None = None) -> OpenCorePackage:
    """Telecharge et extrait OpenCorePkg (release 'latest' ou version precise)."""
    step("OpenCore")
    if version and version != "latest":
        asset = f"OpenCore-{version}-RELEASE.zip"
        url = f"https://github.com/{OPENCORE_REPO}/releases/download/{version}/{asset}"
        resolved = Resolved(OPENCORE_REPO, version, asset, url, "explicite")
    else:
        resolved = dl.resolve(OPENCORE_REPO, OPENCORE_ASSET)
    archive = dl.fetch(resolved.url, resolved.asset)
    work_dir = work_dir or (dl.cache_dir / "opencore" / resolved.tag)
    if not (work_dir / "X64" / "EFI").exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(work_dir)
    ok(f"OpenCore {resolved.tag} ({resolved.source})")
    return OpenCorePackage(work_dir, resolved.tag, resolved)


def build_skeleton(pkg: OpenCorePackage, out_dir: Path, drivers: list[str],
                   tools: list[str], dl: Downloader, want_gui: bool,
                   warnings: list[str] | None = None) -> Path:
    """Cree EFI/BOOT + EFI/OC avec uniquement les pilotes et outils demandes."""
    step("Squelette EFI")
    efi = out_dir / "EFI"
    if efi.exists():
        shutil.rmtree(efi)
    (efi / "BOOT").mkdir(parents=True)
    oc_dir = efi / "OC"
    for sub in ("ACPI", "Drivers", "Kexts", "Tools", "Resources"):
        (oc_dir / sub).mkdir(parents=True)

    src = pkg.efi_x64
    shutil.copy2(src / "BOOT" / "BOOTx64.efi", efi / "BOOT" / "BOOTx64.efi")
    shutil.copy2(src / "OC" / "OpenCore.efi", oc_dir / "OpenCore.efi")
    for meta in (".contentFlavour", ".contentVisibility"):
        for folder, dest in ((src / "BOOT", efi / "BOOT"), (src / "OC", oc_dir)):
            if (folder / meta).exists():
                shutil.copy2(folder / meta, dest / meta)

    for driver in drivers:
        candidate = src / "OC" / "Drivers" / driver
        if candidate.exists():
            shutil.copy2(candidate, oc_dir / "Drivers" / driver)
            info(f"pilote {driver}")
        elif driver == "HfsPlus.efi":
            path = dl.github_raw(OCBINARYDATA, "Drivers/HfsPlus.efi")
            shutil.copy2(path, oc_dir / "Drivers" / "HfsPlus.efi")
            info("pilote HfsPlus.efi (OcBinaryData)")
        else:
            warn(f"pilote introuvable dans la release: {driver}")

    for tool in tools:
        candidate = src / "OC" / "Tools" / tool
        if candidate.exists():
            shutil.copy2(candidate, oc_dir / "Tools" / tool)
            info(f"outil {tool}")

    if want_gui and not _fetch_canopy_resources(dl, oc_dir / "Resources"):
        if warnings is not None:
            warnings.append(
                "ressources OpenCanopy absentes: PickerMode=External affichera un ecran vide. "
                "Copiez OcBinaryData/Resources dans EFI/OC/Resources, ou retirez la "
                "fonction 'gui'.")
    ok(f"EFI cree dans {efi}")
    return efi


def _fetch_canopy_resources(dl: Downloader, dest: Path) -> bool:
    """Recupere les ressources OpenCanopy (images, polices, sons)."""
    url = f"https://github.com/{OCBINARYDATA}/archive/refs/heads/master.zip"
    try:
        archive = dl.fetch(url, "OcBinaryData-master.zip")
    except BuildError as exc:
        warn(f"ressources OpenCanopy non recuperees ({exc}). "
             f"Copiez manuellement OcBinaryData/Resources dans EFI/OC/Resources.")
        return False
    with zipfile.ZipFile(archive) as zf:
        prefix = "OcBinaryData-master/Resources/"
        members = [n for n in zf.namelist() if n.startswith(prefix) and not n.endswith("/")]
        for name in members:
            target = dest / name[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    info(f"ressources OpenCanopy ({len(members)} fichiers)")
    return True


def select_drivers(profile) -> list[str]:
    drivers = list(BASE_DRIVERS)
    drivers.append("HfsPlus.efi")
    drivers.extend(OPTIONAL_DRIVERS["reset-nvram"])
    for feature, names in OPTIONAL_DRIVERS.items():
        if feature in {"reset-nvram"}:
            continue
        if feature in profile.features:
            drivers.extend(names)
    if profile.darwin <= 13:  # OS X 10.7-10.9: partition Recovery
        drivers.append("OpenPartitionDxe.efi")
    return drivers


def select_tools(profile) -> list[str]:
    tools = []
    if profile.debug:
        tools.append("OpenShell.efi")
    return tools
