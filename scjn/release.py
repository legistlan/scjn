"""The `scjn-leyes` release's own readers, disk-first, plus the one downloader
that puts the release on disk in the first place (issue #209, Fase 3 of
#206/#207).

Two things happen together because they cannot be separated: these functions
moved here out of a downstream package's own module, and they stopped
downloading. Every reader below (`download_scjn_leyes_index`,
`download_scjn_leyes_corpus`, `markdown_de_snapshot`,
`download_scjn_leyes_catalog`, `iter_current_federal_laws`, `local_slugs`)
takes a `cache_dir` defaulting to `scjn.cache.CACHE_DIR` and only ever opens
files under it — none of them make an HTTP request, and a missing asset
raises `AssetNotCached` rather than attempting one. Only
`download_scjn_leyes_assets` (and, through it, the `scjn download` CLI) talks
to the network; a caller who wants the corpus on disk runs that first,
exactly once, and every reader afterwards is offline.

This package holds SCJN data only: nothing here links a snapshot to the
*Diario Oficial de la Federación* note that published it. That linking lives
outside this repository.
"""

import gzip
import io
import json
import os
import tarfile
from collections.abc import Iterator
from pathlib import Path

import requests

from scjn import cache
from scjn.outline import strip_markers
from scjn.cache import (
    _SCJN_LEYES_RELEASE,
    ESTATUTOS,
    LINEAMIENTOS,
    REGLAMENTOS,
    TRATADOS,
    Coleccion,
)
from scjn.header import _fecha
from scjn.state import ARCHIVO_ESTADO

#: User-Agent for the `scjn-leyes` release's own GitHub requests -- the only
#: network this module does (the SCJN crawl itself lives in `scjn.api`, with
#: its own headers).
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; legistlan-scjn/1.0)"}

#: Environment variables a GitHub token is read from, the first one set wins
#: -- `GH_TOKEN` before `GITHUB_TOKEN`, the `gh` CLI's own precedence.
_TOKEN_VARIABLES = ("GH_TOKEN", "GITHUB_TOKEN")

#: The repository that owns the releases, as ``<owner>/<name>``, when
#: `RELEASE_REPOSITORY_VARIABLE` is not set: this repository. The variable
#: points a reader at a mirror (another ``<owner>/<name>`` holding releases of
#: the same shape); changing the default is a release of this package.
DEFAULT_RELEASE_REPOSITORY = "legistlan/scjn"
RELEASE_REPOSITORY_VARIABLE = "SCJN_RELEASE_REPOSITORY"


def release_repository() -> str:
    """The ``<owner>/<name>`` repository the release lookups ask GitHub about:
    `RELEASE_REPOSITORY_VARIABLE` from the environment when it is set to
    something other than whitespace, else `DEFAULT_RELEASE_REPOSITORY`. Read
    on every call, so a test or a run against a mirror can point one process at
    another owner without reloading the module."""
    return os.environ.get(RELEASE_REPOSITORY_VARIABLE, "").strip() or DEFAULT_RELEASE_REPOSITORY


def release_api_url(tag: str) -> str:
    """The GitHub REST API URL of the release tagged `tag` in `release_repository`."""
    return f"https://api.github.com/repos/{release_repository()}/releases/tags/{tag}"


def _github_api_headers() -> dict:
    """`_HEADERS` plus `Authorization: Bearer <token>` when `GH_TOKEN` or
    `GITHUB_TOKEN` is set in the environment, for the one request this module
    makes to the GitHub REST API (the release's asset listing).

    Unauthenticated, GitHub allows 60 API requests an hour per IP address,
    which a shared CI runner exhausts: pull request #298's `test (scjn, 3.12)`
    cell failed with `403 rate limit exceeded` on this very lookup while the
    3.10 and 3.11 cells of the same run passed. Authenticated with a runner's
    own `GITHUB_TOKEN` the quota is per repository and three orders of
    magnitude higher. Without a token nothing changes -- an installed package
    never needs one -- and the asset downloads themselves go through
    `github.com/<owner>/<repo>/releases/download/`, which is outside this
    quota, so they keep the plain `_HEADERS`.
    """
    headers = dict(_HEADERS)
    for variable in _TOKEN_VARIABLES:
        token = os.environ.get(variable, "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
            break
    return headers

#: GitHub's own cap on a release's asset count -- its 422 error text is
#: "file_count limited to 1000 assets per release", hit publishing
#: `scjn-reglamentos` on 2026-09-10 (1082 tarballs + 3 more assets, issue
#: #223). A collection over this cap is published as a numbered series of
#: release tags instead of re-bundling anything -- see `_tag_de_parte`.
LIMITE_ASSETS_POR_RELEASE = 1000

#: How many parts `_assets_de_partes` will walk before giving up -- a
#: publishing bug that never 404s (a typo'd tag reused forever, say) must
#: raise, not loop forever.
_MAX_PARTES = 50

#: The index published alongside the per-law tarballs, with one entry per
#: instrument (name, asset, snapshot count, classification) and no text at
#: all, so listing the corpus costs a few hundred KB instead of the ~380 MB
#: the whole corpus weighs.
ASSET_INDICE_GLOBAL = "indice-global.json.gz"

#: The per-law metadata the SCJN's own search carries and this release
#: publishes (issue #215, off #203's items 1/2/5): its subject
#: classification, whether it is still in force, and the SCJN's own
#: one-paragraph abstract of it. One value per law, not per reform — the
#: `Reforma` rows carry none of the three — which is why they live in each
#: law's `estado.json` and in `instrumentos` here, and not in a snapshot's
#: provenance header: `vigencia` describes the law *today*, while a snapshot
#: describes it at one reform in the past.
CAMPOS_METADATOS = ("materia", "vigencia", "resumen")

#: The rest of the SCJN's classification of an instrument, added in issue #8.
#: `categoria_ordenamiento` says what kind of instrument it is (`LEY`,
#: `CODIGO`, `REGLAMENTO`, ...), `ambito` its scope (`FEDERAL`, `ESTATAL`,
#: `TRATADOS INTERNACIONALES`), `pais` its country (the one field that tells
#: the instruments of `scjn-tratados` apart) and, for a state-level
#: instrument, `estado` and `municipio`. Like `CAMPOS_METADATOS` they are one
#: value per instrument, live in `estado.json` and in the index, never in a
#: snapshot's provenance header, and an index older than the fields
#: simply lacks them.
CAMPOS_CLASIFICACION = ("categoria_ordenamiento", "ambito", "pais", "estado", "municipio")


class AssetNotCached(Exception):
    """A release asset a reader needs is not on disk yet.

    Raised instead of a network request by every reader in this module
    (issue #209): the disk-first contract means a caller is told which
    command populates the cache, not left waiting on an HTTP request a pure
    reader has no business making. Downloading is `download_scjn_leyes_assets`
    (or the `scjn download` CLI built on it) alone.
    """

    def __init__(self, nombre: str, cache_dir: Path, *, coleccion: str = "leyes"):
        if coleccion == "leyes":
            # Unchanged since issue #209 -- the message a caller already
            # depends on (see the module's own doctest in docs/source).
            comando = (
                f"scjn download --slug {nombre.removesuffix('.tgz')}"
                if nombre.endswith(".tgz")
                else "scjn download"
            )
        else:
            comando = (
                f"scjn download --coleccion {coleccion} --id {nombre.removesuffix('.tgz')}"
                if nombre.endswith(".tgz")
                else f"scjn download --coleccion {coleccion}"
            )
        super().__init__(f"'{nombre}' is not cached under {cache_dir} -- run `{comando}`")
        self.nombre = nombre
        self.cache_dir = cache_dir


def construye_indice_global(instrumentos: list[dict], generado: str) -> dict:
    """The `indice-global.json.gz` payload for `instrumentos` -- see
    `ASSET_INDICE_GLOBAL`.

    Each entry of `instrumentos` is ``{"slug", "nombre", "asset"?,
    "snapshots"?, <each of CAMPOS_CLASIFICACION>?, "materia"?, "vigencia"?,
    "resumen"?}``. The result is::

        {"generado", "coleccion",
         "instrumentos": {slug: {"nombre", "asset", "snapshots",
                                 "categoria_ordenamiento"?, "ambito"?,
                                 "pais"?, "estado"?, "municipio"?,
                                 "materia"?, "vigencia"?, "resumen"?}}}

    `snapshots` is a plain count, read verbatim off the entry (0 when it has
    none): the leyes tarballs carry the snapshots and `estado.json` only, so
    there is no per-instrument table to derive it from.

    `materia`/`vigencia`/`resumen` (`CAMPOS_METADATOS`, issue #215) are copied
    from the instrument entry when it carries them — the SCJN's own
    classification, in-force status and abstract, one value per law rather
    than per snapshot. A law with no value for one of them simply has no such
    key: absent, never `null`, so a reader can tell "we have not asked" from
    "the SCJN says nothing", and so the asset does not grow by 315 nulls
    while the fields are being backfilled.

    The five `CAMPOS_CLASIFICACION` (`categoria_ordenamiento`, `ambito`,
    `pais`, `estado`, `municipio`, issue #8) are copied the same way, with the
    same absent-never-`null` rule.

    There is no `codNota` section: the DOF is not a source of this
    repository, and an older copy of the payload (an old cache or a mirror;
    no published index has one) that still has one is read without it being used (`download_scjn_leyes_index`).

    `coleccion` is written as the literal `"leyes"`. It stopped being a
    parameter in issue #189, when `leyes` became the project's only
    collection, but stays in the payload: it is a field of a *published*
    asset that readers can already see, and dropping it would change the
    release format for no gain.
    """
    entradas_instrumentos: dict[str, dict] = {}
    for instrumento in sorted(instrumentos, key=lambda i: i["slug"]):
        slug = instrumento["slug"]
        entradas_instrumentos[slug] = {
            "nombre": instrumento["nombre"],
            "asset": instrumento.get("asset") or f"{slug}.tgz",
            "snapshots": instrumento.get("snapshots", 0),
        }
        for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS):
            valor = instrumento.get(campo)
            if valor:
                entradas_instrumentos[slug][campo] = valor

    return {
        "generado": generado,
        "coleccion": "leyes",
        "instrumentos": entradas_instrumentos,
    }


def _tag_de_parte(base: str, n: int) -> str:
    """The release tag of part `n` of the collection whose part 1 is `base`
    -- `base` itself for `n == 1`, `f"{base}-{n}"` after. The one place this
    naming rule lives (issue #223): a collection over `LIMITE_ASSETS_POR_RELEASE`
    is published as this numbered series rather than re-bundled, so every
    part after the first keeps the bare tag's own asset names and URLs.
    """
    return base if n == 1 else f"{base}-{n}"


def _assets_de_release(tag: str, timeout: int) -> dict[str, str] | None:
    """One release tag's own asset map, name -> download URL -- or `None`
    when GitHub has no release under that tag (a 404, meaning the series
    ends here). Any other error status raises (`raise_for_status`), so a
    rate limit (403) or an outage (5xx) is never mistaken for "no more
    parts" (issue #223)."""
    url = release_api_url(tag)
    response = requests.get(url, headers=_github_api_headers(), timeout=timeout)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return {
        asset["name"]: asset["browser_download_url"] for asset in response.json()["assets"]
    }


#: `_assets_de_partes`'s own memo of how many parts its last walk found, by
#: `base` tag -- a private implementation detail (nothing published records
#: a part count, decision 3), read by `scjn.cli` only to word a download
#: session's summary line. Never updated by a caller that mocks
#: `_assets_scjn_leyes`/`_assets_scjn_reglamentos` outright, which is fine:
#: nothing depends on it being current, only on it existing.
_ULTIMO_NUMERO_DE_PARTES: dict[str, int] = {}


def _assets_de_partes(base: str, timeout: int = 30) -> dict[str, str]:
    """Every asset across `base`'s whole series of release parts, merged
    name -> download URL (issue #223, decision 1) -- probing
    `_tag_de_parte(base, 1)`, `(base, 2)`, ... until one comes back `None`
    (decision 3: GitHub is the single source of truth for where an asset
    lives, so nothing here or on disk records a part count).

    Part 1 missing is a real error (`_assets_de_release` raises via
    `raise_for_status`, since GitHub answers a truly nonexistent tag with a
    404 same as an out-of-range part -- so a missing part 1 is instead
    surfaced as `KeyError`, never read as "empty corpus"). A name published
    in more than one part keeps the **lowest** part's URL -- a duplicate can
    only be a publishing bug, and the live coverage test in
    `test_release_red.py` is what catches it. Bounded by `_MAX_PARTES` so a
    publishing bug that never 404s cannot loop forever.
    """
    fusion: dict[str, str] = {}
    n = 1
    while True:
        if n > _MAX_PARTES:
            raise RuntimeError(
                f"'{base}' tiene mas de {_MAX_PARTES} partes -- algo esta mal "
                "publicado (ver issue #223)"
            )
        tag = _tag_de_parte(base, n)
        assets = _assets_de_release(tag, timeout)
        if assets is None:
            if n == 1:
                raise KeyError(f"el release '{base}' no existe")
            break
        for nombre, url in assets.items():
            fusion.setdefault(nombre, url)
        n += 1
    _ULTIMO_NUMERO_DE_PARTES[base] = n - 1
    return fusion


def _mensaje_ningun_asset(base: str, nombre: str) -> str:
    """`KeyError` text for an asset no part of `base`'s series publishes --
    named parts consulted, so the message says exactly where it looked
    (issue #223)."""
    n_partes = _ULTIMO_NUMERO_DE_PARTES.get(base, 1)
    partes = ", ".join(f"'{_tag_de_parte(base, n)}'" for n in range(1, n_partes + 1))
    return (
        f"ninguna parte del release '{base}' publica el asset '{nombre}' "
        f"(partes consultadas: {partes})"
    )


def _assets_scjn_leyes(timeout: int = 30) -> dict[str, str]:
    """Every asset of the `scjn-leyes` release, name -> download URL --
    merged across every part of its series (`_assets_de_partes`, issue
    #223; one part today, decision 7). Network -- used by the downloader
    only, never by a reader."""
    return _assets_de_partes(_SCJN_LEYES_RELEASE, timeout)


def _url_de_asset(nombre: str, timeout: int) -> str:
    """The download URL of `nombre` in the `scjn-leyes` release's series.

    Raises `KeyError` while no part of the series publishes that asset yet —
    expected before a human has read `scripts/empaqueta_scjn_leyes.py`'s own
    manifest and published it by hand (this corpus has no automated publish
    path, on purpose — see that script). Used by the downloader only."""
    urls = _assets_scjn_leyes(timeout)
    if nombre not in urls:
        raise KeyError(_mensaje_ningun_asset(_SCJN_LEYES_RELEASE, nombre))
    return urls[nombre]


def _read_asset(
    nombre: str, cache_dir, *, release: str = _SCJN_LEYES_RELEASE, coleccion: str = "leyes"
) -> bytes:
    """`nombre`'s bytes off the on-disk cache, with no network fallback --
    the basic disk-only building block every reader in this module uses
    (issue #209). Raises `AssetNotCached` when the file is not there.

    `release`/`coleccion` (issue #220) are read by the `scjn-reglamentos`
    readers below, parameterizing this same helper rather than duplicating
    it; every `download_scjn_leyes_*` reader keeps calling this with the
    defaults, unchanged."""
    directorio = cache.resuelve_cache_dir(cache_dir)
    ruta = directorio / release / nombre
    if not ruta.exists():
        raise AssetNotCached(nombre, directorio, coleccion=coleccion)
    return ruta.read_bytes()


#: `download_scjn_leyes_index`'s in-process memo, keyed by which cache
#: directory it was read through. A batch of thousands of `legal_provisions`
#: calls must not re-read (let alone re-decompress) the same index once per
#: note.
_MEMO_INDICE_GLOBAL: dict[str, dict] = {}


def download_scjn_leyes_index(*, cache_dir=None) -> dict:
    """The `scjn-leyes` release's index (`ASSET_INDICE_GLOBAL`), as the dict
    `construye_indice_global` wrote. An older copy of the index (the published
    one has none) from before the DOF linking was removed from this
    repository may have a `codNota` section; it is dropped here, so no reader
    sees it.

    Memoized per cache directory for the life of the process, so reading a
    whole batch of laws reads the file once. Reads only `cache_dir`
    (`scjn.cache.CACHE_DIR` when not given) — raises `AssetNotCached` while
    the index is not cached there yet; run `scjn download` first.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    clave = str(directorio)
    if clave in _MEMO_INDICE_GLOBAL:
        return _MEMO_INDICE_GLOBAL[clave]

    contenido = _read_asset(ASSET_INDICE_GLOBAL, directorio)
    indice = json.loads(gzip.decompress(contenido).decode("utf-8"))
    # An older copy of the index (not the published one) from before the DOF
    # linking left this repository may carry a `codNota` section: tolerated,
    # never used.
    indice.pop("codNota", None)
    _MEMO_INDICE_GLOBAL[clave] = indice
    return indice


def markdown_de_snapshot(
    slug: str, archivo: str, *, cache_dir=None, outline: bool = True
) -> str:
    """The text of one snapshot, read out of its law's already-cached
    `<slug>.tgz` asset. Raises `AssetNotCached` when that tarball is not on
    disk under `cache_dir` yet.

    A snapshot written since review fix-2 of #291 carries the outline the
    SCJN's API states, one marker line before each block (`scjn.outline`);
    `outline=False` takes those lines out and returns the text as it always
    read, for a reader that wants the law and not its structure."""
    contenido = _read_asset(f"{slug}.tgz", cache_dir)
    with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
        # Every member is prefixed with `<slug>/` so the tarball unpacks
        # anywhere -- see scripts/empaqueta_scjn_leyes.py.
        miembro = tar.extractfile(tar.getmember(f"{slug}/{archivo}"))
        texto = miembro.read().decode("utf-8")
    return texto if outline else strip_markers(texto)


def _es_snapshot(relativo: str) -> bool:
    """Whether the member `relativo` (its path inside the tarball, without the
    `<slug>/` prefix) is a snapshot: not `estado.json`, and not the
    `indice.json` / `notas/` an older copy of a tarball (from before the DOF
    linking left this repository; no published one has them) may carry."""
    return (
        relativo != ARCHIVO_ESTADO
        and relativo != "indice.json"
        and not relativo.startswith("notas/")
    )


def download_scjn_leyes_corpus(slug: str, *, cache_dir=None) -> dict:
    """One `leyes` instrument of the SCJN-based corpus (issue #128), by its
    own `slug`, as ``{"slug": ..., "snapshots": [...]}`` — one entry per
    snapshot, each carrying its own `archivo`, `fecha_publicacion` and
    Markdown body as `markdown`, oldest first.

    There is no table to read the dates from: every snapshot's date comes
    straight off its own file name (`DD-MM-YYYY.md`, or `DD-MM-YYYY-N.md` for
    a same-day repeat), the same rule the id-keyed collections use. An older copy of a tarball
    (from before the DOF linking left this repository; no published one) may
    also hold an `indice.json` and a `notas/` folder; neither is read, and
    neither is a snapshot.

    Reads only that law's own already-cached `<slug>.tgz` asset. Raises
    `AssetNotCached` while it is not on disk under `cache_dir` yet — run
    `scjn download --slug <slug>` first.
    """
    contenido = _read_asset(f"{slug}.tgz", cache_dir)

    with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
        miembros = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}

    snapshots = sorted(
        (
            {
                "archivo": relativo,
                "fecha_publicacion": relativo[:10],
                "markdown": contenido_miembro.decode("utf-8"),
            }
            for nombre, contenido_miembro in miembros.items()
            # Every member is prefixed with `<slug>/` so the tarball unpacks
            # anywhere; the prefix carries no information the caller needs.
            for relativo in (nombre.partition("/")[2],)
            if _es_snapshot(relativo)
        ),
        key=lambda s: (_fecha(s["fecha_publicacion"]), s["archivo"]),
    )
    return {"slug": slug, "snapshots": snapshots}


def local_slugs(cache_dir=None) -> list[str]:
    """Every law with a `<slug>.tgz` already on disk under `cache_dir` -- the
    disk-first answer to "which laws does this machine have", with no HTTP
    request at all (issue #205, made public here since every reader in this
    module needs it, not just `iter_current_federal_laws`).

    `Path.glob("*.tgz")` matches a whole file name, so it already excludes an
    interrupted download (`cache.SUFIJO_PARCIAL`'s `<slug>.tgz.parcial`,
    which does not end in `.tgz`) as well as `ASSET_INDICE_GLOBAL` and
    `SHA256SUMS.txt`, neither of which is a `.tgz` either -- nothing here
    needs to filter those out by hand.

    Returns an empty list for a cache directory that does not exist yet.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    carpeta_release = directorio / _SCJN_LEYES_RELEASE
    if not carpeta_release.is_dir():
        return []
    return sorted(ruta.name.removesuffix(".tgz") for ruta in carpeta_release.glob("*.tgz"))


def iter_current_federal_laws(
    slugs: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The current text of every federal law the `scjn-leyes` release
    publishes, one ``{"slug", "nombre", <each of CAMPOS_CLASIFICACION>,
    "materia", "vigencia", "resumen", "fecha_publicacion", "archivo",
    "markdown"}`` dict per law -- "current" meaning the snapshot whose file
    name carries the newest date.

    A true generator: one `<slug>.tgz` asset is opened, its winning snapshot
    read, and the tarball's bytes dropped before the next `slug` is reached,
    so iterating the whole corpus never holds more than one law in memory at
    a time. `download_scjn_leyes_corpus` would not do here -- it decodes
    every snapshot of a law just to keep the one that turns out to be the
    newest.

    `slugs=None` (the default) means "every law this machine has": `cache_dir`
    (`scjn.cache.CACHE_DIR` when not given) is asked for its own `<slug>.tgz`
    file names via `local_slugs`, with no HTTP request at all (issue #205).
    This is a disk-only reader (issue #209): a cold or absent cache does
    **not** fall back to asking the release what it currently publishes (that
    is `scjn_leyes_slugs`'s job, and the downloader's) — it simply yields
    nothing. Run `download_scjn_leyes_assets()` (or the `scjn download` CLI)
    first to populate the cache.

    `materia`/`vigencia`/`resumen` (issue #215) come from the same
    `instrumentos` entry `nombre` does, and degrade to None the same way when
    the index is not cached. They are what makes this iterator usable as a
    *classified* corpus — stratify by `materia`, keep only `VIGENTE` — without
    a second pass over the release or a request to the SCJN. `vigencia` is the
    law's status as of the last metadata run (`clasificado` in its own
    `estado.json`), not as of the snapshot being yielded: a 1970 snapshot of a
    law abrogated in 2014 comes back with `vigencia` `ABROGADO (A)`, which is
    a statement about the law, not about that text.

    `nombre` still comes from `indice-global.json.gz`'s `instrumentos`, which
    `construye_indice_global` populates for every crawled law -- but that
    asset can be cached separately from a law's own tarball. When `cache_dir` holds tarballs but
    not the index, `nombre` degrades to `None` rather than raising
    `AssetNotCached` for a field nobody asked to read explicitly; call
    `download_scjn_leyes_assets()` (or `scjn download`) to populate the index
    too and get real names back.

    The newest snapshot is the one whose file name -- `DD-MM-YYYY.md`, or
    `DD-MM-YYYY-N.md` for a same-day repeat (`scjn.api.descarga_ordenamiento`'s
    `-N` suffix) -- carries the newest date. An older copy of a tarball
    (from before the DOF linking left this repository; no published one) may
    also hold an `indice.json` and a `notas/` folder; they are not snapshots
    and are ignored.

    `fecha_publicacion`, as in a snapshot's file name, is `DD-MM-YYYY`
    (`scjn.header._fecha`'s format), not ISO --
    comparing it lexicographically would rank `"05-01-1999"` ahead of
    `"22-05-1998"`. The winner is chosen by parsing the date with `_fecha`;
    `archivo` breaks a tie between two snapshots published the same day, only
    to make the pick deterministic, not because either ordering is more
    correct.

    Raises `AssetNotCached` for an explicitly named `slug` whose tarball is
    not cached, exactly as `download_scjn_leyes_corpus` does.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    if slugs is None:
        slugs = local_slugs(directorio)

    indice_en_disco = (directorio / _SCJN_LEYES_RELEASE / ASSET_INDICE_GLOBAL).exists()
    instrumentos = (
        download_scjn_leyes_index(cache_dir=directorio)["instrumentos"]
        if indice_en_disco
        else {}
    )

    for slug in slugs:
        contenido = _read_asset(f"{slug}.tgz", directorio)
        with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
            candidatos = [
                relativo
                for m in tar.getmembers()
                if m.isfile()
                for relativo in (m.name.partition("/")[2],)
                if _es_snapshot(relativo)
            ]
            archivo = max(candidatos, key=lambda nombre: (_fecha(nombre[:10]), nombre))
            fecha_publicacion = archivo[:10]

            miembro_md = tar.getmember(f"{slug}/{archivo}")
            markdown = tar.extractfile(miembro_md).read().decode("utf-8")

        entrada_indice = instrumentos.get(slug, {})
        yield {
            "slug": slug,
            "nombre": entrada_indice.get("nombre"),
            **{
                campo: entrada_indice.get(campo)
                for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS)
            },
            "fecha_publicacion": fecha_publicacion,
            "archivo": archivo,
            "markdown": markdown,
        }


def _estado_de_asset(slug: str, cache_dir) -> dict:
    """One law's own `estado.json` as the release ships it inside `<slug>.tgz`,
    or `{}` when that tarball carries none (a law packaged before issue #148
    added the file). Raises `AssetNotCached` when the tarball itself is not
    cached — `download_scjn_leyes_catalog` decides what to do with that."""
    contenido = _read_asset(f"{slug}.tgz", cache_dir)
    with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
        for miembro in tar:
            # Every member is prefixed with `<slug>/` so the tarball unpacks
            # anywhere — the same convention `download_scjn_leyes_corpus` strips.
            if miembro.isfile() and miembro.name.partition("/")[2] == ARCHIVO_ESTADO:
                return json.loads(tar.extractfile(miembro).read())
    return {}


def download_scjn_leyes_catalog(*, freshness: bool = True, cache_dir=None, log=None) -> list[dict]:
    """The federal-law catalogue as the `scjn-leyes` release already publishes
    it: one ``{"abrev", "nombre", "actualizado", "materia", "vigencia",
    "resumen"}`` dict per law, sorted by `abrev`.

    This is the seed the Cámara de Diputados used to be scraped for — which
    laws exist, their name, their abbreviation — read back out of the release
    rather than rebuilt (issue #184). `nombre` comes from
    `indice-global.json.gz`'s `instrumentos`, keyed by slug
    (`scjn.catalog.slug_instrumento`); `abrev` and `actualizado` come from each
    law's own `estado.json` when `freshness=True` -- `abrev` verbatim (issue
    #210: `estado.json` is now the one place that value lives, once the
    one-time backfill has run), `actualizado` the date of the newest
    reform the SCJN serves for the law, never a DOF date (the packager
    publishes `actualizado_scjn`, or the date of the law's newest snapshot
    when that is absent: issue #148, review fix-3).

    `materia`/`vigencia`/`resumen` (issue #215) are the SCJN's own subject
    classification, in-force status and one-paragraph abstract of the law —
    one value per law, not per reform. They are read off the index, so they
    come back in `freshness=False` mode too, with no tarball opened at all;
    when a tarball *is* read, that law's own `estado.json` wins over the
    index for them, since it is the record the next repack will publish. Each
    is **absent** rather than None for a law the SCJN has no value for, or
    that `scripts/fetch_federal_law_metadata.py` has not resolved yet.

    `actualizado` is **absent** — not None, not a placeholder — for a law whose
    `estado.json` has none, or whose tarball is not cached at all under
    `freshness=True` (issue #209: this reader never downloads a tarball just
    to answer four fields, so a law missing from the cache is reported this
    way rather than raising `AssetNotCached`). Absent means "freshness
    unknown, always review", which is what `motivo_pendiente` already does
    with a catalogue entry that has no `actualizado`. Pass `log` (e.g.
    `print`) to be told which laws were skipped for this reason.

    A tarball packaged before issue #210 added `abrev` to `estado.json` -- or
    `freshness=False`, which skips tarballs entirely -- falls back to the
    slug itself, which is `slug_instrumento`'s *normalized* form: the 14 laws
    whose historical `abrev` contains an underscore (`lif_2026`, `pef_2026`,
    `ligie_2022`, the `lrart*`/`lrf*` reglamentarias, `reg_diputados`,
    `reg_senado`) come back hyphenated until their tarball is backfilled.

    `freshness=False` skips the tarballs entirely and returns `abrev`/`nombre`
    only, off the index alone — a few hundred KB, and the only mode that
    never raises `AssetNotCached`. Raises `AssetNotCached` while the index
    itself is not cached — run `scjn download` first.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    indice = download_scjn_leyes_index(cache_dir=directorio)
    catalogo = []
    for slug in sorted(indice["instrumentos"]):
        entrada_indice = indice["instrumentos"][slug]
        entrada = {"abrev": slug, "nombre": entrada_indice["nombre"]}
        entrada.update(
            {
                c: entrada_indice[c]
                for c in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS)
                if entrada_indice.get(c)
            }
        )
        if freshness:
            try:
                estado = _estado_de_asset(slug, directorio)
            except AssetNotCached:
                if log is not None:
                    log(f"{slug}: tarball not cached, skipping freshness check")
                catalogo.append(entrada)
                continue
            if estado.get("abrev"):
                entrada["abrev"] = estado["abrev"]
            if estado.get("actualizado"):
                entrada["actualizado"] = estado["actualizado"]
            entrada.update(
                {
                    campo: estado[campo]
                    for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS)
                    if estado.get(campo)
                }
            )
        catalogo.append(entrada)
    return catalogo


def scjn_leyes_slugs(timeout: int = 30) -> list[str]:
    """Every law the `scjn-leyes` release publishes a tarball for, by slug --
    the *downloader's* question ("what does the release publish"), not a
    reader's: it always makes an HTTP request, unlike `local_slugs`.

    Read off the release's own asset listing rather than off
    `indice-global.json.gz`: a law crawled but not linked yet has a `.tgz`
    and no index entry, and "download the corpus" means the tarballs, not
    the ones the linking phase already got to.
    """
    return sorted(
        nombre.removesuffix(".tgz")
        for nombre in _assets_scjn_leyes(timeout)
        if nombre.endswith(".tgz")
    )


def download_scjn_leyes_assets(
    slugs: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """Put the `scjn-leyes` release's assets on disk: the reverse index plus
    one tarball per law, into ``<cache_dir>/scjn-leyes/``.

    The only function in this module that talks to the network (besides
    `scjn_leyes_slugs`) — every reader above assumes this (or the `scjn
    download` CLI built on it) already ran.

    `slugs` picks which laws to fetch; None (the default) means every law the
    release publishes. The index is always included — it is what every
    reader resolves a law's name and classification through, and it costs a
    few hundred KB against the corpus' ~380 MB.

    Returns one ``(path, downloaded)`` pair per asset, in the order they were
    fetched, with `downloaded` False for an asset that was already cached —
    matched by name and never revalidated. `refrescar=True` re-downloads
    regardless.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)

    # Named slugs give the asset names outright, so a fully cached re-run can
    # skip the release listing too and cost no HTTP request at all; without
    # them the listing *is* how "every law" is known, so it is unavoidable.
    urls = None
    if slugs is None:
        urls = _assets_scjn_leyes(timeout)
        nombres = [ASSET_INDICE_GLOBAL] + [
            f"{slug}.tgz"
            for slug in sorted(n.removesuffix(".tgz") for n in urls if n.endswith(".tgz"))
        ]
    else:
        nombres = [ASSET_INDICE_GLOBAL] + [f"{slug}.tgz" for slug in slugs]

    resultados = []
    for i, nombre in enumerate(nombres, 1):
        destino = directorio / _SCJN_LEYES_RELEASE / nombre
        ya_estaba = destino.exists() and not refrescar
        if ya_estaba:
            ruta = destino
        else:
            if urls is None:
                urls = _assets_scjn_leyes(timeout)
            if nombre not in urls:
                raise KeyError(_mensaje_ningun_asset(_SCJN_LEYES_RELEASE, nombre))
            ruta = cache.asset_en_cache(
                _SCJN_LEYES_RELEASE, nombre, urls[nombre],
                cache_dir=directorio, refrescar=refrescar, timeout=timeout,
            )
        if log is not None:
            estado = "already cached" if ya_estaba else "downloaded"
            log(f"[{i}/{len(nombres)}] {nombre}: {estado}")
        resultados.append((ruta, not ya_estaba))
    return resultados


# --- Id-keyed collections: `scjn-reglamentos` (issue #220), generalized for
# --- `scjn-lineamientos` in issue #222's Fase 0 -----------------------------
#
# Two hand-duplicated collections were a defensible cost (#220's own decision
# 4); three are not, so this generic core replaces what used to be a second,
# independently-duplicated copy of index/corpus/local-ids/assets. Every
# `Coleccion` (`scjn.cache.REGLAMENTOS`/`LINEAMIENTOS`/`TRATADOS`) shares it; `leyes`
# keeps its own separate path above, untouched -- it has `abrev`, which no
# id-keyed collection has.
#
# A tarball of an id-keyed collection ships only
# `<id_ordenamiento>/<fecha>.md` and `<id_ordenamiento>/estado.json`.

#: The SCJN's own classification of the ordenamiento at seeding time
#: (`categoriaOrdenamiento`), the first of `CAMPOS_CLASIFICACION`. Born in the
#: id-keyed collections -- a reglamento's or lineamiento's inclusion rule can
#: rescue an instrument the SCJN itself classifies as `ACUERDO (S)` or
#: similar, so recording what it was actually classified as is worth keeping --
#: and, since issue #8, carried by `scjn-leyes` too (`LEY` or `CODIGO`).
#: Kept as a name for the callers that import it.
CAMPO_CATEGORIA_ORDENAMIENTO = "categoria_ordenamiento"


class SinTextoEnSCJN(Exception):
    """The SCJN classifies this instrument, but serves no consolidated text
    for it at all (issue #222's decision 6/10) -- raised by `_corpus_de_release`
    (and every id-keyed `download_*_corpus` wrapper) instead of
    `AssetNotCached`, since there is no tarball to ever download, not one
    that merely is not downloaded *yet*.

    A sibling of `AssetNotCached`, not a replacement for it: `except
    AssetNotCached` keeps meaning exactly "not downloaded yet". The raise
    order is part of the contract (see `_corpus_de_release`): the index is
    read first (`AssetNotCached` if it is not cached at all), then this
    exception fires only for an `id_ordenamiento` the index actually lists
    with no `asset` -- an id the index does not mention at all still falls
    through to `AssetNotCached` for its tarball.
    """

    def __init__(self, id_ordenamiento: str, coleccion: str):
        super().__init__(
            f"'{id_ordenamiento}' no tiene texto consolidado en la SCJN (coleccion "
            f"'{coleccion}') -- el indice lo lista con snapshots=0 y sin asset que descargar"
        )
        self.id_ordenamiento = id_ordenamiento
        self.coleccion = coleccion


def _indice_global_por_id(coleccion: str, instrumentos: list[dict], generado: str) -> dict:
    """The generic `indice-global.json.gz` payload builder behind
    `construye_indice_global_reglamentos`/`construye_indice_global_lineamientos`
    (issue #222's Fase 0) -- the sibling of `construye_indice_global`, keyed by
    `id_ordenamiento` instead of a slug::

        {"generado", "coleccion": <coleccion>,
         "instrumentos": {id_ordenamiento: {"nombre", "asset"?, "snapshots",
                                             "categoria_ordenamiento"?, "ambito"?,
                                             "pais"?, "estado"?, "municipio"?,
                                             "materia"?, "vigencia"?,
                                             "resumen"?}}}

    Each of `instrumentos` is ``{"id_ordenamiento", "nombre", "asset"?,
    "snapshots"?, <each of CAMPOS_CLASIFICACION>?, "materia"?, "vigencia"?,
    "resumen"?}``, keyed in the result by `id_ordenamiento`
    (`scjn.catalog.instrumento_key`) rather than by a title-derived slug —
    neither id-keyed collection has an `abrev`. `snapshots` is a plain count,
    read verbatim off `instrumento["snapshots"]`, as in
    `construye_indice_global`.

    **`asset` is present only when `snapshots` is not zero** (issue #222's
    decision 6): an instrument the SCJN classifies but serves no
    consolidated text for is still indexed -- with `snapshots: 0` and no
    `asset` key at all -- rather than defaulting to a tarball name that was
    never packaged. This applies retroactively to `scjn-reglamentos`' own 5
    such instruments, which the pre-#222 index silently dropped instead
    (1082 entries, not 1087).
    """
    entradas: dict[str, dict] = {}
    for instrumento in sorted(instrumentos, key=lambda i: int(i["id_ordenamiento"])):
        clave = str(instrumento["id_ordenamiento"])
        snapshots = instrumento.get("snapshots", 0)
        entrada = {"nombre": instrumento["nombre"]}
        if snapshots:
            entrada["asset"] = instrumento.get("asset") or f"{clave}.tgz"
        entrada["snapshots"] = snapshots
        for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS):
            valor = instrumento.get(campo)
            if valor:
                entrada[campo] = valor
        entradas[clave] = entrada
    return {"generado": generado, "coleccion": coleccion, "instrumentos": entradas}


def construye_indice_global_reglamentos(instrumentos: list[dict], generado: str) -> dict:
    """The `scjn-reglamentos` release's own `indice-global.json.gz` payload —
    a thin wrapper over `_indice_global_por_id` (issue #222's Fase 0; the
    body used to live here directly, see that function's own docstring for
    the payload shape and decision 6).

    >>> import scjn.release as release
    >>> indice = release.construye_indice_global_reglamentos(
    ...     [{"id_ordenamiento": "104906", "nombre": "REGLAMENTO...",
    ...       "snapshots": 2, "vigencia": "ABROGADO (A)"}],
    ...     generado="2026-09-09T00:00:00+00:00",
    ... )
    >>> indice["coleccion"]
    'reglamentos'
    >>> indice["instrumentos"]["104906"]
    {'nombre': 'REGLAMENTO...', 'asset': '104906.tgz', 'snapshots': 2, 'vigencia': 'ABROGADO (A)'}
    """
    return _indice_global_por_id("reglamentos", instrumentos, generado)


def construye_indice_global_lineamientos(instrumentos: list[dict], generado: str) -> dict:
    """The `scjn-lineamientos` release's own `indice-global.json.gz` payload —
    the `lineamientos` sibling of `construye_indice_global_reglamentos`
    (issue #222); see `_indice_global_por_id` for the payload shape.

    >>> import scjn.release as release
    >>> indice = release.construye_indice_global_lineamientos(
    ...     [{"id_ordenamiento": "180528", "nombre": "LINEAMIENTOS...",
    ...       "snapshots": 1, "vigencia": "VIGENTE"}],
    ...     generado="2026-09-10T00:00:00+00:00",
    ... )
    >>> indice["coleccion"]
    'lineamientos'
    >>> indice["instrumentos"]["180528"]
    {'nombre': 'LINEAMIENTOS...', 'asset': '180528.tgz', 'snapshots': 1, 'vigencia': 'VIGENTE'}
    """
    return _indice_global_por_id("lineamientos", instrumentos, generado)


def construye_indice_global_tratados(instrumentos: list[dict], generado: str) -> dict:
    """The `scjn-tratados` release's own `indice-global.json.gz` payload —
    the `tratados` sibling of `construye_indice_global_lineamientos` (issue
    #277), same shape, `coleccion: "tratados"`:

    >>> from scjn import release
    >>> indice = release.construye_indice_global_tratados(
    ...     [{"id_ordenamiento": "1012", "nombre": "CONVENIO...",
    ...       "snapshots": 1, "vigencia": "VIGENTE"}],
    ...     "2026-10-08",
    ... )
    >>> indice["coleccion"]
    'tratados'
    >>> indice["instrumentos"]["1012"]
    {'nombre': 'CONVENIO...', 'asset': '1012.tgz', 'snapshots': 1, 'vigencia': 'VIGENTE'}
    """
    return _indice_global_por_id("tratados", instrumentos, generado)


def construye_indice_global_estatutos(instrumentos: list[dict], generado: str) -> dict:
    """The `scjn-estatutos` release's own `indice-global.json.gz` payload —
    the `estatutos` sibling of `construye_indice_global_lineamientos` (issue
    #9), same shape, `coleccion: "estatutos"`:

    >>> from scjn import release
    >>> indice = release.construye_indice_global_estatutos(
    ...     [{"id_ordenamiento": "5001", "nombre": "ESTATUTO ORGANICO...",
    ...       "snapshots": 1, "categoria_ordenamiento": "ESTATUTO",
    ...       "ambito": "FEDERAL", "vigencia": "VIGENTE"}],
    ...     "2026-11-13",
    ... )
    >>> indice["coleccion"]
    'estatutos'
    >>> indice["instrumentos"]["5001"]["categoria_ordenamiento"]
    'ESTATUTO'
    >>> indice["instrumentos"]["5001"]["asset"]
    '5001.tgz'
    """
    return _indice_global_por_id("estatutos", instrumentos, generado)


#: `_index_de_release`'s in-process memo, keyed by `(coleccion, cache_dir)` --
#: the id-keyed sibling of `_MEMO_INDICE_GLOBAL` (issue #222's Fase 0;
#: previously one hand-duplicated dict per collection).
_MEMO_INDICE_POR_ID: dict[tuple[str, str], dict] = {}


def _index_de_release(coleccion: Coleccion, *, cache_dir=None) -> dict:
    """The generic index reader behind `download_scjn_reglamentos_index`/
    `download_scjn_lineamientos_index` (issue #222's Fase 0): a plain disk
    read, memoized per `(coleccion, cache_dir)`.

    Raises `AssetNotCached` while the index is not cached yet — run `scjn
    download --coleccion <nombre>` first.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    clave = (coleccion.nombre, str(directorio))
    if clave in _MEMO_INDICE_POR_ID:
        return _MEMO_INDICE_POR_ID[clave]

    contenido = _read_asset(
        ASSET_INDICE_GLOBAL, directorio,
        release=coleccion.subdirectorio, coleccion=coleccion.nombre,
    )
    indice = json.loads(gzip.decompress(contenido).decode("utf-8"))
    _MEMO_INDICE_POR_ID[clave] = indice
    return indice


def _corpus_de_release(coleccion: Coleccion, id_ordenamiento: str | int, *, cache_dir=None) -> dict:
    """The generic corpus reader behind `download_scjn_reglamentos_corpus`/
    `download_scjn_lineamientos_corpus` (issue #222's Fase 0), as
    ``{"id_ordenamiento": ..., "snapshots": [...]}`` — one entry per
    snapshot, each carrying its own `archivo`/`fecha_publicacion`/`markdown`,
    oldest first. Every snapshot's date comes straight off its own file
    name, the same rule `download_scjn_leyes_corpus` uses.

    Raises, in this order (decision 10, issue #222 -- part of the contract,
    not an implementation detail):

    1. `AssetNotCached` if the collection's own index is not cached at all
       yet — run `scjn download --coleccion <nombre>` first.
    2. `SinTextoEnSCJN` if the index lists `id_ordenamiento` with no `asset`
       (decision 6: the SCJN classifies it but serves no text) — there is
       nothing to ever download for it.
    3. `AssetNotCached` if `id_ordenamiento` is absent from the index
       entirely, or its tarball is not on disk yet — run `scjn download
       --coleccion <nombre> --id <id_ordenamiento>`.
    """
    clave = str(id_ordenamiento)
    directorio = cache.resuelve_cache_dir(cache_dir)
    indice = _index_de_release(coleccion, cache_dir=directorio)
    entrada = indice["instrumentos"].get(clave)
    if entrada is not None and not entrada.get("asset"):
        raise SinTextoEnSCJN(clave, coleccion.nombre)

    contenido = _read_asset(
        f"{clave}.tgz", directorio, release=coleccion.subdirectorio, coleccion=coleccion.nombre,
    )
    with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
        miembros = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}

    snapshots = sorted(
        (
            {
                "archivo": relativo,
                "fecha_publicacion": relativo[:10],
                "markdown": contenido_miembro.decode("utf-8"),
            }
            for nombre, contenido_miembro in miembros.items()
            for relativo in (nombre.partition("/")[2],)
            if relativo != ARCHIVO_ESTADO
        ),
        key=lambda s: (_fecha(s["fecha_publicacion"]), s["archivo"]),
    )
    return {"id_ordenamiento": clave, "snapshots": snapshots}


def _local_ids_de_release(coleccion: Coleccion, cache_dir=None) -> list[str]:
    """The generic local-ids lister behind `local_reglamentos_ids`/
    `local_lineamientos_ids` (issue #222's Fase 0) — every instrument with a
    `<id_ordenamiento>.tgz` already on disk under `cache_dir`, sorted
    numerically: an `id_ordenamiento` is a digit string, and sorting it as
    text would rank `"100"` ahead of `"99"`.

    Returns an empty list for a cache directory that does not exist yet."""
    directorio = cache.resuelve_cache_dir(cache_dir)
    carpeta_release = directorio / coleccion.subdirectorio
    if not carpeta_release.is_dir():
        return []
    return sorted(
        (ruta.name.removesuffix(".tgz") for ruta in carpeta_release.glob("*.tgz")),
        key=int,
    )


def _download_assets_de_release(
    coleccion: Coleccion,
    listar_assets,
    ids: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """The generic downloader behind `download_scjn_reglamentos_assets`/
    `download_scjn_lineamientos_assets` (issue #222's Fase 0) -- puts
    `coleccion`'s assets on disk: the index plus one tarball per instrument,
    into ``<cache_dir>/<coleccion.subdirectorio>/``; the sibling of
    `download_scjn_leyes_assets`, everything documented there (idempotence
    by name, `refrescar`, the partial-download suffix, resolving the whole
    series of release parts) applies here unchanged. `ids` picks which
    instruments to fetch, by `id_ordenamiento`; None (the default) means
    every one the release publishes.

    `listar_assets` is the collection's own `_assets_scjn_<nombre>` function
    (a plain `timeout -> dict[str, str]` callable) -- taken as a parameter,
    not derived from `coleccion` here, so each public wrapper keeps calling
    its own named function and a caller mocking it (as every existing test
    does) keeps working unchanged.

    With `ids=None`, once every asset is on disk, the on-disk index (if it
    is already cached) is cross-checked against the parts actually walked:
    any instrument whose own `asset` field the index names but no part
    publishes is reported to `log` (never raised) -- a partially published
    corpus still downloads everything it can, but says what is missing
    rather than silently coming back short (issue #223's whole point).
    """
    directorio = cache.resuelve_cache_dir(cache_dir)

    urls = None
    if ids is None:
        urls = listar_assets(timeout)
        nombres = [ASSET_INDICE_GLOBAL] + [
            f"{id_}.tgz"
            for id_ in sorted(
                (n.removesuffix(".tgz") for n in urls if n.endswith(".tgz")), key=int
            )
        ]
    else:
        nombres = [ASSET_INDICE_GLOBAL] + [f"{id_}.tgz" for id_ in ids]

    resultados = []
    for i, nombre in enumerate(nombres, 1):
        destino = directorio / coleccion.subdirectorio / nombre
        ya_estaba = destino.exists() and not refrescar
        if ya_estaba:
            ruta = destino
        else:
            if urls is None:
                urls = listar_assets(timeout)
            if nombre not in urls:
                raise KeyError(_mensaje_ningun_asset(coleccion.tag_base, nombre))
            ruta = cache.asset_en_cache(
                coleccion.subdirectorio, nombre, urls[nombre],
                cache_dir=directorio, refrescar=refrescar, timeout=timeout,
            )
        if log is not None:
            estado = "already cached" if ya_estaba else "downloaded"
            log(f"[{i}/{len(nombres)}] {nombre}: {estado}")
        resultados.append((ruta, not ya_estaba))

    if ids is None and urls is not None and log is not None:
        try:
            indice = _index_de_release(coleccion, cache_dir=directorio)
        except AssetNotCached:
            indice = None
        if indice is not None:
            for entrada in indice["instrumentos"].values():
                asset = entrada.get("asset")
                if asset and asset not in urls:
                    log(
                        f"warning: el indice declara '{asset}' pero ninguna parte "
                        "del release lo publica"
                    )
    return resultados


# --- `scjn-reglamentos` (issue #220): public wrappers over the generic core

def _assets_scjn_reglamentos(timeout: int = 30) -> dict[str, str]:
    """Every asset of the `scjn-reglamentos` release, name -> download URL —
    merged across every part of its series (`_assets_de_partes`, issue
    #223: this collection outgrew a single release, 1082 tarballs across
    `scjn-reglamentos`/`scjn-reglamentos-2`). Network — used by the
    downloader only, never by a reader."""
    return _assets_de_partes(REGLAMENTOS.tag_base, timeout)


def download_scjn_reglamentos_index(*, cache_dir=None) -> dict:
    """The `scjn-reglamentos` release's own `indice-global.json.gz`
    (`construye_indice_global_reglamentos`'s payload) — a thin wrapper over
    `_index_de_release` (issue #222's Fase 0)."""
    return _index_de_release(REGLAMENTOS, cache_dir=cache_dir)


def download_scjn_reglamentos_corpus(id_ordenamiento: str | int, *, cache_dir=None) -> dict:
    """One `reglamentos` instrument, by its own `id_ordenamiento` — a thin
    wrapper over `_corpus_de_release` (issue #222's Fase 0); see its own
    docstring for the payload shape and the `AssetNotCached`/`SinTextoEnSCJN`
    raise order."""
    return _corpus_de_release(REGLAMENTOS, id_ordenamiento, cache_dir=cache_dir)


def local_reglamentos_ids(cache_dir=None) -> list[str]:
    """Every reglamento with a `<id_ordenamiento>.tgz` already on disk under
    `cache_dir` — a thin wrapper over `_local_ids_de_release` (issue #222's
    Fase 0)."""
    return _local_ids_de_release(REGLAMENTOS, cache_dir)


def download_scjn_reglamentos_assets(
    ids: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """Put the `scjn-reglamentos` release's assets on disk — a thin wrapper
    over `_download_assets_de_release` (issue #222's Fase 0); see its own
    docstring for the full contract."""
    return _download_assets_de_release(
        REGLAMENTOS, _assets_scjn_reglamentos, ids,
        cache_dir=cache_dir, refrescar=refrescar, timeout=timeout, log=log,
    )


# --- `scjn-lineamientos` (issue #222): public wrappers over the generic core

def _assets_scjn_lineamientos(timeout: int = 30) -> dict[str, str]:
    """Every asset of the `scjn-lineamientos` release, name -> download URL —
    the `lineamientos` sibling of `_assets_scjn_reglamentos` (issue #222),
    merged across every part of its series. Network — used by the
    downloader only, never by a reader."""
    return _assets_de_partes(LINEAMIENTOS.tag_base, timeout)


def download_scjn_lineamientos_index(*, cache_dir=None) -> dict:
    """The `scjn-lineamientos` release's own `indice-global.json.gz`
    (`construye_indice_global_lineamientos`'s payload) — a thin wrapper over
    `_index_de_release` (issue #222's Fase 0)."""
    return _index_de_release(LINEAMIENTOS, cache_dir=cache_dir)


def download_scjn_lineamientos_corpus(id_ordenamiento: str | int, *, cache_dir=None) -> dict:
    """One `lineamientos` instrument, by its own `id_ordenamiento` — a thin
    wrapper over `_corpus_de_release` (issue #222's Fase 0); see its own
    docstring for the payload shape and the `AssetNotCached`/`SinTextoEnSCJN`
    raise order."""
    return _corpus_de_release(LINEAMIENTOS, id_ordenamiento, cache_dir=cache_dir)


def local_lineamientos_ids(cache_dir=None) -> list[str]:
    """Every lineamiento with a `<id_ordenamiento>.tgz` already on disk
    under `cache_dir` — a thin wrapper over `_local_ids_de_release` (issue
    #222's Fase 0)."""
    return _local_ids_de_release(LINEAMIENTOS, cache_dir)


def download_scjn_lineamientos_assets(
    ids: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """Put the `scjn-lineamientos` release's assets on disk — a thin wrapper
    over `_download_assets_de_release` (issue #222's Fase 0); see its own
    docstring for the full contract."""
    return _download_assets_de_release(
        LINEAMIENTOS, _assets_scjn_lineamientos, ids,
        cache_dir=cache_dir, refrescar=refrescar, timeout=timeout, log=log,
    )


# --- `scjn-tratados` (issue #277): public wrappers over the generic core ----

def _assets_scjn_tratados(timeout: int = 30) -> dict[str, str]:
    """Every asset of the `scjn-tratados` release, name -> download URL —
    the `tratados` sibling of `_assets_scjn_lineamientos` (issue #277),
    merged across every part of its series (this one is over GitHub's
    1000-asset cap, like `scjn-reglamentos`). Network — used by the
    downloader only, never by a reader."""
    return _assets_de_partes(TRATADOS.tag_base, timeout)


def download_scjn_tratados_index(*, cache_dir=None) -> dict:
    """The `scjn-tratados` release's own `indice-global.json.gz`
    (`construye_indice_global_tratados`'s payload) — a thin wrapper over
    `_index_de_release` (issue #277)."""
    return _index_de_release(TRATADOS, cache_dir=cache_dir)


def download_scjn_tratados_corpus(id_ordenamiento: str | int, *, cache_dir=None) -> dict:
    """One `tratados` instrument, by its own `id_ordenamiento` — a thin
    wrapper over `_corpus_de_release` (issue #277); see its own docstring
    for the payload shape and the `AssetNotCached`/`SinTextoEnSCJN` raise
    order."""
    return _corpus_de_release(TRATADOS, id_ordenamiento, cache_dir=cache_dir)


def local_tratados_ids(cache_dir=None) -> list[str]:
    """Every treaty with a `<id_ordenamiento>.tgz` already on disk under
    `cache_dir` — a thin wrapper over `_local_ids_de_release` (issue #277)."""
    return _local_ids_de_release(TRATADOS, cache_dir)


def download_scjn_tratados_assets(
    ids: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """Put the `scjn-tratados` release's assets on disk — a thin wrapper
    over `_download_assets_de_release` (issue #277); see its own docstring
    for the full contract."""
    return _download_assets_de_release(
        TRATADOS, _assets_scjn_tratados, ids,
        cache_dir=cache_dir, refrescar=refrescar, timeout=timeout, log=log,
    )


# --- `scjn-estatutos` (issue #9): public wrappers over the generic core -----
# The release was published on 2026-11-17; like every reader, those below read
# only the cache and raise `AssetNotCached` for what `scjn download` has not put
# there.

def _assets_scjn_estatutos(timeout: int = 30) -> dict[str, str]:
    """Every asset of the `scjn-estatutos` release, name -> download URL —
    the `estatutos` sibling of `_assets_scjn_lineamientos` (issue #9),
    merged across every part of its series. Network — used by the
    downloader only, never by a reader."""
    return _assets_de_partes(ESTATUTOS.tag_base, timeout)


def download_scjn_estatutos_index(*, cache_dir=None) -> dict:
    """The `scjn-estatutos` release's own `indice-global.json.gz`
    (`construye_indice_global_estatutos`'s payload) — a thin wrapper over
    `_index_de_release` (issue #9)."""
    return _index_de_release(ESTATUTOS, cache_dir=cache_dir)


def download_scjn_estatutos_corpus(id_ordenamiento: str | int, *, cache_dir=None) -> dict:
    """One `estatutos` instrument, by its own `id_ordenamiento` — a thin
    wrapper over `_corpus_de_release` (issue #9); see its own docstring for
    the payload shape and the `AssetNotCached`/`SinTextoEnSCJN` raise
    order."""
    return _corpus_de_release(ESTATUTOS, id_ordenamiento, cache_dir=cache_dir)


def local_estatutos_ids(cache_dir=None) -> list[str]:
    """Every estatuto with a `<id_ordenamiento>.tgz` already on disk under
    `cache_dir` — a thin wrapper over `_local_ids_de_release` (issue #9)."""
    return _local_ids_de_release(ESTATUTOS, cache_dir)


def download_scjn_estatutos_assets(
    ids: list[str] | None = None,
    *,
    cache_dir=None,
    refrescar: bool = False,
    timeout: int = 60,
    log=None,
) -> list[tuple[Path, bool]]:
    """Put the `scjn-estatutos` release's assets on disk — a thin wrapper
    over `_download_assets_de_release` (issue #9); see its own docstring
    for the full contract."""
    return _download_assets_de_release(
        ESTATUTOS, _assets_scjn_estatutos, ids,
        cache_dir=cache_dir, refrescar=refrescar, timeout=timeout, log=log,
    )


# --- The current text of an id-keyed instrument (issue #227's Fase 2) -------

def _iter_current_de_release(
    coleccion: Coleccion, ids: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The generic current-text iterator behind `iter_current_reglamentos`/
    `iter_current_lineamientos` (issue #227's Fase 2) — the id-keyed sibling
    of `iter_current_federal_laws`, yielding ``{"id_ordenamiento", "nombre",
    "materia", "vigencia", "resumen", "fecha_publicacion", "archivo",
    "markdown"}`` per instrument.

    A true generator, for the same reason its `leyes` counterpart is one: one
    `<id_ordenamiento>.tgz` is opened, its newest snapshot read, and the
    tarball's bytes dropped before the next id is reached, so walking the
    whole of `scjn-reglamentos` (1,082 instruments, ~6.6 minutes to decode on
    `headmaster`) never holds more than one instrument in memory.
    `_corpus_de_release` would not do here — it decodes every snapshot of an
    instrument just to keep the one that turns out to be the newest.

    "Newest" comes from the snapshots' own file names, `DD-MM-YYYY.md` —
    parsed with `_fecha` rather than compared as text, and tie-broken by
    `archivo` only to make the pick deterministic. There is no `abrev` in
    what comes back: an id-keyed collection has none.

    `materia`/`vigencia`/`resumen`/`nombre` come off the cached index at no
    extra request, and are **partial** for these collections, unlike leyes:
    `materia` is present for 533 of 1,087 reglamentos and 112 of 163
    lineamientos, `resumen` for 544 and 14 (issue #227's own measurement). A
    missing one is not a bug to chase.

    `ids=None` (the default) means "every instrument this machine has", via
    `_local_ids_de_release` — a disk-only reader, exactly like
    `iter_current_federal_laws`. An instrument the index lists with no text
    at all (`snapshots: 0`, issue #222's decision 6) is **skipped** rather
    than raising `SinTextoEnSCJN`: there are 5 such reglamentos and 37 such
    lineamientos, none of them has a tarball to read, and a corpus walk
    should not have to catch an exception per instrument the SCJN never
    published text for. An id named explicitly that has no text is skipped on
    the same terms — `download_*_corpus` is where asking for one by name
    raises.
    """
    directorio = cache.resuelve_cache_dir(cache_dir)
    if ids is None:
        ids = _local_ids_de_release(coleccion, directorio)

    try:
        instrumentos = _index_de_release(coleccion, cache_dir=directorio)["instrumentos"]
    except AssetNotCached:
        instrumentos = {}

    for id_ordenamiento in ids:
        clave = str(id_ordenamiento)
        entrada = instrumentos.get(clave)
        if entrada is not None and not entrada.get("asset"):
            continue
        contenido = _read_asset(
            f"{clave}.tgz", directorio,
            release=coleccion.subdirectorio, coleccion=coleccion.nombre,
        )
        with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
            candidatos = [
                relativo
                for m in tar.getmembers()
                if m.isfile()
                for relativo in (m.name.partition("/")[2],)
                if relativo != ARCHIVO_ESTADO
            ]
            if not candidatos:
                continue
            archivo = max(candidatos, key=lambda nombre: (_fecha(nombre[:10]), nombre))
            markdown = tar.extractfile(tar.getmember(f"{clave}/{archivo}")).read().decode("utf-8")

        entrada = entrada or {}
        yield {
            "id_ordenamiento": clave,
            "nombre": entrada.get("nombre"),
            **{campo: entrada.get(campo) for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS)},
            "fecha_publicacion": archivo[:10],
            "archivo": archivo,
            "markdown": markdown,
        }


def iter_current_reglamentos(
    ids: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The current text of every federal *reglamento* the `scjn-reglamentos`
    release publishes — a thin wrapper over `_iter_current_de_release` (issue
    #227's Fase 2); see its own docstring for the payload shape and for what
    happens to an instrument with no consolidated text."""
    return _iter_current_de_release(REGLAMENTOS, ids, cache_dir=cache_dir)


def iter_current_lineamientos(
    ids: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The current text of every federal *lineamiento* the
    `scjn-lineamientos` release publishes — the `lineamientos` sibling of
    `iter_current_reglamentos` (issue #227's Fase 2)."""
    return _iter_current_de_release(LINEAMIENTOS, ids, cache_dir=cache_dir)


def iter_current_tratados(
    ids: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The current text of every international treaty the `scjn-tratados`
    release publishes — the `tratados` sibling of `iter_current_reglamentos`
    (issue #277)."""
    return _iter_current_de_release(TRATADOS, ids, cache_dir=cache_dir)


def iter_current_estatutos(
    ids: list[str] | None = None, *, cache_dir=None
) -> Iterator[dict]:
    """The current text of every federal *estatuto* the `scjn-estatutos`
    release publishes — the `estatutos` sibling of `iter_current_reglamentos`
    (issue #9)."""
    return _iter_current_de_release(ESTATUTOS, ids, cache_dir=cache_dir)
