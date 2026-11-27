"""Чтение RON (с Arrow IPC внутри исходного файла) -> Polars -> CSV.

Повторяющиеся ключи meta становятся одной колонкой List(String).
В GUI можно одновременно открыть несколько файлов, переключать предпросмотр
выделенного файла, синхронно скрывать одноимённые столбцы во всех файлах и
сохранять как отдельный файл, так и все файлы разом.
В окне предпросмотра можно скрывать и переставлять столбцы; эти настройки
применяются к итоговому CSV. В режиме --no-gui доступна настройка через консоль.
В CSV значения list-колонок записываются как настоящие RON-массивы,
например ["Автор 1", "Автор 2"], а CSV-экранирование выполняется отдельно.

Запуск:
    python ron_to_csv.py                 # выбор одного или нескольких .ron / .csv через окно
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


def _gui_preview(root, loaded_files: list[tuple[pl.DataFrame, Path, Meta]]) -> None:
    """Показывает несколько файлов; видимость одноимённых столбцов общая для всех."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    def make_file_state(dataframe: pl.DataFrame, source: Path, meta: Meta) -> dict[str, Any]:
        columns = list(dataframe.columns)
        return {
            "dataframe": dataframe,
            "source": source,
            "meta": meta,
            "all_columns": columns,
            "column_order": list(columns),
            "visible_columns": set(columns),
        }

    files = [
        make_file_state(dataframe, source, meta)
        for dataframe, source, meta in loaded_files
    ]
    selected_file = 0
    preview_rows = 300
    drag_data: dict[str, int | None] = {"index": None}

    window = tk.Toplevel(root)
    window.title("Предпросмотр RON / CSV")
    window.geometry("1450x760")
    window.minsize(1050, 520)
    try:
        window.attributes("-topmost", True)
    except Exception:
        pass

    header = ttk.Frame(window, padding=(10, 8, 10, 4))
    header.pack(fill="x")
    header_text = tk.StringVar()
    ttk.Label(header, textvariable=header_text).pack(
        side="left", anchor="w", fill="x", expand=True
    )

    body = ttk.Panedwindow(window, orient="horizontal")
    body.pack(fill="both", expand=True, padx=10, pady=6)

    controls = ttk.Frame(body, padding=8)
    preview_frame = ttk.Frame(body, padding=4)
    body.add(controls, weight=0)
    body.add(preview_frame, weight=1)

    # Список исходных файлов: выделение переключает таблицу справа.
    ttk.Label(controls, text="Файлы", font=("TkDefaultFont", 10, "bold")).pack(
        anchor="w", pady=(0, 3)
    )
    file_frame = ttk.Frame(controls)
    file_frame.pack(fill="x")
    file_list = tk.Listbox(
        file_frame,
        width=38,
        height=7,
        exportselection=False,
        activestyle="dotbox",
        font="TkDefaultFont",
    )
    file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=file_list.yview)
    file_list.configure(yscrollcommand=file_scroll.set)
    file_list.pack(side="left", fill="x", expand=True)
    file_scroll.pack(side="right", fill="y")

    open_button = ttk.Button(controls, text="Открыть файлы…")
    open_button.pack(fill="x", pady=(5, 10))

    ttk.Separator(controls, orient="horizontal").pack(fill="x", pady=(0, 8))
    ttk.Label(controls, text="Столбцы CSV", font=("TkDefaultFont", 10, "bold")).pack(
        anchor="w", pady=(0, 3)
    )
    ttk.Label(
        controls,
        text=(
            "Перетаскивайте для изменения порядка.\n"
            "Скрытие/возврат столбца применяется\n"
            "ко всем файлам с таким именем."
        ),
        justify="left",
    ).pack(anchor="w", pady=(0, 7))

    list_frame = ttk.Frame(controls)
    list_frame.pack(fill="both", expand=True)
    column_list = tk.Listbox(
        list_frame,
        width=38,
        height=18,
        exportselection=False,
        activestyle="dotbox",
        font="TkDefaultFont",
    )
    list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=column_list.yview)
    column_list.configure(yscrollcommand=list_scroll.set)
    column_list.pack(side="left", fill="both", expand=True)
    list_scroll.pack(side="right", fill="y")

    action_buttons = ttk.Frame(controls)
    action_buttons.pack(fill="x", pady=(8, 0))
    toggle_button = ttk.Button(action_buttons, text="Скрыть столбец везде")
    toggle_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
    up_button = ttk.Button(action_buttons, text="↑ Выше")
    down_button = ttk.Button(action_buttons, text="↓ Ниже")
    up_button.grid(row=1, column=0, sticky="ew", padx=(0, 3))
    down_button.grid(row=1, column=1, sticky="ew", padx=(3, 0))
    ttk.Button(
        action_buttons, text="Показать все", command=lambda: set_all_visible(True)
    ).grid(row=2, column=0, sticky="ew", padx=(0, 3), pady=(5, 0))
    ttk.Button(
        action_buttons, text="Скрыть все", command=lambda: set_all_visible(False)
    ).grid(row=2, column=1, sticky="ew", padx=(3, 0), pady=(5, 0))
    action_buttons.columnconfigure(0, weight=1)
    action_buttons.columnconfigure(1, weight=1)

    table_frame = ttk.Frame(preview_frame)
    table_frame.pack(fill="both", expand=True)
    tree = ttk.Treeview(table_frame, show="headings")
    y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    table_frame.rowconfigure(0, weight=1)
    table_frame.columnconfigure(0, weight=1)

    status_var = tk.StringVar(value="")
    ttk.Label(preview_frame, textvariable=status_var).pack(anchor="w", pady=(5, 0))

    def current_file() -> dict[str, Any]:
        return files[selected_file]

    def selected_column_index() -> int | None:
        selection = column_list.curselection()
        return int(selection[0]) if selection else None

    def refresh_file_list(select_index: int | None = None) -> None:
        file_list.delete(0, tk.END)
        name_counts: dict[str, int] = {}
        for item in files:
            name_counts[item["source"].name] = name_counts.get(item["source"].name, 0) + 1
        for item in files:
            source = item["source"]
            label = str(source) if name_counts[source.name] > 1 else source.name
            file_list.insert(tk.END, label)
        if select_index is not None and files:
            select_index = max(0, min(select_index, len(files) - 1))
            file_list.selection_clear(0, tk.END)
            file_list.selection_set(select_index)
            file_list.activate(select_index)
            file_list.see(select_index)

    def refresh_column_list(select_index: int | None = None) -> None:
        item = current_file()
        column_list.delete(0, tk.END)
        for name in item["column_order"]:
            marker = "[✓]" if name in item["visible_columns"] else "[ ]"
            column_list.insert(tk.END, f"{marker}  {name}")
        if select_index is not None and item["column_order"]:
            select_index = max(0, min(select_index, len(item["column_order"]) - 1))
            column_list.selection_set(select_index)
            column_list.activate(select_index)
            column_list.see(select_index)
        update_toggle_button()

    def update_toggle_button(*_args) -> None:
        index = selected_column_index()
        if index is None:
            toggle_button.configure(text="Скрыть столбец везде", state="disabled")
            up_button.configure(state="disabled")
            down_button.configure(state="disabled")
            return
        item = current_file()
        name = item["column_order"][index]
        is_visible = name in item["visible_columns"]
        toggle_button.configure(
            text="Скрыть столбец везде" if is_visible else "Вернуть столбец везде",
            state="normal",
        )
        up_button.configure(state="normal" if index > 0 else "disabled")
        down_button.configure(
            state="normal" if index < len(item["column_order"]) - 1 else "disabled"
        )

    def update_header() -> None:
        item = current_file()
        dataframe = item["dataframe"]
        source = item["source"]
        header_text.set(
            f"Файл: {source.name}    Строк: {dataframe.height:,}    "
            f"Столбцов: {len(item['all_columns'])}    Загружено файлов: {len(files)}"
        )
        window.title(f"Предпросмотр CSV: {source.name}")

    def render_preview() -> None:
        item = current_file()
        dataframe = item["dataframe"]
        shown = [name for name in item["column_order"] if name in item["visible_columns"]]
        tree.delete(*tree.get_children())
        tree.configure(columns=shown)
        for name in shown:
            tree.heading(name, text=name)
            tree.column(name, width=170, minwidth=80, stretch=True, anchor="w")

        if shown:
            sample = dataframe.select(shown).head(preview_rows)
            for row in sample.iter_rows():
                cells = []
                for value in row:
                    cell = _csv_cell(value)
                    if len(cell) > 300:
                        cell = cell[:297] + "..."
                    cells.append(cell)
                tree.insert("", "end", values=cells)
            shown_rows = min(dataframe.height, preview_rows)
            suffix = (
                f"Показаны первые {shown_rows:,} из {dataframe.height:,} строк."
                if dataframe.height > preview_rows
                else f"Строк показано: {shown_rows:,}."
            )
        else:
            suffix = "Все столбцы скрыты. Верните хотя бы один столбец для сохранения."
        status_var.set(
            f"В CSV: {len(shown)} из {len(item['all_columns'])} столбцов. {suffix}"
        )
        save_button.configure(state="normal" if shown else "disabled")
        has_any_exportable = any(
            any(name in file_item["visible_columns"] for name in file_item["all_columns"])
            for file_item in files
        )
        save_all_button.configure(state="normal" if has_any_exportable else "disabled")

    def display_selected_file(index: int) -> None:
        nonlocal selected_file
        if not 0 <= index < len(files):
            return
        selected_file = index
        update_header()
        refresh_column_list(0 if current_file()["column_order"] else None)
        render_preview()

    def on_file_select(_event=None) -> None:
        selection = file_list.curselection()
        if selection:
            display_selected_file(int(selection[0]))

    def toggle_selected() -> None:
        index = selected_column_index()
        if index is None:
            return
        item = current_file()
        name = item["column_order"][index]
        make_visible = name not in item["visible_columns"]

        # Синхронизируем видимость одноимённого столбца во всех загруженных файлах.
        for file_item in files:
            if name in file_item["all_columns"]:
                if make_visible:
                    file_item["visible_columns"].add(name)
                else:
                    file_item["visible_columns"].discard(name)

        refresh_column_list(index)
        render_preview()

    def move_selected(delta: int) -> None:
        index = selected_column_index()
        if index is None:
            return
        item = current_file()
        target = index + delta
        if not 0 <= target < len(item["column_order"]):
            return
        item["column_order"][index], item["column_order"][target] = (
            item["column_order"][target],
            item["column_order"][index],
        )
        refresh_column_list(target)
        render_preview()

    def set_all_visible(visible: bool) -> None:
        # Команды «Показать все» и «Скрыть все» также действуют на весь список файлов.
        for file_item in files:
            if visible:
                file_item["visible_columns"].update(file_item["all_columns"])
            else:
                file_item["visible_columns"].clear()
        refresh_column_list(selected_column_index() or 0)
        render_preview()

    def on_drag_start(event) -> None:
        index = column_list.nearest(event.y)
        drag_data["index"] = (
            index if 0 <= index < len(current_file()["column_order"]) else None
        )

    def on_drag_end(event) -> None:
        source_index = drag_data["index"]
        drag_data["index"] = None
        item = current_file()
        if source_index is None or not item["column_order"]:
            return
        target_index = column_list.nearest(event.y)
        target_index = max(0, min(target_index, len(item["column_order"]) - 1))
        if source_index == target_index:
            return
        column = item["column_order"].pop(source_index)
        item["column_order"].insert(target_index, column)
        refresh_column_list(target_index)
        render_preview()

    def on_open_files() -> None:
        chosen = filedialog.askopenfilenames(
            parent=window,
            title="Открыть один или несколько RON / CSV файлов",
            initialdir=str(current_file()["source"].parent),
            filetypes=[
                ("RON и CSV files", "*.ron *.csv"),
                ("RON files", "*.ron"),
                ("CSV files", "*.csv"),
                ("Все файлы", "*.*"),
            ],
        )
        if not chosen:
            return

        existing = {item["source"].resolve() for item in files}
        errors: list[str] = []
        added_indices: list[int] = []
        for filename in chosen:
            new_source = Path(filename)
            try:
                resolved = new_source.resolve()
                if resolved in existing:
                    continue
                new_dataframe, new_meta = load_input(new_source)
                new_item = make_file_state(new_dataframe, new_source, new_meta)

                # Для новых файлов учитываем уже заданные общие исключения столбцов.
                hidden_names = {
                    column_name
                    for old_item in files
                    for column_name in old_item["all_columns"]
                    if column_name not in old_item["visible_columns"]
                }
                new_item["visible_columns"].difference_update(hidden_names)

                files.append(new_item)
                existing.add(resolved)
                added_indices.append(len(files) - 1)
            except Exception as exc:
                errors.append(f"{new_source}\n{exc}")

        if added_indices:
            refresh_file_list(added_indices[-1])
            display_selected_file(added_indices[-1])
        if errors:
            messagebox.showerror(
                "Некоторые файлы не удалось открыть",
                "\n\n".join(errors),
                parent=window,
            )
        elif not added_indices:
            messagebox.showinfo(
                "Открытие файлов",
                "Новых файлов не добавлено (возможно, они уже загружены).",
                parent=window,
            )

    def get_visible_dataframe(item: dict[str, Any]) -> pl.DataFrame | None:
        shown = [
            name for name in item["column_order"] if name in item["visible_columns"]
        ]
        return item["dataframe"].select(shown) if shown else None

    def on_save() -> None:
        item = current_file()
        output_dataframe = get_visible_dataframe(item)
        if output_dataframe is None:
            return

        source = item["source"]
        default_suffix = "_long.csv" if source.suffix.lower() == ".ron" else "_copy.csv"
        default = source.with_name(f"{source.stem}{default_suffix}")
        chosen = filedialog.asksaveasfilename(
            parent=window,
            title=f"Сохранить CSV для {source.name}",
            defaultextension=".csv",
            initialdir=str(source.parent),
            initialfile=default.name,
            filetypes=[("CSV files", "*.csv")],
        )
        if not chosen:
            return

        destination = Path(chosen)
        if destination.suffix.lower() != ".csv":
            destination = destination.with_suffix(".csv")

        try:
            write_csv(output_dataframe, destination)
            ok = _verify_csv(
                destination, output_dataframe.columns, output_dataframe.height
            )
        except Exception as exc:
            messagebox.showerror(
                "Ошибка сохранения CSV",
                f"Не удалось сохранить файл:\n{destination}\n\n{exc}",
                parent=window,
            )
            return

        if ok:
            messagebox.showinfo(
                "CSV сохранён",
                f"Файл сохранён:\n{destination}\n\n"
                f"Строк: {output_dataframe.height:,}; "
                f"столбцов: {len(output_dataframe.columns)}.\n"
                "Программа остаётся открытой.",
                parent=window,
            )
        else:
            messagebox.showwarning(
                "Проверка CSV",
                f"Файл записан, но проверка заголовка или числа строк не пройдена:\n{destination}",
                parent=window,
            )

    def unique_batch_path(folder: Path, source: Path, reserved: set[Path]) -> Path:
        suffix = "_long.csv" if source.suffix.lower() == ".ron" else "_copy.csv"
        candidate = folder / f"{source.stem}{suffix}"
        counter = 2
        while candidate.exists() or candidate.resolve() in reserved:
            candidate = folder / f"{source.stem}{suffix[:-4]}_{counter}.csv"
            counter += 1
        reserved.add(candidate.resolve())
        return candidate

    def on_save_all() -> None:
        exportable = [item for item in files if get_visible_dataframe(item) is not None]
        skipped = [item["source"].name for item in files if get_visible_dataframe(item) is None]
        if not exportable:
            messagebox.showwarning(
                "Нет столбцов для сохранения",
                "Во всех файлах скрыты все столбцы. Сначала верните нужные столбцы.",
                parent=window,
            )
            return

        folder_name = filedialog.askdirectory(
            parent=window,
            title="Выберите папку для сохранения всех CSV",
            initialdir=str(current_file()["source"].parent),
            mustexist=True,
        )
        if not folder_name:
            return

        folder = Path(folder_name)
        reserved: set[Path] = set()
        saved: list[Path] = []
        errors: list[str] = []
        for item in exportable:
            source = item["source"]
            output_dataframe = get_visible_dataframe(item)
            assert output_dataframe is not None
            destination = unique_batch_path(folder, source, reserved)
            try:
                write_csv(output_dataframe, destination)
                if not _verify_csv(
                    destination, output_dataframe.columns, output_dataframe.height
                ):
                    raise ValueError("проверка заголовка или числа строк не пройдена")
                saved.append(destination)
            except Exception as exc:
                errors.append(f"{source.name} → {destination.name}: {exc}")

        lines = [
            f"Папка: {folder}",
            f"Успешно сохранено: {len(saved)} из {len(exportable)} файлов.",
        ]
        if skipped:
            lines.append("Пропущены (все столбцы скрыты): " + ", ".join(skipped))
        if errors:
            lines.append("Ошибки сохранения:\n" + "\n".join(errors))
        if saved:
            lines.append("\nСозданные файлы:\n" + "\n".join(path.name for path in saved))

        if errors:
            messagebox.showwarning("Сохранение завершено с ошибками", "\n\n".join(lines), parent=window)
        else:
            messagebox.showinfo("Сохранение всех файлов", "\n\n".join(lines), parent=window)

    def on_close() -> None:
        window.destroy()

    file_list.bind("<<ListboxSelect>>", on_file_select)
    toggle_button.configure(command=toggle_selected)
    up_button.configure(command=lambda: move_selected(-1))
    down_button.configure(command=lambda: move_selected(1))
    column_list.bind("<<ListboxSelect>>", update_toggle_button)
    column_list.bind("<Double-Button-1>", lambda _event: toggle_selected())
    column_list.bind("<ButtonPress-1>", on_drag_start, add="+")
    column_list.bind("<ButtonRelease-1>", on_drag_end, add="+")
    open_button.configure(command=on_open_files)

    footer = ttk.Frame(window, padding=(10, 4, 10, 10))
    footer.pack(fill="x")
    ttk.Button(footer, text="Закрыть", command=on_close).pack(side="right", padx=(8, 0))
    save_all_button = ttk.Button(footer, text="Сохранить все…", command=on_save_all)
    save_all_button.pack(side="right", padx=(8, 0))
    save_button = ttk.Button(
        footer, text="Сохранить выделенный в CSV как…", command=on_save
    )
    save_button.pack(side="right", padx=(8, 0))

    refresh_file_list(0)
    update_header()
    refresh_column_list(0 if current_file()["column_order"] else None)
    render_preview()
    window.bind("<Control-o>", lambda _event: on_open_files())
    window.bind("<Control-s>", lambda _event: on_save())
    window.bind("<Control-Shift-S>", lambda _event: on_save_all())
    window.protocol("WM_DELETE_WINDOW", on_close)
    window.grab_set()
    root.wait_window(window)

def _console_configure_columns(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Интерактивно настраивает видимые столбцы и их порядок в режиме --no-gui."""
    columns = list(dataframe.columns)
    if not columns:
        return dataframe

    print("\nСтолбцы (нумерация с 1):")
    for index, name in enumerate(columns, start=1):
        print(f"  {index:>3}. {name}")

    while True:
        raw_hidden = input(
            "Номера столбцов, которые скрыть (через запятую; Enter — оставить все): "
        ).strip()
        try:
            hidden_indices = {
                int(item.strip()) for item in raw_hidden.split(",") if item.strip()
            }
            if any(index < 1 or index > len(columns) for index in hidden_indices):
                raise ValueError
        except ValueError:
            print(f"Введите номера от 1 до {len(columns)} через запятую.")
            continue

        visible = [
            name
            for index, name in enumerate(columns, start=1)
            if index not in hidden_indices
        ]
        if visible:
            break
        print("Нельзя скрыть все столбцы. Оставьте хотя бы один.")

    print("\nТекущий порядок доступных столбцов:")
    for index, name in enumerate(visible, start=1):
        print(f"  {index:>3}. {name}")
    raw_order = input(
        "Новый порядок номеров (например, 3,1,2; Enter — без изменений): "
    ).strip()
    if raw_order:
        try:
            indices = [int(item.strip()) for item in raw_order.split(",")]
            if sorted(indices) != list(range(1, len(visible) + 1)):
                raise ValueError
            visible = [visible[index - 1] for index in indices]
        except ValueError:
            print(
                "Порядок не изменён: нужны все номера доступных столбцов ровно по одному."
            )

    return dataframe.select(visible)


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

    # В GUI можно выбрать сразу несколько файлов. Окно остаётся открытым
    # после сохранения, а кнопка «Открыть файлы» добавляет новые файлы в список.
    if root is not None:
        from tkinter import filedialog, messagebox

        if args.input:
            input_paths = [Path(args.input)]
        else:
            chosen = filedialog.askopenfilenames(
                parent=root,
                title="Выберите один или несколько RON / CSV файлов",
                filetypes=[
                    ("RON и CSV files", "*.ron *.csv"),
                    ("RON files", "*.ron"),
                    ("CSV files", "*.csv"),
                    ("Все файлы", "*.*"),
                ],
            )
            input_paths = [Path(value) for value in chosen]

        if not input_paths:
            root.destroy()
            return 0

        loaded_files: list[tuple[pl.DataFrame, Path, Meta]] = []
        errors: list[str] = []
        for source in input_paths:
            try:
                dataframe, meta = load_input(source)
                loaded_files.append((dataframe, source, meta))
            except Exception as exc:
                errors.append(f"{source}\n{exc}")

        if errors:
            messagebox.showerror(
                "Ошибки чтения файлов",
                "Не удалось открыть некоторые файлы:\n\n" + "\n\n".join(errors),
                parent=root,
            )
        if not loaded_files:
            root.destroy()
            return 1 if errors else 0

        _gui_preview(root, loaded_files)
        root.destroy()
        return 0

    # Консольный режим --no-gui оставлен без изменений.
    if args.input:
        source = Path(args.input)
    else:
        raw = input("Путь к .ron или .csv: ").strip().strip('"')
        if not raw:
            return 0
        source = Path(raw)

    try:
        output_dataframe, meta = load_input(source)
    except Exception as exc:
        print(f"Ошибка чтения/обработки: {exc}", file=sys.stderr)
        return 1

    output_dataframe = _console_configure_columns(output_dataframe)
    print("\nПредпросмотр итогового CSV:")
    print(preview_text(output_dataframe))
    if input("\nСохранить в CSV? [y/N] ").strip().lower() != "y":
        return 0

    duplicate_count = sum(1 for values in _group_meta(meta).values() if len(values) > 1)
    print(
        f"Прочитано: {source.name}; строк: {output_dataframe.height}; "
        f"meta-записей: {len(meta)}; повторяющихся ключей: {duplicate_count}; "
        f"формат входа: {source.suffix.lower()}"
    )
    print(
        'Списки в CSV будут записаны как RON-массивы, например: ["Автор 1", "Автор 2"].'
    )

    default_suffix = "_long.csv" if source.suffix.lower() == ".ron" else "_copy.csv"
    default = source.with_name(f"{source.stem}{default_suffix}")
    raw = input(f"Куда сохранить [{default}]: ").strip().strip('"')
    destination = Path(raw) if raw else default

    if destination.suffix.lower() != ".csv":
        destination = destination.with_suffix(".csv")

    try:
        write_csv(output_dataframe, destination)
        ok = _verify_csv(destination, output_dataframe.columns, output_dataframe.height)
    except Exception as exc:
        print(f"Ошибка сохранения CSV: {exc}", file=sys.stderr)
        return 1

    print(f"Сохранено: {destination}")
    print("Проверка CSV (заголовок и число строк):", "OK" if ok else "ОШИБКА")
    return 0 if ok else 1

def _group_meta(meta: Meta) -> dict[str, list[str]]:
    """Группирует meta в исходном порядке для подсчёта повторов."""
    grouped: dict[str, list[str]] = {}
    for name, value in meta:
        grouped.setdefault(name, []).append(value)
    return grouped


if __name__ == "__main__":
    sys.exit(main())
