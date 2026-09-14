; Restarts a failed worker only for the exact mission armed by Start/F6.
class MissionWatchdog {
    __New() {
        this.armed := false
        this.id := ""
        this.due := 0
        this.attempts := 0
    }
    Arm() {
        this.armed := true
        this.id := ""
        this.due := 0
        this.attempts := 0
    }
    Stop() {
        this.armed := false
        this.due := 0
    }
    Observe(values) {
        if values.Get("cancelled", "0") = "1" {
            this.Stop()
            return
        }
        id := values.Get("goal_id", "")
        if !this.armed || id = ""
            return
        if this.id != "" && this.id != id {
            this.Stop()
            return
        }
        this.id := id
        if values.Get("goal_pending", "0") != "1"
            this.Stop()
    }
    Schedule(now) {
        if !this.armed || this.id = ""
            return false
        this.attempts += 1
        this.due := now + Min(120000, 15000 * 2 ** Min(3, this.attempts - 1))
        return true
    }
    Ready(now) {
        return this.armed && this.due && now >= this.due
    }
}
