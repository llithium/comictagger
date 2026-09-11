# Contributing

Questions and proposals are welcome in the [Discussions](https://github.com/comictagger/comictagger/discussions/categories/general).
For changes, please open a [pull request](https://github.com/comictagger/comictagger/pulls) with a concise description and focused tests.

## Supported setup

ComicTagger requires Python 3.10 or newer. The macOS build and CI workflow use
native Apple Silicon on `macos-14`; Linux and Windows remain supported by the
application and package metadata.

Create and activate a virtual environment, then install tox:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip tox
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.
The GUI, CBR, and 7z test environments install their optional dependencies
through tox. The ICU checks also require a working PyICU installation; on
macOS, install ICU and pkg-config with Homebrew if needed.

## Checks and tests

Formatting has two deliberately separate modes:

```bash
# Apply formatting and regenerate the checked-in settings namespace.
python -m tox -e format

# Validate formatting and generated sources without editing the checkout.
python -m tox -e format-check
```

Run the full local validation matrix before submitting a change:

```bash
python -m tox p
```

This runs the non-mutating formatting checks, flake8, and the enforced mypy
scope (`comicapi`, `comictaggerlib`, and `comictalker`), followed by the base,
GUI, 7z, CBR, and all-extra pytest environments. To run only the base tests,
use `python -m tox -e none`.

## Packaging

Build packages and application artifacts locally with:

```bash
python -m tox r -m build
```

This command performs the required checks before building. It may require
platform-specific packaging tools and optional dependencies. Release automation
runs `python -m tox p` separately before publishing artifacts.
