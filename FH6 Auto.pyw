"""Double-click entry point. Startup failures remain visible instead of vanishing."""
import traceback

try:
    import os
    import subprocess
    from pathlib import Path
    workspace = Path(__file__).resolve().parent
    ahk = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'AutoHotkey/v2/AutoHotkey64.exe'
    if not ahk.exists():
        raise RuntimeError('AutoHotkey v2 is required for the dashboard.')
    subprocess.Popen([str(ahk), str(workspace/'Forza-Horizon-6-Wheelspin-Macro-main/Main.ahk')],
                     cwd=workspace)
except Exception:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror('FH6 Auto could not start',
                        'Run Setup FH6 Auto.cmd once, then reopen the app.\n\n'+traceback.format_exc())
    root.destroy()
