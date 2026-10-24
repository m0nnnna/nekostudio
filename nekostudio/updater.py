"""nekostudio-update: update this install in place. Standard library only (it replaces the package it lives in).

Run through the nekostudio-update (Linux) / nekostudio-update.bat (Windows) wrappers; see --help.
Your data (data/, models, settings) and the Python envs are never touched; setup re-runs only when the
requirements or setup scripts changed. A git checkout is updated with git; anything else (a release
download) by swapping in the new files, keeping the old ones in .previous/ until the next update.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "m0nnnna/nekostudio"
# Never moved or replaced: user data, envs, the trainer checkout, git metadata, the updater's own dirs.
KEEP = {"data", ".venv", ".venv-train", ".uv-cache", "vendor", ".git", ".previous", ".update-new", "VERSION", "update-source"}
SETUP_INPUTS = ("requirements.txt", "requirements-train.txt", "setup.sh", "setup.ps1", "nekoenv.sh", "nekoenv.ps1")
WIN = os.name == "nt"


class Fail(Exception):
    pass


def say(msg: str):
    print(("== " if WIN else "\033[1;36m== ") + msg + ("" if WIN else "\033[0m"), flush=True)


def repo_name() -> str:
    try:
        for line in (ROOT / "update-source").read_text("utf-8").splitlines():
            line = line.split("#")[0].strip()
            if re.fullmatch(r"[\w.-]+/[\w.-]+", line):
                return line
    except OSError:
        pass
    return DEFAULT_REPO


def api(path: str):
    req = urllib.request.Request("https://api.github.com/" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "nekostudio-update"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Fail(f"not found on GitHub: {path} (no releases yet, wrong branch, or a private repo)") from None
        raise Fail(f"couldn't reach GitHub ({e})") from None
    except Exception as e:  # noqa: BLE001 - any network/HTTP error means "couldn't tell"
        raise Fail(f"couldn't reach GitHub ({e})") from None


def git(*args: str, check=True) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def is_git() -> bool:
    return (ROOT / ".git").exists() and shutil.which("git") is not None


def package_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "nekostudio" / "__init__.py").read_text("utf-8"))
    return "v" + m.group(1) if m else "v0"


def installed() -> str:
    """v0.1.0 (a release), v0.1.0-3-gabc1234 (3 commits past it, from --edge), or plain v0.1.0 for a fresh download."""
    if is_git():
        return git("describe", "--tags", "--always", "--dirty", check=False) or package_version()
    try:
        return (ROOT / "VERSION").read_text("utf-8").strip() or package_version()
    except OSError:
        return package_version()


def semver(tag: str):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def installed_commit(ver: str, repo: str) -> str:
    if ver.endswith("-dirty"):
        return ""
    m = re.search(r"-g([0-9a-f]{7,40})$", ver)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9a-f]{7,40}", ver):
        return ver
    try:
        ref = api(f"repos/{repo}/git/ref/tags/{ver}")["object"]
        return api(f"repos/{repo}/git/tags/{ref['sha']}")["object"]["sha"] if ref["type"] == "tag" else ref["sha"]
    except (Fail, KeyError, TypeError):
        return ""


def setup_hash() -> str:
    h = hashlib.sha1()
    for n in SETUP_INPUTS:
        p = ROOT / n
        h.update(n.encode() + (p.read_bytes() if p.exists() else b""))
    return h.hexdigest()


def server_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:7860/api/status", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ask(question: str, yes: bool):
    if yes:
        return
    if not sys.stdin.isatty():
        raise Fail(f'nothing to answer "{question}" (not a terminal): add --yes')
    if input(question + " [Y/n] ").strip().lower() in ("n", "no"):
        raise SystemExit(1)


def download(repo: str, ref: str) -> bytes:
    """The source tarball of a tag or commit, one plain HTTP stream."""
    url = f"https://codeload.github.com/{repo}/tar.gz/{ref}"
    req = urllib.request.Request(url, headers={"User-Agent": "nekostudio-update", "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        raise Fail(f"download of {url} failed ({e})") from None


def swap_in(blob: bytes, version: str):
    """Extract next to the install (same drive: the moves are renames, also on a share), park the old
    files in .previous/, move the new ones in. Any failure puts the old files back."""
    stage, prev = ROOT / ".update-new", ROOT / ".previous"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(stage, filter="data")
        else:
            for m in tf.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts or not (m.isfile() or m.isdir()):
                    raise Fail(f"unsafe path in the download: {m.name}")
            tf.extractall(stage)
    tops = list(stage.iterdir())
    if len(tops) != 1 or not (tops[0] / "nekostudio" / "__init__.py").exists():
        raise Fail("the download doesn't look like NekoStudio")
    new = tops[0]
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir()
    moved: list[str] = []
    placed: list[str] = []
    try:
        for p in ROOT.iterdir():
            if p.name not in KEEP:
                p.rename(prev / p.name)
                moved.append(p.name)
        for p in new.iterdir():
            if p.name not in KEEP:
                p.rename(ROOT / p.name)
                placed.append(p.name)
    except OSError as e:
        for n in placed:
            target = ROOT / n
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        for n in moved:
            (prev / n).rename(ROOT / n)
        raise Fail(f"couldn't replace the files ({e}); is NekoStudio still running? Nothing was changed") from None
    (ROOT / "VERSION").write_text(version + "\n", "utf-8")
    shutil.rmtree(stage, ignore_errors=True)


def run_setup(train: bool):
    if WIN:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "setup.ps1")]
        cmd += [] if train else ["-NoTrain"]
    else:
        cmd = ["bash", str(ROOT / "setup.sh")] + ([] if train else ["--no-train"])
    say("Requirements or setup changed: running setup again")
    if subprocess.run(cmd, cwd=str(ROOT)).returncode != 0:
        raise Fail("setup failed; the new files are in place, fix the error above and run setup again")


def trainer_installed() -> bool:
    env = Path(os.environ.get("NEKOSTUDIO_ENV") or ROOT)
    return (env / ".venv-train").exists()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nekostudio-update", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Update NekoStudio.\n\n"
                                 "  nekostudio-update          install the newest release\n"
                                 "  nekostudio-update --edge   install the newest commit of main (test/edge PCs)\n"
                                 "  --check                    only say whether there is something newer:\n"
                                 "                             exit 0 = up to date, 10 = an update is waiting, 1 = couldn't tell",
                                 epilog="Your data/, models, settings and Python envs are kept. Old files stay in "
                                        ".previous/ until the next update. Restart NekoStudio afterwards.")
    ap.add_argument("--edge", action="store_true", help="follow the newest commit instead of releases")
    ap.add_argument("--check", action="store_true", help="only check, change nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="don't ask before installing")
    ap.add_argument("--branch", default="main", help="--edge: follow this branch (default main)")
    ap.add_argument("--force", action="store_true", help="reinstall even when up to date; re-run setup")
    a = ap.parse_args(argv)

    repo, have = repo_name(), installed()
    if a.edge:
        try:
            want = api(f"repos/{repo}/commits/{a.branch}")["sha"]
        except (KeyError, TypeError):
            raise Fail(f"{repo} has no branch {a.branch}") from None
        have_sha = installed_commit(have, repo)
        if have_sha and want.startswith(have_sha) and not a.force:
            print(f"NekoStudio {have} is the newest commit on {repo} {a.branch}.")
            return 0
        print(f"{repo} {a.branch} is at {want[:7]} (installed: {have}).")
        target, label = want, want[:7]
    else:
        rel = api(f"repos/{repo}/releases/latest")
        tag = rel.get("tag_name") if isinstance(rel, dict) else None
        if not tag:
            raise Fail(f"{repo} has no releases yet")
        # A -N-g<sha> build past this tag (from --edge) counts as newer than the tag itself.
        if (semver(have) >= semver(tag)) and not a.force:
            print(f"NekoStudio {have} is up to date (latest release: {tag}).")
            return 0
        print(f"NekoStudio {tag} is out (installed: {have}).")
        target, label = tag, tag
    if a.check:
        return 10

    if server_running():
        raise Fail("NekoStudio is running: close its window (or Ctrl+C) first, then update")
    if is_git():
        if git("status", "--porcelain", "--untracked-files=no") and not a.force:
            raise Fail(f"{ROOT} has uncommitted changes; commit or stash them, or add --force to throw them away")
        ask(f"Update this git checkout to {label}?", a.yes)
        before = setup_hash()
        say(f"Getting {repo} {label}")
        git("fetch", "-q", "--tags", "--force", "origin")
        if a.edge:
            git("fetch", "-q", "origin", f"+refs/heads/{a.branch}:refs/remotes/origin/{a.branch}")
            git("checkout", "-q", "-B", a.branch, f"origin/{a.branch}")
            git("reset", "-q", "--hard", f"origin/{a.branch}")
        else:
            git("checkout", "-q", "--force", target)
        version = installed()
    else:
        ask(f"Install NekoStudio {label}?", a.yes)
        before = setup_hash()
        say(f"Downloading {repo} {label}")
        blob = download(repo, target)
        if a.edge:
            # Same shape as `git describe`: <latest tag>-<commits past it>-g<sha>, so the next run can compare.
            try:
                tag = api(f"repos/{repo}/releases/latest").get("tag_name") or ""
                ahead = api(f"repos/{repo}/compare/{tag}...{target}").get("ahead_by", 0) if tag else 0
                version = f"{tag}-{ahead}-g{target[:7]}" if tag and ahead else (tag or target[:7])
            except Fail:
                version = target[:7]
        else:
            version = target
        say(f"Installing {version}")
        swap_in(blob, version)
    if setup_hash() != before or a.force:
        run_setup(trainer_installed())
    print(f"\nNekoStudio {version} is installed. Start it again to use it.")
    if not is_git():
        print(f"The previous files are in {ROOT / '.previous'} until the next update.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        print(f"nekostudio-update: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
