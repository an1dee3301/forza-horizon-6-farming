# Desktop workspace

The native Windows panel uses a restrained dark palette, Segoe UI typography,
a consistent content grid, and a persistent action/status area.

- **Mission:** run mode, target, SP reserve, credit reserve, cleanup policy, and display settings.
- **Activity:** recorded reward, car, garage, and farm counters, progress, and verified inventory.
- **Recovery:** logs, error evidence, checkpoint tools, and crash recovery settings.
- **History:** saved run history.
- **Tools:** individual modules, challenge settings, and Discord configuration.
- **Analytics:** measurement tables, CSV exports, and the existing ETA report.

The existing checkpoint, account, purchase, and keep-list behavior is unchanged.
Empty counters use an em dash; inventory has no estimated replacement. A stopped
or completed mission is never automatically started by opening the preview.

## Safe visual preview

Run AutoHotkey v2 with:

```powershell
& 'C:/Program Files/AutoHotkey/v2/AutoHotkey64.exe' ./Forza-Horizon-6-Wheelspin-Macro-main/Main.ahk --preview
```

Preview builds the real panel and labels it **PREVIEW**. It starts no worker,
inspection, polling timer, Discord watcher, or hotkey. Action buttons are inert;
tabs and form previews remain available. Close the window to exit.

For the hidden regression check, substitute `--self-test`. It exercises budget
previews, saved progress, live counters, reserve options, and lifecycle badges
without game input.
