# -*- coding: utf-8 -*-
"""El repo de Personas no importa nada de la App de registro: ni `server`, ni el prefijo `S.` de los módulos de zona.

La lista de archivos sale del disco (todo `.py` del repo, menos `.git`), no de una lista tecleada.
La revisión es estricta: cualquier `import server`, `from server import …`, `__import__("server")`,
`import_module("server")`, cualquier nombre `S` o cualquier `S.<algo>` cuenta, aunque sea un nombre local.

Lo que NO ve: un import que se arme con texto variable (p. ej. `importlib.import_module(x)` con `x` calculado).
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

    def test_ve_nombre_S_suelto(self):
        self.assertTrue(_violaciones_de_texto("S = None\n", "x.py"))

    def test_ve_import_dinamico_de_server(self):
        self.assertTrue(_violaciones_de_texto("import importlib\nimportlib.import_module('server')\n", "x.py"))

    def test_no_marca_un_modulo_que_se_llama_parecido(self):
        self.assertEqual(_violaciones_de_texto("import servers\nimport personas\nx = 'S.nc'\n", "x.py"), [])


class ElRepoNoTocaLaApp(unittest.TestCase):
    def test_ningun_archivo_del_repo_importa_server_ni_usa_S(self):
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
