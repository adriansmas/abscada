"""Alarm state machine. Acknowledgement belongs to occurrences, not PLC commands."""
import time
from .i18n import tr


def condition(alarm, value, active=False):
    op = alarm["condition"]
    threshold = alarm.get("threshold", 0)
    band = alarm.get("hysteresis", 0) if active else 0
    if op == "true":
        return value is True
    if op == "false":
        return value is False
    if op == "high":
        return value >= threshold-band
    if op == "low":
        return value <= threshold+band
    if op == "equal":
        return value == threshold
    return value != threshold


class AlarmEngine:
    def __init__(self, definitions, repository):
        self.definitions = {a["id"]: a for a in definitions if a.get("enabled", True)}
        self.repository = repository
        self.active = {}
        for row in repository.active():
            if row['alarm_id'] in self.definitions:
                self.active[row['alarm_id']] = row['id']
            else:
                now = time.time()
                repository.connection.execute('UPDATE alarm_instances SET returned_at=? WHERE id=?', (now,row['id']))
                repository.event(row['id'], 'disabled', now, comment='Definición retirada o deshabilitada')
        # Occurrences still waiting for an acknowledgement (active or returned).
        self.unacknowledged = {row[0] for row in repository.connection.execute(
            "SELECT id FROM alarm_instances WHERE ack_required=1 AND ack_at IS NULL")}
        # Rises with every entry, return or acknowledgement.
        self.revision = 0
        self.samples, self.pending = {}, {}
        self.by_tag = {}
        for alarm in self.definitions.values():
            self.by_tag.setdefault(alarm["tag"], []).append(alarm)

    def observe(self, tag, sample, monotonic, wall):
        self.samples[tag] = sample
        for alarm in self.by_tag.get(tag, []):
            self.evaluate(alarm, monotonic, wall)

    def evaluate(self, alarm, monotonic, wall):
        key = alarm["id"]
        sample = self.samples.get(alarm["tag"])
        if alarm["condition"] == "bad_quality":
            # The only condition about the data itself: no valid value, for whatever reason.
            if sample is None:
                return
            active = key in self.active
            desired = sample.quality != "good"
        elif sample is None or sample.quality != "good":
            # Losing the data is not a return of the process: keep the state, cancel delays.
            self.pending.pop(key, None)
            return
        else:
            active = key in self.active
            desired = condition(alarm, sample.value, active)
        if desired == active:
            self.pending.pop(key, None)
            return
        pending = self.pending.get(key)
        if pending is None or pending[0] != desired:
            delay = alarm.get("on_delay_ms" if desired else "off_delay_ms", 0)/1000
            self.pending[key] = (desired, monotonic+delay)
        if monotonic >= self.pending[key][1]:
            if desired:
                # A delayed entry happens when its delay ends, not when the value changed.
                now = wall if alarm.get("on_delay_ms", 0) <= 0 else time.time()
                self.active[key] = self.repository.enter(alarm, sample.value, now)
                if alarm.get("ack_required", True):
                    self.unacknowledged.add(self.active[key])
            else:
                now = wall if alarm.get("off_delay_ms", 0) <= 0 else time.time()
                self.repository.returned(self.active.pop(key), now)
            self.pending.pop(key, None)
            self.revision += 1

    def tick(self, monotonic, wall):
        for key in list(self.pending):
            self.evaluate(self.definitions[key], monotonic, wall)

    def next_deadline(self):
        """Monotonic times at which a delayed entry or return is due (empty without delays)."""
        return [deadline for _, deadline in self.pending.values()]

    def acknowledged(self, instances):
        self.unacknowledged.difference_update(instances)
        self.revision += 1

    def summary(self):
        return dict(active=len(self.active), unacknowledged=len(self.unacknowledged))


def state(row):
    if row["returned_at"] is None:
        return tr("Activa · pendiente ACK") if row["ack_required"] and row["ack_at"] is None else tr("Activa")
    return tr("Retornada · pendiente ACK") if row["ack_required"] and row["ack_at"] is None else tr("Cerrada")
