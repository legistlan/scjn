#!/usr/bin/env python3
"""Discover every federal *estatuto* the SCJN lists and report a reviewable
seed list for the ``scjn-estatutos`` corpus (issue #9) -- and stop: this
script never writes anything, exactly like ``discover_federal_lineamientos.py``,
which it is modelled on.

``ESTATUTO`` is the SCJN's category for the organic statutes of federal
bodies, agencies and universities: 379 federal instruments at the audit of
13 November 2026 (``q="de"``, ``ambitoF=FEDERAL``, ``categoriaF=ESTATUTO``),
article-structured and the size of ``lineamientos``. The ``scjn-estatutos``
release is **not published yet**: this script is the first step of its
Process A (discover, review, seed, crawl, verify, package, publish).

A thin wrapper over `scjn.discovery`, naming this collection's own category
and phrases; the phrase-union paging, the reform-category rescue rule and
the coverage audit itself live there, shared with the other discovery
scripts.

    ./scripts/discover_federal_estatutos.py
    ./scripts/discover_federal_estatutos.py --json candidatos.json
    ./scripts/discover_federal_estatutos.py --auditoria-cobertura   # ~70 min, once

## Inclusion rule

Same shape as reglamentos and lineamientos: an instrument is in the corpus
when ``categoriaOrdenamiento == "ESTATUTO"``, or any row of its own reform
table has ``categoriaReforma == "ESTATUTO"``.

## Two passes, one rule

1. **The union of a phrase search over ``categoriaF=ESTATUTO``+``FEDERAL``**
   (`scjn.discovery.discover_by_category`).
2. **The reform-category rescue** (`scjn.discovery.rescue_by_reform_category`),
   applied to the other federal hits of ``q="estatuto"``: each one's own
   reform table is fetched once and checked for an ESTATUTO row.

**The yield of each phrase has not been measured yet**: unlike
``q="lineamientos"``, which alone reaches every LINEAMIENTOS instrument,
nobody has checked that ``q="estatuto"`` reaches all 379 ESTATUTO ones. The
union keeps the same short common words as the sibling scripts for that
reason, and the first run's per-phrase counts (printed on stderr) are what
should be read before trusting the list is complete.

## The one-time coverage audit (``--auditoria-cobertura``)

An instrument whose title never says "estatuto" but whose reform table the
SCJN classifies as one is invisible to the two passes, so
``--auditoria-cobertura`` sweeps every *other* federal instrument's reform
table too (~65-70 minutes at the default ``--espera``) and applies the same
rescue rule. It shares the reform-table cache of the other discovery scripts
(``--cache-dir``, default ``scripts/scjn/``).

## Reports and stops, never writes anything

The seed list this prints (or, with ``--json``, writes as a reviewable file)
is the whole deliverable. Turning it into ``estado.json`` files is
``seed_federal_reglamentos.py --coleccion estatutos``; nothing here writes
corpus state.

Needs network to the SCJN (the faceted search plus, for the rescue rule and
the coverage audit, one ``Reforma`` request per candidate). No DOF
confirmation step at all: the id-keyed collections have no DOF linking.
"""

import argparse
import json
import sys
from pathlib import Path

# Run straight from a clone, without `pip install -e .` first.
_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from scjn.api import ScjnApi  # noqa: E402
from scjn.discovery import discover  # noqa: E402

CATEGORIA = "ESTATUTO"

#: The phrases `discover_by_category` pages the category with. Whether
#: `q="estatuto"` alone reaches every ESTATUTO instrument is unmeasured; the
#: common words are the same insurance the sibling scripts keep.
FRASES_UNION = ("estatuto", "estatutos", "de", "a", "la", "y", "para", "el")

#: The one phrase whose *other-category* hits the rescue rule is applied to.
FRASE_RESCATE = "estatuto"

#: Every other federal category worth sweeping for the coverage audit --
#: `discover_federal_lineamientos.py`'s own list with ESTATUTO removed
#: (covered by this script's own primary pass) and LINEAMIENTOS added back.
FRASES_AUDITORIA_COBERTURA = (
    ("ley", "LEY"), ("codigo", "CODIGO"), ("constitucion", "CONSTITUCION"),
    ("reglamento", "REGLAMENTO"), ("acuerdo", "ACUERDO"), ("lineamientos", "LINEAMIENTOS"),
    ("decreto", "DECRETO"), ("instrumento normativo", "INSTRUMENTO NORMATIVO"),
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--espera", type=float, default=0.5,
        help="seconds to wait between requests to the SCJN (default: 0.5)",
    )
    parser.add_argument(
        "--auditoria-cobertura", action="store_true",
        help=(
            "besides the two normal passes, sweep the rest of the federal universe "
            "(~8800 instruments, ~65-70 min) looking for an ESTATUTO invisible to "
            "the title -- once"
        ),
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path(__file__).resolve().parent / "scjn",
        help=(
            "where to cache the reform tables the coverage audit sweeps; shared with "
            "the other discover_federal_*.py scripts (default: %(default)s, gitignored)"
        ),
    )
    parser.add_argument(
        "--json", type=Path, default=None, metavar="FILE",
        help="besides printing the list, write it as JSON to FILE",
    )
    args = parser.parse_args(argv)

    def log(mensaje: str) -> None:
        print(mensaje, file=sys.stderr)

    candidatos = discover(
        ScjnApi(espera=args.espera),
        categoria=CATEGORIA,
        frases_union=FRASES_UNION,
        frase_rescate=FRASE_RESCATE,
        auditoria_cobertura=args.auditoria_cobertura,
        frases_auditoria=FRASES_AUDITORIA_COBERTURA,
        cache_dir=args.cache_dir,
        log=log,
    )

    log(f"\ndiscovery: {len(candidatos)} estatuto(s) -- NOTHING was written:")
    for c in candidatos:
        log(
            f"    {c['id_ordenamiento']}  {c['categoria_ordenamiento']}  "
            f"{c['vigencia']}  {c['reformas']} reform(s), {c['reformas_con_texto']} with text"
        )
        log(f"        {c['nombre']}")
    log(
        "  review the list; writing each one's estado.json is "
        "scripts/seed_federal_reglamentos.py --coleccion estatutos, and is not done here"
    )

    if args.json:
        args.json.write_text(
            json.dumps(candidatos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        log(f"\nlist written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
