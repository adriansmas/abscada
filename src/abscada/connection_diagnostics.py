"""Explicit read-only engineering probes, separate from acquisition workers."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPushButton
from .connectors import REGISTRY, create, definition, binding_summary  # noqa: F401  (REGISTRY: tests patch it here)

PROBES=ThreadPoolExecutor(max_workers=2,thread_name_prefix='abscada-probe')


def probe(config,binding,kind,writable,project_root=None):
    if not config: return 'Variable local; no hay equipo que consultar'
    adapter=None
    try:
        definition(config['protocol']).validate_connection(config)
        if binding: definition(config['protocol']).validate_binding(binding['address'],kind,writable)
        adapter=create(config,project_root)
        try: adapter.connect()
        except Exception as exc: return f'Equipo inaccesible o conexión rechazada. Detalle: {exc}'
        if not binding: return 'Conexión establecida. No se han enviado escrituras.'
        try: value=adapter.read(binding['address'],kind)
        except Exception as exc: return f'Conexión establecida; no se pudo leer la dirección. Detalle: {exc}'
        return f"Valor: {value} · Calidad: buena · {datetime.now():%H:%M:%S}\n{'Lectura y escritura' if writable else 'Solo lectura'} · {binding_summary(binding,[config],kind)}"
    except Exception as exc: return f'Configuración inválida: {exc}'
    finally:
        if adapter:
            try: adapter.close()
            except Exception: pass


def add_diagnostic(dialog,layout,configuration,studio,tag_name=None):
    button=QPushButton('Leer variable (configuración de Studio)' if tag_name else 'Probar conexión (configuración de Studio)')
    result=QLabel(); result.setWordWrap(True); result.setTextInteractionFlags(result.textInteractionFlags())
    layout.addWidget(button); layout.addWidget(result)
    pending=None; timer=QTimer(dialog)
    def start():
        nonlocal pending
        try: args=copy.deepcopy(configuration())
        except Exception as exc: result.setText(str(exc)); return
        button.setEnabled(False); result.setText('Consultando…')
        pending=PROBES.submit(probe,*args,project_root=studio.project.root); timer.start(80)
    def poll():
        if pending and pending.done():
            timer.stop(); button.setEnabled(True)
            try: result.setText(pending.result())
            except Exception as exc: result.setText(f'No se pudo completar la prueba: {exc}')
    button.clicked.connect(start); timer.timeout.connect(poll)
    if tag_name and studio.runtime:
        sample=studio.runtime.snapshot().get(tag_name)
        if sample:
            quality={'good':'buena','bad':'mala','uncertain':'incierta'}.get(sample.quality,sample.quality)
            live=QLabel(f'Runtime activo: {sample.value} · Calidad {quality} · {datetime.fromtimestamp(sample.timestamp):%H:%M:%S}')
            live.setWordWrap(True); layout.addWidget(live)
