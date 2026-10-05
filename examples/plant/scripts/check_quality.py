tags = ["Pump1.running", "Pump2.running", "TankLevel"]
bad = [name for name in tags if ctx.quality(name) != "good"]
if bad != ctx.state.get("bad"):
    print("Sin lectura válida: " + ", ".join(bad) if bad else "Lecturas correctas")
    ctx.state["bad"] = bad
