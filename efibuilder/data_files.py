"""Chargement des tables de donnees embarquees (data/*.json)."""
from __future__ import annotations

import functools
import json
from importlib import resources
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


@functools.lru_cache(maxsize=None)
def load(name: str) -> dict:
    """Lit une table embarquee, y compris quand efibuild tourne depuis un .pyz."""
    # joinpath() n'accepte qu'un argument sur zipfile.Path avant Python 3.12:
    # on enchaine les appels pour rester compatible depuis un .pyz.
    resource = resources.files("efibuilder").joinpath("data").joinpath(f"{name}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def platforms() -> list[dict]:
    return load("platforms")["platforms"]


def platform(pid: str) -> dict:
    for entry in platforms():
        if entry["id"] == pid:
            return entry
    known = ", ".join(p["id"] for p in platforms())
    raise KeyError(f"plateforme inconnue: {pid}\nplateformes disponibles: {known}")


def macos_versions() -> list[dict]:
    return load("macos")["versions"]


def macos(key: str) -> dict:
    key = key.lower()
    key = load("macos")["aliases"].get(key, key)
    for entry in macos_versions():
        if entry["key"] == key:
            return entry
    known = ", ".join(v["key"] for v in macos_versions())
    raise KeyError(f"version de macOS inconnue: {key}\nversions disponibles: {known}")


def kexts() -> list[dict]:
    return load("kexts")["kexts"]


def smbios_models() -> list[dict]:
    return load("smbios")["models"]


def smbios_model(model: str) -> dict | None:
    for entry in smbios_models():
        if entry["model"].lower() == model.lower():
            return entry
    return None


def boards() -> dict:
    """board-id -> derniere version de macOS servie (snapshot de boards.json)."""
    return load("boards")["boards"]


def pins() -> dict:
    return load("pins")["pins"]
