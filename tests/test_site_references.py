"""Audit of the repository for references to the SCJN's retired WebForms
*Buscador* (issue #277).

The SCJN's current legislation site is `legislacion.scjn.gob.mx/consulta`
(the page headed "La clave de la Corte"), read through the SCOW JSON backend
`scjn.api` talks to; the legacy WebForms crawler behind the `/Buscador/` path
of the same host was retired in issue #179. A link left pointing at the old
site is a live link to a dead page, so this test fails on any occurrence of
that URL anywhere in the tree. The two frozen history documents that named
it stayed in the monorepo this package was extracted from (with `nota2md`), so this
repository has no exempt file.

Historical *narrative* that says the old path was replaced does not name the
URL and is not touched by this test.

It needs the repository checkout: a `scjn` tested from an sdist has no
`scripts/` next to it, and the test skips with that reason rather than
passing vacuously.
"""

import functools
import os
import unittest
from pathlib import Path

import scjn.api

RAIZ = Path(__file__).resolve().parents[1]

#: Built from pieces so this file does not itself contain the string it
#: forbids.
URL_PROHIBIDA = "legislacion.scjn.gob.mx/" + "Buscador"

SUFIJOS = {".py", ".md", ".rst", ".qmd", ".yml", ".yaml", ".toml", ".json"}

#: Directories never walked: version control, environments, the Sphinx build
#: output, Quarto's build output and the gitignored crawl scratch (the four corpora, the raw SCOW
#: answers and the packaged releases under `scripts/scjn/`).
DIRECTORIOS_EXCLUIDOS = (
    ".git", ".venv", "output", "scripts/scjn", "docs/build", "website/_site", "website/.quarto",
)
NOMBRES_EXCLUIDOS = ("__pycache__", "node_modules")


def _es_excluido(relativa: Path) -> bool:
    texto = relativa.as_posix()
    if any(texto == d or texto.startswith(d + "/") for d in DIRECTORIOS_EXCLUIDOS):
        return True
    return any(parte in NOMBRES_EXCLUIDOS for parte in relativa.parts)


@functools.cache
def _archivos_a_auditar():
    """Every `(relative path, path)` to audit (memoized). Walks with pruning:
    `.venv/` and `scripts/scjn/` hold hundreds of thousands of files that must
    never be listed, let alone read."""
    encontrados = []
    for directorio, subdirectorios, archivos in os.walk(RAIZ):
        base = Path(directorio)
        subdirectorios[:] = sorted(
            d for d in subdirectorios if not _es_excluido((base / d).relative_to(RAIZ))
        )
        for nombre in sorted(archivos):
            ruta = base / nombre
            if ruta.suffix not in SUFIJOS or not ruta.is_file():
                continue
            relativa = ruta.relative_to(RAIZ)
            if not _es_excluido(relativa):
                encontrados.append((relativa, ruta))
    return tuple(encontrados)


@unittest.skipUnless(
    (RAIZ / "scjn").is_dir() and (RAIZ / "scripts").is_dir(),
    "needs the repository checkout (scjn/ and scripts/ next to tests/)",
)
class TestNingunaReferenciaAlBuscadorRetirado(unittest.TestCase):
    def test_ningun_archivo_enlaza_el_sitio_retirado(self):
        encontrados = []
        for relativa, ruta in _archivos_a_auditar():
            try:
                texto = ruta.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if URL_PROHIBIDA in texto:
                encontrados.append(relativa.as_posix())

        self.assertEqual(
            encontrados, [],
            f"{URL_PROHIBIDA} is the retired WebForms site (issue #179); link "
            "https://legislacion.scjn.gob.mx/consulta/home instead",
        )

    def test_el_audit_recorre_el_arbol_y_respeta_las_exclusiones(self):
        auditados = {relativa.as_posix() for relativa, _ in _archivos_a_auditar()}

        self.assertIn("scjn/api.py", auditados)
        self.assertIn("scripts/verify_scjn_outline.py", auditados)
        self.assertIn("docs/source/index.rst", auditados)
        self.assertFalse(any(a.startswith(".venv/") for a in auditados))
        self.assertFalse(any(a.startswith("scripts/scjn/") for a in auditados))

    def test_el_audit_detecta_una_referencia_prohibida(self):
        # The needle is the host plus the retired path, so it matches the
        # retired site's URLs and nothing of the current one.
        self.assertIn(URL_PROHIBIDA, f"https://{URL_PROHIBIDA}/")
        self.assertNotIn(URL_PROHIBIDA, "https://legislacion.scjn.gob.mx/consulta/home")


class TestElClienteLeeElSitioActual(unittest.TestCase):
    """The audit also pins the *current* site: the SCOW backend `scjn.api`
    reads sits under the same host the retired Buscador did."""

    def test_base_url_es_el_backend_scow_de_legislacion_scjn(self):
        self.assertTrue(
            scjn.api.BASE_URL.startswith("https://legislacion.scjn.gob.mx/SCOW-API"),
            scjn.api.BASE_URL,
        )
        self.assertNotIn("Buscador", scjn.api.BASE_URL)


if __name__ == "__main__":
    unittest.main()
