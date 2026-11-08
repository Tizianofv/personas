# -*- coding: utf-8 -*-
"""Saca la foto de las lecturas que el programa contesta (`contrato/portal_lectura.json` y su `contrato/SHA256_portal`), desde la App
de registro.

Uso:  python3 -B tools/generar_portal_de_la_app.py <carpeta de una copia `git archive` de la App de registro>

Tres cosas salen de la App:
  1. `rutas_de_la_app`: las rutas GET del portal (tipo «A») que atiende `Handler.portal_personas_get`. Se leen con AST del `server.py`
     de la App (las comparaciones `path == X` y las llamadas `re.fullmatch(X, path)`), resolviendo las constantes de `server.py` y de
     `personas.py`. Son las rutas que la App CONTESTA; la prueba CP3 las compara con la tabla del programa.
  2. `rutas_de_sesion_de_la_app` (parte 6, tipo «C»): las GET de `RUTAS_DE_SESION` (el buscador y las opciones de instrumento), que la App
     contesta en `Handler.do_GET` DESPUÉS de `if not self.autorizado()`. El generador comprueba con AST que cada una es una comparación
     `path == X` de `do_GET` con línea posterior a esa puerta; si falta alguna, no saca la foto.
  3. `pedidos`: las respuestas de la App para los pedidos de `RUTAS`. Cada pedido corre en un proceso aparte: se importa el `server`
     de la App, se pasa la URL por su `Handler.parse` (el mismo que usa la App) y se llama al método de la App que la atiende
     (`portal_personas_get` para el portal; `do_GET` para las de sesión) con un objeto que solo guarda lo que la App mandaría con
     `send_json`. Eso ejercita el enrutado y las funciones REALES de la App.
     Lo que NO ejercita: la puerta de sesión de `portal_personas` (401 y 403) y, para las de sesión, `autorizado()` (se da por buena) y
     las guardas de antes del despacho (`frenado`, `fuera_de_alcance`, `falta_el_conteo`). Esas no se copian, y el programa no las tiene.

Los datos de NocoDB salen del doble de `tests/doble_nocodb.py`, el mismo que usan las pruebas. Si el doble recibe un pedido que no
conoce, o un pedido que no es GET, la foto NO se guarda. Si la App contesta otro código que el ESPERADO de ese pedido, tampoco: el
esperado va en `RUTAS` (200 para casi todo; 404 y 502 para los escenarios de error y de caída de «borrar/revisar», parte 5; 500 para las
caídas de las lecturas de sesión, parte 6, porque la App contesta así en `do_GET`).

Parte 5: `borrar/revisar` pide en la App el permiso `puede_borrar_fichas`. La puerta de permiso no se copia (igual que la de sesión):
el objeto que contesta tiene `puede_borrar_fichas` = verdadero, y eso va escrito en el DRIVER.

Frontera declarada (rule 18): `RUTAS_DE_SESION` es una lista escrita a mano con las dos GET de tipo C del contrato (filas 9 y 10 de
`CONTRATO-SESION.md`). Una GET de tipo C NUEVA que la App añada no aparece sola: quien la añada la pone aquí y en la tabla del programa.
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

# Las GET de SESIÓN (tipo C, parte 6): la App las contesta en `do_GET`, bajo `autorizado()`. Son las filas 9 y 10 de `CONTRATO-SESION.md`.
RUTAS_DE_SESION = ("/api/personas", "/api/persona-instrumentos")

# (nombre, ruta, consulta, caidas, código esperado). La consulta va cruda, como en la URL; la App la lee con su `parse`. `caidas` son
# los métodos que el doble de ESE pedido contesta con 500 (la base no contesta). Un pedido con caídas va en su propio doble (lo lee la
# prueba P4); los demás comparten la forma del doble de siempre.
# Parte 5 (`borrar/revisar`): el primer pedido de cada ruta es el de ÉXITO (la prueba toma el primero de la foto para cada entrada).
# Parte 6 (tipo C): el primer pedido de cada ruta es el de ÉXITO. Con el doble, `sesion_buscar` da 2 fichas: la 3 sale por `quitada_el` y
# la 4 por `unida_a` (`personas.ficha_fuera`), así que la lista tiene dos y el orden de la foto se puede romper.
RUTAS = [
    ("portal_nueva", "/api/portal-personas/nueva", "", (), 200),
    ("portal_borradas", "/api/portal-personas/borradas", "", (), 200),
    ("portal_lista", "/api/portal-personas", "orden=asc&col=nombre&desde=0&limite=10", (), 200),
    ("portal_ficha", "/api/portal-personas/1", "", (), 200),
    ("portal_por_resolver", "/api/portal-personas/por-resolver", "", (), 200),
    ("portal_unir_revisar", "/api/portal-personas/1/unir/revisar", "otra=2", (), 200),
    ("portal_borrar_revisar", "/api/portal-personas/2/borrar/revisar", "", (), 200),
    ("portal_borrar_revisar_ficha_unida", "/api/portal-personas/4/borrar/revisar", "", (), 200),
    ("portal_borrar_revisar_quitada", "/api/portal-personas/3/borrar/revisar", "", (), 200),
    ("portal_borrar_revisar_sin_permiso", "/api/portal-personas/1/borrar/revisar", "", (), 200),
    ("portal_borrar_revisar_no_existe", "/api/portal-personas/99/borrar/revisar", "", (), 404),
    ("portal_borrar_revisar_caida", "/api/portal-personas/2/borrar/revisar", "", ("GET",), 502),
    # Parte 6, tipo C: el buscador (con q, sin q, q vacío, q de una letra sin leer, q con tilde y la caída) y las opciones de instrumento.
    ("sesion_buscar", "/api/personas", "q=Persona%20de%20prueba", (), 200),
    ("sesion_buscar_sin_q", "/api/personas", "", (), 200),
    ("sesion_buscar_q_vacia", "/api/personas", "q=", (), 200),
    ("sesion_buscar_q_corta", "/api/personas", "q=P", (), 200),
    ("sesion_buscar_con_tilde", "/api/personas", "q=P%C3%A9rsona%20de%20prueba%202", (), 200),
    ("sesion_buscar_caida", "/api/personas", "q=Persona%20de%20prueba", ("GET",), 500),
    ("sesion_instrumentos", "/api/persona-instrumentos", "", (), 200),
    ("sesion_instrumentos_caida", "/api/persona-instrumentos", "", ("GET",), 500),
]
# Las variables de entorno que el programa necesita para «revisar un borrado» (tablas de envíos y de uniones). Van en el entorno de
# AMBOS lados (la App y el programa), igual que las demás tablas de la foto: la foto y la prueba tienen la misma configuración.
ENTORNO_FOTO = {
    "NOCODB_T_MERCADEO_ENVIOS": doble_mod.T_MERCADEO_ENVIOS,
    "NOCODB_T_UNIONES_PERSONAS": doble_mod.T_UNIONES,
}

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
    "    def puede_borrar_fichas(self):\n"
    "        return True\n"   # la puerta de permiso (`puede_borrar_fichas`) no se copia: se da por buena, como la de sesión
    "    def send_json(self, obj, status=200):\n"
    "        self.enviado = (status, obj)\n"
    "ruta, q = server.Handler.parse(Pedido())\n"
    "r = Recogida()\n"
    "server.Handler.portal_personas_get(r, ruta, q)\n"
    "codigo, cuerpo = r.enviado\n"
    "sys.stdout.write('\\n' + json.dumps({'status': codigo, 'respuesta': cuerpo}, ensure_ascii=False) + '\\n')\n"
)

# La App, las rutas de SESIÓN: `do_GET` entero, con la puerta de sesión y las guardas de antes del despacho dadas por buenas (ver la
# docstring). Así el pedido recorre `do_GET` como en la App: `parse`, los `if path ==` de antes y el despacho de la ruta.
# Su error sale como lo escribe la App (`except Exception` de `do_GET`: `print` y `send_json({"error": str(e)}, 500)`); el `print`
# va antes de la última línea, que es la que lee el generador.
DRIVER_SESION = (
    "import json, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "H = server.Handler\n"
    "H.frenado = lambda self, path: False\n"
    "H.fuera_de_alcance = lambda self, path, metodo: False\n"
    "H.falta_el_conteo = lambda self, path, metodo: False\n"
    "H.autorizado = lambda self: True\n"
    "class Recogida(H):\n"
    "    enviado = None\n"
    "    def __init__(self, ruta):\n"
    "        self.path = ruta\n"
    "    def estrenar_el_pedido(self):\n"
    "        pass\n"
    "    def send_json(self, obj, status=200):\n"
    "        self.enviado = (status, obj)\n"
    "        return True\n"
    "r = Recogida(sys.argv[1])\n"
    "r.do_GET()\n"
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


def _constantes(copia):
    """Los árboles de `server.py` y `personas.py` de la App, y sus constantes de nivel de módulo (asignaciones simples)."""
    arboles = {nombre: ast.parse((copia / nombre).read_text(encoding="utf-8")) for nombre in ("server.py", "personas.py")}
    constantes = {"server": {}, "personas": {}}
    for modulo, arbol in (("server", arboles["server.py"]), ("personas", arboles["personas.py"])):
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
                constantes[modulo][nodo.targets[0].id] = nodo.value
    return arboles, constantes


def _metodo_de_handler(arbol, nombre):
    clase = [n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == "Handler"]
    if len(clase) != 1:
        raise SystemExit("no se encontró la clase Handler en server.py de la App")
    metodos = [n for n in clase[0].body if isinstance(n, ast.FunctionDef) and n.name == nombre]
    if len(metodos) != 1:
        raise SystemExit("no se encontró %s en la App" % nombre)
    return metodos[0]


def rutas_de_la_app(copia):
    """Las rutas GET del portal, leídas de `Handler.portal_personas_get` con AST: `[{"patron", "exacta"}]`, sin repetir."""
    arboles, constantes = _constantes(copia)
    rutas = {}
    for nodo in ast.walk(_metodo_de_handler(arboles["server.py"], "portal_personas_get")):
        if isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Name) and nodo.left.id == "path" \
                and len(nodo.ops) == 1 and isinstance(nodo.ops[0], ast.Eq):
            rutas[_valor("server", nodo.comparators[0], constantes)] = False
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "fullmatch" \
                and len(nodo.args) == 2 and isinstance(nodo.args[1], ast.Name) and nodo.args[1].id == "path":
            rutas[_valor("server", nodo.args[0], constantes)] = True
    return [{"patron": p, "exacta": not regex} for p, regex in sorted(rutas.items())]


def rutas_de_sesion_de_la_app(copia):
    """Las rutas de `RUTAS_DE_SESION` que `Handler.do_GET` compara con `path ==` DESPUÉS de `if not self.autorizado()`. Si alguna no
    está en esa posición, levanta: la foto no se saca."""
    arboles, constantes = _constantes(copia)
    do_get = _metodo_de_handler(arboles["server.py"], "do_GET")
    puertas = [n.lineno for n in ast.walk(do_get) if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp)
               and isinstance(n.test.op, ast.Not) and isinstance(n.test.operand, ast.Call)
               and isinstance(n.test.operand.func, ast.Attribute) and n.test.operand.func.attr == "autorizado"]
    if not puertas:
        raise SystemExit("no se encontró `if not self.autorizado()` en do_GET de la App")
    linea_puerta = min(puertas)
    vistas = {}
    for nodo in ast.walk(do_get):
        if isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Name) and nodo.left.id == "path" \
                and len(nodo.ops) == 1 and isinstance(nodo.ops[0], ast.Eq) and nodo.lineno > linea_puerta:
            try:
                valor = _valor("server", nodo.comparators[0], constantes)
            except (SystemExit, KeyError):
                continue
            if valor in RUTAS_DE_SESION:
                vistas[valor] = nodo.lineno
    faltan = sorted(set(RUTAS_DE_SESION) - set(vistas))
    if faltan:
        raise SystemExit("la App no compara estas rutas de sesión después de la puerta de do_GET: %s" % faltan)
    return [{"patron": p, "bajo_autorizado": True} for p in sorted(vistas)]


def pedir_a_la_app(copia, ruta, consulta, url_doble):
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba",
        "NOCODB_T_PERSONAS_QUITADAS": doble_mod.T_QUITADAS,
        "NOCODB_T_BANDEJA_PERSONAS": doble_mod.T_BANDEJA,
        "NOCODB_T_PERSONAS_ANOTACIONES": doble_mod.TABLA_ANOTACIONES,
        **ENTORNO_FOTO,
    }
    url = ruta + ("?" + consulta if consulta else "")
    driver = DRIVER_SESION if ruta in RUTAS_DE_SESION else DRIVER
    salida = subprocess.run([sys.executable, "-I", "-B", "-c", driver, url], cwd=str(copia), env=entorno,
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
    rutas_sesion = rutas_de_sesion_de_la_app(copia)
    pedidos = []
    for nombre, ruta, consulta, caidas, esperado in RUTAS:
        # Con la columna `instrumento` solo en el pedido de instrumentos: así los demás pedidos del portal no cambian su doble.
        doble = doble_mod.Doble(caidas=caidas, instrumentos=(ruta == "/api/persona-instrumentos"))
        url = doble.arrancar()
        try:
            resultado = pedir_a_la_app(copia, ruta, consulta, url)
        finally:
            doble.parar()
        if doble.errores or doble.no_get:
            raise SystemExit("el doble recibió algo que no conoce en «%s»: %s %s" % (ruta, doble.errores, doble.no_get))
        if resultado["status"] != esperado:
            raise SystemExit("la App no contestó %s a «%s» (%s): %s" % (esperado, ruta, nombre, resultado["status"]))
        if caidas and not doble.caidas_servidas:
            raise SystemExit("la caída de «%s» no se usó: la App no leyó NocoDB" % nombre)
        pedidos.append({"nombre": nombre, "ruta": ruta, "consulta": consulta, "status": resultado["status"],
                        "caidas": list(caidas), "lecturas_a_nocodb": doble.lecturas, "respuesta": resultado["respuesta"]})
    foto = {
        "version": 4,
        "fuente": "App de registro, commit 594ec12: server.Handler.parse y portal_personas_get (las rutas GET del portal, leídas "
                  "con AST: rutas_de_la_app), y server.Handler.do_GET para las de sesión (rutas_de_sesion_de_la_app: GET /api/personas "
                  "y GET /api/persona-instrumentos, bajo autorizado()), con las funciones de personas.py de la App. Sin la puerta de "
                  "sesión de portal_personas, ni la de permiso (`puede_borrar_fichas`), ni autorizado(), ni las guardas de antes del "
                  "despacho. Datos del doble tests/doble_nocodb.py.",
        "escrituras_a_nocodb": 0,
        "rutas_de_la_app": rutas,
        "rutas_de_sesion_de_la_app": rutas_sesion,
        "pedidos": pedidos,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato" / "portal_lectura.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato" / "SHA256_portal").write_text("%s  portal_lectura.json\n" % sha, encoding="utf-8")
    print("rutas de la App (portal): %d" % len(rutas))
    print("rutas de la App (sesión): %d" % len(rutas_sesion))
    print("pedidos: %d" % len(pedidos))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
