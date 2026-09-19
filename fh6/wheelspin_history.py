"""Durable SQLite event store and exports for Wheelspin Lab."""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import sqlite3
import uuid


SCHEMA_VERSION = 1
REWARD_TYPES = {"CAR", "CREDITS", "CLOTHING", "HORN", "EMOTE", "COSMETIC", "OTHER", "UNKNOWN"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class WheelspinStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._schema()

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(
          session_id TEXT PRIMARY KEY, requested_spins INTEGER NOT NULL,
          spin_type TEXT NOT NULL CHECK(spin_type IN ('SUPER','REGULAR')),
          dry_run INTEGER NOT NULL, stop_on_unknown INTEGER NOT NULL,
          started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
          completed_spins INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS spins(
          spin_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
          spin_number INTEGER NOT NULL, spin_type TEXT NOT NULL, started_at TEXT NOT NULL,
          reward_screen_at TEXT, completed_at TEXT, duration_seconds REAL,
          screen_path TEXT, slot_count INTEGER NOT NULL, credits_before INTEGER,
          credits_after INTEGER, credits_delta INTEGER, status TEXT NOT NULL,
          error TEXT, rewards_committed INTEGER NOT NULL DEFAULT 0,
          collect_sent INTEGER NOT NULL DEFAULT 0, UNIQUE(session_id, spin_number));
        CREATE TABLE IF NOT EXISTS rewards(
          reward_id INTEGER PRIMARY KEY AUTOINCREMENT, spin_id TEXT NOT NULL REFERENCES spins(spin_id),
          slot_index INTEGER NOT NULL, timestamp TEXT NOT NULL, reward_type TEXT NOT NULL,
          raw_ocr TEXT NOT NULL, normalized_text TEXT NOT NULL,
          classification_confidence REAL NOT NULL, rarity TEXT, card_color TEXT,
          credits_value INTEGER,
          year INTEGER, manufacturer TEXT, model TEXT, display_name TEXT, pi_class TEXT, pi INTEGER,
          forza_edition INTEGER, wheelspin_exclusive INTEGER, protected INTEGER, duplicate INTEGER,
          decision TEXT, decision_confidence REAL, action_attempted TEXT, action_verified INTEGER NOT NULL DEFAULT 0,
          sell_value_if_known INTEGER, full_screen_path TEXT NOT NULL, slot_crop_path TEXT NOT NULL,
          duplicate_dialog_path TEXT, association_confidence REAL,
          UNIQUE(spin_id, slot_index));
        CREATE TABLE IF NOT EXISTS events(
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, spin_id TEXT, reward_id INTEGER,
          event_type TEXT NOT NULL, timestamp TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_rewards_identity ON rewards(year,manufacturer,model);
        CREATE INDEX IF NOT EXISTS ix_events_spin ON events(spin_id,event_id);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(rewards)")}
        if "credits_value" not in columns:
            self.db.execute("ALTER TABLE rewards ADD COLUMN credits_value INTEGER")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def event(self, kind, spin_id=None, reward_id=None, **payload):
        self.db.execute("INSERT INTO events(spin_id,reward_id,event_type,timestamp,payload_json) VALUES(?,?,?,?,?)",
                        (spin_id, reward_id, kind, now(), json.dumps(payload, sort_keys=True)))

    def start_session(self, requested_spins, spin_type="SUPER", dry_run=True, stop_on_unknown=True, session_id=None):
        if spin_type not in {"SUPER", "REGULAR"} or not 1 <= int(requested_spins) <= 10000:
            raise ValueError("Wheelspin session needs 1–10,000 SUPER or REGULAR spins")
        identifier = session_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        self.db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (identifier, int(requested_spins), spin_type, int(bool(dry_run)), int(bool(stop_on_unknown)),
             now(), None, "RUNNING", 0, None))
        return identifier

    def start_spin(self, session_id, spin_number, spin_type):
        slots = 3 if spin_type == "SUPER" else 1
        spin_id = f"{session_id}:{int(spin_number):06d}"
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO spins(spin_id,session_id,spin_number,spin_type,started_at,slot_count,status) VALUES(?,?,?,?,?,?,?)",
                            (spin_id, session_id, int(spin_number), spin_type, now(), slots, "SPIN_STARTED"))
            self.event("SPIN_STARTED", spin_id, spin_number=int(spin_number), spin_type=spin_type)
        return spin_id

    def commit_rewards(self, spin_id, rewards, screen_path=None, reward_screen_at=None):
        spin = self.spin(spin_id)
        expected = spin["slot_count"]
        if len(rewards) != expected:
            raise ValueError(f"{spin['spin_type']} Wheelspin requires exactly {expected} reward records")
        if sorted(int(r["slot_index"]) for r in rewards) != list(range(1, expected + 1)):
            raise ValueError("Reward slots must be complete, unique and one-based")
        with self.transaction():
            for item in rewards:
                kind = item.get("reward_type", "UNKNOWN")
                if kind not in REWARD_TYPES:
                    raise ValueError(f"Unknown reward type {kind}")
                fields = dict(item)
                fields.setdefault("raw_ocr", "")
                fields.setdefault("normalized_text", "")
                fields.setdefault("classification_confidence", 0.0)
                fields.setdefault("full_screen_path", screen_path or "")
                fields.setdefault("slot_crop_path", "")
                columns = ["spin_id", "timestamp", *fields.keys()]
                values = [spin_id, now(), *[fields[key] for key in fields]]
                self.db.execute(f"INSERT INTO rewards({','.join(columns)}) VALUES({','.join('?' for _ in values)})", values)
                reward_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]
                self.event(f"REWARD_SLOT_{item['slot_index']}_RECORDED", spin_id, reward_id,
                           slot_index=item["slot_index"], reward_type=kind)
            stamp = reward_screen_at or now()
            self.db.execute("UPDATE spins SET rewards_committed=1,reward_screen_at=?,screen_path=?,status='REWARDS_COMMITTED' WHERE spin_id=?",
                            (stamp, screen_path, spin_id))
            self.event("REWARDS_COMMITTED", spin_id, slots=expected, screen_path=screen_path)

    def plan_decision(self, spin_id, reward_id, decision, confidence, duplicate_dialog_path=None):
        if decision not in {"SELL", "KEEP", "AUTO_ADDED", "UNKNOWN_DECISION"}:
            raise ValueError("Invalid Wheelspin decision")
        with self.transaction():
            self.db.execute("UPDATE rewards SET decision=?,decision_confidence=?,duplicate_dialog_path=? WHERE reward_id=? AND spin_id=?",
                            (decision, float(confidence), duplicate_dialog_path, reward_id, spin_id))
            self.event("DECISION_PLANNED", spin_id, reward_id, decision=decision, confidence=confidence)

    def associate_duplicate(self, spin_id, reward_id, identity, confidence, path):
        with self.transaction():
            self.db.execute("""UPDATE rewards SET reward_type='CAR',credits_value=NULL,
                duplicate=1,year=?,manufacturer=?,model=?,display_name=?,
                protected=?,wheelspin_exclusive=?,decision_confidence=?,association_confidence=?,duplicate_dialog_path=?
                WHERE spin_id=? AND reward_id=?""",
                (identity.get("year"), identity.get("manufacturer"), identity.get("model"),
                 identity.get("display_name"), identity.get("protected"), identity.get("wheelspin_exclusive"),
                 confidence, confidence, path, spin_id, reward_id))
            self.event("CAR_IDENTIFIED", spin_id, reward_id, confidence=confidence,
                       year=identity.get("year"), manufacturer=identity.get("manufacturer"),
                       model=identity.get("model"), protected=identity.get("protected"))

    def assert_action_allowed(self, spin_id, reward_id, action):
        spin = self.spin(spin_id)
        row = self.db.execute("SELECT * FROM rewards WHERE spin_id=? AND reward_id=?", (spin_id, reward_id)).fetchone()
        if spin["rewards_committed"] != 1 or row is None:
            raise AssertionError("reward screen and slots must be durably committed")
        if action == "SELL":
            if row["protected"] != 0:
                raise AssertionError("protected or unknown car may not be sold")
            # Independent destructive-action interlock. Recheck immutable
            # card OCR and native-dialog identity so a matcher regression
            # cannot sell a user-protected car.
            from .wheelspin_catalog import user_keep_match, lamborghini_candidate
            identity_text = " ".join(str(row[key] or "") for key in
                                     ("raw_ocr", "display_name", "manufacturer", "model"))
            if user_keep_match(identity_text):
                raise AssertionError("protected keep-list alias may not be sold")
            if lamborghini_candidate(identity_text):
                raise AssertionError("Lamborghini may not be sold while gold-card color is uncertain")
            other_cards = self.db.execute(
                "SELECT raw_ocr,protected FROM rewards WHERE spin_id=? AND reward_id<>? "
                "AND action_verified=0 AND reward_type NOT IN "
                "('CREDITS','CLOTHING','HORN','EMOTE','COSMETIC')",
                (spin_id, reward_id)).fetchall()
            if any(card["protected"] == 1 or
                   user_keep_match(card["raw_ocr"]) or
                   lamborghini_candidate(card["raw_ocr"])
                   for card in other_cards):
                raise AssertionError("unresolved protected card in this spin blocks Sell")
        if row["decision"] != action:
            raise AssertionError("decision must be committed before action")
        if row["action_verified"]:
            raise AssertionError("action already verified; never repeat it")
        if row["action_attempted"] is not None:
            raise AssertionError("ambiguous attempted action requires fresh screen detection")
        if row["decision_confidence"] is None or row["decision_confidence"] < .97:
            raise AssertionError("decision confidence below threshold")
        if action == "SELL":
            pass
        elif action == "KEEP":
            pass  # Add to Garage is non-destructive for every duplicate.
        else:
            raise AssertionError("only SELL or KEEP is an input action")

    def action_attempted(self, spin_id, reward_id, action):
        self.assert_action_allowed(spin_id, reward_id, action)
        with self.transaction():
            self.db.execute("UPDATE rewards SET action_attempted=? WHERE reward_id=?", (action, reward_id))
            self.event("ACTION_SENT", spin_id, reward_id, action=action)

    def action_verified(self, spin_id, reward_id, action):
        row = self.db.execute("SELECT action_attempted,action_verified FROM rewards WHERE reward_id=?", (reward_id,)).fetchone()
        assert row and row["action_attempted"] == action and not row["action_verified"]
        with self.transaction():
            self.db.execute("UPDATE rewards SET action_verified=1 WHERE reward_id=?", (reward_id,))
            self.event("ACTION_VERIFIED", spin_id, reward_id, action=action)

    def clear_unaccepted_action(self, spin_id, reward_id, action, evidence_path):
        row = self.db.execute("SELECT action_attempted,action_verified FROM rewards WHERE reward_id=? AND spin_id=?",
                              (reward_id, spin_id)).fetchone()
        assert row and row["action_attempted"] == action and not row["action_verified"]
        with self.transaction():
            self.db.execute("UPDATE rewards SET action_attempted=NULL WHERE reward_id=?", (reward_id,))
            self.event("ACTION_NOT_ACCEPTED", spin_id, reward_id, action=action,
                       evidence_path=evidence_path)

    def set_sell_value(self, spin_id, reward_id, value):
        with self.transaction():
            self.db.execute("UPDATE rewards SET sell_value_if_known=? WHERE reward_id=? AND spin_id=?",
                            (int(value), reward_id, spin_id))
            self.event("SELL_VALUE_RECORDED", spin_id, reward_id, credits=int(value))

    def collect_sent(self, spin_id):
        spin = self.spin(spin_id)
        assert spin["rewards_committed"] == 1, "COLLECT requires committed reward evidence"
        assert spin["collect_sent"] == 0, "COLLECT was already sent; inspect the current screen"
        with self.transaction():
            self.db.execute("UPDATE spins SET collect_sent=1,status='COLLECT_SENT' WHERE spin_id=?", (spin_id,))
            self.event("COLLECT_SENT", spin_id)

    def complete_spin(self, spin_id):
        with self.transaction():
            self.db.execute("""UPDATE spins SET status='COMPLETE',completed_at=?,
                duration_seconds=(julianday(?) - julianday(started_at))*86400 WHERE spin_id=?""",
                (now(), now(), spin_id))
            self.event("SPIN_COMPLETE", spin_id)
            session_id = self.spin(spin_id)["session_id"]
            completed = self.db.execute("SELECT COUNT(*) FROM spins WHERE session_id=? AND status='COMPLETE'", (session_id,)).fetchone()[0]
            requested = self.db.execute("SELECT requested_spins FROM sessions WHERE session_id=?", (session_id,)).fetchone()[0]
            self.db.execute("UPDATE sessions SET completed_spins=?,status=?,completed_at=CASE WHEN ? >= ? THEN ? ELSE completed_at END WHERE session_id=?",
                            (completed, "COMPLETE" if completed >= requested else "RUNNING",
                             completed, requested, now(), session_id))

    def session(self, session_id):
        row = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def latest_session(self):
        row = self.db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def resumable_session(self, requested_spins, spin_type):
        row = self.db.execute("""SELECT * FROM sessions WHERE status='RUNNING' AND requested_spins=? AND spin_type=?
            ORDER BY started_at DESC LIMIT 1""", (int(requested_spins), spin_type)).fetchone()
        return dict(row) if row else None

    def current_spin(self, session_id):
        row = self.db.execute("SELECT * FROM spins WHERE session_id=? AND status!='COMPLETE' ORDER BY spin_number DESC LIMIT 1", (session_id,)).fetchone()
        return dict(row) if row else None

    def spin(self, spin_id):
        row = self.db.execute("SELECT * FROM spins WHERE spin_id=?", (spin_id,)).fetchone()
        if row is None:
            raise KeyError(spin_id)
        return dict(row)

    def rewards(self, spin_id):
        return [dict(row) for row in self.db.execute("SELECT * FROM rewards WHERE spin_id=? ORDER BY slot_index", (spin_id,))]

    def latest_pending_duplicate_spin(self, session_id):
        row = self.db.execute("""SELECT s.* FROM spins s WHERE s.session_id=? AND s.collect_sent=1
          AND EXISTS(SELECT 1 FROM rewards r WHERE r.spin_id=s.spin_id AND r.reward_type='CAR'
                     AND r.duplicate IS NULL) ORDER BY s.spin_number DESC LIMIT 1""",
          (session_id,)).fetchone()
        return dict(row) if row else None

    def global_stats(self):
        row = self.db.execute("""SELECT COUNT(DISTINCT CASE WHEN s.spin_type='SUPER' AND s.status='COMPLETE' THEN s.spin_id END) super_spins,
          COUNT(DISTINCT CASE WHEN s.spin_type='REGULAR' AND s.status='COMPLETE' THEN s.spin_id END) regular_spins,
          COUNT(r.reward_id) reward_slots, SUM(r.reward_type='CAR') car_rewards,
          SUM(COALESCE(r.duplicate,0)) duplicate_cars, SUM(COALESCE(r.protected,0)) protected_exclusive_pulls,
          SUM(r.protected=1 AND r.decision='SELL' AND r.action_verified=1) protected_sold,
          SUM(r.protected=1 AND r.decision='KEEP' AND r.action_verified=1) protected_retained,
          SUM(r.decision='SELL' AND r.action_verified=1) cars_sold,
          SUM(r.decision='KEEP' AND r.action_verified=1) cars_retained,
          SUM(CASE WHEN r.decision='SELL' AND r.action_verified=1 THEN COALESCE(r.sell_value_if_known,0) ELSE 0 END) sell_cr
          FROM spins s LEFT JOIN rewards r ON r.spin_id=s.spin_id""").fetchone()
        return {key: int(value or 0) for key, value in dict(row).items()}

    def export(self, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        queries = {
            "sessions.csv": "SELECT * FROM sessions ORDER BY started_at",
            "spins.csv": "SELECT * FROM spins ORDER BY started_at",
            "rewards.csv": "SELECT * FROM rewards ORDER BY reward_id",
            "car_pulls.csv": "SELECT * FROM rewards WHERE reward_type='CAR' ORDER BY reward_id",
        }
        for name, query in queries.items():
            rows = self.db.execute(query).fetchall()
            with (folder/name).open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                if rows:
                    writer.writerow(rows[0].keys())
                    writer.writerows(rows)
        from .wheelspin_stats import exclusive_rows
        rows = exclusive_rows(self)
        with (folder/"exclusive_summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        return folder


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("runs/wheelspin_lab.sqlite"))
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    store = WheelspinStore(args.db)
    if args.export:
        print(store.export(args.export).resolve())
    else:
        print(json.dumps(store.global_stats(), indent=2))


if __name__ == "__main__":
    main()
