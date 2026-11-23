"""运维命令：重置数据、在线备份、恢复、创建夹具账号。

不打印密码。夹具账号的密码只从环境变量读取。
"""

from __future__ import annotations

import argparse
import os
import shutil

from zhixu_server.backup import backup_consistent, restore_consistent
from zhixu_server.config import load_settings
from zhixu_server.db import connect, init_db
from zhixu_server.security import hash_password, iso, new_id


def reset_data(data_dir) -> None:
    marker = data_dir / "ZHIXU_DATA_MARKER"
    if data_dir.exists() and any(data_dir.iterdir()) and not marker.exists():
        raise SystemExit("拒绝重置：目录不是知序数据目录")
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("zhixu-data\n", encoding="utf-8")


def fixture_users() -> None:
    password_1 = os.environ.get("ZHIXU_FIXTURE_USER1_PASSWORD", "")
    password_2 = os.environ.get("ZHIXU_FIXTURE_USER2_PASSWORD", "")
    name_1 = os.environ.get("ZHIXU_FIXTURE_USER1_NAME", "fixture_user_a")
    name_2 = os.environ.get("ZHIXU_FIXTURE_USER2_NAME", "fixture_user_b")
    if len(password_1) < 10 or len(password_2) < 10:
        raise SystemExit("请用环境变量提供两个至少 10 位的夹具密码，本命令不生成也不打印密码")
    settings = load_settings()
    init_db(settings)
    conn = connect(settings)
    try:
        created = []
        for name, password in ((name_1, password_1), (name_2, password_2)):
            found = conn.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()
            if found:
                created.append(found["id"])
                continue
            user_id = new_id()
            conn.execute(
                "INSERT INTO users(id, username, password_hash, created_at, deleted_at) VALUES (?, ?, ?, ?, NULL)",
                (user_id, name, hash_password(password), iso()),
            )
            created.append(user_id)
    finally:
        conn.close()
    print("fixture_user_ids=" + ",".join(created))


def main() -> None:
    parser = argparse.ArgumentParser(description="知序数据维护")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset")
    reset.add_argument("--yes", action="store_true")
    backup = sub.add_parser("backup")
    backup.add_argument("--dest", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--src", required=True)
    restore.add_argument("--data-dir", required=True)
    purge = sub.add_parser("purge")
    purge.add_argument("--yes", action="store_true")
    purge.add_argument("--backup-root")
    sub.add_parser("fixture-users")
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "reset":
        if not args.yes:
            raise SystemExit("重置需要 --yes")
        reset_data(settings.data_dir)
        print("reset_ok")
    elif args.command == "backup":
        init_db(settings)
        from pathlib import Path

        print(backup_consistent(settings, Path(args.dest)))
    elif args.command == "restore":
        from pathlib import Path

        print(restore_consistent(Path(args.src), Path(args.data_dir)))
    elif args.command == "purge":
        from pathlib import Path

        from zhixu_server.backup import purge_expired_backups

        if not args.yes:
            raise SystemExit("清除过期备份需要 --yes")
        root = Path(args.backup_root) if args.backup_root else settings.backup_dir
        if root is None:
            raise SystemExit("请设置 ZHIXU_BACKUP_DIR 或传入 --backup-root")
        print(purge_expired_backups(root, settings.backup_retention_days))
    elif args.command == "fixture-users":
        fixture_users()
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
