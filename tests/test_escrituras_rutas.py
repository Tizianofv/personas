# -*- coding: utf-8 -*-
"""Las escrituras de Registro en el programa de Personas (paso 5b) contestan lo mismo que la App de registro en `0b48b5d`.

  E1  la foto `contrato_dorado/escrituras.json` tiene el SHA256 que dice `contrato_dorado/SHA256_escrituras`.
  E2  los escenarios de `tests/escenarios_escrituras.py`, corridos contra `servidor.py` del repo y el doble que escribe
      (`tests/doble_escrituras.py`): en cada paso, el MISMO código, la MISMA respuesta y los MISMOS pedidos que llegaron al
      doble que en la foto de la App (método, ruta, query y cuerpo). Y el doble no recibió ningún pedido que no conociera.
  E3  una escritura que falla después de salir a NocoDB se contesta con el aviso de «no sé si quedó guardado» y
      `sin_confirmar: true`, igual que la App; una lectura caída sin escritura se contesta con su texto de siempre.
  K1  la llave de escrituras: sin cabecera, con cabecera vacía, con la llave de Mercadeo, con la de lectura de Registro,
      con una llave mala, y con la variable vacía: 401 en las tres rutas, y el doble no recibe ningún pedido.
  K2  la llave de escrituras no abre las lecturas: 401 y cero pedidos en `credito` (de Registro) y en `identidad` (de Mercadeo).
  K3  con la llave de escrituras, las tres rutas no dan 401 (la llave es la correcta y funciona).
  K4  la llave se mira antes de leer el cuerpo: un cuerpo que no es JSON, sin llave, da 401 y no 400.

Lo que NO ve (declarado): el doble no es NocoDB. No imita sus códigos de error ni sus textos: una operación que cae se simula
con `caidas` (500 para esa operación). La foto se verifica por su hash (E1); quien la rehace la saca de la App copiada
(`tools/generar_escrituras_de_la_app.py`), no de este repo. Ningún pedido sale a NocoDB real: todo va al doble, en 127.0.0.1.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import escenarios_escrituras as esc  # noqa: E402
import base  # noqa: E402

FOTA = RAIZ / "contrato_dorado" / "escrituras.json"
SHA_DECLARADO = RAIZ / "contrato_dorado" / "SHA256_escrituras"
COMANDO = [sys.executable, "-B", str(RAIZ / "servidor.py")]
CUERPOS = {esc.RUTA_CARA: esc.CARA_OK, esc.RUTA_NUEVA: esc.NUEVA_OK, esc.RUTA_EDITAR: esc.EDITAR_OK}


def _correr(pasos, entorno=None, caidas=()):
    escenario = {"nombre": "prueba", "pasos": pasos, "caidas": list(caidas)}
    if entorno is not None:
        escenario["entorno"] = entorno
    return esc.ejecutar(escenario, COMANDO, cwd=str(RAIZ))


class EscriturasDeRegistroEnPersonas(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads(FOTA.read_text(encoding="utf-8"))
        cls.por_nombre = {e["nombre"]: e for e in cls.foto["escenarios"]}

    def test_E1_la_foto_tiene_el_sha_declarado(self):
        real = hashlib.sha256(FOTA.read_bytes()).hexdigest()
        declarado = SHA_DECLARADO.read_text(encoding="utf-8").split()[0]
        self.assertEqual(real, declarado)

    def test_E2_cada_escenario_contesta_y_escribe_como_la_app(self):
        self.assertEqual(sorted(self.por_nombre), sorted(e["nombre"] for e in esc.ESCENARIOS))
        for escenario in esc.ESCENARIOS:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = esc.ejecutar(escenario, COMANDO, cwd=str(RAIZ))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                esperados = self.por_nombre[escenario["nombre"]]["pasos"]
                self.assertEqual(len(pasos), len(esperados))
                for real, foto in zip(pasos, esperados):
                    self.assertEqual(real, foto)

    def test_E3_fallo_despues_de_escribir_se_marca_y_fallo_de_lectura_no(self):
        pasos, _ = _correr([esc._esc(esc.RUTA_CARA, esc.CARA_OK)], caidas=["PATCH"])
        self.assertEqual(pasos[0]["status"], 502)
        self.assertEqual([p["metodo"] for p in pasos[0]["pedidos"]], ["GET", "PATCH"])
        self.assertIs(pasos[0]["respuesta"].get("sin_confirmar"), True)
        self.assertTrue(pasos[0]["respuesta"]["error"].startswith(base.MENSAJE_FALLO_TRAS_ESCRIBIR))
        self.assertTrue(pasos[0]["respuesta"]["error"].endswith("No se guardó. Personas no responde. Inténtalo en un momento."))
        pasos, _ = _correr([esc._esc(esc.RUTA_CARA, esc.CARA_OK)], caidas=["GET"])
        self.assertEqual(pasos[0]["status"], 502)
        self.assertNotIn("sin_confirmar", pasos[0]["respuesta"])
        self.assertEqual(pasos[0]["respuesta"]["error"], "No se guardó. Personas no responde. Inténtalo en un momento.")
        self.assertEqual([p["metodo"] for p in pasos[0]["pedidos"]], ["GET"])

    def test_K1_sin_llave_valida_no_hay_escritura(self):
        pasos = [esc._esc(ruta, cuerpo, valor=valor)
                 for ruta, cuerpo in CUERPOS.items()
                 for valor in ("ausente", "vacia", "lectura_mercadeo", "lectura_registro", "mala")]
        resultados, errores = _correr(pasos)
        self.assertEqual(errores, [])
        for paso in resultados:
            with self.subTest(ruta=paso["ruta"], valor=paso["valor"]):
                self.assertEqual(paso["status"], 401)
                self.assertEqual(paso["respuesta"], {"error": "llave de servicio inválida"})
                self.assertEqual(paso["pedidos"], [])

    def test_K1b_con_la_variable_vacia_la_llave_de_escrituras_no_abre(self):
        pasos = [esc._esc(ruta, cuerpo) for ruta, cuerpo in CUERPOS.items()]
        resultados, _ = _correr(pasos, entorno={"PERSONAS_REGISTRO_ESCRITURA_LLAVE": ""})
        for paso in resultados:
            with self.subTest(ruta=paso["ruta"]):
                self.assertEqual(paso["status"], 401)
                self.assertEqual(paso["pedidos"], [])

    def test_K2_la_llave_de_escrituras_no_abre_las_lecturas(self):
        pasos = [esc._lectura(esc.RUTA_CREDITO, esc.RUTA_LECTURA_REGISTRO_CABECERA, {"telefono": "18097770001"}, "escritura"),
                 esc._lectura(esc.RUTA_IDENTIDAD, esc.RUTA_LECTURA_MERCADEO_CABECERA, {"identidad": "18097770001"}, "escritura")]
        resultados, _ = _correr(pasos)
        for paso in resultados:
            with self.subTest(ruta=paso["ruta"]):
                self.assertEqual(paso["status"], 401)
                self.assertEqual(paso["pedidos"], [])

    def test_K3_con_la_llave_de_escrituras_las_tres_rutas_contestan(self):
        pasos = [esc._esc(ruta, cuerpo) for ruta, cuerpo in CUERPOS.items()]
        resultados, _ = _correr(pasos)
        for paso in resultados:
            with self.subTest(ruta=paso["ruta"]):
                self.assertEqual(paso["status"], 200)
                self.assertTrue(paso["pedidos"], "con la llave buena la ruta tiene que llegar al doble")

    def test_K4_la_llave_se_mira_antes_de_leer_el_cuerpo(self):
        resultados, _ = _correr([esc._esc(esc.RUTA_CARA, crudo="no es json", valor="ausente")])
        self.assertEqual(resultados[0]["status"], 401)
        self.assertEqual(resultados[0]["pedidos"], [])


if __name__ == "__main__":
    unittest.main()
