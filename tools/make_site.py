#!/usr/bin/env python3
"""Assemble la page web du configurateur dans docs/index.html.

La page embarque les memes tables JSON que la CLI: ce script doit etre relance
apres toute modification de efibuilder/data/, sinon le site diverge de l'outil.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "efibuilder" / "data"
SITE = ROOT / "site"
OUT = ROOT / "docs" / "index.html"
ARTIFACT = ROOT / "site" / "build" / "artifact.html"

# Le site autonome a besoin d'un document complet: sans doctype la page bascule en
# mode quirks, et sans meta viewport les mobiles la rendent en 980 px puis dezooment.
SHELL = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Calcule les SSDT, kexts, quirks et boot-args exiges par votre machine, puis la commande efibuild a lancer.">
<meta name="theme-color" content="#EDEFF3" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#12161D" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Nomenclature">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icon.svg">
{body}
</html>
"""

TABLES = ("platforms", "macos", "kexts", "smbios", "boards")
SMBIOS_FIELDS = ("model", "board_id", "cpu", "gpu")


def payload() -> dict:
    data = {name: json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
            for name in TABLES}
    # La page n'a pas besoin des colonnes de dates du tableau SMBIOS.
    data["smbios"] = {"models": [{k: m[k] for k in SMBIOS_FIELDS}
                                 for m in data["smbios"]["models"]]}
    return data


def main() -> int:
    html = (SITE / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__ENGINE__*/", (SITE / "engine.js").read_text(encoding="utf-8"))
    html = html.replace("/*__DATA__*/",
                        json.dumps(payload(), ensure_ascii=False, separators=(",", ":")))
    html = html.replace("/*__APP__*/", (SITE / "app.js").read_text(encoding="utf-8"))
    # L'artifact est insere dans un document fourni par l'hote: contenu seul.
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(html, encoding="utf-8")

    head, _, rest = html.partition("</style>")
    document = SHELL.format(body=f"{head}</style>\n</head>\n<body>{rest}\n</body>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(document, encoding="utf-8")
    for path in (OUT, ARTIFACT):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
