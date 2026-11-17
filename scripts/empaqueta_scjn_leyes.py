#!/usr/bin/env python3
"""Package the SCJN-based `leyes` corpus (the reform-dated snapshots and each
law's `estado.json`, issue #123/#128) into one byte-reproducible tarball *per
instrument*, plus a human-readable manifest and a checksum file. SCJN data
only: nothing about the DOF travels in a release.

## Manual publish only — never automated

The SCJN's own search can return a completely wrong document for an instrument
(issue #115, Hallazgo C) — so nothing this script produces is ever published
automatically, now or in the future. The packaging step (this script) and
the publish step (a person running `gh` by hand) are deliberately kept
apart: this script never calls `gh` itself, and no `.github/workflows/` file
should ever call it and then publish on its own.

    # Defaults: --outdir scripts/scjn, --destino scripts/scjn/leyes-release
    # (the directories the corpus actually lives in today, both under the
    # `scripts/scjn/` that .gitignore excludes).
    ./scripts/empaqueta_scjn_leyes.py
    less scripts/scjn/leyes-release/MANIFEST.md   # read it. all of it.

    # `--repo` is the releases' owner, `scjn.release.release_repository()`:
    # this repository (legistlan/scjn) unless SCJN_RELEASE_REPOSITORY names a mirror.
    # first publish — the release itself, with the small text assets and the
    # index every reader resolves a law's name and classification against:
    cd scripts/scjn/leyes-release
    gh release create scjn-leyes MANIFEST.md SHA256SUMS.txt indice-global.json.gz \\
        --repo legistlan/scjn --title "SCJN — leyes" --notes-file MANIFEST.md

    # then the ~315 per-law tarballs, in batches (gh takes many paths at
    # once, but a batch that fails mid-way is cheaper to retry than one run
    # of 315). `--clobber` makes re-running after a network failure
    # idempotent, so a batch can simply be repeated:
    ls *.tgz | xargs -n 20 gh release upload scjn-leyes \\
        --repo legistlan/scjn --clobber

    # a later run only has to re-upload the laws that changed -- but always
    # the index with them: it lists every law, so any change to any law
    # makes the published one stale.
    gh release upload scjn-leyes lft.tgz indice-global.json.gz \\
        SHA256SUMS.txt MANIFEST.md --repo legistlan/scjn --clobber

## What goes in each tarball

One `<slug>.tgz` per instrument, not one for the whole collection: a
consumer almost always wants a single law, and an incremental update only
has to re-upload the asset of the law that changed. Every member is
prefixed with `<slug>/`, so a tarball can be unpacked anywhere without
stepping on anything:

    <slug>/<fecha>.md          the snapshots, with their provenance header
    <slug>/estado.json         when it was crawled, and the law's
                               `actualizado` (issue #148)

`estado.json` travels with them so the release itself carries its own
freshness metadata, with nothing to trust in local scratch. Its `actualizado`
is the date of the newest reform the SCJN serves for the law, never a DOF
date: `actualizado_scjn` when the file has it, otherwise the date of the
newest snapshot on disk, and no `actualizado` for a law with no snapshot
(`actualizado_publicado`, review fix-3).

Nothing else is shipped, whatever the corpus directory holds: a law crawled
by an older version of this repository may still have an `indice.json` and a
`notas/` folder next to its snapshots (the DOF linking that used to live
here), and its `estado.json` may carry the keys that linking wrote
(`CLAVES_ESTADO_DOF`: `enlazado`, `actualizado_dof`). None of those reach a
tarball: the packager filters the copy it ships and never rewrites the corpus
on disk.

## Updating one law (issue #148)

``--instrumento SLUG`` (repeatable) rewrites only the named instruments'
tarballs and leaves every other `.tgz` already in `--destino` exactly as it
is — the manifest says which ones were actually rewritten, so the human
review before publishing is a handful of rows instead of 315. The manifest,
`SHA256SUMS.txt` and `indice-global.json.gz` are always recomputed over the
whole corpus, though: the index lists every law, so one law changing makes
the published one stale.

    ./scripts/fetch_scjn_legislacion.py --outdir scripts/scjn --plan
    ./scripts/fetch_scjn_legislacion.py --outdir scripts/scjn --instrumento lft
    ./scripts/empaqueta_scjn_leyes.py --instrumento lft
    less scripts/scjn/leyes-release/MANIFEST.md   # short now. still read it all.

A fix to how `scjn.api.articulos_a_markdown` converts an article's own
`contenido` (issue #253's table-row recovery, for one) only reaches an
already-published snapshot by naming it here too, once a law flagged by
`scripts/find_scjn_table_instruments.py` has had all of its snapshots
re-downloaded (`fetch_scjn_legislacion.py --instrumento <slug>`, after
deleting its `*.md` files — never `--reintenta <slug>`, which deletes
`estado.json` and re-searches without the recorded
`id_ordenamiento`, issue #115's wrong-document path); packaging never
re-derives a snapshot from anything cached locally, so skipping the
re-download step would keep publishing the old one. `--instrumento` repeated
over whichever laws were actually re-downloaded packages exactly those; the
manifest names them for review the same way it does for `--instrumento lft`
above.

Needs at least one law already seeded under ``<outdir>/leyes/`` -- `leyes`
is a literal path segment here (issue #189: it is the only collection
left). Since issue #210 there is no separate `catalogo.json`: every
subdirectory of ``<outdir>/leyes/`` is a law, including one seeded but never
crawled at all (Fase 1 pendiente, issue #124, a bare `estado.json` with no
snapshot yet), which the manifest lists rather than silently omitting.

## One-time backfill of the retired `catalogo.json` (issue #210)

``--backfill-estado CATALOGO`` writes `abrev` (verbatim), `nombre` and
`nombre_scjn` from a `catalogo.json` this machine still has -- the seed the
corpus used to carry externally -- into each matching law's own
`estado.json`, and derives `url` from an already-recorded `id_ordenamiento`.
It runs once, its output is reviewed, and the corpus is republished by hand
(#115, Hallazgo C: no Action ever does this on its own):

    ./scripts/empaqueta_scjn_leyes.py --outdir scripts/scjn \\
        --backfill-estado scripts/scjn/leyes/catalogo.json

It only ever *adds* fields (`scjn.state.escribe_estado`'s merge, never an
overwrite) to a directory that already exists under ``<outdir>/leyes/`` --
`actualizado`/`actualizado_scjn`/`rastreado`/`id_ordenamiento`, whatever a
law's `estado.json` already has, are left exactly as they are. It never
crawls or packages anything, and exits
without writing a tarball -- run it, review the diff under `<outdir>/leyes/`,
then run the normal packaging above.
"""

import argparse
import gzip
import hashlib
import io
import json
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from scjn.release import (  # noqa: E402
    ASSET_INDICE_GLOBAL,
    CAMPOS_CLASIFICACION,
    CAMPOS_METADATOS,
    AssetNotCached,
    construye_indice_global,
    download_scjn_leyes_index,
)
from scjn.catalog import slug_instrumento  # noqa: E402
from scjn.header import versiones_de_directorio  # noqa: E402
from scjn.state import ARCHIVO_ESTADO, escribe_estado, lee_estado  # noqa: E402

COLECCION = "leyes"

#: The keys of an `estado.json` that only the DOF linking wrote -- linking
#: this repository no longer holds (review fix-2, found after the fact):
#: `enlazado` (when a law was linked) and `actualizado_dof` (the newest DOF
#: date of a law). `_miembros_instrumento` drops them from the copy of
#: `estado.json` a tarball ships.
CLAVES_ESTADO_DOF = ("enlazado", "actualizado_dof")


def actualizado_publicado(directorio: Path, estado: dict) -> str | None:
    """The `actualizado` a law is published with: the date of the newest reform
    the SCJN serves for it, as `YYYY-MM-DD`, and never a DOF date (review
    fix-3, found after the fact: the `actualizado` the older code persisted in
    `estado.json` was the later of the SCJN's and the DOF's date, so shipping
    it as it was put a DOF-derived value in the release).

    It is `estado["actualizado_scjn"]` when `estado.json` has it; otherwise the
    publication date of the newest snapshot in `directorio` (by date, then by
    the `-N` repetition suffix: `scjn.header.versiones_de_directorio`'s order),
    computed offline; `None` for a law with neither. Every published
    `actualizado` of a law comes from this one function."""
    if estado.get("actualizado_scjn"):
        return estado["actualizado_scjn"]
    versiones = versiones_de_directorio(directorio)
    if not versiones:
        return None
    return datetime.strptime(versiones[-1].fecha_publicacion, "%d-%m-%Y").date().isoformat()


def estado_publicado(directorio: Path) -> dict:
    """A law's `estado.json` as it is published: the one on disk without the
    keys of `CLAVES_ESTADO_DOF` and with `actualizado` set to
    `actualizado_publicado` (no `actualizado` key at all when that is `None`).
    Computed in memory; the corpus on disk is never rewritten."""
    estado = lee_estado(directorio)
    publicado = {k: v for k, v in estado.items() if k not in (*CLAVES_ESTADO_DOF, "actualizado")}
    actualizado = actualizado_publicado(directorio, estado)
    if actualizado:
        publicado["actualizado"] = actualizado
    return publicado


def _load_catalog(outdir: Path) -> list[dict]:
    """Every law this workspace already tracks -- one entry per subdirectory
    of ``<outdir>/leyes/``, in place of the retired `catalogo.json` (issue
    #210). See `fetch_scjn_legislacion._load_catalog`, whose docstring this
    mirrors: `abrev`/`nombre` come from each law's own `estado.json`, falling
    back to `indice-global.json.gz` for `nombre` when that predates issue
    #210."""
    base = outdir / COLECCION
    if not base.is_dir():
        raise SystemExit(
            f"{base} no existe -- corre primero "
            f"./scripts/fetch_scjn_legislacion.py --outdir {outdir} --instrumento <slug>"
        )
    try:
        instrumentos = download_scjn_leyes_index()["instrumentos"]
    except AssetNotCached:
        instrumentos = {}

    catalogo = []
    for directorio in sorted(p for p in base.iterdir() if p.is_dir()):
        slug = directorio.name
        estado = lee_estado(directorio)
        nombre = estado.get("nombre") or instrumentos.get(slug, {}).get("nombre")
        if nombre is None:
            raise SystemExit(f"{directorio}: sin 'nombre' (ni en su estado.json ni en el indice)")
        entrada = {"abrev": estado.get("abrev") or slug, "nombre": nombre}
        if estado.get("nombre_scjn"):
            entrada["nombre_scjn"] = estado["nombre_scjn"]
        catalogo.append(entrada)
    return catalogo


_URL_ORDENAMIENTO = "https://legislacion.scjn.gob.mx/consulta/ordenamiento/{}"


def backfill_estado(outdir: Path, catalogo_anterior: list[dict], *, log=print) -> list[str]:
    """One-time migration (issue #210): write `abrev`/`nombre`/`nombre_scjn`
    from `catalogo_anterior` (a `catalogo.json` this machine still has) into
    each matching law's own `estado.json` under ``<outdir>/leyes/``, plus a
    `url` derived from `id_ordenamiento` when that is already on file and
    `url` is not. Returns the slugs actually written.

    Matched by `slug_instrumento` (issue #186's own reason: `lif_2026`'s
    directory is `lif-2026`, not the historical `abrev` itself), and only
    ever adds fields (`scjn.state.escribe_estado`'s merge) -- an already
    backfilled or freshly crawled `estado.json` keeps whatever it has for
    `actualizado`/`actualizado_scjn`/`rastreado`/`id_ordenamiento`
    untouched.

    A directory under ``<outdir>/leyes/`` with no matching entry in
    `catalogo_anterior` is reported and skipped, not guessed at: it means
    the two are out of sync, and this migration should not be the one
    deciding a new `abrev` for it."""
    por_slug = {slug_instrumento(entrada): entrada for entrada in catalogo_anterior}
    base = outdir / COLECCION
    escritos = []
    for directorio in sorted(p for p in base.iterdir() if p.is_dir()):
        slug = directorio.name
        anterior = por_slug.get(slug)
        if anterior is None:
            log(f"  aviso: {slug} no esta en el catalogo anterior -- se deja intacto")
            continue
        campos = {"abrev": anterior["abrev"], "nombre": anterior["nombre"]}
        if anterior.get("nombre_scjn"):
            campos["nombre_scjn"] = anterior["nombre_scjn"]
        id_ordenamiento = lee_estado(directorio).get("id_ordenamiento")
        if id_ordenamiento and not lee_estado(directorio).get("url"):
            campos["url"] = _URL_ORDENAMIENTO.format(id_ordenamiento)
        escribe_estado(directorio, **campos)
        escritos.append(slug)
    log(f"{COLECCION}: {len(escritos)} estado.json actualizado(s) con el catalogo anterior")
    return escritos


@dataclass
class ResumenInstrumento:
    """One instrument's own row in the manifest: its name, how many
    snapshots it has (`total_snapshots`) and, once `empaqueta` wrote its
    tarball, the `asset` and its `bytes_comprimidos`."""

    slug: str
    nombre: str
    total_snapshots: int
    asset: str | None = None
    bytes_comprimidos: int = 0
    #: This instrument's own `estado.json` (issue #148) — when it was last
    #: crawled, and against which catalogue `actualizado`. Shown
    #: in the manifest so the human reviewing an incremental update can see
    #: at a glance which laws the run actually refreshed.
    estado: dict | None = None
    #: Whether this run rewrote the instrument's own tarball. False for the
    #: ones a `--instrumento` run left untouched and only re-listed.
    reempaquetado: bool = True


def resume_coleccion(outdir: Path) -> tuple[list[ResumenInstrumento], list[str]]:
    """Every `leyes` instrument in the catalogue, summarized for
    the manifest, plus the catalogue names of the ones never crawled at all
    (issue #124's Fase 1 pendiente) — returned separately, since a
    never-crawled instrument has nothing on disk to package."""
    instrumentos = _load_catalog(outdir)
    resumenes = []
    nunca_rastreados = []
    for entrada in instrumentos:
        slug = slug_instrumento(entrada)
        destino = outdir / COLECCION / slug
        versiones = versiones_de_directorio(destino) if destino.is_dir() else []
        if not versiones:
            nunca_rastreados.append(entrada["nombre"])
            continue

        resumenes.append(
            ResumenInstrumento(
                slug=slug, nombre=entrada["nombre"],
                total_snapshots=len(versiones),
                estado=estado_publicado(destino) or None,
            )
        )
    return resumenes, nunca_rastreados


def _miembros_instrumento(directorio: Path) -> list[tuple[str, bytes]]:
    """Every member worth shipping for one instrument, as ``(name, bytes)``
    sorted by name: its snapshot `.md` files and its `estado.json` -- nothing
    else, whatever the directory holds. An `indice.json` or a `notas/` folder
    left by the DOF linking this repository no longer carries, and a hidden
    bookkeeping file (a `.progreso.json`-style checkpoint), are never shipped.

    The shipped `estado.json` is `estado_publicado`: no key of
    `CLAVES_ESTADO_DOF` and an SCJN-only `actualizado`. It is computed in
    memory, the corpus on disk is never rewritten; an `estado.json` that
    already is what would be published ships byte for byte as it is on disk."""
    miembros = []
    for ruta in sorted(directorio.glob("*.md")):
        if ruta.is_file() and not ruta.name.startswith("."):
            miembros.append((ruta.name, ruta.read_bytes()))
    ruta_estado = directorio / ARCHIVO_ESTADO
    if ruta_estado.is_file():
        datos = ruta_estado.read_bytes()
        publicado = estado_publicado(directorio)
        if publicado != lee_estado(directorio):
            datos = (
                json.dumps(publicado, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        miembros.append((ARCHIVO_ESTADO, datos))
    return sorted(miembros)


def empaqueta(
    outdir: Path,
    destino: Path,
    resumenes: list[ResumenInstrumento],
    solo: set[str] | None = None,
) -> None:
    """Write one `<slug>.tgz` per instrument, each **byte-reproducibly**:
    gzip stamped with mtime 0, members added in sorted order, ownership and
    mode fixed. Identical data therefore produces an identical file, which is
    what lets a publish step tell an unchanged law from a changed one by
    comparing bytes rather than guessing — the recipe the retired
    `empaqueta_historial.py` used, kept here because that property is what
    makes an incremental re-upload safe (issue #187). Every member is prefixed with
    `<slug>/` so the tarball unpacks anywhere without stepping on anything.

    `solo` (issue #148) restricts the rewriting to the named slugs — the
    incremental case, where one law changed and re-tarring the other ~314 is
    pure work for a byte-identical result. Every other instrument keeps the
    tarball already sitting in `destino` and is measured from it, so the
    manifest and the checksums still describe the whole corpus; one that has
    no tarball there yet is packaged regardless, since "skip it" would mean
    publishing a manifest row for an asset that does not exist.

    Fills each summary's `asset`/`bytes_comprimidos` in place, so the
    manifest can report what was actually written."""
    if not resumenes:
        raise SystemExit(f"{outdir / COLECCION} no tiene nada que empaquetar")

    for resumen in resumenes:
        directorio = outdir / COLECCION / resumen.slug
        salida = destino / f"{resumen.slug}.tgz"
        if solo is not None and resumen.slug not in solo and salida.is_file():
            resumen.asset = salida.name
            resumen.bytes_comprimidos = salida.stat().st_size
            resumen.reempaquetado = False
            continue
        with open(salida, "wb") as bruto, \
                gzip.GzipFile(filename="", mode="wb", fileobj=bruto, mtime=0) as gz, \
                tarfile.open(fileobj=gz, mode="w") as tar:
            for relativo, datos in _miembros_instrumento(directorio):
                info = tarfile.TarInfo(f"{resumen.slug}/{relativo}")
                info.size = len(datos)
                info.mtime = 0
                info.mode = 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(datos))
        resumen.asset = salida.name
        resumen.bytes_comprimidos = salida.stat().st_size


def escribe_indice_global(
    destino: Path, resumenes: list[ResumenInstrumento], generado: str
) -> int:
    """Write `indice-global.json.gz` next to the tarballs and return its size
    in bytes — the index a consumer needs to list the laws, their names and
    their classification without downloading 380 MB of corpus (issue #117,
    Paso 1). It has no `codNota` section: nothing about the DOF is published.

    Written like every other asset here: gzip stamped with mtime 0, laws in
    slug order (`construye_indice_global` sorts them), so an unchanged corpus
    re-packages to the same bytes except for its own `generado` stamp — the
    same caveat `MANIFEST.md` already carries, and the reason the tarballs
    are the byte-identical ones.

    Like the tarballs, this asset is **published by hand**: it has to be
    re-uploaded whenever the corpus changes, or a reader will list a corpus
    that no longer matches — the same manual step issue #148 has to respect
    when it starts updating law by law.

    Each law's classification (`CAMPOS_CLASIFICACION`) and
    `materia`/`vigencia`/`resumen` (issue #215) travel in from its own
    `estado.json`, falling back to whatever the *published* index already
    says for it — the same fallback `_load_catalog` uses for `nombre`, and for
    the same reason: `scripts/fetch_federal_law_metadata.py` writes the fields
    into a corpus and patches the published asset directly, so a workspace
    whose `estado.json` predates that run must not silently republish an index
    with the fields dropped.
    """
    try:
        publicados = download_scjn_leyes_index()["instrumentos"]
    except AssetNotCached:
        publicados = {}

    indice = construye_indice_global(
        [
            {
                "slug": r.slug,
                "nombre": r.nombre,
                "asset": r.asset or f"{r.slug}.tgz",
                "snapshots": r.total_snapshots,
                **{
                    campo: (r.estado or {}).get(campo)
                    or publicados.get(r.slug, {}).get(campo)
                    for campo in (*CAMPOS_CLASIFICACION, *CAMPOS_METADATOS)
                },
            }
            for r in resumenes
        ],
        generado=generado,
    )
    crudo = json.dumps(indice, ensure_ascii=False, sort_keys=False).encode("utf-8")
    salida = destino / ASSET_INDICE_GLOBAL
    with open(salida, "wb") as bruto, \
            gzip.GzipFile(filename="", mode="wb", fileobj=bruto, mtime=0) as gz:
        gz.write(crudo)
    return salida.stat().st_size


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _tamano(bytes_: int) -> str:
    """A size a human reads at a glance in the manifest's own table — the
    exact byte count is in the asset itself, not something to eyeball."""
    if bytes_ >= 1024 * 1024:
        return f"{bytes_ / (1024 * 1024):.1f} MB"
    return f"{bytes_ / 1024:.0f} KB"


def _formatea_manifiesto(
    resumenes: list[ResumenInstrumento],
    nunca_rastreados: list[str],
    bytes_indice: int | None = None,
) -> str:
    ordenados = sorted(resumenes, key=lambda r: r.nombre)
    total_catalogo = len(resumenes) + len(nunca_rastreados)

    lineas = [
        "# SCJN — leyes: manifiesto de empaquetado",
        "",
        f"Generado: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        f"{total_catalogo} instrumento(s) en el catálogo (`leyes`); "
        f"{len(resumenes)} ya rastreado(s) por la SCJN.",
        "",
    ]

    if nunca_rastreados:
        lineas.append(f"## Nunca rastreados — Fase 1 pendiente ({len(nunca_rastreados)}, issue #124)")
        lineas.append("")
        lineas.extend(f"- {nombre}" for nombre in sorted(nunca_rastreados))
        lineas.append("")

    # La clasificación de confianza de #115 (ratio/motivo) ya no aparece
    # aquí: los títulos se revisaron y corrigieron a mano, así que ordenar
    # por sospecha dejó de decir nada — la tabla va por nombre.
    # Issue #148: on an incremental run only a handful of laws were actually
    # rewritten, and those are the only rows a human has to read closely
    # (¿la SCJN devolvió el documento correcto?).
    # They get their own section above the full table, which stays complete
    # because the checksums and the reverse index still cover everything.
    reempaquetados = [r for r in ordenados if r.reempaquetado]
    if len(reempaquetados) != len(ordenados):
        lineas.append(f"## Actualizados en esta corrida ({len(reempaquetados)}, issue #148)")
        lineas.append("")
        lineas.append(
            f"Los otros {len(ordenados) - len(reempaquetados)} instrumento(s) conservan el "
            "`.tgz` que ya estaba en el destino; sólo se recalcularon el manifiesto, "
            f"`SHA256SUMS.txt` y `{ASSET_INDICE_GLOBAL}`. **Sube sólo estos assets** "
            f"(más `{ASSET_INDICE_GLOBAL}`, `SHA256SUMS.txt` y `MANIFEST.md`):"
        )
        lineas.append("")
        lineas.extend(
            f"- {r.nombre} (`{r.asset}`), rastreado "
            f"{(r.estado or {}).get('rastreado', '—')}"
            for r in reempaquetados
        )
        lineas.append("")

    lineas.append("## Instrumentos empaquetados")
    lineas.append("")
    lineas.append("| instrumento | slug | snapshots | asset | tamaño | rastreado |")
    lineas.append("|---|---|---|---|---|---|")
    for r in ordenados:
        lineas.append(
            f"| {r.nombre} | `{r.slug}` | {r.total_snapshots} "
            f"| `{r.asset}` | {_tamano(r.bytes_comprimidos)} "
            f"| {(r.estado or {}).get('rastreado', '—')} |"
        )
    lineas.append("")

    if bytes_indice is not None:
        lineas.append(f"## Índice — `{ASSET_INDICE_GLOBAL}`")
        lineas.append("")
        lineas.append(
            f"{len(resumenes)} instrumento(s) en el índice; {_tamano(bytes_indice)} comprimido."
        )
        lineas.append("")
        lineas.append(
            "Este asset se sube a mano igual que los tarballs — y hay que volver a "
            "subirlo cada vez que el corpus cambie, o listará un corpus que ya no corresponde."
        )
        lineas.append("")

    lineas.append(
        "**Antes de publicar**: lee esta tabla completa. Nada de este corpus se publica de "
        "forma automática — issue #128 — la decisión de que es seguro publicar es humana."
    )
    return "\n".join(lineas) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Los defaults son los directorios que el corpus usa hoy: `scripts/scjn`
    # es donde fetch ya escribio `leyes/`, y el destino cuelga de
    # ahi mismo — ambos bajo el `scripts/scjn/` que .gitignore excluye, para
    # que ninguna corrida deje datos rastreables por git.
    p.add_argument(
        "--outdir", type=Path, default=Path("scripts/scjn"),
        help="donde fetch_scjn_legislacion.py ya escribio 'leyes'",
    )
    p.add_argument("--destino", type=Path, default=Path("scripts/scjn/leyes-release"))
    p.add_argument(
        "--sin-indice-global", action="store_true",
        help=f"no escribir {ASSET_INDICE_GLOBAL} (el índice de "
        "instrumentos, issue #117); por default se genera",
    )
    p.add_argument(
        "--instrumento", action="append", metavar="SLUG",
        help=(
            "repetible; reescribe solo el .tgz de estos instrumentos (issue #148). El "
            f"manifiesto, SHA256SUMS.txt y {ASSET_INDICE_GLOBAL} se recalculan siempre "
            "completos: el indice lista todas las leyes, asi que "
            "cualquier cambio en una ley deja obsoleto el publicado"
        ),
    )
    p.add_argument(
        "--backfill-estado", type=Path, metavar="CATALOGO", default=None,
        help=(
            "migracion de una sola vez (issue #210): lee CATALOGO (un catalogo.json que "
            "este equipo aun conserve) y escribe 'abrev'/'nombre'/'nombre_scjn' -- mas "
            "'url' cuando ya hay id_ordenamiento -- en el estado.json de cada ley que "
            "coincida. No empaqueta nada; sale despues de escribir"
        ),
    )
    args = p.parse_args(argv)

    if args.backfill_estado is not None:
        catalogo_anterior = json.loads(args.backfill_estado.read_text(encoding="utf-8"))
        backfill_estado(args.outdir, catalogo_anterior, log=lambda m: print(m, file=sys.stderr))
        return 0

    args.destino.mkdir(parents=True, exist_ok=True)
    generado = datetime.now(timezone.utc).isoformat(timespec="seconds")

    resumenes, nunca_rastreados = resume_coleccion(args.outdir)
    solo = set(args.instrumento) if args.instrumento else None
    if solo is not None:
        faltantes = solo - {r.slug for r in resumenes}
        if faltantes:
            raise SystemExit(
                f"{sorted(faltantes)} no tiene(n) snapshots en {args.outdir / COLECCION} -- "
                "corre primero ./scripts/fetch_scjn_legislacion.py --instrumento <slug>"
            )
    empaqueta(args.outdir, args.destino, resumenes, solo=solo)

    bytes_indice = None
    if not args.sin_indice_global:
        bytes_indice = escribe_indice_global(args.destino, resumenes, generado)

    manifiesto = args.destino / "MANIFEST.md"
    manifiesto.write_text(
        _formatea_manifiesto(resumenes, nunca_rastreados, bytes_indice),
        encoding="utf-8",
    )

    # One line per asset, in the format `sha256sum -c` accepts.
    sumas = args.destino / "SHA256SUMS.txt"
    sumas.write_text(
        "".join(
            f"{sha256(args.destino / r.asset)}  {r.asset}\n"
            for r in sorted(resumenes, key=lambda r: r.slug)
        )
        + (
            f"{sha256(args.destino / ASSET_INDICE_GLOBAL)}  {ASSET_INDICE_GLOBAL}\n"
            if bytes_indice is not None else ""
        ),
        encoding="utf-8",
    )

    total = sum(r.bytes_comprimidos for r in resumenes)
    reescritos = sum(1 for r in resumenes if r.reempaquetado)
    if solo is not None:
        print(
            f"{reescritos} asset(s) .tgz reescrito(s): "
            f"{sorted(r.slug for r in resumenes if r.reempaquetado)}",
            file=sys.stderr,
        )
    print(
        f"{len(resumenes)} asset(s) .tgz, {_tamano(total)} en total; "
        f"{len(nunca_rastreados)} instrumento(s) sin rastrear (sin asset)",
        file=sys.stderr,
    )
    if bytes_indice is not None:
        print(
            f"{ASSET_INDICE_GLOBAL}: {len(resumenes)} instrumento(s), {_tamano(bytes_indice)}",
            file=sys.stderr,
        )
    print(
        f"-> {args.destino}/  (<slug>.tgz, {ASSET_INDICE_GLOBAL}, MANIFEST.md, "
        "SHA256SUMS.txt)",
        file=sys.stderr,
    )
    print(
        "\nLee MANIFEST.md completo antes de publicar. Nada de este corpus se publica solo.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
