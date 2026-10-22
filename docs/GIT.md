# Работа с Git и GitHub

Правила ведения репозитория проекта «Array Sum» (https://github.com/DenisSamofalov/MASIV).

## 1. Получение проекта

```bash
git clone https://github.com/DenisSamofalov/MASIV.git
cd MASIV
```

## 2. Ветки
- `main` — рабочая версия, всегда проходит тесты.
- Для изменений создавайте ветки: `feature/<кратко>` — новая возможность, `fix/<кратко>` — исправление, `docs/<кратко>` — документация.

```bash
git checkout -b feature/csv-export
```

## 3. Коммиты
Сообщение — короткая фраза по существу:

- `Добавлена проверка контрольной суммы копий`
- `Исправлена ротация копий при восстановлении`
- `Обновлён регламент обслуживания`

Один коммит — одно логическое изменение. Перед коммитом запускайте тесты:

```bash
python -m unittest discover -s tests -v
```

## 4. Что не попадает в репозиторий
Согласно `.gitignore`: содержимое `backups/` (кроме `.gitkeep`), файл `output.txt`, кэш Python и виртуальные окружения.

## 5. Обновление проекта

```bash
git add .
git commit -m "Описание изменения"
git push
```

## 6. Теги версий

```bash
git tag -a v1.0.0 -m "Первая версия"
git push origin v1.0.0
```

## 7. Автоматическая проверка
При каждой отправке в `main` и при pull request GitHub Actions (`.github/workflows/tests.yml`) запускает тесты на Python 3.8, 3.10 и 3.12. Результат виден на вкладке **Actions**.
