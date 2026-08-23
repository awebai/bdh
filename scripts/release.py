#!/usr/bin/env python3
"""Build, verify, and publish bdh releases without a hosted runner."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


REPOSITORY = "awebai/bdh"
MODULE = "github.com/awebai/bdh"
PLATFORMS = (
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("windows", "amd64"),
    ("windows", "arm64"),
)
VERSION_RE = re.compile(r"^(?:v)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
MINIMUM_VERSION = (0, 12, 0)


class ReleaseError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ReleaseError(f"command failed ({' '.join(args)}): {detail}")
    return (result.stdout or "").strip()


def normalize_version(value: str) -> tuple[str, str]:
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ReleaseError(f"invalid stable release version: {value!r} (expected X.Y.Z or vX.Y.Z)")
    if tuple(int(part) for part in match.groups()) < MINIMUM_VERSION:
        raise ReleaseError("canonical awebai/bdh releases start at v0.12.0")
    version = value.removeprefix("v")
    return version, f"v{version}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def asset_name(version: str, goos: str, goarch: str) -> str:
    suffix = "zip" if goos == "windows" else "tar.gz"
    return f"bdh_{version}_{goos}_{goarch}.{suffix}"


def stable_tar(archive: Path, files: list[tuple[Path, str, int]], epoch: int) -> None:
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for source, name, mode in files:
                    info = tarfile.TarInfo(name)
                    info.size = source.stat().st_size
                    info.mode = mode
                    info.mtime = epoch
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with source.open("rb") as content:
                        bundle.addfile(info, content)


def stable_zip(archive: Path, files: list[tuple[Path, str, int]], epoch: int) -> None:
    timestamp = dt.datetime.fromtimestamp(max(epoch, 315532800), tz=dt.timezone.utc)
    date_time = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source, name, mode in files:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = mode << 16
            bundle.writestr(info, source.read_bytes())


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "go.mod").is_file():
        raise ReleaseError("release script is not inside the bdh repository")
    return root


def require_canonical_origin(root: Path) -> None:
    accepted = (
        "https://github.com/awebai/bdh.git",
        "git@github.com:awebai/bdh.git",
        "ssh://git@github.com/awebai/bdh.git",
    )
    fetch_urls = run(["git", "remote", "get-url", "--all", "origin"], cwd=root).splitlines()
    push_urls = run(["git", "remote", "get-url", "--push", "--all", "origin"], cwd=root).splitlines()
    if not fetch_urls or not push_urls or any(url not in accepted for url in (*fetch_urls, *push_urls)):
        raise ReleaseError(
            f"all origin fetch/push URLs must target github.com/{REPOSITORY}; "
            f"found fetch={fetch_urls!r}, push={push_urls!r}"
        )


def require_clean(root: Path) -> None:
    status = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root)
    if status:
        raise ReleaseError("release builds require a clean worktree:\n" + status)


def build_release(root: Path, version_input: str, stage_arg: str | None) -> Path:
    version, tag = normalize_version(version_input)
    require_canonical_origin(root)
    require_clean(root)

    source_sha = run(["git", "rev-parse", "HEAD^{commit}"], cwd=root)
    source_short = source_sha[:12]
    source_epoch = int(run(["git", "show", "-s", "--format=%ct", source_sha], cwd=root))
    source_date = run(["git", "show", "-s", "--format=%cI", source_sha], cwd=root)
    go_version = run(["go", "version"], cwd=root)

    stage = (root / (stage_arg or f".release-stage/{tag}")).resolve()
    release_parent = (root / ".release-stage").resolve()
    if stage == release_parent or release_parent not in stage.parents:
        raise ReleaseError(f"stage must be a child of {release_parent}")
    if stage.exists():
        raise ReleaseError(f"stage already exists (build-once guard): {stage}")
    stage.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{tag}-", dir=stage.parent))

    try:
        assets: list[dict[str, object]] = []
        for goos, goarch in PLATFORMS:
            binary_name = "bdh.exe" if goos == "windows" else "bdh"
            binary = temporary / f"{goos}-{goarch}-{binary_name}"
            env = os.environ.copy()
            env.update({"CGO_ENABLED": "0", "GOOS": goos, "GOARCH": goarch})
            ldflags = f"-s -w -X main.version={version} -X main.commit={source_short} -X main.date={source_date}"
            run(
                ["go", "build", "-trimpath", "-buildvcs=true", "-ldflags", ldflags, "-o", str(binary), "./cmd/bdh"],
                cwd=root,
                env=env,
            )

            name = asset_name(version, goos, goarch)
            archive = temporary / name
            files = [
                (binary, binary_name, 0o755),
                (root / "LICENSE", "LICENSE", 0o644),
                (root / "README.md", "README.md", 0o644),
            ]
            if goos == "windows":
                stable_zip(archive, files, source_epoch)
            else:
                stable_tar(archive, files, source_epoch)
            binary.unlink()
            assets.append(
                {
                    "name": name,
                    "goos": goos,
                    "goarch": goarch,
                    "sha256": sha256(archive),
                    "size": archive.stat().st_size,
                }
            )

        checksum_lines = [f"{item['sha256']}  {item['name']}" for item in assets]
        (temporary / "checksums.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        receipt = {
            "format_version": 1,
            "repository": REPOSITORY,
            "module": MODULE,
            "version": version,
            "tag": tag,
            "source_sha": source_sha,
            "source_date": source_date,
            "source_tree_clean": True,
            "builder": go_version,
            "assets": assets,
        }
        (temporary / "release-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.rename(stage)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    verify_stage(root, stage)
    print(f"staged {tag} from {source_sha} at {stage}")
    return stage


def archive_members(path: Path) -> list[str]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as bundle:
            return bundle.namelist()
    with tarfile.open(path, "r:gz") as bundle:
        return bundle.getnames()


def extract_binary(path: Path, destination: Path) -> Path:
    binary_name = "bdh.exe" if path.suffix == ".zip" else "bdh"
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as bundle:
            destination.write_bytes(bundle.read(binary_name))
    else:
        with tarfile.open(path, "r:gz") as bundle:
            member = bundle.getmember(binary_name)
            stream = bundle.extractfile(member)
            if stream is None:
                raise ReleaseError(f"cannot read {binary_name} from {path.name}")
            destination.write_bytes(stream.read())
    destination.chmod(0o755)
    return destination


def verify_binary_metadata(
    root: Path,
    archive: Path,
    source_sha: str,
    source_date: str,
    version: str,
    goos: str,
    goarch: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="bdh-release-verify-") as directory:
        binary = extract_binary(archive, Path(directory) / ("bdh.exe" if archive.suffix == ".zip" else "bdh"))
        metadata = run(["go", "version", "-m", str(binary)], cwd=root)
        binary_bytes = binary.read_bytes()
    required = (
        f"path\t{MODULE}/cmd/bdh",
        f"vcs.revision={source_sha}",
        "vcs.modified=false",
        f"GOOS={goos}",
        f"GOARCH={goarch}",
        "CGO_ENABLED=0",
    )
    missing = [item for item in required if item not in metadata]
    if missing:
        raise ReleaseError(f"{archive.name} has incomplete Go build metadata: {', '.join(missing)}")
    embedded = (version, source_sha[:12], source_date)
    missing_values = [value for value in embedded if value.encode("utf-8") not in binary_bytes]
    if missing_values:
        raise ReleaseError(f"{archive.name} lacks injected release values: {', '.join(missing_values)}")


def verify_stage(root: Path, stage: Path) -> dict[str, object]:
    receipt_path = stage / "release-receipt.json"
    checksums_path = stage / "checksums.txt"
    if not receipt_path.is_file() or not checksums_path.is_file():
        raise ReleaseError(f"stage lacks release-receipt.json or checksums.txt: {stage}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("format_version") != 1:
        raise ReleaseError("unsupported or missing release receipt format_version")
    if receipt.get("repository") != REPOSITORY or receipt.get("module") != MODULE:
        raise ReleaseError("receipt does not name the canonical repository and module")
    version, tag = normalize_version(str(receipt.get("version", "")))
    if receipt.get("tag") != tag or receipt.get("source_tree_clean") is not True:
        raise ReleaseError("receipt tag or source cleanliness assertion is invalid")
    source_sha = str(receipt.get("source_sha", ""))
    source_date = str(receipt.get("source_date", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ReleaseError("receipt source_sha is not a full Git commit id")
    actual_source_date = run(["git", "show", "-s", "--format=%cI", f"{source_sha}^{{commit}}"], cwd=root)
    if source_date != actual_source_date:
        raise ReleaseError("receipt source_date does not match its Git commit")

    expected_assets = {asset_name(version, goos, goarch): (goos, goarch) for goos, goarch in PLATFORMS}
    assets = receipt.get("assets")
    if not isinstance(assets, list) or len(assets) != len(expected_assets) or not all(isinstance(item, dict) for item in assets):
        raise ReleaseError("receipt does not contain the exact supported platform set")
    names = [str(item.get("name", "")) for item in assets]
    if len(set(names)) != len(names) or set(names) != set(expected_assets):
        raise ReleaseError("receipt contains missing, duplicate, or unexpected assets")
    checksum_lines: list[str] = []
    for item in assets:
        name = str(item["name"])
        goos, goarch = expected_assets[name]
        if item.get("goos") != goos or item.get("goarch") != goarch:
            raise ReleaseError(f"receipt platform fields do not match {name}")
        path = stage / name
        if not path.is_file():
            raise ReleaseError(f"missing staged asset: {name}")
        actual_hash = sha256(path)
        if item.get("sha256") != actual_hash or item.get("size") != path.stat().st_size:
            raise ReleaseError(f"receipt mismatch for {name}")
        binary_name = "bdh.exe" if name.endswith(".zip") else "bdh"
        if archive_members(path) != [binary_name, "LICENSE", "README.md"]:
            raise ReleaseError(f"unexpected archive contents in {name}")
        verify_binary_metadata(root, path, source_sha, source_date, version, goos, goarch)
        checksum_lines.append(f"{actual_hash}  {name}")
    expected_checksums = "\n".join(checksum_lines) + "\n"
    if checksums_path.read_text(encoding="utf-8") != expected_checksums:
        raise ReleaseError("checksums.txt does not exactly match the staged assets")
    print(f"verified {tag}: {len(assets)} platform archives from {source_sha}")
    return receipt


def remote_tag_sha(root: Path, tag: str) -> str | None:
    output = run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"], cwd=root
    )
    if not output:
        return None
    entries = {ref: sha for sha, ref in (line.split() for line in output.splitlines())}
    return entries.get(f"refs/tags/{tag}^{{}}") or entries.get(f"refs/tags/{tag}")


def release_state(root: Path, tag: str) -> dict[str, object] | None:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", REPOSITORY, "--json", "tagName,isDraft,isPrerelease,assets"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    if "release not found" in result.stderr.lower():
        return None
    raise ReleaseError(f"checking existing release state failed: {result.stderr.strip()}")


def release_asset_names(state: dict[str, object]) -> set[str]:
    assets = state.get("assets")
    if not isinstance(assets, list) or not all(isinstance(asset, dict) for asset in assets):
        raise ReleaseError("GitHub release returned an invalid assets list")
    names = [str(asset.get("name", "")) for asset in assets]
    if "" in names or len(names) != len(set(names)):
        raise ReleaseError("GitHub release returned empty or duplicate asset names")
    return set(names)


def publication_mode(state: dict[str, object] | None, tag: str, expected_assets: set[str]) -> str:
    if state is None:
        return "create"
    if (
        state.get("tagName") != tag
        or not isinstance(state.get("isDraft"), bool)
        or not isinstance(state.get("isPrerelease"), bool)
    ):
        raise ReleaseError("GitHub release returned invalid identity or publication state")
    existing_assets = release_asset_names(state)
    if not existing_assets.issubset(expected_assets):
        raise ReleaseError(f"release {tag} has unexpected assets; refusing to replace them")
    if state["isDraft"] is False and state["isPrerelease"] is False:
        if existing_assets != expected_assets:
            raise ReleaseError(f"public release {tag} is incomplete; refusing to mutate it")
        return "verify"
    return "resume"


def verify_remote_assets(root: Path, tag: str, paths: list[Path]) -> None:
    with tempfile.TemporaryDirectory(prefix="bdh-release-download-") as directory:
        download_dir = Path(directory)
        for path in paths:
            run(
                ["gh", "release", "download", tag, "--repo", REPOSITORY, "--pattern", path.name, "--dir", str(download_dir)],
                cwd=root,
            )
            downloaded = download_dir / path.name
            if not downloaded.is_file() or sha256(downloaded) != sha256(path):
                raise ReleaseError(f"published asset hash mismatch: {path.name}")
            downloaded.unlink()


def publish_release(root: Path, stage: Path, confirmation: str) -> None:
    require_canonical_origin(root)
    receipt = verify_stage(root, stage)
    tag = str(receipt["tag"])
    source_sha = str(receipt["source_sha"])
    expected_confirmation = f"{REPOSITORY}@{tag}"
    if confirmation != expected_confirmation:
        raise ReleaseError(f"publish confirmation must be exactly {expected_confirmation!r}")

    run(["gh", "repo", "view", REPOSITORY, "--json", "nameWithOwner"], cwd=root)
    run(["git", "fetch", "origin", "main"], cwd=root)
    run(["git", "merge-base", "--is-ancestor", source_sha, "origin/main"], cwd=root)
    existing_tag = remote_tag_sha(root, tag)
    if existing_tag is None:
        run(["git", "push", "origin", f"{source_sha}:refs/tags/{tag}"], cwd=root, capture=False)
        existing_tag = remote_tag_sha(root, tag)
    if existing_tag != source_sha:
        raise ReleaseError(f"remote {tag} points to {existing_tag}, expected {source_sha}")

    upload_paths = [stage / str(item["name"]) for item in receipt["assets"]]
    upload_paths += [stage / "checksums.txt", stage / "release-receipt.json"]
    expected_remote_assets = {path.name for path in upload_paths}
    state = release_state(root, tag)
    mode = publication_mode(state, tag, expected_remote_assets)
    if mode == "create":
        notes = f"bdh {tag}\n\nSource: {source_sha}\n\nSee release-receipt.json for the build receipt."
        run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                REPOSITORY,
                "--verify-tag",
                "--draft",
                "--title",
                tag,
                "--notes",
                notes,
            ],
            cwd=root,
            capture=False,
        )
    elif mode == "verify":
        verify_remote_assets(root, tag, upload_paths)
        print(f"already published and verified https://github.com/{REPOSITORY}/releases/tag/{tag}")
        return
    else:
        run(
            ["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=true", "--prerelease=false"],
            cwd=root,
            capture=False,
        )

    for path in upload_paths:
        run(["gh", "release", "upload", tag, str(path), "--repo", REPOSITORY, "--clobber"], cwd=root, capture=False)

    state = release_state(root, tag)
    if state is None or release_asset_names(state) != expected_remote_assets:
        raise ReleaseError(f"draft release {tag} does not contain the exact staged asset set")
    verify_remote_assets(root, tag, upload_paths)
    run(
        ["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--prerelease=false"],
        cwd=root,
        capture=False,
    )
    state = release_state(root, tag)
    if (
        state is None
        or state.get("isDraft") is not False
        or state.get("isPrerelease") is not False
        or state.get("tagName") != tag
        or release_asset_names(state) != expected_remote_assets
    ):
        raise ReleaseError(f"release {tag} is not public and stable after create/resume: {state}")
    print(f"published and verified https://github.com/{REPOSITORY}/releases/tag/{tag}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build all platform artifacts into a new immutable stage")
    build.add_argument("--version", required=True)
    build.add_argument("--stage")
    verify = subparsers.add_parser("verify", help="verify a previously built stage")
    verify.add_argument("--stage", required=True)
    publish = subparsers.add_parser("publish", help="publish and download-verify a stage")
    publish.add_argument("--stage", required=True)
    publish.add_argument("--confirm", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        root = repository_root()
        if args.command == "build":
            build_release(root, args.version, args.stage)
        elif args.command == "verify":
            verify_stage(root, (root / args.stage).resolve())
        else:
            publish_release(root, (root / args.stage).resolve(), args.confirm)
        return 0
    except (ReleaseError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"release error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
