# -*- coding: utf-8 -*-
"""La memoria de Natalia en el programa (P8a-1): `POST /api/servicio/personas/memoria`.

Qué garantiza y con qué prueba:
  M1  la foto (`contrato_dorado/memoria.json`) es la que dice su SHA256.
  M2  los campos de `personas_memoria.MEMORIA_CAMPOS` son los de la foto (`campos_natalia`, sacados de `CAMPOS` de Natalia), no son de
      identidad, y todos están en el editor del portal.
  M3  el programa contesta a cada escenario dorado lo que contesta la App `142d45f` a su `editar` del portal: código, respuesta
      (con la ficha releída) y pedidos a NocoDB (servidor real, doble por HTTP).
  M4  la llave se mira ANTES de NocoDB: ausente, mala, la del portal (otro grupo), cabecera vacía con variable vacía, o variable vacía
      con cabecera buena: 401 y ningún pedido llega al doble.
  M5  sin identidad (cabecera ausente, vacía o solo espacios): 400 y ningún pedido llega al doble.
  M6  un campo fuera de la lista (identidad, teléfono, crédito, caras, bsuid…), un `id` que no es entero o un cuerpo roto: 400 y
      ninguna escritura (ningún POST, PATCH ni DELETE).
  M7  ningún paso que no guardó (409, 404, 400, 422, 502, sin cambios) manda un PATCH.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escenarios_memoria as em  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`normalizar`, el mismo de la foto)
import personas  # noqa: E402
import personas_memoria  # noqa: E402

CONTRATO = RAIZ / "contrato_dorado"
ESCRITURAS = ("POST", "PATCH", "DELETE", "PUT")


def _sin_clave(p):
    """Un paso comparable: código, respuesta y pedidos (lo que guarda la foto además del cuerpo que se mandó)."""
    return {k: p[k] for k in ("cuerpo", "status", "respuesta", "pedidos")}


class FotoYContrato(unittest.TestCase):
    """M1 y M2."""

    @classmethod
    def setUpClass(cls):
        cls.texto = (CONTRATO / "memoria.json").read_bytes()
        cls.foto = json.loads(cls.texto.decode("utf-8"))

    def test_M1_la_foto_es_la_de_su_sha(self):
        sha = hashlib.sha256(self.texto).hexdigest()
        self.assertEqual((CONTRATO / "SHA256_memoria").read_text(encoding="utf-8").split()[0], sha)

    def test_M2_los_campos_son_los_de_natalia_sin_identidad(self):
        self.assertEqual(list(personas_memoria.MEMORIA_CAMPOS), self.foto["campos_natalia"])
        self.assertEqual(len(self.foto["campos_natalia"]), 12)
        self.assertFalse(set(personas_memoria.MEMORIA_CAMPOS) & set(personas_memoria.IDENTIDAD_DE_NATALIA))
        self.assertEqual(set(self.foto["identidad_natalia"]), set(personas_memoria.IDENTIDAD_DE_NATALIA))
        for campo, etiqueta in personas_memoria.MEMORIA_CAMPOS.items():
            self.assertEqual(etiqueta, personas.PORTAL_EDITABLES[campo])


class ProgramaContestaComoLaApp(unittest.TestCase):
    """M3 y M7: cada escenario dorado contra el servidor real y el doble, igual que la foto de la App."""

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads((CONTRATO / "memoria.json").read_text(encoding="utf-8"))

    def test_M3_los_escenarios_dorados_dan_lo_mismo_que_la_app(self):
        for escenario, de_la_foto in zip(em.DORADOS, self.foto["escenarios"]):
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = em.ejecutar(escenario, str(RAIZ))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                self.assertEqual([esc.normalizar(_sin_clave(p)) for p in pasos],
                                 esc.normalizar([_sin_clave(p) for p in de_la_foto["pasos"]]))

    def test_M7_sin_guardar_no_hay_PATCH(self):
        # Un 502 con `sin_confirmar` sí puede llevar un PATCH (la escritura se intentó y el doble la tumbó): ese caso es el que se
        # vigila en `escritura_caida_502`, así que no se exige ausencia ahí. Todo lo demás que no guarda, no escribe.
        for escenario in em.DORADOS:
            pasos, _ = em.ejecutar(escenario, str(RAIZ))
            for paso in pasos:
                if paso["status"] == 200 and paso["respuesta"].get("estado") == "guardado":
                    continue
                if paso["status"] == 502 and paso["respuesta"].get("sin_confirmar"):
                    continue
                with self.subTest(escenario=escenario["nombre"], status=paso["status"]):
                    self.assertNotIn("PATCH", [p["metodo"] for p in paso["pedidos"]])


class GuardaDeLaLlaveYDeLaIdentidad(unittest.TestCase):
    """M4 y M5: 401 o 400 y cero pedidos a NocoDB."""

    def test_M4_la_llave_se_mira_antes_de_nocodb(self):
        for escenario in em.GUARDA:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = em.ejecutar(escenario, str(RAIZ))
                self.assertEqual(errores, [])
                self.assertTrue(pasos)
                for paso in pasos:
                    self.assertEqual(paso["status"], 401, paso)
                    self.assertEqual(paso["pedidos"], [], "llegó a NocoDB sin la llave buena")

    def test_M5_sin_identidad_no_hay_nada_que_leer_ni_escribir(self):
        for escenario in em.IDENTIDAD:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = em.ejecutar(escenario, str(RAIZ))
                self.assertEqual(errores, [])
                for paso in pasos:
                    self.assertEqual(paso["status"], 400, paso)
                    self.assertEqual(paso["pedidos"], [], "llegó a NocoDB sin identidad")


class FueraDeLaLista(unittest.TestCase):
    """M6: nada que no sea de la memoria llega a una escritura."""

    def test_M6_fuera_de_la_lista_no_escribe(self):
        for escenario in em.FUERA:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = em.ejecutar(escenario, str(RAIZ))
                self.assertEqual(errores, [])
                for paso in pasos:
                    self.assertEqual(paso["status"], 400, paso)
                    self.assertNotIn(paso["respuesta"].get("estado"), ("guardado",))
                    self.assertFalse([p for p in paso["pedidos"] if p["metodo"] in ESCRITURAS], "escribió con un campo fuera")

    def test_M6b_los_campos_de_identidad_se_rechazan_por_nombre(self):
        for escenario in em.FUERA:
            if not escenario["nombre"].endswith("_fuera"):
                continue
            campo = escenario["nombre"][: -len("_fuera")]
            with self.subTest(campo=campo):
                pasos, _ = em.ejecutar(escenario, str(RAIZ))
                self.assertEqual(pasos[0]["respuesta"].get("campos_rechazados"), [campo])


if __name__ == "__main__":
    unittest.main()
