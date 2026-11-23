"""原文切段与 jieba 分词。分词结果不写回原文。"""

from __future__ import annotations

import re

import jieba

NOT_FOUND = "资料中未找到"
PLACEHOLDER = "[依据文件已删除或撤销，该轮材料内容不再纳入上下文]"
CLAIMS_MARK = "<<<CLAIMS>>>"
_MAX_PARAGRAPH = 1200


def lex(text: str) -> str:
    """入库和查询必须走同一个 jieba 模式。"""
    words = []
    for word in jieba.lcut(text, cut_all=False, HMM=True):
        cleaned = word.strip()
        if not cleaned or cleaned.isspace():
            continue
        words.append(cleaned)
    return " ".join(words)


def fts_query(text: str) -> str:
    """用同一套 jieba 词做检索。词与词之间取 OR，避免问句里的虚词把命中全部滤掉。"""
    parts = []
    for word in lex(text).split():
        if word.upper() in {"AND", "OR", "NOT"}:
            continue
        if len(word) == 1 and not word.isdigit():
            continue
        safe = word.replace('"', "")
        if safe:
            parts.append('"' + safe + '"')
    return " OR ".join(parts)


def fold_ws(text: str) -> str:
    return "".join(text.split())


def quote_supported(quote: str, chunk_text: str) -> bool:
    if not quote or not quote.strip():
        return False
    if quote in chunk_text:
        return True
    return fold_ws(quote) in fold_ws(chunk_text)


def numbers_supported(claim: str, chunk_text: str) -> bool:
    """金额、日期里的数字必须出现在对应原文。这只是字面守卫，不是语义验收。"""
    for number in re.findall(r"\d+", claim):
        if number not in chunk_text:
            return False
    return True


def split_paragraphs(text: str) -> list[dict]:
    """按空行和 Markdown 标题切段，offset 指向原文，0 基，长度为字符数。"""
    paragraphs: list[dict] = []
    index = 1
    cursor = 0
    block_start = None
    lines = text.splitlines(keepends=True)
    pos = 0
    pending = ""
    pending_start = 0

    def flush() -> None:
        nonlocal index, pending, pending_start
        body = pending
        if body.strip():
            start = pending_start
            # 去掉块尾多余换行，但 offset 仍指向正文起点
            stripped = body.rstrip("\r\n")
            lead = len(stripped) - len(stripped.lstrip("\r\n"))
            core = stripped.strip("\r\n")
            if core:
                real_start = start + lead
                _emit(paragraphs, index, real_start, core)
                index += 1
        pending = ""

    for line in lines:
        is_blank = line.strip() == ""
        is_heading = line.lstrip().startswith("#")
        if is_blank:
            flush()
            pos += len(line)
            continue
        if is_heading and pending.strip():
            flush()
        if not pending:
            pending_start = pos
        pending += line
        pos += len(line)
    flush()
    if not paragraphs and text.strip():
        core = text.strip()
        real_start = text.find(core)
        _emit(paragraphs, 1, real_start, core)
    _ = cursor, block_start
    return paragraphs


def _emit(items: list[dict], paragraph: int, start: int, core: str) -> None:
    if len(core) <= _MAX_PARAGRAPH:
        items.append(
            {
                "paragraph": paragraph,
                "offset": start,
                "length": len(core),
                "text": core,
                "page": 1,
            }
        )
        return
    local = 0
    part = 0
    while local < len(core):
        piece = core[local : local + _MAX_PARAGRAPH]
        items.append(
            {
                "paragraph": paragraph + part,
                "offset": start + local,
                "length": len(piece),
                "text": piece,
                "page": 1,
            }
        )
        local += _MAX_PARAGRAPH
        part += 1


def parse_claims(raw: str) -> tuple[str, list[dict]]:
    if CLAIMS_MARK not in raw:
        return raw.strip(), []
    answer, rest = raw.split(CLAIMS_MARK, 1)
    claims = []
    current: dict[str, str] = {}
    for line in rest.splitlines():
        if line.strip() == "---":
            if current:
                claims.append(current)
            current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = value.strip()
    if current:
        claims.append(current)
    return answer.strip(), claims
