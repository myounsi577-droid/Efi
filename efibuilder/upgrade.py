"""Mise a jour d'un EFI existant, sans toucher a ce qui a ete regle a la main.

Le principe est chirurgical: on remplace les binaires qui vieillissent
(OpenCore, pilotes UEFI, kexts du catalogue) et on laisse strictement
intacts les SSDT, le mappage USB, le config.plist et tout kext inconnu.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from efibuilder import data_files, oc
from efibuilder.net import Downloader
from efibuilder.util import (BuildError, extract_bundle, find_plugins, info, ok,
                             read_plist, step, warn)


def _bundle_index() -> dict[str, dict]:
    """bundle -> entree du catalogue, pour reconnaitre les kexts en place."""
    index = {}
    for entry in data_files.kexts():
        for bundle in entry["bundles"]:
            index.setdefault(bundle, entry)
    return index


def kext_version(bundle: Path) -> str:
    info_plist = bundle / "Contents" / "Info.plist"
    if not info_plist.exists():
        return "?"
    try:
        data = read_plist(info_plist)
    except Exception:  # noqa: BLE001 - un Info.plist illisible n'est pas fatal
        return "?"
    return str(data.get("CFBundleShortVersionString")
               or data.get("CFBundleVersion") or "?")


def locate_efi(path: Path) -> Path:
    """Accepte un dossier EFI, son parent, ou le dossier OC lui-meme."""
    path = Path(path).expanduser()
    for candidate in (path, path / "EFI", path.parent):
        if (candidate / "OC" / "config.plist").exists():
            return candidate
    raise BuildError(f"aucun EFI trouve dans {path} (il faut un dossier OC/config.plist)")


def upgrade_efi(source: Path, dl: Downloader, out_dir: Path | None = None,
                oc_version: str = "latest", dry_run: bool = False) -> dict:
    """Copie l'EFI puis y remplace OpenCore et les kexts connus."""
    efi = locate_efi(source)
    step(f"Mise a jour de {efi}")

    if dry_run:
        target = efi
        info("simulation: rien ne sera ecrit")
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = Path(out_dir) if out_dir else efi.parent / f"EFI-maj-{stamp}"
        if target.exists() and target.samefile(efi):
            raise BuildError("le dossier de sortie ne peut pas etre l'EFI d'origine")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(efi, target)
        ok(f"copie de travail: {target} (votre EFI d'origine n'est pas modifie)")

    pkg = oc.fetch_opencore(dl, oc_version)
    host = oc.host_note()
    if host:
        warn(host)

    report = {
        "efi": efi, "target": target, "opencore": pkg.version,
        "drivers": [], "kexts": [], "preserved": [], "notes": [],
    }
    _upgrade_opencore(pkg, target, report, dry_run, dl)
    _upgrade_kexts(pkg, dl, target, report, dry_run)
    _preserved(target, report)
    return report


def _upgrade_opencore(pkg: oc.OpenCorePackage, target: Path, report: dict,
                      dry_run: bool, dl: Downloader | None = None) -> None:
    step("OpenCore et pilotes UEFI")
    extras: list[tuple[str, Path]] = []
    src = pkg.efi_x64
    pairs = [(src / "BOOT" / "BOOTx64.efi", target / "BOOT" / "BOOTx64.efi"),
             (src / "OC" / "OpenCore.efi", target / "OC" / "OpenCore.efi")]
    for folder in ("Drivers", "Tools"):
        existing = target / "OC" / folder
        if not existing.is_dir():
            continue
        for item in sorted(existing.glob("*.efi")):
            candidate = src / "OC" / folder / item.name
            if candidate.exists():
                pairs.append((candidate, item))
            else:
                extras.append((folder, item))

    for source_file, destination in pairs:
        if not source_file.exists():
            continue
        changed = (not destination.exists()
                   or source_file.stat().st_size != destination.stat().st_size)
        report["drivers"].append((destination.name, "remplace" if changed else "identique"))
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
    # HfsPlus.efi et consorts viennent d'OcBinaryData, pas de la release OpenCore.
    for folder, item in extras:
        refreshed = False
        if dl is not None and folder == "Drivers":
            try:
                fetched = dl.github_raw(oc.OCBINARYDATA, f"Drivers/{item.name}")
                if not dry_run:
                    shutil.copy2(fetched, item)
                report["drivers"].append((item.name, "remplace (OcBinaryData)"))
                refreshed = True
            except Exception:  # noqa: BLE001 - simple repli sur la conservation
                refreshed = False
        if not refreshed:
            report["preserved"].append(f"{folder}/{item.name} (absent de la release)")
    info(f"{len(pairs) + len(extras)} fichiers OpenCore alignes sur la version {pkg.version}")


def _upgrade_kexts(pkg: oc.OpenCorePackage, dl: Downloader, target: Path, report: dict,
                   dry_run: bool) -> None:
    step("Kexts")
    kexts_dir = target / "OC" / "Kexts"
    if not kexts_dir.is_dir():
        warn("pas de dossier Kexts dans cet EFI")
        return
    index = _bundle_index()

    for bundle in sorted(kexts_dir.glob("*.kext")):
        entry = index.get(bundle.name)
        if entry is None or entry.get("manual"):
            reason = "hors catalogue" if entry is None else "a fournir soi-meme"
            report["preserved"].append(f"Kexts/{bundle.name} ({reason})")
            continue
        regex = entry.get("asset") or (entry.get("asset_by_macos") or {}).get("sequoia")
        if not regex:
            report["preserved"].append(f"Kexts/{bundle.name} (version liee a macOS)")
            continue

        before = kext_version(bundle)
        plugins_before = set(find_plugins(bundle))
        try:
            resolved = dl.resolve(entry["repo"], regex)
            archive = dl.fetch(resolved.url, resolved.asset)
        except BuildError as exc:
            warn(f"{bundle.name} laisse en place: {exc}")
            report["preserved"].append(f"Kexts/{bundle.name} (telechargement impossible)")
            continue

        if dry_run:
            report["kexts"].append((bundle.name, before, f"-> {resolved.tag}"))
            continue

        try:
            extract_bundle(archive, bundle.name, kexts_dir)
        except BuildError as exc:
            warn(str(exc))
            continue
        after = kext_version(kexts_dir / bundle.name)
        report["kexts"].append((bundle.name, before, after))

        plugins_after = set(find_plugins(kexts_dir / bundle.name))
        for gone in sorted(plugins_before - plugins_after):
            report["notes"].append(
                f"{bundle.name}: le PlugIn {Path(gone).name} a disparu de la nouvelle "
                f"version, retirez son entree de Kernel -> Add.")
        for added in sorted(plugins_after - plugins_before):
            report["notes"].append(
                f"{bundle.name}: nouveau PlugIn {Path(added).name}, a declarer dans "
                f"Kernel -> Add si vous en avez besoin.")

    changed = [k for k in report["kexts"] if k[1] != k[2]]
    ok(f"{len(report['kexts'])} kexts traites, {len(changed)} mis a jour")


def _preserved(target: Path, report: dict) -> None:
    """Recense ce qui n'a volontairement pas ete touche."""
    acpi = target / "OC" / "ACPI"
    if acpi.is_dir():
        amls = sorted(p.name for p in acpi.glob("*.aml"))
        if amls:
            report["preserved"].insert(0, f"ACPI: {', '.join(amls)}")
    report["preserved"].insert(0, "OC/config.plist (aucune modification)")


def print_report(report: dict) -> None:
    print()
    step("Bilan")
    info(f"OpenCore aligne sur la version {report['opencore']}")
    changed = [k for k in report["kexts"] if k[1] != k[2]]
    if changed:
        print()
        info("kexts mis a jour:")
        for name, before, after in changed:
            info(f"  {name:<34} {before:>10}  ->  {after}")
    same = [k for k in report["kexts"] if k[1] == k[2]]
    if same:
        info(f"deja a jour: {', '.join(n for n, _, _ in same)}")
    print()
    info("conserve tel quel:")
    for item in report["preserved"]:
        info(f"  {item}")
    if report["notes"]:
        print()
        for note in report["notes"]:
            warn(note)
    print()
    ok(f"EFI mis a jour: {report['target']}")
    info("Testez-le depuis une cle USB avant de remplacer celui de votre disque.")
