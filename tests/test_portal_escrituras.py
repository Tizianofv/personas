# -*- coding: utf-8 -*-
"""Las ESCRITURAS del portal que contesta `servidor.py` (paso 5c, parte 3): la llave del portal, la identidad, el `quien` de la
cabecera y las respuestas.

La foto de referencia es `contrato_dorado/portal_escrituras.json`, sacada de la App de registro en `594ec12` por
`tools/generar_portal_escrituras_de_la_app.py`: `rutas_de_la_app` (las rutas POST del portal que la App contesta, leídas con AST)
y `escenarios` (la respuesta de la App y los pedidos que llegaron a su NocoDB, paso a paso).

Pruebas:
  E1  la foto tiene el SHA256 que dice `contrato_dorado/SHA256_portal_escrituras`.
  E2  los pasos de la foto son los de `tests/escenarios_portal_escrituras.py` (dorado), y el servidor del repo, corrido sobre el
      doble que escribe (`tests/doble_escrituras.py`), contesta a cada paso con el MISMO código, la MISMA respuesta y los MISMOS
      pedidos que la App. Y el doble no recibió ningún pedido que no conociera.
  K0  tabla (`servidor.PORTAL_ESCRITURA`) + `PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA` = las rutas POST que la App contesta
      (`rutas_de_la_app`). Ninguna en las dos listas. Cada salida tiene su motivo escrito.
  K1  sin llave, con llave vacía, con la de otro grupo (Mercadeo, Registro, escritura de Registro) o una llave mala: 401 en CADA
      entrada de la tabla, y cero pedidos a NocoDB. Y sin llave con un cuerpo que no es JSON: 401 (la llave va antes que el cuerpo).
  K1b con `PERSONAS_PORTAL_LLAVE` vacía, la cabecera vacía no abre nada: 401 en cada entrada, cero pedidos.
  K2  las rutas de Registro (cara, nueva, editar, credito) con la llave del portal: 401, cero pedidos.
  I1  con la llave bien: sin `quien`, con `quien` en blanco, sin tipo, con otro tipo («B», «a», vacío): 400 con el texto de
      identidad, cero pedidos. En CADA entrada de la tabla (las tres puertas, en todas las rutas).
  H1  hermanos: con llave e identidad bien, cada entrada de la tabla llega a la lógica (no es 401 ni 400 de identidad).
  H2  una ruta que la tabla no conoce (inventada, o una que la App contesta y el programa no porta) da 404 y cero pedidos.
  Q1  el `quien` que se pasa a cada función es el de la cabecera (espía que solo mira el argumento); el del cuerpo no cuenta.
  Q2  la cabecera con el nombre en UTF-8 llega entera («Pérez»), no como «PÃ©rez».

Lo que NO ve (declarado):
  - La puerta de sesión de la App (`portal_personas`: 401 sin sesión, 403 sin permiso). El programa no la tiene.
  - Que la App reenvíe la llave, la identidad y el `quien`: eso es de la App (encargo siguiente); aquí solo se prueba lo que el
    programa hace con lo que recibe.
  - El doble no es NocoDB: no imita sus códigos ni sus textos de error; una operación que cae se simula con `caidas`.
  - Ramas que la foto no ejercita: la marca válida de «Por resolver» (resolver y reabrir dan 400 o 409 con sus claves de prueba: la
    bandeja del doble tiene una sola marca, de otro grupo); la unión; el cambio de teléfono (lee sesiones y conversaciones, que el
    doble no tiene); la columna `notas` (el doble no la declara); los 400 de `dicho_el`, `nota` y `confirmo` de permiso.
  - El campo `cuando` de las anotaciones es la hora de la corrida: la foto y la prueba lo reemplazan por «<ahora>» en los dos lados
    (`escenarios_portal_escrituras.normalizar`) y la prueba solo comprueba que sea una fecha ISO con zona.
  - Q1 mira el argumento con un espía que no escribe: el comportamiento de las funciones lo cubre E2. Y el `quien` sí llega a
    NocoDB solo en las anotaciones de permiso: crear y editar no lo guardan en la tabla de personas (por eso Q1 hace falta).
  - El límite de cuerpo y el `Content-Length` no numérico no se prueban (no están portados; ver `el-programa-personas.md`).
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import escenarios_portal_escrituras as esc  # noqa: E402
import servidor  # noqa: E402  (la tabla real: K0, H1, H2 y Q1 comparan con ella)
import personas  # noqa: E402
import personas_portal_escritura  # noqa: E402

FOTA = RAIZ / "contrato_dorado" / "portal_escrituras.json"
SHA_DECLARADO = RAIZ / "contrato_dorado" / "SHA256_portal_escrituras"
COMANDO = [sys.executable, "-B", str(RAIZ / "servidor.py")]
QUIEN = esc.QUIEN_DORADO
RUTA_REGISTRO = ["/api/servicio/personas/cara", "/api/servicio/personas/nueva", "/api/servicio/personas/editar"]
RUTA_REGISTRO_LECTURA = "/api/servicio/personas/credito"


def muestra(patron):
    """Una ruta concreta que casa con el patrón de la tabla (el número de la ficha, 2). Sin regex: el patrón es el texto."""
    return patron.replace(r"(\d{1,9})", "2")


def cuerpo_de(nombre):
    """Un cuerpo que la ruta acepta en la forma (no garantiza 200: la prueba solo mira que la lógica se alcance)."""
    return {
        "crear": {"cambios": {"nombre": "Prueba Hermana", "telefono": "8095550301"}},
        "editar": {"id": 2, "base": {"instagram": ""}, "cambios": {"instagram": "hermana"}},
        "permiso": {"valor": "no", "visto": 2},
        "resolver": {"clave": "resuelto-" + "c" * 40},
        "reabrir": {"clave": "resuelto-" + "c" * 40},
    }[nombre]


def _pasos_de_la_tabla(llave="portal", quien=QUIEN, tipo="A", cuerpo=None):
    pasos = []
    for patron, (nombre, _tipo, _exige) in servidor.PORTAL_ESCRITURA.items():
        pasos.append({"ruta": muestra(patron), "llave": llave, "quien": quien, "tipo": tipo,
                      "cuerpo": cuerpo if cuerpo is not None else cuerpo_de(nombre)})
    return pasos


def _cuandos_son_iso(x):
    """Cierto si todo valor de una clave `cuando` (a cualquier nivel) es una fecha ISO con zona. Lo que no lo es queda sin cambiar
    al normalizar y no iguala la foto, así que esta comprobación solo le pone el motivo al fallo."""
    if isinstance(x, dict):
        return all((not (k == "cuando") or esc._es_iso(v)) and _cuandos_son_iso(v) for k, v in x.items())
    if isinstance(x, list):
        return all(_cuandos_son_iso(v) for v in x)
    return True


def _correr(pasos, entorno=None, caidas=()):
    escenario = {"nombre": "prueba", "pasos": pasos, "caidas": list(caidas)}
    if entorno is not None:
        escenario["entorno"] = entorno
    return esc.ejecutar(escenario, COMANDO, cwd=str(RAIZ))


class EscriturasDelPortalEnElPrograma(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads(FOTA.read_text(encoding="utf-8"))
        cls.por_nombre = {e["nombre"]: e for e in cls.foto["escenarios"]}

    # ---- E: la foto y lo que contesta el servidor -------------------------------------------------------------------------

    def test_E1_la_foto_tiene_el_sha_declarado(self):
        real = hashlib.sha256(FOTA.read_bytes()).hexdigest()
        declarado = SHA_DECLARADO.read_text(encoding="utf-8").split()[0]
        self.assertEqual(real, declarado)

    def test_E2a_la_foto_tiene_los_pasos_de_los_escenarios_del_repo(self):
        self.assertEqual(sorted(self.por_nombre), sorted(e["nombre"] for e in esc.ESCENARIOS))
        for escenario in esc.ESCENARIOS:
            with self.subTest(escenario=escenario["nombre"]):
                dorado = [p for p in escenario["pasos"] if esc.es_dorado(p)]
                guardado = self.por_nombre[escenario["nombre"]]["pasos"]
                self.assertEqual(len(guardado), len(dorado))
                for paso, foto in zip(dorado, guardado):
                    self.assertEqual(foto["ruta"], paso["ruta"])
                    self.assertEqual(foto["quien"], paso["quien"])
                    if "crudo" in paso:
                        self.assertEqual(foto["crudo"], paso["crudo"])
                    else:
                        self.assertEqual(foto["cuerpo"], paso["cuerpo"])

    def test_E2_cada_escenario_contesta_como_la_app(self):
        # Los pasos salen de `esc.ESCENARIOS` y NO de la foto: la foto guarda los cuerpos con las claves ordenadas, y el orden de
        # las claves decide el orden de los campos que se piden y escriben (la App los recibió en orden de inserción).
        for escenario in esc.ESCENARIOS:
            nombre = escenario["nombre"]
            with self.subTest(escenario=nombre):
                foto = self.por_nombre[nombre]
                pasos = [p for p in escenario["pasos"] if esc.es_dorado(p)]
                real, errores = _correr(pasos, caidas=escenario.get("caidas", ()))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                self.assertEqual(len(real), len(foto["pasos"]))
                for r in real:
                    for q in r["pedidos"]:
                        self.assertTrue(_cuandos_son_iso(q), "un «cuando» que no es fecha ISO con zona: %r" % q)
                for r, f in zip(real, foto["pasos"]):
                    self.assertEqual(r["status"], f["status"])
                    self.assertEqual(esc.normalizar(r["respuesta"]), f["respuesta"])
                    self.assertEqual(esc.normalizar(r["pedidos"]), f["pedidos"])

    # ---- K: la tabla contra la App ------------------------------------------------------------------------------------

    def test_K0_tabla_mas_fuera_son_las_rutas_post_de_la_app(self):
        de_la_app = {(r["patron"], r["exacta"]) for r in self.foto["rutas_de_la_app"]}
        de_la_tabla = {(p, "(" not in p) for p in servidor.PORTAL_ESCRITURA}
        fuera = set(servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA)
        self.assertEqual(set(servidor.PORTAL_ESCRITURA) & fuera, set())
        self.assertEqual(de_la_tabla | {(p, "(" not in p) for p in fuera}, de_la_app)
        for patron, motivo in servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA.items():
            self.assertTrue(motivo.strip(), "cada salida tiene su motivo: %s" % patron)

    def test_K1_sin_llave_valida_no_hay_escritura_en_ninguna_entrada(self):
        pasos = []
        for llave in ("ausente", "vacia", "escritura", "lectura_mercadeo", "lectura_registro", "mala"):
            pasos += _pasos_de_la_tabla(llave=None if llave == "ausente" else llave)
        real, errores = _correr(pasos)
        self.assertEqual(errores, [])
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 401)
                self.assertEqual(r["respuesta"], {"error": "llave de servicio inválida"})
                self.assertEqual(r["pedidos"], [])

    def test_K1c_sin_llave_un_cuerpo_que_no_es_json_da_401_no_400(self):
        pasos = [{"ruta": muestra(p), "llave": None, "quien": QUIEN, "tipo": "A", "crudo": "no es json"}
                 for p in servidor.PORTAL_ESCRITURA]
        real, _ = _correr(pasos)
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 401)
                self.assertEqual(r["pedidos"], [])

    def test_K1b_con_la_variable_vacia_la_cabecera_vacia_no_abre(self):
        pasos = _pasos_de_la_tabla(llave="vacia") + _pasos_de_la_tabla(llave="portal")
        real, _ = _correr(pasos, entorno={"PERSONAS_PORTAL_LLAVE": ""})
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 401)
                self.assertEqual(r["pedidos"], [])

    def test_K2_la_llave_del_portal_no_abre_las_rutas_de_registro(self):
        pasos = [{"ruta": ruta, "llave": "portal", "quien": QUIEN, "tipo": "A", "cuerpo": {"persona_id": 1, "vec": [0.5] * 128}}
                 for ruta in RUTA_REGISTRO]
        pasos.append({"ruta": RUTA_REGISTRO_LECTURA, "llave": "portal", "quien": QUIEN, "tipo": "A", "cuerpo": {"telefono": "1"}})
        real, _ = _correr(pasos)
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 401)
                self.assertEqual(r["pedidos"], [])

    # ---- I: identidad (las tres puertas, en todas las entradas) ----------------------------------------------------------

    def test_I1_con_la_llave_bien_sin_identidad_no_hay_escritura(self):
        variantes = [
            {"quien": None, "tipo": "A"},
            {"quien": "", "tipo": "A"},
            {"quien": "   ", "tipo": "A"},
            {"quien": QUIEN, "tipo": None},
            {"quien": QUIEN, "tipo": "B"},
            {"quien": QUIEN, "tipo": "a"},
            {"quien": QUIEN, "tipo": ""},
        ]
        pasos = []
        for v in variantes:
            pasos += _pasos_de_la_tabla(quien=v["quien"], tipo=v["tipo"])
        real, errores = _correr(pasos)
        self.assertEqual(errores, [])
        self.assertEqual(len(real), len(pasos))
        for r in real:
            with self.subTest(ruta=r["ruta"], respuesta=r["respuesta"]):
                self.assertEqual(r["status"], 400)
                self.assertEqual(r["respuesta"], servidor.ERROR_IDENTIDAD)
                self.assertEqual(r["pedidos"], [])

    def test_H1_hermanos_con_llave_e_identidad_bien_llegan_a_la_logica(self):
        real, _ = _correr(_pasos_de_la_tabla())
        self.assertEqual(len(real), len(servidor.PORTAL_ESCRITURA))
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertNotEqual(r["status"], 401)
                self.assertNotEqual(r["respuesta"], servidor.ERROR_IDENTIDAD)

    def test_H2_rutas_que_la_tabla_no_conoce_dan_404_y_no_escriben(self):
        inventadas = ["/api/portal-personas/2/inventada", "/api/portal-personas/por-resolver/otra",
                      "/api/portal-personas/2/editar/extra", "/api/portal-personas/nueva"]
        fuera = [muestra(p) for p in servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA]
        pasos = [{"ruta": ruta, "llave": "portal", "quien": QUIEN, "tipo": "A", "cuerpo": {"clave": "x", "valor": "no", "visto": 2,
                                                                                           "cambios": {"nombre": "x"}}}
                 for ruta in inventadas + fuera]
        real, errores = _correr(pasos)
        self.assertEqual(errores, [])
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 404)
                self.assertEqual(r["pedidos"], [])

    # ---- Q: el quien de la cabecera -----------------------------------------------------------------------------------

    def test_Q1_cada_funcion_recibe_el_quien_de_la_cabecera_y_no_el_del_cuerpo(self):
        recibidos = {}

        def espia(nombre, devuelve):
            def f(*args, **kwargs):
                recibidos[nombre] = args[-1]          # crear(cuerpo, quien), editar(id, cuerpo, quien), permiso(id, cuerpo, quien), resolver(clave, quien)
                return devuelve
            return f
        parches = [
            mock.patch.object(personas, "crear_persona_portal", espia("crear", (201, {"estado": "creada"}))),
            mock.patch.object(personas, "editar_persona_portal", espia("editar", (200, {"estado": "sin_cambios"}))),
            mock.patch.object(personas, "anotar_permiso", espia("permiso", (200, {"estado": "ya_estaba"}))),
            mock.patch.object(personas, "portal_por_resolver_marcar", espia("resolver", (400, {"error": "x"}))),
        ]
        for p in parches:
            p.start()
        try:
            for patron, (nombre, _tipo, _exige) in servidor.PORTAL_ESCRITURA.items():
                cuerpo = dict(cuerpo_de(nombre), quien="Otra Persona")
                ruta = muestra(patron)
                crudo = json.dumps(cuerpo).encode("utf-8")
                personas_portal_escritura.responder(nombre, ruta, ("2",) if nombre in ("editar", "permiso") else (), crudo, QUIEN)
        finally:
            for p in parches:
                p.stop()
        self.assertEqual(recibidos["crear"], QUIEN)
        self.assertEqual(recibidos["editar"], QUIEN)
        self.assertEqual(recibidos["permiso"], QUIEN)
        self.assertEqual(recibidos["resolver"], QUIEN)

    def test_Q2_el_nombre_en_utf8_llega_entero(self):
        self.assertEqual(servidor.quien_de_la_cabecera("Ana PÃ©rez"), "Ana Pérez")
        self.assertEqual(servidor.quien_de_la_cabecera("  Ana  "), "Ana")
        self.assertEqual(servidor.quien_de_la_cabecera(None), "")
        self.assertEqual(servidor.quien_de_la_cabecera("Ana€"), "Ana€")


if __name__ == "__main__":
    unittest.main()
