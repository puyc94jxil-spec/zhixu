"""SQLite 在线备份。禁止在 WAL 期间直接拷贝主库文件。

恢复函数只给运维或测试调用，没有用户自助恢复接口。
30 天备份清除期限尚未实现。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from zhixu_server.config import Settings


def backup_consistent(settings: Settings, dest: Path) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    db_out = dest / "zhixu.db"
    if db_out.exists():
        db_out.unlink()
    source = sqlite3.connect(settings.db_path)
    target = sqlite3.connect(db_out)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    objects = dest / "objects"
    objects.mkdir(exist_ok=True)
    check = sqlite3.connect(db_out)
    check.row_factory = sqlite3.Row
    manifest = []
    try:
        rows = check.execute(
            "SELECT id, version, hash, object_key, deleted_at FROM files"
        ).fetchall()
        for row in rows:
            src = settings.objects_dir / row["object_key"]
            item = {
                "file_id": row["id"],
                "version": row["version"],
                "hash": row["hash"],
                "object_key": row["object_key"],
                "deleted": row["deleted_at"] is not None,
                "object_present": src.exists() and row["deleted_at"] is None,
            }
            if row["deleted_at"] is None and src.exists():
                target_path = objects / row["object_key"]
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target_path)
            manifest.append(item)
    finally:
        check.close()
    (dest / "manifest.json").write_text(
        json.dumps({"files": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"database": str(db_out), "files": len(manifest)}


def restore_consistent(backup_dir: Path, target_data: Path) -> dict:
    """把一致快照恢复到一个新的数据目录。不覆盖调用者未确认的任意路径。"""
    if not (backup_dir / "zhixu.db").exists():
        raise FileNotFoundError("backup_db_missing")
    target_data.mkdir(parents=True, exist_ok=True)
    marker = target_data / "ZHIXU_DATA_MARKER"
    if any(target_data.iterdir()) and not marker.exists():
        raise RuntimeError("restore_target_not_empty")
    restored_db = target_data / "zhixu.db"
    if restored_db.exists():
        restored_db.unlink()
    source = sqlite3.connect(backup_dir / "zhixu.db")
    target = sqlite3.connect(restored_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    objects_src = backup_dir / "objects"
    objects_dst = target_data / "objects"
    if objects_dst.exists():
        shutil.rmtree(objects_dst)
    if objects_src.exists():
        shutil.copytree(objects_src, objects_dst)
    else:
        objects_dst.mkdir(parents=True, exist_ok=True)
    marker.write_text("zhixu-data\n", encoding="utf-8")
    return {"data_dir": str(target_data)}
