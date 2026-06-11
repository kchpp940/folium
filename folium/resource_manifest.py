"""
Resource manifest management for folium.

Provides repeatable, audit-friendly resource workflows:
  1. ``collect_resources(map)``        – walk the element tree, enumerate all
                                        JS/CSS resources.
  2. ``ResourceManifest``              – JSON-serialisable list of resources
                                        with checksums, original URLs, names.
  3. ``download_manifest(manifest, d)`` – download every resource into a
                                        directory *before* rendering, so the
                                        later HTML generation step never
                                        touches the network.

Typical offline pipeline::

    import folium
    from folium.resource_manifest import (
        collect_resources,
        download_manifest,
        ResourceManifest,
    )

    m = folium.Map()
    folium.plugins.HeatMap(...).add_to(m)
    folium.plugins.Fullscreen().add_to(m)

    # Step 1 – build manifest
    manifest = collect_resources(m)
    manifest.save("resources/manifest.json")

    # Step 2 – download everything up-front (audit-friendly)
    download_manifest(manifest, "resources/")

    # Step 3 – render *without* any network access
    folium.set_resource_mode("manifest", manifest_path="resources/manifest.json")
    m.save("offline_report.html")
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from folium.utilities import ResourceMode

_MANIFEST_VERSION = 1


def _m_url_to_filename(url: str) -> str:
    path = urlparse(url).path
    return os.path.basename(path)


@dataclass
class ResourceEntry:
    """Description of a single JS or CSS resource."""

    name: str
    type: str  # "js" | "css"
    url: str
    filename: str = ""
    sha256: Optional[str] = None
    size: Optional[int] = None
    note: Optional[str] = None

    def __post_init__(self):
        if not self.filename:
            self.filename = _m_url_to_filename(self.url)


@dataclass
class ResourceManifest:
    """A JSON-serialisable list of resources required by a map.

    Attributes
    ----------
    version : int
        Schema version.  Bumped whenever the on-disk format changes.
    resources : list[ResourceEntry]
        The enumerated resources.  Order is preserved (matches the order they
        would be loaded in the HTML head).
    local_path : str or None
        If set, default directory to look for cached files and to download
        into.
    """

    version: int = _MANIFEST_VERSION
    resources: list[ResourceEntry] = field(default_factory=list)
    local_path: Optional[str] = None

    # ------------------------------------------------------------------ I/O --
    @classmethod
    def load(cls, path: str | os.PathLike) -> "ResourceManifest":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        resources = [ResourceEntry(**r) for r in raw.get("resources", [])]
        return cls(
            version=raw.get("version", _MANIFEST_VERSION),
            resources=resources,
            local_path=raw.get("local_path"),
        )

    def save(self, path: str | os.PathLike) -> str:
        data = {
            "version": self.version,
            "resources": [asdict(r) for r in self.resources],
            "local_path": self.local_path,
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return os.path.abspath(path)

    # ------------------------------------------------------------- Lookups --
    def get(self, name: str) -> Optional[ResourceEntry]:
        for r in self.resources:
            if r.name == name:
                return r
        return None

    def __iter__(self) -> Iterable[ResourceEntry]:
        return iter(self.resources)

    def __len__(self) -> int:
        return len(self.resources)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_resources(root_element, include_map_defaults: bool = True) -> ResourceManifest:
    """Walk the element tree and enumerate every ``default_js``/``default_css``.

    Any :class:`~folium.elements.JSCSSMixin` found among the descendants
    contributes its resources.  Duplicate resource ``name``s are de-duplicated
    (first occurrence wins), which mirrors the render behaviour where
    ``figure.header.add_child(..., name=name)`` overwrites duplicates.
    """
    from folium.elements import JSCSSMixin

    seen: set[str] = set()
    entries: list[ResourceEntry] = []

    def _walk(elem):
        if isinstance(elem, JSCSSMixin):
            for name, url in elem.default_js:
                if name not in seen:
                    seen.add(name)
                    entries.append(ResourceEntry(name=name, type="js", url=url))
            for name, url in elem.default_css:
                if name not in seen:
                    seen.add(name)
                    entries.append(ResourceEntry(name=name, type="css", url=url))
        # branca.Element exposes children via ``_children`` dict
        for child in getattr(elem, "_children", {}).values():
            _walk(child)

    _walk(root_element)
    return ResourceManifest(resources=entries)


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download_url(
    url: str,
    timeout: float = 30.0,
    retries: int = 3,
    retry_backoff: float = 0.5,
) -> bytes:
    import time as _time

    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "folium-resource-manifest/1.0 "
                    "(https://github.com/python-visualization/folium)"
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < retries:
                _time.sleep(retry_backoff * (2 ** attempt))
    raise RuntimeError(
        f"Failed after {retries} attempt(s): {last_exc}"
    ) from last_exc


def download_manifest(
    manifest: ResourceManifest,
    local_dir: Optional[str] = None,
    *,
    verify: bool = True,
    overwrite: bool = False,
    timeout: float = 30.0,
    retries: int = 3,
) -> list[tuple[str, str]]:
    """Download every resource listed in *manifest* into *local_dir*.

    Parameters
    ----------
    manifest : ResourceManifest
    local_dir : str, optional
        Target directory.  Defaults to ``manifest.local_path`` or a
        ``resources/`` folder next to the manifest file when known.  A
        temporary directory is used as a last resort (not recommended for
        production).
    verify : bool, default True
        After download, compute sha256 of the downloaded bytes and, if the
        manifest entry already has a ``sha256``, check they match.
    overwrite : bool, default False
        If the target file already exists, re-download it.  By default an
        existing file with the same sha256 (if known) is reused as-is.
    timeout : float, default 30
        Per-attempt timeout in seconds.
    retries : int, default 3
        How many HTTP attempts per resource (with exponential backoff).

    Returns
    -------
    list of (name, absolute_path)
        Same order as ``manifest.resources``.
    """

    if local_dir is None:
        local_dir = manifest.local_path
    if local_dir is None:
        local_dir = os.path.join(tempfile.gettempdir(), "folium_resources")
        warnings.warn(
            f"No local_dir provided; downloading to temp dir {local_dir!r}. "
            "Pass local_dir=... for reproducible builds.",
            stacklevel=2,
        )
    os.makedirs(local_dir, exist_ok=True)

    results: list[tuple[str, str]] = []

    for entry in manifest:
        target = os.path.join(local_dir, entry.filename)
        needs_download = overwrite or not os.path.exists(target)

        if os.path.exists(target) and entry.sha256 and verify:
            existing = open(target, "rb").read()
            if _sha256_of_bytes(existing) != entry.sha256:
                warnings.warn(
                    f"Cached {entry.filename} sha256 mismatch; re-downloading.",
                    stacklevel=2,
                )
                needs_download = True

        if needs_download:
            try:
                data = _download_url(entry.url, timeout=timeout, retries=retries)
            except Exception as exc:  # pragma: no cover - network dependent
                raise RuntimeError(
                    f"Failed to download {entry.name} from {entry.url}: {exc}"
                ) from exc
            with open(target, "wb") as f:
                f.write(data)
        else:
            data = open(target, "rb").read()

        sha = _sha256_of_bytes(data)
        if entry.sha256 and verify and sha != entry.sha256:
            raise RuntimeError(
                f"sha256 mismatch for {entry.name}: expected {entry.sha256}, "
                f"got {sha}.  Pass verify=False to skip."
            )
        entry.sha256 = sha
        entry.size = len(data)

        results.append((entry.name, os.path.abspath(target)))

    if manifest.local_path is None:
        manifest.local_path = os.path.abspath(local_dir)

    return results


# ---------------------------------------------------------------------------
# Manifest-mode resolution helpers (used by _resolve_resource in elements.py)
# ---------------------------------------------------------------------------


def find_manifest_for_element(
    element,
    manifest_path: Optional[str],
    manifest_obj: Optional[ResourceManifest],
) -> Optional[ResourceManifest]:
    """Resolve a ResourceManifest from explicit arg / Figure context."""
    if manifest_obj is not None:
        return manifest_obj
    if manifest_path:
        return ResourceManifest.load(manifest_path)
    root = element.get_root()
    ctx = getattr(root, "_folium_resource_config", None)
    if ctx is not None:
        attached = getattr(ctx, "manifest", None)
        if attached is not None:
            return attached
        attached_path = getattr(ctx, "manifest_path", None)
        if attached_path:
            return ResourceManifest.load(attached_path)
    return None


def resolve_from_manifest(
    name: str,
    manifest: ResourceManifest,
    local_dir: Optional[str] = None,
) -> Optional[str]:
    """Return the absolute on-disk path for *name*, or None if not present.

    The resolved file is validated against the manifest ``sha256`` when
    available.  A failing check emits a warning and returns None so callers
    can fall back to another strategy (or fail hard).
    """
    entry = manifest.get(name)
    if entry is None:
        return None
    target_dir = local_dir or manifest.local_path
    if not target_dir:
        return None
    path = os.path.join(target_dir, entry.filename)
    if not os.path.exists(path):
        return None
    if entry.sha256:
        try:
            data = open(path, "rb").read()
        except OSError:
            return None
        if _sha256_of_bytes(data) != entry.sha256:
            warnings.warn(
                f"Manifest sha256 mismatch for resource {name!r} at {path}.",
                stacklevel=3,
            )
            return None
    return os.path.abspath(path)
