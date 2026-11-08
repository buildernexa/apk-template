# NexaBuild Android Build Template

This repository is the GitHub Actions build engine used by NexaBuild.

## Project structure

- `.github/workflows/build.yml` — reproducible CI setup, SDK installation, tests, build, artifact upload, release, and temporary ZIP cleanup.
- `tools/generate.py` — source detection, safe ZIP extraction, Android project generation, metadata patching, signing, and artifact collection.
- `tools/requirements.txt` — pinned Python image tooling used when a custom launcher icon is supplied.
- `tests/test_generate.py` — regression tests for configuration validation, build-script generation, npm lockfile selection, and ZIP traversal protection.

## Build environment

- Java 17
- Python 3.12
- Node.js 20 when the detected source requires Node
- Android platform 34 and Build Tools 34.0.0
- Gradle 8.7
- Flutter stable when the detected source is Flutter

## Local tests

```bash
python -m pip install -r tools/requirements.txt
python -m unittest discover -s tests -v
```

## Supported sources

- Scratch-generated WebView wrapper
- Web project with `index.html` or `package.json`
- Capacitor
- React Native / Expo
- Flutter
- Existing Gradle Android project

The workflow validates the incoming build configuration before generating or compiling the Android project. ZIP uploads are checked for traversal paths, symbolic links, entry-count abuse, and excessive expanded size.
