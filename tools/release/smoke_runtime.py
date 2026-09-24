"""Fast setup smoke check; deliberately does not start the game or send input."""
from pathlib import Path
import importlib
from importlib import metadata
import sys
import struct


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REQUIRED_FILES = (
    "FH6 Auto.pyw",
    "Forza-Horizon-6-Wheelspin-Macro-main/Main.ahk",
    "Forza-Horizon-6-Wheelspin-Macro-main/Modules/LocalPanel.ahk",
    "Forza-Horizon-6-Wheelspin-Macro-main/Modules/MissionWatchdog.ahk",
    "Forza-Horizon-6-Wheelspin-Macro-main/Runtime/bridge.py",
    "fh6/controller.py",
    "fh6/wheelspin_catalog.py",
    "recognition/current_car_glyph.png",
    "calibration/entry_cinematic.npz",
    "requirements-lock-win-py312.txt",
    "VERSION",
)
IMPORTS = (
    "cv2", "numpy", "mss", "keyboard", "pyautogui", "PIL",
    "matplotlib", "winrt.windows.media.ocr", "windows_capture",
)


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(f"Expected Python 3.12, got {sys.version.split()[0]}")
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("FH6 Auto release runtime requires 64-bit Windows")
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("Required release files are missing: " + ", ".join(missing))
    for module in IMPORTS:
        importlib.import_module(module)
    opencv_distributions = {dist.metadata["Name"].lower()
                            for dist in metadata.distributions()
                            if (dist.metadata.get("Name") or "").lower() in
                            {"opencv-python", "opencv-python-headless"}}
    if opencv_distributions != {"opencv-python"}:
        raise SystemExit("Expected only opencv-python; overlapping OpenCV wheels are unsafe")
    import fh6
    print(f"FH6 Auto runtime smoke passed on Python {sys.version.split()[0]} ({fh6.__file__})")


if __name__ == "__main__":
    main()
