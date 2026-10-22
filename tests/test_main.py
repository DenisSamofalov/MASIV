"""Автоматические тесты программы Array Sum (соответствие ТЗ: FR-1…FR-12, NFR-3…NFR-5)."""
import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import main


def run_cli(argv, base_dir, inputs=()):
    """Запускает main.run, возвращает (код, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with mock.patch("builtins.input", side_effect=list(inputs) + [EOFError()] * 50):
            code = main.run(argv, base_dir)
    return code, out.getvalue(), err.getvalue()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.input = self.base / "input.txt"
        self.output = self.base / "output.txt"
        self.backups = self.base / "backups"


class ParseTests(unittest.TestCase):
    def test_parse_spaces_and_newlines(self):
        self.assertEqual(main.parse_numbers("4 7\n12\t15  20\n"), [4, 7, 12, 15, 20])

    def test_parse_negative_zero_and_plus(self):
        self.assertEqual(main.parse_numbers("-12 0 +8"), [-12, 0, 8])

    def test_parse_empty(self):
        for text in ("", "   \n\t "):
            with self.assertRaises(main.ToolError):
                main.parse_numbers(text)

    def test_parse_rejects_non_integers(self):
        for text in ("4 abc", "1.5", "1,2", "1e3", "1_000", "--5", "٣"):
            with self.assertRaises(main.ToolError, msg=text):
                main.parse_numbers(text)

    def test_error_names_position(self):
        with self.assertRaises(main.ToolError) as ctx:
            main.parse_numbers("1 2 x")
        self.assertIn("№3", str(ctx.exception))

    def test_parse_k(self):
        self.assertEqual(main.parse_k("4"), 4)
        self.assertEqual(main.parse_k(" -4 "), -4)
        self.assertEqual(main.parse_k(7), 7)
        for bad in ("0", "abc", "", "1.5", 0, True, 2.5):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.parse_k(bad)


class SumTests(unittest.TestCase):
    def test_basic_example(self):
        self.assertEqual(main.sum_divisible([4, 7, 12, 15, 20], 4), ([4, 12, 20], 36))

    def test_no_matches(self):
        self.assertEqual(main.sum_divisible([1, 3, 7], 2), ([], 0))

    def test_negative_numbers(self):
        self.assertEqual(main.sum_divisible([-12, 0, 8, 5, -4], 4), ([-12, 0, 8, -4], -8))

    def test_negative_k(self):
        self.assertEqual(main.sum_divisible([-6, -4, 0, 8], -2), ([-6, -4, 0, 8], -2))

    def test_zero_element_counts_as_divisible(self):
        self.assertEqual(main.sum_divisible([0], 5), ([0], 0))

    def test_k_one_takes_everything(self):
        self.assertEqual(main.sum_divisible([4, 7, 12, 15, 20], 1), ([4, 7, 12, 15, 20], 58))

    def test_k_larger_than_all_elements(self):
        self.assertEqual(main.sum_divisible([4, 7], 100), ([], 0))

    def test_zero_k_rejected(self):
        with self.assertRaises(main.ToolError):
            main.sum_divisible([1, 2], 0)

    def test_empty_array_rejected(self):
        with self.assertRaises(main.ToolError):
            main.sum_divisible([], 3)

    def test_non_integer_items_rejected(self):
        for bad in ([1, 2.5], [1, "2"], [True], "123", None):
            with self.assertRaises(main.ToolError, msg=repr(bad)):
                main.sum_divisible(bad, 2)

    def test_huge_numbers(self):
        big = 10 ** 30
        self.assertEqual(main.sum_divisible([big, big + 1], 10), ([big], big))

    def test_performance_one_million(self):  # NFR-5: < 1 с
        numbers = list(range(1, 1000001))
        started = time.perf_counter()
        _, total = main.sum_divisible(numbers, 7)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(total, 7 * (142857 * 142858 // 2))

    def test_parse_one_million_fast(self):
        text = " ".join(map(str, range(1000000)))
        started = time.perf_counter()
        self.assertEqual(len(main.parse_numbers(text)), 1000000)
        self.assertLess(time.perf_counter() - started, 1.0)


class FileTests(TempDirCase):
    def test_read_write_roundtrip(self):
        main.write_array([4, -7, 0], self.input)
        self.assertEqual(self.input.read_text(encoding="utf-8"), "4 -7 0\n")
        self.assertEqual(main.read_array(self.input), [4, -7, 0])

    def test_read_with_bom_and_crlf(self):
        self.input.write_bytes("\ufeff4 7\r\n12\r\n".encode("utf-8"))
        self.assertEqual(main.read_array(self.input), [4, 7, 12])

    def test_read_missing_file(self):
        with self.assertRaises(main.ToolError):
            main.read_array(self.base / "nope.txt")

    def test_read_invalid_content_names_file(self):
        self.input.write_text("4 7 abc", encoding="utf-8")
        with self.assertRaises(main.ToolError) as ctx:
            main.read_array(self.input)
        self.assertIn("input.txt", str(ctx.exception))

    def test_read_not_utf8(self):
        self.input.write_bytes("4 7".encode("utf-16"))
        with self.assertRaises(main.ToolError):
            main.read_array(self.input)

    def test_read_directory(self):
        with self.assertRaises(main.ToolError):
            main.read_array(self.base)

    def test_atomic_write_leaves_no_tmp_and_keeps_old_on_failure(self):
        self.input.write_text("1 2 3\n", encoding="utf-8")
        with mock.patch("main.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                main.atomic_write(self.input, "9 9 9\n")
        self.assertEqual(self.input.read_text(encoding="utf-8"), "1 2 3\n")
        self.assertEqual([p.name for p in self.base.iterdir()], ["input.txt"])

    def test_format_result(self):
        text = main.format_result([4, 7, 12, 15, 20], 4, [4, 12, 20], 36)
        self.assertEqual(text, "Исходный массив: 4 7 12 15 20\nДелитель K: 4\n"
                               "Подходящие элементы: 4 12 20\nСумма: 36\n")

    def test_format_result_no_matches(self):
        self.assertIn("Подходящие элементы: нет\nСумма: 0", main.format_result([1], 2, [], 0))

    def test_short(self):
        self.assertEqual(main.short([1, 2, 3]), "[1, 2, 3]")
        self.assertIn("всего 100", main.short(list(range(100))))


class BackupTests(TempDirCase):
    def make_input(self, text="4 7 12 15 20\n"):
        self.input.write_text(text, encoding="utf-8")

    def test_create_backup_structure(self):
        self.make_input()
        path = main.create_backup(self.input, self.backups)
        self.assertTrue(path.name.endswith("_manual.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"created", "checksum", "data"})
        self.assertEqual(payload["data"], {"numbers": [4, 7, 12, 15, 20]})
        self.assertEqual(len(payload["checksum"]), 64)
        info = main.verify_backup(path)
        self.assertEqual((info["count"], info["numbers"]), (5, [4, 7, 12, 15, 20]))

    def test_backup_of_invalid_input_not_created(self):
        self.make_input("4 abc")
        with self.assertRaises(main.ToolError):
            main.create_backup(self.input, self.backups)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_backup_of_missing_input_not_created(self):
        with self.assertRaises(main.ToolError):
            main.create_backup(self.input, self.backups)
        self.assertEqual(main.list_backups(self.backups), [])

    def test_rotation_keeps_ten_newest(self):
        self.make_input()
        created = [main.create_backup(self.input, self.backups) for _ in range(13)]
        remaining = main.list_backups(self.backups)
        self.assertEqual(len(remaining), 10)
        self.assertEqual(remaining, created[3:])

    def test_unique_names_in_same_microsecond(self):
        self.make_input()
        fixed = main.datetime(2026, 10, 22, 12, 0, 0, 1)
        with mock.patch("main.datetime") as fake:
            fake.now.return_value = fixed
            first = main.create_backup(self.input, self.backups)
            second = main.create_backup(self.input, self.backups)
        self.assertNotEqual(first, second)

    def test_restore_latest(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("1 2\n")
        path, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertEqual(numbers, [4, 7, 12, 15, 20])
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])
        self.assertTrue(main.is_pre_restore(safety))
        self.assertEqual(main.verify_backup(safety)["numbers"], [1, 2])

    def test_restore_latest_is_regular_not_pre_restore(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("1 2\n")
        main.restore_backup(self.input, self.backups)
        main.restore_backup(self.input, self.backups)  # повторно — не откатывается на страховочную
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_restore_by_name_and_undo(self):
        self.make_input()
        first = main.create_backup(self.input, self.backups)
        self.make_input("1 2\n")
        _, _, safety = main.restore_backup(self.input, self.backups, first.name)
        main.restore_backup(self.input, self.backups, safety.name)  # отмена восстановления
        self.assertEqual(main.read_array(self.input), [1, 2])

    def test_restore_when_input_missing_has_no_safety_copy(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.input.unlink()
        _, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertIsNone(safety)
        self.assertEqual(numbers, [4, 7, 12, 15, 20])

    def test_restore_over_corrupted_input(self):
        self.make_input()
        main.create_backup(self.input, self.backups)
        self.make_input("garbage")
        _, numbers, safety = main.restore_backup(self.input, self.backups)
        self.assertIsNone(safety)
        self.assertEqual(main.read_array(self.input), numbers)

    def test_restore_no_backups(self):
        self.make_input()
        with self.assertRaises(main.ToolError):
            main.restore_backup(self.input, self.backups)
        self.assertEqual(self.input.read_text(encoding="utf-8"), "4 7 12 15 20\n")

    def test_restore_unknown_name(self):
        self.make_input()
        with self.assertRaises(main.ToolError):
            main.restore_backup(self.input, self.backups, "missing.json")

    def test_tampered_backup_rejected_and_input_unchanged(self):
        self.make_input()
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

    def test_corrupted_backup_variants_rejected(self):
        self.make_input()
        path = main.create_backup(self.input, self.backups)
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

    def test_backup_with_valid_checksum_but_bad_numbers_rejected(self):
        data = {"numbers": [1, "2"]}
        payload = {"created": "x", "checksum": main._checksum(data), "data": data}
        path = self.backups / "20261022_000000_000000_manual.json"
        self.backups.mkdir()
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(main.ToolError):
            main.verify_backup(path)

    def test_rotation_never_deletes_backup_being_restored(self):
        self.make_input()
        oldest = main.create_backup(self.input, self.backups, keep=3)
        for _ in range(2):
            main.create_backup(self.input, self.backups, keep=3)
        main.restore_backup(self.input, self.backups, oldest.name, keep=3)
        self.assertTrue(oldest.exists())

    def test_list_ignores_foreign_files(self):
        self.backups.mkdir()
        (self.backups / ".gitkeep").write_text("", encoding="utf-8")
        (self.backups / "notes.json").write_text("{}", encoding="utf-8")
        self.assertEqual(main.list_backups(self.backups), [])


class CliTests(TempDirCase):
    def test_sum_array(self):
        code, out, _ = run_cli(["sum", "--array", "4", "7", "12", "15", "20", "--k", "4"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Подходящие элементы: [4, 12, 20]", out)
        self.assertIn("Сумма элементов, кратных 4: 36", out)
        self.assertIn("Сумма: 36", self.output.read_text(encoding="utf-8"))

    def test_sum_array_negative_values(self):
        code, out, _ = run_cli(["sum", "--array", "-12", "0", "8", "5", "-4", "--k", "-4"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("кратных -4: -8", out)

    def test_sum_input_file_default_output(self):
        self.input.write_text("4 7 12 15 20\n", encoding="utf-8")
        code, out, _ = run_cli(["sum", "--input", str(self.input), "--k", "4"], self.base)
        self.assertEqual(code, 0)
        self.assertEqual(self.output.read_text(encoding="utf-8"),
                         "Исходный массив: 4 7 12 15 20\nДелитель K: 4\n"
                         "Подходящие элементы: 4 12 20\nСумма: 36\n")

    def test_sum_custom_output(self):
        self.input.write_text("4 7 12 15 20\n", encoding="utf-8")
        custom = self.base / "result.txt"
        code, _, _ = run_cli(["sum", "--input", str(self.input), "--k", "4",
                              "--output", str(custom)], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Сумма: 36", custom.read_text(encoding="utf-8"))
        self.assertFalse(self.output.exists())

    def test_sum_no_matches_prints_net(self):
        code, out, _ = run_cli(["sum", "--array", "1", "3", "--k", "2"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Подходящие элементы: нет", out)
        self.assertIn("Сумма элементов, кратных 2: 0", out)

    def test_sum_interactive_input(self):
        code, out, _ = run_cli(["sum"], self.base, inputs=["4 7 12 15 20", "4"])
        self.assertEqual(code, 0)
        self.assertIn("кратных 4: 36", out)

    def test_sum_k_prompt_only(self):
        code, out, _ = run_cli(["sum", "--array", "4", "8"], self.base, inputs=["4"])
        self.assertEqual(code, 0)
        self.assertIn("кратных 4: 12", out)

    def test_error_cases_return_1_without_traceback(self):
        self.input.write_text("4 7 abc\n", encoding="utf-8")
        cases = [
            ["sum", "--array", "1", "2", "--k", "0"],
            ["sum", "--array", "1", "2", "--k", "abc"],
            ["sum", "--array", "1", "x", "--k", "4"],
            ["sum", "--input", str(self.input), "--k", "4"],
            ["sum", "--input", str(self.base / "none.txt"), "--k", "4"],
            ["backup"],  # input.txt повреждён
        ]
        for argv in cases:
            code, out, err = run_cli(argv, self.base)
            self.assertEqual(code, 1, msg=argv)
            self.assertIn("ОШИБКА", err, msg=argv)
            self.assertNotIn("Traceback", err + out, msg=argv)

    def test_error_does_not_create_output(self):
        run_cli(["sum", "--array", "1", "2", "--k", "0"], self.base)
        self.assertFalse(self.output.exists())

    def test_bad_arguments_exit_2(self):
        for argv in (["sum", "--array", "1", "--input", "f.txt"], ["frobnicate"], ["restore", "a", "b"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    run_cli(argv, self.base)
            self.assertEqual(ctx.exception.code, 2, msg=argv)

    def test_backup_backups_restore_flow(self):
        self.input.write_text("4 7 12 15 20\n", encoding="utf-8")
        code, out, _ = run_cli(["backup"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Резервная копия создана", out)
        self.input.write_text("1 2 3\n", encoding="utf-8")
        code, out, _ = run_cli(["backups"], self.base)
        self.assertIn("OK, элементов: 5", out)
        code, out, _ = run_cli(["restore"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("Состояние до восстановления сохранено", out)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])
        _, out, _ = run_cli(["backups"], self.base)
        self.assertIn("[страховочная]", out)

    def test_restore_named(self):
        self.input.write_text("4 7 12 15 20\n", encoding="utf-8")
        name = main.create_backup(self.input, self.backups).name
        self.input.write_text("1\n", encoding="utf-8")
        code, _, _ = run_cli(["restore", name], self.base)
        self.assertEqual(code, 0)
        self.assertEqual(main.read_array(self.input), [4, 7, 12, 15, 20])

    def test_backups_empty(self):
        code, out, _ = run_cli(["backups"], self.base)
        self.assertEqual((code, out.strip()), (0, "Резервных копий нет."))

    def test_backups_marks_corrupted(self):
        self.input.write_text("1 2\n", encoding="utf-8")
        path = main.create_backup(self.input, self.backups)
        path.write_text("{oops", encoding="utf-8")
        code, out, _ = run_cli(["backups"], self.base)
        self.assertEqual(code, 0)
        self.assertIn("ПОВРЕЖДЕНА", out)

    def test_restore_without_backups_returns_1(self):
        code, _, err = run_cli(["restore"], self.base)
        self.assertEqual(code, 1)
        self.assertIn("Резервных копий нет", err)


class MenuTests(TempDirCase):
    def test_menu_manual_input_and_exit(self):
        code, out, _ = run_cli([], self.base, inputs=["1", "4 7 12 15 20", "4", "0"])
        self.assertEqual(code, 0)
        self.assertIn("кратных 4: 36", out)
        self.assertIn("Работа программы завершена", out)
        self.assertTrue(self.output.exists())

    def test_menu_load_default_file(self):
        self.input.write_text("4 7 12 15 20\n", encoding="utf-8")
        _, out, _ = run_cli([], self.base, inputs=["2", "4", "0"])
        self.assertIn("Загружен массив: [4, 7, 12, 15, 20]", out)
        self.assertIn("кратных 4: 36", out)

    def test_menu_load_other_file_with_quotes(self):
        other = self.base / "other.txt"
        other.write_text("-12 0 8 5 -4\n", encoding="utf-8")
        _, out, _ = run_cli([], self.base, inputs=["3", '"{}"'.format(other), "4", "0"])
        self.assertIn("кратных 4: -8", out)

    def test_menu_save_show_backup_restore(self):
        # 7 — массива ещё нет; 4 — запросит массив и сохранит в input.txt; 7 — покажет; 5 — копия
        _, out, _ = run_cli([], self.base, inputs=["7", "4", "1 2 3", "7", "5", "0"])
        self.assertIn("Массив ещё не загружен", out)
        self.assertIn("Текущий массив: [1, 2, 3]", out)
        self.assertEqual(main.read_array(self.input), [1, 2, 3])
        self.assertEqual(len(main.list_backups(self.backups)), 1)
        self.input.write_text("9\n", encoding="utf-8")
        _, out, _ = run_cli([], self.base, inputs=["6", "", "0"])
        self.assertIn("Данные восстановлены", out)
        self.assertEqual(main.read_array(self.input), [1, 2, 3])

    def test_menu_errors_do_not_stop_program(self):
        code, out, _ = run_cli([], self.base,
                               inputs=["1", "abc", "1", "1 2", "0", "2", "5", "6", "99", "0"])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(out.count("ОШИБКА"), 4)
        self.assertIn("Нет такого пункта", out)

    def test_menu_eof_exits_cleanly(self):
        code, out, _ = run_cli([], self.base, inputs=["1"])  # затем input() исчерпан
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
