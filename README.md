[![CI](https://github.com/llithium/comictagger/actions/workflows/build.yaml/badge.svg?branch=main&event=push)](https://github.com/llithium/comictagger/actions/workflows/build.yaml)

# ComicTagger

ComicTagger is a Python and PyQt app for writing metadata to digital comics on macOS, Windows, and Linux. This fork of [ComicTagger](https://github.com/comictagger/comictagger) adds Kapowarr-compatible renaming and improvements to archive handling, tagging, and the GUI.

![ComicTagger logo](comictaggerlib/graphics/app.png)

## Features

- Fetch comic information from [Comic Vine](https://comicvine.gamespot.com/).
- Match issues using cover images and tag comics in batches.
- Read and write ComicRack metadata in CBZ archives.
- Read CBR archives, with write support available through external [RAR tools](https://www.rarlab.com/download.htm).
- Use the GUI or CLI for tagging, renaming, and archive operations.

The [upstream wiki](https://github.com/comictagger/comictagger/wiki) covers shared features and plugin setup. Report issues with this fork in [this repository](https://github.com/llithium/comictagger/issues).

## Kapowarr-compatible renaming

This fork can rename tagged files using Kapowarr-compatible filenames:

```text
{series_name} ({year}) Volume {volume_number} Issue {issue_number}
```

In **Preferences → Rename**, enable **Use Kapowarr-compatible naming**, set **Destination Directory** to the folder that should contain the renamed archives, then review the rename preview before applying it. The profile uses embedded ComicInfo metadata, including the `Format` field for TPB, one-shot, hardcover, omnibus, and Volume-As-Issue names; it does not query or alter a Kapowarr database. When available, its year is the persisted `SeriesStartYear` from Comic Vine, with the issue year as a fallback. Auto-tag existing archives once to populate that field. The equivalent CLI option is `--kapowarr-naming --dir /path/to/destination`. It cannot be combined with `--only-move`.

## Installation

### macOS app

Download Apple Silicon macOS builds from the artifacts on successful [CI runs](https://github.com/llithium/comictagger/actions/workflows/build.yaml). Version tags publish builds to this fork's [Releases](https://github.com/llithium/comictagger/releases).

### From source

Use Python 3.10 or newer. On macOS, install ICU and pkg-config first:

```bash
brew install icu4c pkg-config
export PKG_CONFIG_PATH="$(brew --prefix icu4c)/lib/pkgconfig"
```

```bash
git clone https://github.com/llithium/comictagger.git
cd comictagger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[GUI]'
comictagger
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.
Omit `[GUI]` for CLI use, or add optional extras such as `[GUI,CBR,7Z]` for RAR and 7z support.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks, and packaging. The default branch is `main`.

## Credits and license

ComicTagger is distributed under the [Apache License 2.0](LICENSE). See [AUTHORS](AUTHORS) for contributors. Bundled third-party code retains its own licenses.
