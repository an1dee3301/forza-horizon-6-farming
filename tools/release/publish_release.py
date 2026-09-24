"""Publish a verified archive to a GitHub release, failing closed on mismatches."""
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile


OWNER = "an1dee3301"
REPO = "forza-horizon-6-farming"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
REMOTE = f"https://github.com/{OWNER}/{REPO}.git"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=Path(__file__).resolve().parents[2],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def get_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        output = subprocess.check_output(["gh", "auth", "token"], stderr=subprocess.DEVNULL,
                                         text=True, timeout=10).strip()
        if output:
            return output
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        output = subprocess.check_output(["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n", cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        output = ""
    fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return fields.get("password")


def api_request(url, token, method="GET", data=None, content_type="application/json", accept="application/vnd.github+json"):
    headers = {"Accept": accept, "Authorization": f"Bearer {token}",
               "User-Agent": "fh6-auto-release-publisher",
               "X-GitHub-Api-Version": "2022-11-28"}
    if data is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=180) as response:
        body = response.read()
        return response.status, response.headers, body


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def asset_digest(asset, token):
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    # Older GitHub API responses may omit digest. Verify the published bytes.
    _, _, content = api_request(f"{API}/releases/assets/{asset['id']}", token,
                                accept="application/octet-stream")
    if content[:1] == b"{" and b"browser_download_url" in content:
        raise RuntimeError("GitHub did not return downloadable asset bytes for verification")
    return hashlib.sha256(content).hexdigest()


def verify_assets(release, assets, token):
    existing = {item["name"]: item for item in release.get("assets", [])}
    for path in assets:
        asset = existing.get(path.name)
        if not asset:
            raise RuntimeError(f"Release is missing asset {path.name}")
        expected = digest_file(path)
        if asset.get("size") != path.stat().st_size or asset_digest(asset, token) != expected:
            raise RuntimeError(f"Release asset differs from local verified file: {path.name}")


def verify_local_bundle(version, head, assets):
    archive, sidecar, manifest_path = assets
    expected_sidecar = f"{digest_file(archive)}  {archive.name}"
    if sidecar.read_text(encoding="ascii").strip() != expected_sidecar:
        raise SystemExit("Archive SHA-256 sidecar does not match the ZIP")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version or manifest.get("source_commit") != head:
        raise SystemExit("Release manifest does not match the requested version and source commit")
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip():
            raise SystemExit("Archive ZIP CRC validation failed")
        embedded_name = next((n for n in zf.namelist()
                              if n.endswith("/release-manifest.json")), None)
        if not embedded_name:
            raise SystemExit("Archive has no embedded release manifest")
        embedded = json.loads(zf.read(embedded_name))
        if embedded != manifest:
            raise SystemExit("Embedded and sidecar manifests differ")
        archive_root = embedded_name.split("/", 1)[0]
        expected_names = {embedded_name} | {
            archive_root + "/" + item["path"] for item in manifest.get("files", [])}
        if set(zf.namelist()) != expected_names:
            raise SystemExit("ZIP contents differ from the manifest")
        for item in manifest.get("files", []):
            name = archive_root + "/" + item["path"]
            data = zf.read(name)
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise SystemExit(f"Manifest file verification failed: {item['path']}")
        denied_parts = {"runs", "purchases", "localstate", "private", "accounts", ".venv"}
        denied_suffixes = {".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm", ".db",
                           ".db-wal", ".db-shm", ".dpapi", ".mp4", ".pem", ".key", ".pfx", ".p12", ".log"}
        if any(({part.casefold() for part in PurePosixPath(name).parts[1:]} & denied_parts) or
               PurePosixPath(name).suffix.casefold() in denied_suffixes or
               PurePosixPath(name).name.casefold().startswith(".env")
               for name in zf.namelist() if name != embedded_name):
            raise SystemExit("Archive contains forbidden local/account data")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="release version, for example 2.1.0")
    parser.add_argument("assets", nargs=3, type=Path,
                        help="archive ZIP, SHA-256 sidecar, manifest JSON")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("Version must contain only digits and dots, such as 2.1.0")
    tag = "v" + version
    root = Path(__file__).resolve().parents[2]
    notes = root / f"RELEASE-NOTES-{tag}.md"
    assets = [p.resolve() for p in args.assets]
    if not notes.is_file() or any(not p.is_file() for p in assets):
        raise SystemExit("Release notes and all three local assets must exist")
    if (root / "VERSION").read_text(encoding="utf-8").strip() != version:
        raise SystemExit("VERSION file does not match requested release")
    if git("remote", "get-url", "origin") != REMOTE:
        raise SystemExit("Refusing publication: origin is not the expected public repository")
    head = git("rev-parse", "HEAD")
    if git("rev-parse", f"refs/tags/{tag}^{{commit}}") != head:
        raise SystemExit(f"Refusing publication: {tag} must point to the checked-out commit")
    remote_tags = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    if not remote_tags:
        raise SystemExit(f"Refusing publication: push {tag} to origin first")
    remote_tag_rows = [line.split() for line in remote_tags.splitlines() if line.strip()]
    remote_commit = next((sha for sha, ref in remote_tag_rows if ref == f"refs/tags/{tag}^{{}}"),
                         next((sha for sha, ref in remote_tag_rows if ref == f"refs/tags/{tag}"), None))
    if remote_commit != head:
        raise SystemExit(f"Refusing publication: remote {tag} does not point to checked-out commit")
    token = get_token()
    if not token:
        raise SystemExit("No GitHub token is available through GH_TOKEN, gh auth, or the Git credential helper")
    verify_local_bundle(version, head, assets)

    url = f"{API}/releases/tags/{tag}"
    try:
        _, _, body = api_request(url, token)
        release = json.loads(body)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        payload = json.dumps({"tag_name": tag, "target_commitish": head,
            "name": f"FH6 Auto {tag}", "body": notes.read_text(encoding="utf-8"),
            "draft": True, "prerelease": False}).encode()
        _, _, body = api_request(f"{API}/releases", token, method="POST", data=payload)
        release = json.loads(body)

    if not release.get("draft"):
        if release.get("tag_name") != tag or release.get("body", "").strip() != notes.read_text(encoding="utf-8").strip():
            raise SystemExit("Existing published release metadata differs; refusing to treat it as this release")
        verify_assets(release, assets, token)
        print(f"Already published and verified: {release['html_url']}")
        return

    if release.get("tag_name") != tag or release.get("body", "").strip() != notes.read_text(encoding="utf-8").strip():
        raise SystemExit("Existing draft release metadata differs; refusing to publish it")

    current = {asset["name"]: asset for asset in release.get("assets", [])}
    upload_base = release["upload_url"].split("{", 1)[0]
    for path in assets:
        if path.name in current:
            if current[path.name].get("size") != path.stat().st_size or \
               asset_digest(current[path.name], token) != digest_file(path):
                raise SystemExit(f"Draft asset {path.name} exists with different content; refusing overwrite")
            continue
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        query = urllib.parse.urlencode({"name": path.name})
        _, _, body = api_request(upload_base + "?" + query, token, method="POST",
                                 data=path.read_bytes(), content_type=mime,
                                 accept="application/vnd.github+json")
        current[path.name] = json.loads(body)

    _, _, body = api_request(f"{API}/releases/{release['id']}", token)
    release = json.loads(body)
    verify_assets(release, assets, token)
    patch = json.dumps({"draft": False}).encode()
    _, _, body = api_request(f"{API}/releases/{release['id']}", token, method="PATCH", data=patch)
    release = json.loads(body)
    if release.get("draft"):
        raise RuntimeError("GitHub release remained a draft after publish request")
    _, _, body = api_request(f"{API}/releases/{release['id']}", token)
    release = json.loads(body)
    verify_assets(release, assets, token)
    print(f"Published and verified: {release['html_url']}")
    for asset in release.get("assets", []):
        if asset["name"] in {p.name for p in assets}:
            print(asset["browser_download_url"])


if __name__ == "__main__":
    main()
