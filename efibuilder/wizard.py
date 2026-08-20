"""Assistant interactif: construit un profil en posant des questions."""
from __future__ import annotations

from efibuilder import data_files
from efibuilder.profile import (BLUETOOTH_CHOICES, DGPU_CHOICES, ETHERNET_CHOICES,
                                FEATURE_CHOICES, TOUCHPAD_CHOICES, WIFI_CHOICES,
                                Profile)


def _ask(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def _choose(question: str, choices: list[str], default: str) -> str:
    print(f"\n{question}")
    for index, choice in enumerate(choices, 1):
        mark = " (defaut)" if choice == default else ""
        print(f"  {index:>2}. {choice}{mark}")
    while True:
        answer = input(f"Choix [1-{len(choices)}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        if answer in choices:
            return answer
        print("Reponse invalide.")


def _yes(question: str, default: bool = True) -> bool:
    suffix = "[O/n]" if default else "[o/N]"
    answer = input(f"{question} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in {"o", "oui", "y", "yes"}


def run() -> Profile:
    print("Assistant efibuild - construction du profil materiel")
    print("Chaque reponse vide reprend la valeur par defaut.\n")

    platforms = [p["id"] for p in data_files.platforms()]
    print("Plateformes disponibles:")
    for entry in data_files.platforms():
        print(f"  {entry['id']:<26} {entry['name']}")
    platform_id = _ask("\nIdentifiant de plateforme", "coffee-lake-desktop")
    while platform_id not in platforms:
        platform_id = _ask("Identifiant inconnu, reessayez", "coffee-lake-desktop")
    plat = data_files.platform(platform_id)

    versions = [v["key"] for v in data_files.macos_versions()]
    macos = _choose("Version de macOS a installer", versions[6:], "sequoia")

    name = _ask("Nom de la machine", "Mon PC")
    chipset = _ask("Chipset (z390, b550, hm370...)", "")
    vendor = _ask("Marque de la carte mere / du portable (asus, gigabyte, msi, dell...)", "")

    profile = Profile(platform=platform_id, macos=macos, name=name,
                      chipset=chipset, motherboard_vendor=vendor)

    if plat["family"] == "amd":
        cores = _ask("Nombre de coeurs physiques du CPU (obligatoire pour les patchs AMD)", "8")
        profile.cpu_cores = int(cores or 0)
    if plat["family"] == "intel-laptop":
        profile.cpu_generation = _ask("Generation du CPU (8, 9, 10...)", "")

    if plat.get("igpu"):
        if _yes("Le processeur a-t-il un iGPU utilisable ?", True):
            profile.igpu = _ask("Nom de l'iGPU (uhd630, hd4600...)", "uhd630")
            profile.igpu_mode = _choose(
                "Role de l'iGPU", ["display", "headless"],
                "headless" if plat["family"] == "intel-desktop" else "display")
            options = list((plat["igpu"].get("options") or {}).keys())
            if options:
                profile.igpu_variant = _choose(
                    "Variante de framebuffer", options + ["(valeur par defaut)"],
                    "(valeur par defaut)")
                if profile.igpu_variant == "(valeur par defaut)":
                    profile.igpu_variant = ""
        else:
            profile.igpu, profile.igpu_mode = "none", "none"

    profile.dgpu = _choose("Carte graphique dediee", DGPU_CHOICES, "none")
    profile.ethernet = _choose("Carte reseau filaire", ETHERNET_CHOICES, "auto")
    profile.wifi = _choose("Wi-Fi", WIFI_CHOICES, "none")
    profile.bluetooth = _choose("Bluetooth", BLUETOOTH_CHOICES, "none")
    if plat["family"] == "intel-laptop":
        profile.touchpad = _choose("Trackpad", TOUCHPAD_CHOICES, "ps2")

    if _yes("Injecter l'audio analogique via AppleALC ?", True):
        profile.audio_layout = int(_ask("layout-id AppleALC (alcid)", "1") or 1)
    else:
        profile.audio = "none"

    profile.smbios = _ask("SMBIOS (vide = recommande par la plateforme)",
                          plat["smbios"]["default"])
    profile.debug = _yes("Activer le mode debug (verbose + logs) ?", True)

    print("\nFonctions optionnelles disponibles: " + ", ".join(FEATURE_CHOICES))
    features = _ask("Fonctions a activer (separees par des virgules)", "ota")
    profile.features = [f.strip() for f in features.split(",") if f.strip()]

    print()
    for warning in profile.validate():
        print(f"  ! {warning}")
    return profile
