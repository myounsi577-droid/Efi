"""Orchestration: construit un EFI complet a partir d'un profil."""
from __future__ import annotations

import subprocess
from pathlib import Path

from efibuilder import acpi, configgen, kexts, oc, report, smbios, usbmap
from efibuilder.net import Downloader
from efibuilder.profile import Profile, set_boards_table
from efibuilder.util import BuildError, info, ok, step, warn, write_plist


def build_efi(profile: Profile, out_dir: Path, dl: Downloader,
              force: bool = False) -> dict:
    """Construit l'EFI et retourne le contexte utilise pour le rapport."""
    blockers = profile.blockers()
    if blockers:
        listing = "\n  - ".join(blockers)
        if not force:
            raise BuildError(
                f"materiel incompatible avec macOS:\n  - {listing}\n"
                f"Aucun EFI ne rendra cette machine fonctionnelle. Utilisez --force "
                f"pour generer quand meme les fichiers (a des fins d'experimentation).")
        warn("construction forcee malgre un materiel incompatible:")
        for item in blockers:
            info(f"- {item}")
    out_dir.mkdir(parents=True, exist_ok=True)

    pkg = oc.fetch_opencore(dl, profile.oc_version)
    set_boards_table(pkg.boards())

    warnings = list(blockers) + profile.validate()
    issue = smbios.check_model_supports(pkg.boards(), profile.smbios_model, profile.macos_data)
    if issue:
        warnings.append(issue)

    drivers = oc.select_drivers(profile)
    tools = oc.select_tools(profile)
    efi = oc.build_skeleton(pkg, out_dir, drivers, tools, dl,
                            "gui" in profile.features, warnings)
    oc_dir = efi / "OC"

    acpi_add = acpi.install_ssdts(profile, dl, oc_dir / "ACPI")
    acpi_patch = acpi.acpi_patches(profile)

    kernel_add, kext_warnings = kexts.install_kexts(profile, dl, oc_dir / "Kexts")
    warnings.extend(kext_warnings)
    kernel_add.extend(_install_usb_map(profile, oc_dir / "Kexts", warnings))

    platform_info = smbios.platform_info(profile, pkg.tool("macserial"))

    config, config_warnings = configgen.build_config(
        profile, pkg.sample_plist, acpi_add, acpi_patch, kernel_add,
        [d for d in drivers if (oc_dir / "Drivers" / d).exists()],
        [t for t in tools if (oc_dir / "Tools" / t).exists()],
        platform_info, dl)
    warnings.extend(config_warnings)

    config_path = oc_dir / "config.plist"
    write_plist(config_path, config)
    ok(f"config.plist ecrit ({config_path.stat().st_size} octets)")

    validation = validate_config(pkg, config_path)
    if validation:
        warnings.append(validation)

    context = {
        "profile": profile,
        "oc_version": pkg.version,
        "acpi": acpi_add,
        "kernel_add": kernel_add,
        "drivers": [d for d in drivers if (oc_dir / "Drivers" / d).exists()],
        "boot_args": config["NVRAM"]["Add"][configgen.NVRAM_GUID]["boot-args"],
        "secure_boot": config["Misc"]["Security"]["SecureBootModel"],
        "warnings": warnings,
        "efi": efi,
    }
    report.write_report(out_dir / "RAPPORT.md", context)
    profile.save(out_dir / "profil.json")
    return context


def _install_usb_map(profile: Profile, kexts_dir: Path, warnings: list[str]) -> list[dict]:
    """Ajoute USBMap.kext / UTBMap.kext quand le profil en fournit une."""
    if profile.usb_map_kind == "none":
        return []
    if not profile.usb_map_file:
        warnings.append(
            f"usb_map_kind={profile.usb_map_kind} mais aucun fichier fourni "
            f"(--usb-map), le mappage USB n'a pas ete installe.")
        return []
    source = Path(profile.usb_map_file).expanduser()
    if not source.exists():
        warnings.append(f"fichier de mappage USB introuvable: {source}")
        return []
    try:
        if profile.usb_map_kind == "usbmap" and source.suffix == ".json":
            spec = usbmap.load_spec(source)
            spec.setdefault("model", profile.smbios_model)
            bundle = usbmap.build_usbmap(spec, kexts_dir)
        else:
            bundle = usbmap.import_existing(source, kexts_dir)
    except BuildError as exc:
        # Un mappage USB invalide ne doit pas faire perdre tout le reste du build.
        warnings.append(f"mappage USB non installe: {exc}")
        return []
    return [{
        "Arch": "x86_64",
        "BundlePath": bundle.name,
        "Comment": "Mappage des ports USB",
        "Enabled": True,
        "ExecutablePath": "",
        "MaxKernel": "",
        "MinKernel": "",
        "PlistPath": "Contents/Info.plist",
    }]


def validate_config(pkg: oc.OpenCorePackage, config_path: Path) -> str | None:
    """Passe le config.plist a ocvalidate (fourni avec OpenCorePkg)."""
    step("ocvalidate")
    binary = pkg.tool("ocvalidate")
    if binary is None:
        warn("ocvalidate indisponible pour cet OS hote, validation ignoree")
        return None
    result = subprocess.run([str(binary), str(config_path)],
                            capture_output=True, text=True, check=False)
    output = (result.stdout + result.stderr).strip()
    for line in output.splitlines():
        if line.strip():
            info(line)
    if result.returncode != 0:
        return f"ocvalidate signale des problemes dans config.plist (voir la sortie ci-dessus)"
    ok("config.plist valide par ocvalidate")
    return None
