"""Prepare a verified, platform-matched update without touching the running app."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib import parse, request

from doubao_input.product import REPOSITORY_URL
from doubao_input.settings import config_dir

LIMIT = 512 * 1024 * 1024
PLUGIN_ID = "md.lifeos.doubao-say"


def installation(root=None):
    root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    marker = root / ".doubao-managed.json"
    if marker.is_file() and not marker.is_symlink():
        value = json.loads(marker.read_text())
        if value.get("id") == PLUGIN_ID and value.get("kind") in ("app", "plugin"):
            return root, "archive", value["kind"]
        raise ValueError("Invalid installation marker")
    if (root / ".git").exists():
        origin = subprocess.check_output(["git", "-C", str(root), "remote", "get-url", "origin"], text=True).strip()
        if origin not in (REPOSITORY_URL + ".git", REPOSITORY_URL, "git@github.com:quanru/doubao-say.git"):
            raise ValueError("Only the official repository supports in-app updates")
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
        if dirty:
            raise ValueError("Local changes exist. Commit or move them before updating")
        plugin = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy/plugins" / PLUGIN_ID
        return root, "git", "plugin" if root == plugin.resolve() else "app"
    raise ValueError("This installation must be updated using its package manager")


def asset_url(assets, name, tag):
    expected = f"{REPOSITORY_URL}/releases/download/{tag}/{name}"
    for asset in assets:
        if asset.get("name") == name and asset.get("browser_download_url") == expected:
            return expected
    raise ValueError(f"Release is missing {name}")


def download(url, destination, limit=LIMIT):
    if parse.urlparse(url).scheme != "https":
        raise ValueError("Updates require HTTPS")
    req = request.Request(url, headers={"User-Agent": "Doubao-Say-Updater"})
    size = 0
    with request.urlopen(req, timeout=30) as response, Path(destination).open("wb") as output:
        if parse.urlparse(response.geturl()).scheme != "https":
            raise ValueError("Insecure download redirect")
        while chunk := response.read(256 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("Update exceeds size limit")
            output.write(chunk)
    return Path(destination)


def checksum(text, name):
    matches = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].lstrip("*") == name:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
                raise ValueError("Invalid SHA-256")
            matches.append(fields[0].lower())
    if len(matches) != 1:
        raise ValueError("Missing or duplicate update checksum")
    return matches[0]


def extract(archive, destination):
    with tarfile.open(archive, "r:gz") as bundle:
        members = []
        size = 0
        for member in bundle:
            members.append(member); size += member.size
            if len(members) > 50_000 or size > 2 * LIMIT:
                raise ValueError("Invalid update archive size")
        if not members:
            raise ValueError("Empty update archive")
        for member in members:
            path = Path(member.name)
            if not path.parts or path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe update archive entry")
        roots = {Path(m.name).parts[0] for m in members}
        if len(roots) != 1:
            raise ValueError("Update must contain one bundle")
        if hasattr(tarfile, "data_filter"):
            bundle.extractall(destination, members=members, filter="data")
        else:
            bundle.extractall(destination, members=members)
    return Path(destination) / roots.pop()


def prepare(info, *, root=None, status=lambda _: None):
    tag = info.url.rsplit("/", 1)[-1]
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag) or tag.removeprefix("v") != info.version:
        raise ValueError("Invalid update release")
    target, route, kind = installation(root)
    base = config_dir() / "doubao-say" / "updates"
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="pending-", dir=base))
    try:
        plan = {"root": str(target), "route": route, "kind": kind, "tag": tag,
                "parent_pid": os.getpid(), "scratch": str(scratch), "python": sys.executable}
        metadata = scratch / "release.json"
        download(f"https://api.github.com/repos/quanru/doubao-say/releases/tags/{tag}", metadata, 1_000_000)
        release = json.loads(metadata.read_text())
        if release.get("tag_name") != tag or release.get("draft") or release.get("prerelease"):
            raise ValueError("Release changed or is not stable")
        if route == "git":
            status("Downloading release source…")
            repository = scratch / "release.git"
            subprocess.run(["git", "init", "--bare", str(repository)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repository), "fetch", "--depth=1", REPOSITORY_URL + ".git", f"refs/tags/{tag}"], check=True, timeout=120, capture_output=True)
            plan["git_source"] = str(repository)
            plan["revision"] = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "FETCH_HEAD^{commit}"], text=True).strip()
            project = subprocess.check_output(["git", "-C", str(repository), "show", plan["revision"] + ":pyproject.toml"], text=True)
            if tomllib.loads(project)["project"]["version"] != info.version:
                raise ValueError("Release source version does not match its tag")
            plan["previous"] = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            plan["branch"] = subprocess.check_output(["git", "-C", str(target), "symbolic-ref", "--quiet", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip() if subprocess.run(["git", "-C", str(target), "symbolic-ref", "--quiet", "HEAD"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 else ""
        else:
            data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
            config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            expected_root = config / "omarchy/plugins" / PLUGIN_ID if kind == "plugin" else data / "doubao-say/app"
            if target != expected_root.resolve():
                raise ValueError("Relocated installations must be updated using their package manager")
            status("Downloading update…")
            name = f"doubao-say-{info.version}-{kind}-linux-{platform.machine()}-{sys.implementation.cache_tag}.tar.gz"
            assets = release.get("assets", [])
            sums = download(asset_url(assets, "SHA256SUMS", tag), scratch / "SHA256SUMS", 100_000)
            archive = download(asset_url(assets, name, tag), scratch / name)
            with archive.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != checksum(sums.read_text(), name):
                raise ValueError("Update checksum mismatch")
            status("Verifying update…")
            payload = extract(archive, scratch / "unpacked")
            manifest = json.loads((payload / "bundle.json").read_text())
            expected = f"linux-{platform.machine()}-{sys.implementation.cache_tag}"
            if manifest.get("version") != info.version or manifest.get("kind") != kind or manifest.get("platform") != expected:
                raise ValueError("Update bundle does not match this installation")
            # Reuse the release installer's complete allowlist/hash validation.
            import importlib.util
            spec = importlib.util.spec_from_file_location("doubao_release_installer", payload / "install.py")
            installer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(installer)
            installer.verify_bundle(payload)
            plan["payload"] = str(payload)
        shutil.copy2(Path(__file__).with_name("update_helper.py"), scratch / "helper.py")
        (scratch / "plan.json").write_text(json.dumps(plan))
        return scratch
    except Exception:
        shutil.rmtree(scratch)
        raise


def launch(scratch):
    scratch = Path(scratch)
    log = (scratch / "install.log").open("ab")
    try:
        subprocess.Popen([sys.executable, str(scratch / "helper.py"), str(scratch / "plan.json")],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    finally:
        log.close()


def consume_result():
    base = config_dir() / "doubao-say" / "updates"
    records = sorted(base.glob("pending-*/result.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for record in records:
        if record.is_symlink() or record.stat().st_size > 16_384:
            continue
        try:
            value = json.loads(record.read_text())
            record.unlink()
            if isinstance(value, dict) and type(value.get("success")) is bool:
                return value
        except (OSError, ValueError):
            continue
    return None
