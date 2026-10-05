"""Studio drawing commands, all recorded through the project's undo boundary."""
import uuid
import copy
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QListWidgetItem,QMenu,QInputDialog
from .drawing import set_points


class DrawingActions:
    def snap_position(self, position):
        if not self.snap_action.isChecked():
            return position
        step = self.document().get("grid_size",10)
        return QPointF(round(position.x()/step)*step, round(position.y()/step)*step)

    def set_document_snap(self, checked):
        if self.document().get("snap_to_grid",True) != checked:
            previous = copy.deepcopy(self.project)
            self.document()["snap_to_grid"] = checked
            self.record_history(previous); self.mark_dirty()
            self.screen_properties.refresh()

    def insert_path(self, kind, points):
        element = dict(id=kind+"_"+uuid.uuid4().hex[:6],kind=kind,
            stroke_width=12 if kind=="pipe" else 2,stroke_color="#75879a" if kind=="pipe" else "#334155")
        set_points(element,points)
        self.mutate(lambda: self.document()["elements"].append(element),selected_ids=[element["id"]])

    def refresh_layers(self):
        if not hasattr(self,"layers"):
            return
        self.layers.blockSignals(True); self.layers.clear()
        from .graphics import tool_icon, PALETTE
        for element in reversed(self.document()["elements"]):
            flags=('🔒 ' if element.get('editor_locked') else '')+('◌ ' if element.get('editor_hidden') else '')
            title=element.get('description') or element['id']
            row = QListWidgetItem(tool_icon(element["kind"]),flags+title+(' ['+element['group']+']' if element.get('group') else ''))
            row.setToolTip(PALETTE[element["kind"]]+' · '+element['id']); row.setData(Qt.ItemDataRole.UserRole,element["id"])
            self.layers.addItem(row)
        self.layers.blockSignals(False)
        self.sync_layer_selection()

    def sync_layer_selection(self):
        if not hasattr(self,"layers"):
            return
        selected = {item.element["id"] for item in self.scene.selectedItems()}
        self.layers.blockSignals(True)
        for index in range(self.layers.count()):
            item = self.layers.item(index)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selected)
        self.layers.blockSignals(False)

    def select_layers(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.layers.selectedItems()}
        self.scene.blockSignals(True)
        for item in self.scene.items():
            if hasattr(item,"element"):
                item.setSelected(item.element["id"] in selected)
        self.scene.blockSignals(False)
        self.show_properties()

    def layer_menu(self,position):
        menu=QMenu(self.layers)
        for title,key in [('Bloquear / desbloquear','editor_locked'),('Ocultar / mostrar en diseño','editor_hidden')]:
            menu.addAction(title,lambda checked=False,k=key:self.toggle_layer_flag(k))
        menu.addAction('Nombre descriptivo…',self.describe_element)
        menu.addAction('Agrupar',self.group_elements);menu.addAction('Desagrupar',self.ungroup_elements)
        menu.exec(self.layers.mapToGlobal(position))

    def toggle_layer_flag(self,key):
        selected=[i.element for i in self.scene.selectedItems()]
        value=not all(e.get(key,False) for e in selected)
        if selected:self.mutate(lambda:[e.__setitem__(key,value) for e in selected])

    def describe_element(self):
        selected=self.scene.selectedItems()
        if len(selected)==1:
            e=selected[0].element;value,ok=QInputDialog.getText(self,'Nombre descriptivo','Nombre',text=e.get('description',e['id']))
            if ok:self.mutate(lambda:e.__setitem__('description',value))

    def group_elements(self):
        selected=[i.element for i in self.scene.selectedItems()]
        if len(selected)>1:
            group='grupo_'+uuid.uuid4().hex[:6]
            self.mutate(lambda:[e.__setitem__('group',group) for e in selected])

    def ungroup_elements(self):
        groups={i.element.get('group') for i in self.scene.selectedItems()}-{None}
        if groups:self.mutate(lambda:[e.pop('group',None) for e in self.document()['elements'] if e.get('group') in groups])

    def order_elements(self, mode):
        selected = {item.element["id"] for item in self.scene.selectedItems()}
        before = self.document()["elements"]
        ordered = list(before)
        if mode == "front":
            ordered = [e for e in before if e["id"] not in selected]+[e for e in before if e["id"] in selected]
        elif mode == "back":
            ordered = [e for e in before if e["id"] in selected]+[e for e in before if e["id"] not in selected]
        elif mode == "up":
            for i in range(len(ordered)-2,-1,-1):
                if ordered[i]["id"] in selected and ordered[i+1]["id"] not in selected:
                    ordered[i],ordered[i+1] = ordered[i+1],ordered[i]
        elif mode == "down":
            for i in range(1,len(ordered)):
                if ordered[i]["id"] in selected and ordered[i-1]["id"] not in selected:
                    ordered[i],ordered[i-1] = ordered[i-1],ordered[i]
        if before != ordered:
            self.mutate(lambda: self.document().__setitem__("elements",ordered))

    def align_elements(self, mode):
        selected = [item.element for item in self.scene.selectedItems()]
        if len(selected)<2:
            return
        left,top = min(e["x"] for e in selected),min(e["y"] for e in selected)
        right,bottom = max(e["x"]+e["w"] for e in selected),max(e["y"]+e["h"] for e in selected)
        def apply():
            for element in selected:
                if mode in {"left","center","right"}:
                    element["x"] = left if mode=="left" else right-element["w"] if mode=="right" else (left+right-element["w"])/2
                else:
                    element["y"] = top if mode=="top" else bottom-element["h"] if mode=="bottom" else (top+bottom-element["h"])/2
        self.mutate(apply)
