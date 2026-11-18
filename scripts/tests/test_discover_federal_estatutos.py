"""`scripts/discover_federal_estatutos.py` (issue #9) against a fake SCJN API --
no network, and no state is ever written. Run with `pytest scripts/tests -q`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import discover_federal_estatutos as dfe  # noqa: E402
from scjn.api import Ordenamiento, Reforma  # noqa: E402


class FakeApi:
    """`resultados` maps `(frase, categoria)` to a page-1 answer."""

    def __init__(self, resultados, reformas):
        self.resultados = resultados
        self.reformas = reformas
        self.busquedas = []

    def search_ordenamiento(self, frase, *, tamanio_pagina, categoria, ambito, pagina):
        if pagina > 1:
            return []
        self.busquedas.append((frase, categoria, ambito))
        return self.resultados.get((frase, categoria), [])

    def reformas_of_ordenamiento(self, id_ordenamiento):
        return self.reformas.get(str(id_ordenamiento), [])


def _hit(id_ordenamiento, nombre, categoria):
    return Ordenamiento(
        idOrdenamiento=id_ordenamiento, ordenamiento=nombre, categoriaOrdenamiento=categoria,
        ambito="FEDERAL", vigencia="VIGENTE",
    )


def test_the_constants_are_the_documented_ones():
    assert dfe.CATEGORIA == "ESTATUTO"
    assert dfe.FRASES_UNION == ("estatuto", "estatutos", "de", "a", "la", "y", "para", "el")
    assert dfe.FRASE_RESCATE == "estatuto"
    categorias = {categoria for _, categoria in dfe.FRASES_AUDITORIA_COBERTURA}
    assert "ESTATUTO" not in categorias and "LINEAMIENTOS" in categorias


def test_help_works(capsys):
    try:
        dfe.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "estatuto" in capsys.readouterr().out.lower()


def _api():
    return FakeApi(
        resultados={
            ("estatuto", "ESTATUTO"): [_hit("1", "ESTATUTO ORGANICO A", "ESTATUTO")],
            ("de", "ESTATUTO"): [
                _hit("1", "ESTATUTO ORGANICO A", "ESTATUTO"),
                _hit("2", "ESTATUTO DE B", "ESTATUTO"),
            ],
            # the rescue phrase across every category
            ("estatuto", ""): [
                _hit("1", "ESTATUTO ORGANICO A", "ESTATUTO"),
                _hit("3", "ACUERDO POR EL QUE SE EXPIDE C", "ACUERDO (S)"),
                _hit("4", "ACUERDO SIN ESTATUTO D", "ACUERDO (S)"),
            ],
        },
        reformas={
            "1": [Reforma(reformaId=1, fecha_publicacion="01-01-2020", tieneArticulos=True)],
            "2": [Reforma(reformaId=2, fecha_publicacion="01-01-2020", tieneArticulos=True)],
            # an ACUERDO (S) instrument with an ESTATUTO reform row is rescued
            "3": [Reforma(reformaId=3, fecha_publicacion="01-01-2020", categoria="ESTATUTO",
                          tieneArticulos=True)],
            "4": [Reforma(reformaId=4, fecha_publicacion="01-01-2020", categoria="ACUERDO",
                          tieneArticulos=True)],
        },
    )


def test_discovery_includes_members_and_rescues_by_reform_row(tmp_path):
    from scjn.discovery import discover

    api = _api()

    candidatos = discover(
        api, categoria=dfe.CATEGORIA, frases_union=dfe.FRASES_UNION,
        frase_rescate=dfe.FRASE_RESCATE, frases_auditoria=dfe.FRASES_AUDITORIA_COBERTURA,
        cache_dir=tmp_path, log=lambda *_a, **_k: None,
    )

    assert {c["id_ordenamiento"] for c in candidatos} == {"1", "2", "3"}
    assert ("estatuto", "ESTATUTO", "FEDERAL") in api.busquedas
    assert list(tmp_path.iterdir()) == []  # nothing is written without the audit


def test_main_prints_the_list_and_writes_no_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dfe, "ScjnApi", lambda espera: _api())
    antes = set(tmp_path.rglob("*"))

    codigo = dfe.main(["--cache-dir", str(tmp_path)])

    assert codigo == 0
    err = capsys.readouterr().err
    assert "3 estatuto(s)" in err and "NOTHING was written" in err
    assert set(tmp_path.rglob("*")) == antes
    assert not list(tmp_path.rglob("estado.json"))


def test_json_option_writes_only_the_review_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dfe, "ScjnApi", lambda espera: _api())
    salida = tmp_path / "candidatos.json"

    dfe.main(["--cache-dir", str(tmp_path), "--json", str(salida)])

    assert salida.is_file()
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["candidatos.json"]
