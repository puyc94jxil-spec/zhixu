"""解析子进程入口。只使用标准库，不读取父进程环境里的密钥。"""

from __future__ import annotations

import resource
import sys
from pathlib import Path

# 子进程内存上限。过小会导致解释器自己起不来，过大就失去限制意义。
_ADDRESS_LIMIT = 256 * 1024 * 1024
_CPU_SECONDS = 60
_FILE_BYTES = 32 * 1024 * 1024


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (_ADDRESS_LIMIT, _ADDRESS_LIMIT))
    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_BYTES, _FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def main() -> int:
    try:
        _limits()
    except (ValueError, OSError):
        sys.stderr.write("ERR limits\n")
        return 4
    path = Path("/work/input.bin")
    try:
        data = path.read_bytes()
    except OSError:
        sys.stderr.write("ERR read\n")
        return 4
    if not data:
        sys.stderr.write("ERR empty\n")
        return 2
    if b"\x00" in data:
        sys.stderr.write("ERR binary\n")
        return 3
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        sys.stderr.write("ERR binary\n")
        return 3
    # 展开体积由父进程按原文件 10 倍复核。这里只输出正文。
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
