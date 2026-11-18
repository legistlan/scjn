"""This repository holds SCJN data only. Nothing in it depends on the
*Diario Oficial de la Federación* side of the project: the package mentions
neither `nota2md` nor `dofjson` anywhere, and no script under `scripts/`
imports either of them (the DOF linking that used to need them lives outside
this repository). Enforced here, not just by intention."""

import ast
import re
import unittest
from pathlib import Path

_PROHIBITED = re.compile(r"nota2md|dofjson")
_RAIZ = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _RAIZ / "scjn"
_SCRIPTS_DIR = _RAIZ / "scripts"


def _modulos_importados(ruta: Path) -> list[tuple[int, str]]:
    """Every module a Python file imports, as ``(lineno, dotted name)``."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    importados = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.extend((nodo.lineno, alias.name) for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.append((nodo.lineno, nodo.module))
    return importados


def _scripts() -> list[Path]:
    """The scripts and their tests, not the corpus under `scripts/scjn/`."""
    return sorted(
        ruta for ruta in _SCRIPTS_DIR.rglob("*.py") if "scjn" not in ruta.relative_to(_SCRIPTS_DIR).parts[:1]
    )


class TestDependencyDirection(unittest.TestCase):
    def test_no_source_file_mentions_nota2md_or_dofjson(self):
        hits = [
            f"{path}:{lineno}: {line}"
            for path in sorted(_PACKAGE_DIR.rglob("*.py"))
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _PROHIBITED.search(line)
        ]
        self.assertEqual(hits, [])

    def test_no_script_imports_nota2md_or_dofjson(self):
        scripts = _scripts()
        self.assertGreater(len(scripts), 5)  # the walk found the scripts at all
        hits = [
            f"{path}:{lineno}: import {modulo}"
            for path in scripts
            for lineno, modulo in _modulos_importados(path)
            if _PROHIBITED.fullmatch(modulo.split(".")[0])
        ]
        self.assertEqual(hits, [])

    def test_pyproject_no_declara_dofjson_ni_nota2md(self):
        self.assertIsNone(_PROHIBITED.search((_RAIZ / "pyproject.toml").read_text(encoding="utf-8")))

    def test_el_detector_de_imports_ve_un_import_prohibido(self):
        # The test above would pass vacuously if `_modulos_importados` were
        # blind; prove it sees both shapes.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "x.py"
            ruta.write_text("import dofjson.titulos\nfrom nota2md.linking import f\nimport os\n")
            self.assertEqual(
                [m for _, m in _modulos_importados(ruta)],
                ["dofjson.titulos", "nota2md.linking", "os"],
            )


if __name__ == "__main__":
    unittest.main()
