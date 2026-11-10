"""The documentation site stays complete (issue #4).

Two halves share one GitHub Pages site (CLAUDE.md, "Documentation"): the Sphinx
developer reference (`docs/source/`) and the Quarto user site (`website/`).
These tests keep the first naming every module once and the second naming
every command-line option. They need the repository checkout.
"""

import re
import unittest
from pathlib import Path

from scjn import cli

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


if __name__ == "__main__":
    unittest.main()
