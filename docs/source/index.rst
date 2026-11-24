:mod:`scjn`
============

.. image:: https://github.com/legistlan/scjn/actions/workflows/test.yml/badge.svg
        :target: https://github.com/legistlan/scjn/actions/workflows/test.yml

.. image:: https://badge.fury.io/py/scjn.svg
        :target: https://badge.fury.io/py/scjn

.. py:module:: scjn

Version |scjn_version|. ``scjn`` is one package of the Legistlan project
(the ``legistlan`` organization on GitHub), extracted from a
monorepo in November 2026 with its history; the
documentation of its siblings is where each one has put it: ``document2md`` at
`legistlan.github.io/document2md <https://legistlan.github.io/document2md/>`_.

.. note::

   This page is the developer reference. Using the package is documented on
   the user site, `legistlan.github.io/scjn <https://legistlan.github.io/scjn/>`_.

:py:mod:`scjn` is the client for the Suprema Corte de Justicia de la
Nación's SCOW JSON API (:py:mod:`scjn.api`, the backend of
`legislacion.scjn.gob.mx/consulta/buscador
<https://legislacion.scjn.gob.mx/consulta/buscador>`_) and the disk-first
reader for the five GitHub releases it feeds (:py:mod:`scjn.release`) — a
Mexican federal law's reform-dated snapshots, one tarball per law
(``scjn-leyes``); since issue #220, every federal *reglamento* the SCJN has,
one tarball per instrument (``scjn-reglamentos``); and, since issue #222,
every federal *lineamiento* the SCJN has, on the same id-keyed shape
(``scjn-lineamientos``); and, since issue #277, every international *treaty*
the SCJN serves, on that same shape (``scjn-tratados``); and, since issue #9,
every federal *estatuto* the SCJN classifies ``ESTATUTO``, on that same shape
(``scjn-estatutos``, published on 2026-11-17). It was extracted out of ``nota2md``'s own
modules (issue #206): Fase 1 (#207) moved the
transport, the catalogue's own algebra (:py:mod:`scjn.catalog`),
per-instrument crawl state (:py:mod:`scjn.state`) and the provenance header's
reader (:py:mod:`scjn.header`); Fase 3 (#209) moved the release's readers
here too, disk-first and with their own cache directory
(:py:mod:`scjn.cache`). This package depends on no other package of the
project, enforced by ``tests/test_boundary.py``'s own grep for
``nota2md``/``dofjson`` over the package and over ``scripts/``. It holds SCJN
data only: the releases carry no link between a snapshot and the DOF note
that published it (``codNota``), no DOF text and no DOF date — that DOF
linking lives outside this repository.

Two things worth stating explicitly before the API, because nothing in the
signatures below conveys them:

- **What** ``fuente: scjn`` **means.** The SCJN is not an official source of
  legal text — ``dof.gob.mx``/SIDOF remains that. Every
  file this package's crawl writes, and every snapshot the ``scjn-leyes``
  release ships, keeps that header intact, so whoever reads the result can
  tell where it came from — unchanged by this epic.
- **What "reform N" means.** It is the SCJN reform table's own chronological
  order — the snapshots of a law in the ``scjn-leyes`` release, one per
  reform, named by their ``fecha_publicacion``, oldest first. It is not an attempt to reproduce the Cámara de
  Diputados' historical numbering, which is gone with the Diputados data it
  counted (issue #184); the two count different things and are never
  compared.

The sections below are ordered the way a caller actually reaches this
corpus: :py:mod:`scjn.release` (the entry points, disk-only), :py:mod:`scjn.api`
(the transport underneath the corpus — the one documented exception to "every
public symbol has a verified example" on this page), :py:mod:`scjn.discovery`
(the shared discovery machinery behind the two id-keyed collections'
discovery scripts, issue #222's Fase 0), :py:mod:`scjn.catalog`
(the federal-law catalogue's own algebra), :py:mod:`scjn.state` (per-instrument
crawl state and completeness), :py:mod:`scjn.header` (reading a crawl's own
output back off disk), :py:mod:`scjn.cache` (the on-disk cache
:py:mod:`scjn.release` reads and the one-time migration out of
the package this one was extracted from), :py:mod:`scjn.cli` (the ``scjn`` console script). Every
class and function is documented, including private/internal helpers
(leading-underscore names) — useful when extending or debugging the package,
though they are not part of its public API and can change without notice.

Every example below that touches the ``scjn-leyes`` corpus picks one law by
slug — ``lfca`` (LEY Federal de Cine y el Audiovisual), the smallest law in
the release (one snapshot as of this writing) and one of the two the SCJN
does not index at all (its snapshot was built by hand from the DOF). The
whole release is ~380 MB; a corpus example that walked all of it would make
the doctest job unaffordable.

``scjn.release`` — the entry points
-------------------------------------

Every reader here is disk-only (issue #209): none of them make an HTTP
request, and a missing asset raises :py:exc:`~scjn.release.AssetNotCached` rather
than attempting one. Only :py:func:`~scjn.release.download_scjn_leyes_assets` (and,
through it, the ``scjn download`` CLI below) talks to the network — run it
once and every reader afterwards is offline.

>>> import scjn

:py:func:`~scjn.release.download_scjn_leyes_index` reads the release's index
— every law, with its name, its asset, its snapshot count and its
classification — a few hundred KB against the corpus' 380 MB. The published
index has no ``codNota`` section; an older copy (an old cache or a mirror)
that still has one is read the same way, because the reader drops it:

>>> indice = scjn.download_scjn_leyes_index()
>>> sorted(indice.keys())
['coleccion', 'generado', 'instrumentos']
>>> indice["coleccion"]
'leyes'
>>> indice["instrumentos"]["lfca"]["asset"]
'lfca.tgz'

:py:func:`~scjn.release.download_scjn_leyes_corpus` reads one law's own tarball
whole — every snapshot as ``archivo``, ``fecha_publicacion`` (read off the
file name) and ``markdown``, oldest first. The published tarball holds the
snapshots and ``estado.json`` only; an older copy that also holds an
``indice.json`` and a ``notas/`` folder is read the same way, because they are
not snapshots and are ignored:

>>> corpus = scjn.download_scjn_leyes_corpus("lfca")
>>> corpus["slug"]
'lfca'
>>> [(s["archivo"], s["fecha_publicacion"]) for s in corpus["snapshots"]]
[('22-05-2026.md', '22-05-2026')]

:py:func:`~scjn.release.markdown_de_snapshot` reads just one snapshot's text out of
that same tarball, without decoding the rest of it:

>>> scjn.markdown_de_snapshot("lfca", "22-05-2026.md").startswith("---\nfuente: scjn")
True

:py:func:`~scjn.release.iter_current_federal_laws` yields the *current* text of
every federal law the release publishes — one tarball opened, its newest
snapshot read, and its bytes dropped before the next law, so walking the
whole corpus never holds more than one law in memory at a time.
``slugs=["lfca"]`` bounds this example to the one law, the same way a real
caller would narrow it with ``--slug``:

>>> laws = list(scjn.iter_current_federal_laws(slugs=["lfca"]))
>>> len(laws)
1
>>> laws[0]["nombre"]
'LEY Federal de Cine y el Audiovisual'
>>> laws[0]["archivo"]
'22-05-2026.md'

Each law also carries the SCJN's own ``materia`` (its subject
classification), ``vigencia`` (whether it is still in force — seven values,
not a boolean) and ``resumen`` (a one-paragraph abstract), read off the same
index ``nombre`` comes from. They are properties of the *law*, not of the
snapshot being yielded, which is what makes this iterator usable as a
classified corpus — stratify by ``materia``, keep only ``VIGENTE`` — without
a second pass or a request to the SCJN (issue #215):

>>> sorted(laws[0])
['ambito', 'archivo', 'categoria_ordenamiento', 'estado', 'fecha_publicacion', 'markdown', 'materia', 'municipio', 'nombre', 'pais', 'resumen', 'slug', 'vigencia']
>>> laws[0]["materia"]
'ADMINISTRATIVO'

Since issue #8 every instrument also carries the rest of the SCJN's
classification, the five fields of :py:data:`~scjn.release.CAMPOS_CLASIFICACION`:
``categoria_ordenamiento`` (``LEY``, ``CODIGO``, ``REGLAMENTO``, ...),
``ambito`` (``FEDERAL``, ``ESTATAL``, ``TRATADOS INTERNACIONALES``), ``pais``
(the field that tells the instruments of ``scjn-tratados`` apart) and, for a
state-level instrument, ``estado`` and ``municipio``. The iterators always
return the five keys, ``None`` where the index has no value (an index older
than the fields gives ``None`` for every law, and the published one carries
them wherever the SCJN gives a value):

>>> from scjn.release import CAMPOS_CLASIFICACION, construye_indice_global
>>> sorted(CAMPOS_CLASIFICACION)
['ambito', 'categoria_ordenamiento', 'estado', 'municipio', 'pais']
>>> all(campo in laws[0] for campo in CAMPOS_CLASIFICACION)
True

An index built with the fields has them on each entry, and an instrument
lacking a value has no such key (absent, never ``null``):

>>> indice = construye_indice_global(
...     [{"slug": "lfca", "nombre": "LEY Federal de Cine y el Audiovisual",
...       "snapshots": 1, "categoria_ordenamiento": "LEY", "ambito": "FEDERAL",
...       "pais": "MÉXICO", "estado": None}],
...     generado="2026-11-13T00:00:00+00:00",
... )
>>> entrada = indice["instrumentos"]["lfca"]
>>> entrada["categoria_ordenamiento"], entrada["ambito"], entrada["pais"]
('LEY', 'FEDERAL', 'MÉXICO')
>>> "estado" in entrada, "municipio" in entrada
(False, False)

``lfca`` is also the illustration of "absent, never a placeholder": the SCJN
publishes no abstract for it, so ``resumen`` is ``None`` here and the key is
missing outright from the catalogue entry below, rather than carrying a null
that would read as "the SCJN says nothing" when it means "nobody asked".

:py:func:`~scjn.release.local_slugs` is the disk-first answer to "which laws does
this machine have" — no HTTP request, and what ``slugs=None`` above resolves
through:

>>> "lfca" in scjn.local_slugs()
True

:py:func:`~scjn.release.download_scjn_leyes_catalog` reads the federal-law catalogue
the release already publishes — the seed the Cámara de Diputados used to be
scraped for (issue #184). ``freshness=False`` skips every law's own tarball
(the default reads all ~315 of them for the ``actualizado`` freshness date: the
date of the newest reform the SCJN serves for the law, never a DOF date)
and answers off the index alone:

>>> catalogo = scjn.download_scjn_leyes_catalog(freshness=False)
>>> len(catalogo) > 100
True
>>> entrada = next(e for e in catalogo if e["abrev"] == "lfca")
>>> entrada["nombre"]
'LEY Federal de Cine y el Audiovisual'
>>> entrada["materia"], entrada["vigencia"]
('ADMINISTRATIVO', 'VIGENTE')
>>> "resumen" in entrada
False

The three metadata fields come from the index too, so they survive
``freshness=False``; with ``freshness=True`` a law's own ``estado.json``
wins over the index for them, since that is the record its next repack
publishes. They are written with one SCJN search per law, matched by
``idOrdenamiento`` so a wrong document can never be described as the right
one.

A law/asset not yet cached raises :py:exc:`~scjn.release.AssetNotCached`,
naming the exact ``scjn download`` command that populates it:

>>> try:
...     scjn.download_scjn_leyes_corpus("no-such-law")
... except scjn.AssetNotCached as exc:
...     print(exc)
'no-such-law.tgz' is not cached under .../scjn -- run `scjn download --slug no-such-law`

``scjn-reglamentos`` — the second collection (issue #220)
------------------------------------------------------------

Every federal *reglamento* the SCJN has, published as a sibling release
alongside ``scjn-leyes`` — same disk-first contract (every reader here is
offline too, and :py:exc:`~scjn.release.AssetNotCached` names the right ``scjn
download --collection regulations`` command), but a narrower corpus: no
``abrev`` (the SCJN reissues a reglamento as a brand-new ``idOrdenamiento``
rather than as a reform of the previous one, so a title-derived key would
collide — 137 of 1080 titles repeat). A tarball holds the snapshots and
``estado.json``, as a law's does.

>>> import scjn.release as release

:py:func:`~scjn.release.construye_indice_global_reglamentos` is the payload
builder for this release's own index, keyed by
``id_ordenamiento`` (:py:func:`scjn.catalog.reglamento_key`) rather than by a
slug:

>>> indice = release.construye_indice_global_reglamentos(
...     [{"id_ordenamiento": "104906", "nombre": "REGLAMENTO DE LA OFICIALIA "
...       "ELECTORAL DEL INSTITUTO NACIONAL ELECTORAL", "snapshots": 2,
...       "categoria_ordenamiento": "ACUERDO (S)", "vigencia": "VIGENTE"}],
...     generado="2026-09-09T00:00:00+00:00",
... )
>>> sorted(indice.keys())
['coleccion', 'generado', 'instrumentos']
>>> indice["coleccion"]
'reglamentos'
>>> indice["instrumentos"]["104906"]["categoria_ordenamiento"]
'ACUERDO (S)'

``categoria_ordenamiento`` (:py:data:`~scjn.release.CAMPO_CATEGORIA_ORDENAMIENTO`)
is what makes ``104906`` worth carrying at all: the SCJN itself classifies
the *instrument* ``ACUERDO (S)``, but a row of its own reform table is
classified ``REGLAMENTO`` — issue #220's own inclusion rule, load-bearing
for 6 of the corpus' 1087 instruments.

:py:func:`~scjn.catalog.instrumento_key` is the key itself — not a slug of a
title, unlike :py:func:`~scjn.catalog.slug_instrumento` — shared by every
id-keyed collection since issue #222's Fase 0 (``reglamento_key`` is kept as
a working alias of the exact same function, for a caller that has not moved
to the new name yet):

>>> from scjn.catalog import instrumento_key, reglamento_key
>>> instrumento_key({"id_ordenamiento": "104906", "nombre": "..."})
'104906'
>>> reglamento_key is instrumento_key
True

The corpus was published by hand on 2026-09-10 — 1087 instruments, 1082 with
snapshots, 72.2 MB of tarballs — and it outgrew a single GitHub release doing
it (issue #223): a release holds at most 1000 assets, and 1082 tarballs plus
``MANIFEST.md``/``SHA256SUMS.txt``/``indice-global.json.gz`` is 1085, so the
collection lives across two release tags today, ``scjn-reglamentos`` (997
tarballs, part 1) and ``scjn-reglamentos-2`` (the other 85). Every reader
below resolves the whole series transparently — a caller never names a part.

:py:func:`~scjn.release.download_scjn_reglamentos_assets` is the one function below
that talks to the network — every reader after it assumes it (or the ``scjn
download --collection regulations`` CLI built on it) already ran:

>>> resultados = release.download_scjn_reglamentos_assets(["104906"])
>>> sorted(ruta.name for ruta, _ in resultados)
['104906.tgz', 'indice-global.json.gz']

:py:func:`~scjn.release.download_scjn_reglamentos_index` reads the release's own
index, keyed by ``id_ordenamiento``:

>>> indice = release.download_scjn_reglamentos_index()
>>> indice["coleccion"]
'reglamentos'
>>> indice["instrumentos"]["104906"]["nombre"]
'REGLAMENTO DE LA OFICIALIA ELECTORAL DEL INSTITUTO NACIONAL ELECTORAL'
>>> indice["instrumentos"]["104906"]["categoria_ordenamiento"]
'ACUERDO (S)'

:py:func:`~scjn.release.download_scjn_reglamentos_corpus` reads one instrument back
— oldest snapshot first, each with its own provenance header:

>>> corpus = release.download_scjn_reglamentos_corpus("104906")
>>> [s["archivo"] for s in corpus["snapshots"]]
['21-01-2015.md', '25-01-2017.md']
>>> lineas = corpus["snapshots"][0]["markdown"].splitlines()
>>> lineas[0], lineas[1]
('---', 'fuente: scjn')

:py:func:`~scjn.release.local_reglamentos_ids` is the disk-first "what does this
machine already have", no network at all:

>>> "104906" in release.local_reglamentos_ids()
True

:py:func:`~scjn.release.iter_current_reglamentos` is
:py:func:`~scjn.release.iter_current_federal_laws`' id-keyed sibling (issue #227):
the *current* text of each instrument — one tarball opened, its newest
snapshot read, its bytes dropped before the next id — which is what a corpus
build walks. "Newest" comes from the snapshots' own ``DD-MM-YYYY.md`` file
names, parsed as dates rather than compared as text, as it does for a law; and
there is no ``abrev`` in what comes back, because this collection has none
(issue #220):

>>> [reglamento] = list(scjn.iter_current_reglamentos(["104906"]))
>>> sorted(reglamento)
['ambito', 'archivo', 'categoria_ordenamiento', 'estado', 'fecha_publicacion', 'id_ordenamiento', 'markdown', 'materia', 'municipio', 'nombre', 'pais', 'resumen', 'vigencia']
>>> reglamento["archivo"]
'25-01-2017.md'

``materia``/``vigencia``/``resumen`` come off the cached index at no extra
request, exactly as for a law — but they are **partial** here, unlike leyes:
``materia`` is present for 533 of 1,087 reglamentos and 112 of 163
lineamientos, ``resumen`` for 544 and 14 (issue #227's own measurement). A
missing one is the SCJN not having classified that instrument, not a bug to
chase.

An instrument the index lists with no consolidated text at all (``snapshots:
0`` — 5 reglamentos, 37 lineamientos, issue #222's decision 6) is **skipped**
by this iterator rather than raising :py:exc:`~scjn.release.SinTextoEnSCJN`: a corpus
walk should not have to catch an exception per instrument the SCJN never
published text for. Asking for one by name is where that exception still
belongs, and :py:func:`~scjn.release.download_scjn_reglamentos_corpus` still raises it.

``scjn-lineamientos`` — the third collection (issue #222)
------------------------------------------------------------

Every federal *lineamiento* the SCJN has — 163 instruments, 126 with text —
published as a sibling release alongside ``scjn-leyes``/``scjn-reglamentos``,
on the id-keyed collection path issue #222's Fase 0 refactored so a third
collection costs a descriptor entry and four wrapper functions rather than
another ~226-line copy of :py:mod:`scjn.release`. Same shape as
``scjn-reglamentos`` above: no ``abrev`` (3 of 159 titles repeat), no
``actualizado``.

:py:func:`~scjn.release.construye_indice_global_lineamientos` is the payload
builder for this release's own index — the exact sibling of
:py:func:`~scjn.release.construye_indice_global_reglamentos` above, sharing
the same private generic core (:py:func:`~scjn.release._indice_global_por_id`)
and the same decision 6 rule: an instrument with ``snapshots: 0`` gets no
``asset`` key at all, since there is nothing to download for it:

>>> indice = release.construye_indice_global_lineamientos(
...     [{"id_ordenamiento": "96090", "nombre": "MANUAL DE LINEAMIENTOS DE LA "
...       "COORDINACION DE RECURSOS HUMANOS Y ENLACE ADMINISTRATIVO",
...       "snapshots": 0, "categoria_ordenamiento": "MANUAL", "vigencia": "VIGENTE"}],
...     generado="2026-09-10T00:00:00+00:00",
... )
>>> indice["coleccion"]
'lineamientos'
>>> indice["instrumentos"]["96090"]["snapshots"]
0
>>> "asset" in indice["instrumentos"]["96090"]
False

:py:func:`~scjn.release.download_scjn_lineamientos_index`,
:py:func:`~scjn.release.download_scjn_lineamientos_corpus`,
:py:func:`~scjn.release.download_scjn_lineamientos_assets`,
:py:func:`~scjn.release.local_lineamientos_ids` and :py:exc:`~scjn.release.SinTextoEnSCJN`
are the exact wrappers :py:func:`~scjn.release.download_scjn_reglamentos_index` and
its siblings are (decision 7: every published name stays per-collection,
symmetric across both) — sharing the same generic core
(:py:func:`~scjn.release._index_de_release`,
:py:func:`~scjn.release._corpus_de_release`,
:py:func:`~scjn.release._local_ids_de_release`,
:py:func:`~scjn.release._download_assets_de_release`) and the exact same
raise-order contract :py:exc:`~scjn.release.AssetNotCached`/:py:exc:`~scjn.release.SinTextoEnSCJN`
document on those functions (decision 10): a cold cache raises
:py:exc:`~scjn.release.AssetNotCached` for the index first, and only once the index
says an id has no asset does :py:func:`~scjn.release.download_scjn_lineamientos_corpus`
raise :py:exc:`~scjn.release.SinTextoEnSCJN` instead of reaching for a tarball that
does not exist.

The release is published (a human ran the publish plan, ``PUBLICAR.md``, as
issue #115, Hallazgo C requires: publishing is never automated). Its wrappers,
:py:func:`~scjn.release.iter_current_lineamientos` (issue #227) included, are the
exact siblings of the ``scjn-reglamentos`` ones documented with live examples
above; this page keeps the live walk for ``scjn-reglamentos`` and for
``scjn-estatutos`` below, and ``tests/test_release.py`` verifies the
lineamientos wrappers (``TestScjnLineamientos``, ``TestIterCurrentPorId``)
against a synthetic on-disk release.

``scjn-tratados`` — the fourth collection (issue #277)
------------------------------------------------------------

Every international treaty the SCJN serves — ~1,456 instruments — published
as a sibling release on the same id-keyed path: a descriptor entry
(:py:data:`~scjn.cache.TRATADOS`), four wrapper functions and a discovery
script, not a new copy of :py:mod:`scjn.release`. Same shape as
``scjn-reglamentos``: no ``abrev``, no ``actualizado``,
``id_ordenamiento`` as the only key, an
instrument with no consolidated text indexed with ``snapshots: 0`` and no
asset.

What differs is **how membership is decided**. The SCJN does not classify a
treaty as a federal instrument: it carries ``ambito == "TRATADOS
INTERNACIONALES"``, so this collection is every instrument of that *ámbito*,
whatever its category (CONVENIO, ACUERDO (S), CONVENCION, TRATADO, ... — 23
measured, every one a genuine international instrument), not a ``categoria``
as for reglamentos and lineamientos. That is a fact of this collection's
discovery (``discover_federal_tratados.py``, see below), carried by no field
of :py:class:`~scjn.cache.Coleccion`. It is also a numbered series of release
tags (``scjn-tratados``, ``scjn-tratados-2``, ...), since the corpus is over
GitHub's 1000-asset cap, resolved by the downloader itself (issue #223).

:py:func:`~scjn.release.construye_indice_global_tratados` is the payload
builder for this release's own index, the exact sibling of
:py:func:`~scjn.release.construye_indice_global_lineamientos`:

>>> indice = release.construye_indice_global_tratados(
...     [{"id_ordenamiento": "1012", "nombre": "CONVENIO SOBRE AVIACION CIVIL "
...       "INTERNACIONAL", "snapshots": 1, "categoria_ordenamiento": "CONVENIO",
...       "vigencia": "VIGENTE"},
...      {"id_ordenamiento": "2024", "nombre": "ACUERDO SIN TEXTO", "snapshots": 0}],
...     generado="2026-10-08T00:00:00+00:00",
... )
>>> indice["coleccion"]
'tratados'
>>> indice["instrumentos"]["1012"]["asset"]
'1012.tgz'
>>> "asset" in indice["instrumentos"]["2024"]
False

:py:func:`~scjn.release.download_scjn_tratados_index`,
:py:func:`~scjn.release.download_scjn_tratados_corpus`,
:py:func:`~scjn.release.download_scjn_tratados_assets`,
:py:func:`~scjn.release.local_tratados_ids` and :py:func:`~scjn.release.iter_current_tratados`
are the exact wrappers their reglamentos siblings are, over the same generic
core and the same :py:exc:`~scjn.release.AssetNotCached`/:py:exc:`~scjn.release.SinTextoEnSCJN`
raise order.

The release is published (two tags, ``scjn-tratados`` and ``scjn-tratados-2``),
and, like ``scjn-lineamientos`` above, its wrappers are verified by
``tests/test_release.py``'s ``TestScjnTratados`` class against a synthetic
on-disk release rather than by a live walk.

``scjn-estatutos`` — the fifth collection (issue #9)
------------------------------------------------------------

Every federal instrument the SCJN classifies ``ESTATUTO`` (organic statutes of
federal bodies, agencies and universities; 379 at the audit of 13 November 2026),
on the same id-keyed path as ``scjn-lineamientos`` above: no ``abrev``, no
``actualizado``. Membership is by category plus the reform-row
rescue (``categoriaOrdenamiento == "ESTATUTO"`` or any reform row with
``categoriaReforma == "ESTATUTO"``), decided by
``scripts/discover_federal_estatutos.py``, which lists candidates and writes
nothing. The release was published on 2026-11-17: 379 instruments, 377 with
text, 1,139 snapshots. Two are indexed with no or incomplete snapshots because
the SCJN serves a reform with a missing block that the completeness guard
refuses (``178398`` has none, ``111330`` has 4 of its 5 reforms).

The examples below read ``111330`` (the *Estatuto del Servicio Profesional
Electoral Nacional y del Personal de la Rama Administrativa*), a small
instrument with text, which the doctest job puts in the cache the way it does
``lfca`` and ``104906`` (``scjn download --collection bylaws --id 111330``).

:py:func:`~scjn.release.construye_indice_global_estatutos` needs no cache, so it
has a live example; its entries carry the classification fields
(:py:data:`~scjn.release.CAMPOS_CLASIFICACION`) like every id-keyed index:

>>> indice = release.construye_indice_global_estatutos(
...     [{"id_ordenamiento": "5001", "nombre": "ESTATUTO ORGANICO DE EJEMPLO",
...       "snapshots": 1, "categoria_ordenamiento": "ESTATUTO", "ambito": "FEDERAL",
...       "pais": "MÉXICO", "vigencia": "VIGENTE"},
...      {"id_ordenamiento": "5002", "nombre": "ESTATUTO SIN TEXTO", "snapshots": 0}],
...     generado="2026-11-13T00:00:00+00:00",
... )
>>> indice["coleccion"]
'estatutos'
>>> indice["instrumentos"]["5001"]["categoria_ordenamiento"], indice["instrumentos"]["5001"]["pais"]
('ESTATUTO', 'MÉXICO')
>>> "asset" in indice["instrumentos"]["5002"]
False

:py:func:`~scjn.release.download_scjn_estatutos_assets` is the only one of these
readers that talks to the network (and, through it, ``scjn download
--collection bylaws``); it resolves the release's series and puts the index
and the instrument's tarball in the cache:

>>> resultados = release.download_scjn_estatutos_assets(["111330"])
>>> sorted(ruta.name for ruta, _ in resultados)
['111330.tgz', 'indice-global.json.gz']

:py:func:`~scjn.release.download_scjn_estatutos_index` reads the index, keyed by
``id_ordenamiento``, with the classification of each instrument:

>>> indice = release.download_scjn_estatutos_index()
>>> indice["coleccion"]
'estatutos'
>>> entrada = indice["instrumentos"]["111330"]
>>> entrada["asset"], entrada["snapshots"]
('111330.tgz', 4)
>>> entrada["categoria_ordenamiento"], entrada["ambito"], entrada["pais"]
('ESTATUTO', 'FEDERAL', 'MÉXICO')

:py:func:`~scjn.release.download_scjn_estatutos_corpus` reads the instrument back,
oldest snapshot first, each with its provenance header:

>>> corpus = release.download_scjn_estatutos_corpus("111330")
>>> [s["archivo"] for s in corpus["snapshots"]]
['09-06-2016.md', '10-11-2016.md', '01-09-2017.md', '23-07-2020.md']
>>> corpus["snapshots"][0]["markdown"].splitlines()[:2]
['---', 'fuente: scjn']

:py:func:`~scjn.release.local_estatutos_ids` is the disk-first "what does this
machine have", with no request:

>>> "111330" in release.local_estatutos_ids()
True

:py:func:`~scjn.release.iter_current_estatutos` yields the newest snapshot of each
instrument, with the classification keys always present (``None`` for a
value the index lacks, as ``estado`` and ``municipio`` here):

>>> [estatuto] = list(scjn.iter_current_estatutos(["111330"]))
>>> estatuto["archivo"], estatuto["vigencia"]
('23-07-2020.md', 'ABROGADO (A)')
>>> estatuto["estado"], estatuto["municipio"]
(None, None)

An instrument that is not cached raises :py:exc:`~scjn.release.AssetNotCached`
(an id the index says has no text raises :py:exc:`~scjn.release.SinTextoEnSCJN`);
``tests/test_release.py`` (``TestIdKeyedWrappers``, which runs once per
collection of :py:data:`~scjn.cache.COLECCIONES_POR_ID`, ``estatutos``
included) verifies both against a synthetic on-disk release.

.. automodule:: scjn.release
   :members:
   :private-members:
   :undoc-members:

``scjn.api`` — the SCOW transport
-------------------------------------

**The one documented exception to "every public symbol has a verified
example" on this page — the network endpoints only.** :py:mod:`scjn.api` is
an unauthenticated client for three JSON endpoints (``BusquedaFrase``,
``Reforma``, ``Articulos``) that replaced this project's legacy WebForms
crawler (issue #172, retired in #179). A doctest per endpoint would put the
docs gate at the mercy of the SCJN's own uptime, and crawling is not a
caller-facing API the way the readers above are — a caller never
instantiates :py:class:`~scjn.api.ScjnApi` directly, only the
``scjn download`` CLI (or ``scripts/fetch_scjn_legislacion.py`` here) does.
This behaviour is instead
verified for real, against the live service, by
``tests/test_api_red.py`` — not silently skipped, exactly the
mechanism `document2md <https://legistlan.github.io/document2md/>`__'s OCR paths
already use for ``mineru``.

The Markdown writer below it (:py:func:`~scjn.markdown.articulos_a_markdown` and
what it calls) touches no network, so it keeps a verified example like every
other symbol on this page. A blank-line-separated block of an article's
``contenido`` that carries a tab is the one shape it treats differently
(issue #253) — the SCJN's only column signal in otherwise plain text — and
comes back as one ``"| cell | cell |"`` paragraph per recovered row instead
of one paragraph per wrapped source line:

>>> from scjn.api import Articulo, articulos_a_markdown
>>> contenido = (
...     "ARTICULO 1.- Cuotas:\r\n\r\n"
...     "a).- Concepto\r\n"
...     "envuelto en dos líneas\t\t$1.00\t\t$1"
... )
>>> print(articulos_a_markdown([Articulo(1, 1, "ARTÍCULO 1", contenido)]))
**ARTICULO 1.-** Cuotas:
<BLANKLINE>
| a).- Concepto envuelto en dos líneas | $1.00 | $1 |
<BLANKLINE>

The writer's own module, :py:mod:`scjn.markdown` (issue #303), is documented
below; every name it holds is still importable from :py:mod:`scjn.api`. What
stays here is the completeness guard. :py:func:`~scjn.api.completeness_defects`
is the pure predicate :py:meth:`~scjn.api.ScjnApi.articulos_of_reforma` and
``scripts/verify_scjn_outline.py --guard`` share: an empty list is a complete
answer, a gap in ``orden`` and a count below ``tamanio`` are the two defects, and
``total=0`` means the declared ``tamanio`` is unknown (a kept raw answer does not
record it):

>>> from scjn.api import Articulo, completeness_defects
>>> completeness_defects([Articulo(1, 1, "ARTÍCULO 1", "x"), Articulo(3, 3, "ARTÍCULO 3", "y")], 3)
['missing orden [2]', '2 rows is fewer than tamanio 3']
>>> completeness_defects([Articulo(1, 1, "ARTÍCULO 1", "x"), Articulo(2, 2, "ARTÍCULO 2", "y")], 2)
[]

.. automodule:: scjn.api
   :members:
   :private-members:
   :undoc-members:

``scjn.markdown`` — the plain-text-to-Markdown writer (issue #303)
---------------------------------------------------------------------

Split out of :py:mod:`scjn.api` with no behaviour change. It turns the blocks an
``Articulos`` answer holds into the light Markdown a snapshot stores, one marker
line (:py:mod:`scjn.outline`) before each block that yields text when
``outline=True``. A block whose whole text is an editorial ``N. DE E.`` aside
yields no text and so no marker:

>>> from scjn.markdown import articulos_a_markdown
>>> blocks = [Articulo(0, 1, "ENCABEZADO", "LEY DE EJEMPLO"), Articulo(0, 2, "NOTA", "[N. DE E. VÉASE ANEXO]")]
>>> print(articulos_a_markdown(blocks, outline=True))
<!-- scjn:block orden=1 numero=0 kind=header label="ENCABEZADO" -->
<BLANKLINE>
**LEY DE EJEMPLO**
<BLANKLINE>
>>> articulos_a_markdown(blocks)
'**LEY DE EJEMPLO**\n'

.. automodule:: scjn.markdown
   :members:
   :private-members:
   :undoc-members:

``scjn.outline`` — the outline the SCJN's API states
----------------------------------------------------

``GET /api/SCOW/Articulos`` returns an instrument as ordered *blocks*, each with
an ``orden``, a ``numero`` and a ``referencia`` that names what the block is
(``ÍNDICE``, ``TÍTULO PRIMERO``, ``ARTÍCULO 6 TER``, ``ANEXO 1``,
``D.O.F. 10 DE NOVIEMBRE DE 2023``). The writer keeps it: it puts
one HTML-comment marker line before each block, so a reader of the Markdown
(``md2akn``) knows where the index, the containers, a reform decree and each
article are instead of guessing. ``classify`` derives the ``kind`` from the
label, ``marker_line``/``parse_marker`` write and read the line, and
``strip_markers`` gives the text back as it always was:

>>> from scjn.outline import classify, marker_line, parse_marker, strip_markers
>>> classify("PARTE 3")
{'kind': 'container', 'type': 'part', 'num': '3'}
>>> line = marker_line(6, 0, "ÍNDICE")
>>> line
'<!-- scjn:block orden=6 numero=0 kind=toc label="ÍNDICE" -->'
>>> parse_marker(line)["kind"]
'toc'
>>> strip_markers(line + "\n\nTexto.\n")
'Texto.\n'

.. automodule:: scjn.outline
   :members:
   :private-members:
   :undoc-members:

``scjn.discovery`` — shared id-keyed collection discovery (issue #222)
---------------------------------------------------------------------------

The three passes behind ``discover_federal_reglamentos.py`` (issue #220) and
``discover_federal_lineamientos.py`` (issue #222), extracted into library
code parameterised by a target SCJN category and a phrase list, so neither
script duplicates them. Every function here takes an object exposing only
``search_ordenamiento``/``reformas_of_ordenamiento`` (an
:py:class:`~scjn.api.ScjnApi`, or the small stub below) — nothing makes a
network request directly, which is what makes this module unit-testable
without the SCJN:

>>> from scjn.api import Ordenamiento, Reforma
>>> from scjn.discovery import (
...     candidates_outside_category, coverage_audit, discover,
...     discover_by_category, pagina_categoria, rescue_by_reform_category,
... )
>>> class StubApi:
...     """Answers one page of hand-picked hits per (frase, categoria), and
...     a fixed reform table per id -- enough to exercise every pass below
...     without a single HTTP request."""
...     def __init__(self):
...         self.hits = {
...             ("lineamientos", "LINEAMIENTOS"): [
...                 Ordenamiento(idOrdenamiento="1", ordenamiento="LINEAMIENTOS DE EJEMPLO",
...                              categoriaOrdenamiento="LINEAMIENTOS"),
...             ],
...             ("lineamientos", ""): [
...                 Ordenamiento(idOrdenamiento="1", ordenamiento="LINEAMIENTOS DE EJEMPLO",
...                              categoriaOrdenamiento="LINEAMIENTOS"),
...                 Ordenamiento(idOrdenamiento="2", ordenamiento="MANUAL DE LINEAMIENTOS",
...                              categoriaOrdenamiento="MANUAL"),
...             ],
...             ("manual", "MANUAL"): [
...                 Ordenamiento(idOrdenamiento="2", ordenamiento="MANUAL DE LINEAMIENTOS",
...                              categoriaOrdenamiento="MANUAL"),
...             ],
...         }
...         self.reformas = {
...             "1": [Reforma(reformaId=1, fecha_publicacion="01-01-2020", categoria="LINEAMIENTOS")],
...             "2": [Reforma(reformaId=2, fecha_publicacion="01-01-2019", categoria="LINEAMIENTOS",
...                            tieneArticulos=False)],
...         }
...     def search_ordenamiento(self, frase, *, tamanio_pagina, categoria, ambito, pagina):
...         return self.hits.get((frase, categoria), []) if pagina == 1 else []
...     def reformas_of_ordenamiento(self, id_ordenamiento):
...         return self.reformas.get(str(id_ordenamiento), [])
>>> api = StubApi()

:py:func:`~scjn.discovery.pagina_categoria` pages one ``(frase, categoria)``
to the end:

>>> [hit.idOrdenamiento for hit in pagina_categoria(api, "lineamientos", "LINEAMIENTOS")]
['1']

:py:func:`~scjn.discovery.discover_by_category` unions a phrase list over
one target category:

>>> por_categoria = discover_by_category(api, "LINEAMIENTOS", ("lineamientos",))
>>> list(por_categoria)
['1']

:py:func:`~scjn.discovery.candidates_outside_category` finds every other
federal hit of one rescue phrase, minus what is already classified:

>>> otros = candidates_outside_category(api, "lineamientos", por_categoria)
>>> list(otros)
['2']

:py:func:`~scjn.discovery.rescue_by_reform_category` applies the
reform-table rule to those candidates — id ``"2"``'s own reform row is
classified ``LINEAMIENTOS`` even though the SCJN classifies the *instrument*
itself ``MANUAL``:

>>> rescatados = rescue_by_reform_category(api, otros, "LINEAMIENTOS")
>>> list(rescatados)
['2']

:py:func:`~scjn.discovery.coverage_audit` is the opt-in, one-time,
exhaustive sweep (issue #222's decision 8) — it finds the same id ``"2"``
by a different route (the ``MANUAL`` category, not the ``"lineamientos"``
phrase), and would cache every reform table it fetches under a real
``cache_dir``; ``cache_dir=None`` here writes nothing to disk:

>>> extra = coverage_audit(api, {"1"}, "LINEAMIENTOS", (("manual", "MANUAL"),), cache_dir=None)
>>> list(extra)
['2']

:py:func:`~scjn.discovery.discover` is the whole pipeline a discovery script
wraps — union, rescue, and (opt-in) the coverage audit, returning a
reviewable list sorted by name:

>>> candidatos = discover(
...     StubApi(), categoria="LINEAMIENTOS", frases_union=("lineamientos",),
...     frase_rescate="lineamientos", auditoria_cobertura=True,
...     frases_auditoria=(("manual", "MANUAL"),), log=lambda *_a, **_k: None,
... )
>>> [(c["id_ordenamiento"], c["nombre"], c["reformas_con_texto"]) for c in candidatos]
[('1', 'LINEAMIENTOS DE EJEMPLO', 1), ('2', 'MANUAL DE LINEAMIENTOS', 0)]

**By ámbito** (issue #277). ``discover`` and ``discover_by_category`` take an
``ambito`` keyword (``"FEDERAL"`` by default, so every call above is
unchanged). ``categoria=""`` is the by-ámbito mode ``scjn-tratados`` uses:
the whole ámbito is paged, any category, and **neither the reform-category
rescue nor the coverage audit runs** — both are predicates on a reform row's
category, a reform row carries no ámbito, so neither can express
"international". Each candidate carries its ``ambito``:

>>> class AmbitoStub:
...     """Keys on ambito too: the treaties live under their own ambito."""
...     def search_ordenamiento(self, frase, *, tamanio_pagina, categoria, ambito, pagina):
...         if pagina > 1 or (frase, categoria, ambito) != ("tratado", "", "TRATADOS INTERNACIONALES"):
...             return []
...         return [
...             Ordenamiento(idOrdenamiento="1012", ordenamiento="CONVENIO DE EJEMPLO",
...                          categoriaOrdenamiento="CONVENIO", ambito=ambito),
...             Ordenamiento(idOrdenamiento="2024", ordenamiento="ACUERDO DE EJEMPLO",
...                          categoriaOrdenamiento="ACUERDO (S)", ambito=ambito),
...         ]
...     def reformas_of_ordenamiento(self, id_ordenamiento):
...         return [Reforma(reformaId=1, fecha_publicacion="01-01-1951")]
>>> tratados = discover(
...     AmbitoStub(), categoria="", ambito="TRATADOS INTERNACIONALES",
...     frases_union=("tratado",), log=lambda *_a, **_k: None,
... )
>>> [(c["id_ordenamiento"], c["categoria_ordenamiento"], c["ambito"]) for c in tratados]
[('2024', 'ACUERDO (S)', 'TRATADOS INTERNACIONALES'), ('1012', 'CONVENIO', 'TRATADOS INTERNACIONALES')]

:py:func:`~scjn.discovery.report_outside_ambito` lists — for a human to
look at, never to include — the instruments *outside* the ámbito whose own
category is a treaty word (a ``TRATADO`` the SCJN classifies ``ESTATAL``,
say):

>>> from scjn.discovery import report_outside_ambito
>>> class FueraStub:
...     def search_ordenamiento(self, frase, *, tamanio_pagina, categoria, ambito, pagina):
...         if pagina > 1:
...             return []
...         return [
...             Ordenamiento(idOrdenamiento="7", ordenamiento="TRATADO ESTATAL",
...                          categoriaOrdenamiento="TRATADO", ambito="ESTATAL"),
...             Ordenamiento(idOrdenamiento="1012", ordenamiento="CONVENIO DE EJEMPLO",
...                          categoriaOrdenamiento="CONVENIO", ambito="TRATADOS INTERNACIONALES"),
...         ]
>>> [h.idOrdenamiento for h in report_outside_ambito(
...     FueraStub(), "TRATADOS INTERNACIONALES", ("TRATADO",), ("tratado",))]
['7']

.. automodule:: scjn.discovery
   :members:
   :private-members:
   :undoc-members:

``scjn.catalog`` — the federal-law catalogue's own algebra
---------------------------------------------------------------

Slugs, the ``nombre_scjn`` override, and minting a brand-new law's ``abrev``
— what used to also merge a freshly extracted ``catalogo.json`` against the
one on disk, before issue #210 made a law's own ``estado.json`` the single
per-law record with nothing left to reconcile against a second copy.

.. automodule:: scjn.catalog
   :members:
   :private-members:
   :undoc-members:

``scjn.state`` — per-instrument crawl state and completeness
-------------------------------------------------------------------

``estado.json``, one per law, and whether that law needs crawling again —
either by date (:py:func:`~scjn.state.motivo_pendiente`'s offline fallback)
or, since issue #211, by comparing the SCJN's own reform table row by row
against what is on disk (:py:func:`~scjn.state.reformas_faltantes`), the
only way to see a gap in the middle of an otherwise current-looking law
(``lfd`` had 92 snapshots against 98 reforms — issue #178).

.. automodule:: scjn.state
   :members:
   :private-members:
   :undoc-members:

``scjn.header`` — reading a crawl's own output back off disk
-------------------------------------------------------------------

The provenance header :py:func:`scjn.api.cabecera` writes at the top of
every snapshot, read back without re-fetching it — what lets a later pass
work over a crawl's output independently of the crawl itself.
:py:func:`~scjn.header.parse_header` is that parser over text rather than
over a file, for a caller holding a snapshot read straight out of a
``<slug>.tgz``:

>>> from scjn.header import parse_header
>>> cabecera = parse_header(scjn.markdown_de_snapshot("lfca", "22-05-2026.md"))
>>> cabecera["ordenamiento"]
'LEY FEDERAL DE CINE Y EL AUDIOVISUAL'
>>> cabecera["id_ordenamiento"]
'188805'

:py:func:`~scjn.header.lee_cabecera` is the same thing plus the read, for a
snapshot already on disk.

.. automodule:: scjn.header
   :members:
   :private-members:
   :undoc-members:

``scjn.cache`` — the on-disk cache and its one-time migration
--------------------------------------------------------------------

Its own directory, not a downstream package's (issue #209) — a
``platformdirs``-backed :py:data:`~scjn.cache.CACHE_DIR`, overridable with
``$SCJN_CACHE_DIR``:

>>> import scjn.cache as cache
>>> cache.CACHE_DIR.name
'scjn'
>>> (cache.CACHE_DIR / "scjn-leyes" / "lfca.tgz").exists()
True

:py:func:`~scjn.cache.migrate_legacy_assets` is the one-time consequence of
this package's cache not existing before issue #209: this package has no
notion of where a downstream package used to cache this release (its
dependency direction forbids that), so a caller that does know — a
downstream package's own ``download`` verb — hands that knowledge off,
moving release assets over with ``os.replace`` rather than downloading
~380 MB a machine already has:

>>> cache.migrate_legacy_assets(cache.CACHE_DIR, cache.CACHE_DIR / "does-not-exist")
0

:py:class:`~scjn.cache.Coleccion` (issue #222's Fase 0) describes an
id-keyed collection's own release-tag series and cache subdirectory;
:py:data:`~scjn.cache.COLECCIONES_POR_ID` maps a collection's name to its
descriptor, for :py:mod:`scjn.cli` (``--collection``) and the scripts (``--coleccion``) to dispatch
through instead of a per-collection literal branch:

>>> sorted(cache.COLECCIONES_POR_ID)
['estatutos', 'lineamientos', 'reglamentos', 'tratados']
>>> cache.ESTATUTOS.tag_base
'scjn-estatutos'

>>> cache.COLECCIONES_POR_ID["lineamientos"].tag_base
'scjn-lineamientos'
>>> cache.REGLAMENTOS.subdirectorio
'scjn-reglamentos'
>>> cache.TRATADOS.tag_base
'scjn-tratados'

:py:data:`~scjn.cache.COLLECTION_CLI_NAMES` maps every collection's internal
name to the English name it has at the command line; ``scjn download --all``
downloads every entry of it:

>>> cache.COLLECTION_CLI_NAMES
{'leyes': 'laws', 'reglamentos': 'regulations', 'lineamientos': 'guidelines', 'tratados': 'treaties', 'estatutos': 'bylaws'}

.. automodule:: scjn.cache
   :members:
   :private-members:
   :undoc-members:

``scjn.cli`` — command-line entry point
------------------------------------------

One verb: putting a release on disk. A downstream package's own
``download`` subcommands delegate to this same downloader rather than
reimplementing it:

.. code-block:: console

   $ scjn download --slug lfca
   [1/2] indice-global.json.gz: already cached
   [2/2] lfca.tgz: already cached
   scjn-leyes: 2 assets in /home/user/.cache/scjn/scjn-leyes (0 downloaded, 2 already cached)

``--collection {laws,regulations,guidelines,treaties,bylaws}`` (default ``laws``)
picks which release: ``scjn-leyes``, ``scjn-reglamentos``, ``scjn-lineamientos``,
``scjn-tratados`` or ``scjn-estatutos``. The values are the English names of
:py:data:`~scjn.cache.COLLECTION_CLI_NAMES`; the Spanish names are those of the
releases and of the Python API. ``--id`` replaces ``--slug`` for any id-keyed
collection, since all are keyed by ``id_ordenamiento`` rather than by a slug:

.. code-block:: console

   $ scjn download --collection regulations --id 104906
   [1/2] indice-global.json.gz: downloaded
   [2/2] 104906.tgz: downloaded
   scjn-reglamentos: 2 assets in /home/user/.cache/scjn/scjn-reglamentos (2 downloaded, 0 already cached) (2 parts)

   $ scjn download --collection bylaws --id 111330
   [1/2] indice-global.json.gz: downloaded
   [2/2] 111330.tgz: downloaded
   scjn-estatutos: 2 assets in /home/user/.cache/scjn/scjn-estatutos (2 downloaded, 0 already cached)

The id-keyed collections are dispatched through
:py:data:`~scjn.cache.COLECCIONES_POR_ID` rather than a hand-written branch
for each one: adding a further one costs a new dict entry, not a new literal
branch. ``laws`` stays its own separate branch: it takes ``--slug``, not
``--id``, and has no :py:class:`~scjn.cache.Coleccion` descriptor at all.

``(2 parts)`` (issue #223) appears whenever a download session actually
asked GitHub for this collection's series of release tags and found more
than one; this collection is ``scjn-reglamentos``/``scjn-reglamentos-2``
today. A run that finds everything already cached never asks, so it never
prints a part count at all, same as the ``scjn-leyes`` example above.

``--all`` downloads every collection, whole, one summary line per collection,
and cannot be combined with ``--collection``, ``--slug`` or ``--id``. It is
not run here: it fetches several thousand tarballs.

.. code-block:: console

   $ scjn download --all

``--version`` prints the installed version:

.. code-block:: console

   $ scjn --version
   scjn 0.7.0

.. automodule:: scjn.cli
   :members:
   :private-members:
   :undoc-members:
