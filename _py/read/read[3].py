"""Чтение RON (с Arrow IPC внутри исходного файла) -> Polars -> CSV.

Повторяющиеся ключи meta становятся одной колонкой List(String).
В CSV значения list-колонок записываются как настоящие RON-массивы,
например ["Автор 1", "Автор 2"], а CSV-экранирование выполняется отдельно.

Запуск:
    python ron_to_csv.py                 # выбор .ron или .csv через окно
    python ron_to_csv.py file.ron        # прочитать RON и преобразовать в CSV
    python ron_to_csv.py file.csv        # открыть CSV (RON-массивы восстановятся в List)
    python ron_to_csv.py --no-gui        # без окон, в консоли

Зависимости: polars (pip install polars). tkinter входит в стандартную поставку Python.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import re
import sys
from pathlib import Path
from typing import Any

import polars as pl

Meta = list[tuple[str, str]]

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
    r'\(\s*name:\s*"((?:[^"\\]|\\.)*)"\s*,\s*' r'value:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*\)'
)


def _find_byte_string(text: str) -> tuple[int, int]:
    """Возвращает границы содержимого b\"...\" в поле data.bytes."""
    match = re.search(r'\bbytes\s*:\s*b"', text)
    if match is None:
        raise ValueError('Не найдено поле `bytes: b"..."` в исходном RON')

    start = index = match.end()
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return start, index
        else:
            index += 1
    raise ValueError("Не закрыта байтовая строка в поле data.bytes")


def unescape_rust_bytes(value: str) -> bytes:
    """Декодирует содержимое Rust/RON byte string b\"...\" в bytes."""
    result = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            codepoint = ord(char)
            if codepoint > 0xFF:
                raise ValueError(
                    f"Неожиданный символ вне диапазона байта в data.bytes: {char!r}"
                )
            result.append(codepoint)
            index += 1
            continue

        if index + 1 >= len(value):
            raise ValueError("Незавершённая escape-последовательность в data.bytes")
        escaped = value[index + 1]
        if escaped == "x":
            if index + 3 >= len(value):
                raise ValueError("Неполная hex escape-последовательность в data.bytes")
            result.append(int(value[index + 2 : index + 4], 16))
            index += 4
        elif escaped in _BYTE_ESCAPES:
            result.append(_BYTE_ESCAPES[escaped])
            index += 2
        elif escaped == "\n":
            index += 2
            while index < len(value) and value[index] in " \t\r\n":
                index += 1
        else:
            raise ValueError(
                f"Неизвестная escape-последовательность в data.bytes: \\{escaped}"
            )
    return bytes(result)


def _unescape_ron_string(value: str) -> str:
    """Декодирует escape-последовательности обычной RON-строки."""
    simple = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        '"': '"',
        "'": "'",
        "0": "\0",
    }

    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        if escaped.startswith("u{"):
            return chr(int(escaped[2:-1], 16))
        if escaped.startswith("x") and len(escaped) == 3:
            return chr(int(escaped[1:], 16))
        return simple.get(escaped, escaped)

    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|x[0-9a-fA-F]{2}|.)", replace, value)


def read_ron(path: str | Path) -> tuple[pl.DataFrame, Meta]:
    """Читает исходный RON-контейнер: meta и Arrow IPC stream из data.bytes."""
    text = Path(path).read_text(encoding="utf-8")
    start, end = _find_byte_string(text)
    raw = unescape_rust_bytes(text[start:end])

    try:
        dataframe = pl.read_ipc_stream(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать Arrow IPC из {path}: {exc}") from exc

    meta = [
        (_unescape_ron_string(name), _unescape_ron_string(value))
        for name, value in _META_RE.findall(text[:start])
    ]
    return dataframe, meta


def meta_to_columns(dataframe: pl.DataFrame, meta: Meta) -> pl.DataFrame:
    """Добавляет meta-колонки; повторяющиеся ключи становятся List(String)."""
    grouped: dict[str, list[str]] = {}
    for name, value in meta:
        grouped.setdefault(name, []).append(value)

    used_names = set(dataframe.columns)
    meta_series: list[pl.Series] = []

    for name, values in grouped.items():
        candidate = name or "meta"
        if candidate in used_names:
            candidate = f"meta_{candidate}"
        base = candidate
        suffix = 2
        while candidate in used_names:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used_names.add(candidate)

        if len(values) > 1:
            # Одна ячейка содержит полный список значений ключа (например, двух авторов).
            row_values = [list(values) for _ in range(dataframe.height)]
            dtype = pl.List(pl.String)
        else:
            row_values = [values[0] for _ in range(dataframe.height)]
            dtype = pl.String

        meta_series.append(pl.Series(candidate, row_values, dtype=dtype))

    if not meta_series:
        return dataframe

    meta_dataframe = pl.DataFrame(meta_series)
    return pl.concat([meta_dataframe, dataframe], how="horizontal")


class _RonCellParser:
    """Парсер подмножества RON, которое записывает _ron_value()."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def parse(self) -> Any:
        value = self._value()
        self._skip_ws()
        if self.pos != len(self.text):
            raise ValueError(
                f"Лишние символы в конце RON-значения: {self.text[self.pos:]!r}"
            )
        return value

    def _value(self) -> Any:
        self._skip_ws()
        if self.pos >= len(self.text):
            raise ValueError("Пустое RON-значение")

        char = self.text[self.pos]
        if char == '"':
            return self._string()
        if char == "[":
            return self._sequence("[", "]")
        if char == "{":
            return self._map()
        return self._atom()

    def _string(self) -> str:
        self.pos += 1  # opening quote
        result: list[str] = []
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == '"':
                return "".join(result)
            if char != "\\":
                result.append(char)
                continue

            if self.pos >= len(self.text):
                raise ValueError("Незавершённая escape-последовательность в RON-строке")
            escaped = self.text[self.pos]
            self.pos += 1
            simple = {
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "0": "\0",
                "\\": "\\",
                '"': '"',
                "'": "'",
            }
            if escaped in simple:
                result.append(simple[escaped])
            elif escaped == "x":
                digits = self.text[self.pos : self.pos + 2]
                if len(digits) != 2:
                    raise ValueError(
                        "Неполная \\x escape-последовательность в RON-строке"
                    )
                result.append(chr(int(digits, 16)))
                self.pos += 2
            elif (
                escaped == "u"
                and self.pos < len(self.text)
                and self.text[self.pos] == "{"
            ):
                end = self.text.find("}", self.pos + 1)
                if end < 0:
                    raise ValueError("Незакрытая \\u{...} escape-последовательность")
                result.append(chr(int(self.text[self.pos + 1 : end], 16)))
                self.pos = end + 1
            else:
                raise ValueError(
                    f"Неизвестная escape-последовательность в RON-строке: \\{escaped}"
                )
        raise ValueError("Не закрыта RON-строка")

    def _sequence(self, opening: str, closing: str) -> list[Any]:
        if self.text[self.pos] != opening:
            raise ValueError("Внутренняя ошибка парсера RON")
        self.pos += 1
        values: list[Any] = []
        self._skip_ws()
        if self.pos < len(self.text) and self.text[self.pos] == closing:
            self.pos += 1
            return values
        while True:
            values.append(self._value())
            self._skip_ws()
            if self.pos >= len(self.text):
                raise ValueError("Не закрыт RON-массив")
            char = self.text[self.pos]
            self.pos += 1
            if char == closing:
                return values
            if char != ",":
                raise ValueError(f"Ожидалась запятая или {closing!r} в RON-массиве")
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == closing:
                self.pos += 1  # trailing comma
                return values

    def _map(self) -> dict[Any, Any]:
        self.pos += 1
        result: dict[Any, Any] = {}
        self._skip_ws()
        if self.pos < len(self.text) and self.text[self.pos] == "}":
            self.pos += 1
            return result
        while True:
            key = self._value()
            self._skip_ws()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise ValueError("Ожидалось ':' в RON-словаре")
            self.pos += 1
            result[key] = self._value()
            self._skip_ws()
            if self.pos >= len(self.text):
                raise ValueError("Не закрыт RON-словарь")
            char = self.text[self.pos]
            self.pos += 1
            if char == "}":
                return result
            if char != ",":
                raise ValueError("Ожидалась запятая или '}' в RON-словаре")
            self._skip_ws()
            if self.pos < len(self.text) and self.text[self.pos] == "}":
                self.pos += 1
                return result

    def _atom(self) -> Any:
        start = self.pos
        while (
            self.pos < len(self.text)
            and self.text[self.pos] not in ",]}"
            and not self.text[self.pos].isspace()
        ):
            self.pos += 1
        token = self.text[start : self.pos]
        if token == "true":
            return True
        if token == "false":
            return False
        if token == "None":
            return None
        if token == "NaN":
            return float("nan")
        if token == "inf":
            return float("inf")
        if token == "-inf":
            return float("-inf")
        if not token:
            raise ValueError("Не удалось прочитать RON-значение")
        try:
            return int(token, 10)
        except ValueError:
            try:
                return float(token)
            except ValueError as exc:
                raise ValueError(f"Неподдерживаемое RON-значение: {token!r}") from exc


def _parse_ron_cell(value: str) -> Any:
    """Разбирает скаляр/массив RON, сериализованный в CSV-ячейку скриптом."""
    return _RonCellParser(value).parse()


def read_csv(path: str | Path) -> tuple[pl.DataFrame, Meta]:
    """Открывает CSV и восстанавливает RON-массивы в ячейках как Polars List."""
    try:
        # Не передаём missing_utf8_is_empty_string: этот аргумент есть не
        # во всех версиях Polars. Пустые значения ниже обрабатываются как
        # None или пустая строка.
        dataframe = pl.read_csv(
            path,
            try_parse_dates=True,
        )
    except Exception as exc:
        raise ValueError(f"Не удалось прочитать CSV {path}: {exc}") from exc

    expressions: list[pl.Series] = []
    for column in dataframe.columns:
        series = dataframe.get_column(column)
        if series.dtype != pl.String:
            continue

        raw_values = series.to_list()
        nonempty = [value for value in raw_values if value not in (None, "")]
        if not nonempty:
            continue

        parsed_arrays: list[list[Any]] = []
        found_array = False
        all_are_arrays = True
        for value in nonempty:
            if not isinstance(value, str) or not value.lstrip().startswith("["):
                all_are_arrays = False
                break
            try:
                parsed = _parse_ron_cell(value)
            except (ValueError, TypeError):
                all_are_arrays = False
                break
            if not isinstance(parsed, list):
                all_are_arrays = False
                break
            parsed_arrays.append(parsed)
            found_array = True

        if found_array and all_are_arrays:
            parsed_values: list[Any] = []
            for value in raw_values:
                if value in (None, ""):
                    parsed_values.append(None)
                else:
                    parsed_values.append(_parse_ron_cell(value))

            flat_items = [
                item for array in parsed_values if array is not None for item in array
            ]
            if all(isinstance(item, str) or item is None for item in flat_items):
                restored = pl.Series(
                    column, parsed_values, dtype=pl.List(pl.String), strict=False
                )
            else:
                restored = pl.Series(column, parsed_values, strict=False)
            expressions.append(restored)

    if expressions:
        dataframe = dataframe.with_columns(expressions)
    return dataframe, []


def load_input(path: str | Path) -> tuple[pl.DataFrame, Meta]:
    """Загружает поддерживаемый входной файл по расширению: RON или CSV."""
    suffix = Path(path).suffix.lower()
    if suffix == ".ron":
        dataframe, meta = read_ron(path)
        return meta_to_columns(dataframe, meta), meta
    if suffix == ".csv":
        return read_csv(path)
    raise ValueError(f"Неподдерживаемый формат {suffix!r}; выберите .ron или .csv")


def _ron_string(value: str) -> str:
    """Кодирует строку в обычный RON string literal."""
    escaped: list[str] = []
    for char in value:
        codepoint = ord(char)
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif char == "\0":
            escaped.append("\\0")
        elif codepoint < 0x20 or codepoint == 0x7F:
            escaped.append(f"\\u{{{codepoint:x}}}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _ron_value(value: Any) -> str:
    """Форматирует Python-значение как RON literal для ячейки CSV."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _ron_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_ron_value(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = ", ".join(
            f"{_ron_string(str(key))}: {_ron_value(item)}"
            for key, item in value.items()
        )
        return "{" + entries + "}"
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return _ron_string(value.isoformat())

    # Polars scalar wrappers may expose a native Python value through item().
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _ron_value(item())
        except Exception:
            pass
    return _ron_string(str(value))


def _csv_cell(value: Any) -> str:
    """Lists/структуры записывает как RON; обычные значения — как CSV-текст."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return _ron_value(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def write_csv(dataframe: pl.DataFrame, path: str | Path) -> None:
    """Записывает CSV; list-значения внутри ячеек сериализуются как RON-массивы."""
    with Path(path).open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(
            file,
            delimiter=",",
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            doublequote=True,
            lineterminator="\n",
        )
        writer.writerow(dataframe.columns)
        for row in dataframe.iter_rows():
            writer.writerow([_csv_cell(value) for value in row])


def preview_text(dataframe: pl.DataFrame) -> str:
    schema = "\n".join(f"  {key}: {dtype}" for key, dtype in dataframe.schema.items())
    with pl.Config(tbl_rows=40, tbl_cols=-1, tbl_width_chars=400, fmt_str_lengths=80):
        table = str(dataframe)
    return f"shape: {dataframe.shape}\n\nschema:\n{schema}\n\n{table}"


def _make_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    return root


def _gui_preview(root, text: str, title: str) -> bool:
    import tkinter as tk
    from tkinter import ttk

    result = {"ok": False}
    window = tk.Toplevel(root)
    window.title(title)
    window.geometry("1100x600")
    try:
        window.attributes("-topmost", True)
    except Exception:
        pass

    frame = ttk.Frame(window)
    frame.pack(fill="both", expand=True)
    text_box = tk.Text(frame, wrap="none", font="TkFixedFont")
    y_scroll = ttk.Scrollbar(frame, orient="vertical", command=text_box.yview)
    x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=text_box.xview)
    text_box.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    text_box.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    text_box.insert("1.0", text)
    text_box.configure(state="disabled")

    def done(ok: bool) -> None:
        result["ok"] = ok
        window.destroy()

    buttons = ttk.Frame(window)
    buttons.pack(fill="x", padx=8, pady=8)
    ttk.Button(buttons, text="Сохранить CSV как…", command=lambda: done(True)).pack(
        side="right"
    )
    ttk.Button(buttons, text="Отмена", command=lambda: done(False)).pack(
        side="right", padx=8
    )
    window.protocol("WM_DELETE_WINDOW", lambda: done(False))
    window.grab_set()
    root.wait_window(window)
    return result["ok"]


def _verify_csv(
    path: str | Path, expected_columns: list[str], expected_rows: int
) -> bool:
    """Проверяет заголовок и число строк в созданном CSV."""
    with Path(path).open("r", encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        try:
            header = next(reader)
        except StopIteration:
            return False
        row_count = sum(1 for _ in reader)
    return header == expected_columns and row_count == expected_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", nargs="?", help="путь к исходному .ron или .csv файлу")
    parser.add_argument(
        "--no-gui", action="store_true", help="работать без окон, в консоли"
    )
    args = parser.parse_args(argv)

    root = None
    if not args.no_gui:
        try:
            root = _make_root()
        except Exception as exc:
            print(f"Окна недоступны ({exc}), работаю в консоли.")

    if args.input:
        source = Path(args.input)
    elif root is not None:
        from tkinter import filedialog

        chosen = filedialog.askopenfilename(
            parent=root,
            title="Выберите исходный RON или CSV файл",
            filetypes=[
                ("RON и CSV files", "*.ron *.csv"),
                ("RON files", "*.ron"),
                ("CSV files", "*.csv"),
                ("Все файлы", "*.*"),
            ],
        )
        if not chosen:
            root.destroy()
            return 0
        source = Path(chosen)
    else:
        raw = input("Путь к .ron или .csv: ").strip().strip('"')
        if not raw:
            return 0
        source = Path(raw)

    try:
        output_dataframe, meta = load_input(source)
    except Exception as exc:
        print(f"Ошибка чтения/обработки: {exc}", file=sys.stderr)
        if root is not None:
            root.destroy()
        return 1

    duplicate_count = sum(1 for values in _group_meta(meta).values() if len(values) > 1)
    print(
        f"Прочитано: {source.name}; строк: {output_dataframe.height}; "
        f"meta-записей: {len(meta)}; повторяющихся ключей: {duplicate_count}; "
        f"формат входа: {source.suffix.lower()}"
    )
    print(
        'Списки в CSV будут записаны как RON-массивы, например: ["Автор 1", "Автор 2"].'
    )

    preview = preview_text(output_dataframe)
    if root is not None:
        if not _gui_preview(root, preview, f"Превью CSV: {source.name}"):
            root.destroy()
            return 0
    else:
        print(preview)
        if input("\nСохранить в CSV? [y/N] ").strip().lower() != "y":
            return 0

    default_suffix = "_long.csv" if source.suffix.lower() == ".ron" else "_copy.csv"
    default = source.with_name(f"{source.stem}{default_suffix}")
    if root is not None:
        from tkinter import filedialog

        chosen = filedialog.asksaveasfilename(
            parent=root,
            title="Сохранить CSV",
            defaultextension=".csv",
            initialdir=str(source.parent),
            initialfile=default.name,
            filetypes=[("CSV files", "*.csv")],
        )
        if not chosen:
            root.destroy()
            return 0
        destination = Path(chosen)
    else:
        raw = input(f"Куда сохранить [{default}]: ").strip().strip('"')
        destination = Path(raw) if raw else default

    if destination.suffix.lower() != ".csv":
        destination = destination.with_suffix(".csv")

    try:
        write_csv(output_dataframe, destination)
        ok = _verify_csv(destination, output_dataframe.columns, output_dataframe.height)
    except Exception as exc:
        print(f"Ошибка сохранения CSV: {exc}", file=sys.stderr)
        if root is not None:
            root.destroy()
        return 1

    print(f"Сохранено: {destination}")
    print("Проверка CSV (заголовок и число строк):", "OK" if ok else "ОШИБКА")

    if root is not None:
        root.destroy()
    return 0 if ok else 1


def _group_meta(meta: Meta) -> dict[str, list[str]]:
    """Группирует meta в исходном порядке для подсчёта повторов."""
    grouped: dict[str, list[str]] = {}
    for name, value in meta:
        grouped.setdefault(name, []).append(value)
    return grouped


if __name__ == "__main__":
    sys.exit(main())
