"""The documentation site stays complete (issue #4).

Two halves share one GitHub Pages site (CLAUDE.md, "Documentation"): the Sphinx
developer reference (`docs/source/`) and the Quarto user site (`website/`).
These tests keep the first naming every module once and the second naming
every command-line option. They need the repository checkout.
"""

import re
import subprocess
import unittest
from pathlib import Path

from scjn import cli
from scjn.cache import COLLECTION_CLI_NAMES

ROOT = Path(__file__).resolve().parents[1]

_AUTOMODULE_RE = re.compile(r"^\.\.\s+automodule::\s+(\S+)\s*$", re.MULTILINE)

#: Modules with no `automodule` section on the developer page today. A module
#: listed here must be named by none, so the set cannot go stale.
UNDOCUMENTED = {"scjn.text"}


@unittest.skipUnless(
    (ROOT / "docs" / "source").is_dir(),
    "needs the repository checkout (docs/ next to tests/)",
)
class TestEveryModuleHasExactlyOneAutomodulePage(unittest.TestCase):
    def _documented(self):
        rst_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "docs" / "source").rglob("*.rst")
        )
        return _AUTOMODULE_RE.findall(rst_text)

    def test_every_module_is_documented_exactly_once(self):
        module_names = sorted(
            f"scjn.{path.stem}"
            for path in (ROOT / "scjn").glob("*.py")
            if path.stem != "__init__" and f"scjn.{path.stem}" not in UNDOCUMENTED
        )
        self.assertTrue(module_names, "expected at least one scjn/*.py module")

        documented = self._documented()
        for name in module_names:
            occurrences = documented.count(name)
            self.assertEqual(
                occurrences, 1,
                f"{name} is named by {occurrences} automodule directives under "
                "docs/source/, expected exactly 1",
            )

    def test_an_undocumented_module_is_named_by_no_directive(self):
        documented = self._documented()
        for name in sorted(UNDOCUMENTED):
            self.assertEqual(
                documented.count(name), 0,
                f"{name} is in UNDOCUMENTED but docs/source/ has an automodule for it: "
                "remove it from the set",
            )
            self.assertTrue(
                (ROOT / "scjn" / (name.split(".", 1)[1] + ".py")).is_file(),
                f"{name} is in UNDOCUMENTED but the module does not exist",
            )


@unittest.skipUnless(
    (ROOT / "website" / "pages").is_dir(),
    "needs the repository checkout (website/ next to tests/)",
)
class TestCliPageNamesEveryOption(unittest.TestCase):
    def test_every_option_and_subcommand_appears_in_the_cli_page(self):
        import argparse

        page = (ROOT / "website" / "pages" / "cli.qmd").read_text(encoding="utf-8")

        def walk(parser):
            names = set()
            for action in parser._actions:
                names.update(o for o in action.option_strings if o not in ("-h", "--help"))
                if isinstance(action, argparse._SubParsersAction):
                    for name, sub in action.choices.items():
                        names.add(name)
                        names.update(walk(sub))
            return names

        required = walk(cli.build_parser())
        self.assertIn("--cache-dir", required)
        self.assertIn("download", required)

        missing = sorted(name for name in required if name not in page)
        self.assertFalse(
            missing,
            "website/pages/cli.qmd does not name these: " + ", ".join(missing),
        )


class TestNoFormerOwnerNames(unittest.TestCase):
    """No tracked file names the organization or the monorepo this package came from (issue #6).

    Links, comments and prose point at legistlan (this repository, its releases
    and its GitHub Pages site); provenance is said without naming ("the monorepo
    this package was extracted from on 9 November 2026"). A `#N` issue reference
    stays: it names nothing. The check is case-insensitive and also catches the
    two bare words.
    """

    # Built from fragments so this file does not flag itself.
    FORMER = (
        "legal" + "ia",
        "ingeo" + "tec",
    )

    def test_no_tracked_file_names_the_former_owner(self):
        try:
            listing = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available or ROOT is not a git checkout")

        offenders = {}
        for name in filter(None, listing.decode("utf-8").split("\0")):
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                lowered = path.read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue
            found = [word for word in self.FORMER if word in lowered]
            if found:
                offenders[name] = found

        self.assertFalse(
            offenders,
            "tracked files name the former organization or monorepo: "
            + "; ".join(f"{n}: {', '.join(w)}" for n, w in sorted(offenders.items())),
        )


class TestCliSpelling(unittest.TestCase):
    """`scjn download` is English at the command line (issue #11).

    The Spanish spelling (`--coleccion`, `--refrescar`) belongs to the crawl
    scripts under `scripts/`, never to `scjn download`; the README Changelog
    keeps it in the entries that say what was true then.
    """

    SPANISH = re.compile(r"scjn download[^\n]*--(coleccion|refrescar)")
    SKIPPED = {"tests/test_docs.py", "tests/test_cli.py"}
    SUFFIXES = (".md", ".qmd", ".rst", ".yml", ".py")

    @staticmethod
    def _changelog_lines(text):
        """The 1-based numbers of the README lines inside the Changelog section."""
        inside, numbers = False, set()
        for number, line in enumerate(text.splitlines(), start=1):
            if line.startswith("## "):
                inside = line.strip() == "## Changelog"
            if inside:
                numbers.add(number)
        return numbers

    def test_no_document_shows_the_spanish_cli_spelling(self):
        try:
            listing = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available or ROOT is not a git checkout")

        offenders = []
        for name in filter(None, listing.decode("utf-8").split("\0")):
            if (
                not name.endswith(self.SUFFIXES)
                or name.startswith("scripts/")
                or name in self.SKIPPED
            ):
                continue
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            exempt = self._changelog_lines(text) if name == "README.md" else set()
            for number, line in enumerate(text.splitlines(), start=1):
                if number not in exempt and self.SPANISH.search(line):
                    offenders.append(f"{name}:{number}")

        self.assertFalse(
            offenders,
            "these lines show `scjn download` with a Spanish option: " + ", ".join(offenders),
        )

    def test_the_cli_page_maps_every_collection_value_to_its_release(self):
        page = (ROOT / "website" / "pages" / "cli.qmd").read_text(encoding="utf-8")
        for nombre, cli_name in COLLECTION_CLI_NAMES.items():
            with self.subTest(collection=cli_name):
                self.assertIn(f"`{cli_name}`", page)
                self.assertIn(f"`scjn-{nombre}`", page)


@unittest.skipUnless(
    (ROOT / "website" / "pages").is_dir(),
    "needs the repository checkout (website/ next to tests/)",
)
class TestCanonicalSentences(unittest.TestCase):
    """The user site and the README say the same three things in the same words (issue #12)."""

    S1 = (
        "The texts are editorial: the Official Gazette of the Federation (DOF) remains "
        "the official source of Mexican legal text."
    )
    S2 = "A snapshot is a dated version of an instrument: its text as it read after one reform."
    S3 = (
        "Current means the latest text the SCJN serves for an instrument at the time it "
        "was collected; it is not a determination that every provision is in force."
    )

    @staticmethod
    def _read(relative):
        """The file's text with every run of whitespace collapsed to one space."""
        return " ".join((ROOT / relative).read_text(encoding="utf-8").split())

    def test_the_home_page_says_the_texts_are_editorial(self):
        self.assertIn(self.S1, self._read("website/index.qmd"))

    def test_the_readme_says_the_texts_are_editorial(self):
        text = self._read("README.md")
        self.assertIn(self.S1, text)
        self.assertIn(self.S2, text)

    def test_the_releases_page_defines_snapshot_and_current(self):
        text = self._read("website/pages/releases.qmd")
        self.assertIn(self.S2, text)
        self.assertIn(self.S3, text)

    def test_the_developer_reference_has_the_three_sentences(self):
        text = self._read("docs/source/index.rst")
        for sentence in (self.S1, self.S2, self.S3):
            with self.subTest(sentence=sentence[:30]):
                self.assertIn(sentence, text)

    def test_the_developer_reference_names_every_collection(self):
        text = self._read("docs/source/index.rst")
        for nombre, cli_name in COLLECTION_CLI_NAMES.items():
            with self.subTest(collection=cli_name):
                self.assertIn(f"``scjn-{nombre}``", text)
                if nombre != "leyes":
                    self.assertIn(f"scjn download --collection {cli_name}", text)

    def test_convenience_corpus_is_gone_from_the_developer_reference_and_the_package(self):
        for relative in ("docs/source/index.rst", "scjn/__init__.py"):
            with self.subTest(file=relative):
                self.assertNotIn("convenience corpus", self._read(relative).lower())

    def test_the_retired_phrases_are_gone(self):
        files = [ROOT / "README.md", *sorted((ROOT / "website").rglob("*.qmd"))]
        for path in files:
            if "_site" in path.relative_to(ROOT).parts:
                continue
            text = " ".join(path.read_text(encoding="utf-8").split()).lower()
            for phrase in ("convenience corpus", "consolidated view"):
                with self.subTest(file=str(path.relative_to(ROOT)), phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_releases_page_names_every_collection(self):
        page = self._read("website/pages/releases.qmd")
        for nombre, cli_name in COLLECTION_CLI_NAMES.items():
            with self.subTest(collection=cli_name):
                self.assertIn(cli_name, page)
                self.assertIn(f"`scjn-{nombre}`", page)


if __name__ == "__main__":
    unittest.main()
