"""Selection, telechargement et installation des kexts."""
from __future__ import annotations

from pathlib import Path

from efibuilder import data_files
from efibuilder.net import Downloader
from efibuilder.util import (BuildError, ascii_comment, extract_bundle, find_plugins,
                             info, kext_identity, ok, step, warn)


def _version_index(key: str) -> int:
    return [v["key"] for v in data_files.macos_versions()].index(key)


def select_kexts(profile) -> tuple[list[dict], list[str]]:
    """Retourne (kexts retenus, avertissements) pour ce profil."""
    chosen, warnings = [], []
    for entry in data_files.kexts():
        if not entry.get("required") and not profile.matches(entry.get("when")):
            continue
        if entry.get("min_darwin") and profile.darwin < entry["min_darwin"]:
            continue
        if entry.get("max_darwin") and profile.darwin > entry["max_darwin"]:
            continue
        max_macos = entry.get("max_macos")
        if max_macos and _version_index(profile.macos_data["key"]) > _version_index(max_macos):
            warnings.append(
                f"{entry['id']} n'est pas supporte au-dela de "
                f"{data_files.macos(max_macos)['name']}: non installe.")
            continue
        note = (entry.get("warn_macos") or {}).get(profile.macos_data["key"])
        if note:
            warnings.append(f"{entry['id']}: {note}")
        chosen.append(entry)
    if profile.ethernet == "auto":
        warnings.append(
            "carte Ethernet non precisee (--ethernet): aucun pilote reseau installe. "
            "Sans reseau, pas d'iServices ni de mise a jour.")
    chosen.sort(key=lambda e: e.get("order", 100))
    return chosen, warnings


def install_kexts(profile, dl: Downloader, kexts_dir: Path) -> tuple[list[dict], list[str]]:
    """Telecharge les kexts et retourne (entrees Kernel -> Add, avertissements)."""
    step("Kexts")
    chosen, warnings = select_kexts(profile)
    entries: list[dict] = []
    installed: set[str] = set()

    for entry in chosen:
        regex = entry.get("asset")
        if not regex:
            by_macos = entry.get("asset_by_macos", {})
            regex = by_macos.get(profile.macos_data["key"])
            if not regex:
                warnings.append(
                    f"{entry['id']}: pas de build pour {profile.macos_data['name']}, ignore.")
                continue
        try:
            resolved = dl.resolve(entry["repo"], regex)
            archive = dl.fetch(resolved.url, resolved.asset)
        except BuildError as exc:
            if entry.get("required"):
                raise
            warnings.append(f"{entry['id']} non installe: {exc}")
            continue

        for bundle in entry["bundles"]:
            if bundle in installed:
                continue
            try:
                path = extract_bundle(archive, bundle, kexts_dir)
            except BuildError as exc:
                if entry.get("required"):
                    raise
                warnings.append(str(exc))
                continue
            installed.add(bundle)
            entries.extend(_kernel_entries(path, bundle, entry, profile))
            info(f"{bundle:<34} {resolved.tag:<10} {entry.get('reason', '')}")

    ok(f"{len(installed)} kexts installes dans {kexts_dir}")
    return entries, warnings


def _kernel_entries(path: Path, bundle: str, catalog: dict, profile) -> list[dict]:
    """Entree Kernel -> Add du kext + de ses PlugIns internes."""
    out = []
    identity = kext_identity(path)
    out.append({
        "Arch": "x86_64",
        "BundlePath": bundle,
        "Comment": ascii_comment(catalog.get("reason", catalog["id"])),
        "Enabled": True,
        "ExecutablePath": identity["ExecutablePath"],
        "MaxKernel": _max_kernel(catalog),
        "MinKernel": _min_kernel(catalog),
        "PlistPath": identity["PlistPath"],
    })
    for plugin in find_plugins(path):
        plugin_path = path / plugin
        pid = kext_identity(plugin_path)
        out.append({
            "Arch": "x86_64",
            "BundlePath": f"{bundle}/{plugin}",
            "Comment": ascii_comment(f"PlugIn de {bundle}"),
            "Enabled": True,
            "ExecutablePath": pid["ExecutablePath"],
            "MaxKernel": _max_kernel(catalog),
            "MinKernel": _min_kernel(catalog),
            "PlistPath": pid["PlistPath"],
        })
    return out


def _min_kernel(catalog: dict) -> str:
    value = catalog.get("min_darwin")
    return f"{value}.0.0" if value else ""


def _max_kernel(catalog: dict) -> str:
    value = catalog.get("max_darwin")
    return f"{value}.99.99" if value else ""
