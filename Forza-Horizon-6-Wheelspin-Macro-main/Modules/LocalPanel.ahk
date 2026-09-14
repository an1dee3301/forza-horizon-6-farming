; Local control panel. All game recognition and inputs live in the Python worker.
; Closing this panel requests a stop; the worker also watches its parent's PID.
class LocalPanel {
    __New(testMode := false) {
        this.pid := 0
        this.watchdog := MissionWatchdog()
        this.channel := ""
        this.pending := false
        this.goalPending := false
        this.editingProfile := false
        this.shareCode := "155439962"
        this.challengeSeconds := 900
        this.closing := false
        this.testMode := testMode
        this.errorImage := ""
        this.mutex := 0
        this.workspace := A_ScriptDir "\.."
        this.python := this.workspace "\.venv\Scripts\pythonw.exe"
        this.bridge := A_ScriptDir "\Runtime\bridge.py"
        if !testMode {
            this.mutex := DllCall("CreateMutexW", "Ptr", 0, "Int", 0, "Str", "Local\FH6AutoDashboard", "Ptr")
            if !this.mutex || A_LastError = 183 {
                MsgBox("An FH6 Auto panel is already open. Use that panel or close it first.", "FH6 Auto")
                ExitApp()
            }
        }
        this.Build()
        this.timer := ObjBindMethod(this, "Poll")
        if testMode {
            this.SelfTest()
            return
        }
        Hotkey("F6", ObjBindMethod(this, "Start"))
        Hotkey("F7", ObjBindMethod(this, "Stop"))
        this.gui.OnEvent("Close", ObjBindMethod(this, "Close"))
        OnExit(ObjBindMethod(this, "Exiting"))
        SetTimer(this.timer, 250)
        this.Launch("inspect")
        this.DiscordReports("--watch")
    }

    Build() {
        this.gui := Gui("-MaximizeBox", "FH6 // MISSION CONTROL")
        this.gui.BackColor := "0B1018"
        this.gui.SetFont("s21 cE6EDF3", "Consolas")
        this.gui.AddText("x24 y18 w700 h42", "FH6 // MISSION CONTROL")
        this.gui.SetFont("s10 c8795A7", "Consolas")
        this.gui.AddText("x26 y65 w700 h30", "1974 Mazda #123 Mad Mike 808   •   21 SP / car   •   95,000 CR / car")
        this.tabs := this.gui.AddTab3("x24 y108 w700 h435", ["MISSION", "LIVE", "RECOVERY", "HISTORY", "MODULES", "ANALYTICS"])
        this.tabs.UseTab(1)
        this.gui.SetFont("s10 cE6EDF3")
        this.gui.AddText("x46 y162 w160", "Run mode")
        this.mode := this.gui.AddDropDownList("x220 y156 w470 Choose1", ["Earn saved Super Wheelspins", "Full pipeline", "Buy only", "Mastery only", "Recognition only", "Farm SP only", "Return to collection", "Check farm setup", "Open game"])
        this.mode.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.quantityLabel := this.gui.AddText("x46 y217 w160", "Super Wheelspins")
        this.points := this.gui.AddEdit("x220 y210 w180 h32 Background182331 cFFFFFF Number", "10")
        this.gui.AddText("x46 y268 w160", "SP to keep")
        this.reserve := this.gui.AddEdit("x220 y260 w180 h32 Background182331 cFFFFFF Number", "0")
        this.points.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.reserve.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.gui.SetFont("s13 c00C087", "Consolas")
        this.plan := this.gui.AddText("x46 y315 w650 h66", "Enter your current skill points.")
        this.gui.SetFont("s10 c8795A7", "Consolas")
        this.gui.AddText("x46 y389 w650 h55", "Mega V6 → Home → Journal → Buy → My Cars → Recently Added`n→ verified mastery → repeat. Earned Super Wheelspins stay saved.")
        this.gui.AddText("x46 y468 w130", "Game monitor")
        this.monitor := this.gui.AddEdit("x185 y461 w75 h30 Number Background182331 cFFFFFF", "1")
        this.gui.AddText("x322 y468 w150", "Screen timeout (sec)")
        this.timeout := this.gui.AddEdit("x489 y461 w75 h30 Number Background182331 cFFFFFF", "30")
        this.tabs.UseTab(2)
        this.gui.SetFont("s12 cE6EDF3")
        this.stats := this.gui.AddText("x46 y164 w650 h196", "No run started.")
        this.bar := this.gui.AddProgress("x46 y374 w650 h12 c00C087 Background182331 Range0-100", 0)
        this.gui.SetFont("s11 c00C087")
        this.stage := this.gui.AddText("x46 y410 w650 h48 +0x80", "Waiting")
        this.gui.SetFont("s9 c8795A7")
        this.gui.AddText("x46 y477 w650 h42", "SP is read from the game; ≤ marks an unfinished tree.`nCloud sync blocks every input and restart until verified.")
        this.tabs.UseTab(3)
        this.gui.SetFont("s10 cE6EDF3")
        this.AddButton("x46 y165 w290 h38", "Open logs", (*) => Run(this.Q(this.workspace "\runs")))
        this.AddButton("x358 y165 w290 h38", "Error screenshot", ObjBindMethod(this, "OpenError"))
        this.endButton := this.AddButton("x46 y229 w290 h38", "End saved session…", ObjBindMethod(this, "EndSession"))
        this.resolveButton := this.AddButton("x358 y229 w290 h38", "Resolve uncertain purchase…", ObjBindMethod(this, "Resolve"))
        this.gui.AddText("x46 y281 w650 h27", "SYNC // Automatic completion check. No timed bypass.")
        this.gui.SetFont("s10 c8795A7")
        this.gui.AddText("x46 y318 w650 h133", "Resume keeps the original car target and the current stage.`nLeave the selected car unchanged after a stop.`n`nAn uncertain purchase blocks buying until its receipt is verified or you record the outcome.`n`nPurchased cars remain in the garage. An owned Super Wheelspin node completes the reward check.")
        this.steamBackup := this.gui.AddCheckbox("x46 y464 w455 h25 Checked cE6EDF3", "Open through Steam and restart after crashes")
        this.gui.AddText("x46 y501 w290 h22", "Crash limit (0 = unlimited, up to 10)")
        this.maxRestarts := this.gui.AddEdit("x358 y495 w75 h29 Number Background182331 cFFFFFF", "0")
        this.gamePriority := this.gui.AddCheckbox("x462 y497 w220 h25 Checked cE6EDF3", "Prioritize game focus")
        this.tabs.UseTab(4)
        this.gui.SetFont("s10 cE6EDF3")
        this.history := this.gui.AddEdit("x46 y166 w650 h332 ReadOnly Multi Background111A25 cE6EDF3", "Loading history…")
        this.tabs.UseTab(5)
        this.gui.SetFont("s10 cE6EDF3")
        this.gui.AddText("x46 y158 w650 h50", "Mega Farm V6  •  155439962  •  about 15 minutes per run`nUse a fully upgraded 1998 Subaru 22B with completed mastery.")
        this.AddButton("x46 y220 w290 h36", "Check Mega V6 settings", (*) => this.SelectModule("Check farm setup"))
        this.AddButton("x358 y220 w290 h36", "Farm SP only", (*) => this.SelectModule("Farm SP only"))
        this.AddButton("x46 y270 w290 h36", "Buy cars from current SP", (*) => this.SelectModule("Buy only"))
        this.AddButton("x358 y270 w290 h36", "Claim current mastery tree", (*) => this.SelectModule("Mastery only"))
        this.AddButton("x46 y320 w290 h36", "Return to Car Collection", (*) => this.SelectModule("Return to collection"))
        this.AddButton("x358 y320 w290 h36", "Recognition without inputs", (*) => this.SelectModule("Recognition only"))
        this.AddButton("x46 y370 w290 h36", "Challenge profile", ObjBindMethod(this, "EditProfile"))
        this.AddButton("x358 y370 w290 h36", "Module guide / repo features", (*) => Run(this.Q(this.workspace "\MODULES.md")))
        this.gui.SetFont("s9 c8795A7")
        this.AddButton("x46 y417 w290 h36", "Open game through Steam", (*) => this.SelectModule("Open game"))
        this.AddButton("x358 y417 w290 h36", "Discord reports", (*) => this.DiscordReports("--settings"))
        this.gui.AddText("x46 y469 w650 h52", "Mega V6: automatic steering/braking OFF; Skills HUD OFF.`nThe program checks SP after farming. The advertised yield is not guaranteed.`nChallenge navigation is being validated; an unrecognized screen stops the run.")
        this.tabs.UseTab(6)
        this.gui.SetFont("s10 cE6EDF3", "Consolas")
        this.analyticsHeader := this.gui.AddText("x46 y158 w650 h78", "Collecting mission measurements…")
        this.analyticsChoice := this.gui.AddDropDownList("x46 y244 w300 Choose5", ["Car cycles", "Farm runs", "Batch SP refills", "Stage P50 / P90 / P99", "Throughput / mission", "Failure causes / cost", "Transition latency", "Time attribution"])
        this.analyticsChoice.OnEvent("Change", ObjBindMethod(this, "RefreshAnalytics"))
        this.analyticsGrid := this.gui.AddListView("x46 y283 w650 h174 Background111A25 cE6EDF3 Grid", ["Step", "Mean s", "Median s", "Min s", "Max s", "Samples", ""])
        this.analyticsData := Map()
        this.analyticsBasis := this.gui.AddText("x46 y461 w650 h20", "Current-run tables start empty.")
        this.AddButton("x46 y483 w290 h32", "Export analytics CSV", (*) => Run(this.Q(this.python) " -m fh6.analytics --export", this.workspace, "Hide"))
        this.AddButton("x358 y483 w290 h32", "Open exported files", (*) => this.OpenAnalyticsExports())
        this.tabs.UseTab()
        this.gui.SetFont("s11 c0B1018", "Consolas")
        this.startButton := this.AddButton("x24 y562 w458 h43", "Start / Resume   F6", ObjBindMethod(this, "Start"))
        this.stopButton := this.AddButton("x498 y562 w226 h43", "Stop   F7", ObjBindMethod(this, "Stop"))
        this.gui.SetFont("s10 cE6EDF3", "Consolas")
        this.status := this.gui.AddText("x26 y622 w698 h57", "Loading saved progress…")
        this.gui.SetFont("s9 c8795A7")
        this.gui.AddText("x26 y687 w700 h22", "1920 x 1080 / EN   |   SYNC FIRST   |   F6 RUN   F7 STOP")
        corners := Buffer(4, 0)
        NumPut("Int", 1, corners)
        try DllCall("dwmapi\DwmSetWindowAttribute", "Ptr", this.gui.Hwnd, "UInt", 33, "Ptr", corners, "UInt", 4)
        this.gui.Show("w748 h726" (this.testMode ? " Hide" : ""))
    }

    AddButton(options, text, callback) {
        button := this.gui.AddButton(options " +0x8000", text)
        button.OnEvent("Click", callback)
        return button
    }

    Q(value) => Chr(34) value Chr(34)

    DiscordReports(option) {
        try Run(this.Q(this.python) " -m fh6.discord_reports " option, this.workspace, "Hide")
    }

    RefreshPlan(*) {
        goal := this.mode.Text = "Earn saved Super Wheelspins"
        this.quantityLabel.Value := goal ? "Super Wheelspins" : "Current SP"
        if goal {
            if this.goalPending {
                this.plan.Value := "Resume the saved wheelspin target from its last verified step."
                return
            }
            if !RegExMatch(this.points.Value, "^\d+$") || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000 {
                this.plan.Value := "Enter 1–10,000 Super Wheelspins to earn and save."
                return
            }
            count := Integer(this.points.Value)
            this.plan.Value := count " Super Wheelspins  •  " count * 21 " SP total`nRefill to 999 SP → up to 47 cars → repeat."
            if this.pending
                this.plan.Value := count " new Super Wheelspins. Finish the saved car first.`nThen farm and convert as needed; no Designs detour."
            return
        }
        if this.mode.Text = "Open game" {
            this.plan.Value := "Open Steam → Start Game → Continue. The saved target is not started."
            return
        }
        if this.mode.Text = "Recognition only" {
            this.plan.Value := "Check recognized screens without sending game inputs."
            return
        }
        if this.pending {
            this.plan.Value := "Resume the saved run; its target and SP budget stay fixed."
            return
        }
        if this.mode.Text = "Mastery only" {
            this.plan.Value := "One mastery tree. Open the Mad Mike mastery screen first."
            return
        }
        if this.mode.Text = "Farm SP only" || this.mode.Text = "Check farm setup" || this.mode.Text = "Return to collection" {
            this.plan.Value := this.mode.Text = "Farm SP only" ? "Run Mega V6 once, verify the SP increase, then return home." : this.mode.Text = "Check farm setup" ? "Verify automatic assists are off and Skills HUD is off." : "Navigate back to Car Collection without buying a car."
            return
        }
        if !RegExMatch(this.points.Value, "^\d+$") || !RegExMatch(this.reserve.Value, "^\d+$") {
            this.plan.Value := "Enter whole numbers for Current SP and SP to keep."
            return
        }
        cars := Floor(Max(0, Integer(this.points.Value) - Integer(this.reserve.Value)) / 21)
        left := Integer(this.points.Value) - cars * 21
        credits := RegExReplace(String(cars * 95000), "(\d)(?=(\d{3})+(?!\d))", "$1,")
        this.plan.Value := cars " cars  •  " left " SP left  •  " credits " CR needed"
        if this.mode.Text = "Buy only"
            this.plan.Value := cars " cars  •  SP unchanged  •  " credits " CR needed"
        if !cars
            this.plan.Value .= "`nAt least 21 spendable SP is required to start."
    }

    Start(*) {
        if this.pid || this.closing || this.editingProfile
            return
        if this.mode.Text = "Earn saved Super Wheelspins" {
            if !RegExMatch(this.points.Value, "^\d+$") || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000
                || !RegExMatch(this.reserve.Value, "^\d+$") || Integer(this.reserve.Value) > 978 {
                this.status.Value := "Choose 1–10,000 Super Wheelspins and an SP reserve of 0–978."
                return
            }
        }
        if !this.pending && (this.mode.Text = "Full pipeline" || this.mode.Text = "Buy only") {
            if !RegExMatch(this.points.Value, "^\d+$") || !RegExMatch(this.reserve.Value, "^\d+$") {
                this.status.Value := "Enter whole numbers for Current SP and SP to keep."
                return
            }
            if Integer(this.points.Value) - Integer(this.reserve.Value) < 21 {
                this.status.Value := "At least 21 spendable SP is required. No run started."
                return
            }
        }
        if !RegExMatch(this.monitor.Value, "^\d+$") || Integer(this.monitor.Value) < 1
            || !RegExMatch(this.timeout.Value, "^\d+$") || Integer(this.timeout.Value) < 2 || Integer(this.timeout.Value) > 120 {
            this.status.Value := "Use monitor 1 or higher and timeout 2–120 seconds."
            return
        }
        if !RegExMatch(this.maxRestarts.Value, "^\d+$") || Integer(this.maxRestarts.Value) > 10 {
            this.status.Value := "Choose 0–10 crash restarts per run."
            return
        }
        if this.mode.Text = "Earn saved Super Wheelspins"
            this.watchdog.Arm()
        else
            this.watchdog.Stop()
        if this.Launch("run") {
            this.tabs.Choose(2)
            this.status.Value := "Starting in five seconds. Switch to the game."
            this.gui.Minimize()
        }
    }

    ConfirmSync(*) {
        if !FileExist(this.workspace "\runs\cloud_sync.json") {
            this.status.Value := "There is no pending cloud-sync verification."
            return
        }
        if MsgBox("Have you verified that Xbox/game cloud synchronization fully completed?`nA closed dialog or playable menu alone does not prove this.", "Confirm completed sync", "YesNo Icon?") != "Yes"
            return
        channel := A_ScriptDir "\LocalState\sync_confirmation_" A_Now "_" A_TickCount
        DirCreate(channel)
        Run(this.Q(this.python) " " this.Q(this.bridge) " --channel " this.Q(channel) " --action confirm-sync", this.workspace, "Hide")
        this.status.Value := "Recording your sync confirmation; the worker still checks the game screen."
    }

    Launch(action, resumeId := "") {
        if this.pid
            return false
        if !FileExist(this.python) || !FileExist(this.workspace "\fh6\controller.py") {
            this.status.Value := "Keep this folder inside FH6 auto and run Setup FH6 Auto.cmd in its parent folder."
            return false
        }
        this.channel := A_ScriptDir "\LocalState\" A_Now "_" A_TickCount
        DirCreate(this.channel)
        command := this.Q(this.python) " " this.Q(this.bridge) " --channel " this.Q(this.channel)
            . " --owner " ProcessExist() " --action " action
        if action = "run"
            command .= " --mode " this.Q(this.mode.Text) " --points " this.Q(this.points.Value) " --target " this.Q(this.points.Value)
                . " --reserve " this.Q(this.reserve.Value) " --monitor " this.Q(this.monitor.Value)
                . " --timeout " this.Q(this.timeout.Value)
                . " --steam-backup " this.steamBackup.Value " --max-restarts " this.Q(this.maxRestarts.Value) " --game-priority " this.gamePriority.Value
        if action = "save-profile"
            command .= " --share-code " this.Q(this.shareCode) " --challenge-seconds " this.Q(this.challengeSeconds)
        if resumeId != ""
            command .= " --resume-goal-id " this.Q(resumeId)
        try {
            Run(command, this.workspace, "Hide", &pid)
            this.pid := pid
            this.action := action
            this.SetBusy(true)
            return true
        } catch as err {
            this.status.Value := "Could not start: " err.Message
            return false
        }
    }

    SetBusy(busy) {
        this.startButton.Enabled := !busy
        this.endButton.Enabled := !busy
        this.resolveButton.Enabled := !busy
        for control in [this.mode, this.monitor, this.timeout, this.steamBackup, this.maxRestarts, this.gamePriority]
            control.Enabled := !busy
        locked := this.mode.Text = "Earn saved Super Wheelspins" ? this.goalPending : this.pending
        this.points.Enabled := !busy && !locked
        this.reserve.Enabled := !busy && !locked
    }

    Poll(*) {
        if !this.pid {
            if FileExist(this.workspace "\runs\cloud_sync.json") {
                this.stage.Value := "Waiting for full cloud sync"
                this.status.Value := "SYNC WAIT // Watching for full completion. All game actions and restarts are paused."
            }
            if !this.closing && this.watchdog.Ready(A_TickCount) {
                this.watchdog.due := 0
                if !this.Launch("run", this.watchdog.id)
                    this.watchdog.Schedule(A_TickCount)
            }
            return
        }
        alive := ProcessExist(this.pid)
        path := this.channel "\status.ini"
        if FileExist(path) {
            values := Map()
            try {
                for line in StrSplit(IniRead(path, "run"), "`n", "`r") {
                    pos := InStr(line, "=")
                    if pos
                        values[Trim(SubStr(line, 1, pos-1))] := Trim(SubStr(line, pos+1))
                }
                this.Apply(values)
            }
        }
        if !alive {
            this.pid := 0
            if FileExist(this.channel "\stop")
                this.watchdog.Stop()
            if !FileExist(path)
                this.status.Value := "Worker could not load. Run Setup FH6 Auto.cmd in the parent folder, then reopen."
            this.SetBusy(false)
            if this.closing {
                ExitApp()
                return
            }
            if this.action = "run" && this.watchdog.Schedule(A_TickCount) {
                this.SetBusy(true)
                this.status.Value := "Worker exited. Resuming the same saved mission shortly. F7 cancels."
            } else if this.action = "run"
                this.gui.Show()
        }
    }

    Apply(values) {
        this.watchdog.Observe(values)
        get(key, fallback := "—") => values.Get(key, fallback)
        this.pending := get("pending", "0") = "1"
        this.goalPending := get("goal_pending", "0") = "1"
        this.shareCode := get("share_code", this.shareCode)
        this.challengeSeconds := get("challenge_seconds", this.challengeSeconds)
        this.status.Value := get("message", "Waiting…")
        this.stage.Value := get("stage", "Waiting")
        this.stats.Value := get("inventory_line", "SAVED SW / WS: awaiting live game read")
            . "`n" get("inventory_read", "Inventory comes only from My Horizon")
            . "`n`nMISSION NEW " get("rewards", "0") " SW    CARS " get("bought", "0")
            . "`nMAD MIKE  " get("mad_mike_left_prefix", "≤") get("mad_mike_left", get("bought", "0")) " LEFT    "
            . get("mad_mike_bought", get("bought", "0")) " BOUGHT    " get("mad_mike_processed", get("rewards", "0")) " PROCESSED    " get("mad_mike_removed", "0") " REMOVED"
            . "`n`nSP " get("points_left") " / 999    FARMS " get("farm_runs", "0") "    BATCH <=47"
            . "`n`nACTIVE " get("elapsed") "    " get("window_left")
            . "`nETA " get("eta_range", "Collecting measurements")
        this.analyticsHeader.Value := StrReplace(get("analytics_header", "Collecting mission measurements…"), " || ", "`r`n")
        this.analyticsBasis.Value := get("analytics_basis", "Current-run measurements; no automatic exports.")
        this.analyticsData := values
        this.RefreshAnalytics()
        this.bar.Value := get("percent", "0")
        this.errorImage := get("error_image", "")
        this.history.Value := StrReplace(get("history", "No saved history."), " | ", "`r`n`r`n")
        if this.action != "run" {
            this.mode.Choose(get("saved_mode", "Earn saved Super Wheelspins"))
            this.points.Value := this.mode.Text = "Earn saved Super Wheelspins" ? get("input_target", "10") : get("input_sp", "")
            this.reserve.Value := this.mode.Text = "Earn saved Super Wheelspins" ? get("goal_reserve", "0") : get("reserve", "0")
            this.monitor.Value := get("monitor", "1")
            this.timeout.Value := Round(get("timeout", "30"))
            this.steamBackup.Value := get("steam_backup", "1")
            this.maxRestarts.Value := get("max_restarts", "0")
            this.gamePriority.Value := get("game_priority", "1")
        } else if this.mode.Text != "Earn saved Super Wheelspins" && !this.pending && get("phase", "") = "complete" && RegExMatch(get("points_left", ""), "^[\d,]+$") {
            this.points.Value := StrReplace(get("points_left"), ",")
        }
        this.RefreshPlan()
    }

    RefreshAnalytics(*) {
        views := ["cars", "farms", "refills", "steps", "overview", "failures", "transitions", "attribution"]
        index := this.analyticsChoice.Value
        key := "analytics_" views[index]
        content := this.analyticsData.Get(key, "")
        signature := key content
        if this.HasOwnProp("analyticsSignature") && this.analyticsSignature = signature
            return
        this.analyticsSignature := signature
        columns := [["Cycle", "Total s", "Buy s", "Choose s", "Mastery s", "Return s", "Retries"],
                    ["Run", "Start SP", "End SP", "+ SP", "Minutes", "Launches", "Timing"],
                    ["Refill", "Start SP", "End SP", "Runs", "Minutes", "Launches", "Finished"],
                    ["Step", "P50 s", "P90 s", "P99 s", "Samples", "Scope", "Method"],
                    ["Metric", "Value", "Meaning", "", "", "", ""],
                    ["Cause", "Count", "/100 cars", "Cost s", "P50 cost", "P90 cost", "Samples"],
                    ["Stage", "Change50", "Change90", "Ready50", "Ready90", "Total99", "Samples"],
                    ["Category", "Seconds", "Meaning", "", "", "", ""]]
        this.analyticsGrid.Delete()
        for n, title in columns[index]
            this.analyticsGrid.ModifyCol(n, (index = 5 || index = 8) ? (n = 1 ? 145 : n = 2 ? 110 : n = 3 ? 390 : 0) : (n = 1 ? 138 : 78), title)
        if content != "" {
            for row in StrSplit(content, "~")
                this.analyticsGrid.Add("", StrSplit(row, "^")*)
        }
    }

    OpenAnalyticsExports(*) {
        path := this.workspace "\runs\analytics_exports"
        if DirExist(path)
            Run(this.Q(path))
        else
            this.status.Value := "No export yet. Click Export analytics CSV to create one."
    }

    Stop(*) {
        this.watchdog.Stop()
        if this.pid && this.channel != "" {
            try FileAppend("stop", this.channel "\stop", "UTF-8")
            this.status.Value := "Stop requested; waiting for input release…"
        } else if !this.closing {
            this.SetBusy(false)
            this.status.Value := "Stopped. Automatic worker retries cancelled."
        }
    }

    Close(*) {
        this.closing := true
        this.Stop()
        this.gui.Hide()
        if !this.pid
            ExitApp()
    }

    Exiting(*) {
        this.Stop()
        if this.mutex
            DllCall("CloseHandle", "Ptr", this.mutex)
    }

    EndSession(*) {
        if !this.pid && MsgBox("Check the current car first. This ends the saved session without game inputs.`nUnfinished mastery remains unfinished; a new run can buy a new car.`n`nEnd this session?", "End saved session", "YesNo Icon!") = "Yes"
            this.Launch("end")
    }

    Resolve(*) {
        if this.pid
            return
        answer := MsgBox("Inspect the purchase in the game first. Was the car bought?`n`nYes = bought`nNo = not bought`nCancel = leave unresolved", "Resolve uncertain purchase", "YesNoCancel Icon!")
        if answer != "Cancel"
            this.Launch(answer = "Yes" ? "resolve-bought" : "resolve-not-bought")
    }

    OpenError(*) {
        path := this.errorImage != "" && FileExist(this.errorImage) ? this.errorImage : this.workspace "\failures"
        try Run(this.Q(path))
    }

    SelectModule(name) {
        if this.pid
            return
        this.mode.Choose(name)
        this.tabs.Choose(1)
        this.RefreshPlan()
        this.SetBusy(false)
    }

    EditProfile(*) {
        if this.pid || this.editingProfile
            return
        this.editingProfile := true
        dialog := Gui("+Owner" this.gui.Hwnd, "Challenge settings")
        dialog.SetFont("s10", "Consolas")
        dialog.AddText("x20 y20 w370 h45", "Mega V6 uses your prepared 1998 Subaru 22B.`nEnter the challenge share code, not a race code.")
        dialog.AddText("x20 y88 w160", "Share code")
        code := dialog.AddEdit("x185 y82 w195 Number", this.shareCode)
        dialog.AddText("x20 y134 w160", "Run length (seconds)")
        seconds := dialog.AddEdit("x185 y128 w195 Number", this.challengeSeconds)
        dialog.AddText("x20 y178 w370 h60", "900 seconds = 15 minutes. Actual SP is checked after the run.`nAutomatic assists OFF; Skills HUD OFF.")
        save := dialog.AddButton("x20 y248 w170 h35", "Save")
        save.OnEvent("Click", (*) => this.SaveProfile(dialog, code, seconds))
        cancel := dialog.AddButton("x210 y248 w170 h35", "Cancel")
        cancel.OnEvent("Click", (*) => this.CloseProfile(dialog))
        dialog.OnEvent("Close", (*) => this.CloseProfile(dialog))
        dialog.Show("w405 h307")
    }

    CloseProfile(dialog) {
        this.editingProfile := false
        dialog.Destroy()
    }

    SaveProfile(dialog, code, seconds) {
        if !RegExMatch(code.Value, "^\d{9}$") || !RegExMatch(seconds.Value, "^\d+$")
            || Integer(seconds.Value) < 30 || Integer(seconds.Value) > 3600 {
            MsgBox("Use a nine-digit share code and 30–3600 seconds.", "Challenge settings")
            return
        }
        this.shareCode := code.Value
        this.challengeSeconds := Integer(seconds.Value)
        this.CloseProfile(dialog)
        this.Launch("save-profile")
    }

    SelfTest() {
        watch := MissionWatchdog()
        watch.Arm()
        if watch.Schedule(100)
            throw Error("Watchdog restarted without a saved mission id")
        watch.Observe(Map("goal_id", "test1", "goal_pending", "1"))
        Loop 20 {
            if !watch.Schedule(100) || watch.due > 120100 || watch.Ready(100)
                throw Error("Watchdog retry delay or unlimited retries failed")
            if !watch.Ready(watch.due)
                throw Error("Watchdog never became ready")
        }
        watch.Stop()
        if watch.Ready(999999) || watch.Schedule(100)
            throw Error("F7 failed to cancel watchdog")
        watch.Arm()
        watch.Observe(Map("goal_id", "test1", "goal_pending", "1"))
        watch.Observe(Map("goal_id", "test1", "goal_pending", "0"))
        if watch.Schedule(100)
            throw Error("Completed mission restarted")
        watch.Arm()
        watch.Observe(Map("goal_id", "test1", "goal_pending", "1"))
        watch.Observe(Map("goal_id", "test2", "goal_pending", "1"))
        if watch.Schedule(100)
            throw Error("Watchdog followed a different mission")
        watch.Arm()
        watch.Observe(Map("goal_id", "test1", "goal_pending", "1", "cancelled", "1"))
        if watch.Schedule(100)
            throw Error("Worker stop did not cancel watchdog")
        this.pending := false
        this.mode.Choose("Full pipeline")
        this.points.Value := "100"
        this.reserve.Value := "0"
        this.RefreshPlan()
        if !InStr(this.plan.Value, "4 cars") || !InStr(this.plan.Value, "16 SP left")
            throw Error("SP preview failed")
        this.points.Value := "532"
        this.reserve.Value := "100"
        this.RefreshPlan()
        if !InStr(this.plan.Value, "20 cars") || !InStr(this.plan.Value, "112 SP left")
            throw Error("SP reserve failed")
        this.points.Value := "20"
        this.Start()
        if this.pid
            throw Error("Invalid budget launched a worker")
        this.action := "inspect"
        this.Apply(Map("pending", "1", "completed", "5", "limit", "25", "remaining", "20", "input_sp", "532", "stage", "Open mastery", "saved_mode", "Full pipeline"))
        if !this.pending || !InStr(this.stats.Value, "5 / 25")
            throw Error("Saved checkpoint display failed")
        this.SetBusy(false)
        if this.points.Enabled
            throw Error("Saved budget must be locked")
        this.pending := false
        this.goalPending := false
        this.mode.Choose("Earn saved Super Wheelspins")
        this.points.Value := "50"
        this.RefreshPlan()
        if !InStr(this.plan.Value, "50 Super Wheelspins") || !InStr(this.plan.Value, "1050 SP")
            throw Error("Wheelspin target preview failed")
        FileAppend("AHK panel checks passed. No game inputs sent.`n", "*")
        this.gui.Destroy()
        ExitApp(0)
    }
}
