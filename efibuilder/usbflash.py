"""Detection, sauvegarde et preparation d'une cle USB (Windows, macOS, Linux).

Toutes les operations destructives passent par prepare_plan() puis
run_plan(): le plan est affiche et doit etre confirme explicitement avant
d'etre execute. Rien n'est lance implicitement.
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from efibuilder.util import BuildError, human_size, info, ok, step, warn

SYSTEM = platform.system()
FAT32_DISKPART_LIMIT = 32 * 1024**3  # diskpart refuse de formater au-dela


@dataclass
class UsbDevice:
    """Un disque amovible candidat."""
    identifier: str          # /dev/disk2, /dev/sdb, ou le numero de disque Windows
    model: str
    size: int
    bus: str
    removable: bool
    system: bool
    mountpoints: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        mounted = f"  monte sur {', '.join(self.mountpoints)}" if self.mountpoints else ""
        return (f"{self.identifier:<12} {human_size(self.size):>9}  "
                f"{self.model or 'sans nom':<28} [{self.bus}]{mounted}")

    def safety_problem(self) -> str | None:
        """Raison de refuser ce disque, ou None s'il est acceptable."""
        if self.system:
            return "disque systeme ou de demarrage"
        if not self.removable:
            return "disque non amovible"
        if self.size <= 0:
            return "taille inconnue"
        if self.size > 512 * 1024**3:
            return f"taille inhabituelle pour une cle USB ({human_size(self.size)})"
        return None


# --------------------------------------------------------------- detection
def list_devices() -> list[UsbDevice]:
    if SYSTEM == "Windows":
        return _list_windows()
    if SYSTEM == "Darwin":
        return _list_macos()
    if SYSTEM == "Linux":
        return _list_linux()
    raise BuildError(f"systeme non pris en charge pour la detection USB: {SYSTEM}")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def _list_windows() -> list[UsbDevice]:
    script = ("Get-Disk | Select-Object Number,FriendlyName,Size,BusType,IsSystem,IsBoot "
              "| ConvertTo-Json -Compress")
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    if out.returncode != 0 or not out.stdout.strip():
        raise BuildError("Get-Disk a echoue: PowerShell est-il disponible ?")
    data = json.loads(out.stdout)
    if isinstance(data, dict):
        data = [data]
    letters = _windows_letters()
    devices = []
    for disk in data:
        number = str(disk.get("Number"))
        bus = str(disk.get("BusType", "?"))
        devices.append(UsbDevice(
            identifier=number,
            model=disk.get("FriendlyName") or "",
            size=int(disk.get("Size") or 0),
            bus=bus,
            removable=bus.upper() == "USB",
            system=bool(disk.get("IsSystem")) or bool(disk.get("IsBoot")),
            mountpoints=letters.get(number, []),
        ))
    return devices


def _windows_letters() -> dict[str, list[str]]:
    script = ("Get-Partition | Where-Object DriveLetter | "
              "Select-Object DiskNumber,DriveLetter | ConvertTo-Json -Compress")
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    data = json.loads(out.stdout)
    if isinstance(data, dict):
        data = [data]
    mapping: dict[str, list[str]] = {}
    for part in data:
        mapping.setdefault(str(part["DiskNumber"]), []).append(f"{part['DriveLetter']}:\\")
    return mapping


def _list_macos() -> list[UsbDevice]:
    out = _run(["diskutil", "list", "-plist", "physical"])
    if out.returncode != 0:
        raise BuildError("diskutil list a echoue")
    disks = plistlib.loads(out.stdout.encode())["WholeDisks"]
    devices = []
    for name in disks:
        detail = _run(["diskutil", "info", "-plist", f"/dev/{name}"])
        if detail.returncode != 0:
            continue
        d = plistlib.loads(detail.stdout.encode())
        devices.append(UsbDevice(
            identifier=f"/dev/{name}",
            model=d.get("MediaName") or "",
            size=int(d.get("TotalSize") or 0),
            bus=d.get("BusProtocol") or "?",
            removable=bool(d.get("RemovableMediaOrExternalDevice")) or bool(d.get("Ejectable")),
            system=bool(d.get("Internal")) or bool(d.get("SystemImage")),
            mountpoints=_macos_mountpoints(name),
        ))
    return devices


def _macos_mountpoints(disk: str) -> list[str]:
    out = _run(["diskutil", "list", "-plist", f"/dev/{disk}"])
    if out.returncode != 0:
        return []
    data = plistlib.loads(out.stdout.encode())
    mounts = []
    for entry in data.get("AllDisksAndPartitions", []):
        for part in entry.get("Partitions", []):
            if part.get("MountPoint"):
                mounts.append(part["MountPoint"])
    return mounts


def _list_linux() -> list[UsbDevice]:
    out = _run(["lsblk", "--json", "-b", "-o",
                "NAME,PATH,SIZE,MODEL,TRAN,RM,HOTPLUG,TYPE,MOUNTPOINT"])
    if out.returncode != 0:
        raise BuildError("lsblk a echoue: le paquet util-linux est-il installe ?")
    data = json.loads(out.stdout)
    devices = []
    for disk in data.get("blockdevices", []):
        if disk.get("type") != "disk":
            continue
        mounts = [c["mountpoint"] for c in disk.get("children", []) if c.get("mountpoint")]
        if disk.get("mountpoint"):
            mounts.append(disk["mountpoint"])
        devices.append(UsbDevice(
            identifier=disk.get("path") or f"/dev/{disk['name']}",
            model=(disk.get("model") or "").strip(),
            size=int(disk.get("size") or 0),
            bus=(disk.get("tran") or "?"),
            removable=bool(disk.get("rm")) or bool(disk.get("hotplug")),
            system=any(m in ("/", "/boot", "/boot/efi", "/home") for m in mounts),
            mountpoints=mounts,
        ))
    return devices


def usable_devices() -> tuple[list[UsbDevice], list[tuple[UsbDevice, str]]]:
    """Retourne (cles utilisables, disques ecartes avec la raison)."""
    usable, rejected = [], []
    for device in list_devices():
        problem = device.safety_problem()
        (rejected.append((device, problem)) if problem else usable.append(device))
    return usable, rejected


# --------------------------------------------------------------- sauvegarde
def downloads_dir() -> Path:
    home = Path.home()
    for name in ("Downloads", "Telechargements", "Téléchargements"):
        candidate = home / name
        if candidate.is_dir():
            return candidate
    return home


def backup_device(device: UsbDevice, dest_dir: Path | None = None) -> Path | None:
    """Archive le contenu actuel de la cle dans un zip avant tout formatage."""
    step("Sauvegarde du contenu actuel de la cle")
    if not device.mountpoints:
        warn("la cle n'est montee nulle part: rien a sauvegarder "
             "(montez-la d'abord si elle contient des donnees a garder)")
        return None
    dest_dir = dest_dir or downloads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = device.identifier.strip("/").replace("/", "-").replace("\\", "-")
    archive = dest_dir / f"sauvegarde-cle-{safe}-{stamp}.zip"

    total, skipped = 0, 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for mount in device.mountpoints:
            root = Path(mount)
            if not root.is_dir():
                continue
            prefix = root.name or safe
            for path in root.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    zf.write(path, Path(prefix) / path.relative_to(root))
                    total += 1
                except (OSError, PermissionError):
                    skipped += 1
    if total == 0:
        archive.unlink(missing_ok=True)
        warn("aucun fichier lisible sur la cle: pas de sauvegarde creee")
        return None
    info(f"{total} fichiers archives" + (f", {skipped} illisibles ignores" if skipped else ""))
    ok(f"sauvegarde: {archive} ({human_size(archive.stat().st_size)})")
    return archive


# ------------------------------------------------------------ plan d'action
def format_commands(device: UsbDevice, label: str = "EFI") -> list[list[str]]:
    """Commandes de formatage FAT32/GPT, sans les executer."""
    if SYSTEM == "Windows":
        return [["diskpart", "/s", "<script genere>"]]
    if SYSTEM == "Darwin":
        return [["diskutil", "eraseDisk", "FAT32", label, "GPT", device.identifier]]
    if SYSTEM == "Linux":
        target = device.identifier
        part = f"{target}p1" if target[-1].isdigit() else f"{target}1"
        return [
            ["sudo", "wipefs", "-a", target],
            ["sudo", "parted", "-s", target, "mklabel", "gpt"],
            ["sudo", "parted", "-s", target, "mkpart", "primary", "fat32", "1MiB", "100%"],
            ["sudo", "mkfs.vfat", "-F", "32", "-n", label, part],
        ]
    raise BuildError(f"formatage non pris en charge sur {SYSTEM}")


def _windows_diskpart_script(device: UsbDevice, label: str) -> str:
    return "\n".join([
        f"select disk {device.identifier}",
        "clean",
        "convert gpt",
        "create partition primary",
        f"format fs=fat32 quick label={label}",
        "assign",
        "exit",
        "",
    ])


def format_device(device: UsbDevice, label: str = "EFI", dry_run: bool = False) -> None:
    """Formate la totalite de la cle en FAT32 avec une table GPT."""
    step(f"Formatage de {device.identifier} en FAT32 (GPT)")
    if SYSTEM == "Windows" and device.size > FAT32_DISKPART_LIMIT:
        raise BuildError(
            f"diskpart ne formate pas en FAT32 au-dela de 32 Go "
            f"(cle de {human_size(device.size)}). Utilisez une cle plus petite, "
            f"ou formatez-la avec un outil tiers puis relancez avec --skip-format.")
    if dry_run:
        for cmd in format_commands(device, label):
            info("(simulation) " + " ".join(cmd))
        return

    if SYSTEM == "Windows":
        script = Path(os.environ.get("TEMP", ".")) / "efibuild-diskpart.txt"
        script.write_text(_windows_diskpart_script(device, label), encoding="ascii")
        try:
            result = _run(["diskpart", "/s", str(script)])
        finally:
            script.unlink(missing_ok=True)
        if result.returncode != 0:
            raise BuildError(f"diskpart a echoue (droits administrateur requis):\n"
                             f"{result.stdout}{result.stderr}")
    else:
        for cmd in format_commands(device, label):
            info(" ".join(cmd))
            result = _run(cmd)
            if result.returncode != 0:
                raise BuildError(
                    f"echec de: {' '.join(cmd)}\n{result.stdout}{result.stderr}")
    ok("cle formatee")


def wait_for_mount(device: UsbDevice, label: str = "EFI", timeout: int = 30) -> Path:
    """Retrouve (ou cree) le point de montage de la cle fraichement formatee."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if SYSTEM == "Darwin":
            candidate = Path("/Volumes") / label
            if candidate.is_dir():
                return candidate
        elif SYSTEM == "Windows":
            for letters in _windows_letters().get(device.identifier, []):
                return Path(letters)
        else:
            for refreshed in list_devices():
                if refreshed.identifier == device.identifier and refreshed.mountpoints:
                    return Path(refreshed.mountpoints[0])
            return _linux_mount(device, label)
        time.sleep(1)
    raise BuildError("la cle formatee n'est pas apparue: montez-la puis copiez "
                     "le contenu manuellement")


def _linux_mount(device: UsbDevice, label: str) -> Path:
    target = device.identifier
    part = f"{target}p1" if target[-1].isdigit() else f"{target}1"
    mount = Path("/media") / f"efibuild-{label}"
    _run(["sudo", "mkdir", "-p", str(mount)])
    result = _run(["sudo", "mount", part, str(mount)])
    if result.returncode != 0:
        raise BuildError(f"montage impossible: {result.stderr.strip()}")
    return mount


def copy_payload(mount: Path, efi_dir: Path, recovery_dir: Path | None) -> None:
    """Copie EFI/ et l'image de recuperation a la racine de la cle."""
    step(f"Copie des fichiers vers {mount}")
    target = mount / "EFI"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(efi_dir, target)
    info(f"EFI/ copie ({sum(1 for _ in target.rglob('*'))} elements)")
    if recovery_dir and recovery_dir.is_dir():
        dest = mount / recovery_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(recovery_dir, dest)
        info(f"{recovery_dir.name}/ copie")
    else:
        warn("pas d'image de recuperation copiee (voir 'efibuild recovery')")
    ok("fichiers en place")
