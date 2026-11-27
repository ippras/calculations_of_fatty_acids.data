"""Выбирает несколько CSV, приводит порядок колонок и форматирует Value.

Запуск:
    python format_csv_files.py

Без аргументов откроется окно выбора нескольких CSV-файлов.
Можно также передать пути из командной строки:
    python format_csv_files.py file1.csv file2.csv

Результаты сохраняются рядом с исходниками с суффиксом _formatted.csv.
"""

from __future__ import annotations

import csv
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# НАСТРОЙКИ
# ---------------------------------------------------------------------------

# Варианты:
#   "trim"  — убрать только незначащие нули: 12.3400 -> 12.34, 5.000 -> 5.
#             Числовое значение не округляется.
#   "fixed" — записывать ровно DECIMAL_PLACES знаков: 12.3 -> 12.30.
#             Если знаков больше заданного количества, число округляется.
#   "keep"  — оставить исходное текстовое представление Value без изменений.
#   "f64"   — форматировать как десятичную запись f64: всегда минимум один
#             знак после точки (12 -> 12.0), не округляя дробную часть.
#   "min"   — сохранять минимум MIN_DECIMAL_PLACES знаков после точки,
#             убирая лишние конечные нули без округления:
#             0.150 -> 0.15, 0.1556 -> 0.1556, 0.10 -> 0.10.
VALUE_FORMAT = "min"

# Используется только при VALUE_FORMAT = "fixed".
DECIMAL_PLACES = 2

# Используется только при VALUE_FORMAT = "min".
# Минимальное количество знаков после десятичной точки.
MIN_DECIMAL_PLACES = 2

# True — умножать Value на 3, если StereospecificNumbers равно 1, 2 или 3.
# False — не менять значения по этому правилу.
MULTIPLY_SN_VALUES_BY_3 = False

# Порядок стандартных колонок текущего формата.
# Колонки, которых нет в списке, останутся после стандартных в исходном порядке.
COLUMN_ORDER = [
    "DOI",
    "Index",
    "Date",
    "Genus",
    "Species",
    "Name",
    "Lipid",
    "StereospecificNumbers",
    "Method",
    "Label",
    "FattyAcid",
    "Value",
]

# Имя выходного файла: <исходное имя> + этот суффикс + .csv
OUTPUT_SUFFIX = "_formatted"

# True — если результат с таким именем уже существует, перезаписать его.
OVERWRITE_EXISTING_OUTPUT = True

# Дополнительные неизвестные колонки сортировать по алфавиту?
# False — оставить их в исходном порядке.
SORT_EXTRA_COLUMNS_ALPHABETICALLY = False

# ---------------------------------------------------------------------------


def choose_csv_files() -> tuple[str, ...]:
    """Открывает диалог выбора одного или нескольких CSV-файлов."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter недоступен. Передайте пути к CSV-файлам аргументами командной строки."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askopenfilenames(
            parent=root,
            title="Выберите CSV-файлы для обработки",
            filetypes=[("CSV-файлы", "*.csv"), ("Все файлы", "*.*")],
        )
        return tuple(selected)
    finally:
        root.destroy()


def ordered_columns(fieldnames: list[str]) -> list[str]:
    """Возвращает стандартные колонки в заданном порядке, затем остальные."""
    present = set(fieldnames)
    standard = [column for column in COLUMN_ORDER if column in present]
    extra = [column for column in fieldnames if column not in COLUMN_ORDER]

    if SORT_EXTRA_COLUMNS_ALPHABETICALLY:
        extra.sort(key=str.casefold)

    return standard + extra


def format_value(
    raw_value: str | None,
    multiplier: Decimal = Decimal(1),
) -> str:
    """При необходимости умножает и форматирует Value.

    Пустые значения, EPSILON и любые нечисловые маркеры остаются без изменений.
    В режиме trim не выполняется округление.
    """
    if raw_value is None:
        return ""

    value = str(raw_value).strip()
    if not value:
        return ""

    if VALUE_FORMAT == "keep" and multiplier == 1:
        return raw_value

    # Не преобразуем текстовые маркеры (например, EPSILON) и неизвестные значения.
    try:
        number = Decimal(value)
    except InvalidOperation:
        return raw_value

    if not number.is_finite():
        return raw_value

    if multiplier != 1:
        # Достаточная точность для умножения длинных десятичных значений.
        required_precision = max(
            50,
            len(number.as_tuple().digits) + abs(number.adjusted()) + 10,
        )
        with localcontext() as context:
            context.prec = required_precision
            number *= multiplier

    if VALUE_FORMAT == "keep":
        return format(number, "f")

    if number == 0:
        number = abs(number)  # не выводить -0 или -0.00

    if VALUE_FORMAT in {"trim", "f64"}:
        # Формат fixed-point исключает экспоненциальную запись; убираем
        # только незначащие нули после десятичной точки.
        text = format(number, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if not text:
            text = "0"

        if VALUE_FORMAT == "f64" and "." not in text:
            # Сохраняем float-представление даже для целых значений: 12 -> 12.0.
            text += ".0"
        return text

    if VALUE_FORMAT == "min":
        if not isinstance(MIN_DECIMAL_PLACES, int) or MIN_DECIMAL_PLACES < 0:
            raise ValueError("MIN_DECIMAL_PLACES должен быть целым числом >= 0.")

        # Убираем конечные нули, только пока не достигнут заданный минимум.
        # Дробная часть не округляется и значащие цифры не изменяются.
        text = format(number, "f")
        if "." in text:
            integer_part, fractional_part = text.split(".", 1)
            fractional_part = fractional_part.rstrip("0")
            fractional_part = fractional_part.ljust(MIN_DECIMAL_PLACES, "0")
            return f"{integer_part}.{fractional_part}"

        if MIN_DECIMAL_PLACES == 0:
            return text
        return f"{text}.{('0' * MIN_DECIMAL_PLACES)}"

    if VALUE_FORMAT == "fixed":
        if not isinstance(DECIMAL_PLACES, int) or DECIMAL_PLACES < 0:
            raise ValueError("DECIMAL_PLACES должен быть целым числом >= 0.")
        quantum = Decimal(1).scaleb(-DECIMAL_PLACES)
        # Повышаем precision, чтобы можно было форматировать длинные значения.
        required_precision = max(
            50,
            len(number.as_tuple().digits) + DECIMAL_PLACES + abs(number.adjusted()) + 10,
        )
        with localcontext() as context:
            context.prec = required_precision
            rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
        if rounded == 0:
            rounded = abs(rounded)
        return f"{rounded:.{DECIMAL_PLACES}f}"

    raise ValueError(
        f"Неизвестный VALUE_FORMAT={VALUE_FORMAT!r}. "
        "Используйте 'trim', 'fixed', 'f64', 'min' или 'keep'."
    )


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Читает CSV с UTF-8 BOM или без него."""
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("Файл пустой или не содержит строки заголовка.")
        fieldnames = list(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            # DictReader использует ключ None, если в строке лишние поля.
            if None in row:
                raise ValueError(
                    f"Строка {row_number}: найдено больше значений, чем колонок."
                )
            rows.append({
                column: (row.get(column) if row.get(column) is not None else "")
                for column in fieldnames
            })
    return fieldnames, rows


def process_file(input_file: str | Path) -> Path:
    """Сортирует колонки и форматирует Value в одном CSV-файле."""
    source = Path(input_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    fieldnames, rows = read_csv(source)
    if "Value" not in fieldnames:
        raise ValueError(f"В файле нет колонки 'Value': {source.name}")

    if MULTIPLY_SN_VALUES_BY_3 and "StereospecificNumbers" not in fieldnames:
        raise ValueError(
            f"Для умножения значений sn-1/sn-2/sn-3 нужна колонка "
            f"'StereospecificNumbers': {source.name}"
        )

    output_columns = ordered_columns(fieldnames)
    for row in rows:
        sn_value = row.get("StereospecificNumbers", "").strip()
        multiplier = Decimal(3) if (
            MULTIPLY_SN_VALUES_BY_3 and sn_value in {"1", "2", "3"}
        ) else Decimal(1)
        row["Value"] = format_value(row.get("Value", ""), multiplier)

    output = source.with_name(source.stem + OUTPUT_SUFFIX + source.suffix)
    if output.exists() and not OVERWRITE_EXISTING_OUTPUT:
        counter = 1
        while True:
            candidate = source.with_name(
                f"{source.stem}{OUTPUT_SUFFIX}_{counter}{source.suffix}"
            )
            if not candidate.exists():
                output = candidate
                break
            counter += 1

    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=output_columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Готово: {source.name} -> {output.name} ({len(rows)} строк)")
    return output


def main(args: Iterable[str] | None = None) -> int:
    paths = tuple(args if args is not None else sys.argv[1:])
    if not paths:
        paths = choose_csv_files()

    if not paths:
        print("Файлы не выбраны. Работа завершена.")
        return 0

    succeeded: list[Path] = []
    failed: list[tuple[str, str]] = []

    for path in paths:
        try:
            succeeded.append(process_file(path))
        except Exception as exc:
            failed.append((str(path), str(exc)))
            print(f"ОШИБКА: {path}: {exc}", file=sys.stderr)

    print("\nИТОГ")
    print(f"Успешно обработано: {len(succeeded)}")
    print(f"С ошибками: {len(failed)}")
    for output in succeeded:
        print(f"  {output}")
    for name, error in failed:
        print(f"  {name}: {error}")

    # Показываем итоговое окно, если скрипт запущен обычным способом на Windows.
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        details = [f"Успешно обработано: {len(succeeded)}", f"С ошибками: {len(failed)}"]
        if failed:
            details.append("\n" + "\n".join(f"{Path(name).name}: {error}" for name, error in failed))
        messagebox.showinfo("Обработка CSV завершена", "\n".join(details), parent=root)
        root.destroy()
    except Exception:
        pass

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
