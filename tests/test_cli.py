"""`scjn download` (`scjn.cli`): the `--coleccion` dispatch, with the downloaders
replaced -- nothing here touches the network (issue #9)."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scjn import cli
from scjn.cache import COLECCIONES_POR_ID


class TestColeccionEstatutos(unittest.TestCase):
    def test_el_parser_acepta_estatutos(self):
        args = cli.build_parser().parse_args(["download", "--coleccion", "estatutos"])
        self.assertEqual(args.coleccion, "estatutos")

    def test_el_parser_sigue_rechazando_una_coleccion_desconocida(self):
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            cli.build_parser().parse_args(["download", "--coleccion", "acuerdos"])

    def test_estatutos_despacha_a_download_scjn_estatutos_assets(self):
        llamado = {}

        def falso(ids, **kw):
            llamado.update(ids=ids, **kw)
            return [(Path("/c/scjn-estatutos/5001.tgz"), True)]

        with patch.dict(cli._DESCARGAS_POR_ID, {"estatutos": falso}):
            cli._main_download(
                cli.build_parser().parse_args(
                    ["download", "--coleccion", "estatutos", "--id", "5001", "--cache-dir", "/c"]
                ),
                log=lambda *_a, **_k: None,
            )

        self.assertEqual(llamado["ids"], ["5001"])
        self.assertEqual(llamado["cache_dir"], "/c")

    def test_cada_coleccion_id_keyed_tiene_su_descarga(self):
        self.assertEqual(set(cli._DESCARGAS_POR_ID), set(COLECCIONES_POR_ID))
        self.assertIs(
            cli._DESCARGAS_POR_ID["estatutos"], __import__("scjn").download_scjn_estatutos_assets
        )

    def test_id_con_leyes_sigue_siendo_un_error(self):
        args = cli.build_parser().parse_args(["download", "--id", "5001"])
        with self.assertRaises(SystemExit):
            cli._main_download(args, log=lambda *_a, **_k: None)


if __name__ == "__main__":
    unittest.main()
