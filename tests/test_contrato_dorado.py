# -*- coding: utf-8 -*-
"""Contrato dorado de Personas: la foto de lo que contesta la App de registro para las rutas de lectura de Personas.

Origen: la App de registro en el commit `0b48b5d` (rama `main`), corrida en una copia `git archive` con su propio
`contrato_dorado/generar.py` y un doble de NocoDB en 127.0.0.1. Dos corridas seguidas dieron el mismo SHA256, y ese
mismo SHA256 es el que guarda la App en su `contrato_dorado/SHA256`.

Pruebas:
  CD1  los bytes de `contrato.json` tienen el SHA256 de `SHA256` (la foto no se movió).
  CD2  la foto tiene las cinco rutas de lectura de Personas, y ninguna más.
  CD3  la foto declara cero escrituras a NocoDB, y tiene una respuesta por cada pedido.
"""
import hashlib
import json
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "contrato_dorado"

RUTAS_DE_LECTURA = {
    "/api/servicio/personas/config",
    "/api/servicio/personas/identidad",
    "/api/servicio/personas/fichas",
    "/api/servicio/personas/anotaciones",
    "/api/servicio/personas/pagina",
}


class ElContratoDorado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bytes_contrato = (CARPETA / "contrato.json").read_bytes()
        cls.sha_guardado = (CARPETA / "SHA256").read_text(encoding="utf-8").split()[0]
        cls.contrato = json.loads(cls.bytes_contrato.decode("utf-8"))

    def test_CD1_los_bytes_tienen_el_sha256_guardado(self):
        self.assertEqual(hashlib.sha256(self.bytes_contrato).hexdigest(), self.sha_guardado)

    def test_CD2_las_rutas_son_las_cinco_de_lectura_de_personas(self):
        rutas = {r["ruta"] for r in self.contrato["rutas"]}
        self.assertEqual(rutas, RUTAS_DE_LECTURA)

    def test_CD3_cero_escrituras_y_una_respuesta_por_pedido(self):
        self.assertEqual(self.contrato["escrituras_a_nocodb"], 0)
        self.assertEqual(len(self.contrato["rutas"]), self.contrato["pedidos"])


if __name__ == "__main__":
    unittest.main()
