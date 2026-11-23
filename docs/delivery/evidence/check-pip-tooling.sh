#!/bin/sh
# 只区分产品锁和本机安装器。默认不升级、不改系统 pip。
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)
echo "product_prod_lock=$root/server/requirements-prod.lock"
echo "product_dev_lock=$root/server/requirements-dev.lock"
if grep -E '^pip([=<>]|$)' "$root/server/requirements-prod.lock" "$root/server/requirements-dev.lock"; then
  echo "pip_in_product_lock=yes"
else
  echo "pip_in_product_lock=no"
fi
python3 -m pip --version
python3 - << 'PY'
import pathlib
for label, path in (
    ("prod_target", pathlib.Path("/tmp/zhixu-prod-site")),
    ("dev_target", pathlib.Path("/tmp/zhixu-dev-site")),
):
    found = list(path.glob("pip-*.dist-info")) if path.is_dir() else []
    print(f"{label}_exists={path.is_dir()} pip_dist_info={len(found)}")
PY
echo "system_pip_not_modified=yes"
if [ "${APPLY:-0}" != "1" ]; then
  echo "apply=skipped"
  exit 0
fi
installer=${INSTALLER_PIP:-/tmp/zhixu-audit-venv/bin/pip}
dest=${APPLY_DEST:-/tmp/zhixu-tooling-prod}
rm -rf "$dest"
mkdir -p "$dest"
"$installer" --version
"$installer" install --disable-pip-version-check --target "$dest" --upgrade --ignore-installed -r "$root/server/requirements-prod.lock"
find "$dest" -maxdepth 1 -name 'pip-*.dist-info' -print
echo "apply_dest=$dest"
