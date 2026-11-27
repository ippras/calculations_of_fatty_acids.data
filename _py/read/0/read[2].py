"""RON (Rust, polars) -> Python: чтение, meta в отдельные колонки, превью, сохранение в RON.

Поддерживаемый вход:
    - старый RON-контейнер с data.bytes (Arrow IPC stream);
    - новый текстовый RON с data.columns, без IPC.

Новый выходной формат:
    #![enable(unwrap_newtypes)]
    (
        meta: [(name: "...", value: "..."), ...],
        data: (
            format: "polars_columns_v1",
            columns: [
                (name: "...", dtype: "...", values: [...],), ...
            ],
            height: <usize>,
            hash: <u64>,
        ),
    )

Значения колонок записываются нативными RON-значениями: числами, строками,
None, массивами и картами. При сохранении IPC-поток не создаётся.

Запуск:
    python ron_polars_tool.py                 # выбор файла через окно проводника
    python ron_polars_tool.py file.ron        # путь задан сразу
    python ron_polars_tool.py --no-gui        # без окон, всё в консоли

Зависимости: polars (pip install polars). tkinter входит в стандартную поставку Python.
"""

from __future__ import annotations

import argparse
import datetime as dt
import decimal
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

_BYTE_ESCAPES = {
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "\\": 0x5C,
    '"': 0x22,
    "'": 0x27,
    "0": 0x00,
}

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
    simple = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        '"': '"',
        "'": "'",
        "0": "\0",
    }

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


def _ron_value(value) -> str:
    """Сериализует значение ячейки непосредственно в синтаксис RON."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return _ron_str("NaN")
        if value == float("inf"):
            return _ron_str("inf")
        if value == float("-inf"):
            return _ron_str("-inf")
        return repr(value)
    if isinstance(value, dt.datetime):
        return _ron_str(value.isoformat())
    if isinstance(value, dt.date):
        return _ron_str(value.isoformat())
    if isinstance(value, dt.time):
        return _ron_str(value.isoformat())
    if isinstance(value, dt.timedelta):
        return str(int(value.total_seconds() * 1_000_000))
    if isinstance(value, decimal.Decimal):
        return _ron_str(str(value))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return 'b"' + escape_rust_bytes(bytes(value)) + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_ron_value(v) for v in value) + "]"
    if isinstance(value, dict):
        pairs = [f"{_ron_str(str(k))}: {_ron_value(v)}" for k, v in value.items()]
        return "{ " + ", ".join(pairs) + " }"

    # Поддержка скалярных типов numpy/arrow, у которых есть .item().
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _ron_value(item())
        except Exception:
            pass
    return _ron_str(str(value))


class _RonParser:
    """Небольшой парсер под используемое здесь подмножество RON."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        stripped = text.lstrip()
        if stripped.startswith("#!"):
            newline = text.find("\n")
            self.pos = len(text) if newline < 0 else newline + 1

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _expect(self, char: str) -> None:
        self._skip_ws()
        if self.pos >= len(self.text) or self.text[self.pos] != char:
            got = self.text[self.pos : self.pos + 20]
            raise ValueError(
                f"Ожидался символ {char!r} около позиции {self.pos}, найдено {got!r}"
            )
        self.pos += 1

    def _quoted(self, byte_string: bool = False):
        if byte_string:
            self.pos += 2  # b"
        else:
            self.pos += 1  # "
        start = self.pos
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\":
                self.pos += 2
                continue
            if char == '"':
                raw = self.text[start : self.pos]
                self.pos += 1
                return (
                    unescape_rust_bytes(raw) if byte_string else _unescape_ron_str(raw)
                )
            self.pos += 1
        raise ValueError("Незакрытая строка RON")

    def _identifier(self) -> str:
        self._skip_ws()
        start = self.pos
        while self.pos < len(self.text) and (
            self.text[self.pos].isalnum() or self.text[self.pos] == "_"
        ):
            self.pos += 1
        if start == self.pos:
            raise ValueError(f"Ожидалось имя поля около позиции {self.pos}")
        return self.text[start : self.pos]

    def _tuple(self) -> dict:
        self._expect("(")
        result = {}
        while True:
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ")":
                self.pos += 1
                return result
            key = self._identifier()
            self._expect(":")
            result[key] = self._value()
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
            elif self.pos < len(self.text) and self.text[self.pos] == ")":
                self.pos += 1
                return result
            else:
                raise ValueError(f"Ожидалась запятая или ')' около позиции {self.pos}")

    def _list(self) -> list:
        self._expect("[")
        result = []
        while True:
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == "]":
                self.pos += 1
                return result
            result.append(self._value())
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
            elif self.pos < len(self.text) and self.text[self.pos] == "]":
                self.pos += 1
                return result
            else:
                raise ValueError(f"Ожидалась запятая или ']' около позиции {self.pos}")

    def _map(self) -> dict:
        self._expect("{")
        result = {}
        while True:
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                return result
            key = self._value()
            self._expect(":")
            result[key] = self._value()
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1
            elif self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                return result
            else:
                raise ValueError(f"Ожидалась запятая или '}}' около позиции {self.pos}")

    def _value(self):
        self._skip_ws()
        if self.pos >= len(self.text):
            raise ValueError("Неожиданный конец RON")
        if self.text.startswith('b"', self.pos):
            return self._quoted(byte_string=True)
        char = self.text[self.pos]
        if char == '"':
            return self._quoted()
        if char == "(":
            return self._tuple()
        if char == "[":
            return self._list()
        if char == "{":
            return self._map()

        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",)]}: \t\r\n":
            self.pos += 1
        token = self.text[start : self.pos]
        if not token:
            raise ValueError(f"Неожиданный символ около позиции {self.pos}")
        if token == "None":
            return None
        if token == "true":
            return True
        if token == "false":
            return False
        if re.fullmatch(r"[+-]?\d+", token):
            return int(token)
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?", token):
            return float(token)
        return token

    def parse(self):
        result = self._value()
        self._skip_ws()
        if self.pos != len(self.text):
            raise ValueError(
                f"Лишние данные после RON-объекта около позиции {self.pos}"
            )
        return result


def _coerce_value(value, dtype_name: str):
    """Преобразует строковые значения RON обратно в дату/время/decimal и т. п."""
    if value is None:
        return None
    if dtype_name == "Date" and isinstance(value, str):
        return dt.date.fromisoformat(value)
    if dtype_name == "Time" and isinstance(value, str):
        return dt.time.fromisoformat(value)
    if dtype_name.startswith("Datetime(") and isinstance(value, str):
        return dt.datetime.fromisoformat(value)
    if dtype_name.startswith("Duration(") and isinstance(value, int):
        return dt.timedelta(microseconds=value)
    if dtype_name.startswith("Decimal(") and isinstance(value, str):
        return decimal.Decimal(value)
    if dtype_name in ("Float32", "Float64") and isinstance(value, str):
        special = {"NaN": float("nan"), "inf": float("inf"), "-inf": float("-inf")}
        return special.get(value, value)
    if dtype_name.startswith("List(") and isinstance(value, list):
        inner = dtype_name[5:-1]
        return [_coerce_value(v, inner) for v in value]
    return value


def _dtype_from_name(name: str):
    """Восстанавливает распространённые Polars-типы из их строкового имени."""
    simple = (
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "UInt8",
        "UInt16",
        "UInt32",
        "UInt64",
        "Float32",
        "Float64",
        "Boolean",
        "String",
        "Binary",
        "Date",
        "Time",
        "Null",
    )
    if name in simple:
        return getattr(pl, name, None)
    if name == "Categorical":
        return getattr(pl, "Categorical", None)

    match = re.fullmatch(
        r"Datetime\(time_unit=['\"](ns|us|ms)['\"], time_zone=(None|['\"](.*?)['\"])\)",
        name,
    )
    if match:
        zone = match.group(3)
        return pl.Datetime(time_unit=match.group(1), time_zone=zone)

    match = re.fullmatch(r"Duration\(time_unit=['\"](ns|us|ms)['\"]\)", name)
    if match:
        return pl.Duration(time_unit=match.group(1))

    match = re.fullmatch(r"Decimal\(precision=(None|\d+), scale=(None|\d+)\)", name)
    if match:
        precision = None if match.group(1) == "None" else int(match.group(1))
        scale = None if match.group(2) == "None" else int(match.group(2))
        return pl.Decimal(precision=precision, scale=scale)

    match = re.fullmatch(r"List\((.*)\)", name)
    if match:
        inner = _dtype_from_name(match.group(1))
        return pl.List(inner) if inner is not None else None

    return None


def render_ron(df: pl.DataFrame, meta: Meta = (), hash_value: int = 0) -> str:
    """Собирает текстовый RON с нативными RON-значениями; IPC не используется."""
    lines = [HEADER, "(", "    meta: ["]
    lines += [f"        (name: {_ron_str(n)}, value: {_ron_str(v)})," for n, v in meta]
    lines += [
        "    ],",
        "    data: (",
        '        format: "polars_columns_v1",',
        "        columns: [",
    ]
    for name, series in zip(df.columns, df.iter_columns()):
        lines.append(
            "            ("
            f"name: {_ron_str(name)}, "
            f"dtype: {_ron_str(str(series.dtype))}, "
            "values: ["
        )
        lines.extend(
            f"                {_ron_value(value)}," for value in series.to_list()
        )
        lines.append("            ],),")
    lines += [
        "        ],",
        f"        height: {df.height},",
        f"        hash: {hash_value},",
        "    ),",
        ")",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Чтение / конвертация / запись
# --------------------------------------------------------------------------- #


def read_ron(path: str | Path) -> tuple[pl.DataFrame, Meta]:
    """Читает старый RON/IPC или новый текстовый RON -> (DataFrame, meta)."""
    text = Path(path).read_text(encoding="utf-8")
    root = _RonParser(text).parse()
    if not isinstance(root, dict):
        raise ValueError("Корень RON-файла должен быть структурой")

    meta = [(str(item["name"]), str(item["value"])) for item in root.get("meta", [])]
    data = root.get("data")
    if not isinstance(data, dict):
        raise ValueError("В RON-файле отсутствует структура data")

    # Обратная совместимость со старым контейнером, где data.bytes содержал IPC.
    if "bytes" in data:
        raw = data["bytes"]
        if not isinstance(raw, bytes):
            raise ValueError("Поле data.bytes должно быть RON byte string")
        return pl.read_ipc_stream(io.BytesIO(raw)), meta

    if data.get("format") != "polars_columns_v1":
        raise ValueError("Неизвестный формат data в RON-файле")

    series_list = []
    for column in data.get("columns", []):
        name = str(column["name"])
        dtype_name = str(column["dtype"])
        values = [_coerce_value(v, dtype_name) for v in column.get("values", [])]
        dtype = _dtype_from_name(dtype_name)
        if dtype is None:
            series = pl.Series(name=name, values=values, strict=False)
        else:
            series = pl.Series(name=name, values=values, dtype=dtype, strict=False)
        series_list.append(series)

    return (pl.DataFrame(series_list) if series_list else pl.DataFrame()), meta


def meta_to_columns(df: pl.DataFrame, meta: Meta) -> pl.DataFrame:
    """Добавляет по отдельной колонке для каждой meta-записи.

    Повторяющиеся ключи получают суффиксы _2, _3 и т. д.; значения не склеиваются.
    Если имя конфликтует с колонкой данных, используется префикс meta_.
    Meta-колонки идут первыми.
    """
    used = set(df.columns)
    occurrences: dict[str, int] = {}
    exprs, names = [], []

    for name, value in meta:
        occurrences[name] = occurrences.get(name, 0) + 1
        occurrence = occurrences[name]
        candidate = name if occurrence == 1 else f"{name}_{occurrence}"
        if candidate in used:
            candidate = f"meta_{candidate}"
        base = candidate
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1

        used.add(candidate)
        names.append(candidate)
        exprs.append(pl.lit(value, dtype=pl.String).alias(candidate))

    if not exprs:
        return df
    return df.with_columns(exprs).select(names + df.columns)


def write_ron(
    df: pl.DataFrame, path: str | Path, meta: Meta = (), hash_value: int = 0
) -> None:
    """Сохраняет DataFrame в текстовый RON, без Arrow IPC."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_ron(df, meta, hash_value))


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
    ttk.Button(buttons, text="Сохранить как…", command=lambda: done(True)).pack(
        side="right"
    )
    ttk.Button(buttons, text="Отмена", command=lambda: done(False)).pack(
        side="right", padx=8
    )
    win.protocol("WM_DELETE_WINDOW", lambda: done(False))
    win.grab_set()
    root.wait_window(win)
    return result["ok"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "input",
        nargs="?",
        help="путь к .ron (если не задан, откроется окно выбора файла)",
    )
    ap.add_argument(
        "--hash",
        type=int,
        default=0,
        dest="hash_value",
        help="значение поля hash в выходном файле",
    )
    ap.add_argument(
        "--no-gui", action="store_true", help="не использовать окна, работать в консоли"
    )
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
    long_df = meta_to_columns(df, meta)
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

    write_ron(long_df, dst, meta=meta, hash_value=args.hash_value)

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
