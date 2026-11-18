"""Client for the SCJN's SCOW JSON API (`scjn.api`), the federal-law
catalogue's own algebra (`scjn.catalog`), per-instrument crawl state
(`scjn.state`), the provenance header a crawl writes to every snapshot
(`scjn.header`), and the disk-first readers (`scjn.release`) for the five
GitHub releases this package feeds -- `scjn-leyes` and, since issues #220,
#222, #277 and #9, the id-keyed `scjn-reglamentos`/`scjn-lineamientos`/
`scjn-tratados`/`scjn-estatutos` -- re-exported
here as the package's own entry points.

The SCJN is not an official source of legal text — the Diario Oficial de la
Federación remains that; this package's own crawl is a convenience corpus
its consolidated view makes possible, not a replacement for it.

This package holds SCJN data only: nothing in it, or in the releases it
reads, links a snapshot to the Diario Oficial de la Federación note that
published it. That linking lives outside this repository.
"""

from scjn.release import (
    AssetNotCached,
    SinTextoEnSCJN,
    download_scjn_leyes_assets,
    download_scjn_leyes_catalog,
    download_scjn_leyes_corpus,
    download_scjn_estatutos_assets,
    download_scjn_estatutos_corpus,
    download_scjn_estatutos_index,
    download_scjn_leyes_index,
    download_scjn_lineamientos_assets,
    download_scjn_lineamientos_corpus,
    download_scjn_lineamientos_index,
    download_scjn_reglamentos_assets,
    download_scjn_reglamentos_corpus,
    download_scjn_reglamentos_index,
    download_scjn_tratados_assets,
    download_scjn_tratados_corpus,
    download_scjn_tratados_index,
    iter_current_estatutos,
    iter_current_federal_laws,
    iter_current_lineamientos,
    iter_current_reglamentos,
    iter_current_tratados,
    local_estatutos_ids,
    local_lineamientos_ids,
    local_reglamentos_ids,
    local_slugs,
    local_tratados_ids,
    markdown_de_snapshot,
)

__version__ = "0.6.0"

__all__ = [
    "download_scjn_leyes_corpus",
    "download_scjn_leyes_index",
    "download_scjn_leyes_catalog",
    "iter_current_federal_laws",
    "iter_current_reglamentos",
    "iter_current_lineamientos",
    "iter_current_tratados",
    "iter_current_estatutos",
    "markdown_de_snapshot",
    "download_scjn_leyes_assets",
    "local_slugs",
    "download_scjn_reglamentos_index",
    "download_scjn_reglamentos_corpus",
    "download_scjn_reglamentos_assets",
    "local_reglamentos_ids",
    "download_scjn_lineamientos_index",
    "download_scjn_lineamientos_corpus",
    "download_scjn_lineamientos_assets",
    "local_lineamientos_ids",
    "download_scjn_tratados_index",
    "download_scjn_tratados_corpus",
    "download_scjn_tratados_assets",
    "local_tratados_ids",
    "download_scjn_estatutos_index",
    "download_scjn_estatutos_corpus",
    "download_scjn_estatutos_assets",
    "local_estatutos_ids",
    "AssetNotCached",
    "SinTextoEnSCJN",
]
