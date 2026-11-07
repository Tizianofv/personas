# -*- coding: utf-8 -*-
"""Cada constante que `base.py` copia de la App de registro tiene el MISMO valor que en la App (commit `0b48b5d`).

Los valores de la App están en `constantes_app.json` (el origen y el comando que los sacó están dentro del archivo).
La prueba importa `base` en un proceso aparte, con entorno limpio, y compara nombre por nombre. Sin `skip`: si falta un
nombre, o un valor cambió, la prueba sale roja y dice cuál.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO = RAIZ / "constantes_app.json"
ENTORNO_LIMPIO = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}

# Igual que en el generador (la normalización es la misma de los dos lados).
CODIGO_DE_BASE = r'''
import json, sys
sys.path.insert(0, ".")
import base
def norm(v):
    if type(v).__name__ == "object":
        return "<sentinela>"
    if isinstance(v, (tuple, list)):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
nombres = json.loads(sys.argv[1])
salida = {}
for n in nombres:
    salida[n] = norm(getattr(base, n))
print(json.dumps(salida, ensure_ascii=False, sort_keys=True))
'''


class ElValorEsElDeLaApp(unittest.TestCase):
    def test_cada_constante_copiada_tiene_el_valor_de_la_app(self):
        doc = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        esperados = doc["valores"]
        r = subprocess.run([sys.executable, "-B", "-c", CODIGO_DE_BASE, json.dumps(sorted(esperados))],
                           cwd=str(RAIZ), env=ENTORNO_LIMPIO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "base.py no se pudo importar o le falta un nombre: " + r.stderr[-400:])
        reales = json.loads(r.stdout.strip().splitlines()[-1])
        distintos = sorted(n for n in esperados if reales.get(n) != esperados[n])
        self.assertEqual(distintos, [], "constantes que no son las de la App (commit %s)" % doc["origen"][:60])

    def test_el_archivo_declara_su_origen_y_su_comando(self):
        doc = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        self.assertIn("0b48b5d", doc["origen"])
        self.assertIn("generar_constantes.py", doc["comando"])
        self.assertGreater(len(doc["valores"]), 30)


if __name__ == "__main__":
    unittest.main()
