"""`scjn`'s command line: the one verb this package needs, putting a release
on disk.

    scjn --version

    scjn download [--collection {laws,regulations,guidelines,treaties,bylaws}]
                  [--slug SLUG | --id ID] [--all] [--cache-dir DIR] [--refresh]

A downstream package's own `download` subcommands delegate to this same
downloader (`scjn.release.download_scjn_leyes_assets`/
`download_scjn_reglamentos_assets`/`download_scjn_lineamientos_assets`/
`download_scjn_tratados_assets`/`download_scjn_estatutos_assets`)
rather than reimplementing it.

`--collection` (issue #220, #222, #277, #9; its values are the English names of `scjn.cache.COLLECTION_CLI_NAMES`) is dispatched through
`scjn.cache.COLECCIONES_POR_ID` for the id-keyed collections
(`reglamentos`, `lineamientos`, `tratados`, `estatutos`) -- all share the exact same download path
(issue #222's Fase 0), so adding one more id-keyed collection here means one
more dict entry, not a new literal branch. `leyes` stays its own separate
branch: it takes `--slug`, not `--id`, and has no `Coleccion` descriptor at
all."""

import argparse

from scjn import __version__
from scjn.cache import CACHE_DIR, _SCJN_LEYES_RELEASE, COLECCIONES_POR_ID, COLLECTION_CLI_NAMES
from scjn.release import (
    _ULTIMO_NUMERO_DE_PARTES,
    download_scjn_estatutos_assets,
    download_scjn_leyes_assets,
    download_scjn_lineamientos_assets,
    download_scjn_reglamentos_assets,
    download_scjn_tratados_assets,
)

#: Each id-keyed collection's own downloader -- keyed by `Coleccion.nombre`,
#: same as `COLECCIONES_POR_ID` itself. A further id-keyed collection adds one
#: entry here, never a new `if`/`elif` branch.
_DESCARGAS_POR_ID = {
    "reglamentos": download_scjn_reglamentos_assets,
    "lineamientos": download_scjn_lineamientos_assets,
    "tratados": download_scjn_tratados_assets,
    "estatutos": download_scjn_estatutos_assets,
}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="scjn",
        description="Download an scjn-leyes/scjn-reglamentos/scjn-lineamientos/scjn-tratados/scjn-estatutos release "
        "-- the index plus one tarball per instrument -- into this package's own "
        "per-user cache directory, so every reader in scjn.release finds it already there.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    descarga = sub.add_parser(
        "download",
        help="Download a release's assets",
        description="Download the scjn-leyes (default), scjn-reglamentos, "
        "scjn-lineamientos, scjn-tratados or scjn-estatutos release's assets. Already-cached assets are matched by name "
        "and never revalidated, so a second run costs no download at all -- pass "
        "--refresh to force one.",
    )
    descarga.add_argument(
        "--collection", choices=tuple(COLLECTION_CLI_NAMES.values()), default=None,
        help="Which collection to download (default: laws). laws: scjn-leyes, the federal "
        "laws; regulations: scjn-reglamentos; guidelines: scjn-lineamientos; treaties: "
        "scjn-tratados, the international treaties; bylaws: scjn-estatutos, the federal "
        "instruments the SCJN classifies ESTATUTO.",
    )
    descarga.add_argument(
        "--all", action="store_true",
        help="Download every collection, whole. Cannot be combined with --collection, "
        "--slug or --id.",
    )
    descarga.add_argument(
        "--slug", action="append", default=None, metavar="SLUG", dest="slugs",
        help="Only this law's tarball, by slug (repeatable, --collection laws only). "
        "Not given: every law the release publishes. The index is always downloaded.",
    )
    descarga.add_argument(
        "--id", action="append", default=None, metavar="ID", dest="ids",
        help="Only this instrument's tarball, by id_ordenamiento (repeatable, "
        "--collection regulations/guidelines/treaties/bylaws only). Not given: every instrument the "
        "release publishes. The index is always downloaded.",
    )
    descarga.add_argument(
        "--cache-dir", default=None, metavar="DIR",
        help="Directory to write into. Not given: scjn.cache.CACHE_DIR (the "
        "OS-appropriate per-user cache, overridable with $SCJN_CACHE_DIR).",
    )
    descarga.add_argument(
        "--refresh", action="store_true",
        help="Re-download assets already present instead of keeping them",
    )
    return parser


def _download_collection(nombre, keys, cache_dir, refresh, log):
    """Download one collection (`nombre` is its internal name) and log its summary line."""
    if nombre == "leyes":
        resultados = download_scjn_leyes_assets(
            keys, cache_dir=cache_dir, refrescar=refresh, log=log,
        )
        base = _SCJN_LEYES_RELEASE
    else:
        resultados = _DESCARGAS_POR_ID[nombre](
            keys, cache_dir=cache_dir, refrescar=refresh, log=log,
        )
        base = COLECCIONES_POR_ID[nombre].tag_base
    nuevos = sum(1 for _, descargado in resultados if descargado)
    destino = resultados[0][0].parent
    partes = _ULTIMO_NUMERO_DE_PARTES.get(base)
    sufijo_partes = f" ({partes} parts)" if partes and partes > 1 else ""
    log(
        f"scjn-{nombre}: {len(resultados)} assets in {destino} "
        f"({nuevos} downloaded, {len(resultados) - nuevos} already cached){sufijo_partes}"
    )


def _main_download(args, log=print):
    if args.all and (args.collection or args.slugs or args.ids):
        raise SystemExit("--all cannot be combined with --collection, --slug or --id")
    cache_dir = args.cache_dir if args.cache_dir is not None else CACHE_DIR
    if args.all:
        for nombre in COLLECTION_CLI_NAMES:
            _download_collection(nombre, None, cache_dir, args.refresh, log)
        return
    interno = {cli: nombre for nombre, cli in COLLECTION_CLI_NAMES.items()}
    nombre = interno[args.collection or "laws"]
    if args.ids and nombre == "leyes":
        id_keyed = "/".join(c for n, c in COLLECTION_CLI_NAMES.items() if n != "leyes")
        raise SystemExit(f"--id only applies with --collection {id_keyed}")
    if args.slugs and nombre != "leyes":
        raise SystemExit("--slug only applies with --collection laws (the default)")
    _download_collection(nombre, args.slugs if nombre == "leyes" else args.ids, cache_dir, args.refresh, log)


def main(argv=None):
    # No `return` of a subcommand's own result: the console-script entry
    # point does `sys.exit(main())`, and a truthy non-int return value (a
    # list of results, say) would be printed and treated as a failing exit
    # code.
    args = build_parser().parse_args(argv)
    if args.comando == "download":
        _main_download(args)


if __name__ == "__main__":
    main()
