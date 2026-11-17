"""`scripts/fetch_scjn_legislacion.py` decides freshness from the SCJN alone
(review fix-2: the DOF half is gone). Offline, over a temporary corpus. Run
with

    pytest scripts/tests -q
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fetch_scjn_legislacion as fetch  # noqa: E402


def _ley(raiz: Path, slug: str, **estado) -> Path:
    directorio = raiz / "leyes" / slug
    directorio.mkdir(parents=True)
    (directorio / "estado.json").write_text(
        json.dumps({"abrev": slug, "nombre": f"LEY {slug}", **estado}), encoding="utf-8"
    )
    return directorio


class TestSinDof(unittest.TestCase):
    def test_no_importa_dofjson_ni_nota2md(self):
        self.assertNotIn("dofjson", sys.modules)
        self.assertNotIn("nota2md", sys.modules)

    def test_no_tiene_los_flags_del_enlace_dof(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), self.assertRaises(SystemExit):
            fetch.main(["--help"])
        ayuda = salida.getvalue()

        self.assertNotIn("--dof-only", ayuda)
        self.assertNotIn("--cache-dir", ayuda)
        for conservado in ("--plan", "--actualiza", "--solo-fecha", "--reintenta", "--instrumento"):
            self.assertIn(conservado, ayuda)

    def test_dof_only_ya_no_existe(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            fetch.main(["--outdir", "x", "--dof-only"])

        self.assertEqual(ctx.exception.code, 2)

    def test_no_quedan_las_funciones_del_dof(self):
        self.assertFalse(hasattr(fetch, "dof_dates"))
        self.assertFalse(hasattr(fetch, "_resolver_cache_dir"))


class TestActualizadoDeLaScjn(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)

    def test_load_catalog_ignora_actualizado_dof(self):
        # `actualizado_dof` is what an older version of this repository left;
        # it is no longer a source of freshness even when newer.
        _ley(self.raiz, "lfca", actualizado_scjn="2026-05-22", actualizado_dof="2026-05-24")

        with patch.object(fetch, "download_scjn_leyes_index", side_effect=fetch.AssetNotCached("x", self.raiz)):
            [entrada] = fetch._load_catalog(self.raiz)

        self.assertEqual(entrada["actualizado"], "2026-05-22")

    def test_load_catalog_cae_al_actualizado_historico_sin_actualizado_scjn(self):
        _ley(self.raiz, "lft", actualizado="2025-06-13", actualizado_dof="2026-01-01")

        with patch.object(fetch, "download_scjn_leyes_index", side_effect=fetch.AssetNotCached("x", self.raiz)):
            [entrada] = fetch._load_catalog(self.raiz)

        self.assertEqual(entrada["actualizado"], "2025-06-13")

    def test_refresca_catalogo_escribe_solo_actualizado_scjn(self):
        ley = _ley(self.raiz, "lfca", actualizado="2026-01-01", actualizado_dof="2026-05-24")

        with patch.object(fetch, "download_scjn_leyes_index", side_effect=fetch.AssetNotCached("x", self.raiz)), \
                patch.object(fetch, "scjn_dates", return_value={"lfca": "2026-05-22"}) as fechas, \
                contextlib.redirect_stderr(io.StringIO()):
            fetch.refresca_catalogo(self.raiz)

        fechas.assert_called_once()
        estado = json.loads((ley / "estado.json").read_text())
        self.assertEqual(estado["actualizado_scjn"], "2026-05-22")
        self.assertEqual(estado["actualizado"], "2026-01-01")  # the crawl's own key, untouched
        self.assertEqual(estado["actualizado_dof"], "2026-05-24")  # never written, never erased
        self.assertTrue((self.raiz / "leyes" / ".actualizado_refrescado.json").is_file())

    def test_refresca_catalogo_conserva_la_fecha_previa_si_la_scjn_no_responde(self):
        ley = _ley(self.raiz, "lfca", actualizado_scjn="2026-05-22")

        with patch.object(fetch, "download_scjn_leyes_index", side_effect=fetch.AssetNotCached("x", self.raiz)), \
                patch.object(fetch, "scjn_dates", return_value={}), \
                contextlib.redirect_stderr(io.StringIO()):
            fetch.refresca_catalogo(self.raiz)

        self.assertEqual(json.loads((ley / "estado.json").read_text())["actualizado_scjn"], "2026-05-22")

    def test_actualiza_no_enlaza_crawl_y_reempaqueta(self):
        llamadas = []
        empaqueta = type("Emp", (), {"main": staticmethod(lambda argv: llamadas.append(argv) or 0)})

        with patch.object(fetch, "refresca_catalogo"), \
                patch.object(fetch, "planea_coleccion", return_value=["lfca"]), \
                patch.object(fetch, "rastrea_coleccion", return_value=[]) as rastrea, \
                patch.object(fetch, "_script_hermano", return_value=empaqueta) as hermano, \
                contextlib.redirect_stderr(io.StringIO()):
            fallidos = fetch.actualiza_coleccion(self.raiz, 0.0, destino=self.raiz / "rel")

        self.assertEqual(fallidos, 0)
        rastrea.assert_called_once_with(self.raiz, 0.0, instrumento={"lfca"})
        hermano.assert_called_once_with("empaqueta_scjn_leyes")
        self.assertEqual(llamadas, [["--outdir", str(self.raiz), "--destino", str(self.raiz / "rel"), "--instrumento", "lfca"]])

    def test_un_instrumento_que_la_scjn_no_devolvio_se_cuenta_fallido_y_no_se_empaqueta(self):
        with patch.object(fetch, "refresca_catalogo"), \
                patch.object(fetch, "planea_coleccion", return_value=["lfca"]), \
                patch.object(fetch, "rastrea_coleccion", return_value=["lfca"]), \
                patch.object(fetch, "_script_hermano") as hermano, \
                contextlib.redirect_stderr(io.StringIO()):
            fallidos = fetch.actualiza_coleccion(self.raiz, 0.0, destino=self.raiz / "rel")

        self.assertEqual(fallidos, 1)
        hermano.assert_not_called()


if __name__ == "__main__":
    unittest.main()
