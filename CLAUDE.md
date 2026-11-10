# CLAUDE.md

This file guides Claude Code (claude.ai/code) in this repository. It says what the tree **is**, in
the present tense; a decision that outlives an issue is recorded here as a bullet.

## What this is

`scjn` is the client for the Suprema Corte de Justicia de la Nación's SCOW JSON API (`scjn.api`,
the backend of `legislacion.scjn.gob.mx/consulta`), the writer of the Markdown snapshots of an
instrument's reforms (`scjn.markdown`, `scjn.outline`) and the disk-first reader of the four SCJN
releases (`scjn.release`): `scjn-leyes` (315 federal laws, reform-dated snapshots, keyed by
`abrev`) and the id-keyed `scjn-reglamentos`, `scjn-lineamientos` and `scjn-tratados` (keyed by
`id_ordenamiento`). The SCJN is not an official source of legal text; the *Diario Oficial de la
Federación* is, and `fuente: scjn` in a provenance header means exactly that.

It is one package of the Legistlan project (the `legistlan` organization): `nota2md` requires
`scjn>=0.5.1` and re-exports its readers; `scjn` itself imports no sibling, and
`tests/test_boundary.py` greps the package for `nota2md`/`dofjson` to keep it so. It was
`packages/scjn` of the `INGEOTEC/LegalIA` monorepo until 9 November 2026 (monorepo commit
`f403872b1`); this repository is that history filtered to the package, its crawl scripts and its
documentation page, so `git log` and `git blame` reach the first commit. A `#N` in a commit
message, a comment or a docstring is an issue of the monorepo, where those issues live.

## The package

- **Read order**, the way a caller reaches the corpus: `scjn.release` (the entry points,
  disk-only), `scjn.api` (the transport and the completeness guard), `scjn.markdown` and
  `scjn.outline` (the writer and its markers), `scjn.discovery` (the shared paging and rescue
  rules of the id-keyed collections), `scjn.catalog` (slugs, `abrev`, `instrumento_key`),
  `scjn.state` (per-instrument crawl state), `scjn.header` (the provenance header), `scjn.cache`,
  `scjn.cli` (`scjn download`).
- **Entry points** for `scjn-leyes`: `download_scjn_leyes_index`/`_corpus`/`_catalog`,
  `markdown_de_snapshot`, `iter_current_federal_laws`, `local_slugs`,
  `download_scjn_leyes_assets`, `AssetNotCached`; the three id-keyed siblings have the same names
  with `reglamentos`/`lineamientos`/`tratados` (`iter_current_*` included) and raise
  `SinTextoEnSCJN` for an instrument with no text. Every reader reads only the cache and raises
  `AssetNotCached` rather than downloading; only `download_*_assets` and `scjn download` talk to
  the network.
- Only `leyes` has an `abrev`, an `actualizado` (`actualizado_scjn`, `actualizado_dof`), an
  `indice.json` and DOF linking; the id-keyed collections have none. An `abrev` is the release's
  slug and asset name, never re-derived. "Reform N" of a law is the SCJN reform table's
  chronological order. `codNota` linking lives one layer up, in `nota2md`: a `codNota` is a DOF
  concept.
- **No source other than the SCJN**: the Cámara de Diputados (LeyesBiblio) is not a source.

## The outline contract

The SCOW API serves a reform as ordered *blocks* (`orden`, `numero`, `referencia`, `contenido`,
`tamanio`). The writer puts one marker line before each block that yields text:

    <!-- scjn:block orden=N numero=N kind=<kind> [type=] [num=] label="..." -->

`kind` is one of header, recitals, preamble, toc, transitorios, decree, container, article,
provision, other. The marker is an HTML comment on purpose: no character of the text changes,
`strip_markers` returns the text byte for byte, and `markdown_de_snapshot(..., outline=False)` is
what `nota2md` reads. Every block that yields text has exactly one marker; a block that yields none
(an editorial `N. DE E.` aside) leaves its `orden` as a gap the raw answer explains; a marker is
metadata, never embedded. The reader of the markers is `md2akn`, which imports nothing from here:
the two are tied by the vocabulary fixture `scripts/verify_scjn_outline.py --write-vocabulary`
writes into `md2akn`'s own repository (`tests/fixtures_units/marker_vocabulary.json`).

- **Raw answers are kept.** Every reform's answer is stored gzipped under
  `scripts/scjn/raw-api/<c>/<key>/` (local scratch), so the writer can change without a re-crawl
  (`scripts/rewrite_scjn_from_raw.py`).
- **The completeness guard** (`scjn.api.ScjnApi.articulos_of_reforma`): an answer is complete when
  its `orden` values are exactly `1..max` and it carries at least `tamanio` rows. An incomplete
  answer is requested again and then refused with `ScjnApiIncompleteError`, so the reform counts
  as failed and no file is written. A verbatim repeated row is dropped, first kept; two *different*
  blocks sharing an `orden` both stay. An instrument is swapped in whole or not at all.
- **Tables.** A tab-bearing block is a table: a blank line ends a row, a bare newline is a wrapped
  line inside a cell, a run of tabs separates columns; one recovered row is one Markdown paragraph
  `| cell | cell |`, with no header separator; an `Artículo N` lead on a tabbed line is never a row.
- **Lead of an article.** `scjn.api._LEAD_ARTICULO` bolds the whole number (`**Artículo 1.1**:`).
- `scripts/verify_scjn_outline.py` checks the contract over the local corpora and their raw
  answers, read-only: writer drift, marker completeness, attribute round-trip and text invariance.
  Exit 1 only on a round-trip or invariance violation. `scripts/measure_block_gaps.py` counts the
  snapshots whose `orden` markers have a gap and which are explained.

## Data: the releases and the cache

- **Data is never committed.** The corpora live in the four GitHub releases and in the gitignored
  `scripts/scjn/` (the crawl's output, the raw answers, the packaged releases). A release series
  is resolved by asking GitHub: a part keeps the bare tag, a continuation adds `-<n>`, and the
  reader probes `-1`, `-2`, ... until one 404s; a release holds at most 1,000 assets. An instrument
  with no consolidated text is indexed with `snapshots: 0` and no tarball.
- **No workflow publishes SCJN-derived data** (monorepo issue #115, Hallazgo C: the SCJN's search
  can return a completely wrong document for an instrument, so a human decides what is safe to
  publish). Every packaging script writes a `PUBLICAR.md` and uploads nothing; a regenerated
  release is replaced in place (same tag, `--clobber`).
- **The releases' owner.** The four releases still live in `INGEOTEC/LegalIA`, where they were
  first published: `scjn.release.DEFAULT_RELEASE_REPOSITORY` names it, and the environment
  variable `SCJN_RELEASE_REPOSITORY` (`<owner>/<name>`, read on every call by
  `release_repository`) points every lookup, and the `gh` commands `PUBLICAR.md` prints, at
  another owner, so a copy of the releases is verified against its new home before the default
  moves. Changing the default is a release of `scjn`.
- **The cache.** `scjn.cache.CACHE_DIR` (`$SCJN_CACHE_DIR`; platformdirs, `~/.cache/scjn` on
  Linux) is this package's alone, never shared with `nota2md`'s or `legalvec`'s. The release
  listing is one request to `api.github.com`, sent with `GH_TOKEN` or `GITHUB_TOKEN` when set
  (`_github_api_headers`); the asset downloads are outside that quota.

## Process A: crawl a corpus

A human runs the publish step.

1. `scripts/discover_federal_laws.py` / `discover_federal_reglamentos.py` /
   `discover_federal_lineamientos.py` / `discover_federal_tratados.py` list candidates and stop
   (no state is written; a new law is a human's decision). `scjn.discovery` holds the shared
   paging and rescue rules.
2. `scripts/seed_federal_reglamentos.py --coleccion {reglamentos,lineamientos,tratados}` turns a
   reviewed list into `estado.json` files, idempotently.
3. `scripts/fetch_scjn_legislacion.py` crawls (`--coleccion`, `--plan`, and for `leyes` only
   `--actualiza`/`--solo-fecha`/`--dof-only`/`--reintenta`); `scripts/recrawl_scjn_outline.py`
   re-crawls a whole corpus with the markers on; `scripts/rewrite_scjn_from_raw.py` rewrites
   Markdown from the kept raw answers without the network.
4. Linking new `leyes` reforms to their `codNota` is `nota2md`'s `scripts/enlaza_scjn_legislacion.py`,
   in that repository; the id-keyed collections have no DOF linking.
5. `scripts/verify_scjn_outline.py`, then `scripts/measure_block_gaps.py`.
6. `scripts/empaqueta_scjn_leyes.py` / `scripts/empaqueta_scjn_coleccion.py --coleccion ...`
   package the release (tarballs, `indice-global.json.gz`, `SHA256SUMS.txt`, `MANIFEST.md`,
   `partes.json`, `PUBLICAR.md`).
7. **A human** reads `PUBLICAR.md` and publishes; only changed tarballs need `--clobber`.

The three scripts that link laws to the DOF (`discover_federal_laws.py`,
`fetch_scjn_legislacion.py`, `recrawl_scjn_outline.py`) import `dofjson` and `nota2md` from PyPI,
never the package: `uv sync --group scripts` or `pip install dofjson nota2md`.

## Documentation

`docs/source/index.rst` is the Read the Docs page, the **developer reference**: every name in
`__all__`, every public method of an exported class and every CLI subcommand gets a verified
example, a live doctest run by the `docs` job of `test.yml` against the cached `lfca` law and
reglamento `104906`; an exception is written on the page itself, naming the pytest suite that
verifies the behaviour instead (`scjn.api` is the documented one). Private helpers (leading
underscore) get a full docstring and appear through `:private-members:` but need no example. The
HTML build is strict (`-n -W`). Read the Docs builds HTML only and never touches the network. Today
the page is also published as `scjn_api.html` of `legalia.readthedocs.io`, from the monorepo, until
this repository has a Read the Docs project of its own.

## Commands

```bash
pip install -e ".[test]"
pytest tests scripts/tests --ignore=tests/test_api_red.py --ignore=tests/test_release_red.py
pytest tests/test_api_red.py tests/test_release_red.py                   # network: the SCOW API, the release
scjn download --slug lfca && scjn download --coleccion reglamentos --id 104906   # what the doctests read
python -m sphinx -n -W --keep-going -b html docs/source docs/build/html   # the strict build
python -m sphinx -b doctest docs/source docs/build/doctest                # the examples, off the cache
python scripts/check_package_versions.py                                  # one step ahead of PyPI
```

## Releases to PyPI

- The version is dynamic (`scjn.__version__`) and at most one step ahead of PyPI (the next patch,
  or the next minor with patch 0): `check-package-versions` in `test.yml` is the gate.
- A tag `vX.Y.Z` on `main` runs `publish-pypi.yml`, which refuses a tag that does not match
  `__version__`, builds, checks and uploads with the organization's `TWINE` secret.
- Publish order across repositories: `scjn` before the `nota2md` release that raises its floor. A
  published package never carries a URL dependency.

## Git workflow: branches, issues and PRs

- A branch is created to work on one particular issue, only at the moment, while on `main`, an
  issue is read and about to be implemented.
- A secondary issue that turns out necessary is done on the working branch; no new branch.
- A pull request is opened only when the user explicitly asks for it, after the main issue and
  every secondary one are done. `main` takes changes only through a pull request (ruleset).

## Language policy

- The implementation is in English: identifiers, comments, docstrings, commit messages and new
  documentation, whatever language the instructions were given in.
- The codebase still mixes Spanish identifiers (`descarga_ordenamiento`, `versiones_de_directorio`,
  the Spanish CLI help of the scripts). Leave existing Spanish as it is when touching unrelated
  lines, no drive-by renames; new code, and code rewritten anyway, is English.
- Domain terms that are proper nouns or established Mexican legal vocabulary (`SCJN`, `codNota`,
  `DOF`, `abrev`, law abbreviations like `cpeum`/`lft`) are names, not translated.

## Working conventions

- Naming favours precision over brevity: `download_scjn_leyes_corpus`, `instrumento_key`,
  `articulos_of_reforma` are the domain's vocabulary.
- Comments record the incident or the numeric check that justified a design choice (why a
  repeated row is dropped, why a series is probed, why a token is sent); read them before
  "simplifying" the code they are attached to.
- The retired SCJN *Buscador* URL appears nowhere in the tree (`tests/test_site_references.py`).
- A behaviour that moves a snapshot's text is proved, not argued: `verify_scjn_outline.py --compare`
  over the local corpora.
