; Local edition: AutoHotkey panel with the calibrated Python pipeline.
; Original entry point is preserved as UpstreamMain.ahk.txt.
#Requires AutoHotkey v2.0
#SingleInstance Off
#Include Modules\MissionWatchdog.ahk
#Include Modules\LocalPanel.ahk

try {
    global Panel := LocalPanel(A_Args.Length && A_Args[1] = "--self-test")
} catch as err {
    FileAppend(err.Message " at " err.File ":" err.Line "`n", "**")
    ExitApp(1)
}
