# -*- coding: utf-8 -*-
"""El diagnóstico del cálculo (P11, Tiempos): la línea `[CALCULAR]` por cada `POST /calcular/`, el `GET /healthz` y la línea
`[PUERTA-FICHAS]` del modo que solo cuenta (`servidor.py`, `personas.py`).

Qué garantiza y con qué prueba:
  T1  `GET /healthz` contesta 200 con un servidor real, y no llega ningún pedido al doble de NocoDB.
  T2  un `POST /calcular/<nombre>` sin cálculo (404) deja UNA línea `[CALCULAR]`, con `resultado=respuesta_escrita`
      (servidor real, proceso aparte, stdout a un archivo).
  T3  la línea `[CALCULAR]` tiene solo la forma `ruta=/calcular/<nombre> codigo=N ms=N resultado=R`: ni la identidad, ni los valores del
      cuerpo, ni ids. Se mira con una expresión regular estricta sobre cada línea, y el pedido lleva a propósito la identidad y un
      valor de prueba en el cuerpo que no deben aparecer.
  T4  con un servidor real en un hilo del proceso de la prueba: el cliente cierra con RST cuando el cálculo ya empezó, y la línea dice
      `resultado=cliente_cerro`. Es el cierre de la conexión por el lado del cliente (no un doble del socket).
  T5  los rechazos también dejan su línea: 401 (llave mala) y 400 (sin identidad), con su código.
  T6  la línea `[PUERTA-FICHAS]` en modo cuenta dice `modo=solo_cuenta` y `accion=contaria_<accion>`, nunca `accion=completada`;
      en modo escribir dice `modo=escribir` y la acción tal cual. Se prueba la función que imprime (`personas._puerta_registrar`).

Lo que NO cubre: un cálculo real de check-in por `/calcular/` escribiendo la línea `[PUERTA-FICHAS]` (la prueba T6 llama a la
función que imprime, con un resultado armado a mano).
"""
import contextlib
import io
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doble_escrituras  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`_puerto_libre`, `_esperar_arriba`, `ENTORNO_BASE`, `ENTORNO_MINIMO`)
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import reloj  # noqa: E402
import servidor  # noqa: E402

LLAVE_CUENTA = "llave-de-prueba-del-calculo"          # valor de PRUEBA: solo lo usa el harness
QUIEN = "Ana Pérez"                                    # identidad con tilde (UTF-8 dentro de latin-1, como la App)
NOTA = "nota de prueba para el diagnostico"           # valor del cuerpo: no debe aparecer en ninguna línea de registro
CUERPO = {"id": 2, "base": {"notas": ""}, "cambios": {"notas": NOTA}}
NOMBRE = "nombre_sin_calculo"                          # 404 sin tocar NocoDB
RUTA = "/calcular/" + NOMBRE
FORMA = re.compile(r"^\[CALCULAR\] ruta=/calcular/<nombre> codigo=(\d{3}|-) ms=\d+ resultado=(respuesta_escrita|cliente_cerro|sin_respuesta)$")


def _cabeceras(llave=LLAVE_CUENTA, quien=QUIEN):
    cab = {"Content-Type": "application/json"}
    if llave is not None:
        cab["X-Personas-Cuenta-Llave"] = llave
    if quien is not None:
        cab["X-Personas-Cuenta-Quien"] = quien.encode("utf-8").decode("latin-1")
    return cab


class ProcesoReal:
    """El programa real (`servidor.py`, como proceso aparte) contra el doble de NocoDB. La salida va a un archivo para leer sus líneas."""

    def __enter__(self):
        self.doble = doble_escrituras.DobleEscrituras()
        url_doble = self.doble.arrancar()
        self.puerto = esc._puerto_libre()
        self.dir = tempfile.TemporaryDirectory()
        self.salida = Path(self.dir.name) / "salida.txt"
        entorno = dict(esc.ENTORNO_MINIMO)
        entorno.update(esc.ENTORNO_BASE)
        entorno.update({"PERSONAS_CUENTA_LLAVE": LLAVE_CUENTA, "HOST": "127.0.0.1", "PORT": str(self.puerto),
                        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba"})
        self.archivo = open(self.salida, "w", encoding="utf-8")
        self.proceso = subprocess.Popen(reloj.comando_programa(), cwd=str(RAIZ), env=entorno, stdin=subprocess.DEVNULL,
                                        stdout=self.archivo, stderr=subprocess.STDOUT)
        esc._esperar_arriba(self.puerto, self.proceso)
        return self

    def __exit__(self, *_):
        self.proceso.terminate()
        self.proceso.wait(timeout=10)
        self.archivo.close()
        self.doble.parar()
        self.dir.cleanup()

    def pedir(self, metodo, ruta, cabeceras=None, cuerpo=CUERPO):
        self.doble.pedidos.clear()
        datos = json.dumps(cuerpo).encode("utf-8") if metodo == "POST" else None
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.puerto, ruta), data=datos, method=metodo,
                                     headers=cabeceras or {})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def lineas_calcular(self):
        self.archivo.flush()
        return [l.rstrip("\n") for l in self.salida.read_text(encoding="utf-8").splitlines() if l.startswith("[CALCULAR]")]

    def salida_completa(self):
        self.archivo.flush()
        return self.salida.read_text(encoding="utf-8")


class RealesSalud(unittest.TestCase):
    """T1, T2, T3 y T5 contra el proceso real."""

    @classmethod
    def setUpClass(cls):
        cls.p = ProcesoReal().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.p.__exit__(None, None, None)

    def test_T1_healthz_200_sin_nocodb(self):
        codigo, cuerpo = self.p.pedir("GET", "/healthz")
        self.assertEqual(codigo, 200)
        self.assertEqual(self.p.doble.pedidos, [], "el healthz no puede tocar NocoDB")

    def test_T2_calcular_deja_una_linea_respuesta_escrita(self):
        antes = len(self.p.lineas_calcular())
        codigo, _ = self.p.pedir("POST", RUTA, _cabeceras())
        self.assertEqual(codigo, 404)
        nuevas = self.p.lineas_calcular()[antes:]
        self.assertEqual(len(nuevas), 1, nuevas)
        self.assertIn("codigo=404", nuevas[0])
        self.assertIn("resultado=respuesta_escrita", nuevas[0])

    def test_T3_la_linea_no_lleva_datos(self):
        self.p.pedir("POST", RUTA, _cabeceras())
        self.p.pedir("POST", RUTA, _cabeceras(llave="mala"))
        self.p.pedir("POST", RUTA, _cabeceras(quien=""))
        lineas = self.p.lineas_calcular()
        self.assertGreaterEqual(len(lineas), 3)
        for l in lineas:
            self.assertRegex(l, FORMA)
        texto = "\n".join(lineas)
        for dato in (QUIEN, "Ana", "Pérez", NOTA, "nota de prueba", LLAVE_CUENTA, "mala", "token-de-prueba"):
            self.assertNotIn(dato, texto, "un dato sale en el registro: %r" % dato)

    def test_T5_los_rechazos_dejan_su_linea(self):
        antes = len(self.p.lineas_calcular())
        self.assertEqual(self.p.pedir("POST", RUTA, _cabeceras(llave="mala"))[0], 401)
        self.assertEqual(self.p.pedir("POST", RUTA, _cabeceras(quien=""))[0], 400)
        nuevas = self.p.lineas_calcular()[antes:]
        self.assertEqual(len(nuevas), 2, nuevas)
        self.assertIn("codigo=401", nuevas[0])
        self.assertIn("codigo=400", nuevas[1])


class ClienteCierra(unittest.TestCase):
    """T4: un servidor real (el `Manejador` del programa) en un hilo; el cliente cierra con RST mientras el cálculo corre."""

    def test_T4_cliente_cerro(self):
        dentro, soltar, impreso = threading.Event(), threading.Event(), threading.Event()
        original_calcular = personas_cuenta.calcular
        original_registrar = servidor._registrar_calculo
        llave_antes = servidor.LLAVE_PERSONAS_CUENTA

        def calcular_lento(nombre, cuerpo, quien):
            dentro.set()
            soltar.wait(10)                       # el cliente ya se fue: la respuesta se escribe contra una conexión cerrada
            return 200, {"ok": True, "estado": "calculado", "escrituras": []}

        def registrar_y_avisar(*args):
            original_registrar(*args)
            impreso.set()

        personas_cuenta.calcular = calcular_lento
        servidor._registrar_calculo = registrar_y_avisar
        servidor.LLAVE_PERSONAS_CUENTA = LLAVE_CUENTA
        srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
        hilo = threading.Thread(target=srv.serve_forever, daemon=True)
        hilo.start()
        salida = io.StringIO()
        try:
            with contextlib.redirect_stdout(salida):
                cuerpo = json.dumps(CUERPO).encode("utf-8")
                peticion = ("POST %s HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
                            "X-Personas-Cuenta-Llave: %s\r\nX-Personas-Cuenta-Quien: prueba\r\n\r\n"
                            % (RUTA, len(cuerpo), LLAVE_CUENTA)).encode("ascii") + cuerpo
                s = socket.create_connection(("127.0.0.1", srv.server_address[1]))
                s.sendall(peticion)
                self.assertTrue(dentro.wait(10), "el cálculo no arrancó")
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                s.close()                          # RST: el servidor ya no tiene a quién responder
                time.sleep(0.3)
                soltar.set()
                self.assertTrue(impreso.wait(10), "no salió la línea del pedido")
        finally:
            personas_cuenta.calcular = original_calcular
            servidor._registrar_calculo = original_registrar
            servidor.LLAVE_PERSONAS_CUENTA = llave_antes
            srv.shutdown()
            srv.server_close()
        lineas = [l for l in salida.getvalue().splitlines() if l.startswith("[CALCULAR]")]
        self.assertEqual(len(lineas), 1, lineas)
        self.assertRegex(lineas[0], FORMA)
        self.assertIn("resultado=cliente_cerro", lineas[0])


class PuertaEnModoCuenta(unittest.TestCase):
    """T6: la función que imprime la línea `[PUERTA-FICHAS]` (la del programa, sin cambiarla)."""

    RESULTADO = {"estado": "aplicado", "motivo": None, "ficha_id": 7, "accion": "completada", "avisos": []}

    def _linea(self, solo_contar):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            personas._puerta_registrar("checkin", dict(self.RESULTADO), solo_contar=solo_contar)
        return buf.getvalue().strip()

    def test_T6_modo_cuenta_no_dice_completada(self):
        linea = self._linea(solo_contar=True)
        self.assertIn("modo=solo_cuenta", linea)
        self.assertIn("accion=contaria_completada", linea)
        self.assertNotIn("accion=completada", linea)

    def test_T6_modo_escribir_dice_completada(self):
        linea = self._linea(solo_contar=False)
        self.assertIn("modo=escribir", linea)
        self.assertIn("accion=completada", linea)
        self.assertNotIn("solo_cuenta", linea)


if __name__ == "__main__":
    unittest.main()
