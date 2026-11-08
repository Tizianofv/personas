# -*- coding: utf-8 -*-
"""SOLO PARA LAS PRUEBAS. Arranca `servidor.py` igual que `python3 servidor.py`, con UNA diferencia: la llamada HTTP a Google de la
ruta de contactos (`personas_portal_lectura.PEDIR_GOOGLE`) es el doble de `tests/doble_google.py`, en el escenario que llega en argv[1].

Uso:  python3 -B tests/servidor_con_google_falso.py <ok|sin_token>

El arranque en producción no pasa por aquí: `servidor.py` no tiene ningún gancho para Google. Las pruebas lo lanzan como proceso aparte,
con su entorno explícito (como `servidor.py`), y leen HOST y PORT del entorno como el servidor real.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

import doble_google  # noqa: E402
import personas_portal_lectura  # noqa: E402
import servidor  # noqa: E402

personas_portal_lectura.PEDIR_GOOGLE = doble_google.pedir_falso(sys.argv[1])

if __name__ == "__main__":
    servidor.arrancar().serve_forever()
