# -*- coding: utf-8 -*-
"""P11-6, CONTRATO CON LA APP: el cálculo del programa cumple lo que la App manda y espera (`registro` en `cafe2a3`).

La App compara con SU función (`server._resultado_de_la_cuenta`, que usa `_cuenta_personas_difieren`), importada de su árbol
`PERSONAS_APP_RAMA` (`registro-trabajos/p11-comparar`, solo lectura). Se corre en OTRO proceso (como C7): el programa y la App tienen
ambos un módulo `personas`, y no se pueden importar a la vez. Sin `PERSONAS_APP_RAMA` la prueba se SALTA (`OK (skipped=...)`).

Qué garantiza y con qué prueba:
  K1  RUTAS: cada nombre del grupo (a) lo reconoce la App (`server.escritura_de_personas_para_cuenta`) con la ruta que el programa usa.
  K2  COINCIDE: con los escenarios del grupo (a) que escriben, lo que el programa calcula y lo que se escribe de verdad dan `coincide`
      en la función de la App. La «App» aquí es la escritura del programa (capturada en el doble de NocoDB, con los ids reales, sin
      normalizar): la escritura de la App en vivo no se corre (frontera). Esto incluye el número real de una alta (`<nueva>` en sin_valor).
  K3  NO_COINCIDE: si lo escrito cambia un valor, o sobra o falta una fila, la App dice `no_coincide` y nombra la columna (nunca el valor).
  K4  UNA_VEZ: la App, con el mismo envío dos veces, escribe UNA vez (su `escribir_una_vez`); el segundo envío no captura escrituras y
      su comparación sale `no_comparado la_app_no_escribio`, sin pedir el cálculo. El cálculo es puro: la misma petición da lo mismo.

Frontera: la App no escribe aquí (sus escrituras las hace la escritura del programa, copia independiente); los hilos propios no se ven.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import test_calcular_grupo_a as g  # noqa: E402

GUION_APP = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import server
salida = []
for caso in json.loads(sys.stdin.read()):
    if caso["op"] == "ruta":
        salida.append({"escritura": server.escritura_de_personas_para_cuenta(caso["metodo"], caso["ruta"])})
    elif caso["op"] == "comparar":
        server._captura_personas.lista = caso["capturadas"]
        server._captura_personas.fuera = 0
        estado = {"nombre": caso["nombre"], "calculo": {"calculado": True, "motivo": None, "cuenta": caso["cuenta"]}}
        r, motivo, difieren = server._resultado_de_la_cuenta(estado, None)
        salida.append({"resultado": r, "motivo": motivo, "difieren": difieren})
    elif caso["op"] == "una_vez":
        llamadas = []
        def escribir():
            llamadas.append(1)
            return {"ok": True}
        r1 = server.escribir_una_vez("persona", "llave-de-prueba", {"ruta": "/x", "cuerpo": {"a": 1}}, escribir)
        r2 = server.escribir_una_vez("persona", "llave-de-prueba", {"ruta": "/x", "cuerpo": {"a": 1}}, escribir)
        server._captura_personas.lista = []            # lo que la App captura en el repetido: nada (no llegó a escribir)
        server._captura_personas.fuera = 0
        estado = {"nombre": "crear", "calculo": None}
        salida.append({"escrituras": len(llamadas), "repetidos": [r1[1], r2[1]],
                       "comparacion": list(server._resultado_de_la_cuenta(estado, None))})
print(json.dumps(salida))
'''

ENTORNO_APP = {"NOCODB_BASE": "http://127.0.0.1:9", "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "0000",
               "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def preguntar_a_la_app(rama, casos):
    """Corre el guion en otro proceso, con el árbol de la App como raíz, y devuelve la lista de respuestas."""
    r = subprocess.run([sys.executable, "-B", "-c", GUION_APP, rama], input=json.dumps(casos), capture_output=True, text=True,
                       cwd=rama, env=ENTORNO_APP, timeout=300)
    if r.returncode != 0:
        raise AssertionError("el guion de la App falló: " + r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def _capturadas_de(escrituras):
    """Lo que la App captura al escribir (`_anotar_personas`): tabla con su nombre lógico, método, enlace, cuerpo tal cual (con ids reales)."""
    return [{"tabla": g.NOMBRE_DE_TABLA[e["tabla"]], "metodo": e["metodo"], "enlace": None, "cuerpo": e["cuerpo"],
             "columnas": [], "filas": 1, "confirmada": True} for e in escrituras]   # NocoDB contestó bien (`_nc_directo`, App 5e97f9d)


class ContratoConLaApp(unittest.TestCase):

    def setUp(self):
        self.rama = os.environ.get("PERSONAS_APP_RAMA", "").strip()
        if not self.rama:
            self.skipTest("falta la variable PERSONAS_APP_RAMA: la rama de la App (registro) para el contrato. Sin ella no hay contrato real.")

    def test_K1_rutas_que_la_App_reconoce(self):
        casos, esperados = [], []
        for nombre, cuerpo, _etiqueta in g.ESCENARIOS:
            if nombre in esperados:
                continue
            verbo = personas_cuenta.RUTAS[nombre][0]
            casos.append({"op": "ruta", "metodo": verbo, "ruta": g.ruta_de(nombre, dict(cuerpo))})
            esperados.append(nombre)
        respuestas = preguntar_a_la_app(self.rama, casos)
        self.assertEqual([r["escritura"] for r in respuestas], esperados)

    def test_K2_coincide_cuando_la_App_escribe_lo_mismo(self):
        casos, meta = [], []
        for nombre, cuerpo, etiqueta in g.ESCENARIOS:
            with g.Corrida() as w:
                codigo_w, _ = g.escribir(nombre, dict(cuerpo))
                escrituras_w = w.escrituras()
            with g.Corrida():
                codigo_c, datos_c = personas_cuenta.calcular(nombre, g.cuerpo_del_calculo(nombre, dict(cuerpo)), g.QUIEN)
            if codigo_w in (200, 201) and codigo_c in (200, 201) and "escrituras" in datos_c and escrituras_w:
                casos.append({"op": "comparar", "nombre": nombre, "capturadas": _capturadas_de(escrituras_w), "cuenta": datos_c})
                meta.append(etiqueta)
        self.assertTrue(casos, "ningún escenario que escriba")
        for etiqueta, r in zip(meta, preguntar_a_la_app(self.rama, casos)):
            with self.subTest(escenario=etiqueta):
                self.assertEqual((r["resultado"], r["difieren"]), ("coincide", []), r)

    def test_K3_no_coincide_si_la_App_escribe_otra_cosa(self):
        nombre, cuerpo = "crear", {"cambios": {"nombre": "Ana Prueba", "telefono": "18095550101", "instagram": "@ana"}}
        with g.Corrida() as w:
            g.escribir(nombre, dict(cuerpo))
            escrituras_w = w.escrituras()
        with g.Corrida():
            _, datos_c = personas_cuenta.calcular(nombre, g.cuerpo_del_calculo(nombre, dict(cuerpo)), g.QUIEN)
        capturadas = _capturadas_de(escrituras_w)
        ficha = next(c for c in capturadas if c["tabla"] == "personas")
        ficha["cuerpo"] = dict(ficha["cuerpo"], instagram="@otra")          # la App escribió otro valor
        sobra = dict(capturadas[-1], cuerpo={"ficha_id": 99, "clase": "otra"}, tabla="anotaciones")
        casos = [{"op": "comparar", "nombre": nombre, "capturadas": capturadas, "cuenta": datos_c},
                 {"op": "comparar", "nombre": nombre, "capturadas": capturadas[:-1], "cuenta": datos_c},
                 {"op": "comparar", "nombre": nombre, "capturadas": capturadas + [sobra], "cuenta": datos_c}]
        sin_confirmar = [dict(c, confirmada=False) for c in capturadas]
        casos.append({"op": "comparar", "nombre": nombre, "capturadas": sin_confirmar, "cuenta": datos_c})
        cambio, falta, sobrante, no_confirmada = preguntar_a_la_app(self.rama, casos)
        self.assertEqual((no_confirmada["resultado"], no_confirmada["motivo"]), ("no_comparado", "la_app_no_confirmo"))
        self.assertEqual(cambio["resultado"], "no_coincide")
        self.assertIn("personas.POST.instagram", cambio["difieren"])
        self.assertNotIn("@otra", json.dumps(cambio), "la comparación sacó un valor")
        self.assertEqual(falta["resultado"], "no_coincide")
        self.assertEqual(sobrante["resultado"], "no_coincide")

    def test_K4_una_vez_la_App_escribe_una_vez_y_no_pide_el_calculo_al_repetido(self):
        (r,) = preguntar_a_la_app(self.rama, [{"op": "una_vez"}])
        self.assertEqual(r["escrituras"], 1, "el reenvío repetido volvió a escribir")
        self.assertEqual(r["repetidos"], [False, True])
        self.assertEqual(r["comparacion"], ["no_comparado", "la_app_no_escribio", []])

    def test_K4b_el_calculo_es_puro_y_contesta_lo_mismo_en_cada_pedido(self):
        nombre, cuerpo = "crear", {"cambios": {"nombre": "Ana Prueba", "telefono": "18095550101"}}
        with g.Corrida() as c:
            uno = personas_cuenta.calcular(nombre, g.cuerpo_del_calculo(nombre, dict(cuerpo)), g.QUIEN)
            dos = personas_cuenta.calcular(nombre, g.cuerpo_del_calculo(nombre, dict(cuerpo)), g.QUIEN)
            self.assertEqual(c.escrituras(), [], "el cálculo escribió")
        self.assertEqual(uno, dos)


if __name__ == "__main__":
    unittest.main()
