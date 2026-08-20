"""Rapport de build: ce qui a ete pose dans l'EFI et ce qu'il reste a faire."""
from __future__ import annotations

import datetime
from pathlib import Path

BIOS_INTEL = {
    "A desactiver": [
        "Fast Boot", "Secure Boot", "CSM (Compatibility Support Module)",
        "Intel SGX", "Intel Platform Trust (PTT)", "CFG Lock (verrouillage du MSR 0xE2)",
        "Port serie / COM", "Port parallele", "Thunderbolt (le temps de l'installation)",
        "VT-d (sauf si DisableIoMapper reste actif)",
    ],
    "A activer": [
        "VT-x", "Above 4G Decoding", "Hyper-Threading", "Execute Disable Bit",
        "EHCI/XHCI Hand-off", "SATA en mode AHCI", "OS Type: Windows 8.1/10 UEFI Mode",
        "DVMT Pre-Allocated: 64 Mo minimum si iGPU utilise",
    ],
}
BIOS_AMD = {
    "A desactiver": [
        "Fast Boot", "Secure Boot", "CSM (Compatibility Support Module)",
        "Serial/COM Port", "Parallel Port",
    ],
    "A activer": [
        "SVM (virtualisation)", "Above 4G Decoding", "SATA en mode AHCI",
        "Resizable BAR uniquement si ResizeAppleGpuBars est configure",
    ],
}


def write_report(path: Path, context: dict) -> None:
    profile = context["profile"]
    lines: list[str] = []
    add = lines.append

    add(f"# EFI OpenCore - {profile.name}")
    add("")
    add(f"Genere le {datetime.date.today().isoformat()} par efibuild.")
    add("")
    add("## Cible")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Plateforme | {profile.platform_data['name']} |")
    add(f"| macOS | {profile.macos_data['name']} (macOS {profile.macos_data['release']}, "
        f"Darwin {profile.darwin}) |")
    add(f"| OpenCore | {context['oc_version']} |")
    add(f"| SMBIOS | {profile.smbios_model} |")
    add(f"| Chipset | {profile.chipset or 'non precise'} |")
    add(f"| Guide de reference | {profile.platform_data['guide']} |")
    add("")

    add("## ACPI")
    add("")
    if context["acpi"]:
        for entry in context["acpi"]:
            add(f"- `{entry['Path']}` - {entry['Comment']}")
    else:
        add("- aucun SSDT")
    add("")

    add("## Kexts")
    add("")
    add("| Kext | Role |")
    add("|---|---|")
    for entry in context["kernel_add"]:
        if "/" in entry["BundlePath"]:
            continue
        add(f"| `{entry['BundlePath']}` | {entry['Comment']} |")
    add("")

    add("## Pilotes UEFI")
    add("")
    for name in context["drivers"]:
        add(f"- `{name}`")
    add("")

    add("## Reglages notables du config.plist")
    add("")
    add(f"- boot-args: `{context['boot_args'] or '(aucun)'}`")
    add(f"- SecureBootModel: `{context['secure_boot']}`")
    add(f"- Quirks appliques depuis le guide {profile.platform_data['guide']}")
    add("")

    add("## Reglages BIOS a verifier")
    add("")
    table = BIOS_AMD if profile.family == "amd" else BIOS_INTEL
    for title, items in table.items():
        add(f"**{title}**")
        add("")
        for item in items:
            add(f"- {item}")
        add("")

    warnings = context["warnings"]
    add("## Points d'attention")
    add("")
    if warnings:
        for item in warnings:
            add(f"- {item}")
    else:
        add("- aucun")
    add("")

    add("## Etapes suivantes")
    add("")
    add("1. Verifier le rapport ci-dessus, en particulier les points d'attention.")
    add("2. Formater une cle USB en FAT32 (table de partition GPT).")
    add("3. Copier le dossier `EFI/` a la racine de la cle.")
    add("4. Copier `com.apple.recovery.boot/` a la racine de la cle "
        "(`efibuild recovery`).")
    add("5. Demarrer sur la cle, choisir l'entree macOS Recovery, formater le disque "
        "cible en APFS puis installer.")
    add("6. Apres installation, mapper les ports USB depuis macOS ou Windows "
        "(`efibuild usbmap`) et regenerer l'EFI.")
    add("")
    add("Le detail de chaque reglage est explique dans le guide Dortania: "
        "https://dortania.github.io/OpenCore-Install-Guide/")
    add("")

    path.write_text("\n".join(lines), encoding="utf-8")
