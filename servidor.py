# -*- coding: utf-8 -*-
"""EL PROGRAMA DE PERSONAS: el servidor de sus rutas de LECTURA y de las tres ESCRITURAS de Registro (paso 5 de
`disenos/personas-programa-aparte/DISENO.md`, partes 1 y 2).

Rutas de lectura, con las mismas llaves y las mismas respuestas que la App de registro en `0b48b5d` (`PERSONAS_LECTURA_POST` y
`personas_lectura_config` de su `server.py`):
  POST /api/servicio/personas/identidad, /fichas, /pagina, /anotaciones   cabecera X-Personas-Lectura-Llave  (PERSONAS_LECTURA_LLAVE)
  POST /api/servicio/personas/credito, /buscar, /bandeja, /creditos-vivos cabecera X-Personas-Registro-Llave (PERSONAS_REGISTRO_LLAVE)
  GET  /api/servicio/personas/config                                     cabecera X-Personas-Lectura-Llave

🔴 Cada ruta de lectura valida SU llave ANTES de leer el cuerpo. Sin la llave de su grupo, con otra, o con la variable vacía: 401
y no se lee nada. Ninguna ruta de lectura escribe.

ESCRITURAS PARA REGISTRO (paso 5b, `personas_escritura_rutas.py`), con las mismas respuestas que la App (`personas_escritura_post`):
  POST /api/servicio/personas/cara, /nueva, /editar   cabecera X-Personas-Registro-Escritura-Llave  (PERSONAS_REGISTRO_ESCRITURA_LLAVE)
🔴 Su llave se mira ANTES de leer el cuerpo y no abre ninguna lectura, ni la de Mercadeo ni la de Registro. Sin ella, con otra o con
la variable vacía: 401, y no se escribe nada.

LECTURAS DEL PORTAL, DE SESIÓN Y DE GOOGLE (paso 5c, partes 1, 2, 5 y 6; parte 8 para la de tipo D): las GET de la tabla `PORTAL_LECTURA` de
abajo. Tipo «A»: las del portal (lista, ficha, nueva, borradas, por-resolver, unir/revisar y borrar/revisar). Tipo «C»: las que la App
contesta bajo `autorizado()` (`GET /api/personas?q=`, el buscador, y `GET /api/persona-instrumentos`). Tipo «D» (parte 8): `GET
/api/google/contactos/conteo`, que la App contesta solo al PIN de administración. Cabecera X-Personas-Portal-Llave
(PERSONAS_PORTAL_LLAVE), más la identidad que pone la App: X-Personas-Portal-Quien (quien pide, no vacío) y X-Personas-Portal-Tipo (= el
tipo de la ruta, «A», «C» o «D»).
🔴 La llave del portal se mira PRIMERO: sin ella, con otra (la de Mercadeo y la de Registro incluidas) o con la variable vacía: 401,
y no se lee NocoDB. Con la llave bien pero sin identidad, o con un tipo que no es el de la ruta: 400, y no se lee NocoDB. La cabecera
de identidad que venga del navegador no decide nada si la llave no es la del portal. La App mira la puerta de sesión antes de
reenviar; este programa no la ve. Las respuestas: `personas_portal_lectura.py` (copia de la App, `594ec12`), con la foto de
`contrato/portal_lectura.json`. De las GET del portal y de sesión que la App contesta, la única que NO se porta es `entrada/cuadro`, en
`PORTAL_FUERA_DEL_PROGRAMA`, con su motivo. Las GET de proveedores no están en esta tabla: van con Compras (decisión 3 del diseño).
La de Google (tipo «D») usa las tres variables `GOOGLE_CONTACTOS_*` de `google_contactos.VARIABLES`: sin ellas, 503 con sus nombres.

ESCRITURAS DEL PORTAL (paso 5c, partes 3 a 5): las POST del portal en la tabla `PORTAL_ESCRITURA` (crear, editar, permiso, resolver,
reabrir, las de unir: unir, unir/continuar y unir/deshacer, y borrar y devolver).
Misma cabecera de llave (X-Personas-Portal-Llave) y la misma identidad que las lecturas, más el `quien` que pone la App en
X-Personas-Portal-Quien: es el que queda escrito, y el `quien` del cuerpo no se lee. La llave se mira antes que el cuerpo. Las
respuestas: `personas_portal_escritura.py` (copia de `Handler.portal_personas_post` de la App, `594ec12`, sin su puerta de sesión).
🔴 Borrar y devolver piden en la App el permiso `puede_borrar_fichas` (`Handler.puede_borrar_fichas`), y el programa NO lo mira: la App
lo mira antes de reenviar. Quien tenga la llave del portal puede borrar y devolver sin ese permiso, igual que puede escribir con
cualquier `quien`. Esa frontera está declarada aquí y en `el-programa-personas.md`. La App no se toca.

ESCRITURAS DE SESIÓN DEL CHECK-IN (paso 5c, parte 7, tipo «C»): `POST /api/personas` (crear, fila de `PORTAL_ESCRITURA`) y
`PATCH /api/personas/<id>` (editar, fila de `PORTAL_ESCRITURA_PATCH`). Misma llave e identidad que el portal, con `X-Personas-Portal-Tipo`
= `C`. Ninguna de las dos escribe `quien` (la App tampoco). Las respuestas: `personas_portal_escritura.py`, con los errores de la App para
estas rutas (`do_POST` y `do_PATCH`: 400 con el texto de la excepción, 500 con `str(e)`). FUERA, con su motivo en
`PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`: `POST /api/personas/parecidas` y `POST /api/personas/<id>/cara` (dependen de la memoria de caras de la App).
La paridad con la App (la foto) vale con `PROGRAMA_REGISTRO_ESCRITURAS_PERSONAS` APAGADA, que es su valor por defecto: con ella encendida,
la App manda crear, editar y cara al servicio de Personas por red, y este programa no replica ese camino.

NO PORTADO (declarado en `el-programa-personas.md`, «Lo que falta»): la puerta de Natalia, las GET de proveedores y `entrada/cuadro`.

Arranque: `python3 servidor.py`. Variables (solo sus nombres): PORT (3000), HOST (0.0.0.0), NOCODB_BASE, NOCODB_TOKEN,
PERSONAS_LECTURA_LLAVE, PERSONAS_REGISTRO_LLAVE, PERSONAS_REGISTRO_ESCRITURA_LLAVE, PERSONAS_PORTAL_LLAVE, NOCODB_T_*, y para la ruta de
tipo «D»: GOOGLE_CONTACTOS_CLIENT_ID, GOOGLE_CONTACTOS_CLIENT_SECRET, GOOGLE_CONTACTOS_REFRESH_TOKEN (las mismas de la App).
"""
import hmac
import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import base
import personas_escritura_rutas
import personas_escrituras
import personas_lectura
import personas_portal_escritura
import personas_portal_lectura
import personas_servicio_rutas

LLAVE_PERSONAS_LECTURA = os.environ.get("PERSONAS_LECTURA_LLAVE", "").strip()
LLAVE_PERSONAS_REGISTRO = os.environ.get("PERSONAS_REGISTRO_LLAVE", "").strip()
LLAVE_PERSONAS_ESCRITURA_REGISTRO = os.environ.get("PERSONAS_REGISTRO_ESCRITURA_LLAVE", "").strip()
LLAVE_PERSONAS_PORTAL = os.environ.get("PERSONAS_PORTAL_LLAVE", "").strip()

ESCRITURA_RUTAS = {
    "/api/servicio/personas/cara": "cara",
    "/api/servicio/personas/nueva": "nueva",
    "/api/servicio/personas/editar": "editar",
}
ESCRITURA_FUNCIONES = {
    "cara": personas_escritura_rutas.cara, "nueva": personas_escritura_rutas.nueva,
    "editar": personas_escritura_rutas.editar,
}

LECTURA_POST = {
    "/api/servicio/personas/identidad": "identidad",
    "/api/servicio/personas/fichas": "fichas",
    "/api/servicio/personas/pagina": "pagina",
    "/api/servicio/personas/anotaciones": "anotaciones",
    "/api/servicio/personas/credito": "credito",
    "/api/servicio/personas/buscar": "buscar",
    "/api/servicio/personas/bandeja": "bandeja",
    "/api/servicio/personas/creditos-vivos": "creditos_vivos",
}
REGISTRO_NOMBRES = ("credito", "buscar", "bandeja", "creditos_vivos")
CONFIG_RUTA = "/api/servicio/personas/config"
FUNCIONES = {
    "identidad": personas_lectura.identidad, "fichas": personas_lectura.fichas,
    "pagina": personas_lectura.pagina, "anotaciones": personas_lectura.anotaciones,
    "credito": personas_servicio_rutas.credito, "buscar": personas_servicio_rutas.buscar,
    "bandeja": personas_servicio_rutas.bandeja, "creditos_vivos": personas_servicio_rutas.creditos_vivos,
}
ERROR_LLAVE = {"error": "llave de servicio inválida"}
ERROR_IDENTIDAD = {"error": "identidad de portal ausente o no corresponde a la ruta"}

# TABLA ÚNICA de las lecturas: patrón de ruta (el mismo texto que la App usa) -> (nombre de la lectura en `personas_portal_lectura`,
# tipo que la App pone en la identidad, ¿exige identidad?). Las claves salen de la App: CP3 las compara con `rutas_de_la_app` (las del
# portal, de `portal_personas_get`) y `rutas_de_sesion_de_la_app` (las de sesión, de `do_GET`, bajo `autorizado()`) de la foto. El tipo «A»
# es el de la puerta `entra_personas` del portal; el «C» es el de `autorizado()` (filas 9 y 10 de `CONTRATO-SESION.md`); el «D» es el de
# `veredicto().es_admin` (fila 12, parte 8). La puerta de cada tipo la mira la App antes de reenviar; aquí solo se mira el tipo que llega.
PORTAL_TIPO_A = "A"
PORTAL_TIPO_C = "C"
PORTAL_TIPO_D = "D"
PORTAL_LECTURA = {
    "/api/portal-personas": ("lista", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})": ("ficha", PORTAL_TIPO_A, True),
    "/api/portal-personas/nueva": ("nueva", PORTAL_TIPO_A, True),
    "/api/portal-personas/borradas": ("borradas", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver": ("por_resolver", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/unir/revisar": ("unir_revisar", PORTAL_TIPO_A, True),
    # Parte 5: revisar un borrado (no escribe). La App pide el permiso `puede_borrar_fichas` antes de reenviar; el programa no lo mira.
    r"/api/portal-personas/(\d{1,9})/borrar/revisar": ("borrar_revisar", PORTAL_TIPO_A, True),
    # Parte 6, tipo C (cualquier sesión válida en la App): el buscador del check-in y de los selectores, y las opciones de instrumento.
    "/api/personas": ("buscar", PORTAL_TIPO_C, True),
    "/api/persona-instrumentos": ("instrumentos", PORTAL_TIPO_C, True),
    # Parte 8, tipo D (solo administración en la App): contar los contactos de Google que casan con las fichas. Solo cifras.
    "/api/google/contactos/conteo": ("google_conteo", PORTAL_TIPO_D, True),
}
# Rutas que la App contesta y que el programa NO sirve, con el motivo. CP3 exige que tabla + esto = las rutas de la App.
PORTAL_FUERA_DEL_PROGRAMA = {
    "/api/portal-personas/entrada/cuadro": (
        "cuadro de la entrada (`cuadro_de_la_entrada`, App en 594ec12, `server.py:7350`). Lo que pide ya está en el programa: la "
        "bandeja (`base._bandeja_leer`, `personas._bandeja_pagina`; la ruta `/api/servicio/personas/bandeja`, `personas_servicio_rutas"
        ".bandeja`, es la que la App llama por red con `personas_cliente`) y la puerta (`personas.PUERTA_CASOS`, `PUERTA_AVISOS`, "
        "`clave_id`, `clave_telefono`). Lo que NO está: el formato del `resultado` de cada fila (`_entrada_leer_resultado` y "
        "`_entrada_resumen`, `server.py:7016` y `:7001`). Lo escribe la entrada de Natalia (`entrada_procesar`, `server.py:7140`, "
        "un `json.dumps` del resumen) y lo lee también `POST /api/fichas/entrada` (`_entrada_cuerpo`, `server.py:7040`). Es de la "
        "entrada, no de Personas: portarlo sin su escritor partiría el contrato entre dos repos. Sus piezas propias (`CuadroPersonas`, "
        "`cuadro_renglon`, `CUADRO_*`) dependen de él."),
}


# ESCRITURAS POST del portal y de sesión (partes 3 a 5 y 7): la tabla de las POST, mismo formato que `PORTAL_LECTURA`. K0 de
# `tests/test_portal_escrituras.py` las compara con las rutas que la App contesta (AST de `portal_personas_post`, de `do_POST` y de
# `do_PATCH`), con `PORTAL_ESCRITURA_PATCH` y con `PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA` (las que el programa deja fuera, con su motivo).
PORTAL_ESCRITURA = {
    "/api/portal-personas": ("crear", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/editar": ("editar", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/permiso": ("permiso", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver/resolver": ("resolver", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver/reabrir": ("reabrir", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/unir": ("unir", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/unir/continuar": ("continuar", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/unir/deshacer": ("deshacer", PORTAL_TIPO_A, True),
    # Parte 5: borrar (guardar aparte, con su registro) y devolver. La App pide `puede_borrar_fichas` antes de reenviar: aquí no se mira.
    r"/api/portal-personas/(\d{1,9})/borrar": ("borrar", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/devolver": ("devolver", PORTAL_TIPO_A, True),
    # Parte 7, tipo C (check-in): crear desde el check-in. La App la contesta en `do_POST` bajo `autorizado()`, con `una_vez("persona")`.
    "/api/personas": ("crear_checkin", PORTAL_TIPO_C, True),
}
# Parte 7: las escrituras PATCH tienen su tabla hermana, con el mismo formato (el verbo no cabe en las claves de `PORTAL_ESCRITURA`,
# que son POST). `escrituras_del_portal()` las junta para las pruebas. `(\d+)` como en la App (`re.fullmatch(r"/api/personas/(\d+)", path)`).
PORTAL_ESCRITURA_PATCH = {
    r"/api/personas/(\d+)": ("editar_checkin", PORTAL_TIPO_C, True),
}
# Rutas de escritura que la App contesta y que el programa NO sirve, con el motivo. K0 exige tabla + esto = las rutas de la App.
PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA = {
    "/api/personas/parecidas": (
        "check-in, tipo C, «solo lee y propone» (`do_POST` de la App, línea 17087 en 594ec12). La respuesta sale de `parecidas_a`, que mira la "
        "MEMORIA DE CARAS de la App (`get_caras()`, su caché en `server.py`). El programa no tiene esa memoria ni `parecidas_a`: sin ella no hay "
        "propuestas que contestar. No escribe nada."),
    r"/api/personas/(\d+)/cara": (
        "check-in, tipo C, guardar la cara (📷; `do_POST` de la App, línea 17114 en 594ec12). Depende de la MEMORIA DE CARAS de la App en dos "
        "sitios: la línea `[CAMARA]` (`_constancia_de_camara`) recibe las propuestas que salen de `parecidas_a` sobre `get_caras()`, y "
        "`guardar_cara` de la App pone la cara también en esa memoria (`_caras_cache`). El programa no tiene ninguna de las dos. La escritura de la "
        "columna sí existe en el programa (`personas.escribir_cara`, la usa la ruta de Registro), pero la respuesta de la App no se puede dar sin "
        "la memoria."),
}


def escrituras_del_portal():
    """Todas las escrituras que el programa sirve, como `(verbo, patron, (nombre, tipo, exige_identidad))`: primero las POST de
    `PORTAL_ESCRITURA` y después las PATCH de `PORTAL_ESCRITURA_PATCH`. Las pruebas recorren ESTA lista, no una tecleada."""
    return ([("POST", patron, valor) for patron, valor in PORTAL_ESCRITURA.items()]
            + [("PATCH", patron, valor) for patron, valor in PORTAL_ESCRITURA_PATCH.items()])


def _portal_entrada(ruta, tabla=None):
    """La entrada de `tabla` (por defecto `PORTAL_LECTURA`) que casa con la ruta: `(patrón, valor, grupos)`, o `None` si ninguna casa."""
    for patron, valor in (PORTAL_LECTURA if tabla is None else tabla).items():
        m = re.fullmatch(patron, ruta)
        if m:
            return patron, valor, m.groups()
    return None


def quien_de_la_cabecera(valor):
    """El nombre de quien pide, de la cabecera X-Personas-Portal-Quien. `http.server` lee las cabeceras como latin-1; la App manda el
    nombre en UTF-8, así que se deshace esa lectura («PÃ©rez» -> «Pérez»). Si no es UTF-8 válido, queda tal cual, sin recortar más."""
    texto = str(valor or "")
    try:
        texto = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return texto.strip()


def igual_seguro(a, b):
    """Comparación de tiempo constante (copiada de `server.py` de la App, `igual_seguro`)."""
    return hmac.compare_digest(
        str(a).encode("utf-8", "replace"), str(b).encode("utf-8", "replace"))


def lucy_llave_valida(pedida, esperada):
    """¿La cabecera trae la llave? Una variable vacía no acepta nada (copiada de `server.py`, `lucy_llave_valida`)."""
    if not str(esperada or "").strip():
        return False
    return igual_seguro(str(pedida or ""), str(esperada))


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _enviar(self, codigo, cuerpo):
        # La puerta única de las respuestas de error (como `send_json` de la App): si el pedido ya escribió, el error se marca.
        cuerpo = base.marcar_fallo_tras_escribir(codigo, cuerpo)
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _pedido(self):
        """El cuerpo como JSON; si no es JSON válido, `None` (la función decide, como en la App)."""
        largo = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(largo) if largo else b""
        try:
            return json.loads(crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_POST(self):
        base.estrenar_la_cuenta_de_escrituras()     # cada pedido empieza sin escrituras mandadas (como `estrenar_el_pedido` de la App)
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta in ESCRITURA_RUTAS:
            # La llave de escrituras se mira ANTES de leer el cuerpo (como `personas_escritura_post` de la App).
            if not lucy_llave_valida(self.headers.get("X-Personas-Registro-Escritura-Llave"), LLAVE_PERSONAS_ESCRITURA_REGISTRO):
                return self._enviar(401, ERROR_LLAVE)
            codigo, cuerpo = ESCRITURA_FUNCIONES[ESCRITURA_RUTAS[ruta]](personas_escrituras, self._pedido())
            return self._enviar(codigo, cuerpo)
        entrada = _portal_entrada(ruta, PORTAL_ESCRITURA)
        if entrada is not None:
            patron, (nombre, tipo, exige_identidad), grupos = entrada
            return self._portal_escritura(ruta, nombre, tipo, exige_identidad, grupos)
        if ruta not in LECTURA_POST:
            return self._enviar(404, {"error": "ruta no existe"})
        nombre = LECTURA_POST[ruta]
        if nombre in REGISTRO_NOMBRES:
            if not lucy_llave_valida(self.headers.get("X-Personas-Registro-Llave"), LLAVE_PERSONAS_REGISTRO):
                return self._enviar(401, ERROR_LLAVE)
        elif not lucy_llave_valida(self.headers.get("X-Personas-Lectura-Llave"), LLAVE_PERSONAS_LECTURA):
            return self._enviar(401, ERROR_LLAVE)
        codigo, cuerpo = FUNCIONES[nombre](base, self._pedido())
        return self._enviar(codigo, cuerpo)

    def do_PATCH(self):
        base.estrenar_la_cuenta_de_escrituras()
        ruta = urllib.parse.urlsplit(self.path).path
        entrada = _portal_entrada(ruta, PORTAL_ESCRITURA_PATCH)
        if entrada is None:
            return self._enviar(404, {"error": "ruta no existe"})
        patron, (nombre, tipo, exige_identidad), grupos = entrada
        return self._portal_escritura(ruta, nombre, tipo, exige_identidad, grupos)

    def _portal_escritura(self, ruta, nombre, tipo, exige_identidad, grupos):
        """Una escritura del portal. Mismo orden que las lecturas: la llave se mira ANTES de leer el cuerpo y antes de NocoDB; con la
        llave bien, la identidad debe venir (quien no vacío, tipo igual al de la ruta). Solo entonces se lee el cuerpo y se escribe.
        `quien` sale SIEMPRE de la cabecera: el `quien` del cuerpo no se mira (`personas_portal_escritura.responder`)."""
        if not lucy_llave_valida(self.headers.get("X-Personas-Portal-Llave"), LLAVE_PERSONAS_PORTAL):
            return self._enviar(401, ERROR_LLAVE)
        quien = quien_de_la_cabecera(self.headers.get("X-Personas-Portal-Quien"))
        if exige_identidad:
            if not quien or (self.headers.get("X-Personas-Portal-Tipo") or "").strip() != tipo:
                return self._enviar(400, ERROR_IDENTIDAD)
        largo = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(largo) if largo else b""
        codigo, cuerpo = personas_portal_escritura.responder(nombre, ruta, grupos, crudo, quien)
        return self._enviar(codigo, cuerpo)

    def _portal_lectura(self, nombre, tipo, exige_identidad, grupos, consulta):
        """Una lectura del portal. La llave se mira ANTES que la identidad y que NocoDB. Con la llave bien, la identidad debe venir
        (quien no vacío y tipo igual al de la ruta). Después, `personas_portal_lectura.responder` (con los errores de la App)."""
        if not lucy_llave_valida(self.headers.get("X-Personas-Portal-Llave"), LLAVE_PERSONAS_PORTAL):
            return self._enviar(401, ERROR_LLAVE)
        if exige_identidad:
            quien = quien_de_la_cabecera(self.headers.get("X-Personas-Portal-Quien"))
            if not quien or (self.headers.get("X-Personas-Portal-Tipo") or "").strip() != tipo:
                return self._enviar(400, ERROR_IDENTIDAD)
        codigo, cuerpo = personas_portal_lectura.responder(nombre, grupos, consulta)
        return self._enviar(codigo, cuerpo)

    def do_GET(self):
        base.estrenar_la_cuenta_de_escrituras()
        url = urllib.parse.urlsplit(self.path)
        ruta = url.path
        # La consulta se lee como la App (`Handler.parse`): `dict(parse_qsl(...))`, sin los valores vacíos.
        consulta = dict(urllib.parse.parse_qsl(url.query))
        entrada = _portal_entrada(ruta)
        if entrada is not None:
            patron, (nombre, tipo, exige_identidad), grupos = entrada
            return self._portal_lectura(nombre, tipo, exige_identidad, grupos, consulta)
        if ruta != CONFIG_RUTA:
            return self._enviar(404, {"error": "ruta no existe"})
        if not lucy_llave_valida(self.headers.get("X-Personas-Lectura-Llave"), LLAVE_PERSONAS_LECTURA):
            return self._enviar(401, ERROR_LLAVE)
        codigo, cuerpo = personas_lectura.config(base)
        return self._enviar(codigo, cuerpo)


def arrancar(host=None, puerto=None):
    host = host or os.environ.get("HOST", "0.0.0.0")
    puerto = int(puerto if puerto is not None else os.environ.get("PORT", "3000"))
    return ThreadingHTTPServer((host, puerto), Manejador)


if __name__ == "__main__":
    arrancar().serve_forever()
