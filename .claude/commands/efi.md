---
description: Construire un EFI OpenCore complet (ACPI, kexts, USBMap, config.plist, recovery Apple) pour un PC donne
argument-hint: [description du PC et de la version de macOS visee]
allowed-tools: Bash(./efibuild:*), Bash(python3 -m efibuilder:*), Read, Glob
---

Construis un EFI OpenCore complet avec l'outil `efibuild` de ce depot pour la
machine decrite ci-dessous.

Machine et version de macOS visees : $ARGUMENTS

Marche a suivre :

1. Si la description ne suffit pas a choisir une plateforme, liste les
   plateformes disponibles (`./efibuild list platforms`) et demande a
   l'utilisateur les informations manquantes : generation du CPU, chipset,
   marque de la carte mere, iGPU, GPU dedie, carte reseau, Wi-Fi/Bluetooth,
   et pour AMD le nombre de coeurs physiques.
2. Verifie que le SMBIOS retenu recoit encore la version de macOS demandee :
   `./efibuild list smbios --macos <version>`.
3. Affiche le detail de la plateforme choisie (`./efibuild info <plateforme>`)
   et explique brievement a l'utilisateur les SSDT et quirks qui seront poses.
4. Lance la construction avec `./efibuild build` en passant toutes les options
   deduites, `--with-recovery` si l'utilisateur veut aussi l'image de
   recuperation Apple, et `-o` vers un dossier de sortie clair.
5. Lis `RAPPORT.md` du dossier de sortie et restitue en francais :
   - ce qui a ete installe (SSDT, kexts, pilotes),
   - les reglages BIOS a appliquer,
   - chaque point d'attention signale, avec ce que l'utilisateur doit faire.
6. Rappelle les deux etapes qui ne peuvent pas etre automatisees a distance :
   le mappage USB (`./efibuild usbmap template`) qui doit etre releve sur la
   machine cible, et le remplacement de `ROM` par l'adresse MAC reelle de la
   carte reseau pour les iServices.

Ne formate jamais de disque et ne lance aucune commande destructive :
pour la cle USB, utilise `./efibuild usb` qui prepare un dossier et affiche les
commandes que l'utilisateur lancera lui-meme.
