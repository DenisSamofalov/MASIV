"""Автоматические тесты программы Array Sum: ровно 5 тестов на каждую функцию main.py.

Покрытие по ТЗ: FR-1…FR-12, NFR-3…NFR-5 + журналирование в logs/app.log.
"""
import argparse
import contextlib
import hashlib
import io
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import main


# --------------------------------------------------------------------------- помощники
def run_cli(argv, base_dir, inputs=()):
    """Запускает main.run, возвращает (код, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with mock.patch("builtins.input", side_effect=list(inputs) + [EOFError()] * 50):
            code = main.run(argv, base_dir)
    return code, out.getvalue(), err.getvalue()


def capture(func, *args, inputs=(), **kwargs):
    """Вызывает func с подменой input(); возвращает (результат, stdout)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        with mock.patch("builtins.input", side_effect=list(inputs) + [EOFError()] * 50):
            result = func(*args, **kwargs)
    return result, out.getvalue()


def ns(**kwargs):
    """Аргументы команды sum (как после argparse)."""
    values = {"array": None, "input": None, "k": None, "output": None, "name": None, "yes": False}
    values.update(kwargs)
    return argparse.Namespace(**values)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(main.shutdown_logging)  # файл журнала должен быть закрыт до удаления папки
        self.base = Path(self._tmp.name)
        self.input = self.base / "input.txt"
        self.output = self.base / "output.txt"
        self.backups = self.base / "backups"
        self.log_file = self.base / "logs" / "app.log"

    def make_input(self, text="4 7 12 15 20\n"):
        self.input.write_text(text, encoding="utf-8")

    def make_backup_file(self, name):
        """Пустой файл с корректным именем копии (для проверки списка и ротации)."""
        self.backups.mkdir(exist_ok=True)
        path = self.backups / name
        path.write_text("{}", encoding="utf-8")
        return path

    def log_text(self):
        return self.log_file.read_text(encoding="utf-8")


# =========================================================================== данные
class IsIntTests(unittest.TestCase):
    def test_ints_are_true(self):
        for value in (0, 5, -3):
            self.assertTrue(main._is_int(value), msg=value)

    def test_bool_is_not_int(self):
        self.assertFalse(main._is_int(True))
        self.assertFalse(main._is_int(False))

    def test_float_is_not_int(self):
        for value in (1.0, 2.5, float("nan")):
            self.assertFalse(main._is_int(value), msg=value)

    def test_strings_are_not_int(self):
        for value in ("1", "", "abc"):
            self.assertFalse(main._is_int(value), msg=value)

    def test_none_containers_and_huge_int(self):
        self.assertFalse(main._is_int(None))
        self.assertFalse(main._is_int([1]))
        self.assertTrue(main._is_int(10 ** 40))


class ToIntTests(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(main._to_int("42", "x"), 42)

    def test_signs(self):
        self.assertEqual(main._to_int("+7", "x"), 7)
        self.assertEqual(main._to_int("-7", "x"), -7)

    def test_invalid_token_message_contains_label_and_token(self):
        with self.assertRaises(main.ToolError) as ctx:
            main._to_int("abc", "Элемент №2")
        self.assertIn("Элемент №2", str(ctx.exception))
        self.assertIn("abc", str(ctx.exception))

    def test_rejects_non_ascii_digits_and_formats(self):
        for token in ("٣", "1.5", "1e3", "1_000", "--5", "", "1,2"):
            with self.assertRaises(main.ToolError, msg=token):
                main._to_int(token, "x")

    def test_too_long_number_reported(self):
        with mock.patch("main.int", side_effect=ValueError, create=True):
            with self.assertRaises(main.ToolError) as ctx:
                main._to_int("123", "K")
        self.assertIn("слишком длинное", str(ctx.exception))


class ValidateNumbersTests(unittest.TestCase):
    def test_list_returned_as_copy(self):
        source = [1, 2, 3]
        result = main.validate_numbers(source)
        self.assertEqual(result, [1, 2, 3])
        self.assertIsNot(result, source)

    def test_tuple_converted_to_list(self):
        self.assertEqual(main.validate_numbers((4, 5)), [4, 5])

    def test_empty_rejected(self):
        for empty in ([], ()):
            with self.assertRaises(main.ToolError):
                main.validate_numbers(empty)

    def test_bad_element_names_position(self):
        for bad in (2.5, "2", True, None):
            with self.assertRaises(main.ToolError, msg=repr(bad)) as ctx:
                main.validate_numbers([1, bad, 3])
            self.assertIn("№2", str(ctx.exception))

    def test_not_a_list_rejected(self):
        for bad in ("123", None, 5, {1: 2}, {1, 2}):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.validate_numbers(bad)


class ValidateKTests(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(main.validate_k(4), 4)

    def test_negative_allowed(self):
        self.assertEqual(main.validate_k(-4), -4)

    def test_zero_rejected(self):
        with self.assertRaises(main.ToolError) as ctx:
            main.validate_k(0)
        self.assertIn("нулю", str(ctx.exception))

    def test_non_int_types_rejected(self):
        for bad in (True, False, 2.5, "4", None, [4]):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.validate_k(bad)

    def test_huge_value_allowed(self):
        self.assertEqual(main.validate_k(10 ** 30), 10 ** 30)


class ParseNumbersTests(unittest.TestCase):
    def test_separators_spaces_tabs_newlines(self):
        self.assertEqual(main.parse_numbers("4 7\n12\t15  20\n"), [4, 7, 12, 15, 20])

    def test_signs_and_zero(self):
        self.assertEqual(main.parse_numbers("-12 0 +8"), [-12, 0, 8])

    def test_empty_or_blank_rejected(self):
        for text in ("", "   \n\t "):
            with self.assertRaises(main.ToolError, msg=repr(text)):
                main.parse_numbers(text)

    def test_non_integers_rejected_with_position(self):
        for text in ("4 abc", "1.5", "1,2", "1e3", "1_000", "--5", "٣"):
            with self.assertRaises(main.ToolError, msg=text):
                main.parse_numbers(text)
        with self.assertRaises(main.ToolError) as ctx:
            main.parse_numbers("1 2 x")
        self.assertIn("№3", str(ctx.exception))

    def test_one_million_numbers_fast(self):  # NFR-5
        text = " ".join(map(str, range(1000000)))
        started = time.perf_counter()
        self.assertEqual(len(main.parse_numbers(text)), 1000000)
        self.assertLess(time.perf_counter() - started, 1.0)


class ParseKTests(unittest.TestCase):
    def test_string_value(self):
        self.assertEqual(main.parse_k("4"), 4)

    def test_whitespace_and_negative(self):
        self.assertEqual(main.parse_k(" -4 "), -4)

    def test_int_passthrough(self):
        self.assertEqual(main.parse_k(7), 7)

    def test_zero_rejected(self):
        for bad in ("0", "-0", "+0", 0):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.parse_k(bad)

    def test_garbage_rejected(self):
        for bad in ("abc", "", "1.5", True, 2.5):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.parse_k(bad)


class SumDivisibleTests(unittest.TestCase):
    def test_basic_example_and_k_one(self):
        self.assertEqual(main.sum_divisible([4, 7, 12, 15, 20], 4), ([4, 12, 20], 36))
        self.assertEqual(main.sum_divisible([4, 7, 12, 15, 20], 1), ([4, 7, 12, 15, 20], 58))

    def test_negative_numbers_zero_and_negative_k(self):
        self.assertEqual(main.sum_divisible([-12, 0, 8, 5, -4], 4), ([-12, 0, 8, -4], -8))
        self.assertEqual(main.sum_divisible([-6, -4, 0, 8], -2), ([-6, -4, 0, 8], -2))
        self.assertEqual(main.sum_divisible([0], 5), ([0], 0))

    def test_no_matches(self):
        self.assertEqual(main.sum_divisible([1, 3, 7], 2), ([], 0))
        self.assertEqual(main.sum_divisible([4, 7], 100), ([], 0))

    def test_invalid_input_rejected(self):
        with self.assertRaises(main.ToolError):
            main.sum_divisible([1, 2], 0)
        with self.assertRaises(main.ToolError):
            main.sum_divisible([], 3)
        for bad in ([1, 2.5], [1, "2"], [True], "123", None):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.sum_divisible(bad, 2)

    def test_one_million_fast_and_huge_numbers(self):  # NFR-5
        numbers = list(range(1, 1000001))
        started = time.perf_counter()
        _, total = main.sum_divisible(numbers, 7)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(total, 7 * (142857 * 142858 // 2))
        big = 10 ** 30
        self.assertEqual(main.sum_divisible([big, big + 1], 10), ([big], big))


# =========================================================================== файлы
class AtomicWriteTests(TempDirCase):
    def test_writes_utf8_text(self):
        main.atomic_write(self.input, "Привет 1 2 3\n")
        self.assertEqual(self.input.read_text(encoding="utf-8"), "Привет 1 2 3\n")

    def test_creates_missing_parent_dirs(self):
        target = self.base / "a" / "b" / "file.txt"
        main.atomic_write(target, "x")
        self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_overwrites_existing_and_leaves_no_tmp(self):
        self.make_input("1 2 3\n")
        main.atomic_write(self.input, "9 9\n")
        self.assertEqual(self.input.read_text(encoding="utf-8"), "9 9\n")
        self.assertEqual([p.name for p in self.base.iterdir()], ["input.txt"])

    def test_failure_keeps_old_content_and_removes_tmp(self):
        self.make_input("1 2 3\n")
        with mock.patch("main.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                main.atomic_write(self.input, "9 9 9\n")
        self.assertEqual(self.input.read_text(encoding="utf-8"), "1 2 3\n")
        self.assertEqual([p.name for p in self.base.iterdir()], ["input.txt"])

    def test_newlines_not_translated(self):
        main.atomic_write(self.input, "a\nb\n")
        self.assertEqual(self.input.read_bytes(), b"a\nb\n")


class ReadArrayTests(TempDirCase):
    def test_reads_plain_file(self):
        self.make_input("4 7 12\n15 20\n")
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_bom_and_crlf(self):
        self.input.write_bytes("\ufeff4 7\r\n12\r\n".encode("utf-8"))
        self.assertEqual(main.read_array(self.input), [4, 7, 12])

    def test_missing_file_and_directory(self):
        with self.assertRaises(main.ToolError):
            main.read_array(self.base / "nope.txt")
        with self.assertRaises(main.ToolError):
            main.read_array(self.base)

    def test_invalid_content_names_file(self):
        self.make_input("4 7 abc")
        with self.assertRaises(main.ToolError) as ctx:
            main.read_array(self.input)
        self.assertIn("input.txt", str(ctx.exception))

    def test_not_utf8_rejected(self):
        self.input.write_bytes("4 7".encode("utf-16"))
        with self.assertRaises(main.ToolError):
            main.read_array(self.input)


class WriteArrayTests(TempDirCase):
    def test_format_and_roundtrip(self):
        main.write_array([4, -7, 0], self.input)
        self.assertEqual(self.input.read_text(encoding="utf-8"), "4 -7 0\n")
        self.assertEqual(main.read_array(self.input), [4, -7, 0])

    def test_invalid_array_does_not_create_file(self):
        with self.assertRaises(main.ToolError):
            main.write_array([1, "x"], self.input)
        self.assertFalse(self.input.exists())

    def test_empty_array_keeps_existing_file(self):
        self.make_input("1 2\n")
        with self.assertRaises(main.ToolError):
            main.write_array([], self.input)
        self.assertEqual(self.input.read_text(encoding="utf-8"), "1 2\n")

    def test_creates_parent_dir(self):
        target = self.base / "sub" / "input.txt"
        main.write_array([1], target)
        self.assertEqual(main.read_array(target), [1])

    def test_tuple_and_huge_numbers(self):
        main.write_array((10 ** 30, -5), self.input)
        self.assertEqual(main.read_array(self.input), [10 ** 30, -5])


class FormatResultTests(unittest.TestCase):
    def test_exact_text(self):
        text = main.format_result([4, 7, 12, 15, 20], 4, [4, 12, 20], 36)
        self.assertEqual(text, "Исходный массив: 4 7 12 15 20\nДелитель K: 4\n"
                               "Подходящие элементы: 4 12 20\nСумма: 36\n")

    def test_no_matches_says_net(self):
        self.assertIn("Подходящие элементы: нет\nСумма: 0", main.format_result([1], 2, [], 0))

    def test_negative_values(self):
        text = main.format_result([-12, 5], -4, [-12], -12)
        self.assertIn("Делитель K: -4", text)
        self.assertIn("Сумма: -12", text)

    def test_four_lines_and_trailing_newline(self):
        text = main.format_result([1, 2], 1, [1, 2], 3)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len(text.splitlines()), 4)

    def test_long_arrays_not_shortened(self):
        numbers = list(range(100))
        text = main.format_result(numbers, 1, numbers, sum(numbers))
        self.assertIn(" ".join(map(str, numbers)), text)
        self.assertNotIn("…", text)


class SaveResultTests(TempDirCase):
    def test_writes_formatted_text(self):
        main.save_result([4, 8], 4, [4, 8], 12, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"),
                         main.format_result([4, 8], 4, [4, 8], 12))

    def test_overwrites_previous_result(self):
        self.output.write_text("старое", encoding="utf-8")
        main.save_result([1], 1, [1], 1, self.output)
        self.assertNotIn("старое", self.output.read_text(encoding="utf-8"))

    def test_creates_parent_dir(self):
        target = self.base / "out" / "r.txt"
        main.save_result([2], 2, [2], 2, target)
        self.assertTrue(target.exists())

    def test_no_matches_result(self):
        main.save_result([1, 3], 2, [], 0, self.output)
        self.assertIn("Подходящие элементы: нет", self.output.read_text(encoding="utf-8"))

    def test_failure_keeps_old_result(self):
        self.output.write_text("старое", encoding="utf-8")
        with mock.patch("main.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                main.save_result([1], 1, [1], 1, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "старое")


class ShortTests(unittest.TestCase):
    def test_short_list_fully_shown(self):
        self.assertEqual(main.short([1, 2, 3]), "[1, 2, 3]")

    def test_exactly_limit_not_shortened(self):
        text = main.short(list(range(20)))
        self.assertNotIn("…", text)
        self.assertNotIn("всего", text)

    def test_over_limit_shortened_with_total(self):
        text = main.short(list(range(100)))
        self.assertIn("…", text)
        self.assertIn("всего 100", text)
        self.assertIn("19", text)
        self.assertNotIn("20,", text)

    def test_empty_list(self):
        self.assertEqual(main.short([]), "[]")

    def test_custom_limit_and_negatives(self):
        self.assertEqual(main.short([-1, -2, -3], limit=3), "[-1, -2, -3]")
        self.assertEqual(main.short([-1, -2, -3, -4], limit=2), "[-1, -2, … (всего 4)]")


# =========================================================================== резервные копии
class ChecksumTests(unittest.TestCase):
    def test_is_sha256_hex(self):
        value = main._checksum({"numbers": [1, 2]})
        self.assertEqual(len(value), 64)
        int(value, 16)

    def test_deterministic(self):
        self.assertEqual(main._checksum({"numbers": [1, 2]}), main._checksum({"numbers": [1, 2]}))

    def test_key_order_does_not_matter(self):
        self.assertEqual(main._checksum({"a": 1, "b": 2}), main._checksum({"b": 2, "a": 1}))

    def test_changes_with_data(self):
        self.assertNotEqual(main._checksum({"numbers": [1, 2]}), main._checksum({"numbers": [2, 1]}))
        self.assertNotEqual(main._checksum({"numbers": [1]}), main._checksum({"numbers": [1, 0]}))

    def test_matches_independent_computation(self):
        data = {"numbers": [1, -2, 3]}
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(main._checksum(data), hashlib.sha256(canonical.encode("utf-8")).hexdigest())


class ListBackupsTests(TempDirCase):
    def test_missing_dir_gives_empty_list(self):
        self.assertEqual(main.list_backups(self.backups), [])

    def test_ignores_foreign_files(self):
        self.backups.mkdir()
        (self.backups / ".gitkeep").write_text("", encoding="utf-8")
        (self.backups / "notes.json").write_text("{}", encoding="utf-8")
        (self.backups / "2026_manual.json").write_text("{}", encoding="utf-8")
        self.assertEqual(main.list_backups(self.backups), [])

    def test_sorted_from_old_to_new(self):
        newer = self.make_backup_file("20261022_120000_000000_manual.json")
        older = self.make_backup_file("20261021_090000_000000_manual.json")
        self.assertEqual(main.list_backups(self.backups), [older, newer])

    def test_includes_pre_restore(self):
        regular = self.make_backup_file("20261021_090000_000000_manual.json")
        safety = self.make_backup_file("20261022_090000_000000_pre-restore.json")
        self.assertEqual(main.list_backups(self.backups), [regular, safety])

    def test_ignores_directories_with_valid_names(self):
        self.backups.mkdir()
        (self.backups / "20261021_090000_000000_manual.json").mkdir()
        self.assertEqual(main.list_backups(self.backups), [])


class IsPreRestoreTests(unittest.TestCase):
    def test_pre_restore_name(self):
        self.assertTrue(main.is_pre_restore("20261022_090000_000000_pre-restore.json"))

    def test_manual_name(self):
        self.assertFalse(main.is_pre_restore("20261022_090000_000000_manual.json"))

    def test_accepts_path_objects(self):
        self.assertTrue(main.is_pre_restore(Path("20261022_090000_000000_pre-restore.json")))
        self.assertFalse(main.is_pre_restore(Path("20261022_090000_000000_manual.json")))

    def test_uses_file_name_not_directory(self):
        self.assertFalse(main.is_pre_restore(Path("x_pre-restore.json") / "20261022_090000_000000_manual.json"))
        self.assertTrue(main.is_pre_restore(Path("dir") / "20261022_090000_000000_pre-restore.json"))

    def test_similar_but_different_suffix(self):
        self.assertFalse(main.is_pre_restore("20261022_090000_000000_pre-restore.json.bak"))
        self.assertFalse(main.is_pre_restore("pre-restore.json"))


class RotateTests(TempDirCase):
    NAMES = ["2026102{}_090000_000000_manual.json".format(i) for i in range(1, 6)]

    def make_all(self):
        return [self.make_backup_file(name) for name in self.NAMES]

    def test_below_limit_nothing_deleted(self):
        self.make_all()
        main._rotate(self.backups, 10)
        self.assertEqual(len(main.list_backups(self.backups)), 5)

    def test_exactly_limit_nothing_deleted(self):
        self.make_all()
        main._rotate(self.backups, 5)
        self.assertEqual(len(main.list_backups(self.backups)), 5)

    def test_deletes_oldest_over_limit(self):
        paths = self.make_all()
        main._rotate(self.backups, 3)
        self.assertEqual(main.list_backups(self.backups), paths[2:])

    def test_protected_file_survives(self):
        paths = self.make_all()
        main._rotate(self.backups, 3, protect=[paths[0]])
        remaining = main.list_backups(self.backups)
        self.assertIn(paths[0], remaining)
        self.assertEqual(len(remaining), 3)
        self.assertNotIn(paths[1], remaining)

    def test_missing_dir_and_keep_zero(self):
        main._rotate(self.base / "nothing", 3)  # не падает
        self.make_all()
        main._rotate(self.backups, 0)
        self.assertEqual(main.list_backups(self.backups), [])


class CreateBackupTests(TempDirCase):
    def test_structure_of_backup(self):
        self.make_input()
        path = main.create_backup(self.input, self.backups)
        self.assertTrue(path.name.endswith("_manual.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"created", "checksum", "data"})
        self.assertEqual(payload["data"], {"numbers": [4, 7, 12, 15, 20]})
        self.assertEqual(len(payload["checksum"]), 64)
        info = main.verify_backup(path)
        self.assertEqual((info["count"], info["numbers"]), (5, [4, 7, 12, 15, 20]))

    def test_invalid_or_missing_input_not_backed_up(self):
        with self.assertRaises(main.ToolError):
            main.create_backup(self.input, self.backups)  # файла нет
        self.make_input("4 abc")
        with self.assertRaises(main.ToolError):
            main.create_backup(self.input, self.backups)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_unique_names_in_same_microsecond(self):
        self.make_input()
        fixed = main.datetime(2026, 10, 22, 12, 0, 0, 1)
        with mock.patch("main.datetime") as fake:
            fake.now.return_value = fixed
            first = main.create_backup(self.input, self.backups)
            second = main.create_backup(self.input, self.backups)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())

    def test_rotation_keeps_ten_newest(self):
        self.make_input()
        created = [main.create_backup(self.input, self.backups) for _ in range(13)]
        remaining = main.list_backups(self.backups)
        self.assertEqual(len(remaining), 10)
        self.assertEqual(remaining, created[3:])

    def test_kind_pre_restore_in_name(self):
        self.make_input()
        path = main.create_backup(self.input, self.backups, kind=main.PRE_RESTORE)
        self.assertTrue(path.name.endswith("_pre-restore.json"))
        self.assertTrue(main.is_pre_restore(path))


class VerifyBackupTests(TempDirCase):
    def make_valid(self):
        self.make_input()
        return main.create_backup(self.input, self.backups)

    def test_valid_backup_returns_info(self):
        path = self.make_valid()
        info = main.verify_backup(path)
        self.assertEqual(info["path"], path)
        self.assertEqual(info["count"], 5)
        self.assertEqual(info["numbers"], [4, 7, 12, 15, 20])
        self.assertIsInstance(info["created"], str)

    def test_missing_file_rejected(self):
        with self.assertRaises(main.ToolError):
            main.verify_backup(self.backups / "nope.json")

    def test_tampered_data_fails_checksum(self):
        path = self.make_valid()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["data"]["numbers"] = [999]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(main.ToolError) as ctx:
            main.verify_backup(path)
        self.assertIn("SHA-256", str(ctx.exception))

    def test_corrupted_variants_rejected(self):
        path = self.make_valid()
        good = json.loads(path.read_text(encoding="utf-8"))
        variants = {
            "not json": "{oops",
            "list": "[1, 2]",
            "no checksum": json.dumps({"created": "x", "data": good["data"]}),
            "no data": json.dumps({"created": "x", "checksum": "abc"}),
            "no numbers": json.dumps({"created": "x", "checksum": "abc", "data": {}}),
        }
        for label, text in variants.items():
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(main.ToolError, msg=label):
                main.verify_backup(path)

    def test_valid_checksum_but_bad_numbers_rejected(self):
        data = {"numbers": [1, "2"]}
        payload = {"created": "x", "checksum": main._checksum(data), "data": data}
        self.backups.mkdir()
        path = self.backups / "20261022_000000_000000_manual.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(main.ToolError):
            main.verify_backup(path)


class ResolveBackupTests(TempDirCase):
    def test_latest_regular_when_no_name(self):
        self.make_backup_file("20261021_090000_000000_manual.json")
        newest = self.make_backup_file("20261022_090000_000000_manual.json")
        self.assertEqual(main.resolve_backup(self.backups), newest)

    def test_pre_restore_skipped_for_latest(self):
        regular = self.make_backup_file("20261021_090000_000000_manual.json")
        self.make_backup_file("20261022_090000_000000_pre-restore.json")
        self.assertEqual(main.resolve_backup(self.backups), regular)
        deleted = self.make_backup_file("20261023_090000_000000_pre-delete.json")
        self.assertEqual(main.resolve_backup(self.backups), deleted)  # после удаления restore возвращает его

    def test_by_name_in_backup_dir(self):
        self.make_backup_file("20261021_090000_000000_manual.json")
        safety = self.make_backup_file("20261022_090000_000000_pre-restore.json")
        self.assertEqual(main.resolve_backup(self.backups, safety.name), safety)

    def test_by_full_path(self):
        path = self.make_backup_file("20261021_090000_000000_manual.json")
        self.assertEqual(main.resolve_backup(self.base / "other", str(path)), path)

    def test_errors(self):
        with self.assertRaises(main.ToolError):  # папки копий нет
            main.resolve_backup(self.backups)
        self.make_backup_file("20261022_090000_000000_pre-restore.json")
        with self.assertRaises(main.ToolError):  # только страховочные
            main.resolve_backup(self.backups)
        with self.assertRaises(main.ToolError):  # неизвестное имя
            main.resolve_backup(self.backups, "missing.json")


class RestoreBackupTests(TempDirCase):
    def test_restore_latest_creates_safety_copy(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("1 2\n")
        _, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertEqual(numbers, [4, 7, 12, 15, 20])
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])
        self.assertTrue(main.is_pre_restore(safety))
        self.assertEqual(main.verify_backup(safety)["numbers"], [1, 2])

    def test_repeat_restore_and_undo_by_name(self):
        self.make_input()
        first = main.create_backup(self.input, self.backups)
        self.make_input("1 2\n")
        _, _, safety = main.restore_backup(self.input, self.backups, first.name)
        main.restore_backup(self.input, self.backups, safety.name)  # отмена восстановления
        self.assertEqual(main.read_array(self.input), [1, 2])
        main.restore_backup(self.input, self.backups)  # повторно: берётся обычная копия, не страховочная
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_no_safety_copy_when_input_missing_or_corrupted(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.input.unlink()
        _, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertIsNone(safety)
        self.assertEqual(numbers, [4, 7, 12, 15, 20])
        self.make_input("garbage")
        _, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertIsNone(safety)
        self.assertEqual(main.read_array(self.input), numbers)

    def test_errors_leave_input_unchanged(self):
        self.make_input()
        with self.assertRaises(main.ToolError):  # копий нет
            main.restore_backup(self.input, self.backups)
        with self.assertRaises(main.ToolError):  # неизвестное имя
            main.restore_backup(self.input, self.backups, "missing.json")
        path = main.create_backup(self.input, self.backups)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["data"]["numbers"] = [999]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.make_input("1 2\n")
        with self.assertRaises(main.ToolError) as ctx:
            main.restore_backup(self.input, self.backups)
        self.assertIn("SHA-256", str(ctx.exception))
        self.assertEqual(main.read_array(self.input), [1, 2])
        self.assertEqual(len(main.list_backups(self.backups)), 1)  # страховочная не создавалась

    def test_rotation_never_deletes_backup_being_restored(self):
        self.make_input()
        oldest = main.create_backup(self.input, self.backups, keep=3)
        for _ in range(2):
            main.create_backup(self.input, self.backups, keep=3)
        main.restore_backup(self.input, self.backups, oldest.name, keep=3)
        self.assertTrue(oldest.exists())


class IsSafetyCopyTests(unittest.TestCase):
    def test_pre_restore_is_safety(self):
        self.assertTrue(main.is_safety_copy("20261022_090000_000000_pre-restore.json"))

    def test_pre_delete_is_safety(self):
        self.assertTrue(main.is_safety_copy("20261022_090000_000000_pre-delete.json"))

    def test_manual_is_not_safety(self):
        self.assertFalse(main.is_safety_copy("20261022_090000_000000_manual.json"))

    def test_accepts_path_objects_and_uses_file_name(self):
        self.assertTrue(main.is_safety_copy(Path("dir") / "20261022_090000_000000_pre-delete.json"))
        self.assertFalse(main.is_safety_copy(Path("x_pre-delete.json") / "20261022_090000_000000_manual.json"))

    def test_similar_suffixes_rejected(self):
        self.assertFalse(main.is_safety_copy("20261022_090000_000000_pre-delete.json.bak"))
        self.assertFalse(main.is_safety_copy("pre-delete.json"))


class DeleteArrayTests(TempDirCase):
    def test_deletes_file_and_creates_pre_delete_copy(self):
        self.make_input()
        safety = main.delete_array(self.input, self.backups)
        self.assertFalse(self.input.exists())
        self.assertTrue(safety.name.endswith("_pre-delete.json"))
        self.assertEqual(main.verify_backup(safety)["numbers"], [4, 7, 12, 15, 20])

    def test_missing_file_raises(self):
        with self.assertRaises(main.ToolError) as ctx:
            main.delete_array(self.input, self.backups)
        self.assertIn("input.txt", str(ctx.exception))
        self.assertEqual(main.list_backups(self.backups), [])

    def test_corrupted_file_deleted_without_copy(self):
        self.make_input("garbage")
        self.assertIsNone(main.delete_array(self.input, self.backups))
        self.assertFalse(self.input.exists())
        self.assertEqual(main.list_backups(self.backups), [])

    def test_restore_after_delete_brings_array_back(self):
        self.make_input()
        safety = main.delete_array(self.input, self.backups)
        main.restore_backup(self.input, self.backups, safety.name)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_directory_is_not_deleted_and_other_files_stay(self):
        self.make_input()
        self.output.write_text("результат", encoding="utf-8")
        with self.assertRaises(main.ToolError):
            main.delete_array(self.base, self.backups)  # это папка, а не файл
        main.delete_array(self.input, self.backups)
        self.assertTrue(self.output.exists())
        self.assertTrue(self.base.exists())


# =========================================================================== ввод и вывод
class AskConfirmTests(unittest.TestCase):
    def ask(self, answer):
        with mock.patch("builtins.input", return_value=answer):
            return main.ask_confirm("Удалить?")

    def test_yes_variants_accepted(self):
        for answer in ("да", "Да", "Д", "y", "YES", "yes"):
            self.assertTrue(self.ask(answer), msg=answer)

    def test_no_variants_rejected(self):
        for answer in ("нет", "н", "n", "no"):
            self.assertFalse(self.ask(answer), msg=answer)

    def test_empty_and_garbage_rejected(self):
        for answer in ("", "   ", "может быть", "1", "daa"):
            self.assertFalse(self.ask(answer), msg=answer)

    def test_whitespace_trimmed(self):
        self.assertTrue(self.ask("  да  "))

    def test_prompt_text_and_eof_propagates(self):
        with mock.patch("builtins.input", return_value="да") as fake:
            main.ask_confirm("Удалить input.txt?")
        fake.assert_called_once_with("Удалить input.txt? (да/нет): ")
        with mock.patch("builtins.input", side_effect=EOFError()):
            with self.assertRaises(EOFError):
                main.ask_confirm("?")


class AskKTests(unittest.TestCase):
    def test_returns_int(self):
        with mock.patch("builtins.input", return_value="4"):
            self.assertEqual(main.ask_k(), 4)

    def test_whitespace_and_negative(self):
        with mock.patch("builtins.input", return_value="  -3 "):
            self.assertEqual(main.ask_k(), -3)

    def test_zero_rejected(self):
        with mock.patch("builtins.input", return_value="0"):
            with self.assertRaises(main.ToolError):
                main.ask_k()

    def test_garbage_rejected(self):
        for bad in ("abc", "", "1.5"):
            with mock.patch("builtins.input", return_value=bad):
                with self.assertRaises(main.ToolError, msg=bad):
                    main.ask_k()

    def test_prompt_text(self):
        with mock.patch("builtins.input", return_value="2") as fake:
            main.ask_k()
        fake.assert_called_once_with("Введите целое число K (не ноль): ")


class ManualInputTests(unittest.TestCase):
    def test_parses_numbers(self):
        with mock.patch("builtins.input", return_value="4 7 12 15 20"):
            self.assertEqual(main.manual_input(), [4, 7, 12, 15, 20])

    def test_negative_and_plus(self):
        with mock.patch("builtins.input", return_value="-1 +2 0"):
            self.assertEqual(main.manual_input(), [-1, 2, 0])

    def test_empty_rejected(self):
        with mock.patch("builtins.input", return_value="   "):
            with self.assertRaises(main.ToolError):
                main.manual_input()

    def test_garbage_rejected(self):
        with mock.patch("builtins.input", return_value="1 2 x"):
            with self.assertRaises(main.ToolError) as ctx:
                main.manual_input()
        self.assertIn("№3", str(ctx.exception))

    def test_prompt_text_and_eof_propagates(self):
        with mock.patch("builtins.input", side_effect=EOFError()) as fake:
            with self.assertRaises(EOFError):
                main.manual_input()
        fake.assert_called_once_with("Введите целые числа через пробел: ")


class CalculateAndShowTests(TempDirCase):
    def test_prints_and_returns_result(self):
        (selected, total), out = capture(main.calculate_and_show, [4, 7, 12, 15, 20], 4, self.output)
        self.assertEqual((selected, total), ([4, 12, 20], 36))
        self.assertIn("Подходящие элементы: [4, 12, 20]", out)
        self.assertIn("Сумма элементов, кратных 4: 36", out)

    def test_writes_result_file(self):
        capture(main.calculate_and_show, [4, 7, 12, 15, 20], 4, self.output)
        self.assertEqual(self.output.read_text(encoding="utf-8"),
                         main.format_result([4, 7, 12, 15, 20], 4, [4, 12, 20], 36))

    def test_no_matches_prints_net(self):
        _, out = capture(main.calculate_and_show, [1, 3], 2, self.output)
        self.assertIn("Подходящие элементы: нет", out)
        self.assertIn("кратных 2: 0", out)

    def test_label_replaces_path_in_message(self):
        _, out = capture(main.calculate_and_show, [2], 2, self.output, "output.txt")
        self.assertIn("Результат сохранён в файл: output.txt", out)
        self.assertNotIn(str(self.base), out)

    def test_invalid_data_raises_and_creates_no_file(self):
        with self.assertRaises(main.ToolError):
            capture(main.calculate_and_show, [1, 2], 0, self.output)
        with self.assertRaises(main.ToolError):
            capture(main.calculate_and_show, [], 3, self.output)
        self.assertFalse(self.output.exists())


# =========================================================================== команды
class PathsTests(unittest.TestCase):
    def test_names(self):
        input_path, output_path, backup_dir = main._paths("base")
        self.assertEqual(input_path.name, "input.txt")
        self.assertEqual(output_path.name, "output.txt")
        self.assertEqual(backup_dir.name, "backups")

    def test_all_inside_base_dir(self):
        base = Path("some") / "dir"
        for path in main._paths(base):
            self.assertEqual(path.parent, base)

    def test_accepts_string_and_returns_paths(self):
        for path in main._paths("base"):
            self.assertIsInstance(path, Path)

    def test_matches_constants(self):
        input_path, output_path, backup_dir = main._paths(".")
        self.assertEqual((input_path.name, output_path.name, backup_dir.name),
                         (main.INPUT_NAME, main.OUTPUT_NAME, main.BACKUP_DIR_NAME))

    def test_three_distinct_paths(self):
        self.assertEqual(len(set(main._paths("base"))), 3)


class CmdSumTests(TempDirCase):
    def test_array_and_k(self):
        code, out = capture(main.cmd_sum, ns(array=["4", "7", "12", "15", "20"], k="4"), self.base)
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("кратных 4: 36", out)
        self.assertIn("Сумма: 36", self.output.read_text(encoding="utf-8"))

    def test_input_file(self):
        self.make_input()
        code, _ = capture(main.cmd_sum, ns(input=str(self.input), k="4"), self.base)
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("Подходящие элементы: 4 12 20", self.output.read_text(encoding="utf-8"))

    def test_custom_output(self):
        custom = self.base / "result.txt"
        capture(main.cmd_sum, ns(array=["4", "8"], k="4", output=str(custom)), self.base)
        self.assertIn("Сумма: 12", custom.read_text(encoding="utf-8"))
        self.assertFalse(self.output.exists())

    def test_interactive_array_and_k(self):
        code, out = capture(main.cmd_sum, ns(), self.base, inputs=["4 7 12 15 20", "4"])
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("кратных 4: 36", out)
        _, out = capture(main.cmd_sum, ns(array=["4", "8"]), self.base, inputs=["4"])  # K спрашивается отдельно
        self.assertIn("кратных 4: 12", out)

    def test_errors_raise_tool_error_without_output_file(self):
        bad_cases = [ns(array=["1", "2"], k="0"), ns(array=["1", "2"], k="abc"),
                     ns(array=["1", "x"], k="4"), ns(input=str(self.base / "none.txt"), k="4")]
        for args in bad_cases:
            with self.assertRaises(main.ToolError, msg=vars(args)):
                capture(main.cmd_sum, args, self.base)
        self.assertFalse(self.output.exists())


class CmdBackupTests(TempDirCase):
    def test_creates_backup_and_reports_name(self):
        self.make_input()
        code, out = capture(main.cmd_backup, ns(), self.base)
        self.assertEqual(code, main.EXIT_OK)
        files = main.list_backups(self.backups)
        self.assertEqual(len(files), 1)
        self.assertIn("Резервная копия создана: " + files[0].name, out)

    def test_prints_count_and_maximum(self):
        self.make_input()
        _, out = capture(main.cmd_backup, ns(), self.base)
        self.assertIn("Копий в папке: 1 (максимум {})".format(main.KEEP_BACKUPS), out)

    def test_missing_input_raises(self):
        with self.assertRaises(main.ToolError):
            capture(main.cmd_backup, ns(), self.base)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_invalid_input_raises(self):
        self.make_input("4 abc")
        with self.assertRaises(main.ToolError):
            capture(main.cmd_backup, ns(), self.base)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_repeated_calls_accumulate_backups(self):
        self.make_input()
        for _ in range(3):
            capture(main.cmd_backup, ns(), self.base)
        self.assertEqual(len(main.list_backups(self.backups)), 3)


class CmdBackupsTests(TempDirCase):
    def test_empty(self):
        code, out = capture(main.cmd_backups, ns(), self.base)
        self.assertEqual((code, out.strip()), (main.EXIT_OK, "Резервных копий нет."))

    def test_lists_valid_backup_with_count(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        _, out = capture(main.cmd_backups, ns(), self.base)
        self.assertIn("OK, элементов: 5", out)

    def test_marks_pre_restore(self):
        self.make_input()
        main.create_backup(self.input, self.backups, kind=main.PRE_RESTORE)
        _, out = capture(main.cmd_backups, ns(), self.base)
        self.assertIn("[страховочная]", out)

    def test_marks_corrupted_and_still_ok_code(self):
        self.make_input("1 2\n")
        path = main.create_backup(self.input, self.backups)
        path.write_text("{oops", encoding="utf-8")
        code, out = capture(main.cmd_backups, ns(), self.base)
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("ПОВРЕЖДЕНА", out)

    def test_order_old_to_new(self):
        self.make_input()
        first = main.create_backup(self.input, self.backups)
        second = main.create_backup(self.input, self.backups)
        _, out = capture(main.cmd_backups, ns(), self.base)
        self.assertLess(out.index(first.name), out.index(second.name))


class CmdDeleteTests(TempDirCase):
    def test_yes_flag_deletes_without_question(self):
        self.make_input()
        code, out = capture(main.cmd_delete, ns(yes=True), self.base)
        self.assertEqual(code, main.EXIT_OK)
        self.assertFalse(self.input.exists())
        self.assertIn("Массив удалён: input.txt", out)

    def test_confirmed_by_user(self):
        self.make_input()
        capture(main.cmd_delete, ns(), self.base, inputs=["да"])
        self.assertFalse(self.input.exists())

    def test_declined_keeps_file(self):
        self.make_input()
        code, out = capture(main.cmd_delete, ns(), self.base, inputs=["нет"])
        self.assertEqual(code, main.EXIT_OK)
        self.assertTrue(self.input.exists())
        self.assertIn("Удаление отменено", out)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_missing_array_raises_before_question(self):
        with self.assertRaises(main.ToolError):
            capture(main.cmd_delete, ns(yes=True), self.base)
        with self.assertRaises(main.ToolError):
            capture(main.cmd_delete, ns(), self.base)  # вопрос не задаётся: input не потребляется

    def test_prints_safety_copy_hint_and_it_is_listed(self):
        self.make_input()
        _, out = capture(main.cmd_delete, ns(yes=True), self.base)
        self.assertIn("Копия перед удалением сохранена", out)
        _, out = capture(main.cmd_backups, ns(), self.base)
        self.assertIn("[страховочная]", out)


class CmdRestoreTests(TempDirCase):
    def test_restores_latest(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("1\n")
        code, out = capture(main.cmd_restore, ns(), self.base)
        self.assertEqual(code, main.EXIT_OK)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])
        self.assertIn("Элементов в input.txt: 5", out)

    def test_restores_by_name(self):
        self.make_input()
        name = main.create_backup(self.input, self.backups).name
        self.make_input("1\n")
        capture(main.cmd_restore, ns(name=name), self.base)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_reports_safety_copy(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("1\n")
        _, out = capture(main.cmd_restore, ns(), self.base)
        self.assertIn("Состояние до восстановления сохранено", out)

    def test_no_safety_message_when_input_missing(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.input.unlink()
        _, out = capture(main.cmd_restore, ns(), self.base)
        self.assertNotIn("Состояние до восстановления", out)
        self.assertTrue(self.input.exists())

    def test_no_backups_raises(self):
        with self.assertRaises(main.ToolError):
            capture(main.cmd_restore, ns(), self.base)


class MenuTests(TempDirCase):
    def test_manual_input_and_exit(self):
        code, out = capture(main.menu, self.base, inputs=["1", "4 7 12 15 20", "4", "0"])
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("кратных 4: 36", out)
        self.assertIn("Работа программы завершена", out)
        self.assertTrue(self.output.exists())

    def test_load_default_and_other_file(self):
        self.make_input()
        other = self.base / "other.txt"
        other.write_text("-12 0 8 5 -4\n", encoding="utf-8")
        _, out = capture(main.menu, self.base,
                         inputs=["2", "4", "3", '"{}"'.format(other), "4", "0"])
        self.assertIn("Загружен массив: [4, 7, 12, 15, 20]", out)
        self.assertIn("кратных 4: 36", out)
        self.assertIn("кратных 4: -8", out)

    def test_save_show_backup_restore(self):
        _, out = capture(main.menu, self.base, inputs=["7", "4", "1 2 3", "7", "5", "0"])
        self.assertIn("Массив ещё не загружен", out)
        self.assertIn("Текущий массив: [1, 2, 3]", out)
        self.assertEqual(main.read_array(self.input), [1, 2, 3])
        self.assertEqual(len(main.list_backups(self.backups)), 1)
        self.make_input("9\n")
        _, out = capture(main.menu, self.base, inputs=["6", "", "0"])
        self.assertIn("Данные восстановлены", out)
        self.assertEqual(main.read_array(self.input), [1, 2, 3])
        _, out = capture(main.menu, self.base, inputs=["8", "нет", "0"])  # отказ от удаления
        self.assertIn("Удаление отменено", out)
        self.assertTrue(self.input.exists())
        _, out = capture(main.menu, self.base, inputs=["8", "да", "8", "0"])  # удаление; повторно — ошибка
        self.assertIn("Массив удалён", out)
        self.assertIn("Сохранённого массива нет", out)
        self.assertFalse(self.input.exists())
        _, out = capture(main.menu, self.base, inputs=["6", "", "0"])  # откат: самая свежая обычная копия
        self.assertEqual(main.read_array(self.input), [1, 2, 3])

    def test_errors_do_not_stop_program(self):
        code, out = capture(main.menu, self.base,
                            inputs=["1", "abc", "1", "1 2", "0", "2", "5", "6", "99", "0"])
        self.assertEqual(code, main.EXIT_OK)
        self.assertGreaterEqual(out.count("ОШИБКА"), 4)
        self.assertIn("Нет такого пункта", out)

    def test_eof_exits_cleanly(self):
        code, out = capture(main.menu, self.base)  # input() сразу исчерпан
        self.assertEqual(code, main.EXIT_OK)
        code, out = capture(main.menu, self.base, inputs=["1"])  # EOF в середине ввода
        self.assertEqual(code, main.EXIT_OK)
        self.assertIn("Работа программы завершена", out)


# =========================================================================== CLI
class BuildParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = main.build_parser()

    def test_no_command_means_menu(self):
        self.assertIsNone(self.parser.parse_args([]).command)

    def test_sum_arguments(self):
        args = self.parser.parse_args(["sum", "--array", "1", "2", "-3", "--k", "4", "--output", "r.txt"])
        self.assertEqual((args.command, args.array, args.k, args.output), ("sum", ["1", "2", "-3"], "4", "r.txt"))
        args = self.parser.parse_args(["sum", "--input", "f.txt"])
        self.assertEqual((args.input, args.array, args.k), ("f.txt", None, None))

    def test_array_and_input_are_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                self.parser.parse_args(["sum", "--array", "1", "--input", "f.txt"])
        self.assertEqual(ctx.exception.code, 2)

    def test_restore_name_is_optional(self):
        self.assertIsNone(self.parser.parse_args(["restore"]).name)
        self.assertEqual(self.parser.parse_args(["restore", "x.json"]).name, "x.json")

    def test_backup_commands_and_unknown_command(self):
        self.assertEqual(self.parser.parse_args(["backup"]).command, "backup")
        self.assertEqual(self.parser.parse_args(["backups"]).command, "backups")
        self.assertFalse(self.parser.parse_args(["delete"]).yes)
        self.assertTrue(self.parser.parse_args(["delete", "--yes"]).yes)
        for argv in (["frobnicate"], ["restore", "a", "b"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    self.parser.parse_args(argv)
            self.assertEqual(ctx.exception.code, 2, msg=argv)


class RunTests(TempDirCase):
    def test_success_returns_0_creates_output_and_logs(self):
        code, out, err = run_cli(["sum", "--array", "4", "7", "12", "15", "20", "--k", "4"], self.base)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Сумма элементов, кратных 4: 36", out)
        self.assertIn("Сумма: 36", self.output.read_text(encoding="utf-8"))
        log = self.log_text()
        self.assertIn("Запуск: команда=sum", log)
        self.assertIn("Расчёт: элементов=5, K=4, подходящих=3, сумма=36", log)
        self.assertIn("Завершение: код=0", log)

    def test_errors_return_1_without_traceback_and_are_logged(self):
        self.make_input("4 7 abc\n")
        cases = [
            ["sum", "--array", "1", "2", "--k", "0"],
            ["sum", "--array", "1", "2", "--k", "abc"],
            ["sum", "--array", "1", "x", "--k", "4"],
            ["sum", "--input", str(self.input), "--k", "4"],
            ["sum", "--input", str(self.base / "none.txt"), "--k", "4"],
            ["backup"],  # input.txt повреждён
            ["restore"],  # копий нет
        ]
        for argv in cases:
            code, out, err = run_cli(argv, self.base)
            self.assertEqual(code, 1, msg=argv)
            self.assertIn("ОШИБКА", err, msg=argv)
            self.assertNotIn("Traceback", err + out, msg=argv)
        self.assertFalse(self.output.exists())
        self.assertGreaterEqual(self.log_text().count("| ERROR"), len(cases))
        self.assertIn("Завершение: код=1", self.log_text())

    def test_bad_arguments_exit_2(self):
        for argv in (["sum", "--array", "1", "--input", "f.txt"], ["frobnicate"], ["restore", "a", "b"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    run_cli(argv, self.base)
            self.assertEqual(ctx.exception.code, 2, msg=argv)

    def test_interrupt_returns_1_and_unexpected_error_is_logged_and_raised(self):
        with mock.patch.dict(main._COMMANDS, {"backups": mock.Mock(side_effect=KeyboardInterrupt())}):
            code, _, err = run_cli(["backups"], self.base)
        self.assertEqual(code, 1)
        self.assertIn("Прервано пользователем", err)
        self.assertIn("Прервано пользователем", self.log_text())
        with mock.patch.dict(main._COMMANDS, {"backups": mock.Mock(side_effect=RuntimeError("сбой"))}):
            with self.assertRaises(RuntimeError):
                run_cli(["backups"], self.base)
        self.assertIn("Непредвиденная ошибка", self.log_text())
        self.assertIn("RuntimeError: сбой", self.log_text())

    def test_no_command_runs_menu_and_flow_works(self):
        code, out, _ = run_cli([], self.base, inputs=["0"])
        self.assertEqual(code, 0)
        self.assertIn("МЕНЮ", out)
        self.make_input()
        code, out, _ = run_cli(["backup"], self.base)
        self.assertEqual(code, 0)
        self.make_input("1 2 3\n")
        code, out, _ = run_cli(["restore"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Состояние до восстановления сохранено", out)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])
        _, out, _ = run_cli(["backups"], self.base)
        self.assertIn("[страховочная]", out)


class MainTests(unittest.TestCase):
    def test_passes_argv_to_run_and_returns_code(self):
        with mock.patch("main.run", return_value=0) as fake:
            self.assertEqual(main.main(["backups"]), 0)
        fake.assert_called_once_with(["backups"])

    def test_uses_sys_argv_when_none(self):
        with mock.patch("main.run", return_value=0) as fake:
            with mock.patch("sys.argv", ["main.py", "sum", "--k", "3"]):
                main.main()
        fake.assert_called_once_with(["sum", "--k", "3"])

    def test_returns_error_code_from_run(self):
        with mock.patch("main.run", return_value=1):
            self.assertEqual(main.main([]), 1)

    def test_streams_reconfigured_to_utf8(self):
        fake_out, fake_err = mock.Mock(), mock.Mock()
        with mock.patch("main.run", return_value=0):
            with mock.patch("sys.stdout", fake_out), mock.patch("sys.stderr", fake_err):
                main.main([])
        fake_out.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
        fake_err.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")

    def test_reconfigure_errors_and_missing_method_ignored(self):
        broken = mock.Mock()
        broken.reconfigure.side_effect = ValueError("nope")
        with mock.patch("main.run", return_value=0):
            with mock.patch("sys.stdout", broken), mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(main.main([]), 0)  # StringIO без reconfigure + ValueError


# =========================================================================== журнал
class LogLevelTests(unittest.TestCase):
    def test_none_gives_info(self):
        self.assertEqual(main._log_level(None), logging.INFO)

    def test_names_case_insensitive(self):
        self.assertEqual(main._log_level("debug"), logging.DEBUG)
        self.assertEqual(main._log_level(" Warning "), logging.WARNING)

    def test_all_known_names(self):
        for name, level in (("DEBUG", 10), ("INFO", 20), ("WARNING", 30), ("ERROR", 40), ("CRITICAL", 50)):
            self.assertEqual(main._log_level(name), level)

    def test_unknown_name_gives_info(self):
        for bad in ("abc", "", "TRACE"):
            self.assertEqual(main._log_level(bad), logging.INFO, msg=bad)

    def test_numeric_levels(self):
        self.assertEqual(main._log_level(logging.ERROR), logging.ERROR)
        self.assertEqual(main._log_level(7), logging.INFO)  # нестандартное число
        self.assertEqual(main._log_level(2.5), logging.INFO)


class ClipTests(unittest.TestCase):
    def test_short_value_unchanged(self):
        self.assertEqual(main._clip(12345), "12345")

    def test_exact_limit_unchanged(self):
        self.assertEqual(main._clip("a" * 80), "a" * 80)

    def test_long_value_clipped_with_length(self):
        text = main._clip("a" * 200)
        self.assertTrue(text.startswith("a" * 80 + "…"))
        self.assertIn("всего 200", text)

    def test_huge_number(self):
        text = main._clip(10 ** 500)
        self.assertLess(len(text), 130)
        self.assertIn("всего 501", text)

    def test_custom_limit_and_non_str(self):
        self.assertEqual(main._clip(-123456, limit=3), "-12…(всего 7 симв.)")
        self.assertEqual(main._clip(None), "None")


class LogFilePathTests(unittest.TestCase):
    def test_file_name_and_folder(self):
        path = main.log_file_path("base")
        self.assertEqual((path.parent.name, path.name), ("logs", "app.log"))

    def test_inside_base_dir(self):
        base = Path("some") / "dir"
        self.assertEqual(main.log_file_path(base), base / "logs" / "app.log")

    def test_accepts_string(self):
        self.assertIsInstance(main.log_file_path("base"), Path)

    def test_matches_constants(self):
        path = main.log_file_path(".")
        self.assertEqual((path.parent.name, path.name), (main.LOG_DIR_NAME, main.LOG_FILE_NAME))

    def test_does_not_create_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            main.log_file_path(tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class SetupLoggingTests(TempDirCase):
    def test_creates_folder_and_file_if_missing(self):
        self.assertFalse(self.log_file.parent.exists())
        path = main.setup_logging(self.base)
        self.assertEqual(path, self.log_file)
        self.assertTrue(self.log_file.is_file())

    def test_messages_written_to_file_utf8_with_format(self):
        main.setup_logging(self.base)
        main.log.info("Проверка записи")
        main.shutdown_logging()
        line = self.log_text().strip().splitlines()[-1]
        self.assertIn("| INFO     | Проверка записи", line)
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \|")

    def test_level_parameter_and_environment(self):
        main.setup_logging(self.base, level="WARNING")
        main.log.info("скрыто")
        main.log.warning("видно")
        main.shutdown_logging()
        self.assertNotIn("скрыто", self.log_text())
        self.assertIn("видно", self.log_text())
        with mock.patch.dict(os.environ, {main.LOG_LEVEL_ENV: "debug"}):
            main.setup_logging(self.base)
            main.log.debug("отладка")
            main.shutdown_logging()
        self.assertIn("отладка", self.log_text())

    def test_repeated_setup_does_not_duplicate_lines(self):
        main.setup_logging(self.base)
        main.setup_logging(self.base)
        main.log.info("одна строка")
        main.shutdown_logging()
        self.assertEqual(self.log_text().count("одна строка"), 1)
        handlers = [h for h in main.log.handlers if isinstance(h, logging.FileHandler)]
        self.assertEqual(handlers, [])

    def test_unavailable_log_dir_returns_none_with_warning(self):
        (self.base / "logs").write_text("я файл, а не папка", encoding="utf-8")  # mkdir невозможен
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(main.setup_logging(self.base))
        self.assertIn("ПРЕДУПРЕЖДЕНИЕ", err.getvalue())
        code, out, _ = run_cli(["sum", "--array", "4", "8", "--k", "4"], self.base)  # программа работает без журнала
        self.assertEqual(code, 0)
        self.assertIn("кратных 4: 12", out)


class ShutdownLoggingTests(TempDirCase):
    def test_stops_writing_after_shutdown(self):
        main.setup_logging(self.base)
        main.log.info("до")
        main.shutdown_logging()
        main.log.info("после")
        self.assertIn("до", self.log_text())
        self.assertNotIn("после", self.log_text())

    def test_repeated_shutdown_is_safe(self):
        main.setup_logging(self.base)
        main.shutdown_logging()
        main.shutdown_logging()
        main.shutdown_logging()

    def test_shutdown_without_setup_is_safe(self):
        main.shutdown_logging()
        main.log.info("без файла")  # NullHandler — без ошибок

    def test_file_released_and_can_be_deleted(self):
        main.setup_logging(self.base)
        main.log.info("x")
        main.shutdown_logging()
        self.log_file.unlink()
        self.assertFalse(self.log_file.exists())

    def test_removes_file_handler_but_keeps_null_handler(self):
        main.setup_logging(self.base)
        self.assertTrue(any(isinstance(h, logging.FileHandler) for h in main.log.handlers))
        main.shutdown_logging()
        self.assertFalse(any(isinstance(h, logging.FileHandler) for h in main.log.handlers))
        self.assertTrue(any(isinstance(h, logging.NullHandler) for h in main.log.handlers))


if __name__ == "__main__":
    unittest.main()
