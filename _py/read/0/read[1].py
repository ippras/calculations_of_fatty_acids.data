"""RON (Rust, polars) -> Python: чтение, meta в колонки (long format), превью, сохранение в RON.

Формат файла:
    #![enable(unwrap_newtypes)]
    (
        meta: [(name: "...", value: "..."), ...],
        data: (bytes: b"<Arrow IPC stream>", hash: <u64>),
    )

Запуск:
    python ron_polars_tool.py                 # выбор файла через окно проводника
    python ron_polars_tool.py file.ron        # путь задан сразу
    python ron_polars_tool.py --no-gui        # без окон, всё в консоли

Зависимости: polars (pip install polars). tkinter входит в стандартную поставку Python.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import polars as pl

HEADER = "#![enable(unwrap_newtypes)]"
Meta = list[tuple[str, str]]

# --------------------------------------------------------------------------- #
# RON <-> байты / строки
# --------------------------------------------------------------------------- #

_BYTE_ESCAPES = {"n": 0x0A, "r": 0x0D, "t": 0x09, "\\": 0x5C, '"': 0x22, "'": 0x27, "0": 0x00}

_META_RE = re.compile(
    r'\(\s*name:\s*"((?:[^"\\]|\\.)*)"\s*,\s*value:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*\)'
)


def _find_byte_string(text: str) -> tuple[int, int]:
    """Границы содержимого b"..." (без кавычек) в поле `bytes:`."""
    m = re.search(r'\bbytes\s*:\s*b"', text)
    if m is None:
        raise ValueError('не найдено поле `bytes: b"..."`')
    start = i = m.end()
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return start, i
        else:
            i += 1
    raise ValueError("не закрыта байтовая строка")


def unescape_rust_bytes(s: str) -> bytes:
    """Содержимое Rust/RON b"..." -> bytes."""
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(ord(c))
            i += 1
            continue
        nxt = s[i + 1]
        if nxt == "x":
            out.append(int(s[i + 2 : i + 4], 16))
            i += 4
        elif nxt in _BYTE_ESCAPES:
            out.append(_BYTE_ESCAPES[nxt])
            i += 2
        elif nxt == "\n":
            i += 2
            while i < n and s[i] in " \t\r\n":
                i += 1
        else:
            raise ValueError(f"неизвестная escape-последовательность: \\{nxt}")
    return bytes(out)


def escape_rust_bytes(data: bytes) -> str:
    """bytes -> содержимое b"..." (как u8::escape_ascii в Rust)."""
    out = []
    for x in data:
        if x == 0x5C:
            out.append("\\\\")
        elif x == 0x22:
            out.append('\\"')
        elif x == 0x0A:
            out.append("\\n")
        elif x == 0x0D:
            out.append("\\r")
        elif x == 0x09:
            out.append("\\t")
        elif 0x20 <= x < 0x7F:
            out.append(chr(x))
        else:
            out.append(f"\\x{x:02x}")
    return "".join(out)


def _unescape_ron_str(s: str) -> str:
    simple = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'", "0": "\0"}

    def repl(m: re.Match) -> str:
        e = m.group(1)
        if e[0] == "u":
            return chr(int(e[2:-1], 16))
        if e[0] == "x" and len(e) == 3:
            return chr(int(e[1:], 16))
        return simple.get(e, e)

    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|x[0-9a-fA-F]{2}|.)", repl, s)


def _ron_str(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{{{o:x}}}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def render_ron(raw: bytes, meta: Meta = (), hash_value: int = 0) -> str:
    """Собирает текст .ron в том же формате, что пишет Rust."""
    lines = [HEADER, "("]
    if meta:
        lines.append("    meta: [")
        lines += [f"        (name: {_ron_str(n)}, value: {_ron_str(v)})," for n, v in meta]
        lines.append("    ],")
    else:
        lines.append("    meta: [],")
    lines += [
        "    data: (",
        f'        bytes: b"{escape_rust_bytes(raw)}",',
        f"        hash: {hash_value},",
        "    ),",
        ")",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Чтение / конвертация / запись
# --------------------------------------------------------------------------- #

def read_ron(path: str | Path) -> tuple[pl.DataFrame, Meta]:
    """Читает .ron -> (DataFrame, meta как список пар (name, value))."""
    text = Path(path).read_text(encoding="utf-8")
    start, end = _find_byte_string(text)
    df = pl.read_ipc_stream(io.BytesIO(unescape_rust_bytes(text[start:end])))
    meta = [(_unescape_ron_str(n), _unescape_ron_str(v)) for n, v in _META_RE.findall(text[:start])]
    return df, meta


def meta_to_columns(df: pl.DataFrame, meta: Meta, sep: str = "; ") -> pl.DataFrame:
    """Каждая meta-запись становится колонкой (значение повторено в каждой строке).

    Повторяющиеся ключи (например, два Author) склеиваются через `sep`.
    Если имя совпало с уже существующей колонкой, добавляется префикс `meta_`.
    Meta-колонки идут первыми.
    """
    grouped: dict[str, list[str]] = {}
    for name, value in meta:
        grouped.setdefault(name, []).append(value)

    used = set(df.columns)
    exprs, names = [], []
    for name, values in grouped.items():
        col = name
        while col in used:
            col = f"meta_{col}"
        used.add(col)
        names.append(col)
        exprs.append(pl.lit(sep.join(values), dtype=pl.String).alias(col))

    if not exprs:
        return df
    return df.with_columns(exprs).select(names + df.columns)


def write_ron(df: pl.DataFrame, path: str | Path, meta: Meta = (), hash_value: int = 0) -> None:
    """Сохраняет DataFrame в .ron (Arrow IPC stream внутри b"...")."""
    buf = io.BytesIO()
    df.write_ipc_stream(buf)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_ron(buf.getvalue(), meta, hash_value))


# --------------------------------------------------------------------------- #
# Интерфейс: диалоги выбора файла и окно превью (tkinter) + консольный запасной вариант
# --------------------------------------------------------------------------- #

def preview_text(df: pl.DataFrame) -> str:
    schema = "\n".join(f"  {k}: {v}" for k, v in df.schema.items())
    with pl.Config(tbl_rows=40, tbl_cols=-1, tbl_width_chars=400, fmt_str_lengths=80):
        table = str(df)
    return f"shape: {df.shape}\n\nschema:\n{schema}\n\n{table}"


def _make_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)  # чтобы диалоги не прятались за терминалом
    except Exception:
        pass
    return root


def _gui_preview(root, text: str, title: str) -> bool:
    import tkinter as tk
    from tkinter import ttk

    result = {"ok": False}
    win = tk.Toplevel(root)
    win.title(title)
    win.geometry("1100x600")
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    frame = ttk.Frame(win)
    frame.pack(fill="both", expand=True)
    box = tk.Text(frame, wrap="none", font="TkFixedFont")
    ys = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
    xs = ttk.Scrollbar(frame, orient="horizontal", command=box.xview)
    box.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    box.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    box.insert("1.0", text)
    box.configure(state="disabled")

    def done(ok: bool) -> None:
        result["ok"] = ok
        win.destroy()

    buttons = ttk.Frame(win)
    buttons.pack(fill="x", padx=8, pady=8)
    ttk.Button(buttons, text="Сохранить как…", command=lambda: done(True)).pack(side="right")
    ttk.Button(buttons, text="Отмена", command=lambda: done(False)).pack(side="right", padx=8)
    win.protocol("WM_DELETE_WINDOW", lambda: done(False))
    win.grab_set()
    root.wait_window(win)
    return result["ok"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="путь к .ron (если не задан, откроется окно выбора файла)")
    ap.add_argument("--sep", default="; ", help='разделитель для повторяющихся ключей meta (по умолчанию "; ")')
    ap.add_argument("--hash", type=int, default=0, dest="hash_value", help="значение поля hash в выходном файле")
    ap.add_argument("--no-gui", action="store_true", help="не использовать окна, работать в консоли")
    args = ap.parse_args(argv)

    root = None
    if not args.no_gui:
        try:
            root = _make_root()
        except Exception as e:  # нет tkinter или нет дисплея
            print(f"Окна недоступны ({e}), работаю в консоли.")

    # 1. выбор файла
    if args.input:
        src = Path(args.input)
    elif root is not None:
        from tkinter import filedialog

        chosen = filedialog.askopenfilename(
            parent=root,
            title="Выберите .ron файл",
            filetypes=[("RON files", "*.ron"), ("Все файлы", "*.*")],
        )
        if not chosen:
            return 0
        src = Path(chosen)
    else:
        raw = input("Путь к .ron: ").strip().strip('"')
        if not raw:
            return 0
        src = Path(raw)

    # 2. чтение и конвертация
    df, meta = read_ron(src)
    long_df = meta_to_columns(df, meta, args.sep)
    print(f"Прочитано: {src.name}, строк: {df.height}, meta-записей: {len(meta)}")

    # 3. превью и подтверждение
    text = preview_text(long_df)
    if root is not None:
        if not _gui_preview(root, text, f"Превью (long format): {src.name}"):
            return 0
    else:
        print(text)
        if input("\nСохранить? [y/N] ").strip().lower() != "y":
            return 0

    # 4. выбор места и сохранение
    default = src.with_name(f"{src.stem}_long.ron")
    if root is not None:
        from tkinter import filedialog

        chosen = filedialog.asksaveasfilename(
            parent=root,
            title="Сохранить как",
            defaultextension=".ron",
            initialdir=str(src.parent),
            initialfile=default.name,
            filetypes=[("RON files", "*.ron")],
        )
        if not chosen:
            return 0
        dst = Path(chosen)
    else:
        raw = input(f"Куда сохранить [{default}]: ").strip().strip('"')
        dst = Path(raw) if raw else default

    write_ron(long_df, dst, hash_value=args.hash_value)

    # 5. контроль: читаем записанное обратно
    back, _ = read_ron(dst)
    ok = back.equals(long_df)
    print(f"Сохранено: {dst}")
    print("Проверка чтением обратно:", "OK" if ok else "ДАННЫЕ НЕ СОВПАЛИ")
    if args.hash_value == 0:
        print("Внимание: поле hash записано как 0 (см. --hash).")

    if root is not None:
        root.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())