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
        if sample is None or sample.quality != "good":
            self.pending.pop(key, None)
            return
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
                self.active[key] = self.repository.enter(alarm, sample.value, wall)
            else:
                self.repository.returned(self.active.pop(key), wall)
            self.pending.pop(key, None)

    def tick(self, monotonic, wall):
        for key in list(self.pending):
            self.evaluate(self.definitions[key], monotonic, wall)


def state(row):
    if row["returned_at"] is None:
        return tr("Activa · pendiente ACK") if row["ack_required"] and row["ack_at"] is None else tr("Activa")
    return tr("Retornada · pendiente ACK") if row["ack_required"] and row["ack_at"] is None else tr("Cerrada")
