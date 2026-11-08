# -*- coding: utf-8 -*-
"""El candado de «envío hecho» del programa (`una_vez` y `escribir_una_vez` de `personas_portal_escritura.py`), comparable con el
de la App de registro (`594ec12`, `server.py` líneas 2172-2225 y `Handler.una_vez`). Lo usan el generador de la foto
(`tools/generar_portal_escrituras_de_la_app.py`, que guarda la forma de la App) y `test_portal_escrituras.py` (que compara la del
programa con esa foto y busca todos los usos de `una_vez` en el programa).

`normalizar_funcion` quita el docstring, quita `self` si es un método, renombra parámetros (`path` -> `ruta`, `body` -> `cuerpo` para
la App) y devuelve el texto de `ast.unparse`. Así una diferencia de forma o de texto de código se ve, y un comentario o un docstring no.
"""
import ast

NOMBRES = ("una_vez", "escribir_una_vez")
FUNCIONES = ("llave_de_envio", "escribir_una_vez", "una_vez")
CONSTANTES = ("UNA_VEZ_VIDA_S", "UNA_VEZ_MAX", "_UNA_VEZ", "_UNA_VEZ_LOCK")


class _Renombra(ast.NodeTransformer):
    def __init__(self, mapa):
        self.mapa = mapa

    def visit_Name(self, nodo):
        if nodo.id in self.mapa:
            nodo.id = self.mapa[nodo.id]
        return nodo

    def visit_arg(self, nodo):
        if nodo.arg in self.mapa:
            nodo.arg = self.mapa[nodo.arg]
        return self.generic_visit(nodo)


def normalizar_funcion(nodo, renombres=None, quitar_self=False):
    f = ast.parse(ast.unparse(nodo)).body[0]
    if f.body and isinstance(f.body[0], ast.Expr) and isinstance(getattr(f.body[0], "value", None), ast.Constant) \
            and isinstance(f.body[0].value.value, str):
        f.body = f.body[1:] or [ast.Pass()]
    if quitar_self:
        f.args.args = f.args.args[1:]
    return ast.unparse(_Renombra(renombres or {}).visit(f))


def candado_del_modulo(arbol):
    """La forma del candado de un módulo de Python (el programa): funciones normalizadas y constantes."""
    funciones, constantes = {}, {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name in FUNCIONES:
            funciones[nodo.name] = normalizar_funcion(nodo)
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name) \
                and nodo.targets[0].id in CONSTANTES:
            constantes[nodo.targets[0].id] = ast.unparse(nodo.value)
    return {"funciones": funciones, "constantes": constantes}


def candado_de_la_app(arbol):
    """La forma del candado de la App (`server.py`): las funciones de módulo y `Handler.una_vez` (sin `self`, con sus parámetros
    renombrados a los del programa)."""
    base = candado_del_modulo(arbol)
    clase = [n for n in arbol.body if isinstance(n, ast.ClassDef) and n.name == "Handler"]
    metodo = [n for n in clase[0].body if isinstance(n, ast.FunctionDef) and n.name == "una_vez"]
    base["funciones"]["una_vez"] = normalizar_funcion(metodo[0], {"path": "ruta", "body": "cuerpo"}, quitar_self=True)
    return base


def _es_rama_de_accion(nodo):
    return isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Compare) and isinstance(nodo.test.left, ast.Name) \
        and nodo.test.left.id == "nombre" and isinstance(nodo.test.ops[0], ast.Eq)


def usos_y_sitios(raiz):
    """Recorre TODOS los `.py` del programa (fuera de `tests/`, `tools/` y de las carpetas que empiezan por punto) y busca cada
    uso de `una_vez` o `escribir_una_vez`: nombre, atributo, alias o import, o una definición. Lo permitido es SOLO:
      - la definición de `una_vez` y de `escribir_una_vez` en `personas_portal_escritura.py`, y la llamada a `escribir_una_vez`
        dentro de `una_vez`;
      - una llamada directa `una_vez(...)` dentro de la rama `if nombre == "<acción>"` de `_ejecutar` (un sitio).
    Devuelve `(violaciones, sitios)`: violaciones = [(archivo, línea, forma)], sitios = [(ámbito, acción, archivo, línea)]."""
    violaciones, sitios = [], []
    for ruta in sorted(raiz.rglob("*.py")):
        partes = ruta.relative_to(raiz).parts
        if partes[0] in ("tests", "tools") or any(p.startswith(".") for p in partes):
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        permitidos = set()
        if ruta.name == "personas_portal_escritura.py":
            for nodo in arbol.body:
                if isinstance(nodo, ast.FunctionDef) and nodo.name == "escribir_una_vez":
                    permitidos.add(id(nodo))
                if isinstance(nodo, ast.FunctionDef) and nodo.name == "una_vez":
                    permitidos.add(id(nodo))
                    for x in ast.walk(nodo):
                        if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "escribir_una_vez":
                            permitidos.add(id(x.func))
            ejecutar = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "_ejecutar"]
            for rama in ([x for x in ast.walk(ejecutar[0]) if _es_rama_de_accion(x)] if ejecutar else []):
                accion = rama.test.comparators[0].value
                for x in ast.walk(rama):
                    if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "una_vez" and x.args \
                            and isinstance(x.args[0], ast.Constant):
                        permitidos.add(id(x.func))
                        sitios.append((x.args[0].value, accion, str(ruta.relative_to(raiz)), x.lineno))
        for x in ast.walk(arbol):
            forma = None
            if isinstance(x, ast.Name) and x.id in NOMBRES:
                forma = "nombre"
            elif isinstance(x, ast.Attribute) and x.attr in NOMBRES:
                forma = "atributo"
            elif isinstance(x, ast.alias) and (x.name in NOMBRES or x.asname in NOMBRES):
                forma = "import"
            elif isinstance(x, ast.FunctionDef) and x.name in NOMBRES:
                forma = "definición"
            if forma and id(x) not in permitidos:
                violaciones.append((str(ruta.relative_to(raiz)), getattr(x, "lineno", 0), forma))
    return violaciones, sitios
