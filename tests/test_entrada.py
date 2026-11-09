# -*- coding: utf-8 -*-
"""La entrada de Natalia en el programa (P5a + P5b) contesta lo mismo que la App de registro en `8c9d21a`.

  E1  la foto `contrato_dorado/entrada.json` tiene el SHA256 que dice `contrato_dorado/SHA256_entrada`.
  E2  los escenarios de `tests/escenarios_entrada.py`, corridos contra `servidor.py` del programa y el doble que escribe: en cada
      paso, el MISMO código, la MISMA respuesta y los MISMOS pedidos al doble que en la foto de la App (método, ruta, consulta y cuerpo).
      El doble no recibió ningún pedido que no conociera. La hora `cuando` se compara como `<hora>`, pero antes se exige que sea ISO.
  K1  la llave de la entrada: sin cabecera, vacía, mala o con la variable vacía, 401, y el doble no recibe ningún pedido. Con la
      variable vacía la ruta nace cerrada, aunque la cabecera traiga un valor.
  K2  sin llave, un cuerpo que no es JSON da 401 y no 400: la llave se mira antes del cuerpo.
  K3  con la llave correcta, la ruta no da 401.

Lo que NO ve (declarado): el doble no es NocoDB (no imita sus códigos ni sus textos; una operación que cae se simula con `caidas`).
La llave de la App (`X-Fichas-Llave`, `FICHAS_LLAVE_SERVICIO`) y su respuesta 503 «apagada» no son de este programa: la App las mira
antes de reenviar, y no se comparan aquí. La foto no fija `FICHAS_LLAVE_SERVICIO` vacía. El lado de la App solo se prueba con las
llaves de los escenarios de la foto.
"""
import hashlib
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))
import escenarios_entrada as esc  # noqa: E402

COMANDO = [sys.executable, "-B", str(RAIZ / "servidor.py")]
FOTO = RAIZ / "contrato_dorado" / "entrada.json"
SHA = RAIZ / "contrato_dorado" / "SHA256_entrada"


def _foto():
    import json
    return json.loads(FOTO.read_text(encoding="utf-8"))


class TestEntrada(unittest.TestCase):
    def test_E1_la_foto_tiene_el_sha_que_dice(self):
        real = hashlib.sha256(FOTO.read_bytes()).hexdigest()
        self.assertEqual(real, SHA.read_text(encoding="utf-8").split()[0])

    def test_E2_los_escenarios_contestan_lo_mismo_que_la_app(self):
        foto = {e["nombre"]: e["pasos"] for e in _foto()["escenarios"]}
        self.assertEqual(sorted(foto), sorted(e["nombre"] for e in esc.ESCENARIOS), "la foto y los escenarios no son los mismos")
        for escenario in esc.ESCENARIOS:
            with self.subTest(escenario=escenario["nombre"]):
                pasos, errores = esc.ejecutar(escenario, "programa", COMANDO, cwd=str(RAIZ))
                self.assertEqual(errores, [], "el doble recibió un pedido que no conoce")
                horas = esc.horas_de_los_pedidos(pasos)
                self.assertTrue(all(esc._HORA.fullmatch(h) for h in horas), "una hora `cuando` no es ISO")
                esc.normalizar_horas(pasos)
                esperado = foto[escenario["nombre"]]
                self.assertEqual(len(pasos), len(esperado))
                for real, app in zip(pasos, esperado):
                    self.assertEqual(real["status"], app["status"], "código distinto")
                    self.assertEqual(real["respuesta"], app["respuesta"], "respuesta distinta")
                    self.assertEqual(real["pedidos"], app["pedidos"], "pedidos al doble distintos")

    def test_K1_sin_llave_valida_no_se_lee_ni_se_escribe(self):
        escenario = {"nombre": "k1", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"}, "tablas": esc.bandeja(esc.NUEVA),
                     "pasos": [{"cuerpo": {"fila": 1}, "valor": "mala"}, {"cuerpo": {"fila": 1}, "valor": "vacia"},
                               {"cuerpo": {"fila": 1}, "valor": "ausente"}]}
        pasos, errores = esc.ejecutar(escenario, "programa", COMANDO, cwd=str(RAIZ))
        self.assertEqual(errores, [])
        for paso in pasos:
            self.assertEqual(paso["status"], 401)
            self.assertEqual(paso["respuesta"], {"error": "llave de servicio inválida"})
            self.assertEqual(paso["pedidos"], [], "con la llave mal, el doble recibió pedidos")

    def test_K1b_variable_vacia_nace_cerrada(self):
        escenario = {"nombre": "k1b", "entorno": {"PERSONAS_ENTRADA_LLAVE": "", "FICHAS_ENTRADA_MODO": "escribir"},
                     "tablas": esc.bandeja(esc.NUEVA), "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]}
        pasos, errores = esc.ejecutar(escenario, "programa", COMANDO, cwd=str(RAIZ))
        self.assertEqual(errores, [])
        self.assertEqual(pasos[0]["status"], 401)
        self.assertEqual(pasos[0]["pedidos"], [], "con la variable vacía el doble recibió pedidos")

    def test_K2_sin_llave_el_cuerpo_ilegible_da_401(self):
        escenario = {"nombre": "k2", "tablas": esc.bandeja(esc.NUEVA),
                     "pasos": [{"crudo": "no es json", "valor": "ausente"}, {"crudo": "{", "valor": "mala"}]}
        pasos, errores = esc.ejecutar(escenario, "programa", COMANDO, cwd=str(RAIZ))
        self.assertEqual(errores, [])
        for paso in pasos:
            self.assertEqual(paso["status"], 401)
            self.assertEqual(paso["pedidos"], [])

    def test_K3_con_la_llave_correcta_no_da_401(self):
        escenario = {"nombre": "k3", "tablas": esc.bandeja(esc.NUEVA), "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]}
        pasos, errores = esc.ejecutar(escenario, "programa", COMANDO, cwd=str(RAIZ))
        self.assertEqual(errores, [])
        self.assertNotEqual(pasos[0]["status"], 401)


if __name__ == "__main__":
    unittest.main()
