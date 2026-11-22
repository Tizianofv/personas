# -*- coding: utf-8 -*-
"""21-nov-2026, CONTRATO DE LA ENTRADA CON AVISO: la misma entrada da lo mismo en la App real y en el programa.

La App (`server.entrada_fichas`, de su árbol `PERSONAS_APP_RAMA`, solo lectura) corre en OTRO proceso, porque el programa y la App tienen
ambos un módulo `personas` y no se pueden importar a la vez (como `test_contrato_app_p11.py`). Cada lado escribe en su propio doble de
NocoDB con la misma bandeja. Se comparan las escrituras que la App hace al escribir (`FICHAS_ENTRADA_MODO=escribir`) con las que el
programa calcula (`personas_cuenta.calcular("entrada", ...)` en modo escribir), en la misma forma (`personas_cuenta._en_forma_de_la_app`),
sin la columna del reloj.

Qué garantiza y con qué prueba:
  C1  Un aviso de una ficha que ya existe (`por_resolver`): la App contesta 200 y el cálculo también; sus escrituras son las mismas (la
      ficha, la fila de aviso en la bandeja, la fila final con `por_resolver`).
  C2  Un aviso informativo (`ligado_por_dictado`): lo mismo, con la fila final `aplicado`.
  C3  Aviso informativo con dos fichas (`mismo_nombre` con la otra ficha; la ficha 2 sin nombre hace que la entrada la complete):
      la fila de aviso y la fila final llevan `otra_ficha_id`, en la App y en el programa, y dan lo mismo (movida desde
      test_calcular_entrada_escribir.E8: antes comparaba el cálculo con el programa, no con la App).
  C4  Cero escrituras al calcular: el doble del programa no recibe ninguna (en C1 y C3).

Sin `PERSONAS_APP_RAMA` la clase se SALTA (`OK (skipped=...)`); la sala la corre con la variable puesta.
Frontera: el doble de NocoDB no es la base real; el reloj (`cuando`) no se compara; las claves de las filas de aviso se comparan tal cual
(son huellas de los mismos datos en los dos lados).
"""
import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import personas_cuenta  # noqa: E402
import test_calcular_entrada_escribir as ee  # noqa: E402
from test_calcular_grupo_b import Corrida, QUIEN, T_BANDEJA, cuerpo_del_calculo, fila  # noqa: E402

MODO = {"FICHAS_ENTRADA_MODO": "escribir"}

GUION_APP = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import server
codigo, cuerpo = server.entrada_fichas(int(sys.argv[2]))
print(json.dumps({"codigo": codigo, "cuerpo": cuerpo}, default=str))
'''

ENTORNO_APP_BASE = {"NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "0000", "PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin",
                    "LANG": "C.UTF-8", "FICHAS_ENTRADA_MODO": "escribir"}

# (etiqueta, filas de la bandeja, fila pedida)
ESCENARIOS = [
    ("aviso por resolver: teléfono de otra ficha, otro nombre",
     [fila(7, origen="mensaje", telefono_meta="18097770001", nombre="Otra Persona Distinta")], 7),
    ("aviso informativo: número dictado de una ficha",
     [fila(8, origen="mensaje", telefono_dicho="18097770001", nombre="Persona de prueba 1")], 8),
]


def _escrituras_de_la_app(doble_app):
    """Lo que la App escribió en su doble, en la forma del cálculo (`_en_forma_de_la_app`), sin la columna del reloj."""
    # `escrituras_reales` nombra las tablas con las constantes de `base` (las del programa): la `Corrida` vacía las pone como en la prueba.
    with Corrida([]):
        filas, _sin_valor = ee.escrituras_reales(SimpleNamespace(doble=doble_app))
    return ee.sin_reloj(filas)


class ContratoEntradaAviso(unittest.TestCase):

    def setUp(self):
        self.rama = os.environ.get("PERSONAS_APP_RAMA", "").strip()
        if not self.rama:
            self.skipTest("falta la variable PERSONAS_APP_RAMA: la rama de la App (registro) para el contrato de la entrada con aviso.")

    def _entrada_en_la_app(self, filas, n, sembrar=None):
        """La App (`server.entrada_fichas`) en modo escribir, en su proceso, contra su propio doble. Devuelve (código, escrituras en forma de cálculo)."""
        doble = doble_escrituras.DobleEscrituras()
        doble.tablas[T_BANDEJA] = copy.deepcopy(filas)
        if sembrar:
            sembrar(doble.tablas[doble_nocodb.T_PERSONAS])
        url = doble.arrancar()
        try:
            entorno = dict(ENTORNO_APP_BASE)
            entorno.update({"NOCODB_BASE": url, "NOCODB_T_BANDEJA_PERSONAS": T_BANDEJA,
                            "NOCODB_T_UNIONES_PERSONAS": doble_nocodb.T_UNIONES,
                            "NOCODB_T_PERSONAS_ANOTACIONES": doble_nocodb.TABLA_ANOTACIONES})
            r = subprocess.run([sys.executable, "-B", "-c", GUION_APP, self.rama, str(n)], input="", capture_output=True, text=True,
                               cwd=self.rama, env=entorno, timeout=300)
            if r.returncode != 0:
                raise AssertionError("el guion de la App falló: " + r.stderr[-800:])
            resp = json.loads(r.stdout.strip().splitlines()[-1])
            return resp["codigo"], _escrituras_de_la_app(doble)
        finally:
            doble.parar()

    def _pareja(self, etiqueta, filas, n, sembrar=None):
        with mock.patch.dict(os.environ, MODO), Corrida(filas) as c:
            if sembrar:
                sembrar(c.doble.tablas[doble_nocodb.T_PERSONAS])
            codigo_c, datos_c = personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
            self.assertEqual(c.escrituras(), [], "C4: el cálculo escribió (%s)" % etiqueta)
        codigo_a, escrituras_a = self._entrada_en_la_app(filas, n, sembrar)
        self.assertEqual((codigo_a, codigo_c), (200, 200), etiqueta)
        self.assertTrue(escrituras_a, "la App no escribió nada: la prueba no compara (%s)" % etiqueta)
        self.assertEqual(ee.sin_reloj(datos_c["escrituras"]), escrituras_a,
                         "el cálculo no dice lo que la App escribe (%s)" % etiqueta)

    def test_C1_C2_aviso_con_ficha_existente_como_la_App(self):
        for etiqueta, filas, n in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                self._pareja(etiqueta, filas, n)

    def test_C3_informativo_con_dos_fichas_como_la_App(self):
        def ficha_2_sin_nombre(fichas):
            for ficha in fichas:
                if ficha.get("Id") == 2:
                    ficha["nombre"] = None
        filas = [fila(1, origen="mensaje", telefono_meta="18097770002", nombre="Persona de prueba 1")]
        self._pareja("informativo con dos fichas (mismo_nombre)", filas, 1, ficha_2_sin_nombre)
        codigo_a, escrituras_a = self._entrada_en_la_app(filas, 1, ficha_2_sin_nombre)
        finales = [e for e in escrituras_a if e["tabla"] == "bandeja"]
        self.assertIsNotNone(finales[-1]["valores"].get("otra_ficha_id"), "la App no escribió la otra ficha en la fila final")
        self.assertEqual(finales[-1]["valores"].get("estado"), "aplicado")


if __name__ == "__main__":
    unittest.main()
