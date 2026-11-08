# -*- coding: utf-8 -*-
"""El servidor del repo (`servidor.py`) contesta las rutas de lectura de Personas igual que la App de registro en `0b48b5d`.

La foto de referencia es `contrato_dorado/contrato.json` (sacada de la App). Esta prueba:
  R1  arranca `servidor.py` como proceso aparte, con el doble de NocoDB de `tests/doble_nocodb.py` (127.0.0.1), y pide los
      16 pedidos de la foto: el código y el cuerpo de cada respuesta tienen que ser IGUALES a los de la foto.
  R2  el doble no recibió más que GET, y no hubo ninguna lectura que no conociera (ni pedidos mal formados).
  R3a con `PERSONAS_REGISTRO_LLAVE` VACÍA, las cuatro rutas de Registro dan 401 sin cabecera, con cabecera vacía y con la
      llave de Mercadeo: y no se lee NocoDB.
  R3b con la variable llena, las cuatro rutas de Registro dan 401 sin cabecera, con una llave mala y con la llave de
      Mercadeo puesta en la cabecera de Registro; y no se lee NocoDB.
  R3c con la llave de Registro, las cuatro rutas contestan (no 401); credito, buscar y creditos-vivos dan 200 (el doble sabe `gt`
      desde el paso 5c, parte 2).
  L1  con `PERSONAS_LECTURA_LLAVE` vacía, TODAS las rutas de Mercadeo (sacadas de `servidor.LECTURA_POST`) y `config` dan 401
      sin cabecera y con cabecera vacía, y no se lee NocoDB.

Lo que NO ve (declarado): la foto solo se verifica contra su hash (`test_contrato_dorado.py`, CD1). Si alguien cambia un cuerpo
y recalcula el SHA256, esta prueba sigue verde mientras la foto y el servidor coincidan. Quien rehace la foto lo hace desde la
App de registro (`contrato_dorado/generar.py` de la App), no desde este repo. Mutación `m1c` de la sala: aceptada, declarada.
Las cuatro rutas de Registro no tienen foto propia: R3 y R3c miran la llave y el código, no el cuerpo de la respuesta.
"""
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import doble_nocodb as doble_mod  # noqa: E402

CONTRATO = RAIZ / "contrato_dorado" / "contrato.json"
LLAVE_REGISTRO = "llave-de-prueba-registro-personas"
RUTAS_REGISTRO = [("credito", "/api/servicio/personas/credito", {"telefono": "18097770001"}),
                  ("buscar", "/api/servicio/personas/buscar", {"q": "prueba", "limite": 3}),
                  ("bandeja", "/api/servicio/personas/bandeja",
                   {"estados": ["contado"], "campos": "Id,estado", "pagina": 5, "tope": 5, "cursor": 0}),
                  ("creditos_vivos", "/api/servicio/personas/creditos-vivos", {})]


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _arrancar(extra_entorno=None, caidas=()):
    """Arranca `servidor.py` como proceso aparte contra un doble nuevo. Devuelve (proceso, puerto, doble). `caidas`: métodos del doble
    que contestan 500 (la base no contesta); por defecto ninguno."""
    doble = doble_mod.Doble(caidas=caidas)
    url_doble = doble.arrancar()
    puerto = _puerto_libre()
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "HOST": "127.0.0.1", "PORT": str(puerto),
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
        "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
        "PERSONAS_REGISTRO_LLAVE": LLAVE_REGISTRO,
        "NOCODB_T_PERSONAS_ANOTACIONES": doble_mod.TABLA_ANOTACIONES,
    }
    entorno.update(extra_entorno or {})
    proceso = subprocess.Popen([sys.executable, "-B", str(RAIZ / "servidor.py")], cwd=str(RAIZ), env=entorno,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if proceso.poll() is not None:
            break
        try:
            # Listo = contesta CUALQUIER código HTTP (con la variable de Mercadeo vacía, `config` da 401 y eso también es estar arriba).
            urllib.request.urlopen("http://127.0.0.1:%d/api/servicio/personas/config" % puerto, timeout=5).close()
            return proceso, puerto, doble
        except urllib.error.HTTPError:
            return proceso, puerto, doble
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("el servidor del repo no levantó")


def _parar(proceso, doble):
    if proceso.poll() is None:
        proceso.terminate()
        proceso.wait(timeout=10)
    doble.parar()


def _pedir_registro(puerto, ruta, cuerpo, valor_cabecera):
    """POST con la cabecera de Registro (`X-Personas-Registro-Llave`). `valor_cabecera=None` no la manda."""
    datos = json.dumps(cuerpo).encode()
    cabeceras = {"Content-Type": "application/json"}
    if valor_cabecera is not None:
        cabeceras["X-Personas-Registro-Llave"] = valor_cabecera
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), data=datos, method="POST", headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


class ElServidorContesteComoLaApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foto = json.loads(CONTRATO.read_text(encoding="utf-8"))["rutas"]
        cls.proceso, cls.puerto, cls.doble = _arrancar()

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)

    def test_R1_los_dieciseis_pedidos_dan_lo_mismo_que_la_foto(self):
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
    """Con la variable de Registro llena."""

    @classmethod
    def setUpClass(cls):
        cls.proceso, cls.puerto, cls.doble = _arrancar()

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)

    def test_R3b_sin_llave_con_llave_mala_o_con_la_de_mercadeo_401_y_no_se_lee(self):
        for nombre, ruta, cuerpo in RUTAS_REGISTRO:
            for cabecera in (None, "llave-mala", doble_mod.LLAVE_LECTURA):
                antes = self.doble.lecturas
                codigo, _ = _pedir_registro(self.puerto, ruta, cuerpo, cabecera)
                self.assertEqual(codigo, 401, "%s con cabecera %r" % (nombre, cabecera and "(dada)"))
                self.assertEqual(self.doble.lecturas, antes, nombre + ": una ruta sin llave leyó NocoDB")

    def test_R3c_con_la_llave_de_registro_las_rutas_contestan(self):
        for nombre, ruta, cuerpo in RUTAS_REGISTRO:
            codigo, _ = _pedir_registro(self.puerto, ruta, cuerpo, LLAVE_REGISTRO)
            self.assertNotEqual(codigo, 401, nombre)
        self.assertEqual(_pedir_registro(self.puerto, RUTAS_REGISTRO[0][1], RUTAS_REGISTRO[0][2], LLAVE_REGISTRO)[0], 200)
        self.assertEqual(_pedir_registro(self.puerto, RUTAS_REGISTRO[1][1], RUTAS_REGISTRO[1][2], LLAVE_REGISTRO)[0], 200)
        # creditos-vivos pide `credito > 0` (operador `gt`). Hasta el paso 5c, parte 2, el doble no sabía `gt` y esta prueba afirmaba
        # un 502 (límite del doble). Ahora el doble compara números (`gt`, `gte`, `lt`, `lte`) y la ruta contesta 200.
        self.assertEqual(_pedir_registro(self.puerto, RUTAS_REGISTRO[3][1], RUTAS_REGISTRO[3][2], LLAVE_REGISTRO)[0], 200)


class ElRegistroConLaVariableVacia(unittest.TestCase):
    """Con `PERSONAS_REGISTRO_LLAVE` vacía en el servidor: ninguna llave abre las rutas de Registro."""

    @classmethod
    def setUpClass(cls):
        cls.proceso, cls.puerto, cls.doble = _arrancar({"PERSONAS_REGISTRO_LLAVE": ""})

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)

    def test_R3a_variable_vacia_401_con_cabecera_ausente_vacia_o_la_de_mercadeo_sin_leer(self):
        for nombre, ruta, cuerpo in RUTAS_REGISTRO:
            for cabecera in (None, "", doble_mod.LLAVE_LECTURA):
                antes = self.doble.lecturas
                codigo, _ = _pedir_registro(self.puerto, ruta, cuerpo, cabecera)
                self.assertEqual(codigo, 401, nombre)
                self.assertEqual(self.doble.lecturas, antes, nombre + ": leyó NocoDB con la variable vacía")


def _pedir_lectura(puerto, metodo, ruta, cuerpo, valor_cabecera):
    """Pedido con la cabecera de Mercadeo (`X-Personas-Lectura-Llave`). `valor_cabecera=None` no la manda."""
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    cabeceras = {"Content-Type": "application/json"} if datos is not None else {}
    if valor_cabecera is not None:
        cabeceras["X-Personas-Lectura-Llave"] = valor_cabecera
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class ElLecturaConLaVariableVacia(unittest.TestCase):
    """Con `PERSONAS_LECTURA_LLAVE` vacía en el servidor: ninguna ruta de Mercadeo ni `config` se abre sin cabecera o con cabecera vacía.

    Frontera: no prueba una cabecera NO vacía con la variable vacía; eso lo cubre la guarda de llave vacía del servidor
    (`lucy_llave_valida` en `servidor.py`).
    """

    @classmethod
    def setUpClass(cls):
        cls.proceso, cls.puerto, cls.doble = _arrancar({"PERSONAS_LECTURA_LLAVE": ""})

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)

    def test_L1_todas_las_rutas_de_mercadeo_y_config_401_sin_cabecera_o_vacia_sin_leer(self):
        # La lista sale de la tabla REAL del servidor (`LECTURA_POST`), no de una lista tecleada aquí.
        import servidor  # importar no arranca nada; solo lee la tabla de rutas
        mercadeo = sorted(ruta for ruta, nombre in servidor.LECTURA_POST.items() if nombre not in servidor.REGISTRO_NOMBRES)
        self.assertEqual(len(mercadeo), 4, "Mercadeo debe tener cuatro rutas POST (identidad, fichas, pagina, anotaciones)")
        for cabecera in (None, ""):
            for ruta in mercadeo:
                antes = self.doble.lecturas
                self.assertEqual(_pedir_lectura(self.puerto, "POST", ruta, {}, cabecera), 401,
                                 "%s con cabecera %r" % (ruta, cabecera))
                self.assertEqual(self.doble.lecturas, antes, ruta + ": leyó NocoDB con la variable de Mercadeo vacía")
            antes = self.doble.lecturas
            self.assertEqual(_pedir_lectura(self.puerto, "GET", servidor.CONFIG_RUTA, None, cabecera), 401,
                             "config con cabecera %r" % cabecera)
            self.assertEqual(self.doble.lecturas, antes, "config leyó NocoDB con la variable de Mercadeo vacía")


if __name__ == "__main__":
    unittest.main()
