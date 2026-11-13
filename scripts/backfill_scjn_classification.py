#!/usr/bin/env python3
"""Fill the SCJN's classification of an instrument into the `estado.json` of
every instrument already crawled (issue #8).

The crawl scripts record `materia`/`vigencia`/`resumen` and, for the id-keyed
collections, `categoria_ordenamiento` and `ambito`; nothing recorded `pais`,
`estado` or `municipio`, and `leyes` never recorded `categoria_ordenamiento`
or `ambito`. Re-crawling 2,900 instruments to read five fields would be
absurd, so this script asks the SCJN's search once per instrument and merges
what it answers into `estado.json`:

    ./scripts/backfill_scjn_classification.py --coleccion leyes
    ./scripts/backfill_scjn_classification.py --coleccion tratados --dry-run
    ./scripts/backfill_scjn_classification.py --coleccion reglamentos --id 104906
    ./scripts/backfill_scjn_classification.py --coleccion leyes --slug lfca --force

For every directory ``<outdir>/<coleccion>/<key>/`` with an `id_ordenamiento`
(`estado.json`; for an id-keyed collection the directory name is the id when
`estado.json` has none) and a title (`nombre` of `estado.json`, else the
`ordenamiento` of the newest snapshot's provenance header, through
`scjn.header`), it calls `scjn.api.instrument_metadata` and merges
`categoria_ordenamiento`, `ambito`, `pais`, `estado`, `municipio`, `materia`,
`vigencia` and `resumen` into `estado.json` with `scjn.state.escribe_estado`.
Only values the SCJN gives are written: a field it leaves empty never erases
one already on file, and no other key of `estado.json` is touched.

**Nothing is ranked or chosen.** The title is only a way to reach the search
index; the hit is the one whose `idOrdenamiento` equals the instrument's own
(the SCJN's search can return a completely wrong document, issue #115,
Hallazgo C). An instrument the search does not surface is printed and left
alone, never guessed.

**Resumable.** An instrument whose `estado.json` already has `ambito` is
skipped unless `--force`. A transport error on one instrument is warned
about and skipped, so rerunning picks it up. The exit status is 0 whatever
the misses and the transport errors; it is 1 only for a bad invocation.

`--dry-run` calls the SCJN and prints what would be written, and writes
nothing. Nothing here publishes: after the backfill a human re-packages the
collection (`empaqueta_scjn_*.py`) and publishes the regenerated index asset.
"""

import argparse
import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from scjn.api import ScjnApi, ScjnApiError, instrument_metadata  # noqa: E402
from scjn.cache import COLECCIONES_POR_ID  # noqa: E402
from scjn.header import lee_cabecera  # noqa: E402
from scjn.state import escribe_estado, lee_estado  # noqa: E402

COLECCIONES = ("leyes", *COLECCIONES_POR_ID)

#: `estado.json` key -> `scjn.api.Ordenamiento` attribute: the classification
#: (`scjn.release.CAMPOS_CLASIFICACION`) and the per-instrument metadata
#: (`CAMPOS_METADATOS`), the two sets an index carries.
CAMPOS_DE_ESTADO = {
    "categoria_ordenamiento": "categoriaOrdenamiento",
    "ambito": "ambito",
    "pais": "pais",
    "estado": "estado",
    "municipio": "municipio",
    "materia": "materia",
    "vigencia": "vigencia",
    "resumen": "resumen",
}

#: The marker of "already backfilled": every hit of the SCJN's search carries
#: an `ambito`, so a state without it was never filled.
CAMPO_MARCA = "ambito"


def _titulo(directorio: Path, estado: dict) -> str | None:
    """The SCJN's own title for the instrument in `directorio`: `nombre` of its
    `estado.json`, else the `ordenamiento` of its newest snapshot's header."""
    if estado.get("nombre"):
        return estado["nombre"]
    # `DD-MM-YYYY[-N].md` -- the newest by date, not by name.
    def fecha(archivo: Path):
        partes = archivo.stem.split("-")
        return (partes[2], partes[1], partes[0]) if len(partes) >= 3 else ("", "", "")

    for archivo in sorted(directorio.glob("*.md"), key=fecha, reverse=True):
        titulo = lee_cabecera(archivo).get("ordenamiento")
        if titulo:
            return titulo
    return None


def backfill(
    outdir: Path,
    coleccion: str,
    api,
    *,
    claves: set[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    log=print,
) -> dict:
    """Merge the SCJN's classification into the `estado.json` of every
    instrument of `coleccion` under `outdir` and return the tally:
    ``{"written": [key...], "skipped": [...], "not_found": [...],
    "untitled": [...], "failed": [...]}``.

    `api` is anything with `search_ordenamiento` (a `ScjnApi`, or a fake in a
    test). `claves` restricts the run to those directory names. With
    `dry_run` the SCJN is asked and nothing is written (`written` then lists
    what would have been).
    """
    result = {"written": [], "skipped": [], "not_found": [], "untitled": [], "failed": []}
    base = outdir / coleccion
    directorios = sorted(d for d in base.iterdir() if d.is_dir()) if base.is_dir() else []
    for directorio in directorios:
        clave = directorio.name
        if claves is not None and clave not in claves:
            continue
        estado = lee_estado(directorio)
        if estado.get(CAMPO_MARCA) and not force:
            result["skipped"].append(clave)
            continue
        id_ordenamiento = estado.get("id_ordenamiento")
        if not id_ordenamiento and coleccion != "leyes":
            id_ordenamiento = clave
        titulo = _titulo(directorio, estado)
        if not id_ordenamiento or not titulo:
            log(f"  {clave}: no id_ordenamiento or no title -- cannot search")
            result["untitled"].append(clave)
            continue
        try:
            hit = instrument_metadata(api, titulo, id_ordenamiento)
        except ScjnApiError as exc:
            log(f"  warning: {clave}: the search failed ({exc}) -- skipped")
            result["failed"].append(clave)
            continue
        if hit is None:
            log(f"  {clave}: the search did not return idOrdenamiento={id_ordenamiento}")
            result["not_found"].append(clave)
            continue
        campos = {
            campo: getattr(hit, atributo)
            for campo, atributo in CAMPOS_DE_ESTADO.items()
            if getattr(hit, atributo)
        }
        if not dry_run and campos:
            escribe_estado(directorio, **campos)
        log(f"  {clave}: {'would write' if dry_run else 'wrote'} {sorted(campos)}")
        result["written"].append(clave)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--coleccion", choices=COLECCIONES, required=True)
    parser.add_argument(
        "--outdir", type=Path, default=Path("scripts/scjn"),
        help="corpus root: <outdir>/<coleccion>/<key>/ (default: %(default)s)",
    )
    parser.add_argument(
        "--id", action="append", default=[], dest="ids",
        help="only this id_ordenamiento (id-keyed collection); repeatable",
    )
    parser.add_argument(
        "--slug", action="append", default=[], dest="slugs",
        help="only this slug (leyes); repeatable",
    )
    parser.add_argument(
        "--force", action="store_true", help="also the instruments that already have 'ambito'"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="ask the SCJN, write nothing"
    )
    parser.add_argument(
        "--espera", type=float, default=0.5,
        help="seconds to wait between requests to the SCJN (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    if args.coleccion == "leyes" and args.ids:
        parser.error("--id is for the id-keyed collections; use --slug for leyes")
    if args.coleccion != "leyes" and args.slugs:
        parser.error("--slug is for leyes; use --id for an id-keyed collection")
    claves = set(args.ids) | set(args.slugs) or None

    log = lambda mensaje: print(mensaje, file=sys.stderr)  # noqa: E731
    result = backfill(
        args.outdir, args.coleccion, ScjnApi(espera=args.espera),
        claves=claves, force=args.force, dry_run=args.dry_run, log=log,
    )
    log(
        f"{args.coleccion}: {len(result['written'])} "
        f"{'to write (--dry-run)' if args.dry_run else 'written'}, "
        f"{len(result['skipped'])} already filled, "
        f"{len(result['not_found'])} not found, "
        f"{len(result['untitled'])} without title/id, {len(result['failed'])} failed"
    )
    for etiqueta in ("not_found", "untitled", "failed"):
        if result[etiqueta]:
            log(f"{args.coleccion}: {etiqueta}: {sorted(result[etiqueta])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
