#!/usr/bin/env python3
"""Copy the four SCJN release series of one repository into another, once.

`scjn.release` reads four series: `scjn-leyes`, `scjn-reglamentos`,
`scjn-lineamientos` and `scjn-tratados`. A release holds at most 1,000 assets,
so a series is a bare tag plus continuations (`scjn-reglamentos-2`, ...). A move
of the releases' owner copies every release byte for byte (title, body and each
asset) instead of re-crawling the SCJN, which takes days and would not
reproduce the published bytes. The copy decides nothing about what is safe to
publish: a human already published these releases (CLAUDE.md, "Data").

The source repository is required and has no default; the destination is this
repository. Run with --dry-run first: it lists both sides, the differences and
the `gh` commands it would run, and writes nothing to GitHub or to disk.

    ./scripts/copy_scjn_releases.py <owner>/<name> --dry-run
    ./scripts/copy_scjn_releases.py <owner>/<name> > scripts/scjn/release-copy.log 2>&1

Only `gh`, already authenticated with write access to the destination, is
needed. The downloads land in --outdir, one folder per tag (do not commit them).
Uploads go in batches, each retried with a growing pause (GitHub's secondary
rate limits answer 403/429 on bursts of uploads). A rerun is the resume: it
lists both sides again, recomputes the differences and does only what is left.
The script ends by listing the destination again and exits non-zero if any
asset is missing or differs, or a title or body differs.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

BASES = ("scjn-leyes", "scjn-reglamentos", "scjn-lineamientos", "scjn-tratados")
DEFAULT_DESTINATION = "legistlan/scjn"
#: The tag whose release is marked "latest": the corpus the package is named for.
LATEST_TAG = "scjn-leyes"
#: Same safety bound as `scjn.release._MAX_PARTES`: a series that never 404s must stop.
MAX_PARTS = 50
UPLOAD_ATTEMPTS = 5
RETRY_PAUSE = 60  # seconds; the pause before attempt k + 1 is RETRY_PAUSE * k


def gh(*args: str) -> subprocess.CompletedProcess:
    """Run `gh` with `args`; raise CalledProcessError on a non-zero exit.

    A list, never a shell: repository names and paths are not interpreted.
    """
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True)


def _is_not_found(exc: subprocess.CalledProcessError) -> bool:
    error = (exc.stderr or "") + (exc.stdout or "")
    return "404" in error or "Not Found" in error


def release_of(repo: str, tag: str) -> dict | None:
    """`{"id", "title", "body"}` of `repo`'s release `tag`, or None if it has none.

    `gh api` exits 1 with `HTTP 404` in stderr for a missing release, the normal
    state of a destination not copied to yet; any other failure is raised.
    """
    try:
        out = gh("api", f"repos/{repo}/releases/tags/{tag}").stdout
    except subprocess.CalledProcessError as exc:
        if _is_not_found(exc):
            return None
        raise
    data = json.loads(out)
    return {"id": data["id"], "title": data.get("name") or "", "body": data.get("body") or ""}


def series_tags(repo: str, base: str) -> list[str]:
    """`base`, `base-2`, `base-3`, ... while the release exists in `repo`.

    The rule of `scjn.release._tag_de_parte` (the bare tag is part 1, a part n
    after the first is `<base>-<n>`), restated here on purpose: the script must
    not import the package's private helper. A base whose bare tag is missing
    yields nothing.
    """
    tags = []
    for n in range(1, MAX_PARTS + 1):
        tag = base if n == 1 else f"{base}-{n}"
        if release_of(repo, tag) is None:
            break
        tags.append(tag)
    return tags


def assets_of(repo: str, release_id: int) -> dict[str, tuple[int, str | None]]:
    """Map every asset of a release to `(size, digest)`; `digest` may be None.

    Paginated: the `assets` array embedded in the release object is capped, and
    a release holds up to 1,000 assets. `gh api --paginate` prints one JSON
    array per page, one after another, so the output is decoded array by array.
    """
    out = gh("api", "--paginate", f"repos/{repo}/releases/{release_id}/assets?per_page=100").stdout
    decoder = json.JSONDecoder()
    assets = {}
    pos = 0
    while pos < len(out):
        while pos < len(out) and out[pos].isspace():
            pos += 1
        if pos >= len(out):
            break
        page, pos = decoder.raw_decode(out, pos)
        for asset in page:
            assets[asset["name"]] = (int(asset["size"]), asset.get("digest") or None)
    return assets


def differences(source: dict[str, tuple[int, str | None]],
                destination: dict[str, tuple[int, str | None]]) -> tuple[list[str], list[str]]:
    """Names missing from `destination`, and names that differ, both sorted.

    A name differs when the sizes differ, or when both sides report a digest and
    the digests differ (an old upload may have none: that side is ignored). An
    asset only in `destination` is not a difference: the copy never deletes.
    """
    missing = sorted(n for n in source if n not in destination)
    different = []
    for name in sorted(source):
        if name not in destination:
            continue
        (size, digest), (dsize, ddigest) = source[name], destination[name]
        if size != dsize or (digest and ddigest and digest != ddigest):
            different.append(name)
    return missing, different


def _same_text(a: str, b: str) -> bool:
    """Titles and bodies compare modulo the line endings GitHub normalises."""
    return a.replace("\r\n", "\n").strip() == b.replace("\r\n", "\n").strip()


def download(source: str, tag: str, outdir: Path, expected: dict[str, tuple[int, str | None]]) -> int:
    """Download the assets of `source`'s `tag` not already in `outdir` and check every size.

    Returns the number of files in `outdir` after the call. A file with the wrong
    size stops the run: the listing is the truth and a partial download is not.
    """
    outdir.mkdir(parents=True, exist_ok=True)

    def complete() -> bool:
        return all((outdir / n).is_file() and (outdir / n).stat().st_size == s
                   for n, (s, _) in expected.items())

    if not complete():
        for name, (size, _) in expected.items():  # a truncated file from a dead run: fetch it again
            path = outdir / name
            if path.is_file() and path.stat().st_size != size:
                path.unlink()
        # `gh release download` costs one API request per asset: a long series can meet
        # the hourly API rate limit mid-way (seen on a 1,000-asset release), so it is
        # retried like an upload; --skip-existing makes each attempt continue, not restart.
        retrying(lambda: gh("release", "download", tag, "-R", source, "-D", str(outdir),
                            "--skip-existing"), f"{tag}: download")
    for name, (size, _) in sorted(expected.items()):
        path = outdir / name
        if not path.is_file():
            raise SystemExit(f"{tag}: {name} was not downloaded")
        if path.stat().st_size != size:
            raise SystemExit(f"{tag}: {name} downloaded {path.stat().st_size} bytes, "
                             f"the listing says {size}")
    return len(expected)


def retrying(action, label: str) -> None:
    """Call `action()` up to UPLOAD_ATTEMPTS times, pausing RETRY_PAUSE * attempt between them."""
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            action()
            return
        except subprocess.CalledProcessError as exc:
            if attempt == UPLOAD_ATTEMPTS:
                raise
            pause = RETRY_PAUSE * attempt
            detail = (exc.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
            print(f"{label} failed (attempt {attempt}/{UPLOAD_ATTEMPTS}: {detail[0][:200]}); "
                  f"retrying in {pause} s", file=sys.stderr, flush=True)
            time.sleep(pause)


def upload_batch(destination: str, tag: str, files: list[Path]) -> None:
    """`gh release upload` one batch, retried with a growing pause; raise after the last attempt."""
    retrying(lambda: gh("release", "upload", tag, *map(str, files), "-R", destination, "--clobber"),
             f"{tag}: batch")


def copy_tag(source: str, destination: str, tag: str, outdir: Path, batch: int,
             dry_run: bool) -> None:
    """Bring one release of `destination` to equal `source`'s: create it, upload what is left."""
    src = release_of(source, tag)
    src_assets = assets_of(source, src["id"])
    dst = release_of(destination, tag)
    dst_assets = assets_of(destination, dst["id"]) if dst else {}
    missing, different = differences(src_assets, dst_assets)
    print(f"{tag}: source {len(src_assets)} assets, destination {len(dst_assets)}; "
          f"missing {len(missing)}, differing {len(different)}", flush=True)

    folder = outdir / tag
    notes = outdir / f"{tag}.body.md"  # beside the tag's folder, so it is never uploaded
    create = ["gh", "release", "create", tag, "-R", destination, "--target", "main",
              "--title", src["title"], "--notes-file", str(notes), "--latest=false"]
    todo = sorted(set(missing) | set(different))
    if dry_run:
        print(f"[dry-run] would download: gh release download {tag} -R {source} "
              f"-D {folder} --skip-existing")
        if dst is None:
            print("[dry-run] would create the release:", " ".join(create))
        elif not (_same_text(src["title"], dst["title"]) and _same_text(src["body"], dst["body"])):
            print(f"[dry-run] would edit the title and body of {tag} in {destination}")
        for i in range(0, len(todo), batch):
            print(f"[dry-run] would upload: gh release upload {tag} <{len(todo[i:i + batch])} "
                  f"files from {folder}> -R {destination} --clobber")
        return

    if todo:
        download(source, tag, folder, {n: src_assets[n] for n in todo})
    if dst is None:
        outdir.mkdir(parents=True, exist_ok=True)
        notes.write_text(src["body"], encoding="utf-8")
        gh(*create[1:])
        print(f"{tag}: release created in {destination}", flush=True)
    elif not (_same_text(src["title"], dst["title"]) and _same_text(src["body"], dst["body"])):
        outdir.mkdir(parents=True, exist_ok=True)
        notes.write_text(src["body"], encoding="utf-8")
        gh("release", "edit", tag, "-R", destination, "--title", src["title"],
           "--notes-file", str(notes))
        print(f"{tag}: title and body brought to the source's", flush=True)
    for i in range(0, len(todo), batch):
        files = [folder / n for n in todo[i:i + batch]]
        upload_batch(destination, tag, files)
        print(f"{tag}: {min(i + batch, len(todo))}/{len(todo)} uploaded", flush=True)


def verify(source: str, destination: str, tags: list[str]) -> tuple[int, int, bool]:
    """List both sides again; `(releases, assets, ok)`. Prints one line per tag."""
    ok, total = True, 0
    for tag in tags:
        src, dst = release_of(source, tag), release_of(destination, tag)
        if dst is None:
            print(f"{tag}: missing in {destination}", file=sys.stderr, flush=True)
            ok = False
            continue
        src_assets, dst_assets = assets_of(source, src["id"]), assets_of(destination, dst["id"])
        missing, different = differences(src_assets, dst_assets)
        if missing or different:
            print(f"{tag}: missing {missing[:5]}{'...' if len(missing) > 5 else ''} "
                  f"({len(missing)}), differing {different[:5]}"
                  f"{'...' if len(different) > 5 else ''} ({len(different)})",
                  file=sys.stderr, flush=True)
            ok = False
        if not _same_text(src["title"], dst["title"]):
            print(f"{tag}: title differs", file=sys.stderr, flush=True)
            ok = False
        if not _same_text(src["body"], dst["body"]):
            print(f"{tag}: body differs", file=sys.stderr, flush=True)
            ok = False
        total += len(src_assets)
        print(f"{tag}: {len(src_assets)} assets on each side", flush=True)
    return len(tags), total, ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="<owner>/<name> whose scjn-* releases are copied (required)")
    p.add_argument("--destination", default=DEFAULT_DESTINATION,
                   help="<owner>/<name> that receives them (default: %(default)s)")
    p.add_argument("--outdir", default="scripts/scjn/release-copy",
                   help="where the downloaded assets land, one folder per tag (default: %(default)s)")
    p.add_argument("--tag", action="append", default=[],
                   help="restrict the run to this tag (repeatable), for a resumed or partial run")
    p.add_argument("--batch", type=int, default=50,
                   help="assets per `gh release upload` call (default: %(default)s)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the listings, the differences and the commands; write nothing")
    args = p.parse_args(argv)
    if args.batch < 1:
        p.error("--batch must be at least 1")

    found = [t for base in BASES for t in series_tags(args.source, base)]
    if not found:
        sys.exit(f"{args.source} has none of the releases {', '.join(BASES)}")
    unknown = [t for t in args.tag if t not in found]
    if unknown:
        sys.exit(f"{args.source} has no release {', '.join(unknown)}; it has {', '.join(found)}")
    tags = [t for t in found if not args.tag or t in args.tag]
    print(f"tags in {args.source}: {', '.join(found)}", flush=True)
    print(f"copying to {args.destination}: {', '.join(tags)}", flush=True)

    outdir = Path(args.outdir)
    for tag in tags:
        copy_tag(args.source, args.destination, tag, outdir, args.batch, args.dry_run)
    if args.dry_run:
        if LATEST_TAG in tags:
            print(f"[dry-run] would run: gh release edit {LATEST_TAG} -R {args.destination} --latest")
        return 0

    if LATEST_TAG in tags:
        gh("release", "edit", LATEST_TAG, "-R", args.destination, "--latest")
    releases, assets, ok = verify(args.source, args.destination, tags)
    if not ok:
        print("copy NOT verified: see the lines above", file=sys.stderr, flush=True)
        return 1
    print(f"copy verified: {releases} releases, {assets} assets", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
