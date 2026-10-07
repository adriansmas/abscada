"""Validation for screen composition and scoped navigation (no Qt)."""


def containers(document):
    return [e for e in document['elements'] if e['kind'] == 'screen_container']


def validate_layouts(project):
    names = {e['id'] for doc in project.screens.values() for e in containers(doc)}
    if '__window__' in names:
        raise ValueError('Nombre de contenedor reservado: __window__')
    for doc in project.faceplates.values():
        if containers(doc):
            raise ValueError('Los contenedores se colocan en pantallas o layouts, no en objetos de librería')
    for name, doc in project.screens.items():
        if not isinstance(doc.get('layout', False), bool):
            raise ValueError('La propiedad layout debe ser booleana')
        for element in containers(doc):
            target = element.get('screen', '')
            if target not in project.screens:
                raise ValueError(f'{name}: pantalla del contenedor inexistente')
            if target == name or containers(project.screens[target]):
                raise ValueError('Un contenedor aloja una pantalla sin otros contenedores')
    for doc in list(project.screens.values()) + list(project.faceplates.values()):
        for element in doc['elements']:
            if element['kind'] == 'button' and element.get('action') == 'screen':
                target = element.get('target_container', '')
                if not isinstance(target, str) or target not in names | {'', '__window__'}:
                    raise ValueError('Contenedor de navegación inexistente')
                if target not in {'', '__window__'} and containers(project.screens[element['screen']]):
                    raise ValueError('No se puede abrir un layout dentro de un contenedor')
