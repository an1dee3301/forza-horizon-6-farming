from pathlib import PurePosixPath

from tools.release.build_release import is_allowed


def test_release_archive_excludes_local_account_runtime_and_secrets():
    for name in ("runs/session.sqlite", "purchases/pending.json", "LocalState/account.db",
                 "fh6/discord_webhook.dpapi", ".env", ".env.local",
                 "cache/private.mp4", "secrets/deploy.pem"):
        assert not is_allowed(PurePosixPath(name))


def test_release_archive_keeps_required_runtime_and_calibration_assets():
    for name in ("fh6/controller.py", "profiles/default.json",
                 "calibration/entry_cinematic.npz",
                 "recognition/current_car_glyph.png",
                 "Forza-Horizon-6-Wheelspin-Macro-main/Runtime/bridge.py"):
        assert is_allowed(PurePosixPath(name))
