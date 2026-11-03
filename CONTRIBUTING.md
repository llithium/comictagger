# Contributing

Report bugs and propose changes in [Issues](https://github.com/llithium/comictagger/issues).
Open [pull requests](https://github.com/llithium/comictagger/pulls) against `main`
with a concise description and focused tests.

## Supported setup

ComicTagger requires Python 3.10 or newer. The macOS build and CI workflow use
native Apple Silicon on `macos-15`. CI checks Python 3.10 and 3.14 and builds
the macOS application with Python 3.14. Linux and Windows remain supported by
the application and package metadata.

Create and activate a virtual environment, then install tox:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip tox
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.
The GUI, CBR, and 7z test environments install their optional dependencies
through tox. The ICU checks also require a working PyICU installation. On
macOS, configure Homebrew's ICU before running tox:

```bash
brew install icu4c pkg-config
export PKG_CONFIG_PATH="$(brew --prefix icu4c)/lib/pkgconfig"
```

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
QT_QPA_PLATFORM=offscreen python -m tox p
```

This runs the non-mutating formatting checks, flake8, and the enforced mypy
scope (`comicapi`, `comictaggerlib`, and `comictalker`), followed by the base,
GUI, 7z, CBR, and all-extra pytest environments. To run only the base tests,
use `python -m tox -e none`.

The pre-commit lint hook runs the same `tox -e lint` environment as CI, including
its flake8 plugins and mypy scope. Run pre-commit from the activated environment
where tox is installed.

## Packaging

Build packages and application artifacts locally with:

```bash
python -m tox r -m build
```

This command validates formatting and types before building, without applying
formatting changes. It may require platform-specific packaging tools and
optional dependencies.

CI runs on pushes to `main`, pull requests targeting `main`, version tags, and
manual dispatch. Both Python versions must pass the full validation matrix
before a version tag can publish a GitHub release. The release includes the
wheel, source archive, and Apple Silicon DMG. Tags use `1.6.0` for stable releases
or `1.6.0-beta.1` for prereleases. The workflow does not publish to PyPI.
