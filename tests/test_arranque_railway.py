# -*- coding: utf-8 -*-
"""El arranque para Railway: el Procfile lanza el archivo que de verdad arranca, y el programa no trae dependencias externas.

Dos garantías. Todo sale del disco, salvo el texto del Procfile (que se parsea):

1. El Procfile tiene una sola línea `web:` y su comando es `python3 <archivo>`. Ese archivo tiene que ser el ÚNICO .py de la
   raíz del repo con la guarda `if __name__ == "__main__":` a nivel de módulo (se busca por AST en cada .py de la raíz).
2. Los import de los módulos del programa (los .py de la raíz; no `tests/` ni `tools/`) son de la biblioteca estándar o
   módulos propios de la raíz, y `requirements.txt` no lista ninguna dependencia (solo comentarios o líneas vacías).

FRONTERA (declarada, no vigilada): solo se miran import escritos en código fijo (`import x`, `from x import y`). No se ve un
import con nombre calculado (`importlib.import_module(variable)`), ni código que se baje o se cargue por ruta, ni lo que
Railway haga con el Procfile (eso no se corre aquí). «Biblioteca estándar» se decide así: `sys.stdlib_module_names` si el
intérprete lo trae (3.10 o más); si no (el `/usr/bin/python3` de esta máquina es 3.9.6, sin esa lista), que el módulo esté
compilado en el intérprete o su archivo esté dentro de la carpeta `stdlib` de `sysconfig` y fuera de `site-packages`.
"""
import ast
import importlib.util
import os
import shlex
import sys
import sysconfig
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_STD = os.path.realpath(sysconfig.get_paths()["stdlib"])


def _archivos_del_programa():
    """Los .py que están directo en la raíz del repo, sacados del disco."""
    return sorted(p for p in RAIZ.iterdir() if p.is_file() and p.suffix == ".py")


def _propios():
    """Nombres de módulo que el repo trae en su raíz."""
    return {p.stem for p in _archivos_del_programa()}


def _tiene_guarda_main(arbol):
    """True si el módulo tiene `if __name__ == "__main__":` a nivel de módulo."""
    for nodo in arbol.body:
        if not isinstance(nodo, ast.If) or not isinstance(nodo.test, ast.Compare):
            continue
        t = nodo.test
        if (isinstance(t.left, ast.Name) and t.left.id == "__name__"
                and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq)
                and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
                and t.comparators[0].value == "__main__"):
            return True
    return False


def _es_estandar(nombre):
    """True si `nombre` (de nivel superior) es biblioteca estándar de este intérprete."""
    if hasattr(sys, "stdlib_module_names"):
        return nombre in sys.stdlib_module_names
    if nombre in sys.builtin_module_names:
        return True
    spec = importlib.util.find_spec(nombre)  # nivel superior: no ejecuta el módulo
    if spec is None or not spec.origin:
        return False
    if spec.origin in ("built-in", "frozen"):
        return True
    origen = os.path.realpath(spec.origin)
    return (origen.startswith(RUTA_STD + os.sep)
            and "site-packages" not in origen
            and "dist-packages" not in origen)


def _imports_de_nivel_superior(archivo):
    """(nombre de módulo de nivel superior, línea) de cada import absoluto del archivo, en todo el AST."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=archivo.name)
    usados = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            usados += [(alias.name.split(".")[0], nodo.lineno) for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:  # `from . import x`: dentro del propio programa
                continue
            usados.append((nodo.module.split(".")[0], nodo.lineno))
    return usados


class ArranqueRailway(unittest.TestCase):

    def test_procfile_arranca_el_unico_archivo_con_la_guarda_main(self):
        lineas = [l for l in (RAIZ / "Procfile").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lineas), 1, "el Procfile debe tener una sola línea: %r" % lineas)
        proceso, _, comando = lineas[0].partition(":")
        self.assertEqual(proceso.strip(), "web", "el proceso del Procfile debe ser `web`: %r" % lineas[0])
        partes = shlex.split(comando)
        self.assertEqual(partes[:1], ["python3"], "el comando debe empezar por python3: %r" % partes)
        self.assertEqual(len(partes), 2, "el comando debe ser `python3 <archivo>`: %r" % partes)
        arranque = partes[1]
        con_guarda = [
            a.name for a in _archivos_del_programa()
            if _tiene_guarda_main(ast.parse(a.read_text(encoding="utf-8"), filename=a.name))
        ]
        self.assertEqual(con_guarda, [arranque],
                         "el Procfile lanza %r, y el único archivo con la guarda __main__ es %r" % (arranque, con_guarda))

    def test_los_import_son_biblioteca_estandar_o_del_repo_y_requirements_no_lista_nada(self):
        archivos = _archivos_del_programa()
        self.assertGreater(len(archivos), 0, "no hay .py en la raíz del repo")
        propios = _propios()
        externos = []
        for archivo in archivos:
            for nombre, linea in _imports_de_nivel_superior(archivo):
                if nombre in propios or _es_estandar(nombre):
                    continue
                externos.append("%s:%d import %s" % (archivo.name, linea, nombre))
        self.assertEqual(externos, [], "imports que no son biblioteca estándar ni del repo")

        requisitos = (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
        dependencias = [l for l in requisitos if l.strip() and not l.strip().startswith("#")]
        self.assertEqual(dependencias, [], "requirements.txt lista dependencias: %r" % dependencias)


if __name__ == "__main__":
    unittest.main()
