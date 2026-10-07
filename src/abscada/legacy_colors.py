"""Convert legacy shared colors to explicit HEX values when opening old projects."""
from .dynamics import COLOR_KEYS, validate_color
from .i18n import tr


def migrate(project):
    if 'palette' not in project.manifest:
        return
    colors = project.manifest['palette']
    if not isinstance(colors, dict):
        raise ValueError(tr('Paleta inválida'))
    for value in colors.values():
        validate_color(value)

    def convert(value, lamp=False):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if (key in COLOR_KEYS | {'background'} or lamp) and isinstance(item, str) and item.startswith('@'):
                if item[1:] not in colors:
                    raise ValueError(tr('Color de paleta inexistente: {value}', value=item))
                result[key] = colors[item[1:]]
            else:
                result[key] = convert(item, key == 'lamp_colors')
        return result

    project.screens = convert(project.screens)
    project.faceplates = convert(project.faceplates)
    del project.manifest['palette']
