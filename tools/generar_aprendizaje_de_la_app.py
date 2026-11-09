# -*- coding: utf-8 -*-
"""Saca la foto de la ficha del Aprendizaje DE LA APP: `contrato_dorado/aprendizaje.json` y `contrato_dorado/SHA256_aprendizaje`.

Uso:  python3 -B tools/generar_aprendizaje_de_la_app.py <carpeta de una copia `git archive feb87a5` de la App de registro>

Salen de la App, con los pedidos de `tests/escenarios_aprendizaje.py` (solo los dorados):
  1. `ruta_de_la_app`: el literal de la expresión de la ruta `/api/aprendizaje/fichas/<id>/editar` en `do_POST` de la App, leído con
     AST (`re.fullmatch(<literal>, path)`). La prueba lo compara con la tabla `servidor.APRENDIZAJE_ESCRITURA` del programa.
  2. `escenarios`: lo que contesta `server.Handler.do_POST` de la App a cada paso, con los pedidos que llegaron al doble en ese paso.

La App se corre en UN proceso por escenario, con su servidor HTTP (`server.Handler` con tres cambios de prueba, dichos abajo) y el doble
de `tests/doble_escrituras.py`. Lo que el driver da por bueno, y por eso NO sale en la foto:
  · `entra_aprendizaje()` = True (la sesión del equipo con permiso de Aprendizaje: la mira la App antes de reenviar, no el programa).
  · `firma_escrita()` = la cabecera `X-Personas-Portal-Quien`, en UTF-8 (lo que la App pondría como firma de quien escribe).
  · las guardas de `do_POST` (cuerpo, freno, alcance, conteo) y la puerta de programas: se dan por buenas, como en la foto del portal.
El día de hoy se fija igual que en el programa (`tests/reloj.py`).

Si el doble recibe un pedido que no conoce, o la App no contesta, la foto NO se guarda.
"""
import ast
import hashlib
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
import escenarios_aprendizaje as escenarios  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`ejecutar`, `normalizar`: los mismos que usa la prueba del programa)
import reloj  # noqa: E402

# El servidor de la App con sus stubs de prueba. Sin `main()`: lanzaría hilos que tocan NocoDB al arrancar.
DRIVER = (
    "import http.server, os, sys, types\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "import personas\n"
    "sys.path.insert(0, '@TESTS@')\n"
    "import reloj\n"
    "reloj.fijar('@DIA@', server, personas)\n"
    "server.puerta = types.SimpleNamespace(buscar=lambda *a, **k: None)\n"
    "class Pedido(server.Handler):\n"
    "    def veredicto(self):\n"
    "        return types.SimpleNamespace(entra=True, es_admin=True)\n"
    "    def entra_aprendizaje(self):\n"
    "        return True\n"
    "    def firma_escrita(self, tecleado=''):\n"
    "        return (self.headers.get('X-Personas-Portal-Quien') or '').encode('latin-1').decode('utf-8')\n"
    "    def cuerpo_rechazado(self, path):\n"
    "        return False\n"
    "    def frenado(self, path):\n"
    "        return False\n"
    "    def fuera_de_alcance(self, path, metodo):\n"
    "        return False\n"
    "    def falta_el_conteo(self, path, metodo):\n"
    "        return False\n"
    "srv = http.server.ThreadingHTTPServer(('127.0.0.1', int(os.environ['PORT'])), Pedido)\n"
    "sys.stdout.write('listo\\n'); sys.stdout.flush()\n"
    "srv.serve_forever()\n"
)
DRIVER = DRIVER.replace("@DIA@", reloj.DIA_FIJO).replace("@TESTS@", str(RAIZ / "tests"))


def ruta_de_la_app(copia):
    """El literal de la expresión de la ruta de aprendizaje en `do_POST` de la App (AST: la llamada `re.fullmatch(<literal>, path)`
    cuyo literal tiene la ruta `/api/aprendizaje/fichas/` y `/editar`)."""
    arbol = ast.parse((copia / "server.py").read_text(encoding="utf-8"))
    hallados = []
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "fullmatch"
                and nodo.args and isinstance(nodo.args[0], ast.Constant) and isinstance(nodo.args[0].value, str)):
            literal = nodo.args[0].value
            if literal.startswith("/api/aprendizaje/fichas/") and literal.endswith("/editar"):
                hallados.append(literal)
    if len(hallados) != 1:
        raise SystemExit("la App debe tener UNA ruta de aprendizaje `/editar` en `re.fullmatch`; hay %d" % len(hallados))
    return hallados[0]


def exito_de_la_app(copia):
    """El predicado `exito` de la App para `una_vez("ficha-editar", ...)` (AST de `server.py`, el texto de la expresión)."""
    arbol = ast.parse((copia / "server.py").read_text(encoding="utf-8"))
    hallados = []
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "una_vez"
                and nodo.args and isinstance(nodo.args[0], ast.Constant) and nodo.args[0].value == "ficha-editar"):
            hallados += [ast.unparse(kw.value.body) for kw in nodo.keywords if kw.arg == "exito"]
    if len(hallados) != 1:
        raise SystemExit("la App debe tener UN `una_vez(\"ficha-editar\", ...)` con `exito`; hay %d" % len(hallados))
    return hallados[0]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_aprendizaje_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App de registro")
    ruta_app = ruta_de_la_app(copia)
    exito_app = exito_de_la_app(copia)
    comando = [sys.executable, "-I", "-B", "-c", DRIVER]
    escenarios_foto = []
    for escenario in escenarios.ESCENARIOS:
        pasos, errores = esc.ejecutar(escenario, comando, cwd=str(copia))
        if errores:
            raise SystemExit("el doble recibió un pedido que no conoce en «%s»: %s" % (escenario["nombre"], errores))
        escenarios_foto.append({"nombre": escenario["nombre"], "pasos": [esc.normalizar(p) for p in pasos]})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit feb87a5: server.py (Handler.do_POST, ruta /api/aprendizaje/fichas/<id>/editar) y personas.py "
                  "(editar_ficha_cliente, _guardar_edicion_de_persona)",
        "ruta_de_la_app": ruta_app,
        "exito_de_la_app": {"ficha-editar": exito_app},
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "aprendizaje.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_aprendizaje").write_text("%s  aprendizaje.json\n" % sha, encoding="utf-8")
    print("ruta de la App: %s" % ruta_app)
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
