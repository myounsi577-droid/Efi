"""Preparation du contenu de la cle USB d'installation."""
from __future__ import annotations

import platform
import shutil
from pathlib import Path

from efibuilder.util import BuildError, info, ok, step, warn


def stage(efi_dir: Path, recovery_dir: Path | None, dest: Path) -> Path:
    """Rassemble EFI/ et com.apple.recovery.boot/ dans un dossier pret a copier."""
    step("Preparation du contenu de la cle USB")
    dest.mkdir(parents=True, exist_ok=True)
    if not efi_dir.exists():
        raise BuildError(f"dossier EFI introuvable: {efi_dir}")
    target_efi = dest / "EFI"
    if target_efi.exists():
        shutil.rmtree(target_efi)
    shutil.copytree(efi_dir, target_efi)
    info(f"EFI/ copie ({sum(1 for _ in target_efi.rglob('*'))} elements)")

    if recovery_dir and recovery_dir.exists():
        target_rec = dest / recovery_dir.name
        if target_rec.exists():
            shutil.rmtree(target_rec)
        shutil.copytree(recovery_dir, target_rec)
        info(f"{recovery_dir.name}/ copie")
    else:
        warn("aucune image de recuperation: lancez 'efibuild recovery' avant de copier la cle")
    ok(f"contenu pret dans {dest}")
    print_instructions(dest)
    return dest


def print_instructions(dest: Path) -> None:
    system = platform.system()
    print()
    print("Preparation de la cle (aucune commande destructive n'est lancee par efibuild):")
    print()
    if system == "Darwin":
        print("  diskutil list                       # reperer le disque de la cle")
        print("  diskutil eraseDisk FAT32 EFI GPT /dev/diskN")
        print(f"  cp -R {dest}/* /Volumes/EFI/")
    elif system == "Linux":
        print("  lsblk                               # reperer le peripherique de la cle")
        print("  sudo parted /dev/sdX mklabel gpt")
        print("  sudo parted /dev/sdX mkpart primary fat32 1MiB 100%")
        print("  sudo mkfs.vfat -F 32 -n EFI /dev/sdX1")
        print("  sudo mount /dev/sdX1 /mnt && sudo cp -R "
              f"{dest}/* /mnt/ && sudo umount /mnt")
    else:
        print("  Formater la cle en FAT32 avec un schema de partition GPT")
        print("  (Rufus, ou 'diskpart' -> clean / convert gpt / create partition primary /")
        print("   format fs=fat32 quick), puis copier le contenu du dossier prepare.")
        print(f"  Contenu a copier: {dest}\\*")
    print()
    print("La cle doit contenir EFI/ et com.apple.recovery.boot/ a sa racine.")
