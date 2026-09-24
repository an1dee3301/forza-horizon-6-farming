"""Build a deterministic, source-commit-bound Windows release archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
EPOCH = (2020, 1, 1, 0, 0, 0)
DENY_PARTS = {".git", ".venv", "runs", "purchases", "localstate", "failures",
              "account", "accounts", "private"}
DENY_SUFFIXES = {".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm", ".db",
                 ".db-wal", ".db-shm", ".dpapi", ".mp4", ".pem", ".key",
                 ".pfx", ".p12", ".log"}
DENY_NAMES = {".env", "discord_webhook.dpapi", "discord_reports.json"}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def is_allowed(path):
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    return not (parts & DENY_PARTS or name in DENY_NAMES or name.startswith(".env.") or
                path.suffix.casefold() in DENY_SUFFIXES)


def tracked_paths():
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [PurePosixPath(p.decode("utf-8")) for p in raw.split(b"\0") if p]
    return sorted((path for path in paths if is_allowed(path)),
                  key=lambda p: p.as_posix().casefold())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="release version, for example 2.1.0")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    tag = "v" + version
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("Version must contain only digits and dots, such as 2.1.0")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("Refusing release build: source tree is not clean")
    commit = git("rev-parse", "HEAD")
    tagged = git("rev-parse", f"refs/tags/{tag}^{{commit}}")
    if tagged != commit:
        raise SystemExit(f"Refusing release build: {tag} must point to HEAD ({commit})")
    files = tracked_paths()
    required = {"FH6 Auto.pyw", "Setup FH6 Auto.cmd", "Start FH6 Auto.cmd",
                "fh6/controller.py", "fh6/wheelspin_catalog.py",
                "requirements-lock-win-py312.txt", "VERSION", f"RELEASE-NOTES-{tag}.md"}
    names = {p.as_posix() for p in files}
    missing = sorted(required - names)
    if missing:
        raise SystemExit("Refusing incomplete build; missing " + ", ".join(missing))
    if not files:
        raise SystemExit("No tracked release files found")
    if (ROOT / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise SystemExit("VERSION file does not match requested release")

    root_name = f"FH6-Auto-{version}"
    payloads = []
    entries = []
    for rel in files:
        source = ROOT.joinpath(*rel.parts)
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"Unsupported or missing tracked path: {rel}")
        data = source.read_bytes()
        name = f"{root_name}/{rel.as_posix()}"
        payloads.append((name, data))
        entries.append({"path": rel.as_posix(), "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"version": version, "tag": tag, "source_commit": commit,
                "python": "3.12", "files": entries}
    payloads.append((f"{root_name}/release-manifest.json",
                     (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"FH6-Auto-v{version}-Windows.zip"
    temp = archive.with_suffix(".zip.tmp")
    if temp.exists():
        temp.unlink()
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, strict_timestamps=True) as zf:
        for name, data in sorted(payloads, key=lambda pair: pair[0].casefold()):
            info = zipfile.ZipInfo(name, EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temp, archive)
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            archive.unlink(missing_ok=True)
            raise SystemExit(f"ZIP CRC validation failed at {bad}")
        actual = set(zf.namelist())
        expected = {name for name, _ in payloads}
        if actual != expected:
            archive.unlink(missing_ok=True)
            raise SystemExit("ZIP membership verification failed")
        forbidden = [n for n in actual if any(part.casefold() in DENY_PARTS
                                               for part in PurePosixPath(n).parts)]
        if forbidden:
            archive.unlink(missing_ok=True)
            raise SystemExit("Forbidden local runtime data found in archive")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="ascii", newline="\n")
    manifest_path = archive.with_suffix(archive.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
    print(f"Built {archive}\nSHA256 {digest}\nSource {commit}\nFiles {len(files)}")


if __name__ == "__main__":
    main()
