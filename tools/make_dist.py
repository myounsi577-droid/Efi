#!/usr/bin/env python3
"""Construit l'archive de distribution d'efibuild.

Produit dans dist/ :
  - efibuild.pyz            executable autonome (python3 efibuild.pyz), tout OS
  - efibuild-<version>.zip  archive complete: .pyz + sources + lanceurs + docs

Aucune dependance: uniquement la bibliotheque standard.
"""
from __future__ import annotations

import shutil
import sys
import zipapp
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = DIST / "_build"

INCLUDED = ["efibuilder", "tests", "docs", "README.md", "efibuild", "efibuild.cmd",
            "efibuild.ps1", ".gitignore"]
EXCLUDED_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}

INSTALL_TXT = """efibuild - generateur d'EFI OpenCore
===================================

Pre-requis: Python 3.9 ou plus recent. Rien d'autre a installer.
  - Windows : https://www.python.org/downloads/ (cochez "Add python.exe to PATH")
  - macOS   : deja present, ou "brew install python"
  - Linux   : deja present sur la quasi-totalite des distributions

DEMARRAGE LE PLUS SIMPLE
------------------------
Ouvrez un terminal dans ce dossier et lancez:

  Windows      python efibuild.pyz
  macOS/Linux  python3 efibuild.pyz

Sans argument, le menu numerote s'ouvre: tout se choisit avec un numero.

AUTRES FACONS DE LANCER
-----------------------
  Windows          efibuild.cmd
  PowerShell       .\\efibuild.ps1
  macOS / Linux    ./efibuild
  Partout          python3 -m efibuilder

EXEMPLES EN LIGNE DE COMMANDE
-----------------------------
  python3 efibuild.pyz list platforms
  python3 efibuild.pyz build --platform coffee-lake-desktop --chipset z390 \\
      --macos sequoia --igpu uhd630 --ethernet intel-i219 -o mon-efi
  python3 efibuild.pyz recovery --macos sequoia -o mon-efi
  python3 efibuild.pyz flash --efi mon-efi/EFI

ATTENTION
---------
La commande "flash" efface la totalite de la cle USB choisie. Elle refuse tout
disque non amovible ou systeme, et demande de retaper l'identifiant exact du
peripherique avant d'effacer. Utilisez --list et --dry-run pour verifier avant.

Documentation complete: README.md et docs/GUIDE.md
Sources: https://github.com/myounsi577-droid/Efi
"""

MAIN_PY = '''"""Point d'entree du zipapp efibuild."""
import sys

from efibuilder.cli import main

if __name__ == "__main__":
    sys.exit(main())
'''


def version() -> str:
    text = (ROOT / "efibuilder" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    return "0.0.0"


def _copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, "*.pyc"))


def build_pyz(target: Path) -> Path:
    """Cree un executable Python autonome (stdlib zipapp)."""
    staging = BUILD / "pyz"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    _copy_tree(ROOT / "efibuilder", staging / "efibuilder")
    (staging / "__main__.py").write_text(MAIN_PY, encoding="utf-8")
    zipapp.create_archive(staging, target, interpreter="/usr/bin/env python3",
                          compressed=True)
    target.chmod(0o755)
    return target


def build_zip(pyz: Path, target: Path) -> Path:
    """Archive complete: le .pyz, les sources, les lanceurs et la documentation."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        root = f"efibuild-{version()}"
        zf.write(pyz, f"{root}/efibuild.pyz")
        zf.writestr(f"{root}/INSTALLER.txt", INSTALL_TXT)
        for name in INCLUDED:
            path = ROOT / name
            if not path.exists():
                continue
            if path.is_dir():
                for item in sorted(path.rglob("*")):
                    if item.is_dir() or any(part in EXCLUDED_DIRS for part in item.parts):
                        continue
                    if item.suffix == ".pyc":
                        continue
                    zf.write(item, f"{root}/{item.relative_to(ROOT)}")
            else:
                zf.write(path, f"{root}/{name}")
    return target


def main() -> int:
    DIST.mkdir(exist_ok=True)
    pyz = build_pyz(DIST / "efibuild.pyz")
    archive = build_zip(pyz, DIST / f"efibuild-{version()}.zip")
    shutil.rmtree(BUILD, ignore_errors=True)
    for path in (pyz, archive):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
