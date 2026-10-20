"""Variable folders and importing a Siemens DB from its TIA Portal source."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import pytest
from abscada.project import Project
from abscada import tia_import, screen_tree
from abscada.connectors import parse_address

SOURCE = '''TYPE "MD012_VALVE"
TITLE = Válvula
VERSION : 0.1
   STRUCT
      Abierta : Bool;   // final de carrera
      Cerrada : Bool;
      Fallo { S7_SetPoint := 'False'} : Bool := TRUE;
      Modo : Byte;
      Posicion : Real := 12.5;
      Contador : DInt;
      Estado : Word := 16#00FF;
      Nombre : String[10];
      Retardo : Time := T#1s500ms;
      Extra : Struct
         a : Int;
         b : Bool;
      END_STRUCT;
   END_STRUCT;

END_TYPE

DATA_BLOCK "DB_Valvulas"
{ S7_Optimized_Access := 'FALSE' }
VERSION : 0.1
NON_RETAIN
   STRUCT
      Activo : Bool;
      V101 : "MD012_VALVE";
      V102 : "MD012_VALVE";
      Niveles : Array[1..4] of Real;
      Bits : Array[0..9] of Bool;
      Matriz : Array[0..1, 0..2] of Int;
      Final : Int;
   END_STRUCT;


BEGIN
   V102.Posicion := 50.0;
   Niveles[2] := 7.5;
   Matriz[1,2] := 9;
END_DATA_BLOCK
'''


def empty(tmp_path):
    return Project(tmp_path, dict(schema_version=1, name="t", startup_screen="main"), {}, [],
                   [dict(id="plc", protocol="s7", host="127.0.0.1")], {"main": dict(width=100, height=100, elements=[])}, {})


def imported(tmp_path, **options):
    project = empty(tmp_path)
    result = tia_import.plan(project, SOURCE, db=10, connection="plc", **options)
    tia_import.apply(project, result, "PLC/Valvulas")
    project.validate()
    return project, result


def addresses(project):
    return {name: tag["binding"]["address"] for name, tag in project.tags().items() if tag.get("binding")}


def test_db_becomes_one_structured_variable_with_tia_paths_and_addresses(tmp_path):
    project, result = imported(tmp_path)
    found = addresses(project)
    # Bools packed, a byte on the next byte, larger types and structures on even bytes.
    assert found["DB_Valvulas.Activo"] == "%DB10.DBX0.0"
    assert found["DB_Valvulas.V101.Abierta"] == "%DB10.DBX2.0"
    assert found["DB_Valvulas.V101.Fallo"] == "%DB10.DBX2.2"
    assert found["DB_Valvulas.V101.Modo"] == "%DB10.DBB3"
    assert found["DB_Valvulas.V101.Posicion"] == "%DB10.DBD4"
    assert found["DB_Valvulas.V101.Estado"] == "%DB10.DBW12"
    # String[10] is left out but keeps its 12 bytes.
    assert "DB_Valvulas.V101.Nombre" not in project.tags()
    assert found["DB_Valvulas.V101.Retardo"] == "%DB10.DBD26"
    assert found["DB_Valvulas.V101.Extra.a"] == "%DB10.DBW30"
    assert found["DB_Valvulas.V101.Extra.b"] == "%DB10.DBX32.0"
    assert found["DB_Valvulas.V102.Abierta"] == "%DB10.DBX34.0"
    assert found["DB_Valvulas.Niveles[1]"] == "%DB10.DBD66" and found["DB_Valvulas.Niveles[4]"] == "%DB10.DBD78"
    assert found["DB_Valvulas.Bits[9]"] == "%DB10.DBX83.1"
    assert found["DB_Valvulas.Matriz[0][0]"] == "%DB10.DBW84" and found["DB_Valvulas.Matriz[1][2]"] == "%DB10.DBW94"
    assert found["DB_Valvulas.Final"] == "%DB10.DBW96"
    for name, address in found.items():
        parse_address(address, project.tags()[name]["type"])
    assert project.types["MD012_VALVE"]["Extra"] == "MD012_VALVE_Extra"
    assert project.types["DB_Valvulas"]["Niveles"] == "float[1..4]"
    assert any("String[10]" in warning for warning in result.warnings)
    assert any("Word" in warning and "signo" in warning for warning in result.warnings)


def test_initial_values_come_from_declarations_and_begin(tmp_path):
    project, _ = imported(tmp_path)
    tags = project.tags()
    assert tags["DB_Valvulas.V101.Fallo"]["initial"] is True
    assert tags["DB_Valvulas.V101.Posicion"]["initial"] == 12.5
    assert tags["DB_Valvulas.V102.Posicion"]["initial"] == 50.0
    assert tags["DB_Valvulas.V101.Estado"]["initial"] == 255
    assert tags["DB_Valvulas.V101.Retardo"]["initial"] == 1500
    assert tags["DB_Valvulas.Niveles[2]"]["initial"] == 7.5 and tags["DB_Valvulas.Niveles[1]"]["initial"] == 0.0
    assert tags["DB_Valvulas.Matriz[1][2]"]["initial"] == 9
    assert not tags["DB_Valvulas.Activo"]["writable"]


def test_import_goes_into_a_folder_and_can_be_replaced(tmp_path):
    project, _ = imported(tmp_path)
    assert project.variables[0]["folder"] == "PLC/Valvulas"
    assert screen_tree.folders(project, "variables") == ["PLC", "PLC/Valvulas"]
    with pytest.raises(ValueError, match="Sustituir"):
        tia_import.plan(project, SOURCE, db=10, connection="plc")
    result = tia_import.plan(project, SOURCE.replace("Final : Int;", "Final : Int;\n      Nuevo : Bool;"), db=11,
                             connection="plc", writable=True, replace=True)
    tia_import.apply(project, result, "PLC/Valvulas")
    project.validate()
    assert len(project.variables) == 1 and project.tags()["DB_Valvulas.Nuevo"]["binding"]["address"] == "%DB11.DBX98.0"
    assert project.tags()["DB_Valvulas.V101.Abierta"]["writable"]


def test_conflicting_type_needs_replace(tmp_path):
    project = empty(tmp_path)
    project.types["MD012_VALVE"] = {"otro": "int"}
    with pytest.raises(ValueError, match="MD012_VALVE"):
        tia_import.plan(project, SOURCE, db=10, connection="plc")


def test_optimized_db_imports_structure_without_addresses(tmp_path):
    project = empty(tmp_path)
    result = tia_import.plan(project, SOURCE.replace("'FALSE'", "'TRUE'"), db=10, connection="plc")
    tia_import.apply(project, result)
    project.validate()
    assert not addresses(project) and "DB_Valvulas.V101.Posicion" in project.tags()
    assert any("optimizado" in warning for warning in result.warnings)


def test_db_of_a_udt_and_types_only(tmp_path):
    project = empty(tmp_path)
    udt, _, _ = SOURCE.partition("DATA_BLOCK")
    single = udt + 'DATA_BLOCK "V200"\n{ S7_Optimized_Access := \'FALSE\' }\n"MD012_VALVE"\nBEGIN\nEND_DATA_BLOCK\n'
    result = tia_import.plan(project, single, db=3, connection="plc")
    tia_import.apply(project, result)
    assert project.variables[0]["type"] == "MD012_VALVE"
    assert addresses(project)["V200.Abierta"] == "%DB3.DBX0.0"
    types_only = tia_import.plan(empty(tmp_path), udt)
    assert set(types_only.types) == {"MD012_VALVE", "MD012_VALVE_Extra"} and types_only.variable is None


@pytest.mark.parametrize("text, message", [
    ('DATA_BLOCK "X"\n"FB_Motor"\nBEGIN\nEND_DATA_BLOCK', "FB_Motor"),
    ('DATA_BLOCK "X"\nSTRUCT\n a : Patata;\nEND_STRUCT;\nBEGIN\nEND_DATA_BLOCK', "Patata"),
    ('FUNCTION_BLOCK "FB"\nEND_FUNCTION_BLOCK', "solo se importan"),
    ('DATA_BLOCK "X"\nSTRUCT\n a : Int\nEND_STRUCT;\nEND_DATA_BLOCK', "Línea 4"),
    ("", "Pega"),
])
def test_bad_sources_explain_the_problem(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        tia_import.plan(empty(tmp_path), text, db=1, connection="plc")


def test_variable_folders_rename_move_delete(tmp_path):
    project, _ = imported(tmp_path)
    project.variables.append(dict(name="Suelta", type="int", initial=0))
    screen_tree.add_folder(project, "", "Otros", "variables")
    screen_tree.move_variable(project, "Suelta", "Otros")
    screen_tree.rename_folder(project, "PLC", "Planta", "variables")
    assert project.variables[0]["folder"] == "Planta/Valvulas"
    screen_tree.move_folder(project, "Planta/Valvulas", "Otros", "variables")
    assert project.variables[0]["folder"] == "Otros/Valvulas"
    screen_tree.delete_folder(project, "Otros", "variables")
    assert project.variables[0]["folder"] == "Valvulas" and "folder" not in project.variables[1]
    project.validate()
    project.variables[1]["folder"] = "/mal/"
    with pytest.raises(ValueError, match="carpeta"):
        project.validate()


def test_studio_imports_into_a_folder(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from abscada.ui import Window
    from abscada.tia_import_dialog import TiaImportDialog
    from abscada.variable_forms import FOLDER_ROW
    app = QApplication.instance() or QApplication([])
    project = empty(tmp_path / "studio")
    project.variables.append(dict(name="Suelta", type="int", initial=0))
    (tmp_path / "studio").mkdir()
    project.save()
    window = Window(Project.load(tmp_path / "studio"))
    monkeypatch.setattr(window, "error", lambda exc: (_ for _ in ()).throw(AssertionError(str(exc))))
    try:
        window.show(); app.processEvents()
        dialog = TiaImportDialog(window, "PLC")
        dialog.source.setPlainText(SOURCE)
        dialog.db.setValue(10)
        dialog.update_preview()
        assert dialog.preview.topLevelItemCount() == len(dialog.result_plan.rows) > 40
        dialog.validate()
        result = dialog.result_plan
        window.mutate(lambda: tia_import.apply(window.project, result, dialog.folder()))
        dialog.close()
        window.navigate("variables")
        folder = window.variable_item(FOLDER_ROW + "PLC")
        assert folder is not None and folder.child(0).data(0, 256) == "DB_Valvulas"
        window.add_variable("PLC")
        window.new_variable_field.setText("Nueva"); window.new_variable_field.editingFinished.emit()
        for _ in range(5):
            app.processEvents()
        assert window.project.variables[-1] == dict(name="Nueva", type="float", initial=0.0, writable=False, folder="PLC")
    finally:
        window.dirty = False; window.close(); app.processEvents()
