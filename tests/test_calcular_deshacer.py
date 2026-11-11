# -*- coding: utf-8 -*-
"""P11-6, GRUPO (f), `deshacer` (fila 8): el cálculo de deshacer (`personas_cuenta.CALCULOS["deshacer"]`).

`deshacer` deshace una unión que ya quedó `unida` (o a medias): `_deshacer_correr` vuelve las casillas de las dos fichas, devuelve las
asistencias y los enlaces, apunta en la bandeja si la unión la hizo la puerta, y marca el registro `deshecha`. Con `solo_contar` no escribe:
las escrituras quedan en `planeados`, en orden (ver `personas._deshacer_correr`).

Los estados de partida salen de una UNIÓN DE VERDAD (`unir` de verdad contra el doble, y, para los que lo piden, un `deshacer` de verdad
también). Así el registro y las fichas tienen lo que `unir` dejó. Se reusan de `test_calcular_grupo_f` la clase base de corrida y las
constantes; las corridas de esta prueba también fijan el banco de la bandeja (`base.T_BANDEJA_PERSONAS`), que la unión usa en el apunte.

Qué garantiza y con qué prueba:
  F1  PAREJA: en cada escenario que escribe, el cálculo dice EXACTAMENTE lo que `deshacer` mandó al doble (tabla lógica, método, enlace y
      valores, en orden), y su `sin_valor` es el que el escenario declara.
  F2  CERO ESCRITURAS AL CALCULAR, en todos los escenarios (también los rechazos y los que no se predicen).
  F3  RECHAZOS IGUALES: el mismo código y cuerpo que `deshacer` de verdad, y la escritura de verdad no escribió nada.
  F4  SIN CÁLCULO: asistencia nueva, aviso de «Por resolver», parada después de planear y fallo después de planear: 404 y cero escrituras.
  F5  FIJADO A MANO: las escrituras esperadas de dos escenarios están escritas aquí a mano (sacadas del texto de `_deshacer_correr`, no del
      código): la unión sin enlaces, y la unión con un proyecto (el enlace de proyectos sale con `valores` = {registro, ligados}).
  F6  NINGUNA CACHÉ al calcular (la escritura de verdad sí tira las cachés: control).
  F7  REGISTRO: `deshacer` está en `CALCULOS` y en `RUTAS`; la ruta de `unir` se rechaza con 400 para `deshacer`.

Lo que NO ve (declarado): la unión y el deshacer de la App en vivo; una caída de NocoDB en mitad del deshacer (el cálculo supone que cada
escritura se confirma); la verificación del paso e (`deshacer_no_cuadra`) y la relectura final, que el cálculo no hace; el reloj de
NocoDB (se fija); una escritura ajena sobre las fichas entre planear y escribir (carrera, no medida).
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
import doble_nocodb  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_portal_escritura  # noqa: E402
import test_calcular_grupo_f as gf  # noqa: E402  (la corrida base, las constantes y la forma de comparar)

QUIEN = gf.QUIEN
AHORA = gf.AHORA
CLAVE = gf.CLAVE
RUTA_UNIR = gf.RUTA
RUTA_DESHACER = "/api/portal-personas/11/unir/deshacer"
T_U = gf.T_U
T_BANDEJA = doble_nocodb.T_BANDEJA
TABLAS_DE_LA_UNION = (base.T_PERSONAS, base.T_ASISTENCIAS, T_U, T_BANDEJA)
UNION = {"otra": 12, "clave": CLAVE}
PROYECTO_Y_PAR = {(base.T_PERSONAS, base.L_PERSONA_PROYECTOS, 12): [7], (base.T_PROYECTOS, base.L_PROY_MIEMBROS, 7): [12]}
SESION_Y_PAR = {(base.T_PERSONAS, base.L_PERSONA_SESIONES, 12): [3], (base.T_SESIONES, base.L_MUSICOS, 3): [12]}
SESION_Y_PAGO = dict(SESION_Y_PAR, **{})
SESION_Y_PAGO[(base.T_PERSONAS, base.L_PERSONA_PAGOS, 12)] = [5]
SESION_DE_LA_QUE_QUEDA = {(base.T_PERSONAS, base.L_PERSONA_SESIONES, 11): [9], (base.T_SESIONES, base.L_MUSICOS, 9): [11]}
RUTA_PERSONAS = r"/api/v2/tables/%s/records" % re.escape(base.T_PERSONAS)


def _con_falla(doble, metodo, patron, cuantas):
    """La `cuantas`-ésima vez que llega `metodo` a una ruta que casa con `patron`, la base no contesta (500). El pedido queda apuntado."""
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


class CorridaDeshacer(gf.Corrida):
    """La corrida de `gf.Corrida`, con la bandeja apuntada al doble (la unión y el deshacer del apunte la usan) y una falla opcional
    `falla=(método, patrón de ruta, cuál vez)`."""

    def __init__(self, falla=None, **kw):
        super().__init__(**kw)
        self.parches.append(mock.patch.object(base, "T_BANDEJA_PERSONAS", T_BANDEJA))
        if falla:
            _con_falla(self.doble, *falla)


def estado_de(c):
    """Lo que queda en el doble después de una escritura de verdad: las tablas de la unión y los enlaces que tienen algo."""
    return {"tablas": {t: copy.deepcopy(c.doble.tablas[t]) for t in TABLAS_DE_LA_UNION},
            "enlaces": {k: sorted(v) for k, v in c.doble.enlaces.items() if v}}


def tras_unir(cuerpo, quien=QUIEN, enlaces=None, tablas=None, despues=None):
    """`unir` de verdad, sin cortar, contra el doble. Devuelve el estado que deja. `despues(estado)` lo cambia a mano antes de devolverlo."""
    with CorridaDeshacer(enlaces=enlaces, tablas=tablas or {base.T_ASISTENCIAS: []}) as c:
        codigo, datos = personas_portal_escritura.responder("unir", RUTA_UNIR, ("11",), json.dumps(cuerpo).encode(), quien)
        if codigo != 200:
            raise AssertionError("la unión de partida no salió: %r" % ((codigo, datos),))
        estado = estado_de(c)
    if despues:
        despues(estado)
    return estado


def tras_deshacer(estado_unido, cuerpo=None):
    """`deshacer` de verdad sobre un estado unido. Devuelve el estado que deja (la unión queda `deshecha`)."""
    codigo, datos, c = correr_deshacer(estado_unido, False, cuerpo)
    if codigo != 200:
        raise AssertionError("el deshacer de partida no salió: %r" % ((codigo, datos),))
    return estado_de(c)


def correr_deshacer(estado, calculo, cuerpo=None, caidas=(), falla=None, envolver=None):
    """`deshacer` de verdad (o su cálculo) sobre el estado de partida. Devuelve `(código, cuerpo, corrida)`. `envolver()` (opcional) es un
    context manager que envuelve SOLO la llamada: la prueba de cachés lo usa."""
    with CorridaDeshacer(falla=falla, enlaces=estado.get("enlaces"), tablas=estado.get("tablas"), caidas=caidas) as c:
        with (envolver() if envolver else contextlib.nullcontext()):
            if calculo:
                codigo, datos = personas_cuenta.calcular("deshacer", dict(cuerpo or {}, ruta_de_la_escritura=RUTA_DESHACER), QUIEN)
            else:
                crudo = json.dumps(cuerpo).encode() if cuerpo else b""
                codigo, datos = personas_portal_escritura.responder("deshacer", RUTA_DESHACER, ("11",), crudo, QUIEN)
        return codigo, datos, c


def _caso(nombre, tipo, estado, cuerpo=None, caidas=(), falla=None, sin_valor=None):
    return {"nombre": nombre, "tipo": tipo, "sin_valor": sin_valor,
            "correr": lambda calculo, envolver=None: correr_deshacer(estado(), calculo, cuerpo, caidas, falla, envolver)}


def _asistencia_de_vuelta(estado):
    """La ficha que sobró (12) tiene otra vez una asistencia en la sesión 9, de la que la unión la había sacado: `deshacer` la liga."""
    estado["tablas"][base.T_ASISTENCIAS].append(dict(gf.ASISTENCIA, Id=903, persona_id=12, sesion_id=9))


def _queda_unida_a_otra(estado):
    fila = next(f for f in estado["tablas"][base.T_PERSONAS] if f["Id"] == 11)
    fila["unida_a"] = 77


def _sobra_unida_a_otra(estado):
    """La ficha que sobró se unió a otra después de unir: `deshacer` ya escribió la que quedó (paso a) y para al ver esto (paso b)."""
    fila = next(f for f in estado["tablas"][base.T_PERSONAS] if f["Id"] == 12)
    fila["unida_a"] = 99


def _ya_deshecha_sin_apunte():
    """Una unión de la puerta, ya deshecha de verdad, cuya bandeja perdió el apunte: repetir el «deshacer» lo apunta otra vez (`ya_estaba`)."""
    estado = tras_deshacer(tras_unir(UNION, quien=personas.UNION_SOLA_QUIEN["meta"]))
    estado["tablas"][T_BANDEJA] = []
    return estado


def _registro_ilegible():
    return {"tablas": {T_U: [{"Id": 50, "clave": CLAVE, "estado": "unida", "queda_id": 11, "sobra_id": 12, "plan": "{}", "antes": "{}"}]},
            "enlaces": {}}


AVISO = "aviso-" + "c" * 40
CASOS_DESHACER = [
    # Parejas: cada uno escribe; el cálculo tiene que decir lo mismo que `deshacer` mandó al doble.
    _caso("deshacer_tras_unir", "pareja", lambda: tras_unir(UNION), sin_valor=["uniones.PATCH.deshecha_en"]),
    _caso("deshacer_con_proyecto", "pareja", lambda: tras_unir(UNION, enlaces=PROYECTO_Y_PAR),
          sin_valor=["uniones.PATCH.deshecha_en"]),
    _caso("deshacer_con_sesion_y_pago", "pareja", lambda: tras_unir(UNION, enlaces=SESION_Y_PAGO),
          sin_valor=["uniones.PATCH.deshecha_en"]),
    _caso("deshacer_con_asistencia_de_vuelta", "pareja",
          lambda: tras_unir(UNION, tablas={base.T_ASISTENCIAS: gf.asistencias((901, 12, 9), (902, 11, 9))},
                            enlaces=dict(SESION_DE_LA_QUE_QUEDA), despues=_asistencia_de_vuelta),
          sin_valor=["uniones.PATCH.deshecha_en"]),
    _caso("deshacer_de_la_puerta", "pareja", lambda: tras_unir(UNION, quien=personas.UNION_SOLA_QUIEN["meta"]),
          sin_valor=["bandeja.POST.Id", "uniones.PATCH.deshecha_en"]),
    _caso("deshacer_ya_estaba", "pareja", lambda: tras_deshacer(tras_unir(UNION)), cuerpo={"union": 1}, sin_valor=[]),
    _caso("deshacer_ya_estaba_sin_apunte", "pareja", _ya_deshecha_sin_apunte, cuerpo={"union": 1}, sin_valor=["bandeja.POST.Id"]),
    # Rechazos: el mismo código y cuerpo que el deshacer de verdad, y cero escrituras.
    _caso("sin_union", "rechazo", lambda: {"tablas": {T_U: []}, "enlaces": {}}),
    _caso("union_que_no_es_la_que_se_vio", "rechazo", lambda: tras_unir(UNION), cuerpo={"union": 99}),
    _caso("sobra_de_otro_aviso", "rechazo", lambda: tras_unir(UNION), cuerpo={"sobra": 77}),
    _caso("queda_unida_despues", "rechazo", lambda: tras_unir(UNION, despues=_queda_unida_a_otra)),
    _caso("registro_ilegible", "rechazo", _registro_ilegible),
    _caso("lectura_del_registro_caida", "rechazo", lambda: tras_unir(UNION), caidas=("GET",)),
    _caso("cuerpo_con_union_ilegible", "rechazo", lambda: tras_unir(UNION), cuerpo={"union": "x"}),
    # Sin cálculo: lo que la base decide al escribir, o lo que pasa después de planear escrituras.
    _caso("sin_calculo_asistencia_nueva", "sin_calculo",
          lambda: tras_unir(UNION, tablas={base.T_ASISTENCIAS: gf.asistencias((901, 12, 9))})),
    _caso("sin_calculo_aviso_de_por_resolver", "sin_calculo", lambda: tras_unir(UNION), cuerpo={"aviso": AVISO}),
    _caso("sin_calculo_parada_despues_de_planear", "sin_calculo", lambda: tras_unir(UNION, despues=_sobra_unida_a_otra)),
    # Lectura 3 de la ficha `personas` en el deshacer de verdad: 1 la marca de la que queda, 2 el paso a (la que queda), 3 el paso b (la que sobró).
    _caso("sin_calculo_fallo_despues_de_planear", "sin_calculo", lambda: tras_unir(UNION), falla=("GET", RUTA_PERSONAS, 3)),
]
CASOS_POR_NOMBRE = {"deshacer": CASOS_DESHACER}
GRUPO_DESHACER = sorted(n for n in personas_cuenta.CALCULOS if "/unir" in personas_cuenta.RUTAS[n][1].pattern)


def caso_de(nombre):
    return next(c for c in CASOS_DESHACER if c["nombre"] == nombre)


class DeshacerGrupoF(unittest.TestCase):

    def test_F1_pareja_en_los_escenarios_que_escriben(self):
        for caso in [c for c in CASOS_DESHACER if c["tipo"] == "pareja"]:
            with self.subTest(escenario=caso["nombre"]):
                codigo_r, datos_r, real = caso["correr"](False)
                codigo_c, datos_c, _ = caso["correr"](True)
                self.assertEqual(codigo_r, 200, datos_r)
                self.assertEqual((codigo_c, datos_c.get("estado")), (200, "calculado"), datos_c)
                self.assertEqual(datos_c["escrituras"], real.escrituras(), "el cálculo no dice lo que deshacer mandó a NocoDB")
                self.assertEqual(datos_c["sin_valor"], caso["sin_valor"], "el `sin_valor` del cálculo no es el que el escenario declara")

    def test_F2_cero_escrituras_al_calcular(self):
        self.assertEqual(GRUPO_DESHACER, ["continuar", "deshacer", "unir"], "el grupo cambió: revisa esta prueba y la de `continuar`")
        for caso in CASOS_DESHACER:
            with self.subTest(escenario=caso["nombre"]):
                _, _, calc = caso["correr"](True)
                self.assertEqual(gf.escrituras_de(calc), [], "el cálculo mandó una escritura a NocoDB")

    def test_F3_rechazos_iguales_y_sin_escribir(self):
        for caso in [c for c in CASOS_DESHACER if c["tipo"] == "rechazo"]:
            with self.subTest(escenario=caso["nombre"]):
                codigo_r, datos_r, real = caso["correr"](False)
                codigo_c, datos_c, _ = caso["correr"](True)
                self.assertNotEqual(codigo_r, 200)
                self.assertEqual(gf.escrituras_de(real), [], "deshacer escribió en un rechazo")
                self.assertEqual((codigo_c, datos_c), (codigo_r, datos_r))

    def test_F4_sin_calculo_no_escribe(self):
        for caso in [c for c in CASOS_DESHACER if c["tipo"] == "sin_calculo"]:
            with self.subTest(escenario=caso["nombre"]):
                codigo_c, datos_c, calc = caso["correr"](True)
                self.assertEqual((codigo_c, datos_c), (404, personas_cuenta.ERROR_SIN_CALCULO))
                self.assertEqual(gf.escrituras_de(calc), [])

    def test_F4b_los_sin_calculo_si_escriben_de_verdad(self):
        """El control de F4: lo que dice «sin cálculo» es un camino que la unión de verdad sí recorre (no es un rechazo disfrazado). En los
        de «después de planear», `deshacer` de verdad escribe algo antes de parar."""
        for nombre in ["sin_calculo_parada_despues_de_planear", "sin_calculo_fallo_despues_de_planear"]:
            with self.subTest(escenario=nombre):
                codigo_r, _, real = caso_de(nombre)["correr"](False)
                self.assertNotEqual(codigo_r, 200)
                self.assertTrue(gf.escrituras_de(real), "la parada o el fallo de verdad no escribió nada antes: el motivo no es «después de planear»")

    def test_F5_escrituras_fijadas_a_mano(self):
        """Lo que `deshacer` escribe, escrito a mano desde el texto de `_deshacer_correr` (no desde el código).
        Unión sin enlaces (`deshacer_tras_unir`): el registro pasa a `deshaciendo`; la ficha que quedó vuelve a lo que tenía en su teléfono 2
        (vacío); la que sobró recupera su nombre y su teléfono y se le quita la marca; el registro queda `deshecha` con quién y cuándo."""
        esperado = [
            {"tabla": "uniones", "metodo": "PATCH", "enlace": None, "valores": {"estado": "deshaciendo"}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"telefono_2": ""}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"nombre": "Union Uno", "telefono": "18090001102", "unida_a": None}},
            {"tabla": "uniones", "metodo": "PATCH", "enlace": None, "valores": {"estado": "deshecha", "deshecha_por": QUIEN, "deshecha_en": AHORA}},
        ]
        caso = caso_de("deshacer_tras_unir")
        _, _, real = caso["correr"](False)
        self.assertEqual(real.escrituras(), esperado, "la escritura no hizo lo que el texto a mano dice")
        _, datos_c, _ = caso["correr"](True)
        self.assertEqual(datos_c["escrituras"], esperado, "el cálculo no dice lo que el texto a mano dice")

    def test_F5b_el_enlace_de_proyectos_sale_con_registro_y_ligados(self):
        """Unión con el proyecto 7 (de la sobrante, la 12): `deshacer` liga el proyecto 7 a la 12 (registro 7, ligados [12]) y lo desliga de
        la 11 (registro 7, ligados [11]); ninguno de los dos va en `sin_valor`. Escrito a mano."""
        esperado = [
            {"tabla": "uniones", "metodo": "PATCH", "enlace": None, "valores": {"estado": "deshaciendo"}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"telefono_2": ""}},
            {"tabla": "personas", "metodo": "PATCH", "enlace": None, "valores": {"nombre": "Union Uno", "telefono": "18090001102", "unida_a": None}},
            {"tabla": "proyectos", "metodo": "POST", "enlace": "enlace:L_PROY_MIEMBROS", "valores": {"registro": 7, "ligados": [12]}},
            {"tabla": "proyectos", "metodo": "DELETE", "enlace": "enlace:L_PROY_MIEMBROS", "valores": {"registro": 7, "ligados": [11]}},
            {"tabla": "uniones", "metodo": "PATCH", "enlace": None, "valores": {"estado": "deshecha", "deshecha_por": QUIEN, "deshecha_en": AHORA}},
        ]
        caso = caso_de("deshacer_con_proyecto")
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

        for caso in CASOS_DESHACER:
            with self.subTest(escenario=caso["nombre"]):
                del vistos[:]
                caso["correr"](True, vigilar)
                p1, p2, p3 = vistos[-1]
                self.assertFalse(p1.called or p2.called or p3.called, "el cálculo tiró una caché")
        # control: `deshacer` de verdad sí las tira (la escritura pone las caras y el portal al día)
        del vistos[:]
        caso_de("deshacer_tras_unir")["correr"](False, vigilar)
        _, p2, p3 = vistos[-1]
        self.assertTrue(p2.called and p3.called)

    def test_F7_registro(self):
        self.assertIn("deshacer", personas_cuenta.CALCULOS)
        self.assertIn("deshacer", personas_cuenta.RUTAS)
        self.assertEqual(personas_cuenta.RUTAS["deshacer"][0], "POST")
        codigo, datos = personas_cuenta.calcular("deshacer", {"ruta_de_la_escritura": gf.RUTA}, QUIEN)
        self.assertEqual((codigo, datos), (400, personas_cuenta.ERROR_RUTA_AJENA))


if __name__ == "__main__":
    unittest.main()
