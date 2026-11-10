# -*- coding: utf-8 -*-
"""P11-6, GRUPO (d): el cálculo de PERMISO, BAJA y FOTO (`personas_cuenta.CALCULOS`, filas 3, 15 y 16 del diseño).

La App escribe estas tres en su modo contar (nombres de `escritura_de_personas_para_cuenta`, `registro/server.py`):
  permiso  POST /api/portal-personas/<id>/permiso   -> `personas.anotar_permiso` (un renglón por ficha del grupo)
  baja     POST /api/servicio/mercadeo/baja        -> `personas.baja_de_natalia` (anota la baja en cada ficha de la identidad)
  foto     POST /api/servicio/mercadeo/foto        -> `personas.foto_de_natalia` (anota el permiso de fotos en cada ficha)
Las tres escriben SOLO la tabla de anotaciones (POST). El cálculo corre la MISMA función con `solo_contar=True`: decide igual, pero en
vez de cada POST guarda la forma del renglón y lo suma a una lista en memoria (`previstas`), que las lecturas siguientes ven. Así una
baja de dos fichas del mismo grupo predice lo mismo que la escritura (la segunda ficha ya lee la baja que la primera acaba de anotar).

Qué garantiza y con qué prueba:
  D1  PAREJA en los escenarios de `ESCENARIOS` (éxito): el cálculo dice EXACTAMENTE lo que la escritura mandó a NocoDB, en la forma de
      la App (tabla con su nombre lógico, método, cuerpo sin `Id`, en orden). Los `Id` que asigna la base no se normalizan: el cálculo no
      los usa. El reloj (`_ahora_utc`, `hoy_str`) se fija en las dos corridas.
  D2  CERO ESCRITURAS AL CALCULAR: en cada escenario y cada rechazo, el cálculo no manda POST, PATCH, PUT ni DELETE; también con la base
      caída en lecturas.
  D3  RECHAZOS IGUALES Y SIN ESCRIBIR: en cada rechazo (400, 404, 409, 502 previo a escribir), el cálculo da el MISMO código y el MISMO
      cuerpo que la escritura, y la escritura no escribió.
  D4  REGISTRO: `permiso`, `baja` y `foto` están en `CALCULOS` y en `RUTAS`, y la ruta ajena se rechaza con 400.
  D5  NINGUNA CACHÉ: el cálculo no llama a `invalidate_personas`, `invalidate_portal_personas` ni `invalidate_caras`.

Lo que NO ve (declarado): la escritura de la App en vivo (K2d en `test_contrato_app_p11.py` compara con la escritura del programa
capturada en el doble); los hilos propios; las escrituras de otros procesos entre el cálculo y la escritura; y una caída de NocoDB
en mitad de la escritura (el cálculo supone que todo se confirma: lo que la App compara solo si NocoDB confirmó cada escritura).
"""
import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import doble_nocodb  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import test_calcular_grupo_a as g  # noqa: E402

QUIEN = g.QUIEN
GRUPO_D = ("permiso", "baja", "foto")
TA = doble_nocodb.TABLA_ANOTACIONES
TEXTO_RUTA_AJENA = personas_cuenta.ERROR_RUTA_AJENA["error"]


def renglon(i, ficha, clase, valor, **resto):
    """Un renglón de anotaciones con las columnas que lee la App (`ANOTACIONES_LEE`), datos ficticios."""
    return dict({"Id": i, "ficha_id": ficha, "clase": clase, "valor": valor, "canal": "", "dicho_el": "", "quien": "Persona de prueba quien",
                 "cuando": "2026-10-03T09:00:00Z"}, **resto)


def con_anotaciones(*extra):
    """Las anotaciones del doble más `extra` (un escenario con un renglón de permiso, de baja o de foto que ya existe)."""
    return copy.deepcopy(doble_nocodb.ANOTACIONES) + [dict(r) for r in extra]


# ---- Permiso: (etiqueta, ficha, pedido, tablas de anotaciones, confirmo_o_none) -------------------------------------------------------
# Las fichas del doble: 1 (origen, unida a la 4), 2 (permiso «si», renglón 2), 3 (quitada), 4 (unida a la 1).
PERMISO_ESCRIBE = [
    ("grupo {1,4} sin permiso: un renglón por ficha, la abierta al final", 1, {"valor": "no", "visto": None}, None),
    ("ficha sola con permiso «si» visto: escribe «no»", 2, {"valor": "no", "visto": 2}, None),
    ("ficha 4 abierta: el grupo {1,4} se escribe en el orden de la escritura", 4, {"valor": "si", "visto": None}, None),
    ("completar: el grupo lee «no» y la ficha 4 no lo lee", 1, {"valor": "no", "visto": None},
     [renglon(3, 1, "permiso", "no")]),
    ("baja confirmada: cambia la baja de la ficha", 2, {"valor": "no", "visto": 3, "confirmo": True},
     [renglon(3, 2, "permiso", "baja")]),
]
PERMISO_RECHAZA = [
    ("visto viejo: 409 cambio", 2, {"valor": "no", "visto": None}, None),
    ("baja sin confirmar: 409 pide_confirmar", 2, {"valor": "no", "visto": 3}, [renglon(3, 2, "permiso", "baja")]),
    ("valor que no existe: 400", 2, {"valor": "tal vez", "visto": 2}, None),
    ("falta visto: 400", 2, {"valor": "no"}, None),
    ("clave que no se puede mandar (quien): 400", 2, {"valor": "no", "visto": 2, "quien": "otra"}, None),
    ("ficha que no existe: lo que diga la lectura", 99, {"valor": "no", "visto": None}, None),
]
# Ya estaba (200, sin escribir): el grupo lee lo pedido y cada ficha también.
PERMISO_YA_ESTABA = [("ya estaba: la ficha ya lee «si»", 2, {"valor": "si", "visto": 2}, None)]

# ---- Baja: (etiqueta, pedido, tablas de anotaciones) --------------------------------------------------------------------------------
BAJA_ESCRIBE = [
    ("identidad con dos fichas unidas: la segunda ya lee la baja que escribió la primera", {"identidad": "18097770001", "dicho_el": "2026-11-07", "clave": "k1"}, None),
    ("ficha con permiso «si»: reintenta con el renglón que dice el 409", {"identidad": "18097770002", "dicho_el": "2026-11-07", "clave": "k2"}, None),
    ("ficha quitada (guardada aparte): se anota igual", {"identidad": "18097770003", "dicho_el": "2026-11-07", "clave": "k3"}, None),
]
BAJA_RECHAZA = [
    ("sin ficha con esa identidad: 404", {"identidad": "18097770009", "dicho_el": "2026-11-07", "clave": "k4"}, None),
    ("pedido malo (identidad vacía): 400", {"identidad": "", "dicho_el": "2026-11-07", "clave": "k5"}, None),
    ("fecha de otro día: 400", {"identidad": "18097770002", "dicho_el": "2026-11-11", "clave": "k6"}, None),
]
BAJA_YA_ESTABA = [("ya estaba: la ficha ya lee baja", {"identidad": "18097770002", "dicho_el": "2026-11-07", "clave": "k7"},
                   [renglon(3, 2, "permiso", "baja")])]

# ---- Foto: (etiqueta, pedido, tablas de anotaciones) --------------------------------------------------------------------------------
FOTO_ESCRIBE = [
    ("identidad con dos fichas unidas: escribe en las dos", {"identidad": "18097770001", "valor": "si"}, None),
    ("ficha sola sin foto: escribe «no»", {"identidad": "18097770002", "valor": "no"}, None),
]
FOTO_RECHAZA = [
    ("sin ficha con esa identidad: 404", {"identidad": "18097770009", "valor": "si"}, None),
    ("valor que no existe: 400", {"identidad": "18097770002", "valor": "tal vez"}, None),
    ("pedido malo (sin valor): 400", {"identidad": "18097770002"}, None),
]
FOTO_YA_ESTABA = [("ya estaba: la ficha ya lee «no»", {"identidad": "18097770002", "valor": "no"},
                   [renglon(3, 2, "foto", "no", quien="Natalia")])]


def escenarios_de_escritura():
    """(nombre del cálculo, ficha de la ruta o None, cuerpo de la escritura, etiqueta, tablas extra, confirmo_o_None) para el éxito."""
    salida = []
    for etiqueta, ficha, pedido, extra in PERMISO_ESCRIBE + PERMISO_RECHAZA + PERMISO_YA_ESTABA:
        salida.append(("permiso", ficha, pedido, etiqueta, extra))
    for etiqueta, pedido, extra in BAJA_ESCRIBE + BAJA_RECHAZA + BAJA_YA_ESTABA:
        salida.append(("baja", None, pedido, etiqueta, extra))
    for etiqueta, pedido, extra in FOTO_ESCRIBE + FOTO_RECHAZA + FOTO_YA_ESTABA:
        salida.append(("foto", None, pedido, etiqueta, extra))
    return salida


ESCENARIOS = escenarios_de_escritura()
# Los que escriben (para D1): los de ESCRIBE y los de «ya estaba», que no escriben pero tienen que coincidir (cero escrituras).
ETIQUETAS_ESCRIBEN = {x[0] for x in PERMISO_ESCRIBE + BAJA_ESCRIBE + FOTO_ESCRIBE}
ETIQUETAS_YA_ESTABA = {x[0] for x in PERMISO_YA_ESTABA + BAJA_YA_ESTABA + FOTO_YA_ESTABA}
ESCRIBEN = [e for e in ESCENARIOS if e[3] in ETIQUETAS_ESCRIBEN]
RECHAZOS = [e for e in ESCENARIOS if e[3] not in ETIQUETAS_ESCRIBEN | ETIQUETAS_YA_ESTABA]


def ruta_de(nombre, ficha):
    """La ruta que la App manda en `ruta_de_la_escritura` (la de la App: `/api/servicio/mercadeo/...` para baja y foto)."""
    if nombre == "permiso":
        return "/api/portal-personas/%d/permiso" % ficha
    if nombre == "baja":
        return "/api/servicio/mercadeo/baja"
    if nombre == "foto":
        return "/api/servicio/mercadeo/foto"
    raise AssertionError(nombre)


def cuerpo_del_calculo(nombre, ficha, pedido):
    """El cuerpo que manda la App al cálculo: el pedido SIN ids (la ficha va en la ruta) más `ruta_de_la_escritura`."""
    return dict(pedido, **{personas_cuenta.CLAVE_RUTA: ruta_de(nombre, ficha or 0)})


def escribir(nombre, ficha, pedido, confirmo=None):
    """La escritura de verdad del programa, como la llama su ruta (`servidor.py` / `personas_mercadeo.py` / `personas_portal_escritura.py`)."""
    if nombre == "permiso":
        return personas.anotar_permiso(ficha, pedido, QUIEN)
    if nombre == "baja":
        return personas.baja_de_natalia(pedido)
    if nombre == "foto":
        return personas.foto_de_natalia(pedido)
    raise AssertionError(nombre)


def corrida(tablas_extra=None, **kw):
    """Una `g.Corrida` con las anotaciones de este escenario (las del doble más `tablas_extra`)."""
    c = g.Corrida(**kw)
    if tablas_extra is not None:
        c.doble.tablas[TA] = con_anotaciones(*tablas_extra)
    return c


def escrituras_de(c):
    """Las escrituras del doble en la forma de la App (`g.forma_app`, sin `Id`)."""
    return g.forma_app(c.escrituras())


class GrupoD(unittest.TestCase):

    def test_D1_pareja_en_los_escenarios_que_escriben(self):
        for nombre, ficha, pedido, etiqueta, extra in ESCRIBEN:
            with self.subTest(escenario=etiqueta):
                with corrida(extra) as w:
                    codigo_w, datos_w = escribir(nombre, ficha, dict(pedido))
                    escritas = escrituras_de(w)
                with corrida(extra) as c:
                    codigo_c, datos_c = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                    self.assertEqual(c.escrituras(), [], "D2: el cálculo escribió")
                self.assertEqual(codigo_w, 200, "la escritura no dio 200 (%s): %r" % (etiqueta, datos_w))
                self.assertEqual(codigo_c, 200, "el cálculo no dio 200 (%s): %r" % (etiqueta, datos_c))
                self.assertTrue(escritas, "la escritura no escribió (%s)" % etiqueta)
                self.assertEqual(datos_c["escrituras"], escritas, "D1: el cálculo no dice lo que la escritura mandó (%s)" % etiqueta)

    def test_D1_los_ya_estaba_no_escriben_y_el_calculo_no_escribe_nada(self):
        for nombre, ficha, pedido, etiqueta, extra in ESCENARIOS:
            if etiqueta not in ETIQUETAS_YA_ESTABA:
                continue
            with self.subTest(escenario=etiqueta):
                with corrida(extra) as w:
                    codigo_w, datos_w = escribir(nombre, ficha, dict(pedido))
                    self.assertEqual(w.escrituras(), [], "la escritura escribió en «ya estaba»")
                with corrida(extra) as c:
                    codigo_c, datos_c = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                    self.assertEqual(c.escrituras(), [], "D2: el cálculo escribió")
                self.assertEqual((codigo_w, codigo_c), (200, 200))
                self.assertEqual(datos_c["escrituras"], [], "D1: el cálculo dice escrituras donde la escritura no escribió")

    def test_D2_D3_rechazos_iguales_y_sin_escribir(self):
        for nombre, ficha, pedido, etiqueta, extra in RECHAZOS:
            with self.subTest(rechazo=etiqueta):
                with corrida(extra) as w:
                    codigo_w, datos_w = escribir(nombre, ficha, dict(pedido))
                    self.assertEqual(w.escrituras(), [], "la escritura escribió en un rechazo (%s)" % etiqueta)
                with corrida(extra) as c:
                    codigo_c, datos_c = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                    self.assertEqual(c.escrituras(), [], "D2: el cálculo escribió en un rechazo (%s)" % etiqueta)
                self.assertNotEqual(codigo_w, 200, "el escenario no es un rechazo (%s)" % etiqueta)
                self.assertEqual((codigo_c, datos_c), (codigo_w, datos_w), "D3: el cálculo no da el rechazo de la escritura (%s)" % etiqueta)

    def test_D2_cero_escrituras_con_la_base_caida_en_lecturas(self):
        for nombre, ficha, pedido, etiqueta, extra in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                with corrida(extra, caidas=("GET",)) as c:
                    codigo, datos = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                    self.assertEqual(c.escrituras(), [], "D2: el cálculo escribió con la base caída")
                self.assertNotEqual(codigo, 200, "con la base caída en lecturas no puede haber cálculo (%s)" % etiqueta)

    def test_D4_registro(self):
        for nombre in GRUPO_D:
            self.assertIn(nombre, personas_cuenta.CALCULOS)
            self.assertIn(nombre, personas_cuenta.RUTAS)
        # Una ruta ajena (la de la baja para el cálculo de la foto) da 400 y no calcula nada.
        with corrida() as c:
            codigo, datos = personas_cuenta.calcular("foto", cuerpo_del_calculo("baja", None, {"identidad": "18097770002", "dicho_el": "2026-11-07", "clave": "k"}), QUIEN)
            self.assertEqual((codigo, datos), (400, {"error": TEXTO_RUTA_AJENA}))
            self.assertEqual(c.escrituras(), [])

    def test_D5_ninguna_cache_se_invalida(self):
        for nombre, ficha, pedido, etiqueta, extra in ESCENARIOS:
            with self.subTest(escenario=etiqueta):
                with corrida(extra) as c:
                    with mock.patch.object(personas, "invalidate_personas", wraps=personas.invalidate_personas) as a, \
                            mock.patch.object(personas, "invalidate_portal_personas", wraps=personas.invalidate_portal_personas) as b, \
                            mock.patch.object(base, "invalidate_caras", wraps=base.invalidate_caras) as d:
                        personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                    self.assertEqual((a.call_count, b.call_count, d.call_count), (0, 0, 0), "D5: el cálculo invalidó una caché")
                    self.assertEqual(c.escrituras(), [])


if __name__ == "__main__":
    unittest.main()
