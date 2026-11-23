"""解析子进程入口。只读 /work/input.bin，不读取父进程环境里的密钥。

TXT/MD 只用标准库。PDF 使用 pypdf，DOCX 使用 python-docx。
这两个库必须由沙箱只读挂载进来。挂载失败时父进程直接拒绝，不在本进程外另找解析路径。
"""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

_ADDRESS_LIMIT = 256 * 1024 * 1024
_CPU_SECONDS = 60
_FILE_BYTES = 32 * 1024 * 1024
_MAX_PDF_PAGES = 200


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (_ADDRESS_LIMIT, _ADDRESS_LIMIT))
    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_SECONDS, _CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_BYTES, _FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def _fail(code: str) -> int:
    sys.stderr.write(f"ERR {code}\n")
    return 4


def _emit(kind: str, page_count: int | None, pages: list[dict], notice: str | None) -> int:
    sys.stdout.write(
        json.dumps(
            {"kind": kind, "page_count": page_count, "pages": pages, "notice": notice},
            ensure_ascii=False,
        )
    )
    return 0


def _text_file() -> int:
    path = Path("/work/input.bin")
    try:
        data = path.read_bytes()
    except OSError:
        return _fail("read")
    if not data:
        return _fail("empty")
    if b"\x00" in data:
        return _fail("binary")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _fail("binary")
    if not text.strip():
        return _fail("empty")
    return _emit("txt", 1, [{"page": 1, "text": text}], None)


def _pdf() -> int:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except Exception:
        return _fail("dependency_unavailable")
    path = Path("/work/input.bin")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return _fail("encrypted")
        count = len(reader.pages)
    except PdfReadError:
        return _fail("corrupt")
    except Exception:
        return _fail("corrupt")
    if count > _MAX_PDF_PAGES:
        return _fail("too_many_pages")
    pages = []
    missing: list[int] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            return _fail("corrupt")
        if text.strip():
            pages.append({"page": index, "text": text})
        else:
            missing.append(index)
    if not pages:
        return _fail("no_text")
    notice = None
    if missing:
        notice = "missing_pages:" + ",".join(str(number) for number in missing[:50])
    return _emit("pdf", count, pages, notice)


def _docx() -> int:
    try:
        from docx import Document
    except Exception:
        return _fail("dependency_unavailable")
    path = Path("/work/input.bin")
    try:
        document = Document(str(path))
    except Exception:
        return _fail("corrupt")
    parts: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    if not parts:
        return _fail("empty")
    return _emit(
        "docx",
        None,
        [{"page": None, "text": "\n\n".join(parts)}],
        "page_unavailable",
    )


def main() -> int:
    try:
        _limits()
    except (ValueError, OSError):
        return _fail("limits")
    kind = sys.argv[1] if len(sys.argv) > 1 else "txt"
    if kind in {"txt", "md"}:
        return _text_file()
    if kind == "pdf":
        return _pdf()
    if kind == "docx":
        return _docx()
    return _fail("unsupported_media")


if __name__ == "__main__":
    raise SystemExit(main())
