# -*- coding: utf-8 -*-
"""P11-6, GRUPO (f), `continuar` (fila 7): el cálculo de continuar (`personas_cuenta.CALCULOS["continuar"]`).

`continuar` termina una unión que quedó a medias: lee el registro `en_curso` (con el plan guardado) y corre `_union_correr`, la misma
pasada que `unir`. Con `solo_contar` no escribe: las escrituras quedan en `planeados`, en orden, y la respuesta es la de la escritura.

Los estados de partida salen de una unión de VERDAD cortada a propósito (el doble de NocoDB falla una operación): así el registro queda
`en_curso` con el plan que `unir` guardó. Se reusan de `test_calcular_grupo_f` la clase de corrida (`gf.Corrida`) y los escenarios de
`unir`, para que las pruebas de cero escrituras y de rechazos cubran los dos nombres del grupo.

Qué garantiza y con qué prueba:
  F1  PAREJA: en cada escenario que escribe, el cálculo dice EXACTAMENTE lo que `continuar` mandó al doble (tabla lógica, método, enlace y
      valores, en orden). En `continuar`, la única `sin_valor` es la hora de cierre (`uniones.PATCH.terminada_en`).
  F2  CERO ESCRITURAS AL CALCULAR, para cada nombre del grupo (`GRUPO_F`, sacado de `RUTAS` y `CALCULOS`) y sus escenarios.
  F3  RECHAZOS IGUALES: 404 sin unión, 502 registro ilegible, 502 lectura caída: el mismo código y cuerpo, y la escritura no escribe nada.
  F4  SIN CÁLCULO: aviso de «Por resolver», asistencia nueva, plan que no está al día y parada después de planear: 404 y cero escrituras.
  F5  FIJADO A MANO: las escrituras esperadas de un caso están escritas aquí a mano; ni la unión ni el cálculo las fijan.
  F6  NINGUNA CACHÉ al calcular (la escritura de verdad sí tira las cachés: control).
  F7  REGISTRO: `continuar` está en `CALCULOS` y en `RUTAS`; `deshacer` también (su prueba: `test_calcular_deshacer`); la ruta de `unir` se rechaza con 400 para `continuar`.

Lo que NO ve (declarado): la unión de la App en vivo; una caída de NocoDB en mitad de `continuar` (el cálculo supone que cada escritura se
confirma); una verificación final que no cuadra (`no_cuadra`: el cálculo no relee al cerrar, como en `unir`); el reloj de NocoDB (se fija).
"""
import contextlib
import copy
import json
import re
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
import personas_portal_escritura  # noqa: E402
import test_calcular_grupo_f as gf  # noqa: E402  (las corridas de `unir` y sus escenarios; misma forma de comparar)
import test_calcular_deshacer as gd  # noqa: E402  (los escenarios de `deshacer`, con su corrida)

QUIEN = gf.QUIEN
AHORA = gf.AHORA
CLAVE = gf.CLAVE
RUTA_UNIR = "/api/portal-personas/11/unir"
RUTA_CONTINUAR = "/api/portal-personas/11/unir/continuar"
T_U = gf.T_U
TABLAS_DE_LA_UNION = (base.T_PERSONAS, base.T_ASISTENCIAS, T_U)
UNION = {"otra": 12, "clave": CLAVE}
SESION_Y_PAR = {(base.T_PERSONAS, base.L_PERSONA_SESIONES, 12): [3], (base.T_SESIONES, base.L_MUSICOS, 3): [12]}
PROYECTO_Y_PAR = {(base.T_PERSONAS, base.L_PERSONA_PROYECTOS, 12): [7], (base.T_PROYECTOS, base.L_PROY_MIEMBROS, 7): [12]}

def ruta_de_tabla(tabla):
    """El patrón de la ruta de un `PATCH` o un `POST` a los registros de una tabla (sin `Id` ni enlace)."""
    return r"/api/v2/tables/%s/records$" % re.escape(tabla)


class CorridaCon(gf.Corrida):
    """Una corrida de `gf.Corrida` en la que una operación cae a propósito: `falla=(método, patrón de ruta, cuál vez)`."""

    def __init__(self, falla=None, **kw):
        super().__init__(**kw)
        if falla:
            _con_falla(self.doble, *falla)


def _con_falla(doble, metodo, patron, cuantas):
    """La `cuantas`-ésima vez que llega `metodo` a una ruta que casa con `patron`, la base no contesta (500). El pedido queda apuntado,
    como en `caidas`: la prueba ve que salió, y que no se escribió."""
    original = doble.responder
    cuenta = [0]

    def responder(metodo_, ruta, query, cuerpo):
        if metodo_ == metodo and re.search(patron, ruta):
            cuenta[0] += 1
            if cuenta[0] == cuantas:
                with doble._cerrojo:
                    doble.pedidos.append({"metodo": metodo_, "ruta": ruta, "query": dict(sorted(query.items())), "cuerpo": cuerpo})
                return 500, {"msg": "doble: la base no contesta (a propósito)"}
        return original(metodo_, ruta, query, cuerpo)
    doble.responder = responder


def a_medias(falla, despues=None, enlaces=None, tablas=None):
    """La unión de VERDAD, cortada por `falla`. Deja el registro `en_curso` y lo que alcanzó a escribir. Devuelve el estado de partida
    de `continuar` (`tablas` y `enlaces`, como los pide `gf.Corrida`). `despues(estado)` cambia el estado antes de devolverlo."""
    with CorridaCon(falla=falla, enlaces=enlaces, tablas=tablas or {base.T_ASISTENCIAS: []}) as c:
        codigo, datos = personas_portal_escritura.responder("unir", RUTA_UNIR, ("11",), json.dumps(UNION).encode(), QUIEN)
        if codigo != 502:
            raise AssertionError("la unión no se cortó: %r" % ((codigo, datos),))
        estado = {"tablas": {t: copy.deepcopy(c.doble.tablas[t]) for t in TABLAS_DE_LA_UNION},
                  "enlaces": {k: sorted(v) for k, v in c.doble.enlaces.items() if v}}
    if despues:
        despues(estado)
    return estado


def _asistencia_nueva_en_la_que_sobra(estado):
    """Una asistencia de la ficha que sobra (12) en la sesión 9, que el plan no tiene: la unión la movería en una pasada más."""
    estado["tablas"][base.T_ASISTENCIAS].append(dict(gf.ASISTENCIA, Id=950, persona_id=12, sesion_id=9))


def _casilla_de_queda_cambiada(estado):
    """Una casilla que la unión escribe en la ficha que queda cambia a mano: `marcar` la encuentra y para (`cambio_mientras_unias`)."""
    antes = json.loads(estado["tablas"][T_U][0]["antes"])
    casilla = next(c for c, d in antes["queda"].items() if isinstance(d["despues"], str))
    fila = next(f for f in estado["tablas"][base.T_PERSONAS] if f["Id"] == 11)
    fila[casilla] = "CAMBIO A MANO"


def correr_continuar(estado, calculo, cuerpo=None, caidas=(), envolver=None):
    """`continuar` de verdad (o su cálculo) sobre el estado de partida. Devuelve `(código, cuerpo, corrida)`. `envolver()` (opcional) es un
    context manager que envuelve SOLO la llamada (no el arranque ni la limpieza de la corrida): la prueba de cachés lo usa."""
    with gf.Corrida(enlaces=estado["enlaces"], tablas=estado["tablas"], caidas=caidas) as c:
        with (envolver() if envolver else contextlib.nullcontext()):
            if calculo:
                codigo, datos = personas_cuenta.calcular("continuar", dict(cuerpo or {}, ruta_de_la_escritura=RUTA_CONTINUAR), QUIEN)
            else:
                crudo = json.dumps(cuerpo).encode() if cuerpo else b""
                codigo, datos = personas_portal_escritura.responder("continuar", RUTA_CONTINUAR, ("11",), crudo, QUIEN)
        return codigo, datos, c


def correr_unir(e, calculo, envolver=None):
    """Un escenario de `unir` (de `test_calcular_grupo_f`), con la misma forma de correr que `correr_continuar`."""
    with gf.Corrida(enlaces=e.get("enlaces"), tablas=e.get("tablas"), caidas=e.get("caidas", ())) as c:
        with (envolver() if envolver else contextlib.nullcontext()):
            if calculo:
                codigo, datos = personas_cuenta.calcular("unir", dict(e["cuerpo"], ruta_de_la_escritura=gf.RUTA), QUIEN)
            else:
                codigo, datos = personas_portal_escritura.responder("unir", gf.RUTA, ("11",), json.dumps(e["cuerpo"]).encode(), QUIEN)
        return codigo, datos, c


def _caso(nombre, tipo, estado, cuerpo=None, caidas=()):
    return {"nombre": nombre, "tipo": tipo,
            "correr": lambda calculo, envolver=None: correr_continuar(estado(), calculo, cuerpo, caidas, envolver)}


def _caso_de_unir(e):
    """Un escenario de `unir` (de `test_calcular_grupo_f`) con la misma forma que los de `continuar`."""
    return {"nombre": e["nombre"], "tipo": e["tipo"], "correr": lambda calculo, envolver=None: correr_unir(e, calculo, envolver)}


ASISTENCIA_DE_LA_QUE_SOBRA = gf.asistencias((901, 12, 9))
CASOS_CONTINUAR = [
    _caso("cierre_a_medias", "pareja", lambda: a_medias(("PATCH", ruta_de_tabla(T_U), 1))),
    _caso("enlace_de_sesion_a_medias", "pareja", lambda: a_medias(("POST", r"/links/", 1), enlaces=SESION_Y_PAR)),
    _caso("enlace_de_proyecto_a_medias", "pareja", lambda: a_medias(("POST", r"/links/", 1), enlaces=PROYECTO_Y_PAR)),
    _caso("ficha_a_medias", "pareja", lambda: a_medias(("PATCH", ruta_de_tabla(base.T_PERSONAS), 1))),
    _caso("asistencia_nueva", "sin_calculo",
          lambda: a_medias(("POST", ruta_de_tabla(base.T_ASISTENCIAS), 1), tablas={base.T_ASISTENCIAS: ASISTENCIA_DE_LA_QUE_SOBRA})),
    _caso("plan_que_no_esta_al_dia", "sin_calculo",
          lambda: a_medias(("PATCH", ruta_de_tabla(base.T_PERSONAS), 1), despues=_asistencia_nueva_en_la_que_sobra)),
    _caso("parada_despues_de_planear", "sin_calculo",
          lambda: a_medias(("PATCH", ruta_de_tabla(base.T_PERSONAS), 1), despues=_casilla_de_queda_cambiada)),
    _caso("aviso_de_por_resolver", "sin_calculo", lambda: a_medias(("PATCH", ruta_de_tabla(base.T_PERSONAS), 1)),
          cuerpo={"aviso": "aviso-" + "c" * 40}),
    _caso("sin_union_en_curso", "rechazo", lambda: {"tablas": {T_U: []}, "enlaces": {}}),
    _caso("registro_ilegible", "rechazo", lambda: {"tablas": {T_U: [{"Id": 50, "clave": CLAVE, "estado": "en_curso", "queda_id": 11,
                                                                      "sobra_id": 12, "plan": "{}", "antes": "{}"}]}, "enlaces": {}}),
    _caso("lectura_del_registro_caida", "rechazo", lambda: a_medias(("PATCH", ruta_de_tabla(T_U), 1)), caidas=("GET",)),
]

# Los escenarios de `unir` se toman de `test_calcular_grupo_f` (no se repiten aquí).
CASOS_POR_NOMBRE = {"unir": [_caso_de_unir(e) for e in gf.ESCENARIOS],
                    "continuar": CASOS_CONTINUAR,
                    "deshacer": gd.CASOS_DESHACER}
# Los nombres del grupo salen de lo real: `RUTAS` (la ruta que casa con `/unir`) y `CALCULOS` (lo que tiene cálculo).
GRUPO_F = sorted(n for n in personas_cuenta.CALCULOS if "/unir" in personas_cuenta.RUTAS[n][1].pattern)


def caso_continuar(nombre):
    return next(c for c in CASOS_CONTINUAR if c["nombre"] == nombre)


class ContinuarGrupoF(unittest.TestCase):

    def test_F1_pareja_en_los_escenarios_que_escriben(self):
        for nombre in GRUPO_F:
            for caso in [c for c in CASOS_POR_NOMBRE[nombre] if c["tipo"] == "pareja"]:
                with self.subTest(nombre=nombre, escenario=caso["nombre"]):
                    codigo_r, datos_r, real = caso["correr"](False)
                    codigo_c, datos_c, _ = caso["correr"](True)
                    self.assertEqual(codigo_r, 200, datos_r)
                    self.assertEqual((codigo_c, datos_c.get("estado")), (200, "calculado"), datos_c)
                    self.assertEqual(datos_c["escrituras"], real.escrituras(), "el cálculo no dice lo que la escritura mandó a NocoDB")
                    if nombre == "continuar":
                        self.assertEqual(datos_c["sin_valor"], ["uniones.PATCH.terminada_en"])

    def test_F2_cero_escrituras_al_calcular_en_todo_el_grupo(self):
        self.assertEqual(GRUPO_F, ["continuar", "deshacer", "unir"], "el grupo cambió: esta prueba y CASOS_POR_NOMBRE tienen que cubrir el nombre nuevo")
        for nombre in GRUPO_F:
            self.assertTrue(CASOS_POR_NOMBRE[nombre], "el grupo %s no tiene escenarios" % nombre)
            for caso in CASOS_POR_NOMBRE[nombre]:
                with self.subTest(nombre=nombre, escenario=caso["nombre"]):
                    _, _, calc = caso["correr"](True)
                    self.assertEqual(gf.escrituras_de(calc), [], "el cálculo mandó una escritura a NocoDB")

    def test_F3_rechazos_iguales_y_sin_escribir(self):
        for nombre in GRUPO_F:
            for caso in [c for c in CASOS_POR_NOMBRE[nombre] if c["tipo"] == "rechazo"]:
                with self.subTest(nombre=nombre, escenario=caso["nombre"]):
                    codigo_r, datos_r, real = caso["correr"](False)
                    codigo_c, datos_c, _ = caso["correr"](True)
                    self.assertNotEqual(codigo_r, 200)
                    self.assertEqual(gf.escrituras_de(real), [], "la escritura escribió en un rechazo")
                    self.assertEqual((codigo_c, datos_c), (codigo_r, datos_r))

    def test_F4_sin_calculo_no_escribe(self):
        for nombre in GRUPO_F:
            for caso in [c for c in CASOS_POR_NOMBRE[nombre] if c["tipo"] == "sin_calculo"]:
                with self.subTest(nombre=nombre, escenario=caso["nombre"]):
                    codigo_c, datos_c, calc = caso["correr"](True)
                    self.assertEqual((codigo_c, datos_c), (404, personas_cuenta.ERROR_SIN_CALCULO))
                    self.assertEqual(gf.escrituras_de(calc), [])

    def test_F5_escrituras_fijadas_a_mano(self):
        """Lo que `continuar` escribe si la unión se cortó al enlazar la sesión 3 (la ficha que sobra, la 12, la tiene). Escrito a mano:
        el enlace se hace desde el lado de la sesión (`_union_mover_enlaces`), la ficha que queda recibe lo que la que sobra tenía en el
        campo de teléfono (`_union_resolver_contacto`: los dos teléfonos caben, y el de la 12 va al segundo), la que sobra se vacía y se
        marca, y la unión se cierra con su hora (fijada en `AHORA`)."""
        esperado = [
            {"tabla": "sesiones", "metodo": "POST", "enlace": "enlace:L_MUSICOS", "valores": {"registro": 3, "ligados": [11]}},
            {"tabla": "sesiones", "metodo": "DELETE", "enlace": "enlace:L_MUSICOS", "valores": {"registro": 3, "ligados": [12]}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"telefono_2": "18090001102"}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"nombre": None, "telefono": None, "unida_a": 11}},
            {"tabla": "uniones", "metodo": "PATCH", "enlace": None, "valores": {"estado": "unida", "terminada_en": AHORA}},
        ]
        caso = caso_continuar("enlace_de_sesion_a_medias")
        _, _, real = caso["correr"](False)
        self.assertEqual(real.escrituras(), esperado, "la escritura no hizo lo que el texto a mano dice")
        _, datos_c, _ = caso["correr"](True)
        self.assertEqual(datos_c["escrituras"], esperado, "el cálculo no dice lo que el texto a mano dice")

    def test_F6_ninguna_cache_al_calcular(self):
        vistos = []

        @contextlib.contextmanager
        def vigilar():
            with mock.patch.object(personas, "invalidate_personas") as p1, \
                    mock.patch.object(personas, "invalidate_portal_personas") as p2, \
                    mock.patch.object(base, "invalidate_caras") as p3:
                vistos.append((p1, p2, p3))
                yield

        for nombre in GRUPO_F:
            for caso in CASOS_POR_NOMBRE[nombre]:
                with self.subTest(nombre=nombre, escenario=caso["nombre"]):
                    del vistos[:]
                    caso["correr"](True, vigilar)
                    p1, p2, p3 = vistos[-1]
                    self.assertFalse(p1.called or p2.called or p3.called, "el cálculo tiró una caché")
        # control: `continuar` de verdad sí las tira (la escritura las pone al día)
        del vistos[:]
        caso_continuar("enlace_de_sesion_a_medias")["correr"](False, vigilar)
        _, p2, p3 = vistos[-1]
        self.assertTrue(p2.called and p3.called)

    def test_F7_registro(self):
        self.assertIn("continuar", personas_cuenta.CALCULOS)
        self.assertIn("continuar", personas_cuenta.RUTAS)
        self.assertIn("deshacer", personas_cuenta.CALCULOS)     # su prueba: test_calcular_deshacer
        codigo, datos = personas_cuenta.calcular("continuar", {"ruta_de_la_escritura": RUTA_UNIR}, QUIEN)
        self.assertEqual((codigo, datos), (400, personas_cuenta.ERROR_RUTA_AJENA))


if __name__ == "__main__":
    unittest.main()
