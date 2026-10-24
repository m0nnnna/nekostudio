# Sourced by setup.sh and run.sh (from the install dir). Sets ENV_DIR: where .venv, .venv-train and
# vendor/ live. That is the install dir itself, unless it sits on a network share (SMB/NFS/gvfs):
# venvs there are slow to import from and each PC needs its own, so they go to local disk instead.
ROOT="$PWD"
ENV_DIR="$ROOT"
case "$(findmnt -no FSTYPE -T "$ROOT" 2>/dev/null)" in
  cifs|smb3|smbfs|nfs|nfs4|9p|fuse.gvfsd-fuse|fuse.sshfs)
    ENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nekostudio/env-$(printf %s "$ROOT" | sha1sum | cut -c1-8)"
    mkdir -p "$ENV_DIR"
    printf '%s\n' "$ROOT" > "$ENV_DIR/install-path.txt"
    export PYTHONPYCACHEPREFIX="$ENV_DIR/pycache" ;;
esac
export NEKOSTUDIO_ENV="$ENV_DIR"
