"""`scripts/discover_federal_laws.py` works from the SCJN alone (review fix-2:
the DOF confirmation is gone), against a fake API. No network. Run with

    pytest scripts/tests -q
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import discover_federal_laws as dfl  # noqa: E402
from scjn.api import Ordenamiento, Reforma  # noqa: E402


class FakeApi:
    def __init__(self, hits, reformas, fallan=()):
        self.hits, self.reformas, self.fallan = hits, reformas, set(fallan)
        self.reformas_pedidas: list[str] = []

    def search_ordenamiento(self, frase, *, tamanio_pagina=50, pagina=1, categoria=None, **_):
        if pagina != 1:
            return []
        return [h for h in self.hits if frase.upper() in h.ordenamiento.upper()]

    def reformas_of_ordenamiento(self, id_ordenamiento):
        self.reformas_pedidas.append(id_ordenamiento)
        if id_ordenamiento in self.fallan:
            raise RuntimeError("HTTP 500")
        return self.reformas.get(id_ordenamiento, [])


def _hit(id_, nombre):
    return Ordenamiento(idOrdenamiento=id_, ordenamiento=nombre, categoriaOrdenamiento="LEY")


class TestDiscover(unittest.TestCase):
    CATALOGO = [{"abrev": "lft", "nombre": "LEY FEDERAL DEL TRABAJO"}]

    def test_reporta_una_ley_nueva_con_la_fecha_de_su_ultima_reforma_de_la_scjn(self):
        api = FakeApi(
            [_hit("1", "LEY FEDERAL DEL TRABAJO"), _hit("2", "LEY GENERAL NUEVA")],
            {"2": [Reforma("a", "01-02-2026"), Reforma("b", "15-03-2027"), Reforma("c", "09-12-2026")]},
        )

        candidatos = dfl.discover(self.CATALOGO, api=api, log=lambda *_: None)

        self.assertEqual(
            [(c["nombre"], c["actualizado"], c["idOrdenamiento"]) for c in candidatos],
            [("LEY GENERAL NUEVA", "2027-03-15", "2")],
        )
        self.assertEqual(api.reformas_pedidas, ["2"])  # a known law is never asked about

    def test_no_pide_ni_lee_nada_del_dof(self):
        self.assertFalse(hasattr(dfl, "newest_dof_publication_dates"))
        self.assertFalse(hasattr(dfl, "legal_provisions_titles"))

    def test_un_candidato_sin_texto_consolidado_no_se_reporta(self):
        api = FakeApi(
            [_hit("2", "LEY SIN TEXTO")],
            {"2": [Reforma("a", "01-02-2026", tieneArticulos=False)]},
        )

        self.assertEqual(dfl.discover(self.CATALOGO, api=api, log=lambda *_: None), [])

    def test_una_tabla_de_reformas_que_falla_se_avisa_y_se_sigue(self):
        avisos = []
        api = FakeApi(
            [_hit("2", "LEY UNO"), _hit("3", "LEY DOS")],
            {"3": [Reforma("a", "01-02-2026")]},
            fallan={"2"},
        )

        candidatos = dfl.discover(self.CATALOGO, api=api, log=avisos.append)

        self.assertEqual([c["nombre"] for c in candidatos], ["LEY DOS"])
        self.assertTrue(any("LEY UNO" in a and "HTTP 500" in a for a in avisos))

    def test_sin_candidatos_nuevos_no_toca_la_scjn_mas_alla_de_la_busqueda(self):
        api = FakeApi([_hit("1", "LEY FEDERAL DEL TRABAJO")], {})

        self.assertEqual(dfl.discover(self.CATALOGO, api=api, log=lambda *_: None), [])
        self.assertEqual(api.reformas_pedidas, [])

    def test_el_abrev_sugerido_no_choca_con_uno_conocido(self):
        api = FakeApi(
            [_hit("2", "LEY FEDERAL DEL TRABAJO NUEVA")],
            {"2": [Reforma("a", "01-02-2026")]},
        )

        [c] = dfl.discover(self.CATALOGO, api=api, log=lambda *_: None)

        self.assertNotEqual(c["abrev"], "lft")


if __name__ == "__main__":
    unittest.main()
