# Contributing

Thanks for wanting to help! One thing up front: this tool destroys its input on purpose, so being correct
matters way more than new features.

## A few rules

1. Don't break the safety rule. A piece of the ZIP may only be freed after the extracted file and the journal
   entry for it are flushed to disk. If you touch `engine.py`, `journal.py` or `plan.py`, this has to hold.
2. Old runs must stay resumable. Don't change the fingerprint, the entry order or the name logic in `names.py`
   unless there's a migration and a test for it.
3. No new runtime dependencies without talking about it first. Standard library + Win32 API is the whole point.
4. Every setting has to actually do something in the engine and be checked in `settings.py`.

## Getting set up

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests -q
```

The tests need Windows and an NTFS temp folder (your normal `%TEMP%` is fine).

## Pull requests

- One thing per PR, and say why.
- Engine changes need crash/resume tests (see `tests/test_resume.py`, `tests/test_modes.py`). Path or name
  handling needs tests with nasty archives (`tests/test_safety.py`).
- If you say something is faster, show numbers: run `python -m inplace_unpack bench` before and after.
- Texts the user sees go into `i18n.py`, in English and German.
- PEP 8, type hints where they help, comments that explain why.

## Reporting bugs

Open an issue and tell me your Windows version, the file system, what kind of archive it is (size, number of
files, compression) and the exact message. The output of `inplace-unpack-cli status ARCHIVE.zip` helps a lot.

Please don't upload private archives, and remove your own paths and file names from anything you paste.
