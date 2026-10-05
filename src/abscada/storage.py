"""SQLite operational repository. One owner writes; queries use separate connections."""
import json
import sqlite3
import heapq
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples(
 id INTEGER PRIMARY KEY, tag TEXT NOT NULL, recorded_at REAL NOT NULL,
 source_at REAL NOT NULL, value TEXT NOT NULL, numeric REAL, quality TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sample_tag_time ON samples(tag,recorded_at);
CREATE TABLE IF NOT EXISTS recording_sources(
 tag TEXT NOT NULL, file_id TEXT NOT NULL, PRIMARY KEY(tag,file_id));
CREATE TABLE IF NOT EXISTS alarm_instances(
 id INTEGER PRIMARY KEY, alarm_id TEXT NOT NULL, message TEXT NOT NULL,
 category TEXT NOT NULL, priority INTEGER NOT NULL, tag TEXT NOT NULL,
 entered_at REAL NOT NULL, returned_at REAL, ack_at REAL, ack_by TEXT,
 ack_required INTEGER NOT NULL, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS alarm_time ON alarm_instances(entered_at);
CREATE INDEX IF NOT EXISTS alarm_pending ON alarm_instances(returned_at,ack_at);
CREATE TABLE IF NOT EXISTS alarm_events(
 id INTEGER PRIMARY KEY, instance_id INTEGER NOT NULL REFERENCES alarm_instances(id),
 event TEXT NOT NULL, timestamp REAL NOT NULL, actor TEXT NOT NULL, comment TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS alarm_event_time ON alarm_events(timestamp);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL);
PRAGMA user_version=1;
"""


def database_path(project):
    return project.root / "runtime" / "scada.sqlite3"


class ProjectSampleReader:
    """Read current and retired recording files; retain access to legacy history."""
    def __init__(self, project):
        self.project = project

    def _read(self, method, tag, start, end, limit):
        paths = [database_path(self.project)]
        directory = self.project.root / "runtime" / "records"
        paths.extend(sorted(directory.glob("*.sqlite3")))
        first = datetime.fromtimestamp(start, timezone.utc).date().isoformat()
        last = datetime.fromtimestamp(end, timezone.utc).date().isoformat()
        catalog = ArchiveReader(database_path(self.project))
        has_catalog = catalog.query("SELECT name FROM sqlite_master WHERE type='table' AND name='recording_sources'")
        sources = catalog.query("SELECT tag,file_id FROM recording_sources") if has_catalog else []
        known = {s["file_id"] for s in sources}
        relevant = {s["file_id"] for s in sources if s["tag"] == tag}
        # Unknown directories are legacy/unmanaged archives: retain access to them.
        paths.extend(p for p in sorted(directory.glob("*/*.sqlite3"))
                     if first <= p.stem <= last and (p.parent.name in relevant or p.parent.name not in known))
        rows = []
        budget = max(20, limit // max(1, len(paths)))
        for path in paths:
            reader = ArchiveReader(path)
            rows.extend(reader.samples(tag, start, end, budget) if method == "samples" else reader.raw_samples(tag, start, end))
            if method == "raw_samples" and len(rows) > limit:
                # Visit every archive: legacy/current files may overlap in time.
                rows = heapq.nsmallest(limit, rows, key=lambda row: row['recorded_at'])
        rows.sort(key=lambda row: row["recorded_at"])
        if method == "samples" and len(rows) > limit:
            buckets = {}
            count = max(1, limit // 5)
            for row in rows:
                index = min(count-1, int((row["recorded_at"]-start)/max(end-start, 0.001)*count))
                buckets.setdefault(index, []).append(row)
            reduced = []
            for bucket in buckets.values():
                choices = [bucket[0], bucket[-1]]
                numeric = [r for r in bucket if r["numeric"] is not None and r["quality"] == "good"]
                if numeric:
                    choices.extend((min(numeric, key=lambda r:r["numeric"]), max(numeric, key=lambda r:r["numeric"])))
                bad = next((r for r in bucket if r["quality"] != "good"), None)
                if bad:
                    choices.append(bad)
                unique = {r["recorded_at"]: r for r in choices}
                reduced.extend(unique[k] for k in sorted(unique))
            rows = reduced
        return rows

    def samples(self, tag, start, end, limit=5000):
        return self._read("samples", tag, start, end, limit)

    def raw_samples(self, tag, start, end, limit=100001):
        return self._read("raw_samples", tag, start, end, limit)


class RuntimeLease:
    """Cross-process advisory lock, automatically released after a crash."""
    def __init__(self, path):
        self.path, self.file = Path(path), None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b"0"); self.file.flush()
        self.file.seek(0)
        try:
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close(); self.file = None
            raise RuntimeError("Ya existe un runtime registrando este proyecto") from exc

    def close(self):
        if self.file:
            self.file.close(); self.file = None


class Repository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.connection.close()
            raise ValueError("Versión de base de datos no soportada")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)

    def close(self):
        self.connection.close()

    def sample(self, tag, sample, now):
        value = sample.value
        numeric = float(value) if isinstance(value, (bool, int, float)) else None
        self.connection.execute("INSERT INTO samples(tag,recorded_at,source_at,value,numeric,quality) VALUES(?,?,?,?,?,?)",
            (tag, now, sample.timestamp, json.dumps(value, ensure_ascii=False), numeric, sample.quality))

    def enter(self, alarm, value, now):
        cursor = self.connection.execute("""INSERT INTO alarm_instances
          (alarm_id,message,category,priority,tag,entered_at,ack_required,value)
          VALUES(?,?,?,?,?,?,?,?)""", (alarm["id"], alarm["message"], alarm["category"], alarm.get("priority", 500),
            alarm["tag"], now, alarm.get("ack_required", True), json.dumps(value)))
        self.event(cursor.lastrowid, "incoming", now)
        return cursor.lastrowid

    def event(self, instance, event, now, actor="", comment=""):
        self.connection.execute("INSERT INTO alarm_events(instance_id,event,timestamp,actor,comment) VALUES(?,?,?,?,?)",
                                (instance, event, now, actor, comment))

    def returned(self, instance, now):
        self.connection.execute("UPDATE alarm_instances SET returned_at=? WHERE id=? AND returned_at IS NULL", (now, instance))
        self.event(instance, "outgoing", now)

    def acknowledge(self, instances, now, actor, comment=""):
        if not actor.strip():
            raise ValueError("El reconocimiento necesita un operador")
        changed = 0
        for instance in set(instances):
            cursor = self.connection.execute("UPDATE alarm_instances SET ack_at=?,ack_by=? WHERE id=? AND ack_at IS NULL AND ack_required=1", (now, actor, instance))
            if cursor.rowcount:
                self.event(instance, "ack", now, actor, comment); changed += 1
        return changed

    def active(self):
        return [dict(row) for row in self.connection.execute("SELECT * FROM alarm_instances WHERE returned_at IS NULL")]

    def audit(self, now, action, target, actor="", detail=""):
        self.connection.execute("INSERT INTO audit(timestamp,action,target,actor,detail) VALUES(?,?,?,?,?)", (now, action, target, actor, detail))

    def prune(self, now, sample_days, alarm_days):
        self.connection.execute("DELETE FROM samples WHERE recorded_at<?", (now-sample_days*86400,))
        cutoff = now-alarm_days*86400
        eligible = "returned_at<? AND (ack_required=0 OR ack_at IS NOT NULL)"
        self.connection.execute(f"DELETE FROM alarm_events WHERE instance_id IN (SELECT id FROM alarm_instances WHERE {eligible})", (cutoff,))
        self.connection.execute(f"DELETE FROM alarm_instances WHERE {eligible}", (cutoff,))
        self.connection.execute("DELETE FROM audit WHERE timestamp<?", (cutoff,))


class ArchiveReader:
    def __init__(self, path):
        self.path = Path(path)

    def query(self, sql, values=()):
        if not self.path.exists():
            return []
        try:
            connection = sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True, timeout=2)
        except sqlite3.OperationalError:
            if not self.path.exists():
                return []
            raise
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, values)]
        finally:
            connection.close()

    def backup(self, destination):
        """Use SQLite's online backup API: copying the .db file would miss WAL data."""
        import os
        import tempfile
        target = Path(destination).resolve()
        if target == self.path.resolve() or not self.path.exists():
            raise ValueError("Selecciona otro archivo; el archivo operativo debe existir")
        handle, temporary = tempfile.mkstemp(suffix=".sqlite3", dir=target.parent)
        os.close(handle)
        source, output = None, None
        try:
            source = sqlite3.connect(self.path.as_uri()+"?mode=ro", uri=True, timeout=5)
            output = sqlite3.connect(temporary)
            source.backup(output)
            output.close(); output = None
            os.replace(temporary, target)
        finally:
            if source:
                source.close()
            if output:
                output.close()
            Path(temporary).unlink(missing_ok=True)

    def alarms(self, mode="pending", categories=(), min_priority=1, start=0, end=1e20, limit=2000):
        conditions = {"pending": "(a.returned_at IS NULL OR (a.ack_required=1 AND a.ack_at IS NULL))",
                      "active": "a.returned_at IS NULL", "history": "1=1", "events": "1=1"}
        condition = conditions[mode] + " AND a.priority>=?"
        args = [min_priority]
        if categories:
            condition += " AND a.category IN ("+",".join("?" for _ in categories)+")"
            args.extend(categories)
        if mode == "events":
            sql = "SELECT a.*,e.id AS event_id,e.event,e.timestamp,e.actor,e.comment FROM alarm_events e JOIN alarm_instances a ON a.id=e.instance_id WHERE "
            condition += " AND e.timestamp BETWEEN ? AND ?"
            order = "e.timestamp DESC,e.id DESC"
        else:
            sql = "SELECT a.* FROM alarm_instances a WHERE "
            if mode == "history":
                condition += " AND a.entered_at BETWEEN ? AND ?"
            else:
                start, end = 0, 1e20
                condition += " AND a.entered_at BETWEEN ? AND ?"
            order = "a.priority DESC,a.entered_at DESC" if mode != "history" else "a.entered_at DESC,a.id DESC"
        args.extend([start, end, limit])
        return self.query(sql+condition+" ORDER BY "+order+" LIMIT ?", args)

    def samples(self, tag, start, end, limit=5000):
        # Bucket extrema retain spikes while bounding the amount sent to Qt.
        counts = self.query("SELECT count(*) AS n FROM samples WHERE tag=? AND recorded_at BETWEEN ? AND ?", (tag, start, end))
        count = counts[0]["n"] if counts else 0
        if count <= limit:
            return self.query("SELECT * FROM samples WHERE tag=? AND recorded_at BETWEEN ? AND ? ORDER BY recorded_at,id", (tag, start, end))
        width = max((end-start)/max(1,limit//5-1), 0.001)
        return self.query("""WITH bucket AS (
          SELECT *,CAST((recorded_at-?)/? AS INTEGER) AS b FROM samples
          WHERE tag=? AND recorded_at BETWEEN ? AND ?), ranked AS (
          SELECT *,row_number() OVER(PARTITION BY b ORDER BY recorded_at,id) AS first,
            row_number() OVER(PARTITION BY b ORDER BY recorded_at DESC,id DESC) AS last,
            row_number() OVER(PARTITION BY b ORDER BY numeric,id) AS low,
            row_number() OVER(PARTITION BY b ORDER BY numeric DESC,id) AS high,
            row_number() OVER(PARTITION BY b ORDER BY (quality='good'),id) AS quality_rank FROM bucket)
          SELECT * FROM ranked WHERE first=1 OR last=1 OR low=1 OR high=1 OR (quality_rank=1 AND quality!='good')
          ORDER BY recorded_at,id""", (start, width, tag, start, end))

    def raw_samples(self, tag, start, end):
        return self.query("SELECT tag,recorded_at,source_at,value,quality FROM samples WHERE tag=? AND recorded_at BETWEEN ? AND ? ORDER BY recorded_at,id LIMIT 100001", (tag, start, end))
