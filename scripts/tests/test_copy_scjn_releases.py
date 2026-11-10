"""`scripts/copy_scjn_releases.py` (issue #5) against a fake `gh` -- no network.
`subprocess.run` is patched everywhere. Not part of `pytest tests` (this
directory is orchestration, not a package): run with

    pytest scripts/tests -q
"""

import contextlib
import io
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import copy_scjn_releases as c  # noqa: E402

SRC, DST = "example/source", "example/destination"


def _done(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def _failure(stderr):
    return subprocess.CalledProcessError(1, ["gh"], output="", stderr=stderr)


class FakeGh:
    """A tiny in-memory GitHub: `repos[repo][tag]` is a release; `calls` records every command."""

    def __init__(self):
        self.repos = {SRC: {}, DST: {}}
        self.calls = []
        self.next_id = 100
        self.curl_fails = False
        self.upload_failures = 0  # how many `gh release upload` calls fail before one succeeds

    def release(self, repo, tag, title="T", body="B", assets=None):
        self.next_id += 1
        self.repos[repo][tag] = {"id": self.next_id, "name": title, "body": body,
                                 "assets": dict(assets or {})}

    def _by_id(self, repo, rid):
        return next(r for r in self.repos[repo].values() if r["id"] == int(rid))

    def run(self, cmd, **kwargs):
        assert cmd[0] in ("gh", "curl") and kwargs.get("check") and "shell" not in kwargs
        self.calls.append(cmd)
        args = cmd[1:]
        if cmd[0] == "curl":  # curl -fsSL --retry 3 -o <path> https://github.com/<repo>/releases/download/<tag>/<name>
            _, _, _, repo1, repo2, _, _, tag, name = cmd[-1].split("/")
            name = urllib.parse.unquote(name)
            if self.curl_fails:
                raise _failure("curl: (22) 404")
            size = self.repos[f"{repo1}/{repo2}"][tag]["assets"][name][0]
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"x" * size)
            return _done()
        if args[0] == "api":
            return self._api(args[1:])
        if args[:2] == ["release", "download"]:
            tag, repo, outdir = args[2], args[args.index("-R") + 1], Path(args[args.index("-D") + 1])
            wanted = args[args.index("-p") + 1]
            size = self.repos[repo][tag]["assets"][wanted][0]
            (outdir / wanted).write_bytes(b"x" * size)
            return _done()
        if args[:2] == ["release", "create"]:
            tag, repo = args[2], args[args.index("-R") + 1]
            assert tag not in self.repos[repo], "created a release that exists"
            self.release(repo, tag, title=args[args.index("--title") + 1],
                         body=Path(args[args.index("--notes-file") + 1]).read_text(encoding="utf-8"))
            return _done()
        if args[:2] == ["release", "upload"]:
            if self.upload_failures:
                self.upload_failures -= 1
                raise _failure("HTTP 403: secondary rate limit")
            tag, repo = args[2], args[args.index("-R") + 1]
            assert "--clobber" in args
            for path in (Path(a) for a in args[3:args.index("-R")]):
                # GitHub digests the bytes: here, the same bytes carry the digest the source reports.
                source = self.repos[SRC].get(tag, {"assets": {}})["assets"].get(path.name, (0, None))
                self.repos[repo][tag]["assets"][path.name] = (path.stat().st_size, source[1])
            return _done()
        if args[:2] == ["release", "edit"]:
            tag, repo = args[2], args[args.index("-R") + 1]
            if "--title" in args:
                self.repos[repo][tag]["name"] = args[args.index("--title") + 1]
                self.repos[repo][tag]["body"] = Path(
                    args[args.index("--notes-file") + 1]).read_text(encoding="utf-8")
            return _done()
        raise AssertionError(f"unexpected command {cmd}")

    def _api(self, args):
        paginate = args[0] == "--paginate"
        endpoint = args[-1]
        repo_path = endpoint.split("/", 3)  # repos, owner, name, rest
        repo = f"{repo_path[1]}/{repo_path[2]}"
        rest = repo_path[3]
        if rest.startswith("releases/tags/"):
            release = self.repos[repo].get(rest.split("/", 2)[2])
            if release is None:
                raise _failure("gh: Not Found (HTTP 404)")
            return _done(json.dumps({"id": release["id"], "name": release["name"],
                                     "body": release["body"]}))
        assert paginate and rest.startswith("releases/") and "/assets" in rest
        release = self._by_id(repo, rest.split("/")[1])
        rows = [{"name": n, "size": s, "digest": d} for n, (s, d) in release["assets"].items()]
        pages = [rows[i:i + 100] for i in range(0, len(rows), 100)] or [[]]
        return _done("".join(json.dumps(page) for page in pages))  # gh prints page after page


@pytest.fixture
def gh(monkeypatch, tmp_path):
    fake = FakeGh()
    monkeypatch.setattr(subprocess, "run", fake.run)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    fake.tmp = tmp_path
    return fake


def _populate_source(gh):
    gh.release(SRC, "scjn-leyes", "SCJN — leyes", "manifest",
               {"a.tgz": (3, "sha256:a"), "b.tgz": (4, "sha256:b"), "c.tgz": (5, None)})
    gh.release(SRC, "scjn-reglamentos", "SCJN — reglamentos", "r1", {"1.tgz": (1, None)})
    gh.release(SRC, "scjn-reglamentos-2", "SCJN — reglamentos (overflow)", "r2", {"2.tgz": (2, None)})
    gh.release(SRC, "unrelated-release", "Other", "x", {"z.tgz": (9, None)})  # not one of the four


def _main(gh, *extra):
    argv = [SRC, "--destination", DST, "--outdir", str(gh.tmp / "out"), *extra]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = c.main(argv)
    return code, out.getvalue(), err.getvalue()


def _writes(gh):
    return [cmd[1:3] for cmd in gh.calls
            if cmd[1:3] in (["release", "create"], ["release", "upload"], ["release", "edit"])]


class TestDifferences:
    def test_identical_listings(self):
        listing = {"a": (1, "sha256:x"), "b": (2, None)}
        assert c.differences(listing, dict(listing)) == ([], [])

    def test_missing_names_sorted(self):
        src = {"b": (1, None), "a": (1, None), "c": (1, None)}
        assert c.differences(src, {"c": (1, None)}) == (["a", "b"], [])

    def test_size_mismatch(self):
        assert c.differences({"a": (1, None)}, {"a": (2, None)}) == ([], ["a"])

    def test_digest_mismatch_with_the_same_size(self):
        assert c.differences({"a": (1, "sha256:x")}, {"a": (1, "sha256:y")}) == ([], ["a"])

    @pytest.mark.parametrize("src,dst", [(None, "sha256:y"), ("sha256:x", None), (None, None)])
    def test_a_null_digest_on_one_side_is_ignored(self, src, dst):
        assert c.differences({"a": (1, src)}, {"a": (1, dst)}) == ([], [])

    def test_an_extra_asset_at_the_destination_is_not_a_difference(self):
        assert c.differences({"a": (1, None)}, {"a": (1, None), "z": (9, None)}) == ([], [])


class TestSeriesTags:
    def test_stops_at_the_first_tag_the_source_does_not_have(self, gh):
        for tag in ("scjn-tratados", "scjn-tratados-2", "scjn-tratados-4"):  # -3 is the gap
            gh.release(SRC, tag)
        assert c.series_tags(SRC, "scjn-tratados") == ["scjn-tratados", "scjn-tratados-2"]

    def test_a_missing_bare_tag_yields_nothing(self, gh):
        gh.release(SRC, "scjn-tratados-2")
        assert c.series_tags(SRC, "scjn-tratados") == []

    def test_another_failure_is_raised(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", mock.Mock(side_effect=_failure("HTTP 500")))
        with pytest.raises(subprocess.CalledProcessError):
            c.series_tags(SRC, "scjn-leyes")


class TestAssetsOf:
    def test_parses_a_paginated_answer(self, gh):
        assets = {f"{i:04d}.tgz": (i + 1, None if i % 2 else f"sha256:{i}") for i in range(250)}
        gh.release(SRC, "scjn-reglamentos", assets=assets)
        out = gh.run(["gh", "api", "--paginate", f"repos/{SRC}/releases/101/assets?per_page=100"],
                     check=True).stdout
        assert out.count("][") == 2  # three pages, printed one after another
        assert c.assets_of(SRC, 101) == assets

    def test_an_empty_release(self, gh):
        gh.release(SRC, "scjn-leyes")
        assert c.assets_of(SRC, 101) == {}


class TestMain:
    def test_source_is_required_with_no_default(self):
        with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit):
            c.main([])

    def test_dry_run_writes_nothing(self, gh):
        _populate_source(gh)
        code, out, _ = _main(gh, "--dry-run")
        assert code == 0
        assert _writes(gh) == []
        assert not any(cmd[0] == "curl" or cmd[1:3] == ["release", "download"] for cmd in gh.calls)
        assert not (gh.tmp / "out").exists()
        assert gh.repos[DST] == {}
        assert "would create the release" in out and "unrelated-release" not in out

    def test_a_full_copy_creates_uploads_and_verifies(self, gh):
        _populate_source(gh)
        code, out, _ = _main(gh)
        assert code == 0
        assert out.splitlines()[-1] == "copy verified: 3 releases, 5 assets"
        assert set(gh.repos[DST]) == {"scjn-leyes", "scjn-reglamentos", "scjn-reglamentos-2"}
        for tag, src in gh.repos[SRC].items():
            if tag in gh.repos[DST]:
                dst = gh.repos[DST][tag]
                assert (dst["name"], dst["body"]) == (src["name"], src["body"])
                assert {n: s for n, (s, _) in dst["assets"].items()} == \
                    {n: s for n, (s, _) in src["assets"].items()}
        creates = [cmd for cmd in gh.calls if cmd[1:3] == ["release", "create"]]
        assert all("--latest=false" in cmd and "--target" in cmd for cmd in creates)
        assert ["gh", "release", "edit", "scjn-leyes", "-R", DST, "--latest"] in gh.calls

    def test_a_destination_that_equals_the_source_uploads_nothing(self, gh):
        _populate_source(gh)
        for tag in ("scjn-leyes", "scjn-reglamentos", "scjn-reglamentos-2"):
            src = gh.repos[SRC][tag]
            gh.release(DST, tag, src["name"], src["body"], src["assets"])
        code, out, _ = _main(gh)
        assert code == 0
        assert [w for w in _writes(gh) if w != ["release", "edit"]] == []  # only the --latest edit
        assert not any(cmd[0] == "curl" or cmd[1:3] == ["release", "download"] for cmd in gh.calls)
        assert out.splitlines()[-1] == "copy verified: 3 releases, 5 assets"

    def test_two_missing_assets_are_the_only_ones_uploaded(self, gh):
        _populate_source(gh)
        for tag in ("scjn-leyes", "scjn-reglamentos", "scjn-reglamentos-2"):
            src = gh.repos[SRC][tag]
            gh.release(DST, tag, src["name"], src["body"], src["assets"])
        del gh.repos[DST]["scjn-leyes"]["assets"]["a.tgz"]
        del gh.repos[DST]["scjn-leyes"]["assets"]["c.tgz"]
        code, _, _ = _main(gh)
        assert code == 0
        uploads = [cmd for cmd in gh.calls if cmd[1:3] == ["release", "upload"]]
        assert len(uploads) == 1
        assert sorted(Path(a).name for a in uploads[0][4:uploads[0].index("-R")]) == ["a.tgz", "c.tgz"]
        assert not any(cmd[1:3] == ["release", "create"] for cmd in gh.calls)

    def test_a_differing_title_is_edited(self, gh):
        _populate_source(gh)
        for tag in ("scjn-leyes", "scjn-reglamentos", "scjn-reglamentos-2"):
            src = gh.repos[SRC][tag]
            gh.release(DST, tag, src["name"], src["body"], src["assets"])
        gh.repos[DST]["scjn-reglamentos"]["name"] = "stale"
        code, _, _ = _main(gh)
        assert code == 0
        assert gh.repos[DST]["scjn-reglamentos"]["name"] == "SCJN — reglamentos"

    def test_uploads_go_in_batches(self, gh):
        assets = {f"{i:02d}.tgz": (1, None) for i in range(7)}
        gh.release(SRC, "scjn-lineamientos", "SCJN — lineamientos", "b", assets)
        code, out, _ = _main(gh, "--batch", "3")
        assert code == 0
        uploads = [cmd for cmd in gh.calls if cmd[1:3] == ["release", "upload"]]
        assert [len(u) - 7 for u in uploads] == [3, 3, 1]  # gh release upload <tag> <files...> -R d --clobber
        assert "scjn-lineamientos: 3/7 uploaded" in out and "scjn-lineamientos: 7/7 uploaded" in out

    def test_the_tag_option_restricts_the_run(self, gh):
        _populate_source(gh)
        code, _, _ = _main(gh, "--tag", "scjn-reglamentos-2")
        assert code == 0
        assert set(gh.repos[DST]) == {"scjn-reglamentos-2"}

    def test_an_unknown_tag_stops(self, gh):
        _populate_source(gh)
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            _main(gh, "--tag", "scjn-tratados")

    def test_exits_non_zero_when_something_is_still_missing(self, gh, monkeypatch):
        _populate_source(gh)
        monkeypatch.setattr(c, "upload_batch", lambda *a, **k: None)  # an upload that silently drops
        code, out, err = _main(gh)
        assert code == 1
        assert "copy verified" not in out and "missing" in err


class TestUploadRetries:
    def test_a_batch_that_fails_twice_is_retried(self, gh):
        gh.release(DST, "scjn-leyes")
        f = gh.tmp / "a.tgz"
        f.write_bytes(b"abc")
        gh.upload_failures = 2
        with mock.patch.object(c.time, "sleep") as sleep:
            c.upload_batch(DST, "scjn-leyes", [f])
        assert sleep.call_args_list == [mock.call(60), mock.call(120)]
        assert gh.repos[DST]["scjn-leyes"]["assets"]["a.tgz"][0] == 3

    def test_a_batch_that_never_succeeds_raises(self, gh):
        gh.release(DST, "scjn-leyes")
        f = gh.tmp / "a.tgz"
        f.write_bytes(b"abc")
        gh.upload_failures = 99
        with contextlib.redirect_stderr(io.StringIO()), pytest.raises(subprocess.CalledProcessError):
            c.upload_batch(DST, "scjn-leyes", [f])
        assert len([x for x in gh.calls if x[1:3] == ["release", "upload"]]) == c.UPLOAD_ATTEMPTS


class TestDownload:
    def test_fetches_only_what_is_not_there_through_the_public_url(self, gh):
        gh.release(SRC, "t", assets={"a.tgz": (3, None), "b c.tgz": (2, None)})
        outdir = gh.tmp / "d"
        outdir.mkdir()
        (outdir / "a.tgz").write_bytes(b"abc")  # already whole
        with contextlib.redirect_stdout(io.StringIO()):
            assert c.download(SRC, "t", outdir, {"a.tgz": (3, None), "b c.tgz": (2, None)}) == 2
        curls = [cmd for cmd in gh.calls if cmd[0] == "curl"]
        assert [cmd[-1] for cmd in curls] == [f"https://github.com/{SRC}/releases/download/t/b%20c.tgz"]
        assert (outdir / "b c.tgz").stat().st_size == 2 and not list(outdir.glob("*.part"))

    def test_a_truncated_file_is_fetched_again(self, gh):
        gh.release(SRC, "t", assets={"a.tgz": (3, None)})
        outdir = gh.tmp / "d"
        outdir.mkdir()
        (outdir / "a.tgz").write_bytes(b"xx")
        with contextlib.redirect_stdout(io.StringIO()):
            c.download(SRC, "t", outdir, {"a.tgz": (3, None)})
        assert (outdir / "a.tgz").stat().st_size == 3

    def test_a_wrong_size_after_the_download_stops_the_run(self, gh):
        gh.release(SRC, "t", assets={"a.tgz": (2, None)})  # the listing below claims 3
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            c.download(SRC, "t", gh.tmp / "d", {"a.tgz": (3, None)})

    def test_a_complete_folder_downloads_nothing(self, gh):
        outdir = gh.tmp / "d"
        outdir.mkdir()
        (outdir / "a.tgz").write_bytes(b"abc")
        assert c.download(SRC, "t", outdir, {"a.tgz": (3, None)}) == 1
        assert gh.calls == []

    def test_a_failed_curl_falls_back_to_gh_with_retries(self, gh):
        gh.release(SRC, "t", assets={"a.tgz": (3, None)})
        gh.curl_fails = True
        outdir = gh.tmp / "d"
        with contextlib.redirect_stdout(io.StringIO()):
            c.download(SRC, "t", outdir, {"a.tgz": (3, None)})
        assert [cmd[1:3] for cmd in gh.calls if cmd[0] == "gh"] == [["release", "download"]]
        assert not list(outdir.glob("*.part"))

    def test_a_rate_limited_gh_download_is_retried(self, gh, monkeypatch):
        outdir = gh.tmp / "d"
        calls = []

        def flaky(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "curl" or len(calls) == 2:
                raise _failure("HTTP 403: API rate limit exceeded")
            outdir.mkdir(exist_ok=True)
            (outdir / "a.tgz").write_bytes(b"abc")
            return _done()

        monkeypatch.setattr(subprocess, "run", flaky)
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(c.time, "sleep") as sleep:
            assert c.download(SRC, "t", outdir, {"a.tgz": (3, None)}) == 1
        assert len(calls) == 3 and sleep.call_args_list == [mock.call(60)]


class TestRun:
    def test_a_failed_gh_ends_with_its_stderr_and_exit_1(self, gh, monkeypatch):
        monkeypatch.setattr(c, "main", mock.Mock(side_effect=_failure("HTTP 403: rate limit")))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert c.run([SRC]) == 1
        assert "HTTP 403: rate limit" in err.getvalue() and "run the same command again" in err.getvalue()
