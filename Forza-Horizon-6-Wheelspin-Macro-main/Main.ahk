; Local edition: AutoHotkey panel with the calibrated Python pipeline.
; Original entry point is preserved as UpstreamMain.ahk.txt.
#Requires AutoHotkey v2.0
#SingleInstance Off
#Include Modules\MissionWatchdog.ahk
#Include Modules\LocalPanel.ahk

try {
    testMode := A_Args.Length && A_Args[1] = "--self-test"
    trial := A_Args.Length >= 2 && A_Args[1] = "--wheelspin-lab-trial" ? Integer(A_Args[2]) : 0
    tokyoRequested := A_Args.Length && A_Args[1] = "--tokyo-delivery"
    tokyoTarget := tokyoRequested && A_Args.Length >= 2 ? Integer(A_Args[2]) : 0
    if tokyoRequested && (tokyoTarget < 1 || tokyoTarget > 10000)
        throw Error("Choose 1–10,000 Tokyo Delivery shifts")
    previewMode := A_Args.Length && A_Args[1] = "--preview"
    global Panel := LocalPanel(testMode, trial, previewMode, tokyoTarget)
} catch as err {
    FileAppend(err.Message " at " err.File ":" err.Line "`n", "**")
    ExitApp(1)
}
