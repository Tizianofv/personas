# -*- coding: utf-8 -*-
"""Mercadeo hacia Personas en el programa (P7): la baja y la foto. `POST /api/servicio/personas/mercadeo/{baja,foto}`.

Qué garantiza y con qué prueba:
  M1  la foto (`contrato_dorado/mercadeo.json`) es la que dice su SHA256.
  M2  las rutas del programa son las de la App con «/personas» insertado, y la foto guarda las de la App (`rutas_de_la_app`).
  M3  el programa contesta a cada escenario dorado lo que contestó la App `8c9d21a`: código, respuesta y pedidos a NocoDB
      (servidor real, doble de NocoDB por HTTP).
  M4  la llave se mira ANTES de NocoDB: ausente, mala, vacía, la de la entrada, o la variable vacía, dan 401 y ningún pedido llega al doble.
  M5  el llamador de `anotar_origen_al_nacer` es solo `_puerta_recibir` (AST sobre `personas.py`); las rutas de Mercadeo no lo llaman.
"""
import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escenarios_mercadeo as escenarios  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`normalizar`, el mismo de la foto)
import reloj  # noqa: E402
import servidor  # noqa: E402

CONTRATO = RAIZ / "contrato_dorado"


class FotoDeLaApp(unittest.TestCase):
    """M1 y M2: la foto, su SHA y las rutas."""

    @classmethod
    def setUpClass(cls):
        cls.texto = (CONTRATO / "mercadeo.json").read_bytes()
        cls.foto = json.loads(cls.texto.decode("utf-8"))

    def test_M1_la_foto_es_la_de_su_sha(self):
        sha = hashlib.sha256(self.texto).hexdigest()
        self.assertEqual((CONTRATO / "SHA256_mercadeo").read_text(encoding="utf-8").split()[0], sha)

    def test_M2_las_rutas_del_programa_son_las_de_la_app_con_personas(self):
        self.assertEqual(self.foto["rutas_de_la_app"], escenarios.RUTAS["app"])
        esperadas = {ruta.replace("/api/servicio/", "/api/servicio/personas/", 1) for ruta in self.foto["rutas_de_la_app"].values()}
        self.assertEqual(set(servidor.MERCADEO_RUTAS), esperadas)

    def test_M2b_los_escenarios_de_la_foto_son_los_del_archivo_de_escenarios(self):
        self.assertEqual([e["nombre"] for e in self.foto["escenarios"]], [e["nombre"] for e in escenarios.ESCENARIOS])


class ProgramaContestaComoLaApp(unittest.TestCase):
    """M3: cada escenario dorado, contra el servidor real del programa y el doble, igual que la foto de la App."""

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads((CONTRATO / "mercadeo.json").read_text(encoding="utf-8"))

    def test_M3_los_escenarios_dorados_dan_lo_mismo_que_la_app(self):
        for escenario, de_la_foto in zip(escenarios.ESCENARIOS, self.foto["escenarios"]):
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = escenarios.ejecutar(escenario, "programa", reloj.comando_programa(), str(RAIZ))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                self.assertEqual([esc.normalizar(p) for p in pasos], de_la_foto["pasos"])


class GuardaDeLaLlave(unittest.TestCase):
    """M4: sin la llave de Mercadeo (la propia del programa), 401 y ninguna lectura ni escritura en NocoDB."""

    def test_M4_la_llave_se_mira_antes_de_nocodb(self):
        for escenario in escenarios.GUARDA:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = escenarios.ejecutar(escenario, "programa", reloj.comando_programa(), str(RAIZ))
                self.assertEqual(errores, [])
                self.assertTrue(pasos)
                for paso in pasos:
                    self.assertEqual(paso["status"], 401, paso)
                    self.assertEqual(paso["pedidos"], [], "llegó a NocoDB sin la llave buena")


class OrigenNoTieneRuta(unittest.TestCase):
    """M5: el llamador de `anotar_origen_al_nacer` es solo `_puerta_recibir` (AST). Las rutas de Mercadeo no lo llaman."""

    def test_M5_solo_la_puerta_de_recibir_lo_llama(self):
        arbol = ast.parse((RAIZ / "personas.py").read_text(encoding="utf-8"))
        llamadores = set()

        def recorrer(nodo, funcion):
            for hijo in ast.iter_child_nodes(nodo):
                if isinstance(hijo, ast.FunctionDef):
                    recorrer(hijo, hijo.name)
                    continue
                if (isinstance(hijo, ast.Call) and isinstance(hijo.func, ast.Name)
                        and hijo.func.id == "anotar_origen_al_nacer"):
                    llamadores.add(funcion)
                recorrer(hijo, funcion)

        recorrer(arbol, None)
        self.assertEqual(llamadores, {"_puerta_recibir"})
        for archivo in ("personas_mercadeo.py", "servidor.py"):
            arbol_ruta = ast.parse((RAIZ / archivo).read_text(encoding="utf-8"))
            llama = [n for n in ast.walk(arbol_ruta) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "anotar_origen_al_nacer"]
            self.assertEqual(llama, [], archivo)


if __name__ == "__main__":
    unittest.main()
