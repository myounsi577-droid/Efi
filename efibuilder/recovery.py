"""Telechargement de l'image de recuperation Apple via macrecovery (OpenCorePkg)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from efibuilder import data_files
from efibuilder.oc import OpenCorePackage
from efibuilder.util import BuildError, info, ok, step, warn

RECOVERY_DIR = "com.apple.recovery.boot"


def download_recovery(pkg: OpenCorePackage, macos_key: str, out_dir: Path,
                      diagnostics: bool = False, board_id: str | None = None,
                      mlb: str | None = None) -> Path:
    """Lance macrecovery.py et retourne le dossier com.apple.recovery.boot."""
    entry = data_files.macos(macos_key)
    recovery = entry["recovery"]
    board = board_id or recovery["board_id"]
    serial = mlb or recovery["mlb"]

    script = pkg.macrecovery
    if not script.exists():
        raise BuildError(f"macrecovery.py introuvable dans {pkg.utilities}")

    target = out_dir / RECOVERY_DIR
    target.mkdir(parents=True, exist_ok=True)

    step(f"Image de recuperation Apple - {entry['name']}")
    info(f"board-id {board} / MLB {serial}")
    cmd = [sys.executable, str(script), "-b", board, "-m", serial, "-o", str(target)]
    if recovery.get("os_type"):
        cmd += ["-os", recovery["os_type"]]
    if diagnostics:
        cmd.append("-diag")
    cmd.append("download")

    info(" ".join(cmd))
    result = subprocess.run(cmd, cwd=script.parent, check=False)
    if result.returncode != 0:
        raise BuildError(
            "macrecovery a echoue. Les serveurs Apple (osrecovery.apple.com) doivent etre "
            "joignables directement; un proxy ou un pare-feu d'entreprise les bloque souvent.")

    files = sorted(p.name for p in target.iterdir())
    if not files:
        raise BuildError("macrecovery n'a produit aucun fichier")
    ok(f"{entry['name']} telecharge dans {target}")
    for name in files:
        info(f"  {name}")
    if entry["notes"]:
        warn("A savoir sur cette version:")
        for note in entry["notes"]:
            info(f"  - {note}")
    return target


def describe(macos_key: str) -> None:
    entry = data_files.macos(macos_key)
    recovery = entry["recovery"]
    print(f"{entry['name']} (macOS {entry['release']}, noyau Darwin {entry['darwin']})")
    print(f"  board-id : {recovery['board_id']}")
    print(f"  MLB      : {recovery['mlb']}")
    if recovery.get("os_type"):
        print(f"  os-type  : {recovery['os_type']}")
    for note in entry["notes"]:
        print(f"  note     : {note}")
