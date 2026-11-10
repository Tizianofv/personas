# -*- coding: utf-8 -*-
"""P11-6, GRUPO (b): el cálculo de la ENTRADA de Natalia (fila 14; `personas_cuenta.CALCULOS["entrada"]`).

La App compara la entrada en su modo contar (`POST /api/fichas/entrada`, nombre `entrada` en `escritura_de_personas_para_cuenta`):
su única escritura en contar es el PATCH de la fila de la bandeja (el barrido de las pendientes más la fila pedida). El cálculo lo
dice con `personas_entrada.entrada_calculada`, que recorre lo mismo que la entrada sin escribir.

Qué garantiza y con qué prueba:
  B1  PAREJA: el cálculo dice EXACTAMENTE lo que la entrada (`entrada_fichas`, modo contar) escribió en la bandeja, en orden, en forma de la App.
  B2  CERO ESCRITURAS al calcular, en cada escenario (también con la bandeja caída en escrituras).
  B3  RECHAZOS: un pedido ilegible, sin bandeja, con el modo escribir o con la fila en curso dan el MISMO código que la entrada, sin escribir.
  B4  BARRIDO LLENO: con el tope lleno el cálculo contesta 409 y no escribe (la App puede saltar filas por su cursor).
  B5  REGISTRO: `entrada` está en `CALCULOS` y `RUTAS`.
Lo que NO ve (declarado): el cursor de la App (su proceso), y la App escribiendo en modo escribir (el cálculo no lo predice).
"""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import escenarios_entrada as ee  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_entrada  # noqa: E402

QUIEN = "Prueba"
RUTA = "/api/fichas/entrada"
T_BANDEJA = doble_nocodb.T_BANDEJA          # la bandeja de la prueba (la misma que declara el entorno del servidor del programa)
fila = ee.fila


class Corrida:
    """Un doble propio con la bandeja del escenario, y el programa apuntado a él (sin escribir fuera). Un escenario por corrida."""

    def __init__(self, filas, **kw):
        self.doble = doble_escrituras.DobleEscrituras(**kw)
        self.doble.tablas[T_BANDEJA] = copy.deepcopy(filas)
        self.url = self.doble.arrancar()
        self.parches = [mock.patch.object(base, "NOCODB_BASE", self.url), mock.patch.object(base, "NOCODB_TOKEN", "token-de-prueba"),
                        mock.patch.object(base, "T_BANDEJA_PERSONAS", T_BANDEJA),
                        mock.patch.object(base, "T_PERSONAS_ANOTACIONES", doble_nocodb.TABLA_ANOTACIONES),
                        mock.patch.object(base, "T_UNIONES_PERSONAS", doble_nocodb.T_UNIONES)]

    def __enter__(self):
        for p in self.parches:
            p.start()
        personas_entrada._ENTRADA_CURSOR[0] = 0
        return self

    def __exit__(self, *a):
        for p in reversed(self.parches):
            p.stop()
        self.doble.parar()

    def escrituras(self):
        """Lo que el doble recibió de escritura (PATCH, POST, PUT, DELETE), en orden: `{tabla, metodo, cuerpo}`."""
        return [{"tabla": "bandeja" if p["ruta"].split("/api/v2/tables/")[1].split("/")[0] == T_BANDEJA else p["ruta"],
                 "metodo": p["metodo"], "cuerpo": p["cuerpo"]}
                for p in self.doble.pedidos if p["metodo"] in ("POST", "PATCH", "PUT", "DELETE")]


def forma_app(escrituras):
    """Lo que la App ve de estas escrituras de la bandeja: una fila por registro, sin `Id`, con su nombre lógico."""
    return [{"tabla": e["tabla"], "metodo": e["metodo"], "enlace": None,
             "valores": {k: v for k, v in e["cuerpo"].items() if k != "Id"}} for e in escrituras]


def cuerpo_del_calculo(n):
    return {"fila": n, personas_cuenta.CLAVE_RUTA: RUTA}


# Escenarios: (etiqueta, filas de la bandeja, fila pedida). La entrada escribe en contar solo el PATCH de cada fila que procesa.
ESCENARIOS = [
    ("alta por mensaje pendiente", [fila(1, origen="mensaje", telefono_meta="18095550201", nombre="Entrada Uno")], 1),
    ("dos pendientes, se pide la segunda (el barrido escribe las dos)",
     [fila(1, origen="mensaje", telefono_meta="18095550202", nombre="Entrada Dos"),
      fila(2, origen="mensaje", telefono_meta="18095550203", nombre="Entrada Tres")], 2),
    ("origen desconocido (rechazo que se apunta)", [fila(3, origen="raro", telefono_meta="18095550204", nombre="Entrada Cuatro")], 3),
    ("fila ya contada (no escribe nada)", [fila(4, estado="contado", origen="mensaje", telefono_meta="18095550205")], 4),
]
RECHAZOS = [
    ("escribiendo (en curso)", [fila(5, estado="escribiendo", origen="mensaje", telefono_meta="18095550206")], 5, 409),
    ("fila inexistente", [], 9, 404),
]


class EntradaPareja(unittest.TestCase):

    def test_B1_pareja_y_B2_cero_escrituras_al_calcular(self):
        for etiqueta, filas, n in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                with Corrida(filas) as w:
                    codigo_w, _ = personas_entrada.entrada_fichas(n)
                    escritas = w.escrituras()
                with Corrida(filas) as c:
                    codigo_c, datos_c = personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
                    calculo_escrituras = c.escrituras()
                self.assertEqual(calculo_escrituras, [], "B2: el cálculo escribió")
                self.assertEqual(codigo_w, 200)
                self.assertEqual(codigo_c, 200)
                self.assertEqual(bool(escritas), "ya contada" not in etiqueta, "el escenario no escribe lo que debe (%s)" % etiqueta)
                self.assertEqual(datos_c["escrituras"], forma_app(escritas), "B1: el cálculo no dice lo que la entrada escribió")

    def test_B3_rechazos_iguales_y_sin_escribir(self):
        for etiqueta, filas, n, esperado in RECHAZOS:
            with self.subTest(escenario=etiqueta):
                with Corrida(filas) as w:
                    codigo_w, _ = personas_entrada.entrada_fichas(n)
                    escritas = w.escrituras()
                with Corrida(filas) as c:
                    codigo_c, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
                    self.assertEqual(c.escrituras(), [], "B2: el cálculo escribió")
                self.assertEqual((codigo_c, codigo_w), (esperado, esperado))
                self.assertEqual(escritas, [], "B3: la entrada escribió en un rechazo")

    def test_B3b_pedido_ilegible_sin_bandeja_y_modo_escribir(self):
        filas = [fila(1, origen="mensaje", telefono_meta="18095550207", nombre="Entrada Cinco")]
        casos = [({"fila": 1, "otra": 2}, 400), ({"fila": 0}, 400), ({"fila": True}, 400)]
        with Corrida(filas) as c:
            for cuerpo, esperado in casos:
                codigo, _ = personas_cuenta.calcular("entrada", dict(cuerpo, **{personas_cuenta.CLAVE_RUTA: RUTA}), QUIEN)
                self.assertEqual(codigo, esperado, cuerpo)
                self.assertEqual(c.escrituras(), [], "B2: el cálculo escribió con un pedido ilegible")
                codigo_w, _ = personas_entrada.entrada_de_natalia(cuerpo)
                self.assertEqual(codigo_w, esperado, cuerpo)
        with Corrida(filas), mock.patch.object(base, "T_BANDEJA_PERSONAS", ""):
            codigo, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual(codigo, 503)
            self.assertEqual(personas_entrada.entrada_de_natalia({"fila": 1})[0], 503)
        with Corrida(filas), mock.patch.dict(os.environ, {"FICHAS_ENTRADA_MODO": "escribir"}):
            codigo, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual(codigo, 409, "con el modo escribir del programa no se calcula")

    def test_B4_barrido_lleno_contesta_409_y_no_escribe(self):
        filas = [fila(i, origen="mensaje", telefono_meta="1809555%04d" % i, nombre="Entrada %d" % i)
                 for i in range(1, personas_entrada.ENTRADA_TOPE_BARRIDO + 1)]
        with Corrida(filas) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual((codigo, datos), (409, {"error": "barrido_lleno"}))
            self.assertEqual(c.escrituras(), [], "B2: el cálculo escribió con el barrido lleno")

    def test_B5_el_cálculo_entrada_esta_registrado(self):
        self.assertIn("entrada", personas_cuenta.CALCULOS)
        self.assertIn("entrada", personas_cuenta.RUTAS)


if __name__ == "__main__":
    unittest.main()
