"""Interface en ligne de commande d'efibuild."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from efibuilder import __version__, data_files, oc, recovery, smbios, usbdisk, usbmap, wizard
from efibuilder.build import build_efi, validate_config
from efibuilder.net import Downloader, default_cache_dir
from efibuilder.profile import (BLUETOOTH_CHOICES, DGPU_CHOICES, ETHERNET_CHOICES,
                                FEATURE_CHOICES, TOUCHPAD_CHOICES, WIFI_CHOICES,
                                Profile, set_boards_table)
from efibuilder.util import BuildError, err, info, ok, step, warn


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="efibuild",
        description="Construit un EFI OpenCore complet (ACPI, kexts, USBMap, config.plist, "
                    "recovery Apple) en suivant le guide Dortania.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemples:\n"
               "  efibuild wizard -o mon-efi\n"
               "  efibuild build --platform coffee-lake-desktop --chipset z390 \\\n"
               "      --macos sequoia --igpu uhd630 --igpu-mode headless \\\n"
               "      --dgpu amd-navi --ethernet intel-i219 --cores 8 -o mon-efi\n"
               "  efibuild recovery --macos sequoia -o mon-efi\n"
               "  efibuild usb --efi mon-efi/EFI --recovery mon-efi/com.apple.recovery.boot \\\n"
               "      -o cle-usb\n")
    parser.add_argument("--version", action="version", version=f"efibuild {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cache", type=Path, default=default_cache_dir(),
                        help="dossier de cache des telechargements")
    common.add_argument("--offline", action="store_true",
                        help="n'utiliser que le cache local")
    common.add_argument("--pin", action="store_true",
                        help="utiliser les versions epinglees (data/pins.json) au lieu des "
                             "dernieres releases")
    common.add_argument("--token", default=None,
                        help="jeton GitHub (evite la limite de requetes de l'API)")

    # ------------------------------------------------------------------ build
    b = sub.add_parser("build", parents=[common], help="construire un EFI complet")
    b.add_argument("-o", "--out", type=Path, default=Path("efi-out"),
                   help="dossier de sortie")
    b.add_argument("--profile", type=Path, help="profil JSON existant")
    b.add_argument("--save-profile", type=Path, help="enregistrer le profil utilise")
    b.add_argument("--platform", help="identifiant de plateforme (efibuild list platforms)")
    b.add_argument("--macos", default="sequoia", help="version de macOS visee")
    b.add_argument("--name", default="Mon PC", help="nom de la machine")
    b.add_argument("--chassis", choices=["auto", "desktop", "laptop"], default="auto",
                   help="type de machine (defaut: deduit de la plateforme)")
    b.add_argument("--force", action="store_true",
                   help="construire malgre un materiel declare incompatible")
    b.add_argument("--chipset", default="", help="chipset (z390, b550, hm370...)")
    b.add_argument("--vendor", dest="motherboard_vendor", default="",
                   help="marque de la carte mere (asus, gigabyte, msi, dell...)")
    b.add_argument("--cpu-name", default="", help="modele exact du CPU (documentation)")
    b.add_argument("--cpu-gen", dest="cpu_generation", default="",
                   help="generation du CPU (8, 9, 10...)")
    b.add_argument("--cores", dest="cpu_cores", type=int, default=0,
                   help="coeurs physiques (patch AMD cpuid_cores_per_package)")
    b.add_argument("--igpu", default="none", help="modele d'iGPU (uhd630, hd4600, none)")
    b.add_argument("--igpu-mode", choices=["display", "headless", "none"], default="display")
    b.add_argument("--igpu-variant", default="",
                   help="variante de framebuffer (efibuild info <plateforme>)")
    b.add_argument("--dgpu", choices=DGPU_CHOICES, default="none")
    b.add_argument("--no-audio", action="store_true", help="ne pas installer AppleALC")
    b.add_argument("--audio-layout", type=int, default=1, help="layout-id AppleALC (alcid)")
    b.add_argument("--ethernet", choices=ETHERNET_CHOICES, default="auto")
    b.add_argument("--wifi", choices=WIFI_CHOICES, default="none")
    b.add_argument("--bluetooth", choices=BLUETOOTH_CHOICES, default="none")
    b.add_argument("--touchpad", choices=TOUCHPAD_CHOICES, default="none")
    b.add_argument("--no-nvme", action="store_true", help="pas de SSD NVMe")
    b.add_argument("--smbios", default="", help="modele SMBIOS (vide = recommande)")
    b.add_argument("--processor-type", type=int, default=0,
                   help="ProcessorType SMBIOS (0 = auto; 1537 est courant sur portable AMD)")
    b.add_argument("--sip", choices=["enabled", "partial", "disabled"], default="enabled",
                   help="niveau de SIP ecrit dans csr-active-config")
    b.add_argument("--no-serials", action="store_true",
                   help="ne pas generer numero de serie / MLB / UUID")
    b.add_argument("--usb-map", type=Path, help="USBMap JSON, UserUSBMap.plist ou .kext")
    b.add_argument("--usb-map-kind", choices=["none", "usbmap", "usbtoolbox"], default="none")
    b.add_argument("--feature", action="append", default=None, metavar="NOM",
                   help=f"fonction optionnelle, repetable ({', '.join(FEATURE_CHOICES)})")
    b.add_argument("--boot-arg", action="append", default=[], metavar="ARG",
                   help="boot-arg supplementaire, repetable")
    b.add_argument("--cpuid-data", default="", help="Cpuid1Data (spoof CPUID)")
    b.add_argument("--cpuid-mask", default="", help="Cpuid1Mask (spoof CPUID)")
    b.add_argument("--debug", action="store_true", help="config de debug (verbose, logs)")
    b.add_argument("--oc-version", default="latest", help="version d'OpenCore (ex. 1.0.7)")
    b.add_argument("--with-recovery", action="store_true",
                   help="telecharger aussi l'image de recuperation Apple")

    # ----------------------------------------------------------------- wizard
    w = sub.add_parser("wizard", parents=[common], help="assistant interactif puis build")
    w.add_argument("-o", "--out", type=Path, default=Path("efi-out"))
    w.add_argument("--save-profile", type=Path)
    w.add_argument("--with-recovery", action="store_true")

    # --------------------------------------------------------------- recovery
    r = sub.add_parser("recovery", parents=[common],
                       help="telecharger l'image de recuperation Apple (macrecovery)")
    r.add_argument("--macos", default="sequoia")
    r.add_argument("-o", "--out", type=Path, default=Path("efi-out"))
    r.add_argument("--diagnostics", action="store_true",
                   help="telecharger l'image de diagnostic Apple")
    r.add_argument("--board-id", help="forcer un board-id")
    r.add_argument("--mlb", help="forcer un MLB")
    r.add_argument("--show", action="store_true",
                   help="afficher les parametres sans rien telecharger")

    # ----------------------------------------------------------------- usbmap
    u = sub.add_parser("usbmap", help="generer ou importer une USBMap.kext")
    usub = u.add_subparsers(dest="usbmap_command", required=True)
    ut = usub.add_parser("template", help="ecrire un modele JSON a completer")
    ut.add_argument("-o", "--out", type=Path, default=Path("usb-ports.json"))
    ub = usub.add_parser("build", help="generer USBMap.kext depuis un JSON")
    ub.add_argument("--input", type=Path, required=True)
    ub.add_argument("--model", default="", help="SMBIOS a inscrire dans la kext")
    ub.add_argument("-o", "--out", type=Path, default=Path("."))
    ui = usub.add_parser("import", help="importer une UTBMap.kext / UserUSBMap.plist")
    ui.add_argument("--input", type=Path, required=True)
    ui.add_argument("-o", "--out", type=Path, default=Path("."))

    # -------------------------------------------------------------------- usb
    s = sub.add_parser("usb", help="preparer le contenu de la cle USB d'installation")
    s.add_argument("--efi", type=Path, required=True, help="dossier EFI genere")
    s.add_argument("--recovery", type=Path, help="dossier com.apple.recovery.boot")
    s.add_argument("-o", "--out", type=Path, default=Path("usb-stage"))

    # ------------------------------------------------------------------- list
    l = sub.add_parser("list", help="lister les donnees de reference")
    l.add_argument("what", choices=["platforms", "macos", "smbios", "kexts", "features"])
    l.add_argument("--macos", help="pour 'smbios': filtrer sur une version de macOS")

    # ------------------------------------------------------------------ check
    ch = sub.add_parser("check",
                        help="verifier si une machine peut faire tourner macOS, "
                             "sans rien telecharger")
    ch.add_argument("--platform", required=True)
    ch.add_argument("--macos", default="sequoia")
    ch.add_argument("--chassis", choices=["auto", "desktop", "laptop"], default="auto")
    ch.add_argument("--chipset", default="")
    ch.add_argument("--cores", dest="cpu_cores", type=int, default=0)
    ch.add_argument("--igpu", default="none")
    ch.add_argument("--dgpu", choices=DGPU_CHOICES, default="none")
    ch.add_argument("--ethernet", choices=ETHERNET_CHOICES, default="auto")
    ch.add_argument("--wifi", choices=WIFI_CHOICES, default="none")
    ch.add_argument("--bluetooth", choices=BLUETOOTH_CHOICES, default="none")
    ch.add_argument("--smbios", default="")

    # ------------------------------------------------------------------- info
    i = sub.add_parser("info", help="detail d'une plateforme")
    i.add_argument("platform")

    # --------------------------------------------------------------- validate
    v = sub.add_parser("validate", parents=[common],
                       help="valider un config.plist avec ocvalidate")
    v.add_argument("config", type=Path)
    return parser


# ------------------------------------------------------------------- commandes
def _downloader(args) -> Downloader:
    return Downloader(cache_dir=args.cache, offline=args.offline, token=args.token,
                      pins=data_files.pins(), use_pins=args.pin)


def _profile_from_args(args) -> Profile:
    if args.profile:
        profile = Profile.load(args.profile)
        if args.platform:
            profile.platform = args.platform
        if args.macos != "sequoia":
            profile.macos = args.macos
        return profile
    if not args.platform:
        raise BuildError("--platform est requis (ou --profile). "
                         "Voir 'efibuild list platforms'.")
    features = args.feature if args.feature is not None else ["ota"]
    unknown = [f for f in features if f not in FEATURE_CHOICES]
    if unknown:
        raise BuildError(f"fonction inconnue: {', '.join(unknown)}. "
                         f"Disponibles: {', '.join(FEATURE_CHOICES)}")
    return Profile(
        platform=args.platform, macos=args.macos, name=args.name, chipset=args.chipset,
        chassis="" if args.chassis == "auto" else args.chassis,
        motherboard_vendor=args.motherboard_vendor, cpu_name=args.cpu_name,
        cpu_generation=args.cpu_generation, cpu_cores=args.cpu_cores,
        igpu=args.igpu, igpu_mode=args.igpu_mode, igpu_variant=args.igpu_variant,
        dgpu=args.dgpu, audio="none" if args.no_audio else "alc",
        audio_layout=args.audio_layout, ethernet=args.ethernet, wifi=args.wifi,
        bluetooth=args.bluetooth, touchpad=args.touchpad, nvme=not args.no_nvme,
        smbios=args.smbios, serials=not args.no_serials,
        processor_type=args.processor_type, sip=args.sip,
        usb_map_kind=args.usb_map_kind,
        usb_map_file=str(args.usb_map) if args.usb_map else "",
        features=features, boot_args=args.boot_arg, debug=args.debug,
        oc_version=args.oc_version, cpuid_data=args.cpuid_data, cpuid_mask=args.cpuid_mask)


def cmd_build(args, profile: Profile | None = None) -> int:
    profile = profile or _profile_from_args(args)
    dl = _downloader(args)
    context = build_efi(profile, args.out, dl, force=getattr(args, "force", False))
    if getattr(args, "save_profile", None):
        profile.save(args.save_profile)
        ok(f"profil enregistre dans {args.save_profile}")
    if getattr(args, "with_recovery", False):
        pkg = oc.fetch_opencore(dl, profile.oc_version)
        recovery.download_recovery(pkg, profile.macos, args.out)
    _summary(context, args.out)
    return 0


def _summary(context: dict, out: Path) -> None:
    profile = context["profile"]
    print()
    step("Resume")
    info(f"plateforme      {profile.platform_data['name']}")
    info(f"macOS           {profile.macos_data['name']}")
    info(f"OpenCore        {context['oc_version']}")
    info(f"SMBIOS          {profile.smbios_model}")
    info(f"SSDT            {len(context['acpi'])}")
    info(f"kexts           {sum(1 for e in context['kernel_add'] if '/' not in e['BundlePath'])}")
    info(f"boot-args       {context['boot_args'] or '(aucun)'}")
    if context["warnings"]:
        print()
        warn(f"{len(context['warnings'])} point(s) d'attention:")
        for item in context["warnings"]:
            info(f"- {item}")
    print()
    ok(f"EFI: {context['efi']}")
    ok(f"Rapport detaille: {out / 'RAPPORT.md'}")


def cmd_wizard(args) -> int:
    profile = wizard.run()
    target = args.save_profile or (args.out / "profil.json")
    args.out.mkdir(parents=True, exist_ok=True)
    profile.save(target)
    ok(f"profil enregistre dans {target}")
    return cmd_build(args, profile)


def cmd_recovery(args) -> int:
    if args.show:
        recovery.describe(args.macos)
        return 0
    dl = _downloader(args)
    pkg = oc.fetch_opencore(dl, "latest")
    recovery.download_recovery(pkg, args.macos, args.out, args.diagnostics,
                               args.board_id, args.mlb)
    return 0


def cmd_usbmap(args) -> int:
    if args.usbmap_command == "template":
        usbmap.write_template(args.out)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    if args.usbmap_command == "build":
        spec = usbmap.load_spec(args.input)
        if args.model:
            spec["model"] = args.model
        usbmap.build_usbmap(spec, args.out)
        return 0
    usbmap.import_existing(args.input, args.out)
    return 0


def cmd_usb(args) -> int:
    usbdisk.stage(args.efi, args.recovery, args.out)
    return 0


def cmd_list(args) -> int:
    if args.what == "platforms":
        for entry in data_files.platforms():
            limit = entry.get("max_macos")
            suffix = f"  (jusqu'a {data_files.macos(limit)['name']})" if limit else ""
            print(f"{entry['id']:<26} {entry['name']}{suffix}")
    elif args.what == "macos":
        for entry in data_files.macos_versions():
            print(f"{entry['key']:<14} {entry['name']:<22} macOS {entry['release']:<6} "
                  f"Darwin {entry['darwin']:<3} board-id {entry['recovery']['board_id']}")
    elif args.what == "smbios":
        models = data_files.smbios_models()
        if args.macos:
            entry = data_files.macos(args.macos)
            supported = set(smbios.models_for_macos(data_files.boards(), entry))
            print(f"SMBIOS servant encore {entry['name']} "
                  f"(source: boards.json d'OpenCorePkg):")
            for model in models:
                if model["model"] in supported:
                    print(f"  {model['model']:<18} {model['cpu']:<22} {model['gpu']}")
            return 0
        for model in models:
            print(f"{model['model']:<18} {model['cpu']:<22} {model['board_id']:<24} "
                  f"jusqu'a {model['last_supported']}")
    elif args.what == "kexts":
        for entry in data_files.kexts():
            print(f"{entry['id']:<24} {entry['repo']:<38} {entry.get('reason', '')}")
    else:
        for name in FEATURE_CHOICES:
            print(name)
    return 0


def cmd_check(args) -> int:
    profile = Profile(
        platform=args.platform, macos=args.macos,
        chassis="" if args.chassis == "auto" else args.chassis,
        chipset=args.chipset, cpu_cores=args.cpu_cores, igpu=args.igpu,
        dgpu=args.dgpu, ethernet=args.ethernet, wifi=args.wifi,
        bluetooth=args.bluetooth, smbios=args.smbios)
    print(f"Machine    : {profile.platform_data['name']}"
          f" ({'portable' if profile.laptop else 'bureau'})")
    print(f"macOS vise : {profile.macos_data['name']}")
    print(f"SMBIOS     : {profile.smbios_model}")
    print(f"Guide      : {profile.platform_data['guide']}")
    print()
    blockers = profile.blockers()
    if blockers:
        print("VERDICT: incompatible")
        print()
        for item in blockers:
            print(f"  [bloquant] {item}")
    else:
        print("VERDICT: compatible, sous reserve des points ci-dessous")
    warnings = profile.validate()
    if warnings:
        print()
        for item in warnings:
            print(f"  [attention] {item}")
    print()
    for note in profile.macos_data["notes"]:
        print(f"  [{profile.macos_data['name']}] {note}")
    return 1 if blockers else 0


def cmd_info(args) -> int:
    entry = data_files.platform(args.platform)
    print(f"{entry['id']} - {entry['name']}")
    print(f"famille        : {entry['family']}")
    print(f"guide          : {entry['guide']}")
    print(f"SMBIOS conseille: {entry['smbios']['default']}")
    if entry.get("max_macos"):
        print(f"macOS maximum  : {data_files.macos(entry['max_macos'])['name']}")
    print("\nSSDT:")
    for ssdt in entry.get("ssdt", []):
        condition = "  (conditionnel)" if ssdt.get("when") else ""
        print(f"  {ssdt['file']:<28} {ssdt.get('reason', '')}{condition}")
    igpu = entry.get("igpu")
    if igpu:
        print("\niGPU:")
        print(f"  chemin        : {igpu['path']}")
        print(f"  cle           : {igpu.get('key')}")
        if igpu.get("display"):
            print(f"  avec ecran    : {igpu['display']}")
        if igpu.get("headless"):
            print(f"  sans ecran    : {igpu['headless']}")
        for name, value in (igpu.get("options") or {}).items():
            print(f"  variante {name:<12}: {value}")
    print("\nQuirks (deltas par rapport au Sample.plist):")
    for section, values in entry.get("quirks", {}).items():
        for key, value in values.items():
            shown = value["value"] if isinstance(value, dict) else value
            note = "  (conditionnel)" if isinstance(value, dict) else ""
            print(f"  {section}.{key:<26} {shown}{note}")
    for note in entry.get("notes", []):
        print(f"\nnote: {note}")
    return 0


def cmd_validate(args) -> int:
    dl = _downloader(args)
    pkg = oc.fetch_opencore(dl, "latest")
    set_boards_table(pkg.boards())
    issue = validate_config(pkg, args.config)
    return 1 if issue else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "build": cmd_build, "wizard": cmd_wizard, "recovery": cmd_recovery,
        "usbmap": cmd_usbmap, "usb": cmd_usb, "list": cmd_list, "info": cmd_info,
        "check": cmd_check,
        "validate": cmd_validate,
    }
    try:
        return handlers[args.command](args)
    except BuildError as exc:
        err(str(exc))
        return 1
    except KeyError as exc:
        err(str(exc).strip('"'))
        return 1
    except KeyboardInterrupt:
        print()
        err("interrompu")
        return 130


if __name__ == "__main__":
    sys.exit(main())
