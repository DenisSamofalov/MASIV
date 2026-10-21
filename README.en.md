# Array Sum — sum of array elements divisible by K

[🇷🇺 Русский](README.md) · 🇬🇧 English

A Python console program that calculates the sum of all integer-array elements divisible by a number `K` without a remainder. Data can be entered and output through the console and through files. It also backs up and restores the input array.

## About

- Array input: console (menu or arguments) or a text file.
- Result output: console and the `output.txt` file.
- Negative numbers, zero and a negative `K` are supported.
- Backups of the input file with a SHA-256 checksum (the 10 most recent are kept).
- Python standard library only.

Example: array `4 7 12 15 20`, `K = 4` → selected elements `4, 12, 20`, sum `36`.

## Installation

**Requirements:** Python 3.8+ and Git.

1. Check Python:
   ```bash
   python --version
   ```
   On Linux/macOS you may need `python3`.
2. Get the project:
   ```bash
   git clone https://github.com/wwwteams/calculator.git
   cd calculator
   ```
   Or click **Code → Download ZIP** on the repository page and unpack it.
3. Run:
   ```bash
   python main.py
   ```

## Usage

### 1. Interactive menu
```bash
python main.py
```
| Item | Action |
|---|---|
| 1 | Enter an array in the console and calculate the sum |
| 2 | Load the array from `input.txt` and calculate the sum |
| 3 | Load the array from another file and calculate the sum |
| 4 | Save the current array to `input.txt` |
| 5 | Create a backup of `input.txt` |
| 6 | Restore `input.txt` from a backup |
| 7 | Show the current array |
| 0 | Exit |

### 2. Command line

| Command | Description |
|---|---|
| `python main.py sum --array 4 7 12 15 20 --k 4` | Sum for an array given as arguments |
| `python main.py sum --input input.txt --k 4` | Array from a file, result to `output.txt` |
| `python main.py sum --input input.txt --k 4 --output result.txt` | Result to your own file |
| `python main.py backup` | Create a backup of `input.txt` |
| `python main.py backups` | List backups |
| `python main.py restore` | Restore from the latest backup |
| `python main.py restore <file_name>` | Restore from a chosen backup |

Example (the program's messages are in Russian: "Подходящие элементы" = selected elements, "Сумма элементов, кратных 4" = sum of elements divisible by 4):
```
$ python main.py sum --array 4 7 12 15 20 --k 4
Подходящие элементы: [4, 12, 20]
Сумма элементов, кратных 4: 36
```

### 3. File formats
- `input.txt` — integers separated by spaces or line breaks: `4 7 12 15 20`.
- `output.txt` — the source array, `K`, selected elements and the sum.
- `backups/*.json` — backups (do not edit by hand).

### 4. Errors
`K` cannot be zero, and the array cannot be empty or contain non-integer values. On an error the program prints `ОШИБКА: …` ("ERROR: …") and leaves your data unchanged.

### 5. Backup and restore
A backup is created only from a valid `input.txt`. On restore the checksum is verified; before `input.txt` is replaced, its current version is saved as `*_pre-restore.json`. The 10 most recent backups are kept.

## Tests
```bash
python -m unittest discover -s tests -v
```
Manual test cases: [docs/TEST_CASES.md](docs/TEST_CASES.md) (in Russian).

## Project structure
```
.
├── main.py               # the program
├── input.txt             # sample input file
├── tests/test_main.py    # automated tests
├── docs/
│   ├── TZ.md             # technical specification (RU)
│   ├── MAINTENANCE.md    # maintenance regulations (RU)
│   └── TEST_CASES.md     # test cases (RU)
├── README.md             # user guide (RU)
└── README.en.md          # user guide (EN)
```

## Author
Samofalov D.A
