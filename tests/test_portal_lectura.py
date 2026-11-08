# -*- coding: utf-8 -*-
"""Las lecturas del portal que contesta `servidor.py` (paso 5c, partes 1 y 2): la llave del portal, la identidad y las respuestas.

La foto de referencia es `contrato/portal_lectura.json`, sacada de la App de registro en `594ec12` por
`tools/generar_portal_de_la_app.py`: `rutas_de_la_app` (las rutas GET del portal que la App contesta, leídas con AST) y `pedidos`
(una respuesta de la App por ruta de la tabla, con su consulta). Casi todas son 200; los escenarios de error y de caída de
«borrar/revisar» (parte 5) son 404 y 502, con su caída en un doble propio (`caidas`).

Pruebas (las de llave e identidad recorren TODA la tabla `servidor.PORTAL_LECTURA`, no una lista tecleada):
  CP1  los bytes de `contrato/portal_lectura.json` tienen el SHA256 de `contrato/SHA256_portal`.
  CP2  la tabla y la foto cubren lo mismo: cada entrada de la tabla tiene un pedido de la foto que casa con ella, y cada pedido
       casa con una entrada. C2: cada pedido de la foto es un 200, salvo los de caída (502) y el de «no_existe» (404).
  CP5  la foto tiene un pedido por cada escenario de `tools/generar_portal_de_la_app.RUTAS` (el generador es la fuente): quitar uno
       de la foto da rojo aunque se recalcule el SHA (CP1 no lo ve).
  P4   los pedidos con caída corren en su propio servidor y doble (`caidas=GET`): el mismo código y cuerpo que la App, y el doble
       contó la caída.
  CP3  tabla + `PORTAL_FUERA_DEL_PROGRAMA` = las rutas que la App contesta (`rutas_de_la_app`). Ninguna en las dos listas. Cada
       salida tiene su motivo escrito. Si la App añade una ruta y no está en ninguna, esta prueba falla.
  P2   cada pedido de la foto, con la llave y la identidad bien, da el mismo código y el mismo cuerpo que la App; el doble no
       recibió más que GET ni una lectura que no conociera.
  K1   sin cabecera de llave: 401 en cada entrada de la tabla, y cero lecturas a NocoDB.
  K2   con la llave vacía: 401, cero lecturas.
  K4   cada llave de otro grupo (Mercadeo, Registro, escritura de Registro) en SU cabecera, sin la del portal: 401, cero lecturas.
  K4b  las llaves de otros grupos en la cabecera del portal: 401, cero lecturas.
  K5   llave casi igual (un carácter de más o de menos, o en mayúsculas): 401, cero lecturas.
  K6   la llave del portal en la cabecera de config (GET) y de una ruta de Registro (POST): 401, cero lecturas.
  I1   con la llave bien, sin identidad, quien en blanco, o tipo ajeno: 400, cero lecturas (en cada entrada).
  I2   la identidad que llega con la llave de OTRO grupo, o sin llave, no decide nada: 401, cero lecturas (en cada entrada).
  K3   (servidor aparte) con `PERSONAS_PORTAL_LLAVE` VACÍA: 401 en cada entrada con cabecera vacía, sin cabecera, con la llave de
       Mercadeo o con una cualquiera; cero lecturas.
  I3   (en proceso) la bandera «exige identidad» de la tabla es la que manda.

Lo que NO ve (declarado):
  - La puerta de sesión de la App (`portal_personas`: 401 sin sesión, 403 sin permiso). El programa no la tiene.
  - Que la App reenvíe la llave y la identidad: eso es de la App; aquí solo se prueba lo que el programa hace con lo que recibe.
  - La foto se verifica por su hash (CP1). Si alguien cambia un cuerpo y recalcula el SHA256, P2 sigue verde mientras servidor y foto
    coincidan. Quien rehace la foto lo hace desde la App (`tools/generar_portal_de_la_app.py`).
  - Los 400 de validación de la lista (orden, col, desde, limite, ver) y de unir (otra): el código está copiado de la App, pero
    ningún pedido de la foto es un 400 (C2), así que no hay prueba contra la App para esas ramas. Declarado.
  - La rama «resueltos» de por-resolver y la unión de fichas dentro de la ficha (`T_UNIONES_PERSONAS` no se configura en la foto):
    la foto no las ejercita.
  - Tipo de la identidad: solo se comprueba que sea igual al de la ruta («A»).
  - Espacios en los bordes de la llave: HTTP los quita antes de llegar; no son una llave distinta, y K5 no los prueba.
  - La foto es de un día: ningún campo de la foto depende de la fecha de hoy (grep de las claves), pero el código sí puede.
"""
import hashlib
import json
import re
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import doble_nocodb as doble_mod  # noqa: E402
import test_contrato_rutas as ctr  # noqa: E402  (su `_arrancar` y `_parar`: el mismo arranque que las pruebas de lectura)
sys.path.insert(0, str(RAIZ / "tools"))
import generar_portal_de_la_app as generador  # noqa: E402  (la fuente de los escenarios de la foto y de su entorno, `ENTORNO_FOTO`)

CARPETA = RAIZ / "contrato"
LLAVE_PORTAL = "llave-de-prueba-portal-personas"
LLAVE_ESCRITURA = "llave-de-prueba-escritura-personas"
QUIEN = "Persona de prueba quien"
ERROR_LLAVE = {"error": "llave de servicio inválida"}
ERROR_IDENTIDAD = {"error": "identidad de portal ausente o no corresponde a la ruta"}


def _foto():
    return json.loads((CARPETA / "portal_lectura.json").read_text(encoding="utf-8"))


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


def _pedir(puerto, ruta, cabeceras, metodo="GET"):
    """Una petición. `ruta` puede llevar la consulta. GET sin cuerpo; POST con `{}` (las rutas de Registro miran la llave antes)."""
    datos = b"{}" if metodo == "POST" else None
    cabeceras = dict(cabeceras, **({"Content-Type": "application/json"} if datos is not None else {}))
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _url(pedido):
    """La ruta de un pedido de la foto, con su consulta."""
    return pedido["ruta"] + ("?" + pedido["consulta"] if pedido["consulta"] else "")


def _entorno_comun():
    return dict({
        "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
        "PERSONAS_REGISTRO_LLAVE": ctr.LLAVE_REGISTRO,
        "PERSONAS_REGISTRO_ESCRITURA_LLAVE": LLAVE_ESCRITURA,
        "NOCODB_T_PERSONAS_QUITADAS": doble_mod.T_QUITADAS,
        "NOCODB_T_BANDEJA_PERSONAS": doble_mod.T_BANDEJA,
    }, **generador.ENTORNO_FOTO)     # las tablas de envíos y de uniones de «borrar/revisar»: las mismas que en la foto


def _tabla():
    """Las entradas de la tabla del programa (`servidor.PORTAL_LECTURA`), sacadas de su código, no tecleadas."""
    import servidor
    return servidor


def _ejemplos():
    """Por cada entrada de la tabla, el primer pedido de la foto que casa con su patrón: `{patrón: pedido}`. Si una entrada no tiene
    pedido, la prueba falla (CP2): así ninguna entrada se prueba sin una respuesta real de la App delante."""
    tabla = _tabla().PORTAL_LECTURA
    ejemplos = {}
    for patron in tabla:
        casan = [p for p in _foto()["pedidos"] if re.fullmatch(patron, p["ruta"])]
        ejemplos[patron] = casan[0] if casan else None
    return ejemplos


class ElPortalDeLectura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foto = _foto()
        cls.ejemplos = _ejemplos()
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

    def _entradas(self):
        """Las entradas de la tabla, cada una con su pedido de ejemplo (de la foto)."""
        for patron in _tabla().PORTAL_LECTURA:
            self.assertIsNotNone(self.ejemplos[patron], "la tabla tiene una entrada sin pedido de la foto: %s" % patron)
            yield patron, self.ejemplos[patron]

    def test_CP1_la_foto_tiene_su_sha256(self):
        bytes_foto = (CARPETA / "portal_lectura.json").read_bytes()
        sha_guardado = (CARPETA / "SHA256_portal").read_text(encoding="utf-8").split()[0]
        self.assertEqual(hashlib.sha256(bytes_foto).hexdigest(), sha_guardado)

    def test_CP2_la_tabla_y_la_foto_cubren_lo_mismo_y_todo_es_200(self):
        tabla = _tabla().PORTAL_LECTURA
        for patron in tabla:
            self.assertIsNotNone(self.ejemplos[patron], "entrada de la tabla sin pedido de la foto: %s" % patron)
        for pedido in self.foto["pedidos"]:
            self.assertTrue(any(re.fullmatch(p, pedido["ruta"]) for p in tabla), "pedido de la foto sin entrada: %s" % pedido["ruta"])
        # C2: 200, salvo la caída (502, con su doble propio) y el pedido de «no existe» (404). Los códigos los fija el generador.
        for pedido in self.foto["pedidos"]:
            with self.subTest(nombre=pedido["nombre"]):
                if pedido["caidas"]:
                    self.assertEqual(pedido["status"], 502, "C2: una caída de NocoDB es un 502")
                elif pedido["nombre"].endswith("_no_existe"):
                    self.assertEqual(pedido["status"], 404, "C2: una ficha que no existe es un 404")
                else:
                    self.assertEqual(pedido["status"], 200, "C2: la foto tiene un caso que no es 200")

    def test_CP5_la_foto_tiene_un_pedido_por_cada_escenario_del_generador(self):
        """El generador (`generador.RUTAS`) es la fuente de los escenarios. Si la foto pierde uno, esto da rojo aunque se recalcule el
        SHA (CP1 no lo ve)."""
        esperados = sorted(nombre for nombre, *_resto in generador.RUTAS)
        self.assertEqual(sorted(p["nombre"] for p in self.foto["pedidos"]), esperados)

    def test_CP3_tabla_mas_fuera_son_las_rutas_que_la_app_contesta(self):
        tabla = set(_tabla().PORTAL_LECTURA)
        fuera = _tabla().PORTAL_FUERA_DEL_PROGRAMA
        self.assertEqual(tabla & set(fuera), set(), "una ruta está en la tabla y también fuera")
        for patron, motivo in fuera.items():
            self.assertTrue(motivo.strip(), "una salida sin motivo: %s" % patron)
        app = {r["patron"] for r in self.foto["rutas_de_la_app"]}
        self.assertEqual(tabla | set(fuera), app)

    def test_P2_cada_pedido_de_la_foto_es_igual_a_la_app(self):
        # Los pedidos con caída van en P4 (su propio doble). Aquí, todos los demás, contra este servidor.
        for pedido in self.foto["pedidos"]:
            if pedido["caidas"]:
                continue
            with self.subTest(ruta=_url(pedido)):
                codigo, cuerpo = _pedir(self.puerto, _url(pedido), _cabeceras())
                self.assertEqual(codigo, pedido["status"])
                self.assertEqual(cuerpo, pedido["respuesta"])
        self.assertEqual(self.doble.no_get, [], "el doble recibió algo que no es GET")
        self.assertEqual(self.doble.errores, [], "el doble recibió una lectura que no conoce")

    def test_P4_las_caidas_de_nocodb_dan_lo_que_dio_la_app(self):
        """Cada pedido con `caidas` corre en SU servidor y doble, con esas caídas (la base no contesta a GET): el mismo código y el mismo
        cuerpo que la App, el doble contó la caída, y no recibió una lectura que no conoce."""
        con_caida = [p for p in self.foto["pedidos"] if p["caidas"]]
        self.assertTrue(con_caida, "la foto no tiene ningún pedido con caída")
        for pedido in con_caida:
            with self.subTest(nombre=pedido["nombre"]):
                proceso, puerto, doble = ctr._arrancar(dict(_entorno_comun(), PERSONAS_PORTAL_LLAVE=LLAVE_PORTAL),
                                                       caidas=tuple(pedido["caidas"]))
                try:
                    codigo, cuerpo = _pedir(puerto, _url(pedido), _cabeceras())
                finally:
                    ctr._parar(proceso, doble)
                self.assertEqual((codigo, cuerpo), (pedido["status"], pedido["respuesta"]))
                self.assertGreater(doble.caidas_servidas, 0, "la caída no se usó: la App no leyó NocoDB")
                self.assertEqual(doble.errores, [], "el doble recibió una lectura que no conoce")

    def test_K1_sin_cabecera_de_llave_401_sin_leer(self):
        for patron, pedido in self._entradas():
            with self.subTest(patron=patron):
                codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), _cabeceras(llave=None)))
                self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K2_llave_vacia_401_sin_leer(self):
        for patron, pedido in self._entradas():
            with self.subTest(patron=patron):
                codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), _cabeceras(llave="")))
                self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K4_llaves_de_otros_grupos_en_su_propia_cabecera_401_sin_leer(self):
        # Cada llave ajena va en SU cabecera (la de su grupo), sin la del portal: el portal no la acepta.
        ajenas = [("X-Personas-Lectura-Llave", doble_mod.LLAVE_LECTURA),
                  ("X-Personas-Registro-Llave", ctr.LLAVE_REGISTRO),
                  ("X-Personas-Registro-Escritura-Llave", LLAVE_ESCRITURA)]
        for patron, pedido in self._entradas():
            for cabecera, valor in ajenas:
                with self.subTest(patron=patron, cabecera=cabecera):
                    cabeceras = {cabecera: valor, "X-Personas-Portal-Quien": QUIEN, "X-Personas-Portal-Tipo": "A"}
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), cabeceras))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K4b_llaves_de_otros_grupos_en_la_cabecera_del_portal_401_sin_leer(self):
        otras = [doble_mod.LLAVE_LECTURA, ctr.LLAVE_REGISTRO, LLAVE_ESCRITURA]
        for patron, pedido in self._entradas():
            for otra in otras:
                with self.subTest(patron=patron, otra=otra[:6]):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), _cabeceras(llave=otra)))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K5_llaves_casi_iguales_401_sin_leer(self):
        # Los espacios de los bordes no van: HTTP los quita de la cabecera antes de llegar al programa (medido: `" llave"` llega
        # igual que `"llave"`), así que no son una llave distinta.
        casi = [LLAVE_PORTAL + "x", LLAVE_PORTAL[:-1], LLAVE_PORTAL.upper()]
        for patron, pedido in self._entradas():
            for llave in casi:
                with self.subTest(patron=patron, llave=llave[-3:]):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), _cabeceras(llave=llave)))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))

    def test_K6_la_llave_del_portal_en_las_cabeceras_de_otras_rutas_401_sin_leer(self):
        # La llave del portal, en la cabecera que esas rutas miran, no abre: ni config ni una de Registro.
        ajenas = [("GET", "/api/servicio/personas/config", "X-Personas-Lectura-Llave"),
                  ("POST", "/api/servicio/personas/credito", "X-Personas-Registro-Llave")]
        for metodo, ruta, cabecera in ajenas:
            with self.subTest(ruta=ruta, cabecera=cabecera):
                antes = self.doble.lecturas
                codigo, cuerpo = _pedir(self.puerto, ruta, {cabecera: LLAVE_PORTAL}, metodo)
                self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))
                self.assertEqual(self.doble.lecturas, antes, "el servidor leyó NocoDB en un pedido que debía frenar")

    def test_I1_sin_identidad_o_con_tipo_ajeno_400_sin_leer(self):
        casos = [
            ("sin quien", _cabeceras(quien=None)),
            ("quien en blanco", _cabeceras(quien="   ")),
            ("sin tipo", _cabeceras(tipo=None)),
            ("tipo de otra puerta", _cabeceras(tipo="B")),
        ]
        for patron, pedido in self._entradas():
            for nombre, cabeceras in casos:
                with self.subTest(patron=patron, caso=nombre):
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), cabeceras))
                    self.assertEqual((codigo, cuerpo), (400, ERROR_IDENTIDAD))

    def test_I2_la_identidad_del_navegador_no_decide_sin_la_llave_del_portal(self):
        for patron, pedido in self._entradas():
            for llave in [doble_mod.LLAVE_LECTURA, None]:
                with self.subTest(patron=patron, llave=None if llave is None else "otra"):
                    cabeceras = _cabeceras(llave=llave, quien="Quien sea", tipo="A")
                    codigo, cuerpo = self._sin_leer_nocodb(lambda: _pedir(self.puerto, _url(pedido), cabeceras))
                    self.assertEqual((codigo, cuerpo), (401, ERROR_LLAVE))


class ElPortalSinLlaveEnLaVariable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ejemplos = _ejemplos()
        cls.proceso, cls.puerto, cls.doble = ctr._arrancar(dict(_entorno_comun(), PERSONAS_PORTAL_LLAVE=""))

    @classmethod
    def tearDownClass(cls):
        ctr._parar(cls.proceso, cls.doble)

    def test_K3_variable_vacia_no_acepta_ninguna_llave_y_no_lee(self):
        pruebas = [("cabecera vacia", ""), ("sin cabecera", None), ("llave de Mercadeo", doble_mod.LLAVE_LECTURA),
                   ("llave cualquiera", "llave-cualquiera")]
        for patron in _tabla().PORTAL_LECTURA:
            pedido = self.ejemplos[patron]
            self.assertIsNotNone(pedido)
            for nombre, llave in pruebas:
                with self.subTest(patron=patron, caso=nombre):
                    antes = self.doble.lecturas
                    codigo, cuerpo = _pedir(self.puerto, _url(pedido), _cabeceras(llave=llave))
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
                nueva = [p for p in _foto()["pedidos"] if p["ruta"] == "/api/portal-personas/nueva"][0]
                self.assertEqual((codigo, cuerpo), (nueva["status"], nueva["respuesta"]))
        finally:
            servidor_http.shutdown()
            servidor_http.server_close()
            doble.parar()


if __name__ == "__main__":
    unittest.main()
