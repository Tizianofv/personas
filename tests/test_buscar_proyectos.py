# -*- coding: utf-8 -*-
"""La búsqueda para la página de Proyectos (`POST /api/servicio/personas/proyectos/buscar`) de `servidor.py`.

Llave PROPIA de Proyectos (`PERSONAS_PROYECTOS_LLAVE`, cabecera `X-Personas-Proyectos-Llave`). Todo con el doble de NocoDB de
`tests/doble_nocodb.py` (127.0.0.1); el servidor es un proceso aparte, como en `test_contrato_rutas.py`.

  P1  con `PERSONAS_PROYECTOS_LLAVE` VACÍA: 503 con cualquier cabecera (también con la de Registro y con texto), y no se lee NocoDB.
  P2  con la variable llena: sin cabecera, vacía, mala, la de Registro y la de Lectura: 401, y no se lee NocoDB.
  P3  con la llave de Proyectos: 200, y cada fila trae SOLO `id` y `nombre`.
  P4  misma búsqueda: para cada texto y tope, los mismos ids en el mismo orden que `/api/servicio/personas/buscar` (con la llave de
      Registro). Las fichas unidas y las quitadas quedan fuera en las dos.
  P5  la pareja: la llave de Registro no abre la ruta de Proyectos (401), y la de Proyectos no abre `buscar`, `credito` ni
      `creditos-vivos` (401). Ninguna lee NocoDB con la llave equivocada.
  P6  la respuesta no lleva teléfono, correo, instagram ni notas, aunque la ficha los tenga. La misma búsqueda en `/buscar` sí los
      trae (así se ve que el dato estaba en la lectura).
  P7  un cuerpo que no es el de `buscar` (tipos malos, faltan campos, no es JSON): 400, y no se lee NocoDB.
  P8  UNA línea `[PROYECTOS-BUSCAR]` por pedido, también por los rechazados, y ninguna línea trae el texto buscado ni datos de la ficha.

Lo que NO ve (declarado): la regla de búsqueda se compara con `/buscar` del mismo programa, no con la de Lucy. Las diferencias con
Lucy (fichas unidas y quitadas, teléfono sin mirar si hay letras, texto mínimo de 2 caracteres, tope de 12, nombre sin respaldo) están
en el mapa y no se prueban contra Lucy aquí.
"""
import copy
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

import doble_nocodb as doble_mod  # noqa: E402

LLAVE_PROYECTOS = "llave-de-prueba-proyectos-personas"
LLAVE_REGISTRO = "llave-de-prueba-registro-personas"
RUTA_PROYECTOS = "/api/servicio/personas/proyectos/buscar"
RUTA_BUSCAR = "/api/servicio/personas/buscar"
CABECERA_PROYECTOS = "X-Personas-Proyectos-Llave"
CABECERA_REGISTRO = "X-Personas-Registro-Llave"
CABECERA_LECTURA = "X-Personas-Lectura-Llave"
ERROR_LLAVE = {"error": "llave de servicio inválida"}
SECRETOS = ("nota de prueba secreta", "18091112233", "p1@ejemplo.test", "@p1prueba", "18097770001")


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _arrancar(llave_proyectos, salida):
    """Arranca `servidor.py` contra un doble nuevo. `llave_proyectos` es el valor de `PERSONAS_PROYECTOS_LLAVE` ("" = vacía)."""
    doble = doble_mod.Doble()
    url_doble = doble.arrancar()
    puerto = _puerto_libre()
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "HOST": "127.0.0.1", "PORT": str(puerto),
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
        "PERSONAS_LECTURA_LLAVE": doble_mod.LLAVE_LECTURA,
        "PERSONAS_REGISTRO_LLAVE": LLAVE_REGISTRO,
        "PERSONAS_PROYECTOS_LLAVE": llave_proyectos,
        "NOCODB_T_PERSONAS_ANOTACIONES": doble_mod.TABLA_ANOTACIONES,
    }
    proceso = subprocess.Popen([sys.executable, "-B", str(RAIZ / "servidor.py")], cwd=str(RAIZ), env=entorno,
                               stdout=salida, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if proceso.poll() is not None:
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % puerto, timeout=5).close()
            return proceso, puerto, doble
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("el servidor del repo no levantó")


def _parar(proceso, doble):
    if proceso.poll() is None:
        proceso.terminate()
        proceso.wait(timeout=10)
    doble.parar()


def _post(puerto, ruta, cuerpo_crudo, cabeceras):
    """POST con los bytes tal cual y estas cabeceras. Devuelve (código, cuerpo en texto)."""
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), data=cuerpo_crudo, method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **cabeceras))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _buscar(puerto, ruta, q, limite=12, cabeceras=None):
    cuerpo = json.dumps({"q": q, "limite": limite}).encode("utf-8")
    codigo, texto = _post(puerto, ruta, cuerpo, cabeceras if cabeceras is not None else {})
    return codigo, json.loads(texto)


def _leer(salida):
    salida.seek(0)
    return salida.read().decode("utf-8")


class SinVariable(unittest.TestCase):
    """P1: con `PERSONAS_PROYECTOS_LLAVE` vacía, la ruta contesta 503 y no lee nada."""

    @classmethod
    def setUpClass(cls):
        cls.salida = tempfile.TemporaryFile()
        cls.proceso, cls.puerto, cls.doble = _arrancar("", cls.salida)

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)
        cls.salida.close()

    def test_P1_sin_variable_503_con_cualquier_cabecera_y_sin_leer(self):
        cabeceras = [{}, {CABECERA_PROYECTOS: ""}, {CABECERA_PROYECTOS: LLAVE_PROYECTOS}, {CABECERA_PROYECTOS: "x"},
                     {CABECERA_REGISTRO: LLAVE_REGISTRO}, {CABECERA_LECTURA: doble_mod.LLAVE_LECTURA}]
        for cabecera in cabeceras:
            antes = self.doble.lecturas
            codigo, cuerpo = _buscar(self.puerto, RUTA_PROYECTOS, "Persona de prueba", cabeceras=cabecera)
            self.assertEqual(codigo, 503, cabecera)
            self.assertIn("error", cuerpo)
            self.assertEqual(self.doble.lecturas, antes, "leyó NocoDB con la variable vacía: %r" % cabecera)


class ConVariable(unittest.TestCase):
    """P2 a P8, con la llave de Proyectos puesta. Una ficha (Id 1) lleva notas, teléfono secundario, instagram: solo para P6."""

    @classmethod
    def setUpClass(cls):
        cls.salida = tempfile.TemporaryFile()
        cls.guardado_tablas = copy.deepcopy(doble_mod.TABLAS)
        cls.guardado_meta = copy.deepcopy(doble_mod.COLUMNAS_META)
        filas = [dict(f) for f in doble_mod.PERSONAS]
        filas[0].update({"notas": SECRETOS[0], "telefono_2": "18091112233", "instagram": "@p1prueba"})
        doble_mod.TABLAS[doble_mod.T_PERSONAS] = filas
        doble_mod.COLUMNAS_META[doble_mod.T_PERSONAS] = doble_mod.COLUMNAS_META[doble_mod.T_PERSONAS] + [
            {"title": "notas", "uidt": "LongText", "system": False}]
        cls.proceso, cls.puerto, cls.doble = _arrancar(LLAVE_PROYECTOS, cls.salida)

    @classmethod
    def tearDownClass(cls):
        _parar(cls.proceso, cls.doble)
        cls.salida.close()
        doble_mod.TABLAS.clear()
        doble_mod.TABLAS.update(cls.guardado_tablas)
        doble_mod.COLUMNAS_META.clear()
        doble_mod.COLUMNAS_META.update(cls.guardado_meta)

    def test_P2_llave_mala_o_ausente_401_y_sin_leer(self):
        cabeceras = [{}, {CABECERA_PROYECTOS: ""}, {CABECERA_PROYECTOS: "llave-equivocada"},
                     {CABECERA_REGISTRO: LLAVE_REGISTRO}, {CABECERA_LECTURA: doble_mod.LLAVE_LECTURA},
                     {CABECERA_REGISTRO: LLAVE_PROYECTOS}]
        for cabecera in cabeceras:
            antes = self.doble.lecturas
            codigo, cuerpo = _buscar(self.puerto, RUTA_PROYECTOS, "Persona de prueba", cabeceras=cabecera)
            self.assertEqual(codigo, 401, cabecera)
            self.assertEqual(cuerpo, ERROR_LLAVE)
            self.assertEqual(self.doble.lecturas, antes, "leyó NocoDB sin la llave de Proyectos: %r" % cabecera)

    def test_P3_con_la_llave_200_y_solo_id_y_nombre(self):
        codigo, cuerpo = _buscar(self.puerto, RUTA_PROYECTOS, "Persona de prueba", cabeceras={CABECERA_PROYECTOS: LLAVE_PROYECTOS})
        self.assertEqual(codigo, 200)
        self.assertEqual(sorted(cuerpo), ["personas"])
        self.assertEqual(len(cuerpo["personas"]), 2, "las fichas 3 (quitada) y 4 (unida) no deben salir")
        for fila in cuerpo["personas"]:
            self.assertEqual(set(fila), {"id", "nombre"})
        self.assertEqual([f["id"] for f in cuerpo["personas"]], [1, 2])
        self.assertEqual([f["nombre"] for f in cuerpo["personas"]], ["Persona de prueba 1", "Persona de prueba 2"])

    def test_P4_mismos_ids_y_mismo_orden_que_buscar(self):
        textos = ["Persona de prueba", "prueba 2", "PERSONA", "18097770001", "1809777", "zz", "a", "  p1 ", "ejemplo", "nota"]
        for texto in textos:
            for limite in (1, 2, 12):
                _, de_registro = _buscar(self.puerto, RUTA_BUSCAR, texto, limite, cabeceras={CABECERA_REGISTRO: LLAVE_REGISTRO})
                _, de_proyectos = _buscar(self.puerto, RUTA_PROYECTOS, texto, limite, cabeceras={CABECERA_PROYECTOS: LLAVE_PROYECTOS})
                ids_registro = [f["Id"] for f in de_registro["personas"]]
                ids_proyectos = [f["id"] for f in de_proyectos["personas"]]
                self.assertEqual(ids_proyectos, ids_registro, "texto %r, limite %d" % (texto, limite))

    def test_P5_la_pareja_no_se_abre_entre_grupos(self):
        for ruta in (RUTA_PROYECTOS,):
            antes = self.doble.lecturas
            codigo, _ = _buscar(self.puerto, ruta, "Persona de prueba", cabeceras={CABECERA_REGISTRO: LLAVE_REGISTRO})
            self.assertEqual(codigo, 401, "la llave de Registro abrió " + ruta)
            self.assertEqual(self.doble.lecturas, antes)
        for ruta in (RUTA_BUSCAR, "/api/servicio/personas/credito", "/api/servicio/personas/creditos-vivos"):
            antes = self.doble.lecturas
            cuerpo = {"q": "Persona de prueba", "limite": 3} if ruta == RUTA_BUSCAR else (
                {"telefono": "18097770001"} if ruta.endswith("credito") else {})
            codigo, _ = _post(self.puerto, ruta, json.dumps(cuerpo).encode("utf-8"), {CABECERA_PROYECTOS: LLAVE_PROYECTOS})
            self.assertEqual(codigo, 401, "la llave de Proyectos abrió " + ruta)
            self.assertEqual(self.doble.lecturas, antes)
        codigo, _ = _buscar(self.puerto, RUTA_BUSCAR, "Persona de prueba", 3, cabeceras={CABECERA_REGISTRO: LLAVE_REGISTRO})
        self.assertEqual(codigo, 200, "la llave de Registro debe seguir abriendo /buscar")

    def test_P6_la_respuesta_no_trae_contacto_ni_notas(self):
        codigo, texto = _post(self.puerto, RUTA_PROYECTOS, json.dumps({"q": "Persona de prueba 1", "limite": 1}).encode("utf-8"),
                              {CABECERA_PROYECTOS: LLAVE_PROYECTOS})
        self.assertEqual(codigo, 200)
        self.assertIn("Persona de prueba 1", texto)
        for secreto in SECRETOS:
            self.assertNotIn(secreto, texto, "salió un dato de la ficha: " + secreto)
        # La misma ficha, en /buscar con la llave de Registro, SI trae esos datos: el dato estaba en la lectura.
        codigo_registro, con_datos = _post(self.puerto, RUTA_BUSCAR, json.dumps({"q": "Persona de prueba 1", "limite": 1}).encode("utf-8"),
                                           {CABECERA_REGISTRO: LLAVE_REGISTRO})
        self.assertEqual(codigo_registro, 200)
        for secreto in SECRETOS:
            self.assertIn(secreto, con_datos, "el dato no estaba en la lectura, la prueba no vale: " + secreto)

    def test_P7_cuerpo_malo_400_y_sin_leer(self):
        cuerpos = [b'{"q": 5, "limite": 3}', b'{"q": "ab"}', b'{"q": "ab", "limite": 0}', b'{"q": "ab", "limite": 3, "x": 1}',
                   b'{"q": "ab", "limite": true}', b"no es json", b"[]"]
        for crudo in cuerpos:
            antes = self.doble.lecturas
            codigo, _ = _post(self.puerto, RUTA_PROYECTOS, crudo, {CABECERA_PROYECTOS: LLAVE_PROYECTOS})
            self.assertEqual(codigo, 400, crudo)
            self.assertEqual(self.doble.lecturas, antes, "leyó NocoDB con un cuerpo malo: %r" % crudo)

    def test_P8_una_linea_de_registro_por_pedido_sin_datos(self):
        antes = _leer(self.salida).count("[PROYECTOS-BUSCAR]")
        _buscar(self.puerto, RUTA_PROYECTOS, "Persona de prueba 1", cabeceras={CABECERA_PROYECTOS: LLAVE_PROYECTOS})
        _buscar(self.puerto, RUTA_PROYECTOS, "Persona de prueba 1", cabeceras={CABECERA_PROYECTOS: "mala"})
        _post(self.puerto, RUTA_PROYECTOS, b'{"q": 1}', {CABECERA_PROYECTOS: LLAVE_PROYECTOS})
        lineas = [l for l in _leer(self.salida).splitlines() if "[PROYECTOS-BUSCAR]" in l]
        self.assertEqual(len(lineas) - antes, 3, "tres pedidos, tres líneas")
        for linea in lineas:
            for dato in ("Persona de prueba", "18097770001", "p1@ejemplo.test", "nota", "@p1prueba"):
                self.assertNotIn(dato, linea)
        self.assertIn("codigo=200", lineas[-3])
        self.assertIn("codigo=401", lineas[-2])
        self.assertIn("codigo=400", lineas[-1])


if __name__ == "__main__":
    unittest.main()
