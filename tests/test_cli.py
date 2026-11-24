"""`scjn download` (`scjn.cli`): the English command line (`--collection`,
`--refresh`, `--all`, `--version`), with the downloaders replaced -- nothing
here touches the network (issues #9, #11)."""

import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

import scjn
from scjn import cache, cli
from scjn.cache import COLECCIONES_POR_ID, COLLECTION_CLI_NAMES, Coleccion

QUIET = lambda *_a, **_k: None  # noqa: E731


def _recorder(tag):
    """A fake downloader that records its arguments in `calls` and returns one result."""
    calls = []

    def falso(keys, **kw):
        calls.append({"keys": keys, **kw})
        return [(Path(f"/c/{tag}/x.tgz"), True)]

    falso.calls = calls
    return falso


def _all_fakes():
    return {nombre: _recorder(f"scjn-{nombre}") for nombre in COLLECTION_CLI_NAMES}


def _run(argv, fakes, log=QUIET):
    """Run `argv` with every downloader in `fakes` (keyed by internal name) patched in."""
    args = cli.build_parser().parse_args(argv)
    with patch.dict(cli._DESCARGAS_POR_ID, {n: f for n, f in fakes.items() if n != "leyes"}), \
            patch.object(cli, "download_scjn_leyes_assets", fakes["leyes"]):
        cli._main_download(args, log=log)


class TestVersion(unittest.TestCase):
    def test_version_prints_the_package_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue(), f"scjn {scjn.__version__}\n")


class TestCollectionDispatch(unittest.TestCase):
    def test_each_english_value_dispatches_to_its_downloader(self):
        for nombre, cli_name in COLLECTION_CLI_NAMES.items():
            if nombre == "leyes":
                continue
            with self.subTest(collection=cli_name):
                fakes = _all_fakes()
                _run(["download", "--collection", cli_name, "--id", "5001", "--cache-dir", "/c"], fakes)
                self.assertEqual(len(fakes[nombre].calls), 1)
                self.assertEqual(fakes[nombre].calls[0]["keys"], ["5001"])
                self.assertEqual(fakes[nombre].calls[0]["cache_dir"], "/c")
                for otro, falso in fakes.items():
                    if otro != nombre:
                        self.assertEqual(falso.calls, [])

    def test_no_collection_and_laws_both_download_leyes(self):
        for argv in (["download", "--slug", "lfca"], ["download", "--collection", "laws", "--slug", "lfca"]):
            with self.subTest(argv=argv):
                fakes = _all_fakes()
                _run(argv, fakes)
                self.assertEqual(len(fakes["leyes"].calls), 1)
                self.assertEqual(fakes["leyes"].calls[0]["keys"], ["lfca"])

    def test_refresh_is_forwarded_as_refrescar(self):
        fakes = _all_fakes()
        _run(["download", "--slug", "lfca", "--refresh"], fakes)
        self.assertIs(fakes["leyes"].calls[0]["refrescar"], True)
        fakes = _all_fakes()
        _run(["download", "--slug", "lfca"], fakes)
        self.assertIs(fakes["leyes"].calls[0]["refrescar"], False)

    def test_the_spanish_spellings_are_rejected(self):
        for argv in (
            ["download", "--coleccion", "leyes"],
            ["download", "--refrescar"],
            ["download", "--collection", "reglamentos"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), patch("sys.stderr"):
                cli.build_parser().parse_args(argv)

    def test_an_unknown_collection_is_rejected(self):
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            cli.build_parser().parse_args(["download", "--collection", "agreements"])


class TestAll(unittest.TestCase):
    def test_all_downloads_every_collection_once(self):
        fakes = _all_fakes()
        lines = []
        _run(["download", "--all", "--refresh", "--cache-dir", "/c"], fakes, log=lines.append)
        for nombre, falso in fakes.items():
            with self.subTest(collection=nombre):
                self.assertEqual(len(falso.calls), 1)
                self.assertIsNone(falso.calls[0]["keys"])
                self.assertIs(falso.calls[0]["refrescar"], True)
                self.assertEqual(falso.calls[0]["cache_dir"], "/c")
        summaries = [line for line in lines if str(line).startswith("scjn-")]
        self.assertEqual(len(summaries), 5)

    def test_all_includes_a_collection_added_to_the_registry(self):
        fakes = _all_fakes()
        sexta = _recorder("scjn-acuerdos")
        nueva = Coleccion(nombre="acuerdos", tag_base="scjn-acuerdos", subdirectorio="scjn-acuerdos")
        with patch.dict(cache.COLLECTION_CLI_NAMES, {"acuerdos": "agreements"}), \
                patch.dict(cache.COLECCIONES_POR_ID, {"acuerdos": nueva}), \
                patch.dict(cli._DESCARGAS_POR_ID, {"acuerdos": sexta}):
            _run(["download", "--all"], {**fakes, "acuerdos": sexta})
            self.assertEqual(len(sexta.calls), 1)
            args = cli.build_parser().parse_args(["download", "--collection", "agreements"])
            self.assertEqual(args.collection, "agreements")

    def test_all_cannot_be_combined(self):
        for extra in (["--collection", "laws"], ["--slug", "lfca"], ["--id", "5001"]):
            with self.subTest(extra=extra):
                fakes = _all_fakes()
                with self.assertRaises(SystemExit) as ctx:
                    _run(["download", "--all", *extra], fakes)
                self.assertEqual(
                    ctx.exception.code,
                    "--all cannot be combined with --collection, --slug or --id",
                )
                for falso in fakes.values():
                    self.assertEqual(falso.calls, [])


class TestErrors(unittest.TestCase):
    def test_id_with_laws_is_an_error(self):
        with self.assertRaises(SystemExit) as ctx:
            _run(["download", "--id", "5001"], _all_fakes())
        self.assertEqual(
            ctx.exception.code,
            "--id only applies with --collection regulations/guidelines/treaties/bylaws",
        )

    def test_slug_with_an_id_keyed_collection_is_an_error(self):
        with self.assertRaises(SystemExit) as ctx:
            _run(["download", "--collection", "bylaws", "--slug", "lfca"], _all_fakes())
        self.assertEqual(
            ctx.exception.code, "--slug only applies with --collection laws (the default)"
        )


class TestRegistry(unittest.TestCase):
    def test_the_registry_is_consistent(self):
        self.assertEqual(set(COLLECTION_CLI_NAMES), {"leyes"} | set(COLECCIONES_POR_ID))
        values = list(COLLECTION_CLI_NAMES.values())
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(set(cli._DESCARGAS_POR_ID), set(COLECCIONES_POR_ID))
        self.assertIs(cli._DESCARGAS_POR_ID["estatutos"], scjn.download_scjn_estatutos_assets)

    def test_help_is_english(self):
        sub = next(
            action for action in cli.build_parser()._actions if hasattr(action, "choices") and action.choices
        ).choices["download"]
        text = sub.format_help()
        for word in ("coleccion", "refrescar", "solo aplica", "partes"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
