# efibuild sur téléphone et tablette

Trois usages, du plus simple au plus complet.

## 1. Le configurateur, sans rien installer

Ouvrez [le site](https://myounsi577-droid.github.io/Efi/) : il calcule les SSDT,
les kexts, les quirks et les boot-args de votre machine, et donne la commande à
lancer. Il s'installe comme une application et fonctionne ensuite **hors ligne** :

| Appareil | Comment |
|---|---|
| iPhone / iPad | Safari → Partager → **Sur l'écran d'accueil** |
| Android | Chrome → menu ⋮ → **Installer l'application** |

C'est la seule option qui ne demande aucune installation, et elle suffit pour
préparer une configuration ou vérifier une compatibilité.

## 2. Android : construire réellement l'EFI

[Termux](https://f-droid.org/packages/com.termux/) (depuis F-Droid, pas le Play
Store dont la version est abandonnée) donne un vrai environnement Linux :

```bash
pkg update && pkg install python
curl -LO https://github.com/myounsi577-droid/Efi/raw/claude/hackintosh-efi-command-9imz6g/dist/efibuild.pyz
python efibuild.pyz
```

Le menu numéroté s'ouvre, l'EFI se construit vraiment : OpenCore, SSDT, kexts et
`config.plist` sont téléchargés et assemblés. Récupérez le dossier avec
`termux-setup-storage` puis copiez-le dans votre stockage partagé.

## 3. iPhone / iPad : construire aussi

### a-Shell — le plus simple

Installez **a-Shell** (gratuite, App Store), ouvrez-la et tapez :

```bash
curl -LO https://github.com/myounsi577-droid/Efi/raw/claude/hackintosh-efi-command-9imz6g/dist/efibuild.pyz
python3 efibuild.pyz
```

Le menu numéroté s'ouvre. Choisissez `1`, répondez aux questions, et l'EFI est
construit dans le dossier que vous indiquez.

Pour le récupérer, transformez-le en zip puis ouvrez l'app **Fichiers** →
**Sur mon iPhone** → **a-Shell** :

```bash
python3 -c "import shutil; shutil.make_archive('mon-efi','zip','mon-efi')"
```

Quelques points propres à a-Shell :

- Tapez `python3`, pas `python`.
- L'application n'a pas de dossier de téléchargement : tout se passe dans son
  propre espace, visible depuis Fichiers.
- Si `curl` échoue, essayez d'abord `pickFolder` puis relancez, ou téléchargez le
  `.pyz` avec Safari et déplacez-le dans le dossier a-Shell via l'app Fichiers.
- **a-Shell ne peut lancer aucun programme externe.** `macserial`, `ocvalidate` et
  `macrecovery` sont donc sautés ; l'outil le dit clairement et construit le reste.

### iSH — plus complet, plus lent

**iSH** émule un vrai Linux x86 :

```bash
apk add python3 curl
curl -LO https://github.com/myounsi577-droid/Efi/raw/claude/hackintosh-efi-command-9imz6g/dist/efibuild.pyz
python3 efibuild.pyz
```

Comme l'émulation est x86, `macserial` et `ocvalidate` **fonctionnent**, et
l'image de récupération Apple peut être téléchargée. Comptez plusieurs minutes
pour un build.

## Ce qui ne marche pas sur mobile, et pourquoi

**Les numéros de série et la validation.** Deux raisons se cumulent : OpenCorePkg
ne fournit `macserial` et `ocvalidate` qu'en x86 alors que les mobiles sont en
ARM, et a-Shell interdit de lancer un programme externe. L'outil détecte les deux
cas, l'annonce et poursuit : l'EFI est construit normalement, mais
`SystemSerialNumber` et `MLB` restent vides et le `config.plist` n'est pas validé
automatiquement. Terminez ces deux étapes sur un ordinateur :

```bash
efibuild validate mon-efi/EFI/OC/config.plist
```

iSH est l'exception : son émulation x86 exécute ces binaires.

**Le formatage de la clé USB.** `efibuild flash` a besoin d'un accès disque brut,
donc de root sur Android et d'un accès impossible sur iOS. Construisez l'EFI sur
le téléphone, puis écrivez la clé depuis un ordinateur.

## Honnêteté sur les tests

La dégradation ARM est vérifiée : un build complet exécuté en simulant un hôte
`aarch64` produit bien 9 kexts, 4 SSDT et un `config.plist`, en signalant les deux
outils ignorés. En revanche, Termux, a-Shell et iSH n'ont pas pu être testés
depuis l'environnement de développement. Si l'un d'eux se comporte autrement,
ouvrez une issue avec le message d'erreur.
