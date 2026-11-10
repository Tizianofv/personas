# -*- coding: utf-8 -*-
"""P11-6, GRUPO (a): el cálculo de las escrituras de la ficha de Personas (`personas_cuenta.CALCULOS`).

Las cinco escrituras del grupo: `crear` (portal, fila 1), `editar` (portal, fila 2; la fila 18, precio de Proveedores, va por la misma
ruta), `crear_checkin` (fila 11), `editar_checkin` (fila 12) y `editar_aprendizaje` (fila 13). Cada una corre DOS veces sobre un doble de
NocoDB propio (`tests/doble_escrituras.py`), en el mismo proceso: una con la escritura de verdad y otra con el cálculo.

Qué garantiza y con qué prueba:
  G1  PAREJA: el cálculo dice EXACTAMENTE lo que la escritura mandó a NocoDB (tabla, método y cuerpo, en orden). El doble de la escritura
      guarda cada pedido; el cálculo se compara con esa lista. Dos cosas se normalizan y solo esas: (a) el número que la base asigna a un
      alta se cambia por la marca `<nueva>` (el cálculo no lo sabe), y con él la clave de su aviso (`aviso-<nueva>`); (b) el reloj: se fija
      con un día y una hora (`base.hoy_str`, `personas._ahora_utc`) en las dos corridas.
  G2  CERO ESCRITURAS AL CALCULAR: en cada escenario, el doble del cálculo recibe cero pedidos POST, PATCH, PUT o DELETE. También si la
      base cae en lecturas (GET) a mitad, y si la base cae en escrituras (el cálculo no las llama).
  G3  RECHAZOS: en cada escenario que la escritura rechaza (un 400, 409, 422 o 502 previo a escribir), el cálculo devuelve el MISMO código
      y el MISMO cuerpo (mismo motivo y mismo texto), y no escribe.
  G4  REGISTRO: `CALCULOS` tiene exactamente los cinco nombres del grupo (una prueba se rompe si uno se quita).

Lo que NO ve (declarado): la escritura de la App (`_nc_directo` de la App no se usa aquí); los hilos propios (reloj de Google y barrido al
arrancar), y las escrituras de otros procesos. La dirección (`id` o `identidad`) va en el cuerpo del cálculo: la App tiene que mandarla así.
"""
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
import personas_escrituras  # noqa: E402

QUIEN = "Prueba"
FECHA = "2026-11-10"
AHORA = "2026-11-10T12:00:00+00:00"
NUEVA = personas.CALCULO_FICHA_NUEVA
METODOS_ESCRITURA = ("POST", "PATCH", "PUT", "DELETE")
GRUPO_A = ("crear", "editar", "crear_checkin", "editar_checkin", "editar_aprendizaje")


class Corrida:
    """Un doble de NocoDB propio y el apuntado de la base hacia él, con reloj fijo y cachés limpias. Una corrida por escenario y lado."""

    def __init__(self, **kw):
        self.doble = doble_escrituras.DobleEscrituras(**kw)
        self.url = self.doble.arrancar()
        self.parches = [
            mock.patch.object(base, "NOCODB_BASE", self.url),
            mock.patch.object(base, "NOCODB_TOKEN", "token-de-prueba"),
            mock.patch.object(base, "T_PERSONAS_ANOTACIONES", doble_nocodb.TABLA_ANOTACIONES),
            mock.patch.object(base, "T_BANDEJA_PERSONAS", doble_nocodb.T_BANDEJA),
            mock.patch.object(base, "hoy_str", lambda: FECHA),
            mock.patch.object(personas, "_ahora_utc", lambda: AHORA),
        ]

    def __enter__(self):
        for p in self.parches:
            p.start()
        personas.invalidate_personas()
        personas.invalidate_portal_personas()
        self.nueva_id = max(f["Id"] for f in self.doble.tablas[doble_nocodb.T_PERSONAS]) + 1
        return self

    def __exit__(self, *a):
        for p in reversed(self.parches):
            p.stop()
        self.doble.parar()

    def escrituras(self):
        """Lo que el doble recibió de escritura, en orden: `{tabla, metodo, cuerpo}`. Las lecturas no entran."""
        salida = []
        for p in self.doble.pedidos:
            if p["metodo"] in METODOS_ESCRITURA:
                tabla = p["ruta"].split("/api/v2/tables/")[1].split("/")[0]
                salida.append({"tabla": tabla, "metodo": p["metodo"], "cuerpo": p["cuerpo"]})
        return salida


def _normalizar(escrituras, nueva_id):
    """Lo que escribió la base, con el número asignado cambiado por la marca (y la clave de su aviso)."""
    salida = []
    for e in escrituras:
        c = dict(e["cuerpo"]) if isinstance(e["cuerpo"], dict) else e["cuerpo"]
        if isinstance(c, dict):
            for k in ("ficha_id", "otra_ficha_id"):
                if c.get(k) == nueva_id:
                    c[k] = NUEVA
            if e["tabla"] == doble_nocodb.T_BANDEJA and c.get("ficha_id") == NUEVA:
                c["clave"] = "aviso-" + NUEVA
        salida.append({"tabla": e["tabla"], "metodo": e["metodo"], "cuerpo": c})
    return salida


NOMBRE_DE_TABLA = {doble_nocodb.T_PERSONAS: "personas", doble_nocodb.TABLA_ANOTACIONES: "anotaciones", doble_nocodb.T_BANDEJA: "bandeja"}
AHORA_2 = "2026-11-10T13:37:00+00:00"
FECHA_2 = "2026-11-11"


def forma_app(escrituras):
    """Lo que la App ve de estas escrituras (contrato de `panel_reenvio.calcular_personas`): una fila por registro, la tabla con su nombre
    lógico, sin la columna `Id`. Es lo que el cálculo tiene que devolver en `escrituras`."""
    filas = []
    for e in escrituras:
        registros = e["cuerpo"] if isinstance(e["cuerpo"], list) else [e["cuerpo"]]
        for reg in registros:
            filas.append({"tabla": NOMBRE_DE_TABLA[e["tabla"]], "metodo": e["metodo"], "enlace": None,
                          "valores": {k: v for k, v in reg.items() if k != "Id"}})
    return filas


def ruta_de(nombre, cuerpo):
    """La ruta que la App manda en `ruta_de_la_escritura`: las ids van en la ruta, no en el cuerpo."""
    if nombre == "crear":
        return "/api/portal-personas"
    if nombre == "editar":
        return "/api/portal-personas/%d/editar" % cuerpo["id"]
    if nombre == "crear_checkin":
        return "/api/personas"
    if nombre == "editar_checkin":
        return "/api/personas/%d" % cuerpo["id"]
    if nombre == "editar_aprendizaje":
        return "/api/aprendizaje/fichas/%s/editar" % cuerpo["identidad"]
    raise AssertionError(nombre)


def cuerpo_del_calculo(nombre, cuerpo):
    """El cuerpo que manda la App al cálculo: el de la escritura SIN sus ids (van en la ruta), más `ruta_de_la_escritura`."""
    quitar = ("identidad",) if nombre == "editar_aprendizaje" else ("id", "identidad")   # el `id` de la ficha del Aprendizaje va en el cuerpo
    sin_ids = {k: v for k, v in cuerpo.items() if k not in quitar}
    return dict(sin_ids, ruta_de_la_escritura=ruta_de(nombre, cuerpo))


def _como_la_ruta(funcion):
    """Lo que la ruta hace con los errores de la escritura (`personas_cuenta._envuelto`): la escritura y el cálculo usan el mismo mapeo."""
    return personas_cuenta._envuelto(funcion)


def escribir(nombre, cuerpo):
    """La escritura de verdad, como la llama la ruta del grupo."""
    if nombre == "crear":
        return personas.crear_persona_portal(cuerpo, QUIEN)
    if nombre == "editar":
        return personas.editar_persona_portal(cuerpo["id"], cuerpo, QUIEN)
    if nombre == "crear_checkin":
        return _como_la_ruta(lambda: (201, {"ok": True, "rec": personas_escrituras.crear_persona(cuerpo)}))
    if nombre == "editar_checkin":
        datos = {k: v for k, v in cuerpo.items() if k != "id"}
        return _como_la_ruta(lambda: (200, {"ok": True, "rec": personas_escrituras.editar_persona(cuerpo["id"], datos)}))
    if nombre == "editar_aprendizaje":
        resto = {k: v for k, v in cuerpo.items() if k != "identidad"}
        return _como_la_ruta(lambda: personas.editar_ficha_cliente(cuerpo["identidad"], resto, QUIEN))
    raise AssertionError(nombre)


# Escenarios: (nombre del cálculo, cuerpo, etiqueta). El cuerpo es el de la escritura; `identidad` y `id` van en él para las dos rutas que
# llevan la dirección en la URL. Hay escenarios de éxito (guardan), de «sin cambios», de rechazo y de bandeja (un aviso).
ESCENARIOS = [
    ("crear", {"cambios": {"nombre": "Ana Prueba", "telefono": "18095550101", "instagram": "@ana"}}, "alta nueva"),
    ("crear", {"cambios": {"nombre": "Persona de prueba 1", "telefono": "18095550102"}}, "alta con nombre repetido (aviso a la bandeja)"),
    ("crear", {"cambios": {"nombre": "Otra", "telefono": "18097770002"}}, "alta con teléfono de otra ficha (rechazo)"),
    ("crear", {"cambios": {"telefono": "18095550103"}}, "alta sin nombre (rechazo)"),
    ("editar", {"id": 1, "cambios": {"instagram": "@p1"}, "base": {"instagram": ""}}, "editar instagram"),
    ("editar", {"id": 2, "cambios": {"instagram": ""}, "base": {"instagram": ""}}, "editar sin cambios"),
    ("editar", {"id": 1, "cambios": {"instagram": "@p1"}, "base": {"instagram": "otro"}}, "editar con cambio entre medio (rechazo)"),
    ("editar", {"id": 1, "cambios": {"telefono": "18097770002"}, "base": {"telefono": "18097770001"}}, "editar a teléfono de otra (rechazo)"),
    ("editar", {"id": 2, "cambios": {"telefono": "18097770009"}, "base": {"telefono": "18097770002"}}, "cambiar teléfono sin confirmar (rechazo)"),
    ("crear_checkin", {"nombre": "Check Nuevo", "telefono": "8095550104", "instagram": "@ck"}, "alta del check-in"),
    ("crear_checkin", {"nombre": ""}, "alta del check-in sin nombre (rechazo)"),
    ("editar_checkin", {"id": 2, "instagram": "@ck2"}, "edición del check-in"),
    ("editar_checkin", {"id": 3, "instagram": "@ck3"}, "edición del check-in de una ficha borrada (rechazo)"),
    ("editar_aprendizaje", {"identidad": "18097770002", "id": 2, "cambios": {"instagram": "@ap"}, "base": {"instagram": ""}},
     "edición de la ficha del Aprendizaje"),
    ("editar_aprendizaje", {"identidad": "18097770001", "id": 2, "cambios": {"instagram": "@ap"}, "base": {"instagram": ""}},
     "ficha del Aprendizaje con otra dirección (rechazo)"),
]


def _pareja(testcase, nombre, cuerpo, etiqueta, **caidas_del_calculo):
    """Corre la escritura y el cálculo sobre dobles propios y compara (G1, G3); el cálculo no escribe (G2)."""
    with Corrida() as w:
        nueva = w.nueva_id
        codigo_w, datos_w = escribir(nombre, dict(cuerpo))
        escrituras_w = _normalizar(w.escrituras(), nueva)
    with Corrida(**caidas_del_calculo) as c:
        codigo_c, datos_c = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, dict(cuerpo)), QUIEN)
        escrituras_c = c.escrituras()
    testcase.assertEqual(escrituras_c, [], "G2: el cálculo mandó escrituras (%s)" % etiqueta)
    if codigo_w in (200, 201) and codigo_c in (200, 201) and isinstance(datos_c, dict) and "escrituras" in datos_c:
        testcase.assertEqual(codigo_c, codigo_w, "G1: código distinto (%s)" % etiqueta)
        testcase.assertEqual(datos_c["escrituras"], forma_app(escrituras_w), "G1: el cálculo no dice lo que la escritura mandó (%s)" % etiqueta)
        return escrituras_w
    testcase.assertEqual((codigo_c, datos_c), (codigo_w, datos_w), "G3: el rechazo no es el mismo (%s)" % etiqueta)
    testcase.assertEqual(escrituras_w, [], "G3: la escritura rechazada escribió (%s)" % etiqueta)
    return None


class GrupoA(unittest.TestCase):

    def test_G1_pareja_y_G2_cero_escrituras_en_cada_escenario(self):
        con_escrituras = set()
        for nombre, cuerpo, etiqueta in ESCENARIOS:
            with self.subTest(calculo=nombre, escenario=etiqueta):
                if _pareja(self, nombre, cuerpo, etiqueta):
                    con_escrituras.add(nombre)
        # que la pareja no sea vacía: cada cálculo del grupo tiene al menos un escenario que escribe, y el cálculo lo dijo igual
        self.assertEqual(con_escrituras, set(GRUPO_A))

    def test_G1_el_escenario_de_bandeja_escribe_un_aviso(self):
        # Cubre lo que dice: el alta con nombre repetido apunta un aviso en la bandeja, y el cálculo lo dice igual.
        escrituras = _pareja(self, "crear", {"cambios": {"nombre": "Persona de prueba 1", "telefono": "18095550102"}}, "bandeja")
        self.assertIsNotNone(escrituras)
        self.assertIn(doble_nocodb.T_BANDEJA, [e["tabla"] for e in escrituras], "el escenario no pone ningún aviso en la bandeja")
        self.assertIn(doble_nocodb.TABLA_ANOTACIONES, [e["tabla"] for e in escrituras], "el alta no anota su origen")

    def test_G2_cero_escrituras_si_la_base_cae_en_lecturas(self):
        # El cálculo lee lo mismo que la escritura; si la lectura cae a mitad, no escribe nada y no dice que escribiría.
        for nombre, cuerpo, etiqueta in ESCENARIOS:
            with self.subTest(calculo=nombre, escenario=etiqueta):
                with Corrida(caidas=("GET",)) as c:
                    personas_cuenta.calcular(nombre, dict(cuerpo), QUIEN)
                    self.assertEqual(c.escrituras(), [], "el cálculo con la base caída en lecturas mandó escrituras")

    def test_G2_cero_escrituras_si_la_base_no_acepta_escrituras(self):
        # Con las escrituras caídas, el cálculo contesta igual y no las llama: no se entera de que caen.
        for nombre, cuerpo, etiqueta in ESCENARIOS:
            with self.subTest(calculo=nombre, escenario=etiqueta):
                with Corrida(caidas=("POST", "PATCH", "PUT", "DELETE")) as c:
                    personas_cuenta.calcular(nombre, dict(cuerpo), QUIEN)
                    self.assertEqual(c.escrituras(), [], "el cálculo mandó una escritura con la base caída")

    def test_G4_el_grupo_esta_registrado_con_sus_cinco_nombres(self):
        self.assertEqual(set(personas_cuenta.CALCULOS), set(GRUPO_A))
        self.assertEqual(set(personas_cuenta.RUTAS), set(GRUPO_A))

    def test_G5_lo_que_sale_del_reloj_o_del_alta_va_en_sin_valor(self):
        """Dos corridas con relojes distintos: toda columna que cambia tiene que estar en `sin_valor` del cálculo (la App la compara solo
        por existencia). Y el número de una alta (`<nueva>`) también va en `sin_valor`."""
        for nombre, cuerpo, etiqueta in ESCENARIOS:
            with Corrida():
                codigo_a, datos_a = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, dict(cuerpo)), QUIEN)
            with Corrida(), mock.patch.object(personas, "_ahora_utc", lambda: AHORA_2), mock.patch.object(base, "hoy_str", lambda: FECHA_2):
                codigo_b, datos_b = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, dict(cuerpo)), QUIEN)
            if codigo_a not in (200, 201) or "escrituras" not in datos_a:
                continue
            self.assertEqual(codigo_a, codigo_b, etiqueta)
            movidas = set()
            for fa, fb in zip(datos_a["escrituras"], datos_b["escrituras"]):
                for col in set(fa["valores"]) | set(fb["valores"]):
                    if fa["valores"].get(col) != fb["valores"].get(col):
                        movidas.add("%s.%s.%s" % (fa["tabla"], fa["metodo"], col))
            self.assertLessEqual(movidas, set(datos_a["sin_valor"]), "columna que cambia con el reloj fuera de sin_valor (%s)" % etiqueta)


if __name__ == "__main__":
    unittest.main()
