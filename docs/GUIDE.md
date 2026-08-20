# Guide d'utilisation

Ce document complète le `README.md` avec le déroulé complet d'une installation.

## 1. Rassembler les informations sur la machine

| Information | Où la trouver |
|---|---|
| Génération du CPU | `lscpu` (Linux), Gestionnaire des tâches (Windows), CPU-Z |
| Chipset | manuel de la carte mère, HWiNFO, `lspci` |
| iGPU / GPU dédié | Gestionnaire de périphériques, `lspci -nn \| grep VGA` |
| Carte réseau | `lspci -nn \| grep -i ethernet` |
| Wi-Fi / Bluetooth | `lspci` / `lsusb`, ou le manuel du portable |
| Codec audio | HWiNFO, `lspci -nn \| grep -i audio`, puis [layouts AppleALC](https://github.com/acidanthera/AppleALC/wiki/Supported-codecs) |

Puis :

```bash
./efibuild list platforms          # choisir la plateforme
./efibuild info coffee-lake-desktop  # voir SSDT, quirks et framebuffers
```

## 0. Lancer l'outil

| Système | Commande |
|---|---|
| Linux / macOS | `./efibuild` |
| Windows | `efibuild.cmd` |
| Partout (sans lanceur) | `python3 -m efibuilder` |

Sans argument, le menu numéroté s'ouvre. Toutes les commandes décrites plus bas
y sont accessibles, et l'inverse est vrai : le menu n'est qu'une façade sur la
même CLI.

## 1 bis. Vérifier que la machine est compatible

```bash
./efibuild check --platform amd-zen --chassis laptop --macos sequoia --wifi realtek
```

Matériel qui interdit purement et simplement un Hackintosh :

| Matériel | Pourquoi |
|---|---|
| CPU sans SSE4.2 | bloqué à macOS 10.13 |
| CPU sans AVX2 | bloqué à macOS 12 |
| Alder Lake et plus récent | hors du guide Dortania, correctifs à assembler soi-même |

Matériel jouable mais hors guide, à traiter comme un projet :

| Matériel | Situation |
|---|---|
| APU AMD de portable (Athlon/Ryzen mobiles) | plateforme `amd-zen-laptop` : `AMD_Vanilla` + `NootedRed` ; gestion d'énergie CPU, batterie et veille à régler à la main |

Matériel remplaçable, qui n'empêche pas de démarrer :

| Matériel | Solution |
|---|---|
| Wi-Fi Realtek / MediaTek / Qualcomm récent | remplacer la carte M.2 par une Intel AX200/AX210 ou une Broadcom, ou utiliser un dongle USB |
| NVIDIA Maxwell/Pascal et plus récent | aucun pilote depuis macOS 10.14 : désactiver le GPU (`--dgpu nvidia-unsupported`) |
| Optane / Micron 3D XPoint | retirer le module |

## 2. Choisir la version de macOS

```bash
./efibuild list macos
./efibuild list smbios --macos sequoia
```

Points de bascule à connaître :

| Version | Conséquence |
|---|---|
| macOS 10.14 (Mojave) | SSE4.2 obligatoire |
| macOS 11.3 (Big Sur) | `XhciPortLimit` inopérant : mappage USB obligatoire |
| macOS 12 (Monterey) | iGPU Ivy Bridge et NVIDIA Kepler supprimés |
| macOS 13 (Ventura) | AVX2 obligatoire, iGPU Haswell supprimé |
| macOS 14 (Sonoma) | Wi-Fi Broadcom natif supprimé ; OTA à partir de 14.4 : `revpatch=sbvmm` |
| macOS 15 (Sequoia) | Broadcom uniquement via AppleBCMWLANCompanion (VT-d requis) |
| macOS 26 (Tahoe) | AppleHDA supprimé (pas d'audio analogique), 6 SMBIOS seulement, `-ibtcompatbeta` pour le Bluetooth Intel |

## 3. Construire l'EFI

```bash
./efibuild build \
    --platform coffee-lake-desktop --chipset z390 --vendor gigabyte \
    --macos sequoia \
    --igpu uhd630 --igpu-mode headless \
    --dgpu amd-navi \
    --ethernet intel-i219 --audio-layout 7 \
    --wifi none --bluetooth none \
    --feature ota --debug \
    --name "PC Z390" --save-profile z390.json \
    -o mon-efi
```

- `--igpu-mode headless` : l'iGPU sert au décodage matériel mais l'affichage passe
  par la carte dédiée. `display` si l'écran est branché sur la carte mère.
- `--debug` : `-v debug=0x100 keepsyms=1`, logs OpenCore et OpenShell. À retirer
  une fois l'installation réussie, puis reconstruire.
- `--feature` : `ota`, `sidecar`, `hibernation`, `gui`, `audio-chime`,
  `linux-boot`, `cpufriend`, `light-sensor`, `rtc-fix`, `no-avx2`.

Le build échoue proprement si un fichier indispensable ne peut pas être récupéré ;
les éléments optionnels manquants apparaissent en points d'attention.

## 4. Télécharger l'image de récupération Apple

```bash
./efibuild recovery --macos sequoia -o mon-efi
```

`macrecovery.py` d'OpenCorePkg interroge `osrecovery.apple.com` avec le board-id
et le MLB officiels de la version demandée (table `recovery_urls.txt` d'OpenCorePkg).
Les serveurs Apple doivent être joignables directement : un proxy d'entreprise
bloque souvent cet appel.

## 5. Préparer la clé USB

```bash
./efibuild usb --efi mon-efi/EFI --recovery mon-efi/com.apple.recovery.boot -o cle-usb
```

La commande prépare un dossier et affiche les commandes de formatage adaptées à
votre système ; **elle ne touche à aucun disque**. La clé doit être en FAT32
avec une table de partition GPT, et contenir `EFI/` et `com.apple.recovery.boot/`
à sa racine.

## 5 bis. Écrire la clé automatiquement

```bash
./efibuild flash --efi mon-efi/EFI --recovery mon-efi/com.apple.recovery.boot
```

Séquence : liste numérotée des clés → sauvegarde zip dans Téléchargements →
formatage FAT32/GPT → copie. Il faut retaper l'identifiant exact de la clé pour
que l'effacement démarre.

Droits nécessaires : administrateur sous Windows, `sudo` sous Linux
(macOS n'en demande pas pour un disque externe).

## 6. Régler le BIOS

Le fichier `RAPPORT.md` du dossier de sortie liste les réglages à appliquer
(Intel ou AMD). Les deux plus souvent oubliés : **CSM désactivé** et
**Above 4G Decoding activé**.

## 7. Après l'installation : mapper les ports USB

```bash
./efibuild usbmap template -o usb-ports.json
# relever les ports avec USBToolBox / Hackintool / IORegistryExplorer
./efibuild usbmap build --input usb-ports.json --model iMac19,1 \
    -o mon-efi/EFI/OC/Kexts
```

Puis reconstruire en déclarant la carte :

```bash
./efibuild build --profile z390.json \
    --usb-map-kind usbmap --usb-map usb-ports.json -o mon-efi
```

## 8. Finitions

- Remplacer `PlatformInfo → Generic → ROM` par l'adresse MAC de la carte réseau
  principale (nécessaire pour iMessage / FaceTime).
- Retirer `--debug` et reconstruire une fois le système stable.
- Vérifier la gestion d'énergie CPU, la veille, l'audio et le Wi-Fi avant de
  considérer l'installation terminée.

## Mettre à jour un EFI existant

```bash
./efibuild import /Volumes/EFI/EFI -o profil.json
$EDITOR profil.json          # compléter chipset, motherboard_vendor, usb_map_file
./efibuild build --profile profil.json --macos tahoe -o efi-neuf
```

Quelques précautions :

- **Gardez vos SSDT.** Ceux générés par SSDTTime sont taillés sur votre DSDT ;
  ceux d'efibuild sont génériques. Recopiez les vôtres dans `EFI/OC/ACPI` et
  reprenez les entrées correspondantes de `ACPI → Add`.
- **Gardez votre mappage USB** : `--usb-map <votre UTBMap.kext>`.
- **Comparez avant de remplacer.** Démarrez d'abord depuis une clé USB avec le
  nouvel EFI, l'ancien reste intact sur le disque.
- `import` liste les kexts hors catalogue : ils ne seront pas régénérés, il faut
  les recopier à la main.

## Dépannage

| Symptôme | Piste |
|---|---|
| Panic `Couldn't allocate runtime area` | basculer `EnableWriteUnprotector` / `RebuildAppleMemoryMap`, activer Above 4G Decoding |
| Écran noir après le mode verbeux | essayer le framebuffer alternatif (`efibuild info <plateforme>`), ou `-wegnoegpu` |
| Blocage sur `PCI Configuration Begin` | ports USB non mappés, ou `npci=0x2000` |
| Panic `AppleIntelI210Ethernet` | chemin PCI de l'I225 différent (voir le point d'attention du rapport) |
| Redémarrage immédiat sur AMD | patchs `AMD_Vanilla` absents ou `cpuid_cores_per_package` faux (`--cores`) |

Le guide de dépannage complet est chez Dortania :
<https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/troubleshooting.html>
