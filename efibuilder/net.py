"""Telechargements: cache local, releases GitHub, fichiers bruts."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from efibuilder.util import BuildError, human_size, info, warn

USER_AGENT = "efibuild (+https://github.com/myounsi577-droid/Efi)"
GITHUB_API = "https://api.github.com"


def default_cache_dir() -> Path:
    base = os.environ.get("EFIBUILD_CACHE")
    if base:
        return Path(base)
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "efibuild"


@dataclass
class Resolved:
    """Un asset resolu: d'ou il vient et en quelle version."""
    repo: str
    tag: str
    asset: str
    url: str
    source: str  # "api" | "pin"


class Downloader:
    def __init__(self, cache_dir: Path, offline: bool = False, token: str | None = None,
                 pins: dict | None = None, use_pins: bool = False):
        self.cache_dir = cache_dir
        self.offline = offline
        self.token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        self.pins = pins or {}
        self.use_pins = use_pins
        self._release_cache: dict[str, dict] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ HTTP
    def _open(self, url: str, accept: str | None = None, timeout: int = 60):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if accept:
            req.add_header("Accept", accept)
        if self.token and url.startswith(GITHUB_API):
            req.add_header("Authorization", f"Bearer {self.token}")
        return urllib.request.urlopen(req, timeout=timeout)

    def get_json(self, url: str) -> dict:
        with self._open(url, accept="application/vnd.github+json") as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch(self, url: str, filename: str | None = None, retries: int = 3) -> Path:
        """Telecharge une URL dans le cache et retourne le chemin local."""
        name = filename or url.rsplit("/", 1)[-1]
        key = re.sub(r"[^A-Za-z0-9._-]", "_", url)[-120:]
        dest = self.cache_dir / key
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        if self.offline:
            raise BuildError(f"mode hors ligne: {name} absent du cache ({self.cache_dir})")
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with self._open(url, timeout=180) as resp, open(dest, "wb") as fh:
                    total = 0
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
                        total += len(chunk)
                info(f"telecharge {name} ({human_size(total)})")
                return dest
            except Exception as exc:  # noqa: BLE001 - on retente puis on remonte
                last = exc
                if dest.exists():
                    dest.unlink()
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
        raise BuildError(f"telechargement impossible: {url} ({last})")

    # ---------------------------------------------------------------- GitHub
    def latest_release(self, repo: str) -> dict | None:
        if repo in self._release_cache:
            return self._release_cache[repo]
        if self.offline or self.use_pins:
            return None
        try:
            data = self.get_json(f"{GITHUB_API}/repos/{repo}/releases/latest")
        except Exception as exc:  # noqa: BLE001 - le fallback pins prend le relais
            warn(f"API GitHub indisponible pour {repo} ({exc}); repli sur les versions epinglees")
            return None
        self._release_cache[repo] = data
        return data

    def resolve(self, repo: str, asset_regex: str) -> Resolved:
        """Trouve l'asset d'une release correspondant a asset_regex."""
        release = self.latest_release(repo)
        if release:
            pattern = re.compile(asset_regex)
            for asset in release.get("assets", []):
                if pattern.search(asset["name"]):
                    return Resolved(repo, release.get("tag_name", "?"), asset["name"],
                                    asset["browser_download_url"], "api")
            warn(f"aucun asset ne correspond a /{asset_regex}/ dans {repo} {release.get('tag_name')}")
        pin = self.pins.get(repo)
        if not pin:
            raise BuildError(
                f"impossible de resoudre {repo}: pas de release accessible et aucune version "
                f"epinglee dans data/pins.json")
        url = f"https://github.com/{repo}/releases/download/{pin['tag']}/{pin['asset']}"
        return Resolved(repo, pin["tag"], pin["asset"], url, "pin")

    def github_raw(self, repo: str, path: str, ref: str = "master") -> Path:
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
        return self.fetch(url, filename=path.rsplit("/", 1)[-1])
