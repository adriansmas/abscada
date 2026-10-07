"""Recording files own membership and cadence, independently of screen controls."""
import re
from datetime import datetime, timezone, timedelta
from .i18n import tr


def files(project):
    if "files" in project.historian:
        return project.historian["files"]
    # Compatibility with projects created before recording files existed.
    groups = {}
    for tag in project.historian.get("tags", []):
        cycle = tag.get("interval_ms", 1000)
        key = "legacy_" + str(cycle).replace(".", "_")
        groups.setdefault(key, dict(id=key, name=f"Registro {cycle} ms", interval_ms=cycle, variables=[]))["variables"].append(tag["tag"])
    return list(groups.values())


def migrate(project):
    if "files" not in project.historian:
        project.historian["files"] = files(project)
        project.historian.pop("tags", None)


def assignment(project, tag):
    return next((f["id"] for f in files(project) if tag in f["variables"]), "")


def assign(project, tag, file_id):
    migrate(project)
    if file_id and file_id not in {f["id"] for f in files(project)}:
        raise ValueError(tr("Fichero de registro inexistente"))
    if tag not in project.tags():
        raise ValueError(tr("Variable inexistente"))
    for file in files(project):
        file["variables"] = [v for v in file["variables"] if v != tag]
        if file["id"] == file_id:
            file["variables"].append(tag)


def path(project, identifier, timestamp=None):
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
        raise ValueError(tr("El ID del fichero solo admite letras, números, _ y -"))
    if identifier.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError(tr("Nombre de fichero reservado"))
    directory = project.root / "runtime" / "records" / identifier
    if timestamp is None:
        return directory
    day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    return directory / (day + ".sqlite3")


class DailyArchive:
    """One writer per configured file; rotate only at UTC calendar boundaries."""
    def __init__(self, project, identifier):
        self.project, self.identifier = project, identifier
        self.repository = None

    def sample(self, tag, sample, timestamp):
        from .storage import Repository
        target = path(self.project, self.identifier, timestamp)
        if self.repository is None or self.repository.path != target:
            self.close()
            if not target.exists():
                # Publish only after the schema exists, so readers at midnight
                # cannot observe an empty SQLite database during initialization.
                temporary = target.with_suffix(".initializing")
                initialized = Repository(temporary)
                initialized.close()
                temporary.replace(target)
            self.repository = Repository(target)
        self.repository.sample(tag, sample, timestamp)

    def commit(self):
        if self.repository:
            self.repository.connection.commit()

    def close(self):
        if self.repository:
            try:
                self.commit()
            finally:
                self.repository.close()
                self.repository = None

    def prune(self, timestamp, retention_days):
        cutoff = datetime.fromtimestamp(timestamp, timezone.utc) - timedelta(days=retention_days)
        for target in path(self.project, self.identifier).glob("*.sqlite3"):
            try:
                day = datetime.strptime(target.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if day + timedelta(days=1) > cutoff or (self.repository and self.repository.path == target):
                continue
            try:
                target.unlink()
                for suffix in ("-wal", "-shm"):
                    target.with_name(target.name + suffix).unlink(missing_ok=True)
            except OSError:
                # A historical query or backup can hold the file open on Windows.
                # Retention will retry on the next pass.
                continue


def logs(project):
    if "files" not in project.historian:
        return [dict(item, file_id="") for item in project.historian.get("tags", [])]
    return [dict(tag=tag, interval_ms=file["interval_ms"], file_id=file["id"], mode="cyclic")
            for file in files(project) for tag in file["variables"]]
