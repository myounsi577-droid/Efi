"""Petits utilitaires partages: affichage, plist, versions."""
from __future__ import annotations

import os
import plistlib
import shutil
import sys
import zipfile
from pathlib import Path

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def step(msg: str) -> None:
    print(_c("1;36", "==>") + " " + msg)


def info(msg: str) -> None:
    print("    " + msg)


def ok(msg: str) -> None:
    print("    " + _c("32", "OK") + "  " + msg)


def warn(msg: str) -> None:
    print("    " + _c("33", "!!") + "  " + msg)


def err(msg: str) -> None:
    print(_c("1;31", "ERREUR") + " " + msg, file=sys.stderr)


class BuildError(Exception):
    """Erreur fatale, remontee proprement par la CLI."""


def run_tool(cmd, **kwargs):
    """Lance un programme externe, ou retourne None si l'hote l'interdit.

    Certains environnements mobiles (a-Shell et Pythonista sur iOS) executent
    Python sans possibilite de creer un processus: subprocess leve alors une
    OSError ou une NotImplementedError. Le reste d'efibuild continue de
    fonctionner, seules les etapes qui dependent d'un binaire sont sautees.
    """
    import subprocess

    kwargs.setdefault("check", False)
    try:
        return subprocess.run(cmd, **kwargs)
    except (OSError, NotImplementedError, ValueError):
        return None


NO_SUBPROCESS = ("cet environnement execute Python sans pouvoir lancer de programme "
                 "externe (c'est le cas d'a-Shell sur iOS)")


def ascii_comment(text: str) -> str:
    """OpenCore refuse les caracteres non ASCII dans les champs Comment."""
    import unicodedata

    normalised = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalised if 32 <= ord(c) < 127)


def read_plist(path: Path) -> dict:
    with open(path, "rb") as fh:
        return plistlib.load(fh)


def write_plist(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump(data, fh, sort_keys=True)


def hexdata(value: str) -> bytes:
    """Convertit '07009B3E' en donnees binaires pour un plist."""
    cleaned = "".join(value.split())
    return bytes.fromhex(cleaned)


def extract_bundle(archive: Path, bundle: str, dest_dir: Path) -> Path:
    """Extrait <bundle>.kext (ou .efi) d'une archive zip vers dest_dir.

    Le chemin le plus court correspondant est retenu et les dossiers de debug
    (.dSYM) sont ignores, ce qui couvre les archives ou les kexts sont ranges
    dans un sous-dossier (VirtualSMC place les siens dans Kexts/).
    """
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        prefix = None
        for name in sorted(names, key=lambda n: (n.count("/"), len(n))):
            if ".dSYM" in name:
                continue
            marker = bundle.rstrip("/") + "/"
            if name.endswith(marker) or f"/{marker}" in name:
                idx = name.rfind(marker)
                prefix = name[: idx + len(marker)]
                break
        if prefix is None:
            raise BuildError(f"{bundle} introuvable dans {archive.name}")
        target = dest_dir / bundle
        if target.exists():
            shutil.rmtree(target)
        for name in names:
            if not name.startswith(prefix) or ".dSYM" in name:
                continue
            rel = name[len(prefix):]
            if not rel:
                continue
            out = target / rel
            if name.endswith("/"):
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            mode = (zf.getinfo(name).external_attr >> 16) & 0o777
            if mode & 0o111:
                out.chmod(mode or 0o755)
    return target


def kext_identity(kext_dir: Path) -> dict:
    """Retourne BundlePath/ExecutablePath/PlistPath d'un kext extrait."""
    info_plist = kext_dir / "Contents" / "Info.plist"
    executable = ""
    if info_plist.exists():
        try:
            data = read_plist(info_plist)
            name = data.get("CFBundleExecutable", "")
            if name and (kext_dir / "Contents" / "MacOS" / name).exists():
                executable = f"Contents/MacOS/{name}"
        except Exception:  # plist illisible: on retombe sur un kext sans binaire
            executable = ""
    return {"ExecutablePath": executable, "PlistPath": "Contents/Info.plist"}


def find_plugins(kext_dir: Path) -> list[str]:
    """Liste les PlugIns internes d'un kext (chemins relatifs au bundle)."""
    plugins_dir = kext_dir / "Contents" / "PlugIns"
    if not plugins_dir.is_dir():
        return []
    return sorted(
        f"Contents/PlugIns/{p.name}"
        for p in plugins_dir.iterdir()
        if p.is_dir() and p.name.endswith(".kext")
    )


def human_size(num: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if num < 1024 or unit == "Go":
            return f"{num:.0f} {unit}" if unit == "o" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num} o"
