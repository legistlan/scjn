"""`scripts/backfill_scjn_classification.py` (issue #8), against a fake SCJN
API and a temporary corpus -- no network. Run with

    pytest scripts/tests -q
"""

import json
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import backfill_scjn_classification as bf  # noqa: E402
from scjn.api import Ordenamiento, ScjnApiError  # noqa: E402


class FakeApi:
    """`respuestas` maps a searched title to the `Ordenamiento` list its page 1
    answers; `errores` maps a title to an exception to raise. Records every
    search."""

    def __init__(self, respuestas=None, errores=None):
        self.respuestas = respuestas or {}
        self.errores = errores or {}
        self.busquedas: list[str] = []

    def search_ordenamiento(self, frase, *, tamanio_pagina=50, pagina=1, **_):
        self.busquedas.append(frase)
        if frase in self.errores:
            raise self.errores[frase]
        return self.respuestas.get(frase, []) if pagina == 1 else []


def _hit(id_ordenamiento, titulo="TITULO", **campos):
    base = dict(
        categoriaOrdenamiento="CONVENIO", ambito="TRATADOS INTERNACIONALES", pais="FRANCIA",
        materia="ADMINISTRATIVO", vigencia="VIGENTE",
    )
    base.update(campos)
    return Ordenamiento(idOrdenamiento=str(id_ordenamiento), ordenamiento=titulo, **base)


def _instrumento(raiz, coleccion, clave, **estado):
    directorio = raiz / coleccion / clave
    directorio.mkdir(parents=True)
    (directorio / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
    return directorio


def _estado(directorio):
    return json.loads((directorio / "estado.json").read_text(encoding="utf-8"))


def _corre(raiz, coleccion, api, **kw):
    return bf.backfill(raiz, coleccion, api, log=lambda *_a, **_k: None, **kw)


def test_merges_the_fields_of_the_hit_with_its_own_id(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10",
                     rastreado="2026-09-01")
    api = FakeApi({"T10": [_hit(99, "OTRO"), _hit(10, "T10", estado="X", municipio="Y")]})

    resultado = _corre(tmp_path, "tratados", api)

    assert resultado["written"] == ["10"]
    estado = _estado(d)
    assert estado["ambito"] == "TRATADOS INTERNACIONALES"
    assert estado["pais"] == "FRANCIA"
    assert estado["categoria_ordenamiento"] == "CONVENIO"
    assert (estado["estado"], estado["municipio"]) == ("X", "Y")
    assert estado["materia"] == "ADMINISTRATIVO"
    # the other keys of estado.json are left alone
    assert estado["rastreado"] == "2026-09-01"
    assert estado["nombre"] == "T10"


def test_never_picks_another_hit_when_the_id_is_missing(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10")
    api = FakeApi({"T10": [_hit(99, "T10", pais="OTRO PAIS")]})

    resultado = _corre(tmp_path, "tratados", api)

    assert resultado["not_found"] == ["10"]
    assert resultado["written"] == []
    assert "pais" not in _estado(d)


def test_an_empty_value_does_not_erase_one_already_on_file(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10",
                     resumen="ya estaba")
    api = FakeApi({"T10": [_hit(10, "T10", resumen=None)]})

    _corre(tmp_path, "tratados", api)

    assert _estado(d)["resumen"] == "ya estaba"


def test_an_estado_with_ambito_but_no_stamp_is_queried(tmp_path):
    # Review fix-1: the crawl and the seed write `ambito` too (every crawled `tratados`
    # instrument had it), so it must not count as "already backfilled".
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10",
                     ambito="TRATADOS INTERNACIONALES", categoria_ordenamiento="CONVENIO")
    api = FakeApi({"T10": [_hit(10, "T10")]})

    resultado = _corre(tmp_path, "tratados", api)

    assert resultado["written"] == ["10"] and resultado["skipped"] == []
    assert api.busquedas == ["T10"]
    assert _estado(d)["pais"] == "FRANCIA"


def test_skips_an_instrument_that_already_has_the_stamp(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10",
                     clasificacion_consultada="2026-11-01")
    api = FakeApi({"T10": [_hit(10, "T10")]})

    resultado = _corre(tmp_path, "tratados", api)

    assert resultado["skipped"] == ["10"]
    assert api.busquedas == []
    assert _estado(d)["clasificacion_consultada"] == "2026-11-01"
    assert "pais" not in _estado(d)


def test_force_asks_again_and_overwrites(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10",
                     ambito="FEDERAL", clasificacion_consultada="2026-11-01")
    api = FakeApi({"T10": [_hit(10, "T10")]})

    resultado = _corre(tmp_path, "tratados", api, force=True)

    assert resultado["written"] == ["10"]
    assert _estado(d)["ambito"] == "TRATADOS INTERNACIONALES"
    assert _estado(d)["clasificacion_consultada"] == date.today().isoformat()


def test_a_written_instrument_gets_todays_stamp_even_with_no_field_to_write(tmp_path):
    vacio = Ordenamiento(idOrdenamiento="10", ordenamiento="T10")
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10")

    _corre(tmp_path, "tratados", FakeApi({"T10": [vacio]}))

    assert _estado(d) == {
        "id_ordenamiento": "10", "nombre": "T10",
        "clasificacion_consultada": date.today().isoformat(),
    }


def test_not_found_failed_untitled_and_dry_run_get_no_stamp(tmp_path):
    nf = _instrumento(tmp_path, "tratados", "1", id_ordenamiento="1", nombre="NF")
    ko = _instrumento(tmp_path, "tratados", "2", id_ordenamiento="2", nombre="KO")
    sin = _instrumento(tmp_path, "tratados", "3", id_ordenamiento="3")
    seco = _instrumento(tmp_path, "tratados", "4", id_ordenamiento="4", nombre="SECO")
    api = FakeApi({"NF": [_hit(99, "NF")], "SECO": [_hit(4, "SECO")]},
                  errores={"KO": ScjnApiError("503")})

    _corre(tmp_path, "tratados", api, dry_run=True)
    for d in (nf, ko, sin, seco):
        assert "clasificacion_consultada" not in _estado(d)
    _corre(tmp_path, "tratados", api)
    for d in (nf, ko, sin):
        assert "clasificacion_consultada" not in _estado(d)
    assert _estado(seco)["clasificacion_consultada"] == date.today().isoformat()


def test_dry_run_asks_but_writes_nothing(tmp_path):
    d = _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10")
    antes = (d / "estado.json").read_text(encoding="utf-8")
    api = FakeApi({"T10": [_hit(10, "T10")]})

    resultado = _corre(tmp_path, "tratados", api, dry_run=True)

    assert resultado["written"] == ["10"]
    assert api.busquedas == ["T10"]
    assert (d / "estado.json").read_text(encoding="utf-8") == antes


def test_a_transport_error_on_one_instrument_does_not_stop_the_others(tmp_path):
    malo = _instrumento(tmp_path, "tratados", "1", id_ordenamiento="1", nombre="MALO")
    bueno = _instrumento(tmp_path, "tratados", "2", id_ordenamiento="2", nombre="BUENO")
    api = FakeApi({"BUENO": [_hit(2, "BUENO")]}, errores={"MALO": ScjnApiError("503")})

    resultado = _corre(tmp_path, "tratados", api)

    assert resultado["failed"] == ["1"]
    assert resultado["written"] == ["2"]
    assert "ambito" not in _estado(malo)
    assert _estado(bueno)["ambito"] == "TRATADOS INTERNACIONALES"


def test_a_requests_exception_on_one_instrument_does_not_stop_the_run(tmp_path):
    # Review fix-1: a DNS failure is a `requests` exception, not a `ScjnApiError`.
    malo = _instrumento(tmp_path, "tratados", "1", id_ordenamiento="1", nombre="MALO")
    lento = _instrumento(tmp_path, "tratados", "2", id_ordenamiento="2", nombre="LENTO")
    bueno = _instrumento(tmp_path, "tratados", "3", id_ordenamiento="3", nombre="BUENO")
    api = FakeApi(
        {"BUENO": [_hit(3, "BUENO")]},
        errores={"MALO": requests.exceptions.ConnectionError("NameResolutionError"),
                 "LENTO": requests.exceptions.Timeout("timed out")},
    )

    resultado = _corre(tmp_path, "tratados", api)

    assert sorted(resultado["failed"]) == ["1", "2"]
    assert resultado["written"] == ["3"]
    assert "ambito" not in _estado(malo) and "ambito" not in _estado(lento)
    assert _estado(bueno)["ambito"] == "TRATADOS INTERNACIONALES"


def test_main_returns_zero_when_every_search_raises_a_requests_exception(tmp_path, monkeypatch, capsys):
    _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10")
    monkeypatch.setattr(
        bf, "ScjnApi",
        lambda espera: FakeApi(errores={"T10": requests.exceptions.ConnectionError("dns")}),
    )

    codigo = bf.main(["--coleccion", "tratados", "--outdir", str(tmp_path)])

    assert codigo == 0
    assert "1 failed" in capsys.readouterr().err


def test_leyes_take_the_title_from_a_snapshot_header_when_estado_has_none(tmp_path):
    d = _instrumento(tmp_path, "leyes", "lfca", id_ordenamiento="693")
    (d / "01-01-2000.md").write_text(
        "---\nfuente: scjn\nordenamiento: TITULO VIEJO\n---\n\ntexto\n", encoding="utf-8"
    )
    (d / "05-05-2020.md").write_text(
        "---\nfuente: scjn\nordenamiento: LEY FEDERAL DE CINE\n---\n\ntexto\n", encoding="utf-8"
    )
    api = FakeApi({"LEY FEDERAL DE CINE": [_hit(693, categoriaOrdenamiento="LEY", ambito="FEDERAL")]})

    resultado = _corre(tmp_path, "leyes", api)

    assert resultado["written"] == ["lfca"]
    assert api.busquedas == ["LEY FEDERAL DE CINE"]
    assert _estado(d)["categoria_ordenamiento"] == "LEY"
    assert _estado(d)["id_ordenamiento"] == "693"


def test_a_law_without_id_or_without_title_is_reported_not_searched(tmp_path):
    _instrumento(tmp_path, "leyes", "sinid", nombre="X")
    _instrumento(tmp_path, "leyes", "sintitulo", id_ordenamiento="5")
    api = FakeApi()

    resultado = _corre(tmp_path, "leyes", api)

    assert sorted(resultado["untitled"]) == ["sinid", "sintitulo"]
    assert api.busquedas == []


def test_an_id_keyed_directory_name_is_its_id_when_estado_has_none(tmp_path):
    d = _instrumento(tmp_path, "reglamentos", "104906", nombre="REGLAMENTO")
    api = FakeApi({"REGLAMENTO": [_hit(104906, "REGLAMENTO", categoriaOrdenamiento="ACUERDO (S)")]})

    _corre(tmp_path, "reglamentos", api)

    assert _estado(d)["categoria_ordenamiento"] == "ACUERDO (S)"


def test_claves_restrict_the_run(tmp_path):
    _instrumento(tmp_path, "tratados", "1", id_ordenamiento="1", nombre="A")
    _instrumento(tmp_path, "tratados", "2", id_ordenamiento="2", nombre="B")
    api = FakeApi({"A": [_hit(1, "A")], "B": [_hit(2, "B")]})

    resultado = _corre(tmp_path, "tratados", api, claves={"2"})

    assert resultado["written"] == ["2"]
    assert api.busquedas == ["B"]


def test_a_missing_collection_directory_is_an_empty_run(tmp_path):
    assert _corre(tmp_path, "lineamientos", FakeApi())["written"] == []


def test_main_exits_zero_whatever_the_misses(tmp_path, monkeypatch, capsys):
    _instrumento(tmp_path, "tratados", "10", id_ordenamiento="10", nombre="T10")
    monkeypatch.setattr(bf, "ScjnApi", lambda espera: FakeApi())

    codigo = bf.main(["--coleccion", "tratados", "--outdir", str(tmp_path), "--dry-run"])

    assert codigo == 0
    assert "not found" in capsys.readouterr().err


def test_the_seed_carries_the_classification_fields_of_a_candidate(tmp_path):
    import seed_federal_reglamentos as seed

    candidato = {
        "id_ordenamiento": "7", "nombre": "T", "categoria_ordenamiento": "CONVENIO",
        "ambito": "TRATADOS INTERNACIONALES", "pais": "FRANCIA", "estado": None, "municipio": "",
    }

    seed.seed(tmp_path, [candidato], coleccion="tratados", log=lambda *_a, **_k: None)

    estado = _estado(tmp_path / "tratados" / "7")
    assert estado["pais"] == "FRANCIA"
    assert estado["ambito"] == "TRATADOS INTERNACIONALES"
    assert "estado" not in estado and "municipio" not in estado
