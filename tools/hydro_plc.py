"""Compatibility shim for the hydro plant simulator, now in abscada.simulators.hydro.

    abscada --simulador hydro        (equivalent to running this file)
"""
from abscada.simulators.hydro import *  # noqa: F401,F403
from abscada.simulators.hydro import main

if __name__ == "__main__":
    main()
