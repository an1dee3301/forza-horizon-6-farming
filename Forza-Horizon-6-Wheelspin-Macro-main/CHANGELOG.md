### Changelog

All notable changes to this project will be documented in this file. Dates are displayed in UTC.

#### [v1.8.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.7.0...v1.8.0)

feat: release v1.8.0 - core automation, window management, and miniGUI overhaul

This release introduces significant stability and feature enhancements across the entire macro framework, focusing on background execution resilience, UI modularity, and precision targeting.

New Features:
- Advanced Game Lock & Background Rendering: Implemented continuous native activation message spoofing to bypass auto-pause behaviors when minimized.
- Custom Resolution Support: Added adaptive floating-point coordinate scaling for multi-target layout scaling across resolutions.
- Special K Mod Integration: Automated deployment, profile injection, and fallback registry checks for reliable borderless background inputs.
- Draggable Spin Hub: Extracted wheelspin parameters into an independent, theme-aware, draggable sub-panel window.
- Viewport Manipulation Suite: Added quick-access toggles for window states (Always-On-Top, fullscreen toggles, and Alt+LButton canvas dragging).
- Path Discovery Matrix: Implemented heuristic registry, process, and multi-drive scanning to auto-locate installations.
- Diagnostics: Added a toggleable Visual Bounding Zone overlay to frame color/OCR scanning boundaries in real-time.
- Centralized Config Sync: Deployed automated .ini file reading/writing to ensure session consistency.

Bug Fixes:
- Bound background macro loops strictly to unique window handles (HWND) instead of title strings to ensure focus resilience.
- Added automated administrative token validation and self-elevation on startup.
- Implemented an OCR car verification safety check to prevent accidental perk deployment on incorrect vehicles.
- Resolved scoreboard synchronization lockups and menu transition delays during race completion sequences.
- Added a safe purchase increment buffer offset to counter edge-case visual recognition skips.
- Excised premature integer rounding from relative coordinate mapping to eliminate targeting drift.

Refactoring & Performance:
- Comprehensive MiniGUI Overhaul: Added state-driven dynamic icons, embedded action toggles, and quick-access environment controls (reset/reload/abort).
- Interactive Notifications: Removed overlay barriers to allow instant dismissal via mouse click and extended default display timers to 8 seconds.
- OCR Processing: Replaced exact string matching with a fuzzy case-insensitive string edit-distance algorithm to tolerate minor OCR misreads.
- Architecture: Migrated flat array listings into typed map dictionaries (EventLabData, CarData) and deployed pre-execution boundary health checks before tasks trigger.

#### [v1.7.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.6.2...v1.7.0)

> 21 June 2026

- feat: v1.7.0 release - cyber noir visual overhaul and window-relative automation optimizations [`59dbc5a`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/59dbc5a1fbff1d78e201ab9d9e99afd880df2a27)
- Replace old screenshots with updated images [`741cb6a`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/741cb6ad22b96e6f0db573d8036d0f7af8e32a2a)

#### [v1.6.2](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.6.1...v1.6.2)

> 19 June 2026

- feat: multiple monitor support [`#5`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/pull/5)
- fix: update multipliers, refine UI labels, and adjust skill point scanning parameters for improved functionality [`69458ad`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/69458ad6330f64d9e174e691627807a430fc3eba)
- feat: add multiple monitor support [`f589e5e`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/f589e5e78a0addbc5b3f49266c230ddf551c4045)
- Update README with mode instructions [`c83786c`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/c83786c5ee7a4982dda0d2d7e60c42cb1cfad0f7)

#### [v1.6.1](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.6.0...v1.6.1)

> 18 June 2026

- Revise images and framerate recommendations in README [`e4657a6`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/e4657a6e978a4f3db95a1c8528e553d2b1cd66e3)
- fix: update version to v1.6.1 and adjust UI element positions for better compatibility with higher dpi scaling [`1b5e674`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/1b5e674a56ac7913a1efc68779574e181717f060)

#### [v1.6.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.5.0...v1.6.0)

> 18 June 2026

- feat: release v1.6.0 - UI overhaul [`39789ff`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/39789ff50c44d9cfdadb9c2c5e60e422eadbc95a)
- Revise images and framerate recommendations in README [`82d1318`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/82d1318f9c2be8078085a30332e6951f784f2513)
- Update README installation instructions and TOC [`d29287e`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/d29287e4d29d1a3fae64d2d4f7033376326c723c)

#### [v1.5.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.4.0...v1.5.0)

> 17 June 2026

- feat: release v1.4.0 - OCR integration, Special K background play, and Ammagedon optimization [`5f690f4`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/5f690f4cf9cd8d09de54383905efc30d4d3f2a8e)
- feat: release v1.5.0 - wheelspin automation, UI overhaul, and timing fixes [`ff22deb`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/ff22deb5c3f0051cb07e645f211b057500eac0d5)
- Replace old screenshots with new ones [`278b190`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/278b190b3b0dc098bd678166027db0037a2fd1f7)

#### [v1.4.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.3.0...v1.4.0)

> 15 June 2026

- feat: release v1.4.0 - OCR integration, Special K background play, and Ammagedon optimization [`53e7989`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/53e79891495481df020ed838bb5d17b966694950)

#### [v1.3.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.2.2...v1.3.0)

> 13 June 2026

- feat: update to v1.3.0 with dynamic tracks, loop controls, and delay scaling [`1abda0f`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/1abda0f5402926875d1abd385c17eed9485ebdae)
- fix(gui): update icons and text for better clarity in macro interface, remove requirement for EventLab track loading pixel detection. [`758fc82`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/758fc82906307a27abbf59be0064ecd7914835aa)

#### [v1.2.2](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.2.0...v1.2.2)

> 12 June 2026

- feat(macro): upgrade to v1.2.2 - hardware scan codes, input locking, and dynamic countdowns [`90d87e6`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/90d87e6eb94ef44c055985c1c05b3709be04dd28)
- Refactor README.md to improve clarity on screen settings and HUD calibration; consolidate important warnings regarding screen coverage and HUD settings for optimal macro performance. [`095e814`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/095e8145aae1cd16e52c03f1bad51984f9603d8f)
- chore: update version to v1.2.0 and enhance README with HUD settings and warnings [`edb2608`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/edb26086cc1b1019a29edf95a6cc92dc9068c5b2)

#### [v1.2.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/1.1.0...v1.2.0)

> 11 June 2026

- feat: upgrade macro to v1.2.0 with dynamic pixel validation [`8004c43`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/8004c43320f9d04f5fbe0ae9148afec0531b8c9a)
- Revise README with new screenshots and formatting [`7b2f55a`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/7b2f55a888e2c89183fcc05744889027b9c401c2)
- Update vehicle strategy descriptions in README.md for clarity and accuracy [`02b59fc`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/02b59fcc5fa0885ce09485a482d1cb0cddf47e62)

#### [1.1.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.1.0...1.1.0)

> 10 June 2026

#### [v1.1.0](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/compare/v1.0.1...v1.1.0)

> 11 June 2026

- feat: upgrade macro to v1.2.0 with dynamic pixel validation [`8004c43`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/8004c43320f9d04f5fbe0ae9148afec0531b8c9a)
- Update README.md: Enhance automation loop description, clarify skill point results, and add reward vehicle options with strategies [`24d5efe`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/24d5efe875363335abe4de7bfe1e162a03f17aba)
- Revise README with new screenshots and formatting [`7b2f55a`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/7b2f55a888e2c89183fcc05744889027b9c401c2)

#### v1.0.1

> 9 June 2026

- Add files via upload [`f438afd`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/f438afd2bb57386263b02f0c8bff1675f9c057f2)
- Refactor time calculations and update UI labels [`6ac2db6`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/6ac2db65b520e63e24cbf91e937b88f7b4249d65)
- Revise README for FH6 Wheelspin Macro updates [`cb29a78`](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/commit/cb29a78fffec0a8ecc41c9a0f6251b11a657fa33)
