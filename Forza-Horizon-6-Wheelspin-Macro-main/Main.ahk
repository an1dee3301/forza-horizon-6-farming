; Local edition: AutoHotkey panel with the calibrated Python pipeline.
; Original entry point is preserved as UpstreamMain.ahk.txt.
#Requires AutoHotkey v2.0
#SingleInstance Off
#Include Modules\MissionWatchdog.ahk
#Include Modules\LocalPanel.ahk

try {
    testMode := A_Args.Length && A_Args[1] = "--self-test"
    trial := A_Args.Length >= 2 && A_Args[1] = "--wheelspin-lab-trial" ? Integer(A_Args[2]) : 0
    global Panel := LocalPanel(testMode, trial)
} catch as err {
    FileAppend(err.Message " at " err.File ":" err.Line "`n", "**")
    ExitApp(1)
}
