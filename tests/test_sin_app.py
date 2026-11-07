# -*- coding: utf-8 -*-
"""La guarda de los nombres: ningún `.py` del repo NOMBRA el módulo `server` en un import ni usa el nombre `S`.

Lo que ve (sobre el AST de cada archivo): `import server`, `from server import …`, `from <lo que sea> import server`
(p. ej. `from . import server`) y `from … import algo as server`, `__import__("server")` y `import_module("server")` con el
texto literal `server`; cualquier nombre `S`, y cualquier `S.<algo>`. Es estricta: cuenta aunque `S` sea un nombre local.
La lista de archivos sale del disco (todo `.py` del repo, menos `.git`), no de una lista tecleada.

FRONTERA (declarada, no vigilada): un módulo cargado por ruta de archivo (`importlib.util.spec_from_file_location`,
`runpy`), un `open` o un `subprocess` que ejecute `server.py` de la App, o un import con nombre calculado. Esta prueba no
dice que el repo no toque la App: dice que ningún import ni nombre `S` lo nombra.
"""
import ast
import os
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MODULO_PROHIBIDO = "server"
NOMBRE_PROHIBIDO = "S"


def _violaciones_de_texto(texto, nombre):
    """Lista de las violaciones que tiene el código `texto` (cada una con su línea)."""
    arbol = ast.parse(texto, filename=nombre)
    malos = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                if alias.name.split(".")[0] == MODULO_PROHIBIDO:
                    malos.append("import %s (línea %d)" % (alias.name, nodo.lineno))
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.module and nodo.module.split(".")[0] == MODULO_PROHIBIDO:
                malos.append("from %s import … (línea %d)" % (nodo.module, nodo.lineno))
            # `from <lo que sea> import server` (p. ej. `from . import server`), o `… as server`: cualquier módulo
            for alias in nodo.names:
                if MODULO_PROHIBIDO in (alias.name, alias.asname):
                    malos.append("from %s import %s (línea %d)" % ("." * nodo.level + (nodo.module or ""), alias.name, nodo.lineno))
        elif isinstance(nodo, ast.Call):
            f = nodo.func
            llama = (isinstance(f, ast.Name) and f.id == "__import__") or \
                    (isinstance(f, ast.Attribute) and f.attr == "import_module")
            if llama and nodo.args and isinstance(nodo.args[0], ast.Constant) and nodo.args[0].value == MODULO_PROHIBIDO:
                malos.append("importación dinámica de server (línea %d)" % nodo.lineno)
        elif isinstance(nodo, ast.Name) and nodo.id == NOMBRE_PROHIBIDO:
            malos.append("nombre S (línea %d)" % nodo.lineno)
        elif isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name) and nodo.value.id == NOMBRE_PROHIBIDO:
            malos.append("S.%s (línea %d)" % (nodo.attr, nodo.lineno))
    return malos


def _archivos_py():
    for carpeta, subcarpetas, archivos in os.walk(str(RAIZ)):
        subcarpetas[:] = [d for d in subcarpetas if d != ".git"]
        for nombre in archivos:
            if nombre.endswith(".py"):
                yield Path(carpeta) / nombre


class LaGuardaVeLoQueDebe(unittest.TestCase):
    """La guarda se prueba a sí misma con código sintético: si no ve estos casos, la prueba de abajo no vale nada."""

    def test_ve_import_de_server(self):
        self.assertTrue(_violaciones_de_texto("import server\n", "x.py"))

    def test_ve_from_server(self):
        self.assertTrue(_violaciones_de_texto("from server import nc\n", "x.py"))

    def test_ve_S_punto(self):
        self.assertTrue(_violaciones_de_texto("def f():\n    return S.nc('GET', '/')\n", "x.py"))

    def test_ve_from_punto_import_server(self):
        self.assertTrue(_violaciones_de_texto("from . import server\n", "x.py"))

    def test_ve_import_con_alias_server(self):
        self.assertTrue(_violaciones_de_texto("from tools import algo as server\n", "x.py"))

    def test_ve_nombre_S_suelto(self):
        self.assertTrue(_violaciones_de_texto("S = None\n", "x.py"))

    def test_ve_import_dinamico_de_server(self):
        self.assertTrue(_violaciones_de_texto("import importlib\nimportlib.import_module('server')\n", "x.py"))

    def test_no_marca_un_modulo_que_se_llama_parecido(self):
        self.assertEqual(_violaciones_de_texto("import servers\nimport personas\nx = 'S.nc'\n", "x.py"), [])


class ElRepoNoNombraServer(unittest.TestCase):
    def test_ningun_archivo_del_repo_nombra_server_en_un_import_ni_usa_S(self):
        archivos = sorted(_archivos_py())
        self.assertTrue(archivos, "no hay ningún .py en el repo: la lista saldría vacía y la prueba no vería nada")
        malos = {}
        for ruta in archivos:
            hallazgos = _violaciones_de_texto(ruta.read_text(encoding="utf-8"), str(ruta))
            if hallazgos:
                malos[str(ruta.relative_to(RAIZ))] = hallazgos
        self.assertEqual(malos, {}, "archivos del repo que dependen de la App de registro")


if __name__ == "__main__":
    unittest.main()
