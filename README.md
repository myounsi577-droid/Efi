# efibuild

Générateur d'EFI OpenCore complet pour Hackintosh : **une seule commande** produit
l'ACPI, les kexts, la USBMap, le `config.plist` et l'image de récupération Apple,
adaptés à votre matériel **et à la version de macOS que vous visez**.

Tout est aligné sur le [guide d'installation Dortania](https://dortania.github.io/OpenCore-Install-Guide/) :
les quirks, les SSDT et les SMBIOS sont extraits de ses tableaux, les binaires
viennent de leurs dépôts officiels (OpenCorePkg, acidanthera, OpenIntelWireless…),
et le `config.plist` produit est vérifié par `ocvalidate`.

Aucune dépendance : Python 3.9+ suffit.

## Démarrage rapide

```bash
# assistant interactif (questions guidées, puis construction)
./efibuild wizard -o mon-efi

# ou tout en une ligne
./efibuild build \
    --platform coffee-lake-desktop --chipset z390 --vendor gigabyte \
    --macos sequoia --igpu uhd630 --igpu-mode headless --dgpu amd-navi \
    --ethernet intel-i219 --audio-layout 7 --debug -o mon-efi

# image de récupération Apple (macrecovery d'OpenCorePkg)
./efibuild recovery --macos sequoia -o mon-efi

# contenu prêt à copier sur la clé USB
./efibuild usb --efi mon-efi/EFI --recovery mon-efi/com.apple.recovery.boot -o cle-usb
```

Le dossier de sortie contient :

```
mon-efi/
├── EFI/
│   ├── BOOT/BOOTx64.efi
│   └── OC/
│       ├── ACPI/            SSDT compilés choisis pour la plateforme
│       ├── Drivers/         OpenRuntime, HfsPlus, ResetNvramEntry…
│       ├── Kexts/           Lilu, VirtualSMC, WhateverGreen, USBMap…
│       ├── Tools/
│       └── config.plist     validé par ocvalidate
├── com.apple.recovery.boot/ image de récupération Apple (option --with-recovery)
├── profil.json              profil rejouable
└── RAPPORT.md              ce qui a été posé + réglages BIOS + points d'attention
```

## Ce que la commande fait à votre place

| Étape | Détail |
|---|---|
| OpenCore | dernière release d'`acidanthera/OpenCorePkg`, EFI nettoyée (aucun pilote inutile) |
| ACPI | SSDT pré-compilés de Dortania, **choisis selon le chipset** (SSDT-PMC seulement sur les vraies séries 300, SSDT-RHUB seulement sur Asus série 400, SSDT-CPUR seulement sur B550/A520+…), plus le renommage `_OSI` → `XOSI` quand SSDT-XOSI est retenu |
| Kexts | téléchargés depuis leurs dépôts, avec les PlugIns internes déclarés automatiquement dans `Kernel → Add`, et bornés par `MinKernel`/`MaxKernel` |
| USB | génération d'une `USBMap.kext` depuis un relevé de ports, ou import d'une `UTBMap.kext` / `UserUSBMap.plist` de USBToolBox |
| config.plist | quirks de la page Dortania de votre plateforme, DeviceProperties iGPU, boot-args, `PlatformInfo` complet |
| SMBIOS | modèle recommandé par plateforme, numéros de série générés par `macserial`, et **vérification que le board-id reçoit encore la version de macOS visée** |
| AMD | patchs noyau `AMD_Vanilla` avec `cpuid_cores_per_package` réglé sur votre nombre de cœurs, et patch AM5 activé pour les chipsets B650/X670/B850/X870 |
| Recovery | `macrecovery.py` d'OpenCorePkg avec le board-id/MLB officiel de la version demandée |
| Validation | `ocvalidate` de la même release d'OpenCore |

## Adaptation à la version de macOS

La version visée (`--macos`) change réellement le résultat :

- **AirportItlwm** est téléchargé dans la build correspondant exactement à la version.
- **AirportBrcmFixup** n'est plus installé au-delà de Ventura (Wi-Fi Broadcom retiré de macOS 14).
- **BlueToolFixup** n'est injecté qu'à partir de Big Sur (`MinKernel 20.0.0`).
- **macOS 14.4+** : `RestrictEvents` + `revpatch=sbvmm` + `SecureBootModel=Disabled` pour garder les mises à jour OTA.
- **macOS 26 (Tahoe)** : boot-arg `-ibtcompatbeta` pour le Bluetooth Intel, alerte sur la disparition d'AppleHDA (plus d'audio analogique) et sur les problèmes AMD de WhateverGreen.
- **macOS 11.3+** : `XhciPortLimit` est désactivé, la USBMap devient la seule solution correcte.
- **SMBIOS** : `efibuild list smbios --macos tahoe` ne liste que les modèles encore servis par Apple.

## Vérifier avant de construire

```bash
./efibuild check --platform amd-zen --chassis laptop --macos sequoia --wifi realtek
```

`check` ne télécharge rien et répond en quelques lignes : verdict, blocages
rédhibitoires, points d'attention. Le code de sortie vaut 1 si la machine est
incompatible, ce qui permet de l'enchaîner dans un script.

`build` refuse de construire quand un blocage est détecté (`--force` passe outre).
Aujourd'hui un seul cas bloque : **CPU sans AVX2 visé sur macOS 13+**.

Certaines pièces ne bloquent pas le démarrage mais n'ont aucun pilote macOS ;
elles sont signalées et doivent être remplacées : Wi-Fi Realtek, MediaTek et
Qualcomm récents (`--wifi realtek|mediatek|qualcomm`).

### Portables AMD

Ils sont hors du périmètre du guide Dortania, mais la communauté les fait tourner :
la plateforme `amd-zen-laptop` combine les patchs `AMD_Vanilla` et
[NootedRed](https://github.com/ChefKissInc/NootedRed), qui accélère les iGPU Vega
des Athlon Silver/Gold jusqu'aux Ryzen 5xxx, de macOS 10.15 à macOS 26.
`WhateverGreen` est alors remplacé par `NootedRed`, et `CpuTscSync` par
`ForgedInvariant`.

Ses quirks, son SMBIOS et ses boot-args sont calés sur un **HP 245 G8
(Athlon Silver 3050U) en fonctionnement** : les trois sections `Quirks` générées
sont identiques à celles de cet EFI de référence.

### Kexts non téléchargeables

Certains pilotes communautaires n'ont pas de release exploitable automatiquement
(`rtw88` pour le Wi-Fi Realtek PCIe, `RealtekBluetoothFirmware`,
`AppleMCEReporterDisabler`, `CtlnaAHCIPort`). L'outil ne les invente pas : il les
sélectionne, explique leur rôle et indique où les récupérer, et le rapport les
liste comme « à ajouter manuellement ».

## Repartir d'un EFI existant

```bash
./efibuild import mon-efi/EFI -o profil.json      # ou directement un config.plist
./efibuild build --profile profil.json -o efi-neuf
```

`import` relit un `config.plist` et en déduit un profil complet : plateforme,
châssis, SMBIOS, `ProcessorType`, nombre de cœurs (relu dans le patch AMD
`cpuid_cores_per_package`), réseau / Wi-Fi / Bluetooth / trackpad d'après les
kexts, framebuffer iGPU, `layout-id` audio, niveau de SIP, mappage USB et
fonctions activées.

Il signale aussi ce qu'il ne sait pas reproduire : kexts hors catalogue,
quirks de votre EFI qui diffèrent de ceux de la plateforme, champs à compléter
à la main. C'est le chemin pour **remettre à jour un EFI qui marche** (OpenCore
et kexts récents) ou le **porter vers une version plus récente de macOS**
(`--macos tahoe`), sans repartir de zéro.

## Commandes

```
efibuild build       construire un EFI complet
efibuild import      déduire un profil d'un EFI existant
efibuild check       verdict de compatibilité, sans téléchargement
efibuild wizard      assistant interactif puis construction
efibuild recovery    télécharger l'image de récupération Apple
efibuild usbmap      template | build | import  (USBMap.kext)
efibuild usb         préparer le contenu de la clé USB
efibuild list        platforms | macos | smbios | kexts | features
efibuild info        détail d'une plateforme (SSDT, quirks, framebuffers)
efibuild validate    passer un config.plist à ocvalidate
```

`efibuild <commande> --help` détaille toutes les options.

## Mappage USB

macOS ne gère que 15 ports par contrôleur : le relevé doit être fait **sur la machine cible**.

```bash
./efibuild usbmap template -o usb-ports.json   # modèle commenté
# relever les ports avec USBToolBox (Windows), Hackintool ou IORegistryExplorer (macOS)
./efibuild usbmap build --input usb-ports.json --model iMac19,1 -o mon-efi/EFI/OC/Kexts

# ou réutiliser une sortie USBToolBox
./efibuild build ... --usb-map-kind usbtoolbox --usb-map ~/UTBMap.kext
```

## Reproductibilité

Par défaut, les dernières releases sont résolues via l'API GitHub. `--pin` utilise
les versions vérifiées de `efibuilder/data/pins.json`, `--offline` n'utilise que le
cache local (`~/.cache/efibuild`), et `--oc-version 1.0.7` fige OpenCore.
Chaque build écrit un `profil.json` rejouable avec `--profile`.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Limites assumées

- efibuild **ne formate aucun disque** : la commande `usb` prépare un dossier et
  affiche les commandes à lancer vous-même.
- Le relevé des ports USB et le choix du `layout-id` audio dépendent de la machine :
  aucun outil ne peut les deviner à distance.
- Alder Lake et plus récent ne sont pas couverts par le guide Dortania : partez de
  `comet-lake-desktop` et ajoutez les correctifs spécifiques.
- `ROM` est généré aléatoirement ; pour les iServices, remplacez-le par l'adresse MAC
  de votre carte réseau principale.

## Sources

- Guide d'installation : <https://dortania.github.io/OpenCore-Install-Guide/>
- SSDT pré-compilés : <https://github.com/dortania/Getting-Started-With-ACPI>
- OpenCore : <https://github.com/acidanthera/OpenCorePkg>
- Patchs noyau AMD : <https://github.com/AMD-OSX/AMD_Vanilla>
