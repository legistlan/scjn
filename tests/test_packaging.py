"""Packaging metadata that `pyproject.toml` carries for development tools."""
import unittest
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10 has no tomllib; no dependency is added for it.
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
class TestUvCacheKeys(unittest.TestCase):
    """The version is dynamic (``scjn.__version__``), so uv only rebuilds the
    editable install on a version bump if ``scjn/__init__.py`` is a cache key."""

    def cache_keys(self):
        with open(ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["tool"]["uv"]["cache-keys"]

    def test_version_source_and_build_files_are_cache_keys(self):
        keys = self.cache_keys()
        for name in ("scjn/__init__.py", "pyproject.toml", "setup.py"):
            self.assertIn({"file": name}, keys)

    def test_every_cache_key_names_an_existing_file(self):
        for key in self.cache_keys():
            self.assertTrue((ROOT / key["file"]).is_file(), key)


if __name__ == "__main__":
    unittest.main()
