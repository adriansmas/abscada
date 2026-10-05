"""Create the TCP S7 example using the same screens and faceplates as demo."""
from pathlib import Path
from abscada.project import Project

root = Path(__file__).resolve().parents[1]
project = Project.load(root / "examples" / "demo")
project.root = root / "examples" / "s7"
project.manifest["name"] = "Planta"
project.connections = [dict(id="plant", protocol="s7", host="127.0.0.1", port=1102, rack=0, slot=1, poll_ms=250)]
for i, variable in enumerate(project.variables[:2]):
    offset = i * 16
    for field, suffix in (("running", f"DBX{offset}.0"), ("flow", f"DBD{offset+4}"), ("setpoint", f"DBD{offset+8}")):
        variable["bindings"][variable["name"] + "." + field]["address"] = "%DB1." + suffix
project.variables[2]["binding"]["address"] = "%DB1.DBD12"
project.save()
print(project.root)
