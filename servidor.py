# -*- coding: utf-8 -*-
"""EL PROGRAMA DE PERSONAS: el servidor de sus rutas de LECTURA (paso 5 de `disenos/personas-programa-aparte/DISENO.md`).

Rutas, con las mismas llaves y las mismas respuestas que la App de registro en `0b48b5d` (`PERSONAS_LECTURA_POST` y
`personas_lectura_config` de su `server.py`):
  POST /api/servicio/personas/identidad, /fichas, /pagina, /anotaciones   cabecera X-Personas-Lectura-Llave  (PERSONAS_LECTURA_LLAVE)
  POST /api/servicio/personas/credito, /buscar, /bandeja, /creditos-vivos cabecera X-Personas-Registro-Llave (PERSONAS_REGISTRO_LLAVE)
  GET  /api/servicio/personas/config                                     cabecera X-Personas-Lectura-Llave

🔴 Cada ruta valida SU llave ANTES de leer el cuerpo. Sin la llave de su grupo, con otra, o con la variable vacía: 401 y no se
lee nada. Ninguna ruta de estas escribe.

NO PORTADO TODAVÍA (declarado en `el-programa-personas.md`): las escrituras de Registro (`/cara`, `/nueva`, `/editar`, con su llave
`PERSONAS_REGISTRO_ESCRITURA_LLAVE`). Llaman a `crear_persona`, `editar_persona` y `guardar_cara`, que siguen en la App.
Y ninguna de las rutas de la tabla 1.2 que no están aquí (portal, proveedores, Google, cuadro de la entrada).

Arranque: `python3 servidor.py`. Variables (solo sus nombres): PORT (3000), HOST (0.0.0.0), NOCODB_BASE, NOCODB_TOKEN,
PERSONAS_LECTURA_LLAVE, PERSONAS_REGISTRO_LLAVE, NOCODB_T_*.
"""
import hmac
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import base
import personas_lectura
import personas_servicio_rutas

LLAVE_PERSONAS_LECTURA = os.environ.get("PERSONAS_LECTURA_LLAVE", "").strip()
LLAVE_PERSONAS_REGISTRO = os.environ.get("PERSONAS_REGISTRO_LLAVE", "").strip()

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
        ruta = urllib.parse.urlsplit(self.path).path
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

    def do_GET(self):
        ruta = urllib.parse.urlsplit(self.path).path
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
