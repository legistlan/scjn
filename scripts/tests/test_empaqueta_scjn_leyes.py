"""`scripts/empaqueta_scjn_leyes.py`: a `leyes` tarball ships the snapshots and
`estado.json` only, with no key of the DOF linking, and the index has no
`codNota` section -- over a temporary corpus laid out the way an older version
of this repository left it (an `indice.json`, a `notas/` folder and an
`estado.json` with `enlazado`/`actualizado_dof`). No network. Run with

    pytest scripts/tests -q
"""

import gzip
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import empaqueta_scjn_leyes as emp  # noqa: E402
from scjn import release  # noqa: E402

CABECERA = (
    "---\nfuente: scjn\nordenamiento: LEY FEDERAL DE CINE\n"
    "fecha_publicacion: {fecha}\ncategoria: LEY\n---\n\n"
)

ESTADO_VIEJO = {
    "abrev": "lfca", "nombre": "LEY Federal de Cine", "id_ordenamiento": "188805",
    "actualizado": "2026-05-22", "actualizado_scjn": "2026-05-22",
    "actualizado_dof": "2026-05-24", "enlazado": "2026-09-01", "rastreado": "2026-09-01",
    "ambito": "FEDERAL", "categoria_ordenamiento": "LEY", "materia": "ADMINISTRATIVO",
}


class CorpusTemporal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.outdir = self.tmp / "corpus"
        self.destino = self.tmp / "release"
        self.destino.mkdir()
        self.ley = self.outdir / "leyes" / "lfca"
        (self.ley / "notas").mkdir(parents=True)
        (self.ley / "05-01-1999.md").write_text(CABECERA.format(fecha="05-01-1999") + "UNO\n")
        (self.ley / "22-05-2026.md").write_text(CABECERA.format(fecha="22-05-2026") + "DOS\n")
        (self.ley / "indice.json").write_text(json.dumps([
            {"archivo": "05-01-1999.md", "codNota": 1, "title_link_status": "linked"},
            {"archivo": "22-05-2026.md", "codNota": 2, "title_link_status": "linked"},
        ]))
        (self.ley / "notas" / "nota-1.md").write_text("DECRETO uno")
        (self.ley / ".progreso.json").write_text("{}")
        self.estado_en_disco = json.dumps(ESTADO_VIEJO, indent=2, sort_keys=True) + "\n"
        (self.ley / "estado.json").write_text(self.estado_en_disco)

    def empaqueta(self, solo=None):
        # No published index in the (empty) cache directory: the result must not depend on
        # whatever this machine has cached (a cached `lfca` index used to hide a missing
        # `nombre` locally while CI, with an empty cache, failed).
        with patch("scjn.cache.CACHE_DIR", self.tmp / "cache-vacio"):
            resumenes, nunca = emp.resume_coleccion(self.outdir)
            emp.empaqueta(self.outdir, self.destino, resumenes, solo=solo)
            bytes_indice = emp.escribe_indice_global(self.destino, resumenes, "2026-11-17T00:00:00+00:00")
        return resumenes, nunca, bytes_indice

    def miembros(self):
        with tarfile.open(self.destino / "lfca.tgz") as tar:
            return {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}


class TestTarball(CorpusTemporal):
    def test_solo_lleva_los_snapshots_y_el_estado(self):
        self.empaqueta()

        self.assertEqual(
            sorted(self.miembros()),
            ["lfca/05-01-1999.md", "lfca/22-05-2026.md", "lfca/estado.json"],
        )

    def test_ni_indice_json_ni_notas_ni_archivos_ocultos(self):
        self.empaqueta()

        nombres = " ".join(self.miembros())
        for prohibido in ("indice.json", "notas", ".progreso"):
            self.assertNotIn(prohibido, nombres)

    def test_el_estado_enviado_no_trae_claves_del_enlace_dof(self):
        self.empaqueta()

        estado = json.loads(self.miembros()["lfca/estado.json"])

        for clave in emp.CLAVES_ESTADO_DOF:
            self.assertNotIn(clave, estado)
        self.assertNotIn("enlazado", estado)
        self.assertNotIn("actualizado_dof", estado)
        esperado = {k: v for k, v in ESTADO_VIEJO.items() if k not in ("enlazado", "actualizado_dof")}
        self.assertEqual(estado, esperado)

    def test_el_corpus_en_disco_no_se_reescribe(self):
        self.empaqueta()

        self.assertEqual((self.ley / "estado.json").read_text(), self.estado_en_disco)
        self.assertTrue((self.ley / "indice.json").is_file())
        self.assertTrue((self.ley / "notas" / "nota-1.md").is_file())

    def test_un_estado_ya_publicable_viaja_byte_por_byte(self):
        limpio = json.dumps(  # not even normalized
            {"abrev": "lfca", "nombre": "LEY Federal de Cine", "actualizado": "2026-05-22"}
        )
        (self.ley / "estado.json").write_text(limpio)

        self.empaqueta()

        self.assertEqual(self.miembros()["lfca/estado.json"], limpio.encode("utf-8"))

    def test_es_reproducible_byte_por_byte(self):
        self.empaqueta()
        primero = (self.destino / "lfca.tgz").read_bytes()
        self.empaqueta()

        self.assertEqual((self.destino / "lfca.tgz").read_bytes(), primero)

    def test_el_resumen_cuenta_los_snapshots_de_los_encabezados(self):
        resumenes, nunca, _ = self.empaqueta()

        [r] = resumenes
        self.assertEqual((r.slug, r.total_snapshots), ("lfca", 2))
        self.assertEqual(nunca, [])


class TestActualizadoSoloSCJN(CorpusTemporal):
    """Review fix-3: the `actualizado` a release carries is an SCJN date only."""

    def estado_enviado(self, directorio="lfca"):
        with tarfile.open(self.destino / f"{directorio}.tgz") as tar:
            return json.loads(tar.extractfile(f"{directorio}/estado.json").read())

    def test_con_actualizado_scjn_gana_sobre_la_fecha_mezclada_con_el_dof(self):
        estado = {**ESTADO_VIEJO, "actualizado": "2026-06-30", "actualizado_scjn": "2026-05-22"}
        (self.ley / "estado.json").write_text(json.dumps(estado))

        self.empaqueta()

        enviado = self.estado_enviado()
        self.assertEqual(enviado["actualizado"], "2026-05-22")
        self.assertEqual(enviado["actualizado_scjn"], "2026-05-22")
        self.assertNotIn("actualizado_dof", enviado)
        self.assertNotIn("enlazado", enviado)

    def test_sin_actualizado_scjn_es_la_fecha_del_snapshot_mas_nuevo(self):
        for ruta in self.ley.glob("*.md"):
            ruta.unlink()
        for nombre, fecha in [
            ("05-02-1917.md", "05-02-1917"), ("01-04-2025.md", "01-04-2025"),
            ("01-04-2025-2.md", "01-04-2025"), ("22-05-2024.md", "22-05-2024"),
        ]:
            (self.ley / nombre).write_text(CABECERA.format(fecha=fecha) + "X\n")
        estado = {k: v for k, v in ESTADO_VIEJO.items() if k != "actualizado_scjn"}
        estado["actualizado"] = "2026-06-30"  # the old code's DOF-later value
        (self.ley / "estado.json").write_text(json.dumps(estado))

        self.empaqueta()

        enviado = self.estado_enviado()
        self.assertEqual(enviado["actualizado"], "2025-04-01")
        self.assertNotIn("actualizado_scjn", enviado)
        self.assertNotIn("actualizado_dof", enviado)

    def test_una_ley_sin_snapshots_no_lleva_actualizado(self):
        directorio = self.outdir / "leyes" / "vacia"
        directorio.mkdir()
        (directorio / "estado.json").write_text(json.dumps(
            {"nombre": "LEY VACIA", "actualizado": "2026-06-30", "actualizado_dof": "2026-06-30"}
        ))

        self.assertEqual(emp.estado_publicado(directorio), {"nombre": "LEY VACIA"})
        self.assertIsNone(emp.actualizado_publicado(directorio, emp.lee_estado(directorio)))
        resumenes, nunca = emp.resume_coleccion(self.outdir)
        self.assertEqual([r.slug for r in resumenes], ["lfca"])
        self.assertEqual(nunca, ["LEY VACIA"])
        self.assertEqual(
            emp._miembros_instrumento(directorio),
            [("estado.json", b'{\n  "nombre": "LEY VACIA"\n}\n')],
        )

    def test_el_resumen_usa_el_mismo_valor(self):
        estado = {**ESTADO_VIEJO, "actualizado": "2026-06-30"}
        (self.ley / "estado.json").write_text(json.dumps(estado))

        [r] = self.empaqueta()[0]

        self.assertEqual(r.estado["actualizado"], "2026-05-22")

    def test_el_catalogo_del_release_devuelve_ese_actualizado(self):
        estado = {k: v for k, v in ESTADO_VIEJO.items() if k != "actualizado_scjn"}
        estado["actualizado"] = "2026-06-30"
        (self.ley / "estado.json").write_text(json.dumps(estado))
        self.empaqueta()
        cache = self.tmp / "cache"
        (cache / "scjn-leyes").mkdir(parents=True)
        for asset in self.destino.iterdir():
            (cache / "scjn-leyes" / asset.name).write_bytes(asset.read_bytes())

        catalogo = release.download_scjn_leyes_catalog(freshness=True, cache_dir=cache)

        [entrada] = catalogo
        self.assertEqual(entrada["actualizado"], "2026-05-22")


class TestIndiceGlobal(CorpusTemporal):
    def indice(self):
        return json.loads(gzip.decompress((self.destino / release.ASSET_INDICE_GLOBAL).read_bytes()))

    def test_no_tiene_seccion_codnota_ni_nada_derivado(self):
        self.empaqueta()

        indice = self.indice()
        self.assertEqual(set(indice), {"generado", "coleccion", "instrumentos"})
        self.assertNotIn("codNota", json.dumps(indice))

    def test_lista_la_ley_con_su_conteo_y_su_clasificacion(self):
        self.empaqueta()

        self.assertEqual(self.indice()["instrumentos"]["lfca"], {
            "nombre": "LEY Federal de Cine", "asset": "lfca.tgz", "snapshots": 2,
            "categoria_ordenamiento": "LEY", "ambito": "FEDERAL", "materia": "ADMINISTRATIVO",
        })

    def test_devuelve_el_tamano_del_asset(self):
        _, _, bytes_indice = self.empaqueta()

        self.assertEqual(bytes_indice, (self.destino / release.ASSET_INDICE_GLOBAL).stat().st_size)


class TestManifiesto(CorpusTemporal):
    def test_no_habla_de_enlaces_ni_de_notas_dof(self):
        resumenes, nunca, bytes_indice = self.empaqueta()

        texto = emp._formatea_manifiesto(resumenes, nunca, bytes_indice)

        for prohibido in ("enlazad", "codNota", "notas DOF", "confirmados", "indice inverso"):
            self.assertNotIn(prohibido, texto)
        self.assertIn("| `lfca` | 2 |", texto)

    def test_un_indice_ausente_no_agrega_su_seccion(self):
        resumenes, nunca, _ = self.empaqueta()

        self.assertNotIn(release.ASSET_INDICE_GLOBAL, emp._formatea_manifiesto(resumenes, nunca))


if __name__ == "__main__":
    unittest.main()
