# -*- coding: utf-8 -*-
"""El servidor del repo (`servidor.py`) contesta las rutas de lectura de Personas igual que la App de registro en `0b48b5d`.

La foto de referencia es `contrato_dorado/contrato.json` (sacada de la App). Esta prueba:
  R1  arranca `servidor.py` como proceso aparte, con el doble de NocoDB de `tests/doble_nocodb.py` (127.0.0.1), y pide los
      16 pedidos de la foto: el código y el cuerpo de cada respuesta tienen que ser IGUALES a los de la foto.
  R2  el doble no recibió más que GET, y no hubo ninguna lectura que no conociera (ni pedidos mal formados).
  R3  las cuatro rutas de Registro (`credito`, `buscar`, `bandeja`, `creditos-vivos`) no abren con la llave de Mercadeo
      ni con la variable vacía: 401 y no se lee nada.

Lo que NO ve (declarado): la foto solo se verifica contra su hash (`test_contrato_dorado.py`, CD1). Si alguien cambia un cuerpo
y recalcula el SHA256, esta prueba sigue verde mientras la foto y el servidor coincidan. Quien rehace la foto lo hace desde la
App de registro (`contrato_dorado/generar.py` de la App), no desde este repo. Mutación `m1c` de la sala: aceptada, declarada.
Las cuatro rutas de Registro no tienen foto propia: R3 solo mira la llave, no el cuerpo.
"""
import json
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import doble_nocodb as doble_mod  # noqa: E402

CONTRATO = RAIZ / "contrato_dorado" / "contrato.json"
LLAVE_REGISTRO = "llave-de-prueba-registro-personas"


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ElServidorContesteComoLaApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads(CONTRATO.read_text(encoding="utf-8"))["rutas"]
        cls.doble = doble_mod.Doble()
        url_doble = cls.doble.arrancar()
        cls.puerto = _puerto_libre()
        entorno = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "HOST": "127.0.0.1", "PORT": str(cls.puerto),
            "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
            "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
            "PERSONAS_REGISTRO_LLAVE": LLAVE_REGISTRO,
            "NOCODB_T_PERSONAS_ANOTACIONES": doble_mod.TABLA_ANOTACIONES,
        }
        cls.proceso = subprocess.Popen([sys.executable, "-B", str(RAIZ / "servidor.py")], cwd=str(RAIZ), env=entorno,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.listo = False
        for _ in range(100):
            if cls.proceso.poll() is not None:
                break
            try:
                if doble_mod._pedir(cls.puerto, "sonda", "GET", "/api/servicio/personas/config", None, True)["status"] == 200:
                    cls.listo = True
                    break
            except OSError:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        if cls.proceso.poll() is None:
            cls.proceso.terminate()
            cls.proceso.wait(timeout=10)
        cls.doble.parar()

    def test_R1_los_dieciseis_pedidos_dan_lo_mismo_que_la_foto(self):
        self.assertTrue(self.listo, "el servidor del repo no levantó")
        self.assertEqual(len(self.foto), 16)
        for entrada in self.foto:
            real = doble_mod._pedir(self.puerto, entrada["nombre"], entrada["metodo"], entrada["ruta"],
                                    entrada["cuerpo"], entrada["con_llave"])
            self.assertEqual(real["status"], entrada["status"], entrada["nombre"])
            self.assertEqual(real["respuesta"], entrada["respuesta"], entrada["nombre"])

    def test_R2_el_doble_solo_vio_get_y_ninguna_lectura_desconocida(self):
        self.assertEqual(self.doble.no_get, [])
        self.assertEqual(self.doble.errores, [])


class ElRegistroTieneSuLlave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doble = doble_mod.Doble()
        url_doble = cls.doble.arrancar()
        cls.puerto = _puerto_libre()
        entorno = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "HOST": "127.0.0.1", "PORT": str(cls.puerto),
            "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
            "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
            "PERSONAS_REGISTRO_LLAVE": LLAVE_REGISTRO,
        }
        cls.proceso = subprocess.Popen([sys.executable, "-B", str(RAIZ / "servidor.py")], cwd=str(RAIZ), env=entorno,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.listo = False
        for _ in range(100):
            if cls.proceso.poll() is not None:
                break
            try:
                if doble_mod._pedir(cls.puerto, "sonda", "GET", "/api/servicio/personas/config", None, True)["status"] == 200:
                    cls.listo = True
                    break
            except OSError:
                time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        if cls.proceso.poll() is None:
            cls.proceso.terminate()
            cls.proceso.wait(timeout=10)
        cls.doble.parar()

    RUTAS_REGISTRO = [("credito", "/api/servicio/personas/credito", {"telefono": "18097770001"}),
                      ("buscar", "/api/servicio/personas/buscar", {"q": "prueba", "limite": 3}),
                      ("bandeja", "/api/servicio/personas/bandeja", {"estados": ["contado"], "campos": "Id,estado", "pagina": 5, "tope": 5, "cursor": 0}),
                      ("creditos_vivos", "/api/servicio/personas/creditos-vivos", {})]

    def test_R3_sin_llave_o_con_la_de_mercadeo_401_y_no_se_lee_nada(self):
        self.assertTrue(self.listo)
        lecturas_antes = self.doble.lecturas
        for nombre, ruta, cuerpo in self.RUTAS_REGISTRO:
            sin = doble_mod._pedir(self.puerto, nombre, "POST", ruta, cuerpo, False)
            self.assertEqual(sin["status"], 401, nombre)
            con_la_otra = doble_mod._pedir(self.puerto, nombre, "POST", ruta, cuerpo, True)
            self.assertEqual(con_la_otra["status"], 401, nombre + " con la llave de Mercadeo")
        self.assertEqual(self.doble.lecturas, lecturas_antes, "una ruta sin llave leyó NocoDB")


if __name__ == "__main__":
    unittest.main()
