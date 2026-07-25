#!/usr/bin/env bash
# Reinstall gazetteer into .venv for local development.
#
# This sandbox's filesystem layer silently breaks .pth-based editable
# installs: `site.addpackage()` fails to add the path from a .pth file
# even though the file's content, permissions, and every syscall it uses
# succeed when called directly (see the ModuleNotFoundError debugging
# session in project history). Standard `pip install -e` / `uv pip
# install -e` are therefore unreliable here.
#
# Workaround: symlink the package directly into site-packages, bypassing
# .pth processing entirely, and hand-write the `gaz` console script.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    uv venv --python 3.12
fi

# shellcheck disable=SC1091
source .venv/bin/activate

uv pip install click 'pytest>=8.0'
uv pip uninstall gazetteer >/dev/null 2>&1 || true

SITE_PKGS=$(python3 -c "import site; print(site.getsitepackages()[0])")
ln -sf "$(pwd)/src/gazetteer" "$SITE_PKGS/gazetteer"

cat > .venv/bin/gaz <<EOF
#!$(pwd)/.venv/bin/python3
import sys
from gazetteer.cli import main

if __name__ == "__main__":
    sys.exit(main())
EOF
chmod +x .venv/bin/gaz

echo "Installed. Verifying:"
gaz --help
