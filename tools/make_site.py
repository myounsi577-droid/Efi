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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
