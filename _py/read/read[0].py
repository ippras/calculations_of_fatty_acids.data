"""Чтение .ron-файла с сериализованным polars DataFrame (Rust) в Python.

Структура файла:
    (
        meta: [(name: "...", value: "..."), ...],
        data: (bytes: b"<Arrow IPC stream>", hash: <u64>),
    )

Внутри `bytes` лежит обычный Arrow IPC stream, который polars читает напрямую.

Зависимости: polars (pip install polars). Больше ничего не нужно.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import polars as pl

_SIMPLE_ESCAPES = {
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "\\": 0x5C,
    '"': 0x22,
    "'": 0x27,
    "0": 0x00,
}


def _find_byte_string(text: str) -> tuple[int, int]:
    """Возвращает (start, end) границ содержимого b"..." (без кавычек)."""
    m = re.search(r'\bbytes\s*:\s*b"', text)
    if m is None:
        raise ValueError('не найдено поле `bytes: b"..."`')
    start = m.end()
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2  # пропускаем экранированный символ целиком
        elif c == '"':
            return start, i
        else:
            i += 1
    raise ValueError("не закрыта байтовая строка")


def _unescape_rust_bytes(s: str) -> bytes:
    """Разбирает содержимое Rust/RON b"..." в bytes."""
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(ord(c))  # в b"..." допустим только ASCII
            i += 1
            continue
        nxt = s[i + 1]
        if nxt == "x":
            out.append(int(s[i + 2 : i + 4], 16))
            i += 4
        elif nxt in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[nxt])
            i += 2
        elif nxt == "\n":  # перенос строки внутри литерала
            i += 2
            while i < n and s[i] in " \t\r\n":
                i += 1
        else:
            raise ValueError(f"неизвестная escape-последовательность: \\{nxt}")
    return bytes(out)


def read_ron_polars(path: str | Path) -> tuple[pl.DataFrame, dict[str, list[str]]]:
    """Читает .ron и возвращает (DataFrame, meta).

    meta — словарь name -> список value (ключи могут повторяться, например Author).
    """
    text = Path(path).read_text(encoding="utf-8")

    start, end = _find_byte_string(text)
    raw = _unescape_rust_bytes(text[start:end])
    df = pl.read_ipc_stream(io.BytesIO(raw))

    meta: dict[str, list[str]] = {}
    for name, value in re.findall(
        r'\(\s*name:\s*"((?:[^"\\]|\\.)*)"\s*,\s*value:\s*"((?:[^"\\]|\\.)*)"\s*\)',
        text[:start],
    ):
        meta.setdefault(name, []).append(value)

    return df, meta


if __name__ == "__main__":
    file = sys.argv[1] if len(sys.argv) > 1 else "data.ron"
    df, meta = read_ron_polars(file)
    print("meta:", meta)
    print(df.schema)
    print(df)

# ThirdParty/Brockerhoff1966/ron/{Lipids=Neutral}{StereospecificNumbers=1}{Index=1}{Name=Peanut}{Date=1966-01-01}.ron
# & 'C:\Program Files\Python312\python.exe' 'd:/git/ippras/calculations_of_fatty_acids.data/_py/read.py' 'ThirdParty/Brockerhoff1966/ron/{Lipids=Neutral}{StereospecificNumbers=1}{Index=1}{Name=Peanut}{Date=1966-01-01}.ron'