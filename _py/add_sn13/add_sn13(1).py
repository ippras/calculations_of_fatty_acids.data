"""Добавляет строки sn-1,3 в CSV нового формата без округления значений.

Для каждой жирной кислоты и каждой группы метаданных рассчитывается:
    Value(1,3) = (3 * Value(1,2,3) - Value(2)) / 2

Отрицательные значения сохраняются. Нормализация не выполняется.
Пустое или нечисловое значение sn-2 (например, EPSILON) принимается за 0.
"""

from __future__ import annotations

import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


SN_COLUMN = "StereospecificNumbers"
VALUE_COLUMN = "Value"
TOTAL_SN = "1,2,3"
SN2 = "2"
SN13 = "1,3"


def _to_decimal(value: Optional[str]) -> Optional[Decimal]:
    """Преобразует значение CSV в Decimal; пустое/EPSILON -> None."""
    if value is None:
        return None

    cleaned = str(value).strip()
    if not cleaned:
        return None

    # На случай десятичной запятой в отдельных файлах.
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _calculate_sn13(total_value: Decimal, sn2_value: Decimal) -> Decimal:
    """Точно вычисляет (3 * TAG - sn-2) / 2 без округления Decimal-контекстом.

    Все входные значения из CSV — конечные десятичные дроби. Деление на 2
    также даёт конечную десятичную дробь, поэтому результат можно представить
    точно, без ограничения числа знаков после запятой.
    """
    exponent = min(
        total_value.as_tuple().exponent,
        sn2_value.as_tuple().exponent,
        0,
    )

    def to_scaled_integer(value: Decimal) -> int:
        sign, digits, value_exponent = value.as_tuple()
        coefficient = int("".join(str(digit) for digit in digits)) if digits else 0
        if sign:
            coefficient = -coefficient
        return coefficient * (10 ** (value_exponent - exponent))

    numerator = 3 * to_scaled_integer(total_value) - to_scaled_integer(sn2_value)

    # Если числитель нечётный, умножаем его на 5 и уменьшаем exponent на 1:
    # numerator / 2 * 10**exponent == numerator * 5 * 10**(exponent - 1).
    if numerator % 2 == 0:
        coefficient = numerator // 2
        result_exponent = exponent
    else:
        coefficient = numerator * 5
        result_exponent = exponent - 1

    sign = 1 if coefficient < 0 else 0
    digits = tuple(int(char) for char in str(abs(coefficient))) if coefficient else (0,)
    return Decimal((sign, digits, result_exponent))


def _format_decimal(value: Decimal) -> str:
    """Форматирует Decimal полностью, не округляя; убирает только лишние нули."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def add_sn13(input_path: str | Path) -> Path:
    """Рассчитывает sn-1,3 для всех строк TAG и сохраняет новый CSV.

    Сопоставление выполняется по всем колонкам, кроме
    StereospecificNumbers и Value. Поэтому учитываются DOI, Index, Lipid,
    Label, FattyAcid, Method и любые дополнительные метаданные.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("CSV-файл пустой или не содержит заголовка.")

        missing_columns = [
            column for column in (SN_COLUMN, VALUE_COLUMN) if column not in fieldnames
        ]
        if missing_columns:
            raise ValueError(
                "В CSV отсутствуют обязательные колонки: "
                + ", ".join(missing_columns)
            )

        rows = list(reader)

    # Ключ включает все поля, кроме номера sn-позиций и самого значения.
    # Method включён в ключ, чтобы не смешивать разные источники данных.
    key_columns = [
        column for column in fieldnames if column not in {SN_COLUMN, VALUE_COLUMN}
    ]

    def make_key(row: dict[str, str]) -> tuple[str, ...]:
        return tuple((row.get(column) or "").strip() for column in key_columns)

    # Убираем старые результаты sn-1,3, чтобы повторный запуск не дублировал их.
    base_rows = [
        row for row in rows if (row.get(SN_COLUMN) or "").strip() != SN13
    ]

    sn2_by_key: dict[tuple[str, ...], dict[str, str]] = {}
    for row in base_rows:
        if (row.get(SN_COLUMN) or "").strip() != SN2:
            continue

        key = make_key(row)
        if key in sn2_by_key:
            raise ValueError(
                "Найдено несколько строк sn-2 с одинаковыми метаданными. "
                "Нельзя однозначно сопоставить их с TAG. Проверьте дубликаты "
                "для: "
                + ", ".join(
                    f"{column}={row.get(column, '')}" for column in key_columns
                )
            )
        sn2_by_key[key] = row

    total_rows = [
        row for row in base_rows
        if (row.get(SN_COLUMN) or "").strip() == TOTAL_SN
    ]
    if not total_rows:
        raise ValueError(f"В файле не найдены строки {TOTAL_SN} (TAG).")

    calculated_rows: list[dict[str, str]] = []
    missing_sn2_rows = 0
    missing_total_values = 0

    for total_row in total_rows:
        key = make_key(total_row)
        sn2_row = sn2_by_key.get(key)

        if sn2_row is None:
            missing_sn2_rows += 1
            sn2_value = Decimal("0")
        else:
            # Пустое sn-2 или EPSILON, как и прежде, считается нулём.
            sn2_value = _to_decimal(sn2_row.get(VALUE_COLUMN)) or Decimal("0")

        total_value = _to_decimal(total_row.get(VALUE_COLUMN))
        new_row = dict(total_row)
        new_row[SN_COLUMN] = SN13

        if total_value is None:
            new_row[VALUE_COLUMN] = ""
            missing_total_values += 1
        else:
            new_value = _calculate_sn13(total_value, sn2_value)
            new_row[VALUE_COLUMN] = _format_decimal(new_value)

        if "Method" in fieldnames:
            new_row["Method"] = "Calculated"

        calculated_rows.append(new_row)

    output_path = source.with_name(source.stem + "_with_1_3.csv")
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(base_rows)
        writer.writerows(calculated_rows)

    print("\nРасчёт завершён.")
    print(f"Строк TAG (1,2,3): {len(total_rows)}")
    print(f"Строк sn-2 найдено: {len(sn2_by_key)}")
    print(f"Добавлено строк 1,3: {len(calculated_rows)}")
    print(f"Строк без пары sn-2 (для расчёта sn-2 принято за 0): {missing_sn2_rows}")
    print(f"Строк с пустым/нечисловым TAG Value: {missing_total_values}")
    print("Отрицательные значения сохранены; нормализация и округление не выполнялись.")
    print(f"Сохранено: {output_path}")

    return output_path


def choose_csv_file() -> Optional[str]:
    """Открывает стандартное окно выбора входного CSV-файла."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "Не удалось загрузить tkinter — окно выбора файла недоступно. "
            "Передайте путь к CSV аргументом командной строки."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    try:
        selected = filedialog.askopenfilename(
            parent=root,
            title="Выберите CSV-файл для расчёта sn-1,3",
            filetypes=[("CSV-файлы", "*.csv"), ("Все файлы", "*.*")],
        )
    finally:
        root.destroy()

    return selected or None


def main() -> None:
    # Можно передать путь аргументом; без аргумента откроется окно выбора файла.
    input_path = sys.argv[1] if len(sys.argv) > 1 else choose_csv_file()
    if not input_path:
        print("Файл не выбран. Расчёт отменён.")
        return

    try:
        output_path = add_sn13(input_path)
        print(f"\nГотовый файл: {output_path}")
    except Exception as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Ошибка расчёта", str(exc), parent=root)
            root.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
