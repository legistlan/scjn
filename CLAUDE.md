# CLAUDE.md

This file guides Claude Code (claude.ai/code) in this repository. It says what the tree **is**, in
the present tense; a decision that outlives an issue is recorded here as a bullet.

## What this is

`scjn` is the client for the Suprema Corte de Justicia de la Nación's SCOW JSON API (`scjn.api`,
the backend of `legislacion.scjn.gob.mx/consulta`), the writer of the Markdown snapshots of an
instrument's reforms (`scjn.markdown`, `scjn.outline`) and the disk-first reader of the five SCJN
releases (`scjn.release`): `scjn-leyes` (315 federal laws, reform-dated snapshots, keyed by
`abrev`) and the id-keyed `scjn-reglamentos`, `scjn-lineamientos`, `scjn-tratados` and
`scjn-estatutos` (keyed by `id_ordenamiento`; `scjn-estatutos` holds the federal `ESTATUTO`
instruments). The five releases are published (seven tags counting continuations; the table in the
README says what each holds). The SCJN is not an official source of legal text; the *Diario Oficial de la
Federación* is, and `fuente: scjn` in a provenance header means exactly that.

**This repository and its releases hold SCJN data only.** The link between an SCJN snapshot and the
DOF note (`codNota`) that published it, the DOF text of candidate notes and the DOF dates used to
decide whether a law is up to date are not here and not in any release: that DOF linking lives
outside this repository. A `leyes` tarball ships the snapshots and `estado.json`, nothing else; the
freshness of a law is decided by the SCJN alone (`actualizado_scjn`, the reform-table row
comparison of `--plan`).

It is one package of the Legistlan project (the `legistlan` organization); `scjn` itself imports no
sibling, and `tests/test_boundary.py` greps the package for `nota2md`/`dofjson` and the scripts
for any import of either to keep it so. It was
`packages/scjn` of a monorepo until 9 November 2026 (monorepo commit
`f403872b1`); this repository is that history filtered to the package, its crawl scripts and its
documentation page, so `git log` and `git blame` reach the first commit. A `#N` in a commit
message, a comment or a docstring is an issue of the monorepo, where those issues live.

## The package

- **Read order**, the way a caller reaches the corpus: `scjn.release` (the entry points,
  disk-only), `scjn.api` (the transport and the completeness guard), `scjn.markdown` and
  `scjn.outline` (the writer and its markers), `scjn.discovery` (the shared paging and rescue
  rules of the id-keyed collections), `scjn.catalog` (slugs, `abrev`, `instrumento_key`),
  `scjn.state` (per-instrument crawl state), `scjn.header` (the provenance header), `scjn.cache`,
  `scjn.cli` (`scjn download`, `scjn --version`).
- **Entry points** for `scjn-leyes`: `download_scjn_leyes_index`/`_corpus`/`_catalog`,
  `markdown_de_snapshot`, `iter_current_federal_laws`, `local_slugs`,
  `download_scjn_leyes_assets`, `AssetNotCached`; the three id-keyed siblings have the same names
  with `reglamentos`/`lineamientos`/`tratados`/`estatutos` (`iter_current_*` included) and raise
  `SinTextoEnSCJN` for an instrument with no text. Every reader reads only the cache and raises
  `AssetNotCached` rather than downloading; only `download_*_assets` and `scjn download` talk to
  the network.
- **The command line is English, the Python API is not.** `scjn download --collection` takes
  `laws`, `regulations`, `guidelines`, `treaties` or `bylaws`; `scjn.cache.COLLECTION_CLI_NAMES`
  maps each internal name (`leyes`, `reglamentos`, `lineamientos`, `tratados`, `estatutos`) to
  it and is the only place that translation lives. `--all` downloads every entry of that
  mapping, so a new collection is one entry there. Release tags, cache directories and Python
  names stay Spanish.
- Only `leyes` has an `abrev` and an `actualizado`, the date of the newest reform the SCJN serves
  for the law, never a DOF date: the packager publishes `actualizado_scjn` (what the crawl records)
  or, when `estado.json` lacks it, the date of the law's newest snapshot
  (`actualizado_publicado` in `scripts/empaqueta_scjn_leyes.py`; no `actualizado` for a law with no
  snapshot); the id-keyed collections have none. An `abrev` is the release's slug and asset name, never re-derived. "Reform N" of a law
  is the SCJN reform table's chronological order.
- **Old copies are still read.** No published release has the shape the DOF linking left (the
  `scjn-leyes` index has no `codNota` section, a tarball holds the snapshots and `estado.json` only,
  and `estado.json` has none of the keys the linking wrote), but an older copy in a user's cache or
  in a mirror may: the readers ignore a `codNota` section, an `indice.json` and a `notas/` folder
  (`tests/test_release.py` covers that shape), and the packager never ships them nor those
  `estado.json` keys (`CLAVES_ESTADO_DOF` in `scripts/empaqueta_scjn_leyes.py`).
- **The classification of an instrument** (one value per instrument, never in a snapshot's
  provenance header): `scjn.release.CAMPOS_METADATOS` (`materia`, `vigencia`, `resumen`) and
  `CAMPOS_CLASIFICACION` (`categoria_ordenamiento`, `ambito`, `pais`, `estado`, `municipio`).
  They travel from the API hit (`scjn.api.Ordenamiento`) through `scjn.discovery` and the seed into
  `estado.json`, from it into every collection's `indice-global.json.gz` (the index omits a field
  with no value) and out of every reader (the keys are always returned, `None` where the index has
  none; an index older than a field lacks it, which is not an error). Every published index carries
  the classification wherever the SCJN gives it (the backfill was run on all four corpora before
  the releases were republished on 2026-11-17).
  `scripts/backfill_scjn_classification.py` fills them into the `estado.json` of instruments already
  crawled (match by `idOrdenamiento` only, never ranks, resumable through the
  `clasificacion_consultada` stamp it writes in `estado.json`, skips transport errors and exits 0); a human runs it, re-packages
  and publishes the index asset.
- **No source other than the SCJN**: every text comes from the SCJN, and a new law is discovered
  from the SCJN alone (`scripts/discover_federal_laws.py`). The original list of the 315 laws was
  seeded from the catalogue of federal legislation the Cámara de Diputados publishes
  (LeyesBiblio); that site is not a source of text and nothing in the tree reads it.

## The outline contract

The SCOW API serves a reform as ordered *blocks* (`orden`, `numero`, `referencia`, `contenido`,
`tamanio`). The writer puts one marker line before each block that yields text:

    <!-- scjn:block orden=N numero=N kind=<kind> [type=] [num=] label="..." -->

`kind` is one of header, recitals, preamble, toc, transitorios, decree, container, article,
provision, other. The marker is an HTML comment on purpose: no character of the text changes,
`strip_markers` returns the text byte for byte, and `markdown_de_snapshot(..., outline=False)` is
what a caller that wants the plain law reads. Every block that yields text has exactly one marker; a block that yields none
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

- **Data is never committed.** The corpora live in the GitHub releases and in the gitignored
  `scripts/scjn/` (the crawl's output, the raw answers, the packaged releases). A release series
  is resolved by asking GitHub: a part keeps the bare tag, a continuation adds `-<n>`, and the
  reader probes `-1`, `-2`, ... until one 404s; a release holds at most 1,000 assets. An instrument
  with no consolidated text is indexed with `snapshots: 0` and no tarball.
- **No workflow publishes SCJN-derived data** (monorepo issue #115, Hallazgo C: the SCJN's search
  can return a completely wrong document for an instrument, so a human decides what is safe to
  publish). Every packaging script writes a `PUBLICAR.md` and uploads nothing; a regenerated
  release is replaced in place (same tag, `--clobber`).
- **Copying the releases.** `scripts/copy_scjn_releases.py <owner>/<name>` copies the release series from a
  source repository to this one (a series the source lacks, as `scjn-estatutos` was before it
  was published, is reported and skipped) (title, body and every asset, byte for byte; `--destination`, `--tag`,
  `--batch`, `--dry-run`), uploads in retried batches, resumes by rerunning and exits non-zero unless
  names, sizes and digests match. It is how a move of owner is done; it publishes nothing new and names
  no source repository (a required argument). Downloads land in the gitignored `scripts/scjn/release-copy/`.
- **The releases' owner.** This repository owns the releases: `scjn.release.DEFAULT_RELEASE_REPOSITORY`
  names it (`legistlan/scjn`), and the environment variable `SCJN_RELEASE_REPOSITORY`
  (`<owner>/<name>`, read on every call by `release_repository`) points every lookup, and the `gh`
  commands `PUBLICAR.md` prints, at a mirror of the releases elsewhere. Changing the default is a
  release of `scjn`. `scripts/copy_scjn_releases.py` is how the releases were copied here.
- **The cache.** `scjn.cache.CACHE_DIR` (`$SCJN_CACHE_DIR`; platformdirs, `~/.cache/scjn` on
  Linux) is this package's alone, never shared with `nota2md`'s or `legalvec`'s. The release
  listing is one request to `api.github.com`, sent with `GH_TOKEN` or `GITHUB_TOKEN` when set
  (`_github_api_headers`); the asset downloads are outside that quota.

## Process A: crawl a corpus

A human runs the publish step.

1. `scripts/discover_federal_laws.py` / `discover_federal_reglamentos.py` /
   `discover_federal_lineamientos.py` / `discover_federal_tratados.py` /
   `discover_federal_estatutos.py` list candidates and stop
   (no state is written; a new law is a human's decision). `scjn.discovery` holds the shared
   paging and rescue rules.
2. `scripts/seed_federal_reglamentos.py --coleccion {reglamentos,lineamientos,tratados,estatutos}` turns a
   reviewed list into `estado.json` files, idempotently.
3. `scripts/fetch_scjn_legislacion.py` crawls (`--coleccion`, `--plan`, and for `leyes` only
   `--actualiza`/`--solo-fecha`/`--reintenta`); `scripts/recrawl_scjn_outline.py`
   re-crawls a whole corpus with the markers on; `scripts/rewrite_scjn_from_raw.py` rewrites
   Markdown from the kept raw answers without the network.
4. `scripts/backfill_scjn_classification.py --coleccion ...` (network; for instruments crawled
   before their `estado.json` had the whole classification), `scripts/verify_scjn_outline.py`, then
   `scripts/measure_block_gaps.py`.
5. `scripts/empaqueta_scjn_leyes.py` / `scripts/empaqueta_scjn_coleccion.py --coleccion ...`
   package the release (tarballs, `indice-global.json.gz`, `SHA256SUMS.txt`, `MANIFEST.md`,
   `partes.json`, `PUBLICAR.md`).
6. **A human** reads `PUBLICAR.md` and publishes; only changed tarballs need `--clobber`.

No script imports `dofjson` or `nota2md`, and there is no `scripts` dependency group: a clone runs
every script with the package's own dependencies.

## Documentation

One GitHub Pages site, `https://legistlan.github.io/scjn/`, built and deployed by
`.github/workflows/website.yml` (the official Pages artifact flow, Pages source "GitHub Actions",
no `gh-pages` branch; pull requests only build, a push to `main` deploys). It has two halves with
no overlapping page:

- `docs/source/index.rst`, published under `/dev/`, is the **developer reference**: every name in
  `__all__`, every public method of an exported class and every CLI subcommand gets a verified
  example, a live doctest run by the `docs` job of `test.yml` against the cached `lfca` law,
  reglamento `104906` and estatuto `111330`; an exception is written on the page itself, naming the pytest suite that
  verifies the behaviour instead (`scjn.api` is the documented one). Private helpers (leading
  underscore) get a full docstring and appear through `:private-members:` but need no example. The
  HTML build is strict (`-n -W`). The strict build and the doctest stay in `test.yml`'s `docs` job
  as the pull request gate; `website.yml` builds HTML only and never touches the network.
- `website/` is the Quarto **user site** at the root, in English, written from the README and these
  notes: install, command line, Python, releases, outline, crawl. `execute.enabled: false` (every
  example needs the cache or the network), no API reference; its code blocks are illustrative and
  the developer reference holds the verified ones. `tests/test_docs.py` keeps
  `website/pages/cli.qmd` naming every CLI option and every `scjn/*.py` module documented by
  exactly one `automodule` (`scjn.text` is the one named exception, until it has a section).

Both halves and the README use one vocabulary: an *instrument* is any legal text; the five
*collections* are laws, regulations, guidelines, treaties and bylaws, each named with its
release tag on first mention; a *snapshot* is a dated version of an instrument; *current* is the
latest text the SCJN serves, never "in force"; the texts are *editorial*, the DOF official.
Three sentences are fixed word for word and `tests/test_docs.py` (`TestCanonicalSentences`)
keeps them on the home page, the Releases page, the README and the developer reference: "The
texts are editorial: the Official Gazette of the Federation (DOF) remains the official source of
Mexican legal text.", "A snapshot is a dated version of an instrument: its text as it read after
one reform." and "Current means the latest text the SCJN serves for an instrument at the time it
was collected; it is not a determination that every provision is in force." The documentation
stops at the Markdown snapshot and its markers: what other packages do with them is not
described here.

Nothing in the tree names the former organization or the monorepo this package was extracted from:
provenance is said without naming ("the monorepo this package was extracted from"), links point at
`legistlan`, and `tests/test_docs.py` (`TestNoFormerOwnerNames`) fails on either name, in any letter
case, in any tracked file. A `#N` issue reference stays: it names nothing.

## Commands

```bash
pip install -e ".[test]"
pytest tests scripts/tests --ignore=tests/test_api_red.py --ignore=tests/test_release_red.py
pytest tests/test_api_red.py tests/test_release_red.py                   # network: the SCOW API, the release
scjn download --slug lfca --refresh && scjn download --collection regulations --id 104906 \
  && scjn download --collection bylaws --id 111330   # what the doctests read
python -m sphinx -n -W --keep-going -b html docs/source docs/build/html   # the strict build
quarto render website                                                     # the user site, into website/_site
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
- `[tool.uv] cache-keys` in `pyproject.toml` lists `scjn/__init__.py` (with `pyproject.toml` and
  `setup.py`, which replacing uv's default list drops) so uv rebuilds the editable install when
  `__version__` changes. Development-only: nothing in the wheel or a release changes;
  `tests/test_packaging.py` pins it.

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
- Domain terms that are proper nouns or established Mexican legal vocabulary (`SCJN`,
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
