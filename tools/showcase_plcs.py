"""Compatibility shim for the laboratory PLCs, now in abscada.simulators.laboratory.

    abscada --simulador laboratorio   (equivalent to running this file)
"""
from abscada.simulators.laboratory import *  # noqa: F401,F403
from abscada.simulators.laboratory import main

if __name__ == "__main__":
    main()
