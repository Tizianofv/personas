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
  K3  sin llave y sin identidad a la vez (cabecera de llave ausente, quien y tipo ausentes): 401, cero pedidos, en cada entrada
      de la tabla. La llave va antes que la identidad.
  R1  un fallo de escritura no se recuerda como guardado: editar y crear, con la misma `clave_envio`, fallan una vez (la base
      no contesta), y el segundo envío VUELVE a escribir (hay pedido de escritura) y no trae `ya_guardado` / `ya_creada`.
  X1  la regla de «envío hecho» es la de la App, entera: el predicado `exito` de cada `una_vez` del programa (AST de
      `personas_portal_escritura.py`) es el texto que la foto saca de la App (`exito_de_la_app`).
  R2  la regla recorre todos los códigos que pueden dar crear y editar, sacados de la foto (los que aparecen en sus pasos): cada
      código tiene un par de envíos con la misma clave; el 2.º trae `ya_guardado` / `ya_creada` si y solo si el 1.º cumple el
      `exito` de la App (evaluado sobre la respuesta del 1.º); si no, no lo trae.
  HU1 hermanos de `una_vez`: los sitios del programa que usan `una_vez` (AST de `personas_portal_escritura._ejecutar`) son los
      mismos que la foto (crear y editar), y a cada uno se le exige el MISMO juego de escenarios, sacado de la foto: mismo cuerpo,
      cuerpo distinto, fallo y cada código que la foto da al sitio. Además, el escenario de cuerpo distinto de cada sitio escribe
      otra vez (el 2.º no trae ya_*): así se pone roja una huella que ignore el cuerpo, en los dos.
  A1  el candado de «envío hecho» del programa (`llave_de_envio`, `escribir_una_vez`, `una_vez` y sus constantes) tiene la MISMA
      forma que el de la App `594ec12` (`candado_de_la_app` de la foto, sacado por AST con `tests/candado.py`). Cualquier
      diferencia de código (llave nula, vencimiento, tope, expulsión, candado, copia) se ve aquí.
  B1  en todo el programa (todos los `.py` fuera de `tests/` y `tools/`), cada uso de `una_vez` o `escribir_una_vez` es un sitio:
      una llamada directa `una_vez(...)` en la rama de su acción de `_ejecutar`. Alias, atributo, import, otra llamada o una
      referencia suelta dan rojo.
  C1  con una clave de envío, sin clave escribe siempre (dos envíos sin clave, dos escrituras).
  C2  con clave, recuerda 600 s: a los 599 s no vuelve a escribir, a los 700 s sí (reloj simulado).
  C3  una excepción de la escritura no se recuerda: el mismo envío vuelve a escribir.
  K2  las rutas de Registro (cara, nueva, editar, credito) con la llave del portal: 401, cero pedidos.
  I1  con la llave bien: sin `quien`, con `quien` en blanco, sin tipo, con otro tipo («B», «a», vacío): 400 con el texto de
      identidad, cero pedidos. En CADA entrada de la tabla (las tres puertas, en todas las rutas).
  H1  hermanos: con llave e identidad bien, cada entrada de la tabla llega a la lógica (no es 401 ni 400 de identidad).
  H2  una ruta que la tabla no conoce (inventada, o una que la App contesta y el programa no porta) da 404 y cero pedidos.
  Q1  el `quien` que se pasa a cada función es el de la cabecera (espía que solo mira el argumento); el del cuerpo no cuenta.
  Q2  la cabecera con el nombre en UTF-8 llega entera («Pérez»), no como «PÃ©rez».
  Las tres de UNIÓN (unir, unir/continuar, unir/deshacer, paso 5c parte 4) entran en TODAS las pruebas de arriba por la tabla
  (K0, K1, K1b, K3, I1, H1, H2, Q1, E2). Sus escenarios van en el modo de unión del doble (`union=True`), con su llave en el entorno;
  sin esa llave, 503 «sin_registro» (`unir_sin_registro`). Lo que la foto cubre de unión: 400 de validación, 404, 409
  (`cambio_quien_queda`), 502 con NocoDB caída en lectura y en escritura, unión sin
  enlaces, unión a medias con `continuar`, deshacer, y los 200 de repetición (`ya_estaba`).

Lo que NO ve (declarado):
  - La puerta de sesión de la App (`portal_personas`: 401 sin sesión, 403 sin permiso). El programa no la tiene.
  - La unión CON enlaces (asistencias, sesiones, proyectos, pagos, inscripciones que hay que mover): el doble del modo de unión
    declara que las listas de enlace salen vacías; una unión que tendría que mover algo da 500 y la prueba lo ve. Tampoco la marca
    VÁLIDA de un aviso de «Por resolver» (`unir_con_aviso` da `marcado: false`: el doble no tiene aviso real), ni `deshacer` con
    NocoDB caída en medio de sus escrituras (el doble solo tumba un método entero).
  - Que la App reenvíe la llave, la identidad y el `quien`: eso es de la App (encargo siguiente); aquí solo se prueba lo que el
    programa hace con lo que recibe.
  - El doble no es NocoDB: no imita sus códigos ni sus textos de error; una operación que cae se simula con `caidas`.
  - Ramas que la foto no ejercita: la marca válida de «Por resolver» (resolver y reabrir dan 400 o 409 con sus claves de prueba: la
    bandeja del doble tiene una sola marca, de otro grupo); el cambio de teléfono (lee sesiones y conversaciones, que el
    doble no tiene); la columna `notas` (el doble no la declara); los 400 de `dicho_el`, `nota` y `confirmo` de permiso.
  - El campo `cuando` de las anotaciones es la hora de la corrida: la foto y la prueba lo reemplazan por «<ahora>» en los dos lados
    (`escenarios_portal_escrituras.normalizar`) y la prueba solo comprueba que sea una fecha ISO con zona.
  - Q1 mira el argumento con un espía que no escribe: el comportamiento de las funciones lo cubre E2. Y el `quien` sí llega a
    NocoDB solo en las anotaciones de permiso: crear y editar no lo guardan en la tabla de personas (por eso Q1 hace falta).
  - El límite de cuerpo y el `Content-Length` no numérico no se prueban (no están portados; ver `el-programa-personas.md`).
"""
import ast
import hashlib
import json
import types
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
import candado  # noqa: E402  (el candado de «envío hecho»: la forma y los usos, sacados del código)

FOTA = RAIZ / "contrato_dorado" / "portal_escrituras.json"
SHA_DECLARADO = RAIZ / "contrato_dorado" / "SHA256_portal_escrituras"
COMANDO = [sys.executable, "-B", str(RAIZ / "servidor.py")]
QUIEN = esc.QUIEN_DORADO
RUTA_CREAR = esc.RUTA_PORTAL
RUTA_REGISTRO = ["/api/servicio/personas/cara", "/api/servicio/personas/nueva", "/api/servicio/personas/editar"]
RUTA_REGISTRO_LECTURA = "/api/servicio/personas/credito"
AVISO_DE_PRUEBA = "aviso-" + "d" * 40        # formato válido de aviso (no existe en el doble): va en las tres de unión para la Q1


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
        "unir": {"otra": 12, "clave": "union-prueba-0001", "aviso": AVISO_DE_PRUEBA},
        "continuar": {"aviso": AVISO_DE_PRUEBA},
        "deshacer": {"union": 1, "sobra": 12, "aviso": AVISO_DE_PRUEBA},
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
        return all((not esc.es_clave_de_hora(k) or esc._es_iso(v)) and _cuandos_son_iso(v) for k, v in x.items())
    if isinstance(x, list):
        return all(_cuandos_son_iso(v) for v in x)
    return True


def _correr(pasos, entorno=None, caidas=(), caidas_una_vez=(), union=False):
    escenario = {"nombre": "prueba", "pasos": pasos, "caidas": list(caidas), "caidas_una_vez": list(caidas_una_vez), "union": union}
    if entorno is not None:
        escenario["entorno"] = entorno
    return esc.ejecutar(escenario, COMANDO, cwd=str(RAIZ))


def _correr_escenario(escenario, pasos):
    """Corre los pasos de un escenario de la foto con SU modo (caídas, unión y entorno): lo mismo que hace la foto."""
    return _correr(pasos, entorno=escenario.get("entorno"), caidas=escenario.get("caidas", ()),
                   caidas_una_vez=escenario.get("caidas_una_vez", ()), union=escenario.get("union", False))


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
                real, errores = _correr_escenario(escenario, pasos)
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

    def test_K3_sin_llave_y_sin_identidad_da_401_antes_que_400(self):
        pasos = []
        for patron, (nombre, _tipo, _exige) in servidor.PORTAL_ESCRITURA.items():
            pasos.append({"ruta": muestra(patron), "llave": None, "quien": None, "tipo": None, "cuerpo": cuerpo_de(nombre)})
        real, errores = _correr(pasos)
        self.assertEqual(errores, [])
        self.assertEqual(len(real), len(servidor.PORTAL_ESCRITURA))
        for r in real:
            with self.subTest(ruta=r["ruta"]):
                self.assertEqual(r["status"], 401)
                self.assertEqual(r["respuesta"], {"error": "llave de servicio inválida"})
                self.assertEqual(r["pedidos"], [])

    def test_R1_un_fallo_no_se_recuerda_como_guardado_ni_creado(self):
        por_nombre = {e["nombre"]: e for e in esc.ESCENARIOS}
        for escenario_nombre, exito, escribe in (("editar_reintento_tras_fallo", 200, "PATCH"),
                                                 ("crear_reintento_tras_fallo", 201, "POST")):
            with self.subTest(escenario=escenario_nombre):
                escenario = por_nombre[escenario_nombre]
                real, errores = esc.ejecutar(escenario, COMANDO, cwd=str(RAIZ))
                self.assertEqual(errores, [])
                primero, segundo = real
                self.assertEqual(primero["status"], 502)
                self.assertIs(primero["respuesta"].get("sin_confirmar"), True)
                self.assertEqual(segundo["status"], exito)
                self.assertNotIn("ya_guardado", segundo["respuesta"])
                self.assertNotIn("ya_creada", segundo["respuesta"])
                self.assertIn(escribe, [q["metodo"] for q in segundo["pedidos"]],
                              "el reintento tiene que volver a escribir")

    def test_X1_el_exito_del_programa_es_el_de_la_app(self):
        arbol = ast.parse((RAIZ / "personas_portal_escritura.py").read_text(encoding="utf-8"))
        de_programa = {}
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "una_vez":
                for kw in nodo.keywords:
                    if kw.arg == "exito":
                        de_programa[nodo.args[0].value] = ast.unparse(kw.value.body)
        self.assertEqual(de_programa, self.foto["exito_de_la_app"])

    def test_R2_la_regla_recorre_los_codigos_de_la_foto(self):
        # Los códigos que la App contesta a crear y a editar, sacados de la foto (sus pasos, no una lista tecleada).
        codigos = {}
        for e in self.foto["escenarios"]:
            for paso in e["pasos"]:
                if paso["ruta"] == RUTA_CREAR:
                    codigos.setdefault("crear", set()).add(paso["status"])
                elif paso["ruta"].endswith("/editar"):
                    codigos.setdefault("editar", set()).add(paso["status"])
        self.assertTrue(codigos.get("crear") and codigos.get("editar"))
        exitos = {"crear": eval("lambda r: " + self.foto["exito_de_la_app"]["portal-persona-crear"]),
                  "editar": eval("lambda r: " + self.foto["exito_de_la_app"]["portal-persona-editar"])}
        ya_clave = {"crear": "ya_creada", "editar": "ya_guardado"}
        cubiertos = {"crear": set(), "editar": set()}
        for nombre in [e["nombre"] for e in esc.ESCENARIOS if "reintento" in e["nombre"]]:
            escenario = next(e for e in esc.ESCENARIOS if e["nombre"] == nombre)
            accion = "crear" if escenario["pasos"][0]["ruta"] == RUTA_CREAR else "editar"
            pasos = [p for p in escenario["pasos"] if esc.es_dorado(p)]
            real, errores = _correr_escenario(escenario, pasos)
            self.assertEqual(errores, [], nombre)
            primero, segundo = real
            cubiertos[accion].add(primero["status"])
            recordado = bool(exitos[accion]((primero["status"], primero["respuesta"])))
            with self.subTest(escenario=nombre):
                self.assertEqual(ya_clave[accion] in segundo["respuesta"], recordado,
                                 "la regla de la App dice recordado=%s" % recordado)
                if recordado:
                    self.assertIs(segundo["respuesta"][ya_clave[accion]], True)
        for accion in ("crear", "editar"):
            with self.subTest(accion=accion):
                self.assertTrue(codigos[accion] <= cubiertos[accion],
                                "códigos de la foto sin reintento: %s" % sorted(codigos[accion] - cubiertos[accion]))

    def _accion_de_cada_sitio_una_vez(self):
        """Los sitios de `una_vez` del programa (`candado.usos_y_sitios`, B1): ámbito -> acción. Ningún uso fuera de ellos."""
        violaciones, sitios = candado.usos_y_sitios(RAIZ)
        self.assertEqual(violaciones, [], "uso de una_vez fuera de un sitio")
        return {ambito: accion for ambito, accion, _archivo, _linea in sitios}

    def _juego_de_escenarios_de_la_foto(self):
        """Por acción (crear / editar): los escenarios de dos pasos con la misma clave, clasificados (fallo, mismo cuerpo,
        cuerpo distinto), y los códigos que la foto da a esa acción."""
        juego, codigos, primeros = {}, {}, {}
        for e in self.foto["escenarios"]:
            pasos = e["pasos"]
            ruta = pasos[0]["ruta"]
            if ruta == esc.RUTA_PORTAL:
                accion = "crear"
            elif ruta.endswith("/editar"):
                accion = "editar"
            else:
                continue
            codigos.setdefault(accion, set()).update(p["status"] for p in pasos if p["ruta"] == ruta)
            if e.get("caidas_una_vez"):
                clase = "fallo"
            elif len(pasos) == 2 and all(p.get("cuerpo", {}).get("clave_envio") for p in pasos):
                clase = "mismo_cuerpo" if pasos[0]["cuerpo"] == pasos[1]["cuerpo"] else "cuerpo_distinto"
            else:
                continue
            juego.setdefault(accion, {}).setdefault(clase, e["nombre"])
            primeros.setdefault(accion, set()).add(pasos[0]["status"])
        return juego, codigos, primeros

    def test_HU1_hermanos_de_una_vez_tienen_el_mismo_juego(self):
        por_ambito = self._accion_de_cada_sitio_una_vez()
        acciones = set(por_ambito.values())
        juego, codigos, primeros = self._juego_de_escenarios_de_la_foto()
        self.assertEqual(acciones, set(juego), "todo sitio de una_vez tiene escenarios en la foto")
        requeridas = {"fallo", "mismo_cuerpo", "cuerpo_distinto"}
        for accion in acciones:
            with self.subTest(accion=accion):
                self.assertTrue(requeridas <= set(juego[accion]),
                                "falta un escenario en %s: %s" % (accion, sorted(requeridas - set(juego[accion]))))
                self.assertTrue(codigos[accion] <= primeros[accion],
                                "códigos de la foto sin reintento en %s: %s" % (accion, sorted(codigos[accion] - primeros[accion])))
        self.assertEqual(set(juego["crear"]), set(juego["editar"]), "crear y editar tienen que tener el mismo juego de escenarios")
        # Comportamiento: en cada sitio, el escenario de cuerpo distinto escribe otra vez y el 2.º no trae ya_*.
        ya_clave = {"crear": "ya_creada", "editar": "ya_guardado"}
        for accion in acciones:
            with self.subTest(accion=accion, comportamiento=True):
                nombre = juego[accion]["cuerpo_distinto"]
                escenario = next(e for e in esc.ESCENARIOS if e["nombre"] == nombre)
                pasos = [p for p in escenario["pasos"] if esc.es_dorado(p)]
                real, errores = _correr_escenario(escenario, pasos)
                self.assertEqual(errores, [])
                segundo = real[1]
                self.assertNotIn(ya_clave[accion], segundo["respuesta"])
                self.assertTrue([q for q in segundo["pedidos"] if q["metodo"] != "GET"], "el cuerpo distinto tiene que escribir")

    def test_A1_el_candado_del_programa_es_el_de_la_app(self):
        """Compara las funciones y constantes NOMBRADAS del candado. NO compara el enlace a nivel de módulo de `copy`, `time`,
        `hashlib`, `json` y `threading`: reasignarlos queda fuera (frontera declarada; la burla SH pasa esta prueba)."""
        arbol = ast.parse((RAIZ / "personas_portal_escritura.py").read_text(encoding="utf-8"))
        self.assertEqual(candado.candado_del_modulo(arbol), self.foto["candado_de_la_app"])

    def test_B1_no_hay_usos_de_una_vez_fuera_de_los_sitios(self):
        """Ve `Name`, `Attribute`, `alias` y `FunctionDef`. NO ve accesos por cadena (`globals()[...]`, `getattr`): pasan (la burla
        GA pasa esta prueba)."""
        violaciones, sitios = candado.usos_y_sitios(RAIZ)
        self.assertEqual(violaciones, [])
        self.assertEqual(sorted({ambito for ambito, _a, _f, _l in sitios}), ["portal-persona-crear", "portal-persona-editar"])

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
        """Espías que solo miran los argumentos (no escriben). Crear, editar, permiso, resolver y reabrir reciben `quien` como último
        argumento. Unir y deshacer lo reciben (unir como 5.º, deshacer como 2.º). Continuar NO recibe `quien` (como la App); su aviso
        de «Por resolver», que sí lo lleva (`marcar_aviso_de_la_union`), lo recibe de la cabecera. El `quien` del cuerpo no cuenta."""
        recibidos = {}

        def espia(nombre, devuelve):
            def f(*args, **kwargs):
                recibidos[nombre] = (args, kwargs)
                return devuelve
            return f
        parches = [
            mock.patch.object(personas, "crear_persona_portal", espia("crear", (201, {"estado": "creada"}))),
            mock.patch.object(personas, "editar_persona_portal", espia("editar", (200, {"estado": "sin_cambios"}))),
            mock.patch.object(personas, "anotar_permiso", espia("permiso", (200, {"estado": "ya_estaba"}))),
            mock.patch.object(personas, "portal_por_resolver_marcar", espia("resolver", (400, {"error": "x"}))),
            mock.patch.object(personas, "unir_fichas", espia("unir", (200, {"estado": "unida"}))),
            mock.patch.object(personas, "continuar_union", espia("continuar", (200, {"estado": "unida"}))),
            mock.patch.object(personas, "deshacer_union", espia("deshacer", (200, {"estado": "deshecha"}))),
            mock.patch.object(personas, "marcar_aviso_de_la_union", espia("aviso", {"clave": AVISO_DE_PRUEBA, "marcado": True})),
        ]
        for p in parches:
            p.start()
        try:
            for patron, (nombre, _tipo, _exige) in servidor.PORTAL_ESCRITURA.items():
                cuerpo = dict(cuerpo_de(nombre), quien="Otra Persona")
                ruta = muestra(patron)
                crudo = json.dumps(cuerpo).encode("utf-8")
                grupos = () if nombre in ("crear", "resolver", "reabrir") else ("2",)
                personas_portal_escritura.responder(nombre, ruta, grupos, crudo, QUIEN)
        finally:
            for p in parches:
                p.stop()
        self.assertEqual(recibidos["crear"][0][-1], QUIEN)
        self.assertEqual(recibidos["editar"][0][-1], QUIEN)
        self.assertEqual(recibidos["permiso"][0][-1], QUIEN)
        self.assertEqual(recibidos["resolver"][0][-1], QUIEN)
        self.assertEqual(recibidos["unir"][0][4], QUIEN, "unir_fichas(ficha, otra, resoluciones, clave, quien, ...)")
        self.assertEqual(recibidos["deshacer"][0][1], QUIEN, "deshacer_union(ficha, quien, ...)")
        self.assertEqual(recibidos["continuar"], ((2,), {}), "continuar_union(ficha): la App no le pasa quien")
        self.assertEqual(recibidos["aviso"][0][3], QUIEN, "el aviso de «Por resolver» lleva el quien de la cabecera")

    def test_Q2_el_nombre_en_utf8_llega_entero(self):
        self.assertEqual(servidor.quien_de_la_cabecera("Ana PÃ©rez"), "Ana Pérez")
        self.assertEqual(servidor.quien_de_la_cabecera("  Ana  "), "Ana")
        self.assertEqual(servidor.quien_de_la_cabecera(None), "")
        self.assertEqual(servidor.quien_de_la_cabecera("Ana€"), "Ana€")


class CandadoEnProceso(unittest.TestCase):
    """C1 a C3: el candado con reloj simulado. Solo se cambia la fuente del instante (`time` del módulo, en la prueba); el camino de
    código es el de producción."""

    def setUp(self):
        self.reloj = [0.0]
        self.parche = mock.patch.object(personas_portal_escritura, "time", types.SimpleNamespace(monotonic=lambda: self.reloj[0]))
        self.parche.start()
        self._vaciar()

    def tearDown(self):
        self.parche.stop()
        self._vaciar()

    @staticmethod
    def _vaciar():
        with personas_portal_escritura._UNA_VEZ_LOCK:
            personas_portal_escritura._UNA_VEZ.clear()

    @staticmethod
    def _llamar(clave, escribir):
        cuerpo = {"cambios": {"instagram": "x"}}
        if clave is not None:
            cuerpo["clave_envio"] = clave
        return personas_portal_escritura.una_vez("portal-persona-editar", "/api/portal-personas/2/editar", cuerpo, escribir)

    def test_C1_sin_clave_escribe_siempre(self):
        escrituras = []

        def escribir():
            escrituras.append(1)
            return (200, {"estado": "guardado"})
        self._llamar(None, escribir)
        _res, repetido = self._llamar(None, escribir)
        self.assertEqual(len(escrituras), 2)
        self.assertFalse(repetido)

    def test_C2_con_clave_recuerda_600_s_y_despues_vence(self):
        escrituras = []

        def escribir():
            escrituras.append(1)
            return (200, {"estado": "guardado"})
        self._llamar("k", escribir)
        self.reloj[0] = 599.0
        _res, repetido = self._llamar("k", escribir)
        self.assertTrue(repetido)
        self.assertEqual(len(escrituras), 1)
        self.reloj[0] = 700.0
        _res, repetido = self._llamar("k", escribir)
        self.assertFalse(repetido)
        self.assertEqual(len(escrituras), 2)

    def test_C3_una_excepcion_no_se_recuerda(self):
        intentos = []

        def escribir():
            intentos.append(1)
            if len(intentos) == 1:
                raise RuntimeError("la base no contesta")
            return (200, {"estado": "guardado"})
        with self.assertRaises(RuntimeError):
            self._llamar("k2", escribir)
        _res, repetido = self._llamar("k2", escribir)
        self.assertEqual(len(intentos), 2)
        self.assertFalse(repetido)


if __name__ == "__main__":
    unittest.main()
