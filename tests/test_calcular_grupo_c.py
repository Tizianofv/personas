# -*- coding: utf-8 -*-
"""P11-6, GRUPO (c): el cálculo de la CARA (fila 17; `personas_cuenta.CALCULOS["cara"]`).

La App escribe la cara en su modo contar (`POST /api/personas/<id>/cara`; nombre `cara` en `escritura_de_personas_para_cuenta`):
su única escritura es el PATCH de la columna de caras de la ficha, con las ranuras de antes más la nueva (rotando a `CARA_RANURAS`).
El cálculo lo dice con `personas.cara_calculada`, la misma cuenta que `personas.escribir_cara` (sin el PATCH).

Qué garantiza y con qué prueba:
  C1  PAREJA en los escenarios de `ESCENARIOS` (ranura libre, ranuras llenas, la misma cara otra vez): el cálculo dice exactamente lo que la
      escritura de servicio del programa (`personas_escritura_rutas.cara`) mandó a NocoDB, en forma de la App (sin `Id`), y el número de
      ranuras que contesta la escritura es el de las que el cálculo arma.
  C2  CERO ESCRITURAS AL CALCULAR: en cada escenario y cada rechazo, el cálculo no manda POST, PATCH, PUT ni DELETE; también con la base
      caída en lecturas.
  C3  RECHAZOS IGUALES Y SIN ESCRIBIR: ficha unida, ficha guardada aparte, ficha inexistente (la base contesta 404 a su lectura), id 0 y
      cara de 127 números: el cálculo da el MISMO código y el MISMO cuerpo que la escritura. Los códigos y textos esperados van escritos
      a mano aquí, así que una mutación que quite una guarda se ve aunque las dos caras cambien igual.
  C4  REGISTRO: `cara` está en `CALCULOS` y en `RUTAS`.
  C5  NINGUNA CACHÉ: el cálculo no invalida la caché de caras del programa (`base._caras_cache`, `base.invalidate_caras`).
  C6  CUERPO: una clave que no sea `cara`, la falta de `cara`, o una cara que no es base64 de 128 números dan 400, sin escribir.
Lo que NO ve: la caché de caras de la App (`_caras_cache` de su proceso; el cálculo no puede tocarla desde el programa), y la escritura
de la App en vivo (frontera: la App no escribe aquí, ver K2c en `test_contrato_app_p11.py`).
"""
import base64
import copy
import struct
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
import personas_cuenta  # noqa: E402
import personas_escritura_rutas  # noqa: E402
import personas_escrituras  # noqa: E402

QUIEN = "Prueba"
METODOS_ESCRITURA = ("POST", "PATCH", "PUT", "DELETE")
TEXTO_UNIDA_O_QUITADA = "La ficha está unida o guardada aparte: no admite cambio de cara. No se guardó."
TEXTO_PEDIDO_CARA = "El pedido de cara es {persona_id: entero, vec: [números]}."
TEXTO_VEC = "vec son 128 números."
TEXTO_NO_SE_GUARDO = "No se guardó. Personas no responde. Inténtalo en un momento."


def vec(semilla):
    """128 números exactos en float32 (k/128 - 1): el mismo vector llega a la escritura y, en base64, al cálculo."""
    return [((semilla * 31 + i * 7) % 256) / 128.0 - 1.0 for i in range(128)]


def b64(v):
    """La cara como la manda la App: base64 de los float32 en little-endian. Se escribe aquí a mano, sin el codificador del programa."""
    return base64.b64encode(struct.pack("<%df" % len(v), *v)).decode("ascii")


def caras_de(*vs):
    """El valor de la columna `caras` de una ficha con esos vectores, como lo guarda el programa (separador `|`)."""
    return base.CARA_SEPARADOR.join(b64(v) for v in vs)


def tablas_con(caras_por_ficha):
    """La tabla `personas` del doble, con la columna `caras` puesta en esas fichas (las demás, como en el doble)."""
    filas = copy.deepcopy(doble_nocodb.PERSONAS)
    for fila in filas:
        if fila["Id"] in caras_por_ficha:
            fila[base.CARA_COLUMNA] = caras_por_ficha[fila["Id"]]
    return filas


def cuerpo_del_calculo(pid, v):
    """Lo que manda la App: la cara en base64 (sin ids) y la ruta de la escritura, con la ficha."""
    return {"cara": b64(v), personas_cuenta.CLAVE_RUTA: "/api/personas/%s/cara" % pid}


class Corrida:
    """Un doble propio de NocoDB con las caras del escenario, y el programa apuntado a él (sin escribir fuera). Una corrida por lado."""

    def __init__(self, caras=None, **kw):
        self.doble = doble_escrituras.DobleEscrituras(**kw)
        self.doble.tablas[doble_nocodb.T_PERSONAS] = tablas_con(caras or {})
        self.url = self.doble.arrancar()
        self.parches = [mock.patch.object(base, "NOCODB_BASE", self.url), mock.patch.object(base, "NOCODB_TOKEN", "token-de-prueba")]

    def __enter__(self):
        for p in self.parches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self.parches):
            p.stop()
        self.doble.parar()

    def escrituras(self):
        """Lo que el doble recibió de escritura, en orden, en forma de la App: `{tabla, metodo, enlace, valores}` (sin `Id`)."""
        salida = []
        for p in self.doble.pedidos:
            if p["metodo"] not in METODOS_ESCRITURA:
                continue
            tabla = p["ruta"].split("/api/v2/tables/")[1].split("/")[0]
            assert tabla == doble_nocodb.T_PERSONAS, "escritura fuera de personas: %s" % p["ruta"]
            salida.append({"tabla": "personas", "metodo": p["metodo"], "enlace": None,
                           "valores": {k: v for k, v in p["cuerpo"].items() if k != "Id"}})
        return salida


# Escenarios de la escritura que sí escribe: (etiqueta, caras de las fichas, ficha, vector que llega).
ESCENARIOS = [
    ("ranura libre", {}, 1, vec(1)),
    ("ranuras llenas: entra la cuarta y se va la más vieja", {2: caras_de(vec(2), vec(3), vec(4))}, 2, vec(5)),
    ("la misma cara otra vez", {1: caras_de(vec(6))}, 1, vec(6)),
]
# Rechazos: (etiqueta, caras, ficha, vector que llega, código esperado, cuerpo esperado).
RECHAZOS = [
    ("ficha unida", {}, 4, vec(7), 409, {"ok": False, "error": TEXTO_UNIDA_O_QUITADA}),
    ("ficha guardada aparte", {}, 3, vec(7), 409, {"ok": False, "error": TEXTO_UNIDA_O_QUITADA}),
    ("ficha inexistente", {}, 99, vec(7), 502, {"ok": False, "error": TEXTO_NO_SE_GUARDO}),
    ("id 0", {}, 0, vec(7), 400, {"ok": False, "error": TEXTO_PEDIDO_CARA}),
    ("cara de 127 números", {}, 1, vec(7)[:127], 400, {"ok": False, "error": TEXTO_VEC}),
]


class CaraPareja(unittest.TestCase):

    def test_C1_pareja_en_los_escenarios(self):
        for etiqueta, caras, pid, v in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                with Corrida(caras) as w:
                    codigo_w, datos_w = personas_escritura_rutas.cara(personas_escrituras, {"persona_id": pid, "vec": v})
                    escritas = w.escrituras()
                with Corrida(caras) as c:
                    codigo_c, datos_c = personas_cuenta.calcular("cara", cuerpo_del_calculo(pid, v), QUIEN)
                    self.assertEqual(c.escrituras(), [], "C2: el cálculo escribió")
                self.assertEqual((codigo_w, codigo_c), (200, 200))
                self.assertEqual(len(escritas), 1, "la escritura no mandó un PATCH de caras")
                self.assertEqual(datos_c["escrituras"], escritas, "C1: el cálculo no dice lo que la escritura mandó")
                self.assertEqual(datos_c["sin_valor"], [])
                self.assertEqual(len(escritas[0]["valores"][base.CARA_COLUMNA].split(base.CARA_SEPARADOR)), datos_w["ranuras"],
                                 "C1: el número de ranuras no es el de la escritura")

    def test_C2_y_C3_rechazos_iguales_y_sin_escribir(self):
        for etiqueta, caras, pid, v, esperado, cuerpo_esperado in RECHAZOS:
            with self.subTest(caso=etiqueta):
                with Corrida(caras) as w:
                    codigo_w, datos_w = personas_escritura_rutas.cara(personas_escrituras, {"persona_id": pid, "vec": v})
                    self.assertEqual(w.escrituras(), [], "la escritura escribió en un rechazo")
                with Corrida(caras) as c:
                    codigo_c, datos_c = personas_cuenta.calcular("cara", cuerpo_del_calculo(pid, v), QUIEN)
                    self.assertEqual(c.escrituras(), [], "C2: el cálculo escribió")
                self.assertEqual((codigo_w, datos_w), (esperado, cuerpo_esperado), "la escritura cambió su rechazo")
                self.assertEqual((codigo_c, datos_c), (esperado, cuerpo_esperado), "C3: el cálculo no da el rechazo de la escritura")

    def test_C2_cero_escrituras_al_calcular_tambien_con_la_base_caida_en_lecturas(self):
        for etiqueta, caras, pid, v in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                with Corrida(caras, caidas=("GET",)) as c:
                    codigo, datos = personas_cuenta.calcular("cara", cuerpo_del_calculo(pid, v), QUIEN)
                    self.assertEqual(c.escrituras(), [], "C2: el cálculo escribió con la base caída")
                self.assertEqual((codigo, datos), (502, {"ok": False, "error": TEXTO_NO_SE_GUARDO}))
        for etiqueta, caras, pid, v, _esperado, _cuerpo in RECHAZOS:
            with self.subTest(rechazo=etiqueta):
                with Corrida(caras, caidas=("GET",)) as c:
                    personas_cuenta.calcular("cara", cuerpo_del_calculo(pid, v), QUIEN)
                    self.assertEqual(c.escrituras(), [], "C2: el cálculo escribió con la base caída")

    def test_C4_el_calculo_cara_esta_registrado(self):
        self.assertIn("cara", personas_cuenta.CALCULOS)
        self.assertIn("cara", personas_cuenta.RUTAS)

    def test_C5_no_invalida_ninguna_cache_de_caras(self):
        for etiqueta, caras, pid, v in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                sentinela = {"sentinela": 1}
                with Corrida(caras) as c, mock.patch.object(base, "_caras_cache", {"data": sentinela}):
                    with mock.patch.object(base, "invalidate_caras", wraps=base.invalidate_caras) as espia:
                        personas_cuenta.calcular("cara", cuerpo_del_calculo(pid, v), QUIEN)
                    self.assertEqual(espia.call_count, 0, "C5: el cálculo invalidó la caché de caras")
                    self.assertIs(base._caras_cache["data"], sentinela, "C5: el cálculo tocó la caché de caras")
                    self.assertEqual(c.escrituras(), [])

    def test_C6_cuerpo_que_no_es_la_cara_da_400_y_no_escribe(self):
        ruta = "/api/personas/1/cara"
        cuerpos = [{"cara": "no-es-base64"}, {"cara": b64(vec(1)), "otra": 1}, {}, {"cara": 5},
                   {"cara": b64(vec(1)[:127])}]
        with Corrida({}) as c:
            for cuerpo in cuerpos:
                with self.subTest(cuerpo=sorted(cuerpo)):
                    codigo, _ = personas_cuenta.calcular("cara", dict(cuerpo, **{personas_cuenta.CLAVE_RUTA: ruta}), QUIEN)
                    self.assertEqual(codigo, 400)
            self.assertEqual(c.escrituras(), [], "C2: el cálculo escribió con un cuerpo malo")


if __name__ == "__main__":
    unittest.main()
