# -*- coding: utf-8 -*-
"""La ficha del Aprendizaje en el programa (P6): `POST /api/aprendizaje/fichas/<identidad>/editar`.

Qué garantiza y con qué prueba:
  A1  la foto (`contrato_dorado/aprendizaje.json`) es la que dice su SHA256.
  A2  la ruta de la tabla (`servidor.APRENDIZAJE_ESCRITURA`) es el literal de la App (`ruta_de_la_app` de la foto, leído con AST).
  A3  el programa contesta a cada escenario dorado lo que contestó la App: código, respuesta y pedidos a NocoDB (servidor real, doble).
  A4  la guarda: sin llave buena no se lee ni se escribe nada (401); sin identidad de tipo «C» y `quien` no vacío, tampoco (400).
  A5  `quien` sale de la cabecera X-Personas-Portal-Quien, nunca del cuerpo (espía en el proceso: el doble no guarda `quien` aquí).
  A6  el `una_vez` «ficha-editar» tiene el `exito` de la App (AST) y su hermano «cuerpo distinto» escribe otra vez (la regla de hermanos).
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escenarios_aprendizaje as escenarios  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (servidor real, doble de NocoDB y normalización de la foto)
import personas  # noqa: E402
import personas_portal_escritura  # noqa: E402
import reloj  # noqa: E402
import servidor  # noqa: E402

CONTRATO = RAIZ / "contrato_dorado"


class FotoDeLaApp(unittest.TestCase):
    """A1 y A2: la foto y la tabla."""

    @classmethod
    def setUpClass(cls):
        cls.texto = (CONTRATO / "aprendizaje.json").read_bytes()
        cls.foto = json.loads(cls.texto.decode("utf-8"))

    def test_A1_la_foto_es_la_de_su_sha(self):
        sha = hashlib.sha256(self.texto).hexdigest()
        self.assertEqual((CONTRATO / "SHA256_aprendizaje").read_text(encoding="utf-8").split()[0], sha)

    def test_A2_la_ruta_de_la_tabla_es_la_de_la_app(self):
        self.assertEqual(len(servidor.APRENDIZAJE_ESCRITURA), 1)
        self.assertEqual(list(servidor.APRENDIZAJE_ESCRITURA)[0], self.foto["ruta_de_la_app"])

    def test_A2b_los_escenarios_de_la_foto_son_los_del_archivo_de_escenarios(self):
        self.assertEqual([e["nombre"] for e in self.foto["escenarios"]], [e["nombre"] for e in escenarios.ESCENARIOS])


class ProgramaContestaComoLaApp(unittest.TestCase):
    """A3: cada escenario dorado, contra el servidor real del programa y el doble, igual que la foto de la App."""

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads((CONTRATO / "aprendizaje.json").read_text(encoding="utf-8"))

    def test_A3_los_escenarios_dorados_dan_lo_mismo_que_la_app(self):
        for escenario, de_la_foto in zip(escenarios.ESCENARIOS, self.foto["escenarios"]):
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = esc.ejecutar(escenario, reloj.comando_programa(), str(RAIZ))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                self.assertEqual([esc.normalizar(p) for p in pasos], de_la_foto["pasos"])


class HermanosDeUnaVez(unittest.TestCase):
    """A6: el `una_vez` de la ficha (ámbito «ficha-editar») tiene el `exito` de la App y su hermano «cuerpo distinto» escribe otra vez."""

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads((CONTRATO / "aprendizaje.json").read_text(encoding="utf-8"))

    def test_A6a_el_exito_del_programa_es_el_de_la_app(self):
        import ast
        arbol = ast.parse((RAIZ / "personas_portal_escritura.py").read_text(encoding="utf-8"))
        exitos = []
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "una_vez"
                    and nodo.args and isinstance(nodo.args[0], ast.Constant) and nodo.args[0].value == "ficha-editar"):
                exitos += [ast.unparse(kw.value.body) for kw in nodo.keywords if kw.arg == "exito"]
        self.assertEqual(exitos, [self.foto["exito_de_la_app"]["ficha-editar"]])

    def test_A6b_cuerpo_distinto_escribe_otra_vez_y_no_dice_ya_guardado(self):
        escenario = next(e for e in self.foto["escenarios"] if e["nombre"] == "editar_cuerpo_distinto")
        segundo = escenario["pasos"][1]
        self.assertNotIn("ya_guardado", segundo["respuesta"])
        self.assertTrue([q for q in segundo["pedidos"] if q["metodo"] != "GET"], "el cuerpo distinto tiene que escribir")


class GuardasDelPrograma(unittest.TestCase):
    """A4: sin llave o sin identidad, 401 o 400 y ningún pedido a NocoDB."""

    def test_A4_llave_y_identidad_se_miran_antes_de_nocodb(self):
        for escenario in escenarios.GUARDA:
            # Llave mala, vacía o ausente: 401. Identidad mala (tipo, `quien` vacío o ausente): 400. Ninguna llega a NocoDB.
            esperado = 401 if escenario["nombre"].startswith("llave_") else 400
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = esc.ejecutar(escenario, reloj.comando_programa(), str(RAIZ))
                self.assertEqual(errores, [])
                for paso in pasos:
                    self.assertEqual(paso["status"], esperado)
                    self.assertEqual(paso["pedidos"], [], "llegó a NocoDB sin llave o identidad buenas")


class QuienSaleDeLaCabecera(unittest.TestCase):
    """A5: el espía. `quien` que llega a `personas.editar_ficha_cliente` es el de la cabecera; el del cuerpo no se lee."""

    def test_A5_quien_es_el_de_la_cabecera(self):
        llamadas = []
        original = personas.editar_ficha_cliente

        def espia(identidad, cuerpo, quien):
            llamadas.append((identidad, quien))
            return 200, {"ok": True, "estado": "guardado", "campos": ["nombre"], "base": {"nombre": "X"}}

        personas.editar_ficha_cliente = espia
        try:
            crudo = json.dumps({"id": 2, "quien": "Otra Persona", "cambios": {"nombre": "X"}, "base": {"nombre": "Y"}}).encode("utf-8")
            codigo, cuerpo = personas_portal_escritura.responder(
                "editar_aprendizaje", "/api/aprendizaje/fichas/18097770002/editar", ("18097770002",), crudo, "Ana Pérez")
        finally:
            personas.editar_ficha_cliente = original
        self.assertEqual(codigo, 200)
        self.assertEqual(llamadas, [("18097770002", "Ana Pérez")])


if __name__ == "__main__":
    unittest.main()
