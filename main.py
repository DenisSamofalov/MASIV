"""Array Sum — сумма элементов целочисленного массива, кратных K.

Консольная программа: ввод и вывод через консоль и файлы, резервное копирование
и восстановление входного массива (input.txt), журнал работы в logs/app.log.
Только стандартная библиотека, Python 3.8+.

Запуск:
    python main.py                      # интерактивное меню
    python main.py sum --array 4 7 12 15 20 --k 4
    python main.py sum --input input.txt --k 4
    python main.py backup | backups | restore [имя_файла]
    python main.py delete [--yes]       # удалить сохранённый input.txt (с копией для отката)

Журнал: logs/app.log рядом с программой (папка создаётся автоматически, ротация по размеру).
Уровень задаётся переменной окружения ARRAY_SUM_LOG_LEVEL (DEBUG/INFO/WARNING/ERROR, по умолчанию INFO).
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_NAME = "input.txt"
OUTPUT_NAME = "output.txt"
BACKUP_DIR_NAME = "backups"
KEEP_BACKUPS = 10

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "app.log"
LOG_LEVEL_ENV = "ARRAY_SUM_LOG_LEVEL"
LOG_MAX_BYTES = 512 * 1024  # размер одного файла журнала до ротации
LOG_BACKUP_COUNT = 3  # сколько старых файлов журнала хранить (app.log.1 … app.log.3)
LOG_CLIP = 80  # длинные значения (огромные числа) в журнале сокращаются
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOGGER_NAME = "array_sum"

MANUAL = "manual"
PRE_RESTORE = "pre-restore"
PRE_DELETE = "pre-delete"

EXIT_OK = 0
EXIT_ERROR = 1  # код 2 выдаёт argparse при неверных аргументах командной строки

_INT = re.compile(r"[+-]?[0-9]+")
_PLAIN_TEXT = re.compile(r"[0-9+\-\s]*")  # быстрая проверка: только цифры, знаки и пробельные символы
_BACKUP_NAME = re.compile(r"^\d{8}_\d{6}_\d{6}_(manual|pre-restore|pre-delete)\.json$")
_DISPLAY_LIMIT = 20


class ToolError(Exception):
    """Ошибка данных, файла или резервной копии (сообщение предназначено пользователю)."""


# --------------------------------------------------------------------------- журнал
log = logging.getLogger(LOGGER_NAME)
log.addHandler(logging.NullHandler())  # при использовании функций как библиотеки файлов не создаётся
log.propagate = False
_file_handler = None

_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
           "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}


def _log_level(value):
    """Уровень журнала из имени ('debug') или числа; неизвестное значение -> INFO."""
    if _is_int(value) and value in _LEVELS.values():
        return value
    if isinstance(value, str):
        return _LEVELS.get(value.strip().upper(), logging.INFO)
    return logging.INFO


def _clip(value, limit=LOG_CLIP):
    """Строка для журнала: слишком длинное значение сокращается."""
    text = str(value)
    if len(text) <= limit:
        return text
    return "{}…(всего {} симв.)".format(text[:limit], len(text))


def log_file_path(base_dir):
    """Путь к файлу журнала: <base_dir>/logs/app.log."""
    return Path(base_dir) / LOG_DIR_NAME / LOG_FILE_NAME


def shutdown_logging():
    """Закрывает файл журнала и отключает запись (можно вызывать повторно)."""
    global _file_handler
    if _file_handler is not None:
        log.removeHandler(_file_handler)
        try:
            _file_handler.close()
        finally:
            _file_handler = None


def setup_logging(base_dir, level=None):
    """Включает запись в <base_dir>/logs/app.log; папка и файл создаются, если их нет.

    Возвращает путь к файлу журнала или None, если файл создать нельзя —
    тогда программа продолжает работу без журнала и выводит предупреждение.
    """
    shutdown_logging()
    global _file_handler
    path = log_file_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(str(path), maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    except OSError as exc:
        print("ПРЕДУПРЕЖДЕНИЕ: журнал недоступен, работа продолжается без него: {}".format(exc),
              file=sys.stderr)
        return None
    resolved = _log_level(os.environ.get(LOG_LEVEL_ENV) if level is None else level)
    handler.setLevel(resolved)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    log.setLevel(resolved)
    log.addHandler(handler)
    _file_handler = handler
    return path


# --------------------------------------------------------------------------- данные
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _to_int(token, what):
    if not _INT.fullmatch(token):
        raise ToolError("{} не является целым числом: '{}'.".format(what, token))
    try:
        return int(token)
    except ValueError:  # слишком длинное число (ограничение Python на длину)
        raise ToolError("{}: слишком длинное число.".format(what))


def validate_numbers(numbers):
    """Массив должен быть непустым списком целых чисел. Возвращает список."""
    if not isinstance(numbers, (list, tuple)):
        raise ToolError("Массив должен быть списком чисел.")
    if not numbers:
        raise ToolError("Массив пуст. Введите хотя бы одно целое число.")
    for index, value in enumerate(numbers, 1):
        if not _is_int(value):
            raise ToolError("Элемент №{} не является целым числом: {!r}.".format(index, value))
    return list(numbers)


def validate_k(k):
    """K — целое число, не равное нулю (отрицательное допускается)."""
    if not _is_int(k):
        raise ToolError("K должно быть целым числом.")
    if k == 0:
        raise ToolError("K не должно быть равно нулю.")
    return k


def parse_numbers(text):
    """Разбирает целые числа, разделённые пробелами и/или переводами строк."""
    tokens = text.split()
    if not tokens:
        raise ToolError("Массив пуст. Введите хотя бы одно целое число.")
    if _PLAIN_TEXT.fullmatch(text):
        try:
            return list(map(int, tokens))  # быстрый путь (миллион элементов — доли секунды)
        except ValueError:
            pass  # некорректный токен: ниже находим его и сообщаем номер
    return [_to_int(token, "Элемент №{}".format(index)) for index, token in enumerate(tokens, 1)]


def parse_k(value):
    """Преобразует значение K (строка или число) в целое, не равное нулю."""
    if _is_int(value):
        return validate_k(value)
    return validate_k(_to_int(str(value).strip(), "K"))


def sum_divisible(numbers, k):
    """Возвращает (элементы, кратные K, их сумма). Ноль кратен любому K != 0."""
    numbers = validate_numbers(numbers)
    validate_k(k)
    selected = [number for number in numbers if number % k == 0]
    total = sum(selected)
    log.info("Расчёт: элементов=%d, K=%s, подходящих=%d, сумма=%s",
             len(numbers), _clip(k), len(selected), _clip(total))
    return selected, total


# --------------------------------------------------------------------------- файлы
def atomic_write(path, text):
    """Запись через временный файл: сбой не оставляет наполовину записанный файл."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
        log.debug("Файл записан: %s", path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_array(path):
    """Читает и проверяет массив из текстового файла (UTF-8)."""
    path = Path(path)
    if not path.is_file():
        raise ToolError("Файл не найден: {}".format(path))
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ToolError("Файл {} не в кодировке UTF-8.".format(path))
    except OSError as exc:
        raise ToolError("Не удалось прочитать файл {}: {}".format(path, exc))
    try:
        numbers = parse_numbers(text)
    except ToolError as exc:
        raise ToolError("{}: {}".format(path.name, exc))
    log.debug("Прочитан файл %s: элементов=%d", path, len(numbers))
    return numbers


def write_array(numbers, path):
    numbers = validate_numbers(numbers)
    atomic_write(path, " ".join(map(str, numbers)) + "\n")


def format_result(numbers, k, selected, total):
    """Текст для файла результата (все данные полностью)."""
    return (
        "Исходный массив: {}\n"
        "Делитель K: {}\n"
        "Подходящие элементы: {}\n"
        "Сумма: {}\n"
    ).format(" ".join(map(str, numbers)), k,
             " ".join(map(str, selected)) if selected else "нет", total)


def save_result(numbers, k, selected, total, path):
    atomic_write(path, format_result(numbers, k, selected, total))


def short(numbers, limit=_DISPLAY_LIMIT):
    """Компактный вывод списка для консоли (длинные списки сокращаются)."""
    if len(numbers) <= limit:
        return "[" + ", ".join(map(str, numbers)) + "]"
    head = ", ".join(map(str, numbers[:limit]))
    return "[{}, … (всего {})]".format(head, len(numbers))


# --------------------------------------------------------------------------- резервные копии
def _checksum(data):
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def list_backups(backup_dir):
    """Все копии (обычные и страховочные), от старых к новым."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    return sorted(p for p in backup_dir.iterdir() if p.is_file() and _BACKUP_NAME.match(p.name))


def is_pre_restore(path):
    return Path(path).name.endswith("_{}.json".format(PRE_RESTORE))


def is_safety_copy(path):
    """Страховочная копия (перед восстановлением или удалением) — для пометки в списках."""
    name = Path(path).name
    return name.endswith("_{}.json".format(PRE_RESTORE)) or name.endswith("_{}.json".format(PRE_DELETE))


def _rotate(backup_dir, keep, protect=()):
    """Удаляет самые старые копии сверх лимита, пропуская защищённые."""
    protected = {Path(p) for p in protect}
    backups = list_backups(backup_dir)
    excess = len(backups) - keep
    for old in backups:
        if excess <= 0:
            break
        if old in protected:
            continue
        old.unlink()
        log.info("Ротация: удалена старая копия %s", old.name)
        excess -= 1


def create_backup(source, backup_dir, kind=MANUAL, keep=KEEP_BACKUPS, protect=()):
    """Проверяет входной файл и создаёт копию. Повреждённые данные не копируются."""
    numbers = read_array(source)
    backup_dir = Path(backup_dir)
    moment = datetime.now()
    while True:
        path = backup_dir / "{}_{}.json".format(moment.strftime("%Y%m%d_%H%M%S_%f"), kind)
        if not path.exists():
            break
        moment += timedelta(microseconds=1)
    data = {"numbers": numbers}
    payload = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "checksum": _checksum(data),
        "data": data,
    }
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    log.info("Создана резервная копия %s (тип=%s, элементов=%d)", path.name, kind, len(numbers))
    _rotate(backup_dir, keep, protect=[path] + list(protect))
    return path


def verify_backup(path):
    """Проверяет копию (структура и SHA-256). Возвращает сведения о ней."""
    path = Path(path)
    if not path.is_file():
        raise ToolError("Резервная копия не найдена: {}".format(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ToolError("{}: файл повреждён (не JSON).".format(path.name))
    except OSError as exc:
        raise ToolError("Не удалось прочитать копию {}: {}".format(path.name, exc))
    if (not isinstance(payload, dict) or not isinstance(payload.get("created"), str)
            or not isinstance(payload.get("checksum"), str)
            or not isinstance(payload.get("data"), dict) or "numbers" not in payload["data"]):
        raise ToolError("{}: неверная структура копии.".format(path.name))
    if _checksum(payload["data"]) != payload["checksum"]:
        raise ToolError("{}: контрольная сумма SHA-256 не совпала.".format(path.name))
    try:
        numbers = validate_numbers(payload["data"]["numbers"])
    except ToolError as exc:
        raise ToolError("{}: {}".format(path.name, exc))
    log.debug("Копия %s проверена: элементов=%d", path.name, len(numbers))
    return {"path": path, "created": payload["created"], "count": len(numbers), "numbers": numbers}


def resolve_backup(backup_dir, name=None):
    """Находит копию: по имени (в папке копий или путь) либо самую свежую.

    Копии pre-restore пропускаются (иначе повторное восстановление откатывалось бы назад);
    копия pre-delete берётся, поэтому после удаления хватает просто «restore»."""
    if name is None:
        regular = [p for p in list_backups(backup_dir) if not is_pre_restore(p)]
        if not regular:
            raise ToolError("Резервных копий нет.")
        return regular[-1]
    candidate = Path(name)
    if candidate.is_file():
        return candidate
    in_dir = Path(backup_dir) / name
    if in_dir.is_file():
        return in_dir
    raise ToolError("Резервная копия не найдена: {}".format(name))


def restore_backup(target, backup_dir, name=None, keep=KEEP_BACKUPS):
    """Восстанавливает входной файл из копии.

    Порядок: найти копию -> проверить -> сохранить текущий файл как pre-restore ->
    атомарно записать массив. При ошибке на любом шаге до записи target не меняется.
    Возвращает (путь копии, массив, путь страховочной копии или None).
    """
    path = resolve_backup(backup_dir, name)
    info = verify_backup(path)
    safety = None
    target = Path(target)
    if target.exists():
        try:
            safety = create_backup(target, backup_dir, kind=PRE_RESTORE, keep=keep, protect=[path])
        except ToolError as exc:
            log.warning("Страховочная копия не создана, текущий файл повреждён: %s", exc)
            safety = None  # текущий файл уже повреждён — восстанавливаем поверх
    write_array(info["numbers"], target)
    log.info("Восстановлено из %s: элементов=%d, страховочная копия=%s",
             info["path"].name, len(info["numbers"]), safety.name if safety else "нет")
    return info["path"], info["numbers"], safety


def delete_array(target, backup_dir, keep=KEEP_BACKUPS):
    """Удаляет сохранённый входной файл. Перед этим создаёт копию pre-delete для отката
    (если файл повреждён, копия не создаётся, но удалить его всё равно можно).
    Возвращает путь страховочной копии или None."""
    target = Path(target)
    if not target.is_file():
        raise ToolError("Сохранённого массива нет: {}".format(target.name))
    safety = None
    try:
        safety = create_backup(target, backup_dir, kind=PRE_DELETE, keep=keep)
    except ToolError as exc:
        log.warning("Копия перед удалением не создана, файл повреждён: %s", exc)
    target.unlink()
    log.info("Удалён файл %s, страховочная копия=%s", target.name, safety.name if safety else "нет")
    return safety


# --------------------------------------------------------------------------- ввод
def ask_confirm(question):
    """Запрос подтверждения: да/д/y/yes — согласие, всё остальное — отказ."""
    return input("{} (да/нет): ".format(question)).strip().lower() in ("да", "д", "y", "yes")


def ask_k():
    return parse_k(input("Введите целое число K (не ноль): "))


def manual_input():
    return parse_numbers(input("Введите целые числа через пробел: "))


def calculate_and_show(numbers, k, output_path, label=None):
    selected, total = sum_divisible(numbers, k)
    print("Подходящие элементы: {}".format(short(selected) if selected else "нет"))
    print("Сумма элементов, кратных {}: {}".format(k, total))
    save_result(numbers, k, selected, total, output_path)
    print("Результат сохранён в файл: {}".format(label or output_path))
    log.info("Результат сохранён: %s", output_path)
    return selected, total


# --------------------------------------------------------------------------- команды
def _paths(base_dir):
    base_dir = Path(base_dir)
    return base_dir / INPUT_NAME, base_dir / OUTPUT_NAME, base_dir / BACKUP_DIR_NAME


def cmd_sum(args, base_dir):
    _, default_output, _ = _paths(base_dir)
    source = "array" if args.array is not None else "file" if args.input is not None else "console"
    log.info("Команда sum: источник=%s, вывод=%s", source, args.output or default_output)
    if args.array is not None:
        numbers = [_to_int(token, "Элемент №{}".format(i)) for i, token in enumerate(args.array, 1)]
        numbers = validate_numbers(numbers)
    elif args.input is not None:
        numbers = read_array(args.input)
    else:
        numbers = manual_input()
    k = parse_k(args.k) if args.k is not None else ask_k()
    calculate_and_show(numbers, k, args.output or default_output, args.output or OUTPUT_NAME)
    return EXIT_OK


def cmd_backup(args, base_dir):
    input_path, _, backup_dir = _paths(base_dir)
    log.info("Команда backup")
    path = create_backup(input_path, backup_dir)
    print("Резервная копия создана: {}".format(path.name))
    print("Копий в папке: {} (максимум {})".format(len(list_backups(backup_dir)), KEEP_BACKUPS))
    return EXIT_OK


def cmd_backups(args, base_dir):
    _, _, backup_dir = _paths(base_dir)
    log.info("Команда backups")
    paths = list_backups(backup_dir)
    if not paths:
        print("Резервных копий нет.")
        return EXIT_OK
    for path in paths:
        label = " [страховочная]" if is_safety_copy(path) else ""
        try:
            info = verify_backup(path)
            status = "OK, элементов: {}, создана: {}".format(info["count"], info["created"])
        except ToolError as exc:
            log.warning("Повреждённая копия: %s", exc)
            status = "ПОВРЕЖДЕНА: {}".format(exc)
        print("{}{}  {}".format(path.name, label, status))
    return EXIT_OK


def cmd_delete(args, base_dir):
    input_path, _, backup_dir = _paths(base_dir)
    log.info("Команда delete: без подтверждения=%s", bool(args.yes))
    if not input_path.is_file():
        raise ToolError("Сохранённого массива нет: {}".format(input_path.name))
    if not args.yes and not ask_confirm("Удалить {}?".format(input_path.name)):
        print("Удаление отменено.")
        return EXIT_OK
    safety = delete_array(input_path, backup_dir)
    print("Массив удалён: {}".format(input_path.name))
    if safety:
        print("Копия перед удалением сохранена: {} (вернуть: restore {})".format(safety.name, safety.name))
    return EXIT_OK


def cmd_restore(args, base_dir):
    input_path, _, backup_dir = _paths(base_dir)
    log.info("Команда restore: имя=%s", args.name or "самая свежая")
    path, numbers, safety = restore_backup(input_path, backup_dir, args.name)
    print("Восстановлено из: {}".format(path.name))
    print("Элементов в {}: {}".format(input_path.name, len(numbers)))
    if safety:
        print("Состояние до восстановления сохранено: {}".format(safety.name))
    return EXIT_OK


def menu(base_dir):
    input_path, output_path, backup_dir = _paths(base_dir)
    current = None
    print("Array Sum — сумма элементов массива, кратных K")
    while True:
        print("\nМЕНЮ")
        print("1. Ввести массив в консоли и вычислить сумму")
        print("2. Загрузить массив из {} и вычислить сумму".format(INPUT_NAME))
        print("3. Загрузить массив из другого файла и вычислить сумму")
        print("4. Сохранить текущий массив в {}".format(INPUT_NAME))
        print("5. Создать резервную копию {}".format(INPUT_NAME))
        print("6. Восстановить {} из резервной копии".format(INPUT_NAME))
        print("7. Показать текущий массив")
        print("8. Удалить сохранённый массив ({})".format(INPUT_NAME))
        print("0. Выход")
        try:
            choice = input("Выберите пункт меню: ").strip()
        except EOFError:
            choice = "0"
        log.info("Меню: пункт %r", choice)
        try:
            if choice == "1":
                current = manual_input()
                calculate_and_show(current, ask_k(), output_path, OUTPUT_NAME)
            elif choice == "2":
                current = read_array(input_path)
                print("Загружен массив: {}".format(short(current)))
                calculate_and_show(current, ask_k(), output_path, OUTPUT_NAME)
            elif choice == "3":
                raw_path = input("Введите путь к текстовому файлу: ").strip().strip('"')
                current = read_array(raw_path)
                print("Загружен массив: {}".format(short(current)))
                calculate_and_show(current, ask_k(), output_path, OUTPUT_NAME)
            elif choice == "4":
                if current is None:
                    current = manual_input()
                write_array(current, input_path)
                print("Массив сохранён в {}.".format(input_path.name))
            elif choice == "5":
                path = create_backup(input_path, backup_dir)
                print("Резервная копия создана: {}".format(path.name))
            elif choice == "6":
                paths = list_backups(backup_dir)
                if not paths:
                    raise ToolError("Резервных копий нет.")
                for path in paths:
                    print("  " + path.name + (" [страховочная]" if is_safety_copy(path) else ""))
                name = input("Имя копии (Enter — самая свежая): ").strip().strip('"') or None
                path, current, safety = restore_backup(input_path, backup_dir, name)
                print("Данные восстановлены в {} из {}: {}".format(input_path.name, path.name, short(current)))
                if safety:
                    print("Состояние до восстановления сохранено: {}".format(safety.name))
            elif choice == "7":
                print("Массив ещё не загружен." if current is None
                      else "Текущий массив: {}".format(short(current)))
            elif choice == "8":
                if not input_path.is_file():
                    raise ToolError("Сохранённого массива нет: {}".format(input_path.name))
                if ask_confirm("Удалить {}?".format(input_path.name)):
                    safety = delete_array(input_path, backup_dir)
                    print("Массив удалён: {}".format(input_path.name))
                    if safety:
                        print("Копия перед удалением сохранена: {} (вернуть: пункт 6)".format(safety.name))
                else:
                    print("Удаление отменено.")
            elif choice == "0":
                print("Работа программы завершена.")
                return EXIT_OK
            else:
                print("Нет такого пункта. Выберите пункт из меню.")
        except (ToolError, OSError) as error:
            log.warning("Меню: ошибка: %s", error)
            print("ОШИБКА: {}".format(error))
        except EOFError:
            log.warning("Меню: ввод завершён (EOF)")
            print("Работа программы завершена.")
            return EXIT_OK


# --------------------------------------------------------------------------- CLI
def build_parser():
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Сумма элементов целочисленного массива, кратных K, "
                    "с резервным копированием входного файла. Без команды запускается меню.")
    sub = parser.add_subparsers(dest="command")

    sum_parser = sub.add_parser("sum", help="вычислить сумму элементов, кратных K")
    source = sum_parser.add_mutually_exclusive_group()
    source.add_argument("--array", nargs="+", metavar="N", help="элементы массива")
    source.add_argument("--input", metavar="ФАЙЛ", help="файл с массивом (числа через пробел/перевод строки)")
    sum_parser.add_argument("--k", metavar="K", help="целый делитель, не ноль (иначе запрос в консоли)")
    sum_parser.add_argument("--output", metavar="ФАЙЛ",
                            help="файл результата (по умолчанию {} в папке программы)".format(OUTPUT_NAME))

    sub.add_parser("backup", help="создать резервную копию {}".format(INPUT_NAME))
    sub.add_parser("backups", help="список резервных копий с проверкой целостности")
    delete = sub.add_parser("delete", help="удалить сохранённый {} (перед этим создаётся копия)".format(INPUT_NAME))
    delete.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    restore = sub.add_parser("restore", help="восстановить {} из копии".format(INPUT_NAME))
    restore.add_argument("name", nargs="?", help="имя копии (по умолчанию — самая свежая)")
    return parser


_COMMANDS = {"sum": cmd_sum, "backup": cmd_backup, "backups": cmd_backups, "restore": cmd_restore,
             "delete": cmd_delete}


def run(argv, base_dir=BASE_DIR):
    """Выполняет программу и возвращает код возврата (0 — успех, 1 — ошибка, 2 — аргументы)."""
    args = build_parser().parse_args(argv)
    setup_logging(base_dir)
    code = EXIT_ERROR
    try:
        log.info("Запуск: команда=%s", args.command or "menu")
        if args.command is None:
            code = menu(base_dir)
        else:
            code = _COMMANDS[args.command](args, base_dir)
    except (ToolError, OSError) as exc:
        log.error("%s", exc)
        print("ОШИБКА: {}".format(exc), file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        log.warning("Прервано пользователем")
        print("\nПрервано пользователем.", file=sys.stderr)
    except Exception:
        log.exception("Непредвиденная ошибка")
        raise
    finally:
        log.info("Завершение: код=%s", code)
        shutdown_logging()
    return code


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    return run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
