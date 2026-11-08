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

LECTURAS DEL PORTAL (paso 5c, partes 1 y 2): seis rutas GET, en la tabla `PORTAL_LECTURA` de abajo (lista, ficha, nueva, borradas,
por-resolver y unir/revisar). Cabecera X-Personas-Portal-Llave (PERSONAS_PORTAL_LLAVE), más la identidad que pone la App:
X-Personas-Portal-Quien (quien pide, no vacío) y X-Personas-Portal-Tipo (= «A»).
🔴 La llave del portal se mira PRIMERO: sin ella, con otra (la de Mercadeo y la de Registro incluidas) o con la variable vacía: 401,
y no se lee NocoDB. Con la llave bien pero sin identidad, o con un tipo que no es el de la ruta: 400, y no se lee NocoDB. La cabecera
de identidad que venga del navegador no decide nada si la llave no es la del portal. La App mira la puerta de sesión antes de
reenviar; este programa no la ve. Las respuestas: `personas_portal_lectura.py` (copia de la App, `594ec12`), con la foto de
`contrato/portal_lectura.json`. Las dos rutas de la App que NO se portan están en `PORTAL_FUERA_DEL_PROGRAMA`, con su motivo.

ESCRITURAS DEL PORTAL (paso 5c, parte 3): cinco POST en la tabla `PORTAL_ESCRITURA` (crear, editar, permiso, resolver y reabrir).
Misma cabecera de llave (X-Personas-Portal-Llave) y la misma identidad que las lecturas, más el `quien` que pone la App en
X-Personas-Portal-Quien: es el que queda escrito, y el `quien` del cuerpo no se lee. La llave se mira antes que el cuerpo. Las
respuestas: `personas_portal_escritura.py` (copia de `Handler.portal_personas_post` de la App, `594ec12`, sin su puerta de sesión).
Lo que la App atiende por POST y el programa NO porta (unir, unir/continuar, unir/deshacer, borrar, devolver) está en
`PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`, con su motivo; el programa lo contesta 404 sin tocar NocoDB.

NO PORTADO (declarado en `el-programa-personas.md`, «Lo que falta»): la búsqueda GET, las instrumentos, Google, la puerta de Natalia
y las rutas POST de unión y borrado de arriba.

Arranque: `python3 servidor.py`. Variables (solo sus nombres): PORT (3000), HOST (0.0.0.0), NOCODB_BASE, NOCODB_TOKEN,
PERSONAS_LECTURA_LLAVE, PERSONAS_REGISTRO_LLAVE, PERSONAS_REGISTRO_ESCRITURA_LLAVE, PERSONAS_PORTAL_LLAVE, NOCODB_T_*.
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

# TABLA ÚNICA de las lecturas del portal: patrón de ruta (el mismo texto que la App usa en `portal_personas_get`) -> (nombre de la
# lectura en `personas_portal_lectura`, tipo que la App pone en la identidad, ¿exige identidad?). Las claves salen de la App: las
# compara CP3 con `rutas_de_la_app` de la foto. El tipo «A» es el de la tabla 1.2 de `CONTRATO-SESION.md` (puerta `entra_personas`).
PORTAL_TIPO_A = "A"
PORTAL_LECTURA = {
    "/api/portal-personas": ("lista", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})": ("ficha", PORTAL_TIPO_A, True),
    "/api/portal-personas/nueva": ("nueva", PORTAL_TIPO_A, True),
    "/api/portal-personas/borradas": ("borradas", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver": ("por_resolver", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/unir/revisar": ("unir_revisar", PORTAL_TIPO_A, True),
}
# Rutas que la App contesta y que el programa NO sirve, con el motivo. CP3 exige que tabla + esto = las rutas de la App.
PORTAL_FUERA_DEL_PROGRAMA = {
    "/api/portal-personas/entrada/cuadro": (
        "cuadro de la entrada: lee la bandeja de la entrada y cuenta con el cliente de Personas de la App (`personas_cliente`, que "
        "llama al programa por red) y con funciones de `server.py` de la App (`cuadro_de_la_entrada`). El programa no tiene ni lo "
        "uno ni lo otro (grep: 0 coincidencias en `personas.py`, `base.py` y `servidor.py`)."),
    r"/api/portal-personas/(\d{1,9})/borrar/revisar": (
        "pide el permiso de borrar fichas de la sesión («puede_borrar_fichas», `server.py` de la App, `Handler.puede_borrar_fichas`): "
        "el programa no ve sesiones ni permisos por persona."),
}


# ESCRITURAS del portal (paso 5c, parte 3): TABLA ÚNICA de las cinco POST. Mismo formato que `PORTAL_LECTURA`. Lo que la App
# atiende por POST y NO se porta está en `PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`, con su motivo. K0 de `tests/test_portal_escrituras.py` las
# compara con las rutas POST de `Handler.portal_personas_post` de la App (AST).
PORTAL_ESCRITURA = {
    "/api/portal-personas": ("crear", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/editar": ("editar", PORTAL_TIPO_A, True),
    r"/api/portal-personas/(\d{1,9})/permiso": ("permiso", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver/resolver": ("resolver", PORTAL_TIPO_A, True),
    "/api/portal-personas/por-resolver/reabrir": ("reabrir", PORTAL_TIPO_A, True),
}
PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA = {
    r"/api/portal-personas/(\d{1,9})/unir": (
        "unir fichas: la App la contesta por POST, pero esta parte del paso 5c no la porta (encargo de la sala, sesion-3). Pendiente."),
    r"/api/portal-personas/(\d{1,9})/unir/continuar": (
        "continuar una unión: igual que `unir`, pendiente en el paso 5c (no es de esta parte)."),
    r"/api/portal-personas/(\d{1,9})/unir/deshacer": (
        "deshacer una unión: igual que `unir`, pendiente en el paso 5c (no es de esta parte)."),
    r"/api/portal-personas/(\d{1,9})/borrar": (
        "borrar una ficha: pide el permiso de borrar fichas de la sesión («puede_borrar_fichas», `server.py` de la App): el programa "
        "no ve sesiones ni permisos por persona."),
    r"/api/portal-personas/(\d{1,9})/devolver": (
        "devolver una ficha guardada aparte: pide el mismo permiso que `borrar` (`puede_borrar_fichas`): el programa no lo ve."),
}


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
