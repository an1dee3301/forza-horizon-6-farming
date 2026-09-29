; Local control panel. All game recognition and inputs live in the Python worker.
; Closing this panel requests a stop; the worker also watches its parent's PID.
class LocalPanel {
    __New(testMode := false, wheelspinTrial := 0, previewMode := false, tokyoTarget := 0) {
        this.pid := 0
        this.watchdog := MissionWatchdog()
        this.channel := ""
        this.action := ""
        this.lastPhase := ""
        this.pending := false
        this.goalPending := false
        this.savedMode := ""
        this.savedTokyoLimit := ""
        this.inspectionReady := false
        this.savedCreditFloor := ""
        this.editingProfile := false
        this.shareCode := "155439962"
        this.challengeSeconds := 900
        this.closing := false
        this.testMode := testMode
        this.previewMode := previewMode
        this.errorImage := ""
        this.mutex := 0
        this.workspace := A_ScriptDir "\.."
        this.python := this.workspace "\.venv\Scripts\pythonw.exe"
        this.bridge := A_ScriptDir "\Runtime\bridge.py"
        if !testMode && !previewMode {
            this.mutex := DllCall("CreateMutexW", "Ptr", 0, "Int", 0, "Str", "Local\FH6AutoDashboard", "Ptr")
            if !this.mutex || A_LastError = 183 {
                MsgBox("An FH6 Auto panel is already open. Use that panel or close it first.", "FH6 Auto")
                ExitApp()
            }
        }
        this.Build()
        if previewMode {
            this.RefreshPlan()
            this.status.Value := "Preview only. No game connection or worker is running."
            this.runState.Value := "PREVIEW"
            this.gui.OnEvent("Close", (*) => ExitApp())
            return
        }
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
        this.wheelspinTrialPending := wheelspinTrial
        this.tokyoTargetPending := tokyoTarget
        this.Launch("inspect")
        this.DiscordReports("--watch")
    }

    Build() {
        this.gui := Gui("-MaximizeBox", "FH6 Auto — Workspace")
        this.gui.BackColor := "0F1219"
        this.gui.SetFont("s10 cE6EAF2 Norm", "Segoe UI")
        ; A quiet navigation rail and a fixed content grid keep every workspace
        ; predictable. No placeholder values are presented as live measurements.
        this.gui.AddText("x0 y0 w196 h770 Background151A24", "")
        this.gui.AddProgress("x195 y0 w1 h770 c273043 Background273043 Range0-1", 1)
        this.gui.SetFont("s21 cF4F6FB Bold", "Segoe UI")
        this.gui.AddText("x24 y28 w155 h40 BackgroundTrans", "FH6 Auto")
        this.gui.SetFont("s9 c92A0B8 Norm")
        this.gui.AddText("x25 y74 w148 h42 BackgroundTrans", "Your local farming`nworkspace")
        this.gui.AddProgress("x24 y130 w148 h1 c2B3445 Background2B3445 Range0-1", 1)
        this.gui.SetFont("s9 cA8B7D0 Bold")
        this.gui.AddText("x24 y151 w148 h20 BackgroundTrans", "WORKFLOW")
        this.gui.SetFont("s10 cCBD4E4 Norm")
        this.gui.AddText("x24 y184 w148 h130 BackgroundTrans", "01   Set a mission`n`n02   Track activity`n`n03   Review results")
        this.gui.SetFont("s9 c92A0B8 Norm")
        this.gui.AddText("x24 y353 w148 h95 BackgroundTrans", "Saved progress`nResume the current car`nfrom its checkpoint.")
        this.gui.AddProgress("x24 y619 w148 h1 c2B3445 Background2B3445 Range0-1", 1)
        this.gui.SetFont("s9 c92A0B8 Norm")
        this.gui.AddText("x24 y642 w148 h80 BackgroundTrans", "KEYBOARD`n`nF6   Start / resume`nF7   Request stop")
        this.gui.SetFont("s24 cF4F6FB Bold")
        this.gui.AddText("x220 y28 w756 h43", "Mission workspace")
        this.gui.SetFont("s10 c92A0B8 Norm")
        this.gui.AddText("x222 y79 w750 h24", "Plan your run, follow saved progress and explore measured performance.")
        this.tabs := this.gui.AddTab3("x220 y126 w756 h462 Background151A24 cF4F6FB", ["  Mission  ", "  Activity  ", "  Recovery  ", "  History  ", "  Tools  ", "  Analytics  "])
        this.tabs.UseTab(1)
        this.gui.SetFont("s10 cE6EAF2 Norm")
        this.gui.AddText("x244 y180 w173", "Run mode")
        this.mode := this.gui.AddDropDownList("x432 y174 w508 Choose1", ["Earn saved Super Wheelspins", "Wheelspin Lab", "Tokyo Delivery", "Full pipeline", "Buy only", "Mastery only", "Recognition only", "Farm SP only", "Return to collection", "Check farm setup", "Open game"])
        this.mode.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.quantityLabel := this.gui.AddText("x244 y235 w173", "Super Wheelspins")
        this.points := this.gui.AddEdit("x432 y228 w194 h32 Border Background1C2330 cFFFFFF Number", "10")
        this.gui.AddText("x244 y286 w173", "SP to keep")
        this.reserve := this.gui.AddEdit("x432 y278 w194 h32 Border Background1C2330 cFFFFFF Number", "0")
        this.gui.AddText("x658 y235 w97", "Spin type")
        this.spinType := this.gui.AddDropDownList("x756 y228 w184 Choose1", ["SUPER", "REGULAR"])
        this.dryRun := this.gui.AddCheckbox("x658 y278 w130 h28 Checked cE6EAF2", "Dry Run")
        this.stopUnknown := this.gui.AddCheckbox("x793 y278 w157 h28 Checked cE6EAF2", "Stop on unknown")
        this.spinType.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.dryRun.OnEvent("Click", ObjBindMethod(this, "RefreshPlan"))
        this.stopUnknown.OnEvent("Click", ObjBindMethod(this, "RefreshPlan"))
        this.points.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.reserve.OnEvent("Change", ObjBindMethod(this, "RefreshPlan"))
        this.gui.SetFont("s13 c9AB8FF Norm", "Segoe UI")
        this.plan := this.gui.AddText("x244 y333 w702 h66", "Enter your current skill points.")
        this.gui.SetFont("s10 c92A0B8 Norm", "Segoe UI")
        this.gui.AddText("x244 y407 w173", "Credits to keep (CR)")
        this.creditFloor := this.gui.AddEdit("x432 y400 w194 h32 Border Background1C2330 cFFFFFF Number", "")
        this.cleanupPolicy := this.gui.AddDropDownList("x658 y401 w281 Choose1", ["Keep saved / default cleanup", "Final cleanup only"])
        this.savedCreditPolicy := this.gui.AddText("x244 y438 w702 h34", "Optional reserve: blank keeps the saved setting. No reserve by default.")
        this.gui.AddText("x244 y486 w140", "Game monitor")
        this.monitor := this.gui.AddEdit("x394 y479 w81 h30 Number Border Background1C2330 cFFFFFF", "1")
        this.gui.AddText("x542 y486 w162", "Screen timeout (sec)")
        this.timeout := this.gui.AddEdit("x722 y479 w81 h30 Number Border Background1C2330 cFFFFFF", "30")
        this.tabs.UseTab(2)
        ; Keep the main production counters visible while the detailed report scrolls.
        this.liveLabels := []
        this.liveValues := []
        for index, name in ["NEW REWARDS", "CARS COMPLETE", "GARAGE QUEUE", "FARM RUNS"] {
            x := 244 + (index - 1) * 178
            this.gui.AddText("x" x " y175 w166 h76 Background151A24", "")
            this.gui.AddProgress("x" x " y175 w166 h2 c4776E6 Background4776E6 Range0-1", 1)
            this.gui.SetFont("s8 c92A0B8 Bold", "Segoe UI")
            this.liveLabels.Push(this.gui.AddText("x" (x + 10) " y187 w146 h17 BackgroundTrans", name))
            this.gui.SetFont("s19 cF4F6FB Bold", "Segoe UI")
            this.liveValues.Push(this.gui.AddText("x" (x + 10) " y207 w146 h32 BackgroundTrans", "—"))
        }
        this.gui.SetFont("s9 cE6EAF2 Norm", "Consolas")
        this.stats := this.gui.AddEdit("x244 y254 w702 h124 ReadOnly Multi VScroll Border Background121722 cE6EAF2", "No run started.")
        this.bar := this.gui.AddProgress("x244 y392 w702 h12 c9AB8FF Background273043 Range0-100", 0)
        this.gui.SetFont("s11 c9AB8FF Norm")
        this.inventorySummary := this.gui.AddText("x244 y416 w702 h25", "Saved inventory · awaiting a game reading")
        this.gui.SetFont("s8 c92A0B8 Norm")
        this.inventoryTimestamp := this.gui.AddText("x244 y443 w702 h19", "Source: My Horizon · no estimated inventory")
        this.gui.SetFont("s11 c9AB8FF Norm")
        this.stage := this.gui.AddText("x244 y466 w702 h25 +0x280", "Waiting")
        this.gui.SetFont("s9 c92A0B8 Norm")
        this.gui.AddText("x244 y495 w702 h42", "SP is read from the game; ≤ marks an unfinished tree.`nInventory and session details update when a worker reports them.")
        this.tabs.UseTab(3)
        this.gui.SetFont("s10 cE6EAF2 Norm")
        this.AddButton("x244 y183 w313 h38", "Open logs", (*) => Run(this.Q(this.workspace "\runs")))
        this.AddButton("x581 y183 w313 h38", "Error screenshot", ObjBindMethod(this, "OpenError"))
        this.endButton := this.AddButton("x244 y247 w313 h38", "End saved session…", ObjBindMethod(this, "EndSession"))
        this.resolveButton := this.AddButton("x581 y247 w313 h38", "Resolve uncertain purchase…", ObjBindMethod(this, "Resolve"))
        this.AddButton("x244 y295 w313 h34", "Confirm completed cloud sync…", ObjBindMethod(this, "ConfirmSync"))
        this.gui.AddText("x581 y302 w346 h27", "Resume from the last saved checkpoint.")
        this.gui.SetFont("s10 c92A0B8 Norm")
        this.gui.AddText("x244 y336 w702 h133", "Resume keeps the original car target and the current stage.`nLeave the selected car unchanged after a stop.`n`nAn uncertain purchase blocks buying until its receipt is verified or you record the outcome.`n`nPurchased cars remain in the garage. An owned Super Wheelspin node completes the reward check.")
        this.steamBackup := this.gui.AddCheckbox("x244 y482 w491 h25 Checked cE6EAF2", "Open through Steam and restart after crashes")
        this.gui.AddText("x244 y519 w313 h22", "Crash limit (0 = unlimited, up to 10)")
        this.maxRestarts := this.gui.AddEdit("x581 y513 w81 h29 Number Border Background1C2330 cFFFFFF", "0")
        this.gamePriority := this.gui.AddCheckbox("x693 y515 w238 h25 Checked cE6EAF2", "Prioritize game focus")
        this.tabs.UseTab(4)
        this.gui.SetFont("s10 cE6EAF2 Norm")
        this.history := this.gui.AddEdit("x244 y184 w702 h332 ReadOnly Multi Border Background121722 cE6EAF2", "Loading history…")
        this.tabs.UseTab(5)
        this.gui.SetFont("s10 cE6EAF2 Norm")
        this.gui.AddText("x244 y176 w702 h50", "Mega Farm V6  •  155439962  •  about 15 minutes per run`nUse a fully upgraded 1998 Subaru 22B with completed mastery.")
        this.AddButton("x244 y238 w313 h36", "Check Mega V6 settings", (*) => this.SelectModule("Check farm setup"))
        this.AddButton("x581 y238 w313 h36", "Farm SP only", (*) => this.SelectModule("Farm SP only"))
        this.AddButton("x244 y288 w313 h36", "Buy cars from current SP", (*) => this.SelectModule("Buy only"))
        this.AddButton("x581 y288 w313 h36", "Claim current mastery tree", (*) => this.SelectModule("Mastery only"))
        this.AddButton("x244 y338 w313 h36", "Return to Car Collection", (*) => this.SelectModule("Return to collection"))
        this.AddButton("x581 y338 w313 h36", "Recognition without inputs", (*) => this.SelectModule("Recognition only"))
        this.AddButton("x244 y388 w313 h36", "Challenge profile", ObjBindMethod(this, "EditProfile"))
        this.AddButton("x581 y388 w313 h36", "Module guide / repo features", (*) => Run(this.Q(this.workspace "\MODULES.md")))
        this.gui.SetFont("s9 c92A0B8 Norm")
        this.AddButton("x244 y435 w313 h36", "Open game through Steam", (*) => this.SelectModule("Open game"))
        this.AddButton("x581 y435 w313 h36", "Discord reports", (*) => this.DiscordReports("--settings"))
        this.gui.AddText("x244 y487 w702 h52", "Mega V6: automatic steering/braking OFF; Skills HUD OFF.`nThe program checks SP after farming. The advertised yield is not guaranteed.`nChallenge navigation is being validated; an unrecognized screen stops the run.")
        this.tabs.UseTab(6)
        this.gui.SetFont("s10 cE6EAF2 Norm", "Segoe UI")
        this.analyticsHeader := this.gui.AddText("x244 y176 w702 h78", "Run measurements appear here when available.")
        this.analyticsChoice := this.gui.AddDropDownList("x244 y262 w324 Choose5", ["Car cycles", "Farm runs", "Batch SP refills", "Stage P50 / P90 / P99", "Throughput / mission", "Failure causes / cost", "Transition latency", "Time attribution", "Wheelspin exclusives", "Wheelspin keeps"])
        this.analyticsChoice.OnEvent("Change", ObjBindMethod(this, "RefreshAnalytics"))
        this.analyticsGrid := this.gui.AddListView("x244 y301 w702 h174 Background121722 cE6EAF2 ", ["Step", "Mean s", "Median s", "Min s", "Max s", "Samples", ""])
        this.analyticsData := Map()
        this.analyticsBasis := this.gui.AddText("x244 y479 w702 h20", "No samples yet. Tables use recorded run measurements.")
        this.AddButton("x244 y501 w214 h32", "Export mission CSV", (*) => Run(this.Q(this.python) " -m fh6.analytics --export", this.workspace, "Hide"))
        this.AddButton("x466 y501 w214 h32", "Export Wheelspin CSV", (*) => Run(this.Q(this.python) " -m fh6.wheelspin_history --export " this.Q(this.workspace "\runs\wheelspin_exports"), this.workspace, "Hide"))
        this.AddButton("x689 y501 w205 h32", "Open exports", (*) => this.OpenAnalyticsExports())
        this.AddButton("x244 y539 w650 h28", "ETA history / interactive chart", (*) => Run(this.workspace "\runs\reports\eta_history.html"))
        this.tabs.UseTab()
        this.gui.SetFont("s11 cFFFFFF Bold", "Segoe UI")
        this.startButton := this.AddButton("x220 y611 w502 h44", "F6   START / RESUME", ObjBindMethod(this, "Start"))
        this.stopButton := this.AddButton("x738 y611 w238 h44", "F7   STOP", ObjBindMethod(this, "Stop"))
        this.gui.AddText("x220 y672 w756 h66 Background151A24", "")
        this.gui.SetFont("s9 cCBD4E4 Bold")
        this.runState := this.gui.AddText("x234 y688 w108 h25 Center +0x200 Background273043", "READY")
        this.gui.SetFont("s10 cE6EAF2 Norm")
        this.status := this.gui.AddText("x358 y682 w603 h48 BackgroundTrans", "Loading saved progress…")
        this.gui.SetFont("s8 c92A0B8 Norm")
        this.gui.AddText("x222 y746 w754 h18", "LOCAL WORKSPACE   ·   Progress is checkpointed   ·   Stop requests finish through the worker")
        corners := Buffer(4, 0)
        NumPut("Int", 2, corners)
        try DllCall("dwmapi\DwmSetWindowAttribute", "Ptr", this.gui.Hwnd, "UInt", 33, "Ptr", corners, "UInt", 4)
        dark := Buffer(4, 0)
        NumPut("Int", 1, dark)
        try DllCall("dwmapi\DwmSetWindowAttribute", "Ptr", this.gui.Hwnd, "UInt", 20, "Ptr", dark, "UInt", 4)
        this.gui.Show("w1000 h770" (this.testMode ? " Hide" : ""))
    }

    AddButton(options, text, callback) {
        style := " Center +0x100 +0x200 Background273043 cE6EAF2"
        if InStr(text, "F6") && InStr(text, "START")
            style := " Center +0x100 +0x200 Background4776E6 cFFFFFF"
        else if InStr(text, "F7") && InStr(text, "STOP")
            style := " Center +0x100 +0x200 Background422A34 cFFD9E1"
        button := this.gui.AddText(options style, text)
        button.OnEvent("Click", this.previewMode ? (*) => 0 : callback)
        return button
    }

    Q(value) => Chr(34) value Chr(34)

    DiscordReports(option) {
        try Run(this.Q(this.python) " -m fh6.discord_reports " option, this.workspace, "Hide")
    }

    RefreshPlan(*) {
        goal := this.mode.Text = "Earn saved Super Wheelspins"
        this.creditFloor.Enabled := goal && !this.pid
        this.cleanupPolicy.Enabled := goal && !this.pid
        lab := this.mode.Text = "Wheelspin Lab"
        delivery := this.mode.Text = "Tokyo Delivery"
        this.quantityLabel.Value := goal ? "Super Wheelspins" : lab ? "Spins to open" : delivery ? "Shifts to finish" : "Current SP"
        if lab {
            if !RegExMatch(this.points.Value, "^\d+$") || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000 {
                this.plan.Value := "Enter 1–10,000 Wheelspins to open and record."
                return
            }
            state := this.dryRun.Value ? "DRY RUN — duplicate action stops for review" : "AUTO ACTIONS — activation gate must be complete"
            this.plan.Value := this.points.Value " " this.spinType.Text " spins  •  every reward slot saved first`n" state
            return
        }
        if delivery {
            if this.goalPending {
                this.plan.Value := "Finish the saved Super Wheelspin goal before starting Tokyo Delivery."
                return
            }
            if !RegExMatch(this.points.Value, "^\d+$") || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000 {
                this.plan.Value := "Enter 1–10,000 Tokyo Delivery shifts to complete."
                return
            }
            this.plan.Value := this.points.Value " completed shifts  •  F7 stops at any time`nEach shift counts only after its game result is verified."
            return
        }
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

    PrepareWheelspinTrial(count) {
        if this.pid || count < 1 || count > 10000
            return
        this.mode.Choose(2)
        this.points.Value := count
        this.spinType.Choose(1)
        this.dryRun.Value := 0
        this.stopUnknown.Value := 0
        this.RefreshPlan()
        this.tabs.Choose(1)
        this.status.Value := count "-Super Wheelspin run prepared. F6 starts; F7 stops."
    }

    PrepareTokyoDelivery(count) {
        if this.pid || count < 1 || count > 10000
            return
        this.mode.Choose("Tokyo Delivery")
        this.points.Value := count
        this.RefreshPlan()
        this.tabs.Choose(1)
        this.status.Value := count " Tokyo Delivery shifts selected. Starting through the saved worker checkpoint."
    }

    Start(*) {
        if this.pid || this.closing || this.editingProfile
            return
        if this.mode.Text = "Earn saved Super Wheelspins" {
            floor := Trim(this.creditFloor.Value)
            if floor != "" && (!RegExMatch(floor, "^\d+$") || Integer(floor) < 1 || Integer(floor) > 999999999) {
                this.status.Value := "Credits to keep must be blank or 1–999,999,999 CR."
                return
            }
            if this.cleanupPolicy.Value = 2 && floor = "" && this.savedCreditFloor = "" {
                this.status.Value := "Set Credits to keep before choosing final cleanup only."
                return
            }
            if !RegExMatch(this.points.Value, "^\d+$") || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000
                || !RegExMatch(this.reserve.Value, "^\d+$") || Integer(this.reserve.Value) > 978 {
                this.status.Value := "Choose 1–10,000 Super Wheelspins and an SP reserve of 0–978."
                return
            }
        }
        if this.mode.Text = "Wheelspin Lab" && (!RegExMatch(this.points.Value, "^\d+$")
            || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000) {
            this.status.Value := "Choose 1–10,000 Wheelspins for Wheelspin Lab."
            return
        }
        if this.mode.Text = "Tokyo Delivery" && (!RegExMatch(this.points.Value, "^\d+$")
            || Integer(this.points.Value) < 1 || Integer(this.points.Value) > 10000) {
            this.status.Value := "Choose 1–10,000 Tokyo Delivery shifts."
            return
        }
        if this.mode.Text = "Tokyo Delivery" && this.goalPending {
            this.status.Value := "Finish the saved Super Wheelspin goal before Tokyo Delivery."
            return
        }
        if this.mode.Text = "Tokyo Delivery" && this.pending && this.savedMode != "Tokyo Delivery" {
            this.status.Value := "Finish the saved car before Tokyo Delivery."
            return
        }
        if this.mode.Text = "Tokyo Delivery" && this.pending && this.savedTokyoLimit != ""
            && this.points.Value != this.savedTokyoLimit {
            this.status.Value := "Resume Tokyo Delivery with its saved shift target."
            return
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
                . " --spin-type " this.spinType.Text " --dry-run " this.dryRun.Value " --stop-on-unknown " this.stopUnknown.Value
                . " --steam-backup " this.steamBackup.Value " --max-restarts " this.Q(this.maxRestarts.Value) " --game-priority " this.gamePriority.Value
        if action = "run"
            command .= this.CreditPolicyArgs()
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
        if busy
            this.runState.Value := this.action = "run" ? "RUNNING" : "CHECKING"
        else if this.action = "run" && this.channel != "" && FileExist(this.channel "\stop")
            this.runState.Value := "STOPPED"
        else if this.lastPhase = "complete"
            this.runState.Value := "COMPLETE"
        else
            this.runState.Value := "READY"
        this.startButton.Enabled := !busy
        this.endButton.Enabled := !busy
        this.resolveButton.Enabled := !busy
        for control in [this.mode, this.monitor, this.timeout, this.steamBackup, this.maxRestarts, this.gamePriority, this.spinType, this.dryRun, this.stopUnknown]
            control.Enabled := !busy
        locked := this.mode.Text = "Earn saved Super Wheelspins" ? this.goalPending : this.pending
        this.points.Enabled := !busy && !locked
        this.reserve.Enabled := !busy && !locked
        this.creditFloor.Enabled := !busy && this.mode.Text = "Earn saved Super Wheelspins"
        this.cleanupPolicy.Enabled := !busy && this.mode.Text = "Earn saved Super Wheelspins"
    }

    CreditPolicyArgs() {
        if this.mode.Text != "Earn saved Super Wheelspins"
            return ""
        result := ""
        floor := Trim(this.creditFloor.Value)
        if floor != ""
            result .= " --credit-floor " this.Q(floor)
        if this.cleanupPolicy.Value = 2
            result .= " --cleanup-policy final_only"
        return result
    }

    Poll(*) {
        if !this.pid {
            if FileExist(this.workspace "\runs\cloud_sync.json") {
                this.runState.Value := "SYNC WAIT"
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
            if this.action = "inspect" && this.wheelspinTrialPending {
                count := this.wheelspinTrialPending
                this.wheelspinTrialPending := 0
                this.PrepareWheelspinTrial(count)
            }
            if this.action = "inspect" && this.tokyoTargetPending {
                count := this.tokyoTargetPending
                this.tokyoTargetPending := 0
                if !this.inspectionReady {
                    this.status.Value := "Startup inspection did not complete. Tokyo Delivery was not started."
                    this.gui.Show()
                } else if this.goalPending {
                    this.status.Value := "A saved farming mission is pending. Tokyo Delivery was not started."
                    this.gui.Show()
                } else if this.pending && this.savedMode != "Tokyo Delivery" {
                    this.status.Value := "A different saved mission is pending. Tokyo Delivery was not started."
                    this.gui.Show()
                } else if this.pending && this.savedTokyoLimit != "" && Integer(this.savedTokyoLimit) != count {
                    this.status.Value := "Resume Tokyo Delivery with its saved shift target."
                    this.gui.Show()
                } else {
                    this.PrepareTokyoDelivery(count)
                    this.Start()
                }
            }
            if this.closing {
                ExitApp()
                return
            }
            if this.action = "run" && this.watchdog.Schedule(A_TickCount) {
                this.SetBusy(true)
                this.runState.Value := "RECOVERING"
                this.status.Value := "Worker exited. Resuming the same saved mission shortly. F7 cancels."
            } else if this.action = "run"
                this.gui.Show()
        }
    }

    Apply(values) {
        this.watchdog.Observe(values)
        get(key, fallback := "—") => values.Get(key, fallback)
        this.lastPhase := get("phase", "")
        this.pending := get("pending", "0") = "1"
        this.goalPending := get("goal_pending", "0") = "1"
        if this.action = "inspect" {
            this.savedMode := get("saved_mode", "")
            this.savedTokyoLimit := this.savedMode = "Tokyo Delivery" ? get("limit", "") : ""
            this.inspectionReady := get("ok", "0") = "1"
        }
        this.shareCode := get("share_code", this.shareCode)
        this.challengeSeconds := get("challenge_seconds", this.challengeSeconds)
        this.status.Value := get("message", "Waiting…")
        this.stage.Value := get("stage", "Waiting")
        this.inventorySummary.Value := get("inventory_line", "SAVED SW / WS: awaiting live game read")
        this.inventoryTimestamp.Value := get("inventory_read", "Inventory comes only from My Horizon")
        if this.pid {
            if this.channel != "" && FileExist(this.channel "\stop")
                this.runState.Value := "STOPPING"
            else if this.stage.Value = "Waiting for full cloud sync" || this.lastPhase = "sync_wait"
                this.runState.Value := "SYNC WAIT"
            else if this.lastPhase = "complete"
                this.runState.Value := "COMPLETE"
            else
                this.runState.Value := this.action = "run" ? "RUNNING" : "CHECKING"
        }
        if get("run_mode", "") = "Tokyo Delivery" {
            for index, label in ["SHIFTS DONE", "SHIFTS LEFT", "SHIFT TARGET", "RUN TIME"]
                this.liveLabels[index].Value := label
            for index, value in [get("completed", "0"), get("remaining", "—"), get("limit", "—"), get("elapsed", "—")]
                this.liveValues[index].Value := value
            this.inventorySummary.Value := "Tokyo City Food Delivery"
            this.inventoryTimestamp.Value := "Completed shifts require a verified game result."
            this.stats.Value := "TOKYO DELIVERY  " get("completed", "0") " / " get("limit", "—")
                . "    REMAINING  " get("remaining", "—")
                . "`n`nSTAGE  " get("stage", "Waiting")
                . "`nPHASE  " get("phase", "—")
                . "`n`nVERIFIED SHIFTS  " get("completed", "0")
                . "`nACTIVE  " get("elapsed", "—") "    " get("window_left", "UNTIL SHIFTS / F7")
        } else if get("run_mode", "") = "Wheelspin Lab" {
            for index, label in ["SUPER SPINS", "REWARD SLOTS", "CAR REWARDS", "CARS KEPT"]
                this.liveLabels[index].Value := label
            for index, value in [get("lab_super_spins", "0"), get("lab_reward_slots", "0"), get("lab_car_rewards", "0"), get("lab_retained", "0")]
                this.liveValues[index].Value := value
            this.stats.Value := "WHEELSPIN LAB  " get("completed", "0") " / " get("limit", "—")
                . "    REMAINING  " get("remaining", "—")
                . "`n`nSUPER " get("lab_super_spins", "0") "    REGULAR " get("lab_regular_spins", "0")
                . "    SLOTS " get("lab_reward_slots", "0")
                . "`nCAR REWARDS " get("lab_car_rewards", "0") "    DUPLICATES " get("lab_duplicates", "0")
                . "`nEXCLUSIVE " get("lab_exclusive_pulls", "0") "    SOLD " get("lab_sold", "0") "    KEPT " get("lab_retained", "0")
                . "`nSELL CR " get("lab_sell_cr", "0")
                . "`n`nEVERY REWARD COMMITTED BEFORE PROCESSING"
                . "`nACTIVE " get("elapsed") "    " get("window_left")
        } else {
            for index, label in ["MISSION NEW", "CARS PROCESSED", "GARAGE LEFT", "FARM RUNS"]
                this.liveLabels[index].Value := label
            for index, value in [get("rewards", "0"), get("mad_mike_processed", get("rewards", "0")), get("mad_mike_left_prefix", "≤") get("mad_mike_left", get("bought", "0")), get("farm_runs", "0")]
                this.liveValues[index].Value := value
            this.stats.Value := "PROGRESS  " get("completed", "0") " / " get("limit", "—")
            . "    REMAINING  " get("remaining", "—")
            . "`n`n" get("inventory_line", "SAVED SW / WS: awaiting live game read")
            . "`n" get("inventory_read", "Inventory comes only from My Horizon")
            . "`n`nMISSION NEW " get("rewards", "0") " SW    CARS " get("bought", "0")
            . "`nMAD MIKE  " get("mad_mike_left_prefix", "≤") get("mad_mike_left", get("bought", "0")) " LEFT    "
            . get("mad_mike_bought", get("bought", "0")) " BOUGHT    " get("mad_mike_processed", get("rewards", "0")) " PROCESSED    " get("mad_mike_removed", "0") " REMOVED"
            . "`n`nSP " get("points_left") " / 999    FARMS " get("farm_runs", "0") "    BATCH <=47"
            . "`n`nACTIVE " get("elapsed") "    " get("window_left")
            . "`nETA " get("eta_range", "Collecting measurements")
        }
        this.analyticsHeader.Value := StrReplace(get("analytics_header", "Collecting mission measurements…"), " || ", "`r`n")
        this.analyticsBasis.Value := get("analytics_basis", "Current-run measurements; no automatic exports.")
        this.analyticsData := values
        this.RefreshAnalytics()
        this.bar.Value := get("percent", "0")
        this.errorImage := get("error_image", "")
        this.history.Value := StrReplace(get("history", "No saved history."), " | ", "`r`n`r`n")
        this.savedCreditFloor := get("goal_credit_floor", "")
        savedCleanup := get("goal_cleanup_policy", "") = "final_only" ? "final cleanup only" : "saved / default cleanup"
        this.savedCreditPolicy.Value := this.savedCreditFloor != "" ? "Saved reserve: " this.savedCreditFloor " CR  •  " savedCleanup "`nBlank preserves this setting on resume." : "Optional reserve: blank keeps the saved setting. No reserve by default."
        if this.action != "run" {
            this.mode.Choose(get("saved_mode", "Earn saved Super Wheelspins"))
            this.points.Value := this.mode.Text = "Earn saved Super Wheelspins" ? get("input_target", "10")
                : this.mode.Text = "Wheelspin Lab" || this.mode.Text = "Tokyo Delivery" ? get("limit", get("input_sp", "")) : get("input_sp", "")
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
        views := ["cars", "farms", "refills", "steps", "overview", "failures", "transitions", "attribution", "wheelspin", "retention"]
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
                    ["Category", "Seconds", "Meaning", "", "", "", ""],
                    ["Exclusive car", "Count", "First seen", "Last seen", "/100 SWP", "", ""],
                    ["Keep target / model", "Pulls", "Scope", "", "", "", ""]]
        this.analyticsGrid.Delete()
        for n, title in columns[index]
            this.analyticsGrid.ModifyCol(n, (index = 5 || index = 8) ? (n = 1 ? 145 : n = 2 ? 110 : n = 3 ? 390 : 0) : (n = 1 ? 138 : 78), title)
        if content != "" {
            for row in StrSplit(content, "~")
                this.analyticsGrid.Add("", StrSplit(row, "^")*)
        }
    }

    OpenAnalyticsExports(*) {
        path := this.workspace "\runs"
        if DirExist(path)
            Run(this.Q(path))
        else
            this.status.Value := "No export yet. Click Export analytics CSV to create one."
    }

    Stop(*) {
        this.watchdog.Stop()
        this.tokyoTargetPending := 0
        if this.pid && this.channel != "" {
            try FileAppend("stop", this.channel "\stop", "UTF-8")
            this.runState.Value := "STOPPING"
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
        this.Apply(Map("pending", "1", "completed", "5", "limit", "25", "remaining", "20", "input_sp", "532", "stage", "Open mastery", "saved_mode", "Full pipeline", "rewards", "3", "mad_mike_processed", "2", "mad_mike_left", "1", "farm_runs", "4"))
        if !this.pending || !InStr(this.stats.Value, "5 / 25")
            throw Error("Saved checkpoint display failed")
        if this.liveValues[1].Value != "3" || this.liveValues[2].Value != "2" || this.liveValues[4].Value != "4"
            throw Error("Live mission cards do not match saved progress")
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
        this.creditFloor.Value := ""
        this.cleanupPolicy.Choose(1)
        if this.CreditPolicyArgs() != ""
            throw Error("Blank reserve must preserve saved policy")
        this.creditFloor.Value := "1234567"
        this.cleanupPolicy.Choose(2)
        policyArgs := this.CreditPolicyArgs()
        if !InStr(policyArgs, "--credit-floor") || !InStr(policyArgs, "1234567") || !InStr(policyArgs, "--cleanup-policy final_only")
            throw Error("Explicit reserve/cleanup arguments missing")
        this.mode.Choose("Full pipeline")
        if this.CreditPolicyArgs() != ""
            throw Error("Credit policy leaked into another mode")
        this.mode.Choose("Earn saved Super Wheelspins")
        this.SetBusy(true)
        if this.creditFloor.Enabled || this.cleanupPolicy.Enabled
            throw Error("Running reserve controls must be locked")
        this.SetBusy(false)
        if !this.creditFloor.Enabled || !this.cleanupPolicy.Enabled
            throw Error("Idle reserve controls must be editable")
        this.pid := 1
        this.action := "run"
        this.Apply(Map("phase", "farm_drive", "stage", "Farming"))
        if this.runState.Value != "RUNNING"
            throw Error("Live worker badge did not show running")
        this.Apply(Map("phase", "sync_wait", "stage", "Waiting for full cloud sync"))
        if this.runState.Value != "SYNC WAIT"
            throw Error("Cloud sync badge did not show waiting")
        this.Apply(Map("phase", "complete", "stage", "Complete"))
        this.pid := 0
        this.SetBusy(false)
        if this.runState.Value != "COMPLETE"
            throw Error("Finished worker badge did not show complete")
        this.pending := false
        this.goalPending := false
        this.mode.Choose("Tokyo Delivery")
        this.points.Value := "3"
        this.RefreshPlan()
        if !InStr(this.plan.Value, "3 completed shifts")
            throw Error("Tokyo Delivery target preview failed")
        this.action := "inspect"
        this.Apply(Map("run_mode", "Tokyo Delivery", "saved_mode", "Tokyo Delivery",
            "pending", "1", "completed", "1", "limit", "3", "remaining", "2",
            "phase", "active", "stage", "Tokyo Delivery — drive the route", "elapsed", "0:12", "ok", "1"))
        if !InStr(this.stats.Value, "1 / 3") || this.liveLabels[1].Value != "SHIFTS DONE"
            || this.liveValues[2].Value != "2" || this.points.Value != "3"
            || !this.inspectionReady || this.savedTokyoLimit != "3"
            throw Error("Tokyo Delivery checkpoint display failed")
        this.pending := false
        this.PrepareTokyoDelivery(2)
        if this.mode.Text != "Tokyo Delivery" || this.points.Value != "2"
            throw Error("Tokyo Delivery startup target failed")
        FileAppend("AHK panel checks passed. No game inputs sent.`n", "*")
        this.gui.Destroy()
        ExitApp(0)
    }
}
