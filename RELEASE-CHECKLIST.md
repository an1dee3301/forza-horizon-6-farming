# Release gate

Run from a clean Windows checkout with 64-bit CPython 3.12 and AutoHotkey v2 installed. A package is publishable only after every item below passes.

1. Confirm `README.md`, `RELEASE-NOTES-vX.Y.Z.md` for the version being published, protected-car policy, and `VERSION` agree. Remove the release notes' draft status only after the final operational and packaging checks pass. Keep the 33 saved-SW/hour result labeled unproven until the native-inventory verifier passes its adjacent-window rule.
2. Run the complete suite: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`.
3. Run `tools\release\smoke_runtime.py`, `.venv\Scripts\python.exe -m pip check`, and `Forza-Horizon-6-Wheelspin-Macro-main\Main.ahk --self-test` with AutoHotkey v2. These checks must not start a game or send input.
4. Review source diff, license, package paths and `git status`; confirm no local runtime, account database, logs, credentials, private screenshots or save data are included.
5. Commit, push `main`, create and push an immutable `vX.Y.Z` tag on that same commit.
6. Build with `python tools\release\build_release.py X.Y.Z`. Re-run the build and compare SHA-256 values to verify deterministic output. Inspect the sidecar, embedded manifest, ZIP CRC, expected entry points and deny-list.
7. Publish with `python tools\release\publish_release.py X.Y.Z dist\FH6-Auto-vX.Y.Z-Windows.zip dist\FH6-Auto-vX.Y.Z-Windows.zip.sha256 dist\FH6-Auto-vX.Y.Z-Windows.zip.manifest.json`. The publisher checks the remote tag and uploaded asset sizes and SHA-256 values before publishing.
8. Download the published archive from GitHub and verify its SHA-256 against the release sidecar; extract it to a clean temporary folder and rerun the smoke check. Do not start the game as part of a release smoke test.

The publisher leaves a partially uploaded release as a draft when a check fails. Fix or remove that draft deliberately; never bypass a mismatch by overwriting an asset in place.
