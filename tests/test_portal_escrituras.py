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
  K0  tablas de escritura (`servidor.escrituras_del_portal()`: POST y PATCH) + `PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA` = las rutas de
      escritura que la App contesta (`rutas_de_la_app` del portal y `rutas_checkin_de_la_app` de sesión). Ningún patrón está en la
      tabla y en la lista de fuera a la vez. Cada salida tiene su motivo escrito.
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
  H2  una ruta que la tabla no conoce (inventada) da 404 y cero pedidos. Las rutas de `PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`
      (hoy `cara` y `parecidas`, de sesión) dan 404 y no escriben: la lista de fuera se recorre igual.
  Q1  el `quien` que se pasa a cada función es el de la cabecera (espía que solo mira el argumento); el del cuerpo no cuenta.
  Q2  la cabecera con el nombre en UTF-8 llega entera («Pérez»), no como «PÃ©rez».
  Las tres de UNIÓN (unir, unir/continuar, unir/deshacer, paso 5c parte 4) entran en TODAS las pruebas de arriba por la tabla
  (K0, K1, K1b, K3, I1, H1, H2, Q1, E2). Sus escenarios van en el modo de unión del doble (`union=True`), con su llave en el entorno;
  sin esa llave, 503 «sin_registro» (`unir_sin_registro`). Lo que la foto cubre de unión: 400 de validación, 404, 409
  (`cambio_quien_queda`), 502 con NocoDB caída en lectura y en escritura, unión sin
  enlaces, unión a medias con `continuar`, deshacer, y los 200 de repetición (`ya_estaba`).

  Parte 7 (check-in, tipo C): `crear_checkin` (POST /api/personas) y `editar_checkin` (PATCH /api/personas/<id>, tabla
  `PORTAL_ESCRITURA_PATCH`) entran en TODAS las pruebas por `servidor.escrituras_del_portal()`, con el tipo de su fila. Ninguna lleva
  `quien` (la App no lo escribe). `cara` y `parecidas` quedan FUERA (`PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`, con su motivo).

Lo que NO ve (declarado):
  - La puerta de sesión de la App (`portal_personas`: 401 sin sesión, 403 sin permiso). El programa no la tiene. Tampoco la de
    `puede_borrar_fichas` (parte 5: `borrar` y `devolver` la piden en la App, y aquí no se mira). Quien tenga la llave del portal puede
    borrar y devolver sin ese permiso: es la frontera de la decisión de la sala, y la App la mira antes de reenviar. Las pruebas no la
    cubren, y no tiene que cubrirla el programa.
  - `borrar` y `devolver` (parte 5) entran en K0, K1, K3, I1, H1 y Q1 por la tabla. Sus escenarios van en `ENTORNO_BORRAR` (tablas de
    envíos y de uniones). La foto tiene: el éxito de `borrar` (200 `quitada`) y de `devolver` (200 `devuelta`), la repetición de los dos
    (`ya_estaba`), el 400 de clave (vacía, corta, no texto) y de cuerpo ilegible, el 404 de ficha que no existe, el 409 de paradas (crédito,
    ya guardada, unida), el 409 `clave_repetida`, el 409 `otra_operacion`, el 409 `no_borrada` de devolver, el 502 de lectura caída, el 502
    `sin_confirmar` con la escritura caída (POST) y con el PATCH caído, el reintento con la misma clave tras un fallo, y el 503 sin registro.
    NO tiene (el doble no tiene los datos o el camino no se puede provocar sin tocar NocoDB real): de `borrar`, los 502 `registro_ilegible`
    y `no_se_pudo_apuntar`, los 409 `borrado_en_otro_estado` y `cambio_mientras_la_borrabas`, el 404 y el 409 `ficha_desaparecio`, y las
    paradas 2 (reserva por venir), 3 (envío por salir), 4 (no escribir o permiso no sabido), 6 (proyecto) y 7 (no se pudo medir); de
    `devolver`, los 409 `otra_operacion`, `viva`, `ocupado` y `cambio_mientras_la_devolvias`. Todo eso es HUECO DE PRUEBA declarado, no
    «no puede pasar»: en producción sí puede pasar.
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
import personas_escrituras  # noqa: E402  (parte 7: crear y editar del check-in, tipo C)
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
    return patron.replace(r"(\d{1,9})", "2").replace(r"(\d+)", "2")


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
        "borrar": {"clave": "borrado-prueba-0001"},
        "devolver": {},
        "crear_checkin": {"nombre": "Sesion Hermana", "telefono": "8095550302"},
        "editar_checkin": {"instagram": "hermana_s"},
    }[nombre]


def _tipo_pedido(tipo_de_la_fila, tipo):
    """El tipo que manda el paso: «fila» = el de su ruta; «otro» = el contrario (A con C); cualquier otro valor, tal cual."""
    if tipo == "fila":
        return tipo_de_la_fila
    if tipo == "otro":
        return "C" if tipo_de_la_fila == "A" else "A"
    return tipo


def _pasos_de_la_tabla(llave="portal", quien=QUIEN, tipo="fila", cuerpo=None):
    """Un paso por cada escritura que el programa sirve (POST y PATCH), con SU verbo y el tipo de su fila."""
    pasos = []
    for verbo, patron, (nombre, tipo_de_la_fila, _exige) in servidor.escrituras_del_portal():
        pasos.append({"ruta": muestra(patron), "metodo": verbo, "llave": llave, "quien": quien,
                      "tipo": _tipo_pedido(tipo_de_la_fila, tipo), "cuerpo": cuerpo if cuerpo is not None else cuerpo_de(nombre)})
    return pasos

def _cuandos_son_iso(x):
    """Cierto si todo valor de una clave de hora (a cualquier nivel) es una fecha ISO con zona, o NULO: una marca que se quita (la
    `quitada_el` de una ficha devuelta, parte 5) se escribe como null y no es una hora. Lo que no lo es queda sin cambiar al normalizar y
    no iguala la foto, así que esta comprobación solo le pone el motivo al fallo."""
    if isinstance(x, dict):
        return all((not esc.es_clave_de_hora(k) or v is None or esc._es_iso(v)) and _cuandos_son_iso(v) for k, v in x.items())
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


def _acciones_con_aviso():
    """{acción: (función que la hace, modo, estado)} para las acciones de `_ejecutar` que llaman a `_con_el_aviso_marcado`, sacado del
    AST de `personas_portal_escritura.py`: la acción es la rama `if nombre == "<acción>"`; la función, la que llama esa rama; el modo y el
    estado, los argumentos constantes de la llamada a `_con_el_aviso_marcado` dentro de esa función."""
    arbol = ast.parse((RAIZ / "personas_portal_escritura.py").read_text(encoding="utf-8"))
    funciones = {n.name: n for n in arbol.body if isinstance(n, ast.FunctionDef)}
    por_funcion = {}
    for nombre, nodo in funciones.items():
        for x in ast.walk(nodo):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "_con_el_aviso_marcado":
                por_funcion[nombre] = (x.args[1].value, x.args[2].value)
    salida = {}
    for x in ast.walk(funciones["_ejecutar"]):
        if isinstance(x, ast.If) and isinstance(x.test, ast.Compare) and isinstance(x.test.left, ast.Name) and x.test.left.id == "nombre":
            comparado = x.test.comparators[0]
            acciones_de_la_rama = [e.value for e in comparado.elts] if isinstance(comparado, ast.Tuple) else [comparado.value]
            for y in ast.walk(x):
                if isinstance(y, ast.Call) and isinstance(y.func, ast.Name) and y.func.id in por_funcion:
                    for accion in acciones_de_la_rama:
                        salida[accion] = (y.func.id,) + por_funcion[y.func.id]
    return salida


def _accion_de_la_foto(paso):
    """La acción de `_ejecutar` que contesta un paso de la foto, o None si no es un sitio de `una_vez` (crear, editar o crear_checkin)."""
    ruta = paso["ruta"]
    if ruta == esc.RUTA_PORTAL:
        return "crear"
    if ruta.endswith("/editar"):
        return "editar"
    if ruta == esc.RUTA_CHECKIN:
        return "crear_checkin"
    return None


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
                    self.assertEqual(foto.get("metodo", "POST"), paso.get("metodo", "POST"))
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

    def test_K0_tabla_mas_fuera_son_las_rutas_de_escritura_de_la_app(self):
        """Tabla POST + tabla PATCH + fuera = las rutas que la App contesta: las del portal (`rutas_de_la_app`, POST) y las de sesión
        (`rutas_checkin_de_la_app`, POST y PATCH, leídas con AST de `do_POST` y `do_PATCH`)."""
        de_la_app = {("POST", r["patron"], r["exacta"]) for r in self.foto["rutas_de_la_app"]}
        de_la_app |= {(r["verbo"], r["patron"], r["exacta"]) for r in self.foto["rutas_checkin_de_la_app"]}
        de_la_tabla = {(v, p, "(" not in p) for v, p, _valor in servidor.escrituras_del_portal()}
        fuera = {("POST", p, "(" not in p) for p in servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA}
        patrones_de_la_tabla = {p for _v, p, _valor in servidor.escrituras_del_portal()}
        self.assertEqual(patrones_de_la_tabla & set(servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA), set())
        self.assertEqual(de_la_tabla | fuera, de_la_app)
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
        pasos = [{"ruta": muestra(p), "metodo": v, "llave": None, "quien": QUIEN, "tipo": tipo_fila, "crudo": "no es json"}
                 for v, p, (_nombre, tipo_fila, _exige) in servidor.escrituras_del_portal()]
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
        for verbo, patron, (nombre, _tipo, _exige) in servidor.escrituras_del_portal():
            pasos.append({"ruta": muestra(patron), "metodo": verbo, "llave": None, "quien": None, "tipo": None,
                          "cuerpo": cuerpo_de(nombre)})
        real, errores = _correr(pasos)
        self.assertEqual(errores, [])
        self.assertEqual(len(real), len(pasos))
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
        """Cada `una_vez` del programa (AST de `personas_portal_escritura.py`) tiene el mismo `exito` que la App (la foto): el del portal
        (crear y editar) y el del check-in («persona»), que no lleva `exito` en la App (`None` en las dos)."""
        arbol = ast.parse((RAIZ / "personas_portal_escritura.py").read_text(encoding="utf-8"))
        de_programa = {}
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "una_vez":
                exitos = [ast.unparse(kw.value.body) for kw in nodo.keywords if kw.arg == "exito"]
                de_programa[nodo.args[0].value] = exitos[0] if exitos else None
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
        """Por acción (crear / editar / crear_checkin): los escenarios de dos pasos con la misma clave, clasificados (fallo, mismo cuerpo,
        cuerpo distinto), y los códigos que la foto da a esa acción. La acción de cada paso la da `_accion_de_la_foto`."""
        juego, codigos, primeros = {}, {}, {}
        for e in self.foto["escenarios"]:
            pasos = e["pasos"]
            accion = _accion_de_la_foto(pasos[0])
            if accion is None:
                continue
            codigos.setdefault(accion, set()).update(p["status"] for p in pasos if _accion_de_la_foto(p) == accion)
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
        for accion in acciones:
            self.assertEqual(set(juego[accion]), set(juego["crear"]), "el juego de %s es el mismo que el de crear" % accion)
        # Comportamiento: en cada sitio, el escenario de cuerpo distinto escribe otra vez y el 2.º no trae ya_*.
        ya_clave = {"crear": "ya_creada", "editar": "ya_guardado", "crear_checkin": "ya_guardado"}
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
        self.assertEqual(sorted({ambito for ambito, _a, _f, _l in sitios}), ["persona", "portal-persona-crear", "portal-persona-editar"])

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
        """La identidad de cada fila es la de SU ruta (tipo «fila»); «otro» manda el tipo contrario (A con C) y tiene que dar 400."""
        variantes = [
            {"quien": None, "tipo": "fila"},
            {"quien": "", "tipo": "fila"},
            {"quien": "   ", "tipo": "fila"},
            {"quien": QUIEN, "tipo": None},
            {"quien": QUIEN, "tipo": "B"},
            {"quien": QUIEN, "tipo": "a"},
            {"quien": QUIEN, "tipo": ""},
            {"quien": QUIEN, "tipo": "otro"},
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
        self.assertEqual(len(real), len(servidor.escrituras_del_portal()))
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
        """Espías que solo miran los argumentos (no escriben) y guardan CADA llamada. Por cada escritura de la tabla (POST y PATCH) se corre
        el pedido y se mira lo que llegó en ese pedido. Crear, editar, permiso, resolver y reabrir reciben `quien` como último argumento;
        unir y deshacer lo reciben (unir como 5.º, deshacer como 2.º); continuar NO recibe `quien` (como la App). Las del check-in
        (crear_checkin y editar_checkin) NO reciben `quien`: la App no lo escribe en esas rutas. El aviso de «Por resolver»
        (`_con_el_aviso_marcado`) recibe el `quien` de la cabecera en CADA acción que lo llama: las acciones y sus argumentos (modo,
        estado) salen de `_acciones_con_aviso()`, que lee el AST de `personas_portal_escritura.py`, no de una lista tecleada.
        El `quien` del cuerpo no cuenta."""
        recibidos = {}

        def espia(nombre, devuelve):
            def f(*args, **kwargs):
                recibidos.setdefault(nombre, []).append((args, kwargs))
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
            mock.patch.object(personas, "quitar_ficha", espia("borrar", (200, {"estado": "quitada"}))),
            mock.patch.object(personas, "devolver_ficha", espia("devolver", (200, {"estado": "devuelta"}))),
            mock.patch.object(personas_escrituras, "crear_persona", espia("crear_checkin", {"Id": 9, "_releida": {"Id": 9, "nombre": "x"}})),
            mock.patch.object(personas_escrituras, "editar_persona", espia("editar_checkin", {"Id": 2, "nombre": "x"})),
            mock.patch.object(personas_portal_escritura, "_con_el_aviso_marcado",
                              espia("aviso", {"clave": AVISO_DE_PRUEBA, "marcado": True})),
        ]
        por_ruta = {}
        for p in parches:
            p.start()
        try:
            for _verbo, patron, (nombre, _tipo, _exige) in servidor.escrituras_del_portal():
                recibidos.clear()
                cuerpo = dict(cuerpo_de(nombre), quien="Otra Persona")
                ruta = muestra(patron)
                crudo = json.dumps(cuerpo).encode("utf-8")
                grupos = () if nombre in ("crear", "resolver", "reabrir", "crear_checkin") else ("2",)
                personas_portal_escritura.responder(nombre, ruta, grupos, crudo, QUIEN)
                por_ruta[nombre] = {k: list(v) for k, v in recibidos.items()}
        finally:
            for p in parches:
                p.stop()
        self.assertEqual(por_ruta["crear"]["crear"][0][0][-1], QUIEN)
        self.assertEqual(por_ruta["editar"]["editar"][0][0][-1], QUIEN)
        self.assertEqual(por_ruta["permiso"]["permiso"][0][0][-1], QUIEN)
        self.assertEqual(por_ruta["resolver"]["resolver"][0][0][-1], QUIEN)
        self.assertEqual(por_ruta["unir"]["unir"][0][0][4], QUIEN, "unir_fichas(ficha, otra, resoluciones, clave, quien, ...)")
        self.assertEqual(por_ruta["deshacer"]["deshacer"][0][0][1], QUIEN, "deshacer_union(ficha, quien, ...)")
        self.assertEqual(por_ruta["continuar"]["continuar"], [((2,), {})], "continuar_union(ficha): la App no le pasa quien")
        self.assertEqual(por_ruta["borrar"]["borrar"][0][0][-1], QUIEN, "quitar_ficha(ficha, clave, quien): el quien de la cabecera")
        self.assertEqual(por_ruta["devolver"]["devolver"][0][0][-1], QUIEN, "devolver_ficha(ficha, quien): el quien de la cabecera")
        self.assertFalse(any(a == QUIEN for a in por_ruta["crear_checkin"]["crear_checkin"][0][0]), "crear_checkin: la App no escribe quien")
        self.assertFalse(any(a == QUIEN for a in por_ruta["editar_checkin"]["editar_checkin"][0][0]), "editar_checkin: la App no escribe quien")
        acciones = _acciones_con_aviso()
        self.assertEqual(set(acciones), {"unir", "continuar", "deshacer"}, "las acciones que marcan aviso, sacadas del AST de _ejecutar")
        for accion, (_funcion, modo, estado) in sorted(acciones.items()):
            with self.subTest(accion=accion):
                llamadas = por_ruta[accion].get("aviso", [])
                self.assertEqual(len(llamadas), 1, "la acción %s tiene que marcar el aviso una vez" % accion)
                (args, _kwargs) = llamadas[0]
                self.assertEqual(args[0], AVISO_DE_PRUEBA, "el aviso que llega es el del cuerpo")
                self.assertEqual(args[1], modo, "modo del aviso, del AST")
                self.assertEqual(args[2], estado, "estado del aviso, del AST")
                self.assertEqual(args[5], QUIEN, "el aviso de «Por resolver» lleva el quien de la cabecera")

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
