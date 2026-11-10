# -*- coding: utf-8 -*-
"""SOLO PARA LAS PRUEBAS (`tests/test_calcular_cuenta.py`, C7). Llama a `panel_reenvio.calcular_personas` del CLIENTE REAL de la App y
escribe su resultado en JSON, en la última línea de la salida.

Uso:  python3 -B tests/cliente_app_calcular.py <rama_de_la_app> <nombre> <cuerpo_json> <quien>

La rama de la App se lee solo (`sys.path`); nada se escribe en ella (`-B`). Corre en su propio proceso porque la App tiene
módulos con el mismo nombre que los del programa (`personas`).
"""
import json
import sys

rama, nombre, cuerpo, quien = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.path.insert(0, rama)

import panel_reenvio  # noqa: E402

resultado = panel_reenvio.calcular_personas(nombre, json.loads(cuerpo), quien)
print(json.dumps(resultado, ensure_ascii=False))
