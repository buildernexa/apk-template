# NexaBuild overhaul changelog

## Build 6 — 2026-11-08

### UI
- Rebuilt the home dashboard hierarchy around a clear hero action, account/performance summary, quick actions, pipeline, activity, and recent builds.
- Applied a consistent responsive Neobrutalism system with warm neutral surfaces, controlled yellow accent, stronger typography, consistent spacing, and restrained hard shadows.
- Split the monolithic page into `index.html`, `styles.css`, and `app.js` without changing the existing feature set.
- Fixed all duplicate HTML IDs that caused incorrect DOM targeting: pull-to-refresh hint, drawer shade, config export, log download, and date display.
- Updated the service worker cache version and core assets so deployed users receive the new CSS and JavaScript instead of stale cached files.
- Added UI validation and CI workflow.

### Build engine
- Added an explicit Python 3.12 + pinned Pillow setup to prevent the missing `PIL` failure seen in the supplied build recording.
- Replaced the ambiguous `npm ci || npm install` behavior with lockfile-aware deterministic installation.
- Added Android SDK package installation and moved Java setup before SDK manager use.
- Added strict shell mode and safer argument quoting to generated build scripts.
- Added package/version/minSdk validation and clearer early failures.
- Hardened ZIP extraction against path traversal, symbolic links, excessive entry counts, and expanded archives over 500 MB.
- Added regression tests and pinned Python tool requirements.
- Added streaming SHA-256 calculation and clearer missing Android Build Tools errors.
- Bumped template marker to `NEXA_TPL = 6` and updated UI synchronization to include `tools/requirements.txt`.

### Verification
- UI static validation: passed.
- JavaScript syntax (`node --check`): passed.
- Python compilation: passed.
- Generator regression tests: 6 passed.
- Workflow YAML parse: passed.
- Scratch project generation: passed; generated Android XML parsed successfully.
- Full Android Gradle/APK build: not run in this environment because Android SDK/Gradle are not installed here; GitHub Actions remains the required end-to-end build verification.
