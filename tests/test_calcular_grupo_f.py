# -*- coding: utf-8 -*-
"""P11-6, GRUPO (f), `unir` (fila 6): el cálculo de la unión (`personas_cuenta.CALCULOS["unir"]`). `continuar` (fila 7) va en
`tests/test_calcular_continuar.py`; `deshacer` (fila 8) va en `tests/test_calcular_deshacer.py`.

La App compara `unir` en su modo contar (`registro/server.py`, `escritura_de_personas_para_cuenta`, nombre `unir`). El programa calcula
con `personas.unir_fichas(..., solo_contar=True, planeados=...)`: la misma decisión, las mismas lecturas y los mismos rechazos que la
unión; las escrituras que mandaría (la fila del registro, los movimientos de asistencias y de enlaces UNA persona por pedido, y las dos
fichas) quedan en `planeados`, en orden.

Qué garantiza y con qué prueba:
  F1  PAREJA: en cada escenario que la unión escribe, el cálculo dice EXACTAMENTE lo que la unión mandó al doble (tabla lógica, método,
      enlace y valores, en orden). Las dos corridas usan el mismo estado de partida, el mismo reloj y las mismas cachés limpias.
  F2  CERO ESCRITURAS AL CALCULAR: en cada escenario (también los que no se predicen y los rechazos), el cálculo no manda POST, PATCH,
      PUT ni DELETE. Esto vigila también que la decisión (`_union_planear`) sea pura.
  F3  RECHAZOS IGUALES: en cada rechazo, el cálculo da el MISMO código y cuerpo que la unión, y la unión no escribió nada.
  F4  SIN CÁLCULO: un camino que no se predice (asistencia nueva, unión a medias, aviso de «Por resolver», parada o fallo después de
      planear) contesta 404 «sin cálculo» y no escribe.
  F5  REGISTRO: `unir` está en `CALCULOS` y en `RUTAS`; la ruta de `continuar` se rechaza con 400 (ruta ajena) para `unir`; `deshacer`
      también tiene cálculo (su prueba: `test_calcular_deshacer`).
  F6  NINGUNA CACHÉ: el cálculo no invalida `personas`, `portal` ni `caras` (la unión sí lo hace, y eso no cambia).

Lo que NO ve (declarado): la unión de la App en vivo (la comparación de la App con NocoDB real no se corre aquí); una caída de NocoDB
en mitad de la unión (el cálculo supone que cada escritura se confirma: la caída al escribir el registro no se predice); el reloj de
NocoDB (se fija el de `personas._ahora_utc`, así que las columnas del reloj se comparan iguales aquí; en producción las vigila la
lista `COLUMNAS_DEL_RELOJ` por existencia, y eso no lo prueba este archivo).
"""
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
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_portal_escritura  # noqa: E402

QUIEN = "Prueba"
FECHA = "2026-11-10"
AHORA = "2026-11-10T12:00:00+00:00"
CLAVE = "union-prueba-0001"
RUTA = "/api/portal-personas/11/unir"
METODOS_ESCRITURA = ("POST", "PATCH", "PUT", "DELETE")
T_U = doble_escrituras.T_UNIONES
NOMBRE_DE_TABLA = {base.T_PERSONAS: "personas", base.T_ASISTENCIAS: "asistencias", T_U: "uniones",
                   base.T_SESIONES: "sesiones", base.T_PROYECTOS: "proyectos",
                   doble_nocodb.T_BANDEJA: "bandeja"}      # (deshacer, P11-6f: el apunte de la puerta)
NOMBRE_DE_ENLACE = {valor: "enlace:" + nombre for nombre, valor in vars(base).items()
                    if nombre.startswith("L_") and isinstance(valor, str) and valor}
RE_ENLACE = re.compile(r"/api/v2/tables/([^/]+)/links/([^/]+)/records/(\d+)")
RE_TABLA = re.compile(r"/api/v2/tables/([^/]+)/records")
# Enlaces que NocoDB guarda en sus dos lados (el doble los liga y desliga juntos).
PAREJAS = {(base.T_PROYECTOS, base.L_PROY_MIEMBROS): (base.T_PERSONAS, base.L_PERSONA_PROYECTOS),
           (base.T_SESIONES, base.L_MUSICOS): (base.T_PERSONAS, base.L_PERSONA_SESIONES)}
ASISTENCIA = {"titulo": "Sesión de prueba", "checkin_at": "2026-10-01T10:00:00Z", "registrado_por": "Prueba"}


def asistencias(*pares):
    """Asistencias de prueba: (Id, persona, sesión)."""
    return [dict(ASISTENCIA, Id=i, persona_id=p, sesion_id=s) for i, p, s in pares]


# Cada escenario: nombre, cuerpo de la unión, estado de partida (enlaces, tablas) y lo que se espera del cálculo.
#   "pareja": el cálculo tiene que decir lo mismo que la unión (F1). "rechazo": la unión contesta un error antes de escribir (F3).
#   "sin_calculo": el cálculo contesta 404 (F4).
ESCENARIOS = [
    {"nombre": "unir_simple", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "pareja", "tablas": {base.T_ASISTENCIAS: []}},
    {"nombre": "unir_con_proyecto", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "pareja", "tablas": {base.T_ASISTENCIAS: []},
     "enlaces": {(base.T_PERSONAS, base.L_PERSONA_PROYECTOS, 12): [7], (base.T_PROYECTOS, base.L_PROY_MIEMBROS, 7): [12]}},
    {"nombre": "unir_con_sesion_y_pago", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "pareja", "tablas": {base.T_ASISTENCIAS: []},
     "enlaces": {(base.T_PERSONAS, base.L_PERSONA_SESIONES, 12): [3], (base.T_SESIONES, base.L_MUSICOS, 3): [12],
                 (base.T_PERSONAS, base.L_PERSONA_PAGOS, 12): [5]}},
    {"nombre": "unir_asistencia_que_ya_tenia", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "pareja",
     "tablas": {base.T_ASISTENCIAS: asistencias((901, 12, 9), (902, 11, 9))},
     "enlaces": {(base.T_PERSONAS, base.L_PERSONA_SESIONES, 11): [9], (base.T_SESIONES, base.L_MUSICOS, 9): [11]}},
    {"nombre": "ya_estaba", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "pareja", "tablas": {base.T_ASISTENCIAS: [],
     T_U: [{"Id": 50, "clave": CLAVE, "estado": "unida", "queda_id": 11, "sobra_id": 12}]}},
    {"nombre": "rechazo_misma_ficha", "cuerpo": {"otra": 11, "clave": CLAVE}, "tipo": "rechazo"},
    {"nombre": "rechazo_otra_no_existe", "cuerpo": {"otra": 99, "clave": CLAVE}, "tipo": "rechazo"},
    {"nombre": "rechazo_queda_cambio", "cuerpo": {"otra": 12, "queda": 12, "clave": CLAVE}, "tipo": "rechazo"},
    {"nombre": "rechazo_resoluciones_mal", "cuerpo": {"otra": 12, "resoluciones": "x", "clave": CLAVE}, "tipo": "rechazo"},
    {"nombre": "rechazo_lectura_caida", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "rechazo", "caidas": ("GET",)},
    {"nombre": "sin_calculo_asistencia_nueva", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "sin_calculo",
     "tablas": {base.T_ASISTENCIAS: asistencias((901, 12, 9))}},
    {"nombre": "sin_calculo_union_a_medias", "cuerpo": {"otra": 12, "clave": CLAVE}, "tipo": "sin_calculo", "tablas": {
     base.T_ASISTENCIAS: [], T_U: [{"Id": 50, "clave": CLAVE, "estado": "en_curso", "queda_id": 11, "sobra_id": 12,
                                    "plan": "{}", "antes": "{}"}]}},
    {"nombre": "sin_calculo_aviso_de_por_resolver", "cuerpo": {"otra": 12, "clave": CLAVE, "aviso": "aviso-" + "c" * 40},
     "tipo": "sin_calculo", "tablas": {base.T_ASISTENCIAS: []}},
]


# Las funciones de invalidar, guardadas al cargar el módulo: la prueba de cachés las parchea, y limpiar antes de cada corrida no debe contar.
_INVALIDAR = (personas.invalidate_personas, personas.invalidate_portal_personas, base.invalidate_caras)


def _limpiar_caches():
    for invalidar in _INVALIDAR:
        invalidar()


class Corrida:
    """Un doble de NocoDB en modo de unión, con el estado de partida del escenario, y el apuntado de la base hacia él. Reloj fijo y
    cachés limpias. Una corrida por lado (la unión y el cálculo), cada una con su doble."""

    def __init__(self, enlaces=None, tablas=None, caidas=()):
        self.doble = doble_escrituras.DobleEscrituras(union=True, enlaces=enlaces, caidas=caidas, parejas=PAREJAS)
        for tabla, filas in (tablas or {}).items():
            self.doble.tablas[tabla] = copy.deepcopy(filas)
        self.url = self.doble.arrancar()
        self.parches = [
            mock.patch.object(base, "NOCODB_BASE", self.url),
            mock.patch.object(base, "NOCODB_TOKEN", "token-de-prueba"),
            mock.patch.object(base, "T_UNIONES_PERSONAS", T_U),
            mock.patch.object(base, "hoy_str", lambda: FECHA),
            mock.patch.object(personas, "_ahora_utc", lambda: AHORA),
        ]

    def __enter__(self):
        for p in self.parches:
            p.start()
        _limpiar_caches()
        return self

    def __exit__(self, *a):
        for p in reversed(self.parches):
            p.stop()
        self.doble.parar()
        _limpiar_caches()
        return False

    def escrituras(self):
        """Lo que salió a NocoDB como escritura, en la forma de la App: una fila por registro (sin `Id`); un enlace, una fila por pedido
        con su registro y sus ligados. Solo mira las tablas y enlaces que `unir` toca (el mapa de nombres de arriba)."""
        filas = []
        for p in self.doble.pedidos:
            if p["metodo"] not in METODOS_ESCRITURA:
                continue
            m = RE_ENLACE.fullmatch(p["ruta"])
            if m:
                filas.append({"tabla": NOMBRE_DE_TABLA[m.group(1)], "metodo": p["metodo"], "enlace": NOMBRE_DE_ENLACE[m.group(2)],
                              "valores": {"registro": int(m.group(3)), "ligados": sorted(int(f["Id"]) for f in p["cuerpo"])}})
                continue
            m = RE_TABLA.fullmatch(p["ruta"])
            cuerpos = p["cuerpo"] if isinstance(p["cuerpo"], list) else [p["cuerpo"]]
            for f in cuerpos:
                filas.append({"tabla": NOMBRE_DE_TABLA[m.group(1)], "metodo": p["metodo"], "enlace": None,
                              "valores": {k: v for k, v in f.items() if k != "Id"}})
        return filas


def correr_union(cuerpo, enlaces=None, tablas=None, caidas=()):
    """La unión de verdad (`responder` del portal, con la escritura), contra un doble. Devuelve `(código, cuerpo, corrida)`."""
    with Corrida(enlaces=enlaces, tablas=tablas, caidas=caidas) as c:
        codigo, datos = personas_portal_escritura.responder("unir", RUTA, ("11",), json.dumps(cuerpo).encode(), QUIEN)
        return codigo, datos, c


def correr_calculo(cuerpo, enlaces=None, tablas=None, caidas=()):
    """El cálculo de `unir` (`calcular`, como lo llama `POST /calcular/unir`) contra un doble. Devuelve `(código, cuerpo, corrida)`."""
    with Corrida(enlaces=enlaces, tablas=tablas, caidas=caidas) as c:
        codigo, datos = personas_cuenta.calcular("unir", dict(cuerpo, ruta_de_la_escritura=RUTA), QUIEN)
        return codigo, datos, c


def escrituras_de(corrida):
    return [p for p in corrida.doble.pedidos if p["metodo"] in METODOS_ESCRITURA]


class GrupoF(unittest.TestCase):
    def _escenario(self, nombre):
        return next(e for e in ESCENARIOS if e["nombre"] == nombre)

    def _pareja_o_rechazo(self, e):
        kw = {"enlaces": e.get("enlaces"), "tablas": e.get("tablas"), "caidas": e.get("caidas", ())}
        codigo_r, datos_r, real = correr_union(e["cuerpo"], **kw)
        codigo_c, datos_c, calc = correr_calculo(e["cuerpo"], **kw)
        return codigo_r, datos_r, real, codigo_c, datos_c, calc

    def test_F1_pareja_en_los_escenarios_que_escriben(self):
        for e in [x for x in ESCENARIOS if x["tipo"] == "pareja"]:
            with self.subTest(escenario=e["nombre"]):
                codigo_r, datos_r, real, codigo_c, datos_c, calc = self._pareja_o_rechazo(e)
                self.assertEqual(codigo_r, 200, datos_r)
                self.assertEqual(codigo_c, 200, datos_c)
                self.assertEqual(datos_c.get("estado"), "calculado")
                self.assertEqual(datos_c["escrituras"], real.escrituras(),
                                 "el cálculo no dice lo que la unión mandó a NocoDB")

    def test_F2_cero_escrituras_al_calcular(self):
        for e in ESCENARIOS:
            with self.subTest(escenario=e["nombre"]):
                _, _, _, _, _, calc = self._pareja_o_rechazo(e)
                self.assertEqual(escrituras_de(calc), [], "el cálculo mandó una escritura a NocoDB")

    def test_F3_rechazos_iguales_y_sin_escribir(self):
        for e in [x for x in ESCENARIOS if x["tipo"] == "rechazo"]:
            with self.subTest(escenario=e["nombre"]):
                codigo_r, datos_r, real, codigo_c, datos_c, _ = self._pareja_o_rechazo(e)
                self.assertNotEqual(codigo_r, 200)
                self.assertEqual(escrituras_de(real), [], "la unión escribió en un rechazo")
                self.assertEqual((codigo_c, datos_c), (codigo_r, datos_r))

    def test_F4_sin_calculo_no_escribe(self):
        for e in [x for x in ESCENARIOS if x["tipo"] == "sin_calculo"]:
            with self.subTest(escenario=e["nombre"]):
                _, _, _, codigo_c, datos_c, calc = self._pareja_o_rechazo(e)
                self.assertEqual((codigo_c, datos_c), (404, personas_cuenta.ERROR_SIN_CALCULO))
                self.assertEqual(escrituras_de(calc), [])

    def test_F5_registro(self):
        self.assertIn("unir", personas_cuenta.CALCULOS)
        self.assertIn("unir", personas_cuenta.RUTAS)
        self.assertIn("continuar", personas_cuenta.CALCULOS)     # su prueba: test_calcular_continuar
        self.assertIn("deshacer", personas_cuenta.CALCULOS)     # su prueba: test_calcular_deshacer
        codigo, datos = personas_cuenta.calcular("unir", {"otra": 12, "clave": CLAVE,
                                                         "ruta_de_la_escritura": RUTA + "/continuar"}, QUIEN)
        self.assertEqual((codigo, datos), (400, personas_cuenta.ERROR_RUTA_AJENA))

    def test_F6_ninguna_cache(self):
        for e in ESCENARIOS:
            with self.subTest(escenario=e["nombre"]):
                with Corrida(enlaces=e.get("enlaces"), tablas=e.get("tablas"), caidas=e.get("caidas", ())):
                    with mock.patch.object(personas, "invalidate_personas") as p1, \
                            mock.patch.object(personas, "invalidate_portal_personas") as p2, \
                            mock.patch.object(base, "invalidate_caras") as p3:
                        personas_cuenta.calcular("unir", dict(e["cuerpo"], ruta_de_la_escritura=RUTA), QUIEN)
                        self.assertFalse(p1.called or p2.called or p3.called, "el cálculo tiró una caché")
        # control: la unión de verdad sí las tira
        with Corrida(tablas={base.T_ASISTENCIAS: []}):
            with mock.patch.object(personas, "invalidate_portal_personas") as p2, \
                    mock.patch.object(base, "invalidate_caras") as p3:
                personas_portal_escritura.responder("unir", RUTA, ("11",), json.dumps({"otra": 12, "clave": CLAVE}).encode(), QUIEN)
                self.assertTrue(p2.called and p3.called)


if __name__ == "__main__":
    unittest.main()
