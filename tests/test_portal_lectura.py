# -*- coding: utf-8 -*-
"""Las lecturas del portal que contesta `servidor.py` (paso 5c, primera parte): la llave del portal y la identidad.

La foto de referencia es `contrato/portal_lectura.json` (sacada de la App de registro en `594ec12` por
`tools/generar_portal_de_la_app.py`). Pruebas:
  CP1  los bytes de `contrato/portal_lectura.json` tienen el SHA256 de `contrato/SHA256_portal` (la foto no se movió).
  CP2  las rutas que el programa contesta (`servidor.PORTAL_LECTURA`) son EXACTAMENTE las de la foto de la App.
  P2   con la llave y la identidad bien, cada ruta contesta el mismo código y el mismo cuerpo que la foto; el doble no recibió
       más que GET ni una lectura que no conociera.
  K1   sin cabecera de llave: 401 en cada ruta, y cero lecturas a NocoDB.
  K2   con la llave vacía (cabecera vacía): 401, cero lecturas.
  K4   con la llave de otro grupo (Mercadeo, Registro o escritura de Registro), con identidad o sin ella: 401, cero lecturas.
  K5   con la llave casi igual (un carácter de más, o uno de menos): 401, cero lecturas.
  K3   con `PERSONAS_PORTAL_LLAVE` VACÍA (servidor aparte): 401 con cabecera vacía, sin cabecera, con la llave de Mercadeo y con
       una cualquiera; cero lecturas.
  I1   con la llave bien, sin identidad, con quien en blanco o con un tipo que no es el de la ruta: 400, cero lecturas.
  I2   la identidad que llega en cabeceras con la llave de OTRO grupo no decide nada: 401, cero lecturas.
  I3   (en proceso) la bandera de «exige identidad» de la tabla es la que manda: con `False`, la ruta contesta sin identidad.

Lo que NO ve (declarado):
  - La puerta de sesión de la App (`portal_personas`: 401 sin sesión, 403 sin permiso). No está en el programa; su tabla de
    rutas de 27 entradas es el paso siguiente del contrato y no se prueba aquí.
  - Que la App reenvíe la identidad: eso es de la App; aquí solo se prueba lo que el programa hace con la cabecera que recibe.
  - La foto se verifica por su hash (CP1). Si alguien cambia un cuerpo y recalcula el SHA256, P2 sigue verde mientras servidor y
    foto coincidan. Quien rehace la foto lo hace desde la App (`tools/generar_portal_de_la_app.py`).
  - Tipo de la identidad: solo se comprueba que sea igual al de la ruta («A»); no hay otros tipos todavía.
  - Espacios en los bordes de la llave: HTTP los quita antes de llegar; no son una llave distinta, y K5 no los prueba.
"""
import hashlib
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import doble_nocodb as doble_mod  # noqa: E402
import test_contrato_rutas as ctr  # noqa: E402  (su `_arrancar` y `_parar`: el mismo arranque que las pruebas de lectura)

CARPETA = RAIZ / "contrato"
LLAVE_PORTAL = "llave-de-prueba-portal-personas"
LLAVE_ESCRITURA = "llave-de-prueba-escritura-personas"
QUIEN = "Persona de prueba quien"
ERROR_LLAVE = {"error": "llave de servicio inválida"}
ERROR_IDENTIDAD = {"error": "identidad de portal ausente o no corresponde a la ruta"}


def _cabeceras(llave=LLAVE_PORTAL, quien=QUIEN, tipo="A"):
    """Las cabeceras del portal. Un valor `None` no se manda; `""` sí."""
    cabeceras = {}
    if llave is not None:
        cabeceras["X-Personas-Portal-Llave"] = llave
    if quien is not None:
        cabeceras["X-Personas-Portal-Quien"] = quien
    if tipo is not None:
        cabeceras["X-Personas-Portal-Tipo"] = tipo
    return cabeceras


def _pedir(puerto, ruta, cabeceras):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), method="GET", headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _entorno_comun():
    return {
        "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
        "PERSONAS_REGISTRO_LLAVE": ctr.LLAVE_REGISTRO,
        "PERSONAS_REGISTRO_ESCRITURA_LLAVE": LLAVE_ESCRITURA,
        "NOCODB_T_PERSONAS_QUITADAS": doble_mod.T_QUITADAS,
    }


def _rutas_del_programa():
    """Las rutas que el programa contesta, sacadas de su tabla real (no tecleadas)."""
    import servidor
    return sorted(servidor.PORTAL_LECTURA)


class ElPortalDeLectura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads((CARPETA / "portal_lectura.json").read_text(encoding="utf-8"))
        cls.proceso, cls.puerto, cls.doble = ctr._arrancar(dict(_entorno_comun(), PERSONAS_PORTAL_LLAVE=LLAVE_PORTAL))

    @classmethod
    def tearDownClass(cls):
        ctr._parar(cls.proceso, cls.doble)

    def _sin_leer_nocodb(self, fn):
        """Corre `fn` y comprueba que no hubo ninguna lectura a NocoDB."""
        antes = self.doble.lecturas
        resultado = fn()
        self.assertEqual(self.doble.lecturas, antes, "el servidor leyó NocoDB en un pedido que debía frenar")
        return resultado

    def test_CP1_la_foto_tiene_su_sha256(self):
        bytes_foto = (CARPETA / "portal_lectura.json").read_bytes()
        sha_guardado = (CARPETA / "SHA256_portal").read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256(bytes_foto).hexdigest(), sha_guardado)

    def test_CP2_las_rutas_del_programa_son_las_de_la_app(self):
        self.assertEqual(_rutas_del_programa(), sorted(p["ruta"] for p in self.foto["pedidos"]))

    def test_P2_con_llave_e_identidad_cada_ruta_es_igual_al_dorado(self):
        for pedido in self.foto["pedidos"]:
            with self.subTest(ruta=pedido["ruta"]):
                codigo, cuerpo = _pedir(self.puerto, pedido["ruta"], _cabeceras())
                self.assertEqual(codigo, pedido["status"])
                self.assertEqual(cuerpo, pedido["respuesta"])
        self.assertEqual(self.doble.no_get, [], "el doble recibió algo que no es GET")
        self.assertEqual(self.doble.errores, [], "el doble recibió una lectura que no conoce")

    def test_K1_sin_cabecera_de_llave_401_sin_leer(self):
        for ruta in _rutas_del_programa():
            with self.subTest(ruta=ruta):
                codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, _cabeceras(llave=None)))
                self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K2_llave_vacia_401_sin_leer(self):
        for ruta in _rutas_del_programa():
            with self.subTest(ruta=ruta):
                codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, _cabeceras(llave="")))
                self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K4_llaves_de_otros_grupos_401_sin_leer(self):
        otras = [doble_mod.LLAVE_LECTURA, ctr.LLAVE_REGISTRO, LLAVE_ESCRITURA]
        for ruta in _rutas_del_programa():
            for otra in otras:
                with self.subTest(ruta=ruta, otra=otra[:6]):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, _cabeceras(llave=otra)))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K5_llaves_casi_iguales_401_sin_leer(self):
        # Los espacios de los bordes no van: HTTP los quita de la cabecera antes de llegar al programa (medido: `" llave"` llega
        # igual que `"llave"`), así que no son una llave distinta.
        casi = [LLAVE_PORTAL + "x", LLAVE_PORTAL[:-1], LLAVE_PORTAL.upper()]
        for ruta in _rutas_del_programa():
            for llave in casi:
                with self.subTest(ruta=ruta, llave=llave[-3:]):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, _cabeceras(llave=llave)))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_I1_sin_identidad_o_con_tipo_que_no_es_el_de_la_ruta_400_sin_leer(self):
        casos = [
            ("sin quien", _cabeceras(quien=None)),
            ("quien en blanco", _cabeceras(quien="   ")),
            ("sin tipo", _cabeceras(tipo=None)),
            ("tipo de otra puerta", _cabeceras(tipo="B")),
        ]
        for ruta in _rutas_del_programa():
            for nombre, cabeceras in casos:
                with self.subTest(ruta=ruta, caso=nombre):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, cabeceras))
                    self.assertEqual((codigo, cuerpo), (400, ERROR_IDENTIDAD))

    def test_I2_la_identidad_del_navegador_no_decide_sin_la_llave_del_portal(self):
        for ruta in _rutas_del_programa():
            for llave in [doble_mod.LLAVE_LECTURA, None]:
                with self.subTest(ruta=ruta, llave=None if llave is None else "otra"):
                    cabeceras = _cabeceras(llave=llave, quien="Quien sea", tipo="A")
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, ruta, cabeceras))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))


class ElPortalSinLlaveEnLaVariable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proceso, cls.puerto, cls.doble = ctr._arrancar(dict(_entorno_comun(), PERSONAS_PORTAL_LLAVE=""))

    @classmethod
    def tearDownClass(cls):
        ctr._parar(cls.proceso, cls.doble)

    def test_K3_variable_vacia_no_acepta_ninguna_llave_y_no_lee(self):
        pruebas = [("cabecera vacia", ""), ("sin cabecera", None), ("llave de Mercadeo", doble_mod.LLAVE_LECTURA),
                   ("llave cualquiera", "llave-cualquiera")]
        for ruta in _rutas_del_programa():
            for nombre, llave in pruebas:
                with self.subTest(ruta=ruta, caso=nombre):
                    antes = self.doble.lecturas
                    codigo, cuerpo = _pedir(self.puerto, ruta, _cabeceras(llave=llave))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))
                    self.assertEqual(self.doble.lecturas, antes)


class ElFlagDeIdentidadManda(unittest.TestCase):
    """En proceso: con la bandera de «exige identidad» en `False`, la ruta contesta sin identidad (la bandera de la tabla es la que manda)."""

    def test_I3_bandera_falsa_no_pide_identidad(self):
        import base
        import servidor
        doble = doble_mod.Doble()
        url = doble.arrancar()
        tabla = {"/api/portal-personas/nueva": ("nueva", servidor.PORTAL_TIPO_A, False)}
        servidor_http = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        threading.Thread(target=servidor_http.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(servidor, "PORTAL_LECTURA", tabla), \
                    mock.patch.object(servidor, "LLAVE_PERSONAS_PORTAL", LLAVE_PORTAL), \
                    mock.patch.object(base, "NOCODB_BASE", url), mock.patch.object(base, "NOCODB_TOKEN", "token-de-prueba"):
                codigo, cuerpo = _pedir(servidor_http.server_address[1], "/api/portal-personas/nueva", _cabeceras(quien=None, tipo=None))
                foto = json.loads((CARPETA / "portal_lectura.json").read_text(encoding="utf-8"))
                nueva = [p for p in foto["pedidos"] if p["ruta"] == "/api/portal-personas/nueva"][0]
                self.assertEqual((codigo, cuerpo), (nueva["status"], nueva["respuesta"]))
        finally:
            servidor_http.shutdown()
            servidor_http.server_close()
            doble.parar()


if __name__ == "__main__":
    unittest.main()
