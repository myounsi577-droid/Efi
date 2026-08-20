"""Menu interactif ou tout se choisit avec un numero.

Fonctionne a l'identique sur Windows, macOS et Linux: uniquement input()
et print(), aucune dependance ni sequence terminal exotique.
"""
from __future__ import annotations

from pathlib import Path

from efibuilder import data_files, importer, oc, recovery, usbdisk, usbflash, usbmap
from efibuilder.build import build_efi
from efibuilder.net import Downloader, default_cache_dir
from efibuilder.profile import (BLUETOOTH_CHOICES, DGPU_CHOICES, ETHERNET_CHOICES,
                                FEATURE_CHOICES, TOUCHPAD_CHOICES, WIFI_CHOICES, Profile)
from efibuilder.util import BuildError, err, human_size, info, ok, step, warn

RULE = "-" * 68


class Cancelled(Exception):
    """L'utilisateur a choisi 0 pour revenir en arriere."""


# ------------------------------------------------------------------ briques
def choose(title: str, options: list[tuple[str, str]], default: int | None = None,
           back: str = "retour") -> int:
    """Affiche une liste numerotee et retourne l'index choisi (0 = Cancelled)."""
    print(f"\n{title}")
    print(RULE)
    for index, (label, note) in enumerate(options, 1):
        suffix = f"   {note}" if note else ""
        star = " *" if default == index else "  "
        print(f" {index:>2}.{star}{label}{suffix}")
    print(f"  0.  {back}")
    while True:
        raw = input(f"Numero{f' [{default}]' if default else ''} : ").strip()
        if not raw and default:
            return default
        if raw == "0":
            raise Cancelled
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw)
        print(f"Entrez un numero entre 0 et {len(options)}.")


def ask_number(question: str, default: int = 0, minimum: int = 0) -> int:
    while True:
        raw = input(f"{question} [{default}] : ").strip()
        if not raw:
            return default
        if raw.isdigit() and int(raw) >= minimum:
            return int(raw)
        print(f"Entrez un nombre entier (>= {minimum}).")


def ask_text(question: str, default: str = "") -> str:
    shown = f" [{default}]" if default else " [vide]"
    return input(f"{question}{shown} : ").strip() or default


def yes_no(question: str, default: bool = True) -> bool:
    index = choose(question, [("Oui", ""), ("Non", "")], default=1 if default else 2,
                   back="annuler")
    return index == 1


def pick(title: str, values: list[str], default: str) -> str:
    options = [(v, "") for v in values]
    return values[choose(title, options, default=values.index(default) + 1) - 1]


# ------------------------------------------------------------------- ecrans
def main_menu() -> int:
    while True:
        print(f"\n{RULE}\n  efibuild - generateur d'EFI OpenCore\n{RULE}")
        try:
            index = choose("Que voulez-vous faire ?", [
                ("Construire un EFI pour ma machine", ""),
                ("Repartir d'un EFI existant", "import + reconstruction"),
                ("Telecharger l'image de recuperation Apple", ""),
                ("Preparer une cle USB", "sauvegarde, formatage FAT32, copie"),
                ("Verifier si une machine est compatible", ""),
                ("Generer une USBMap", ""),
                ("Consulter les listes de reference", ""),
            ], back="quitter")
        except Cancelled:
            print("Au revoir.")
            return 0
        try:
            {1: screen_build, 2: screen_import, 3: screen_recovery, 4: screen_usb,
             5: screen_check, 6: screen_usbmap, 7: screen_lists}[index]()
        except Cancelled:
            continue
        except BuildError as exc:
            err(str(exc))
        except KeyboardInterrupt:
            print()
            warn("interrompu")


def _downloader() -> Downloader:
    return Downloader(cache_dir=default_cache_dir(), pins=data_files.pins())


def build_profile() -> Profile:
    """Questionnaire entierement numerote."""
    platforms = data_files.platforms()
    families = [
        ("Bureau Intel", "intel-desktop"),
        ("Portable Intel", "intel-laptop"),
        ("Station de travail Intel (HEDT)", "intel-hedt"),
        ("AMD", "amd"),
    ]
    family = families[choose("Type de machine", [(n, "") for n, _ in families]) - 1][1]
    subset = [p for p in platforms if p["family"] == family]
    entry = subset[choose("Plateforme (generation du processeur)",
                          [(p["name"], "") for p in subset]) - 1]

    versions = data_files.macos_versions()[6:]
    version = versions[choose("Version de macOS a installer",
                              [(v["name"], f"macOS {v['release']}") for v in versions],
                              default=len(versions) - 1) - 1]

    profile = Profile(platform=entry["id"], macos=version["key"])
    profile.name = ask_text("Nom de la machine", "Mon PC")
    profile.chipset = ask_text("Chipset (z390, b550, hm370... vide si inconnu)")
    vendors = ["asus", "gigabyte", "msi", "asrock", "dell", "hp", "lenovo", "acer",
               "autre / inconnu"]
    vendor = pick("Marque de la carte mere ou du portable", vendors, "autre / inconnu")
    profile.motherboard_vendor = "" if vendor.startswith("autre") else vendor

    if entry["family"] == "amd":
        profile.cpu_cores = ask_number("Nombre de coeurs physiques du processeur", 8, 1)
    if entry["family"] == "intel-laptop":
        profile.cpu_generation = ask_text("Generation du processeur (8, 9, 10...)")

    if entry.get("igpu"):
        if yes_no("Le processeur a-t-il un circuit graphique integre utilisable ?"):
            profile.igpu = ask_text("Nom du circuit integre", "uhd630")
            profile.igpu_mode = pick("Role du circuit integre",
                                     ["display", "headless"],
                                     "headless" if family == "intel-desktop" else "display")
            options = list((entry["igpu"].get("options") or {}).keys())
            if options:
                variants = options + ["valeur par defaut"]
                chosen = pick("Variante de framebuffer", variants, "valeur par defaut")
                profile.igpu_variant = "" if chosen == "valeur par defaut" else chosen
        else:
            profile.igpu, profile.igpu_mode = "none", "none"

    profile.dgpu = pick("Carte graphique dediee", DGPU_CHOICES, "none")
    profile.ethernet = pick("Carte reseau filaire", ETHERNET_CHOICES, "auto")
    profile.wifi = pick("Wi-Fi", WIFI_CHOICES, "none")
    profile.bluetooth = pick("Bluetooth", BLUETOOTH_CHOICES, "none")
    if profile.laptop:
        profile.touchpad = pick("Trackpad", TOUCHPAD_CHOICES, "ps2")

    if yes_no("Injecter l'audio analogique (AppleALC) ?"):
        profile.audio_layout = ask_number("layout-id AppleALC (alcid)", 1, 1)
    else:
        profile.audio = "none"

    profile.smbios = ask_text("SMBIOS (vide = recommande)", entry["smbios"]["default"])
    profile.sip = pick("Niveau de SIP", ["enabled", "partial", "disabled"], "enabled")
    profile.debug = yes_no("Activer le mode debug (verbose + journaux) ?")

    features: list[str] = []
    print(f"\nFonctions optionnelles (repondez plusieurs fois, 0 pour terminer)\n{RULE}")
    while True:
        remaining = [f for f in FEATURE_CHOICES if f not in features]
        if not remaining:
            break
        try:
            picked = remaining[choose(
                f"Ajouter une fonction  (deja choisies: {', '.join(features) or 'aucune'})",
                [(f, "") for f in remaining], back="terminer") - 1]
        except Cancelled:
            break
        features.append(picked)
    profile.features = features
    return profile


def screen_build() -> None:
    profile = build_profile()
    out = Path(ask_text("Dossier de sortie", "efi-out"))
    print()
    for warning in profile.validate():
        warn(warning)
    if not yes_no("Lancer la construction ?"):
        raise Cancelled
    context = build_efi(profile, out, _downloader())
    profile.save(out / "profil.json")
    print()
    ok(f"EFI pret: {context['efi']}")
    ok(f"Rapport: {out / 'RAPPORT.md'}")
    if yes_no("Telecharger aussi l'image de recuperation Apple ?", default=False):
        recovery.download_recovery(oc.fetch_opencore(_downloader()), profile.macos, out)


def screen_import() -> None:
    source = Path(ask_text("Chemin du config.plist ou du dossier EFI", "EFI"))
    config, path = importer.load_config(source)
    versions = data_files.macos_versions()[6:]
    version = versions[choose("Version de macOS visee",
                              [(v["name"], "") for v in versions],
                              default=len(versions) - 1) - 1]
    profile, notes = importer.import_profile(config, version["key"])
    importer.describe(profile, notes, path)
    out = Path(ask_text("Fichier de profil a ecrire", "profil.json"))
    profile.save(out)
    ok(f"profil ecrit dans {out}")
    if yes_no("Reconstruire un EFI depuis ce profil maintenant ?"):
        target = Path(ask_text("Dossier de sortie", "efi-neuf"))
        build_efi(profile, target, _downloader())


def screen_recovery() -> None:
    versions = data_files.macos_versions()
    version = versions[choose("Version de macOS a telecharger",
                              [(v["name"], f"macOS {v['release']}") for v in versions],
                              default=len(versions)) - 1]
    out = Path(ask_text("Dossier de sortie", "efi-out"))
    recovery.download_recovery(oc.fetch_opencore(_downloader()), version["key"], out)


def screen_check() -> None:
    profile = build_profile()
    print()
    blockers = profile.blockers()
    print("VERDICT:", "incompatible" if blockers else "compatible sous reserve")
    for item in blockers:
        err(item)
    for item in profile.validate():
        warn(item)


def screen_usbmap() -> None:
    index = choose("Mappage USB", [
        ("Ecrire un modele JSON a completer", ""),
        ("Generer USBMap.kext depuis un JSON rempli", ""),
        ("Importer une UTBMap.kext / UserUSBMap.plist", ""),
    ])
    if index == 1:
        usbmap.write_template(Path(ask_text("Fichier a ecrire", "usb-ports.json")))
    elif index == 2:
        spec = usbmap.load_spec(Path(ask_text("Fichier JSON", "usb-ports.json")))
        usbmap.build_usbmap(spec, Path(ask_text("Dossier de sortie", ".")))
    else:
        usbmap.import_existing(Path(ask_text("Chemin de la kext ou du plist")),
                               Path(ask_text("Dossier de sortie", ".")))


def screen_lists() -> None:
    index = choose("Quelle liste ?", [
        ("Plateformes", ""), ("Versions de macOS", ""),
        ("SMBIOS pour une version donnee", ""), ("Kexts du catalogue", ""),
    ])
    if index == 1:
        for entry in data_files.platforms():
            print(f"  {entry['id']:<26} {entry['name']}")
    elif index == 2:
        for entry in data_files.macos_versions():
            print(f"  {entry['key']:<14} {entry['name']:<22} macOS {entry['release']}")
    elif index == 3:
        versions = data_files.macos_versions()
        version = versions[choose("Version", [(v["name"], "") for v in versions],
                                  default=len(versions)) - 1]
        from efibuilder import smbios as smbios_mod
        for model in smbios_mod.models_for_macos(data_files.boards(), version):
            print(f"  {model}")
    else:
        for entry in data_files.kexts():
            print(f"  {entry['id']:<26} {entry.get('reason', '')}")


# ---------------------------------------------------------------- cle USB
def screen_usb() -> None:
    step("Preparation d'une cle USB")
    usable, rejected = usbflash.usable_devices()
    if rejected:
        info("disques ecartes pour votre securite:")
        for device, why in rejected:
            info(f"  {device.identifier:<12} {human_size(device.size):>9}  {why}")
    if not usable:
        warn("aucune cle USB amovible detectee. Branchez-la puis relancez.")
        warn("Sur Linux et Windows, lancez efibuild avec les droits administrateur.")
        raise Cancelled

    device = usable[choose("Choisissez la cle USB",
                           [(d.label, "") for d in usable]) - 1]
    efi_dir = Path(ask_text("Dossier EFI a copier", "efi-out/EFI"))
    if not efi_dir.is_dir():
        raise BuildError(f"dossier EFI introuvable: {efi_dir}")
    recovery_input = ask_text("Dossier com.apple.recovery.boot (vide = aucun)")
    recovery_dir = Path(recovery_input) if recovery_input else None

    print()
    step("Recapitulatif")
    info(f"cle           {device.identifier}  {human_size(device.size)}  {device.model}")
    info(f"EFI           {efi_dir}")
    info(f"recuperation  {recovery_dir or '(aucune)'}")

    archive = None
    if yes_no("Sauvegarder d'abord le contenu actuel de la cle dans un zip ?"):
        target = ask_text("Dossier de la sauvegarde", str(usbflash.downloads_dir()))
        archive = usbflash.backup_device(device, Path(target))

    index = choose("Que faire de la cle ?", [
        ("Tout effacer et formater en FAT32, puis copier", "efface TOUT le contenu"),
        ("Copier seulement, sans formater", "la cle doit deja etre en FAT32"),
    ])
    if index == 2:
        if not device.mountpoints:
            raise BuildError("la cle n'est montee nulle part: impossible de copier sans "
                             "formatage")
        usbflash.copy_payload(Path(device.mountpoints[0]), efi_dir, recovery_dir)
        ok("cle prete")
        return

    print()
    warn(f"TOUT le contenu de {device.identifier} ({human_size(device.size)}) va etre "
         f"efface definitivement.")
    if archive:
        info(f"une sauvegarde existe: {archive}")
    else:
        warn("aucune sauvegarde n'a ete faite.")
    confirmation = input(f"Tapez exactement '{device.identifier}' pour confirmer : ").strip()
    if confirmation != device.identifier:
        warn("confirmation incorrecte: rien n'a ete modifie.")
        raise Cancelled

    usbflash.format_device(device)
    mount = usbflash.wait_for_mount(device)
    usbflash.copy_payload(mount, efi_dir, recovery_dir)
    print()
    ok(f"cle prete: {mount}")
    info("Redemarrez sur cette cle et choisissez l'entree macOS Recovery.")
