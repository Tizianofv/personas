# -*- coding: utf-8 -*-
"""Saca la foto de las ESCRITURAS del portal que el programa contesta (`contrato_dorado/portal_escrituras.json` y su
`contrato_dorado/SHA256_portal_escrituras`), desde la App de registro.

Uso:  python3 -B tools/generar_portal_escrituras_de_la_app.py <carpeta de una copia `git archive` de la App de registro>

Dos cosas salen de la App:
  1. `rutas_de_la_app`: las rutas POST del portal que atiende `Handler.portal_personas_post` (AST del `server.py` de la App:
     `path == X`, `path in (X, Y)`, `re.fullmatch(X, path)`). Son las rutas que la App CONTESTA; la prueba CP3 las compara con
     `servidor.PORTAL_ESCRITURA` más `servidor.PORTAL_ESCRITURA_FUERA_DEL_PROGRAMA`.
  2. `escenarios`: las respuestas de la App a los pasos de `tests/escenarios_portal_escrituras.py` (solo los de dorado). La App se
     corre en UN proceso por escenario, con su `Handler.portal_personas` (el mismo despacho que usa `do_POST`, que incluye el
     `una_vez`, el 400 por cuerpo ilegible y los 500 con sus textos) y un objeto de prueba que hace de handler: se le ponen las
     cabeceras y el cuerpo, y se le da la identidad que la App pondría (`firma_escrita` y `quien_del_cambio` devuelven el `quien`
     del paso). Lo que NO ejercita: la puerta de sesión (`veredicto().entra` y `entra_personas`, que se dan por buenos).
Los pasos van uno a uno: el driver avisa tras cada uno (`PASO …`) y este script anota los pedidos que llegaron al doble en ese
paso, así cada paso lleva lo suyo.

Si el doble recibe un pedido que no conoce, o la App no responde, la foto NO se guarda.
"""
import ast
import base64
import hashlib
import json
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ / "tools"))
import doble_escrituras  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402
import generar_portal_de_la_app as gpl  # noqa: E402  (su evaluador de constantes `_valor`, el mismo que lee las rutas GET)

# La App, un escenario por proceso. Lee los pasos por la entrada, los corre con su `Handler.portal_personas` y avisa tras cada uno.
DRIVER = (
    "import base64, io, json, os, sys, types\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "class Pedido(server.Handler):\n"
    "    def __init__(self, ruta, quien, datos):\n"
    "        self.path = ruta\n"
    "        self.headers = {'Content-Length': str(len(datos)), 'Content-Type': 'application/json'}\n"
    "        self.rfile = io.BytesIO(datos)\n"
    "        self.wfile = io.BytesIO()\n"
    "        self.close_connection = False\n"
    "        self.codigo = None\n"
    "        self._quien = quien\n"
    "    def send_response(self, codigo, mensaje=None):\n"
    "        self.codigo = codigo\n"
    "    def send_header(self, *a):\n"
    "        pass\n"
    "    def end_headers(self):\n"
    "        pass\n"
    "    def veredicto(self):\n"
    "        return types.SimpleNamespace(entra=True, es_admin=True)\n"
    "    def firma_escrita(self, tecleado=''):\n"
    "        return self._quien\n"
    "    def quien_del_cambio(self):\n"
    "        return self._quien\n"
    "for linea in sys.stdin:\n"
    "    paso = json.loads(linea)\n"
    "    p = Pedido(paso['ruta'], paso['quien'], base64.b64decode(paso['datos_b64']))\n"
    "    server.estrenar_la_cuenta_de_escrituras()\n"
    "    server.estrenar_el_historial_del_pedido(p.quien_del_cambio)\n"
    "    server.Handler.portal_personas(p, paso['ruta'], {}, 'POST')\n"
    "    cuerpo = json.loads(p.wfile.getvalue().decode('utf-8'))\n"
    "    sys.stdout.write('PASO ' + json.dumps({'status': p.codigo, 'respuesta': cuerpo}, ensure_ascii=False) + '\\n')\n"
    "    sys.stdout.flush()\n"
)


def rutas_post_de_la_app(copia):
    """Las rutas que `Handler.portal_personas_post` atiende, leídas con AST: `[{"patron", "exacta"}]`, sin repetir."""
    arboles = {nombre: ast.parse((copia / nombre).read_text(encoding="utf-8")) for nombre in ("server.py", "personas.py")}
    constantes = {"server": {}, "personas": {}}
    for modulo, arbol in (("server", arboles["server.py"]), ("personas", arboles["personas.py"])):
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
                constantes[modulo][nodo.targets[0].id] = nodo.value
    clase = [n for n in arboles["server.py"].body if isinstance(n, ast.ClassDef) and n.name == "Handler"]
    if len(clase) != 1:
        raise SystemExit("no se encontró la clase Handler en server.py de la App")
    metodos = [n for n in clase[0].body if isinstance(n, ast.FunctionDef) and n.name == "portal_personas_post"]
    if len(metodos) != 1:
        raise SystemExit("no se encontró portal_personas_post en la App")
    rutas = {}
    for nodo in ast.walk(metodos[0]):
        if isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Name) and nodo.left.id == "path" and len(nodo.ops) == 1:
            if isinstance(nodo.ops[0], ast.Eq):
                rutas[gpl._valor("server", nodo.comparators[0], constantes)] = False
            elif isinstance(nodo.ops[0], ast.In) and isinstance(nodo.comparators[0], ast.Tuple):
                for elemento in nodo.comparators[0].elts:
                    rutas[gpl._valor("server", elemento, constantes)] = False
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "fullmatch" \
                and len(nodo.args) == 2 and isinstance(nodo.args[1], ast.Name) and nodo.args[1].id == "path":
            rutas[gpl._valor("server", nodo.args[0], constantes)] = True
    return [{"patron": p, "exacta": not regex} for p, regex in sorted(rutas.items())]


def correr_escenario(copia, pasos, caidas):
    """Corre los pasos de un escenario en la App y devuelve, por paso, `{status, respuesta, pedidos}`."""
    doble = doble_escrituras.DobleEscrituras(caidas=caidas)
    url_doble = doble.arrancar()
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba",
        "NOCODB_T_PERSONAS_ANOTACIONES": esc.ENTORNO_BASE["NOCODB_T_PERSONAS_ANOTACIONES"],
        "NOCODB_T_PERSONAS_QUITADAS": esc.ENTORNO_BASE["NOCODB_T_PERSONAS_QUITADAS"],
        "NOCODB_T_BANDEJA_PERSONAS": esc.ENTORNO_BASE["NOCODB_T_BANDEJA_PERSONAS"],
    }
    entrada = "".join(json.dumps({
        "ruta": p["ruta"], "quien": p["quien"],
        "datos_b64": base64.b64encode(esc.datos_del_paso(p)).decode("ascii")}, ensure_ascii=False) + "\n" for p in pasos)
    proceso = subprocess.Popen([sys.executable, "-I", "-B", "-c", DRIVER], cwd=str(copia), env=entorno, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        proceso.stdin.write(entrada)
        proceso.stdin.close()
        resultados, antes = [], 0
        for linea in proceso.stdout:
            if not linea.startswith("PASO "):
                continue
            dato = json.loads(linea[len("PASO "):])
            # el doble es de ESTE proceso: cuando la App avisa, lo que llegó al doble en el paso ya está anotado
            resultados.append({"status": dato["status"], "respuesta": esc.normalizar(dato["respuesta"]),
                               "pedidos": esc.normalizar(doble.pedidos[antes:])})
            antes = len(doble.pedidos)
        codigo = proceso.wait(timeout=300)
        if codigo != 0 or len(resultados) != len(pasos):
            raise SystemExit("la App no contestó a todos los pasos (código %s, %d de %d): %s"
                             % (codigo, len(resultados), len(pasos), proceso.stderr.read()[-800:]))
    finally:
        if proceso.poll() is None:
            proceso.kill()
        doble.parar()
    if doble.errores:
        raise SystemExit("el doble recibió un pedido que no conoce: %s" % doble.errores)
    return resultados


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_portal_escrituras_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App con server.py y personas.py")
    escenarios_foto = []
    for escenario in esc.ESCENARIOS:
        pasos = [p for p in escenario["pasos"] if esc.es_dorado(p)]
        resultados = correr_escenario(copia, pasos, escenario.get("caidas", ()))
        escenarios_foto.append({"nombre": escenario["nombre"], "caidas": list(escenario.get("caidas", ())), "pasos": [
            dict({"ruta": p["ruta"], "quien": p["quien"]}, **({"crudo": p["crudo"]} if "crudo" in p else {"cuerpo": p["cuerpo"]}),
                 **r) for p, r in zip(pasos, resultados)]})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 594ec12: server.Handler.portal_personas_post (las rutas POST del portal, leídas con AST: "
                  "rutas_de_la_app), con su `portal_personas` (sin la puerta de sesión) y las funciones de personas.py de la App. "
                  "Datos del doble tests/doble_nocodb.py y tests/doble_escrituras.py.",
        "rutas_de_la_app": rutas_post_de_la_app(copia),
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "portal_escrituras.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_portal_escrituras").write_text("%s  portal_escrituras.json\n" % sha, encoding="utf-8")
    print("rutas POST de la App: %d" % len(foto["rutas_de_la_app"]))
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
