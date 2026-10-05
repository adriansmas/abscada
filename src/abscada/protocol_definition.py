"""Protocol-owned configuration schemas, independent of Qt and network libraries."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: object
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple = ()  # (stored value, display label, compatible logical types)
    kinds: tuple = ()

    def options(self, kind=None):
        return [(value, label) for value, label, kinds in self.choices
                if kind is None or not kinds or kind in kinds]

    def validate(self, value, kind=None):
        if isinstance(self.default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.label}: se esperaba un entero")
            if not self.minimum <= value <= self.maximum:
                raise ValueError(f"{self.label}: fuera de rango")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self.label}: valor vacío o inválido")
        if self.choices and value not in [v for v, _ in self.options(kind)]:
            raise ValueError(f"{self.label}: valor incompatible con {kind or 'el protocolo'}")


@dataclass(frozen=True)
class ProtocolDefinition:
    label: str
    connection_fields: tuple[Field, ...]
    binding_fields: tuple[Field, ...]
    normalize: Callable
    check_binding: Callable
    describe: Callable
    version: int = 1

    def fields_for(self, kind):
        return tuple(f for f in self.binding_fields if not f.kinds or kind in f.kinds)

    def supports_type(self, kind):
        return all(not f.choices or bool(f.options(kind)) for f in self.fields_for(kind))

    def validate_connection(self, config):
        for field in self.connection_fields:
            field.validate(config.get(field.key, field.default))

    def validate_binding(self, address, kind, writable):
        if not self.supports_type(kind):
            raise ValueError(f"{self.label}: tipo SCADA no soportado: {kind}")
        address = self.normalize(address, kind)
        fields = self.fields_for(kind)
        if not isinstance(address, dict) or set(address) - {f.key for f in fields}:
            raise ValueError("Campos de enlace desconocidos o incompatibles")
        for field in fields:
            options = field.options(kind)
            default = field.default if not options or field.default in [v for v, _ in options] else options[0][0]
            address.setdefault(field.key, default)
            field.validate(address.get(field.key, field.default), kind)
        self.check_binding(address, kind, writable)
        return address
