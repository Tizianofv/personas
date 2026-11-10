# -*- coding: utf-8 -*-
"""P11-6, CONTRATO CON LA APP: el cálculo del programa cumple lo que la App manda y espera (`registro` en `cafe2a3`).

La App compara con SU función (`server._resultado_de_la_cuenta`, que usa `_cuenta_personas_difieren`), importada de su árbol
`PERSONAS_APP_RAMA` (`registro-trabajos/p11-comparar`, solo lectura). Se corre en OTRO proceso (como C7): el programa y la App tienen
ambos un módulo `personas`, y no se pueden importar a la vez. Sin `PERSONAS_APP_RAMA` la prueba se SALTA (`OK (skipped=...)`).

Qué garantiza y con qué prueba:
  K1  RUTAS: cada nombre del grupo (a) lo reconoce la App (`server.escritura_de_personas_para_cuenta`) con la ruta que el programa usa.
  K2  COINCIDE: con los escenarios del grupo (a) que escriben, lo que calcula el programa (por el CLIENTE REAL de la App contra el
      servidor real del programa) y lo que se escribe de verdad dan `coincide` en la función de la App, en los cinco nombres. La «App» aquí es la escritura del programa (capturada en el doble de NocoDB, con los ids reales, sin
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
import escenarios_portal_escrituras as esc  # noqa: E402
import test_calcular_cuenta as tc  # noqa: E402
import personas_entrada  # noqa: E402
import test_calcular_grupo_a as g  # noqa: E402

CLIENTE = RAIZ / "tests" / "cliente_app_calcular.py"

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


def llamar_cliente(rama, entorno, nombre, cuerpo):
    """`panel_reenvio.calcular_personas` de la App, en su propio proceso (como C7). Devuelve su resultado: `calculado`, `motivo`, `cuenta`."""
    env = dict(esc.ENTORNO_MINIMO)
    env.update(entorno)
    r = subprocess.run([sys.executable, "-B", str(CLIENTE), rama, nombre, json.dumps(cuerpo, ensure_ascii=False), g.QUIEN],
                       env=env, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise AssertionError("el cliente de la App falló: " + r.stderr[-800:])
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

    def test_K2_coincide_con_el_cliente_real_de_la_App_en_los_cinco_nombres(self):
        """Pasa por `panel_reenvio.calcular_personas` (el cliente real de la App, en su propio proceso) contra el servidor real del
        programa (HTTP, con el doble de NocoDB). Cada nombre del grupo tiene que dar `coincide` por la comparación de la App."""
        cubiertos, casos, meta = set(), [], []
        with tc.Servidor() as s:
            entorno = {"PERSONAS_BASE": "http://127.0.0.1:%d" % s.puerto, tc.VARIABLE_LLAVE: tc.LLAVE_CUENTA}
            for nombre, cuerpo, etiqueta in g.ESCENARIOS:
                with g.Corrida() as w:
                    codigo_w, _ = g.escribir(nombre, dict(cuerpo))
                    escrituras_w = w.escrituras()
                if codigo_w not in (200, 201) or not escrituras_w:
                    continue
                s.doble.pedidos.clear()
                resp = llamar_cliente(self.rama, entorno, nombre, g.cuerpo_del_calculo(nombre, dict(cuerpo)))
                escrituras_c = [x for x in s.doble.pedidos if x["metodo"] in g.METODOS_ESCRITURA]
                self.assertEqual(escrituras_c, [], "el cálculo mandó una escritura (%s)" % etiqueta)
                self.assertTrue(resp.get("calculado"), "el cliente de la App no dio cálculo (%s): %r" % (etiqueta, resp))
                cubiertos.add(nombre)
                casos.append({"op": "comparar", "nombre": nombre, "capturadas": _capturadas_de(escrituras_w), "cuenta": resp["cuenta"]})
                meta.append(etiqueta)
        self.assertEqual(cubiertos, set(g.GRUPO_A), "algún nombre del grupo no tiene un escenario de éxito")
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


class ContratoConLaEntrada(unittest.TestCase):
    """K2b (grupo b): la entrada de Natalia en modo contar. El cliente real de la App calcula `entrada` contra el servidor real del
    programa (con la bandeja del escenario); la comparación de la App da `coincide` con lo que la entrada escribió en la bandeja."""

    def setUp(self):
        self.rama = os.environ.get("PERSONAS_APP_RAMA", "").strip()
        if not self.rama:
            self.skipTest("falta la variable PERSONAS_APP_RAMA: la rama de la App (registro) para el contrato. Sin ella no hay contrato real.")

    def test_K2b_la_entrada_coincide_con_el_cliente_real(self):
        import test_calcular_grupo_b as gb  # noqa: E402
        casos, meta = [], []
        for etiqueta, filas, n in gb.ESCENARIOS:
            with gb.Corrida(filas) as w:
                personas_entrada.entrada_fichas(n)
                escritas = w.escrituras()
            if not escritas:
                continue
            with tc.Servidor(tablas={gb.T_BANDEJA: filas}) as s:
                entorno = {"PERSONAS_BASE": "http://127.0.0.1:%d" % s.puerto, tc.VARIABLE_LLAVE: tc.LLAVE_CUENTA}
                s.doble.pedidos.clear()
                resp = llamar_cliente(self.rama, entorno, "entrada", gb.cuerpo_del_calculo(n))
                escrituras_c = [x for x in s.doble.pedidos if x["metodo"] in g.METODOS_ESCRITURA]
                self.assertEqual(escrituras_c, [], "el cálculo de la entrada mandó una escritura (%s)" % etiqueta)
            self.assertTrue(resp.get("calculado"), "el cliente de la App no dio cálculo (%s): %r" % (etiqueta, resp))
            casos.append({"op": "comparar", "nombre": "entrada", "capturadas": [dict(e, enlace=None, columnas=[], filas=1, confirmada=True)
                                                                             for e in escritas], "cuenta": resp["cuenta"]})
            meta.append(etiqueta)
        self.assertTrue(casos, "ningún escenario de la entrada escribe")
        for etiqueta, r in zip(meta, preguntar_a_la_app(self.rama, casos)):
            with self.subTest(escenario=etiqueta):
                self.assertEqual((r["resultado"], r["difieren"]), ("coincide", []), r)


if __name__ == "__main__":
    unittest.main()
