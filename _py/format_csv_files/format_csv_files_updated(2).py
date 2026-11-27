"""Выбирает несколько CSV, приводит порядок колонок и форматирует Value.

Запуск:
    python format_csv_files.py

Без аргументов откроется окно выбора нескольких CSV-файлов.
Можно также передать пути из командной строки:
    python format_csv_files.py file1.csv file2.csv

По умолчанию результаты сохраняются рядом с исходниками с суффиксом _formatted.csv.
Режим сохранения настраивается параметром REPLACE_SOURCE_FILE.
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
#   "min"   — сохранять минимум DECIMAL_PLACES знаков после точки,
#             убирая лишние конечные нули без округления:
#             0.150 -> 0.15, 0.1556 -> 0.1556, 0.10 -> 0.10.
VALUE_FORMAT = "min"

# Для "fixed" — точное количество знаков (с округлением).
# Для "min" — минимальное количество знаков (без округления).
DECIMAL_PLACES = 1

# Проверять суммы Value внутри текущего CSV-файла.
# Если есть StereospecificNumbers — отдельно по каждому его значению.
# Если колонки нет — одна общая сумма по всем строкам файла.
CHECK_STEREOSPECIFIC_SUMS = True

# True — приводить распознанные суммы каждой группы (или всего файла) к 1:
#   сумма около 1      — оставить значения без изменения;
#   сумма около 100    — разделить каждое Value на 100;
#   сумма около 33.(3) — умножить каждое Value на 3 и разделить на 100.
# False — только проверять и показывать результаты, не меняя масштаб.
NORMALIZE_STEREOSPECIFIC_SUMS = True

# Допуск проверки относительно ожидаемой суммы (10%).
# Например, 33.3 будет распознано как представление 33.(3).
SUM_RELATIVE_TOLERANCE = Decimal("0.1")

# Порядок стандартных колонок текущего формата.
# Колонки, которых нет в списке, останутся после стандартных в исходном порядке.
COLUMN_ORDER = [
    "DOI",
    "Index",
    "Date",
    "Group",
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

# Режим сохранения результата:
# True  — заменить исходный CSV-файл обработанным результатом.
# False — создать отдельный файл с суффиксом OUTPUT_SUFFIX.
REPLACE_SOURCE_FILE = True

# Имя нового файла, если REPLACE_SOURCE_FILE = False:
# <исходное имя> + этот суффикс + .csv
OUTPUT_SUFFIX = "_formatted"

# True — если файл с суффиксом уже существует, перезаписать его.
# False — подобрать свободное имя с номером (_1, _2 и т. д.).
OVERWRITE_EXISTING_OUTPUT = True

# Дополнительные неизвестные колонки сортировать по алфавиту?
# False — оставить их в исходном порядке.
SORT_EXTRA_COLUMNS_ALPHABETICALLY = False

# ---------------------------------------------------------------------------


class SumValidationError(ValueError):
    """Сумма группы не позволяет однозначно определить представление."""


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
        if not isinstance(DECIMAL_PLACES, int) or DECIMAL_PLACES < 0:
            raise ValueError("DECIMAL_PLACES должен быть целым числом >= 0.")

        # Убираем конечные нули, только пока не достигнут заданный минимум.
        # Дробная часть не округляется и значащие цифры не изменяются.
        text = format(number, "f")
        if "." in text:
            integer_part, fractional_part = text.split(".", 1)
            fractional_part = fractional_part.rstrip("0")
            fractional_part = fractional_part.ljust(DECIMAL_PLACES, "0")
            return f"{integer_part}.{fractional_part}"

        if DECIMAL_PLACES == 0:
            return text
        return f"{text}.{('0' * DECIMAL_PLACES)}"

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


def parse_decimal(value: str | None) -> Decimal | None:
    """Преобразует значение в Decimal; пустые и текстовые маркеры пропускает."""
    if value is None or not str(value).strip():
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def expected_sum_multiplier(total: Decimal) -> tuple[str, Decimal] | None:
    """Возвращает тип суммы и множитель для приведения группы к 1."""
    expected_sums = (
        ("1", Decimal(1), Decimal(1)),
        ("100", Decimal(100), Decimal("0.01")),
        ("33.(3)", Decimal(100) / Decimal(3), Decimal("0.03")),
    )

    for label, expected, multiplier in expected_sums:
        tolerance = abs(expected) * SUM_RELATIVE_TOLERANCE
        if abs(total - expected) <= tolerance:
            return label, multiplier
    return None


def analyze_stereospecific_groups(
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> tuple[dict[int, Decimal], list[str]]:
    """Проверяет суммы Value по StereospecificNumbers или по всему файлу.

    Если колонка StereospecificNumbers присутствует, каждое её значение
    образует отдельную группу. Пустое значение тоже считается отдельной группой,
    если в строке заполнено Value.
    Если колонки нет, все строки файла образуют одну общую группу.

    Если для любой группы невозможно определить представление суммы, функция
    выбрасывает SumValidationError — обработка файла должна быть остановлена.

    Возвращает множители для строк (по их индексам) и человекочитаемый отчёт.
    Колонка Index на группировку не влияет.
    """
    has_stereospecific_numbers = "StereospecificNumbers" in fieldnames
    groups: dict[tuple[str, ...], list[int]] = {}

    if has_stereospecific_numbers:
        for row_index, row in enumerate(rows):
            stereospecific_number = row.get("StereospecificNumbers", "").strip()
            # Строки без Value не влияют на сумму. Если Value заполнено, но
            # StereospecificNumbers пуст, проверяем их отдельной пустой группой.
            if not str(row.get("Value", "")).strip():
                continue
            groups.setdefault((stereospecific_number,), []).append(row_index)
    elif rows:
        # Если колонки нет, проверяем общую сумму Value по всем строкам.
        groups[()] = list(range(len(rows)))

    row_multipliers: dict[int, Decimal] = {}
    report: list[str] = []

    for key, row_indices in groups.items():
        values = [
            (row_index, parse_decimal(rows[row_index].get("Value")))
            for row_index in row_indices
        ]
        numeric_values = [
            (row_index, value)
            for row_index, value in values
            if value is not None
        ]

        if not numeric_values:
            total = None
            match = None
        else:
            total = sum((value for _, value in numeric_values), Decimal(0))
            match = expected_sum_multiplier(total)

        if has_stereospecific_numbers:
            group_value = key[0] if key[0] else "<пусто>"
            group_label = f"StereospecificNumbers={group_value}"
        else:
            group_label = "весь файл (без StereospecificNumbers)"

        if total is None:
            raise SumValidationError(
                f"{group_label}: невозможно определить представление суммы — "
                "нет числовых значений в колонке Value. Обработка остановлена."
            )

        if match is None:
            raise SumValidationError(
                f"{group_label}: сумма Value равна {total} и не соответствует "
                "ни одному допустимому представлению (1, 100 или 33.(3)) "
                f"с относительным допуском {SUM_RELATIVE_TOLERANCE}. "
                "Обработка остановлена."
            )

        sum_kind, multiplier = match
        if NORMALIZE_STEREOSPECIFIC_SUMS and multiplier != 1:
            for row_index, _ in numeric_values:
                row_multipliers[row_index] = multiplier
            operation = "нормализована к 1"
        elif NORMALIZE_STEREOSPECIFIC_SUMS:
            operation = "уже около 1, без изменений"
        else:
            operation = "проверка пройдена"

        report.append(
            f"  {group_label}: сумма {total} (представление {sum_kind}) — {operation}"
        )

    return row_multipliers, report


def process_file(input_file: str | Path) -> Path:
    """Проверяет суммы групп, форматирует Value и сохраняет CSV-файл."""
    source = Path(input_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    fieldnames, rows = read_csv(source)
    if "Value" not in fieldnames:
        raise ValueError(f"В файле нет колонки 'Value': {source.name}")

    if NORMALIZE_STEREOSPECIFIC_SUMS and not CHECK_STEREOSPECIFIC_SUMS:
        raise ValueError(
            "Для нормализации включите CHECK_STEREOSPECIFIC_SUMS."
        )

    row_multipliers: dict[int, Decimal] = {}
    if CHECK_STEREOSPECIFIC_SUMS:
        row_multipliers, group_report = analyze_stereospecific_groups(
            rows, fieldnames
        )
        print(f"\nПроверка сумм Value — {source.name}:")
        if group_report:
            for line in group_report:
                print(line)
        else:
            if "StereospecificNumbers" in fieldnames:
                print("  Групп с заполненным StereospecificNumbers не найдено.")
            else:
                print("  Файл не содержит строк для проверки.")

    output_columns = ordered_columns(fieldnames)
    for row_index, row in enumerate(rows):
        multiplier = row_multipliers.get(row_index, Decimal(1))
        row["Value"] = format_value(row.get("Value", ""), multiplier)

    if REPLACE_SOURCE_FILE:
        output = source
    else:
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

    # Сначала полностью записываем временный файл, затем заменяем целевой.
    # Это снижает риск потерять исходник при прерывании записи.
    temporary_output = output.with_name(output.name + ".tmp")
    try:
        with temporary_output.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=output_columns,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary_output.replace(output)
    except Exception:
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    print(f"Готово: {source.name} -> {output.name} ({len(rows)} строк)")
    return output


def main(args: Iterable[str] | None = None) -> int:
    paths = tuple(args if args is not None else sys.argv[1:])
    if not paths:
        paths = choose_csv_files()

    if not paths:
        print("Файлы не выбраны. Работа завершена.")
        return 0

    # Сначала проверяем суммы во всех выбранных файлах. Если хотя бы одна
    # группа не распознаётся, завершаем программу до изменения любого CSV.
    if CHECK_STEREOSPECIFIC_SUMS:
        for path in paths:
            source = Path(path).expanduser().resolve()
            try:
                if not source.is_file():
                    raise FileNotFoundError(f"Файл не найден: {source}")
                fieldnames, rows = read_csv(source)
                if "Value" not in fieldnames:
                    raise ValueError(f"В файле нет колонки 'Value': {source.name}")
                analyze_stereospecific_groups(rows, fieldnames)
            except SumValidationError as exc:
                raise RuntimeError(
                    f"PANIC: проверка сумм не пройдена для файла {source.name}: {exc}"
                ) from exc

    succeeded: list[Path] = []
    failed: list[tuple[str, str]] = []

    for path in paths:
        try:
            succeeded.append(process_file(path))
        except SumValidationError as exc:
            raise RuntimeError(
                f"PANIC: проверка сумм не пройдена для файла {path}: {exc}"
            ) from exc
        except ValueError as exc:
            failed.append((str(path), str(exc)))
            print(f"ОШИБКА: {path}: {exc}", file=sys.stderr)
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
