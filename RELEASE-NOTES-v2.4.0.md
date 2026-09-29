# FH6 Auto v2.4.0

## Tokyo City Food Delivery

Added Tokyo Delivery as a mode of the existing desktop panel, bridge, and guarded Controller worker. The requested shift count and verified results use a separate durable checkpoint. Map and job navigation, virtual-controller ANNA Auto Drive, a guarded route follower for timed legs without ANNA, observed route progress, bounded parking recovery, and native summary verification are included. Uncertain menu and Auto Drive submissions remain saved and are never replayed automatically.

The pinned Windows runtime now includes `vgamepad==0.1.0`; ViGEmBus is a separate driver prerequisite. `Main.ahk --tokyo-delivery N` prepares a target through the same panel startup inspection. The dashboard shows completed and remaining shifts. See [Tokyo Delivery setup and limits](docs/TOKYO_DELIVERY.md).

Portable tests cover route recognition, checkpoint resume, menu uncertainty, parking bounds, and controller input guards. One live Tokyo shift completed on September 29, 2026: the native summary showed 3/3 deliveries and 4 Shift Stars, and the worker stopped at its saved one-shift target. Other game variants remain unverified. Each delivery requires positive native Shift Stars and advancing Shift Progress; a full shift is counted only at a verified 3/3 summary.

## Existing operation

The v2.3.0 credit reserve, protected Subaru keep list, purchase receipts, final-only Mad Mike cleanup, and saved operation analysis remain intact. The measured saved Wheelspin rate remains 28.105/hour for the final observation interval; 33/hour is unproven.

## Release validation

The full Python suite, runtime smoke, dependency check, AutoHotkey self-test, archive verification, and package review are required before publication.
