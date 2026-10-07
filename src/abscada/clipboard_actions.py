"""Copy, cut and paste of canvas elements, also between screens, faceplates and Studio windows.

The system clipboard carries the elements and the configuration of the viewers they own, so a
pasted trend gets its own copy of the curves.
"""
import copy
import json
import uuid

from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication
from .i18n import tr

MIME = "application/x-abscada-elements"


class ClipboardActions:
    """Mixin for Studio's Window."""

    def copy_elements(self):
        elements = [copy.deepcopy(item.element) for item in self.scene.selectedItems()]
        if not elements:
            return False
        viewers = {}
        from .screen_tree import VIEWERS
        for element in elements:
            if element["kind"] in VIEWERS:
                views = getattr(self.project, VIEWERS[element["kind"]])
                if element.get("view") in views:
                    viewers[f'{element["kind"]}:{element["view"]}'] = copy.deepcopy(views[element["view"]])
        payload = json.dumps(dict(elements=elements, viewers=viewers,
                                  source=f"{self.document_kind}:{self.document_name}"), ensure_ascii=False)
        data = QMimeData()
        data.setData(MIME, payload.encode("utf-8"))
        data.setText(payload)
        QApplication.clipboard().setMimeData(data)
        self.statusBar().showMessage(tr("{len} elemento(s) copiado(s)", len=len(elements)), 3000)
        return True

    def cut_elements(self):
        if self.editable() and self.copy_elements():
            self.delete_element()

    def paste_elements(self):
        if not self.editable():
            return
        data = QApplication.clipboard().mimeData()
        if data is None or not data.hasFormat(MIME):
            self.statusBar().showMessage(tr("No hay elementos copiados"), 3000)
            return
        try:
            payload = json.loads(bytes(data.data(MIME)).decode("utf-8"))
        except ValueError:
            return
        same_document = payload.get("source") == f"{self.document_kind}:{self.document_name}"
        elements, groups = [], {}
        for element in payload.get("elements", []):
            element = dict(element)
            element["id"] = element["kind"] + "_" + uuid.uuid4().hex[:6]
            if same_document:
                element["x"] += 20
                element["y"] += 20
                if "points" in element:
                    element["points"] = [[x + 20, y + 20] for x, y in element["points"]]
            if element.get("group"):
                element["group"] = groups.setdefault(element["group"], "grupo_" + uuid.uuid4().hex[:6])
            elements.append(element)
        if not elements:
            return

        def paste():
            from .screen_tree import VIEWERS, new_view_id
            for element in elements:
                if element["kind"] in VIEWERS:
                    config = payload.get("viewers", {}).get(f'{element["kind"]}:{element.get("view")}')
                    if config is not None:
                        view = new_view_id(self.project, element["kind"], element["id"])
                        getattr(self.project, VIEWERS[element["kind"]])[view] = copy.deepcopy(config)
                        element["view"] = view
            self.document()["elements"].extend(elements)
        if self.mutate(paste, selected_ids=[e["id"] for e in elements]):
            self.statusBar().showMessage(tr("{len} elemento(s) pegado(s)", len=len(elements)), 3000)
