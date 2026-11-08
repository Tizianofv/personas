# -*- coding: utf-8 -*-
"""Saca la foto de las lecturas del portal que el programa contesta (`contrato/portal_lectura.json` y su `contrato/SHA256_portal`),
desde la App de registro.

Uso:  python3 -B tools/generar_portal_de_la_app.py <carpeta de una copia `git archive` de la App de registro>

Dos cosas salen de la App:
  1. `rutas_de_la_app`: las rutas GET del portal que atiende `Handler.portal_personas_get`. Se leen con AST del `server.py` de la
     App (las comparaciones `path == X` y las llamadas `re.fullmatch(X, path)`), resolviendo las constantes de `server.py` y de
     `personas.py`. Son las rutas que la App CONTESTA; la prueba CP3 las compara con la tabla del programa.
  2. `pedidos`: las respuestas de la App para los pedidos de `RUTAS`. Cada pedido corre en un proceso aparte: se importa el `server`
     de la App, se pasa la URL por su `Handler.parse` (el mismo que usa la App) y se llama a `Handler.portal_personas_get` con un
     objeto que solo guarda lo que la App mandaría con `send_json`. Eso ejercita el enrutado y las funciones REALES de la App.
     Lo que NO ejercita: la puerta de sesión de `portal_personas` (401 y 403). Esa no se copia, y el programa no la tiene.

Los datos de NocoDB salen del doble de `tests/doble_nocodb.py`, el mismo que usan las pruebas. Si el doble recibe un pedido que no
conoce, o un pedido que no es GET, la foto NO se guarda. Si algún pedido no es 200, tampoco (la foto es la referencia de 200).
"""
import ast
import hashlib
import json
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
import doble_nocodb as doble_mod  # noqa: E402

# (nombre, ruta, consulta). La consulta va cruda, como en la URL; la App la lee con su `parse`.
RUTAS = [
    ("portal_nueva", "/api/portal-personas/nueva", ""),
    ("portal_borradas", "/api/portal-personas/borradas", ""),
    ("portal_lista", "/api/portal-personas", "orden=asc&col=nombre&desde=0&limite=10"),
    ("portal_ficha", "/api/portal-personas/1", ""),
    ("portal_por_resolver", "/api/portal-personas/por-resolver", ""),
    ("portal_unir_revisar", "/api/portal-personas/1/unir/revisar", "otra=2"),
]

# La App, sin `main()`: importa su `server` (que no arranca hilos), pasa la URL por su `parse` y contesta a un objeto de prueba.
DRIVER = (
    "import json, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "class Pedido:\n"
    "    path = sys.argv[1]\n"
    "    def estrenar_el_pedido(self):\n"
    "        pass\n"   # `parse` la llama para borrar el estado del pedido anterior; este proceso nace con el estado vacío.
    "class Recogida:\n"
    "    enviado = None\n"
    "    def send_json(self, obj, status=200):\n"
    "        self.enviado = (status, obj)\n"
    "ruta, q = server.Handler.parse(Pedido())\n"
    "r = Recogida()\n"
    "server.Handler.portal_personas_get(r, ruta, q)\n"
    "codigo, cuerpo = r.enviado\n"
    "sys.stdout.write('\\n' + json.dumps({'status': codigo, 'respuesta': cuerpo}, ensure_ascii=False) + '\\n')\n"
)


def _valor(modulo, nodo, constantes):
    """El valor de texto de una expresión de constantes (`X + "/y"`, `personas.X`, un nombre de módulo). Lo que no se sabe leer, levanta."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        return _valor(modulo, nodo.left, constantes) + _valor(modulo, nodo.right, constantes)
    if isinstance(nodo, ast.Name):
        return _valor(modulo, constantes[modulo][nodo.id], constantes)
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name) and nodo.value.id == "personas":
        return _valor("personas", constantes["personas"][nodo.attr], constantes)
    raise SystemExit("no se puede leer una constante de la App: %s" % ast.dump(nodo)[:120])


def rutas_de_la_app(copia):
    """Las rutas GET de `Handler.portal_personas_get`, leídas con AST: `[{"patron", "exacta"}]`, sin repetir."""
    arboles = {nombre: ast.parse((copia / nombre).read_text(encoding="utf-8")) for nombre in ("server.py", "personas.py")}
    constantes = {"server": {}, "personas": {}}
    for modulo, arbol in (("server", arboles["server.py"]), ("personas", arboles["personas.py"])):
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
                constantes[modulo][nodo.targets[0].id] = nodo.value
    clase = [n for n in arboles["server.py"].body if isinstance(n, ast.ClassDef) and n.name == "Handler"]
    if len(clase) != 1:
        raise SystemExit("no se encontró la clase Handler en server.py de la App")
    metodos = [n for n in clase[0].body if isinstance(n, ast.FunctionDef) and n.name == "portal_personas_get"]
    if len(metodos) != 1:
        raise SystemExit("no se encontró portal_personas_get en la App")
    rutas = {}
    for nodo in ast.walk(metodos[0]):
        if isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Name) and nodo.left.id == "path" \
                and len(nodo.ops) == 1 and isinstance(nodo.ops[0], ast.Eq):
            rutas[_valor("server", nodo.comparators[0], constantes)] = False
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "fullmatch" \
                and len(nodo.args) == 2 and isinstance(nodo.args[1], ast.Name) and nodo.args[1].id == "path":
            rutas[_valor("server", nodo.args[0], constantes)] = True
    return [{"patron": p, "exacta": not regex} for p, regex in sorted(rutas.items())]


def pedir_a_la_app(copia, ruta, consulta, url_doble):
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba",
        "NOCODB_T_PERSONAS_QUITADAS": doble_mod.T_QUITADAS,
        "NOCODB_T_BANDEJA_PERSONAS": doble_mod.T_BANDEJA,
        "NOCODB_T_PERSONAS_ANOTACIONES": doble_mod.TABLA_ANOTACIONES,
    }
    url = ruta + ("?" + consulta if consulta else "")
    salida = subprocess.run([sys.executable, "-I", "-B", "-c", DRIVER, url], cwd=str(copia), env=entorno,
                            capture_output=True, text=True, timeout=300)
    if salida.returncode != 0:
        raise SystemExit("la App no contestó «%s»: %s" % (url, salida.stderr[-800:]))
    return json.loads(salida.stdout.strip().splitlines()[-1])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_portal_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App con server.py y personas.py")
    rutas = rutas_de_la_app(copia)
    pedidos = []
    for nombre, ruta, consulta in RUTAS:
        doble = doble_mod.Doble()
        url = doble.arrancar()
        try:
            resultado = pedir_a_la_app(copia, ruta, consulta, url)
        finally:
            doble.parar()
        if doble.errores or doble.no_get:
            raise SystemExit("el doble recibió algo que no conoce en «%s»: %s %s" % (ruta, doble.errores, doble.no_get))
        if resultado["status"] != 200:
            raise SystemExit("la App no contestó 200 a «%s»: %s" % (ruta, resultado["status"]))
        pedidos.append({"nombre": nombre, "ruta": ruta, "consulta": consulta, "status": resultado["status"],
                        "lecturas_a_nocodb": doble.lecturas, "respuesta": resultado["respuesta"]})
    foto = {
        "version": 2,
        "fuente": "App de registro, commit 594ec12: server.Handler.parse y portal_personas_get (las rutas GET del portal, leídas "
                  "con AST: rutas_de_la_app), con las funciones de personas.py de la App. Sin la puerta de sesión de portal_personas. "
                  "Datos del doble tests/doble_nocodb.py.",
        "escrituras_a_nocodb": 0,
        "rutas_de_la_app": rutas,
        "pedidos": pedidos,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato" / "portal_lectura.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato" / "SHA256_portal").write_text("%s  portal_lectura.json\n" % sha, encoding="utf-8")
    print("rutas de la App: %d" % len(rutas))
    print("pedidos: %d" % len(pedidos))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
