# -*- coding: utf-8 -*-
"""El cálculo del modo que solo cuenta en el programa (P11-5): `POST /calcular/<nombre>` (`personas_cuenta.py`).

Qué garantiza y con qué prueba (servidor real del programa, como proceso, contra el doble de NocoDB; el doble recibe TODO pedido):
  C1  la llave de cálculo se mira ANTES del cuerpo y de NocoDB: ausente, mala, la de CADA otro grupo del programa (la lista sale de
      `servidor.py`, no se teclea), la del portal y la de Natalia incluidas, cabecera vacía, o variable vacía con cabecera buena:
      401 y cero pedidos. Con cuerpo roto y llave mala también 401.
  C2  sin identidad (cabecera ausente, vacía o solo espacios): 400 y cero pedidos.
  C3  un cuerpo que no es un objeto JSON (roto, vacío, una lista): 400 `pedido ilegible` y cero pedidos.
  C4  con llave, identidad y cuerpo buenos, un `<nombre>` SIN cálculo registrado contesta 404 `sin cálculo` y cero pedidos. (P11-6a
      registró el grupo (a): sus nombres ya no están en esta lista; los demás grupos siguen en 404 hasta registrarse.)
  C5  con variable vacía, ni la cabecera vacía ni una cabecera buena abren la ruta: 401 y cero pedidos.
  C6  `personas_cuenta.CALCULOS` tiene el grupo (a) de P11-6 (sus cinco nombres) y nada más. Cada grupo que se registre cambia esta prueba.
  C7  contrato con el cliente real de la App (`panel_reenvio.calcular_personas`, App `3ffe870`): corre en un proceso aparte, con la
      rama de la App que dice la variable `PERSONAS_APP_RAMA`. Sin esa variable C7 se SALTA: unittest muestra `OK (skipped=1)` y el
      motivo solo sale con `-v`. Por eso la suite se corre con `PERSONAS_APP_RAMA` apuntando a la App (`registro-trabajos/p11-cliente`)
      cuando se publica, y así C7 corre de verdad. Nada de la App se toca: solo se importa su `panel_reenvio.py`.
La cuenta de pedidos la lleva el doble (`DobleEscrituras.pedidos`): cuenta los pedidos HTTP a NocoDB, de cualquier método, no solo las
escrituras. No cuenta otras escrituras (archivos, procesos).
"""
import copy
import json
import os
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doble_escrituras  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`_puerto_libre`, `_esperar_arriba`, `ENTORNO_BASE`, `ENTORNO_MINIMO`)
import personas_cuenta  # noqa: E402
import reloj  # noqa: E402

RUTA = "/calcular/%s"
CABECERA_LLAVE = "X-Personas-Cuenta-Llave"
CABECERA_QUIEN = "X-Personas-Cuenta-Quien"
VARIABLE_LLAVE = "PERSONAS_CUENTA_LLAVE"
LLAVE_CUENTA = "llave-de-prueba-del-calculo"        # valor de PRUEBA: solo lo usa el harness
QUIEN = "Ana Pérez"                                  # con tilde: como la manda la App (UTF-8 dentro de latin-1)
CUERPO = {"id": 2, "base": {"notas": ""}, "cambios": {"notas": "nota de prueba"}}
ERROR_LLAVE = {"error": "llave de servicio inválida"}
ERROR_IDENTIDAD = {"error": "identidad de cálculo ausente (X-Personas-Cuenta-Quien)"}
ERROR_ILEGIBLE = {"error": "pedido ilegible. No se calculó nada."}
ERROR_SIN_CALCULO = {"error": "sin cálculo para esa escritura"}


def grupos_de_llave():
    """Las variables de llave del programa, sacadas de `servidor.py` (no tecleadas). Cada una es la llave de un grupo."""
    fuente = (RAIZ / "servidor.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'os\.environ\.get\("(PERSONAS_[A-Z_]*LLAVE)"', fuente)))


class Servidor:
    """El servidor real del programa (`reloj.comando_programa`, con el día fijado) contra el doble de NocoDB. Cada grupo de llave
    tiene un valor de prueba distinto, y `PERSONAS_CUENTA_LLAVE` el de este módulo, salvo que `extra` diga otra cosa."""

    def __init__(self, extra=None, tablas=None):
        self.extra = dict(extra or {})
        self.tablas = dict(tablas or {})                 # tablas del doble que la prueba necesita (p. ej. la bandeja de la entrada)

    def __enter__(self):
        self.doble = doble_escrituras.DobleEscrituras()
        for tabla, filas in self.tablas.items():
            self.doble.tablas[tabla] = copy.deepcopy(filas)
        url_doble = self.doble.arrancar()
        self.puerto = esc._puerto_libre()
        self.llaves = {nombre: "llave-de-prueba-" + nombre.lower() for nombre in grupos_de_llave()}
        self.llaves[VARIABLE_LLAVE] = LLAVE_CUENTA
        entorno = dict(esc.ENTORNO_MINIMO)
        entorno.update(esc.ENTORNO_BASE)
        entorno.update(self.llaves)
        entorno.update({"HOST": "127.0.0.1", "PORT": str(self.puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                        "APP_PIN": "pin-de-prueba"})
        entorno.update(self.extra)
        self.proceso = subprocess.Popen(reloj.comando_programa(), cwd=str(RAIZ), env=entorno, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        esc._esperar_arriba(self.puerto, self.proceso)
        return self

    def __exit__(self, *_):
        self.proceso.terminate()
        self.proceso.wait(timeout=10)
        self.doble.parar()

    def pedir(self, ruta, crudo=None, cuerpo=CUERPO, cabeceras=None):
        """Un pedido `POST` al programa. Devuelve `(codigo, respuesta)`. Los pedidos que llegaron al doble van en `self.doble.pedidos`."""
        self.doble.pedidos.clear()
        datos = crudo.encode("utf-8") if crudo is not None else json.dumps(cuerpo).encode("utf-8")
        cab = {"Content-Type": "application/json"}
        cab.update(cabeceras or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.puerto, ruta), data=datos, method="POST", headers=cab)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                codigo, bruto = r.status, r.read()
        except urllib.error.HTTPError as e:
            codigo, bruto = e.code, e.read()
        return codigo, json.loads(bruto.decode("utf-8"))

    def buena(self):
        """Las cabeceras de un pedido bueno: llave de cálculo e identidad (la identidad en UTF-8 dentro de latin-1, como la App)."""
        return {CABECERA_LLAVE: self.llaves[VARIABLE_LLAVE], CABECERA_QUIEN: QUIEN.encode("utf-8").decode("latin-1")}


def con_cabeceras(base, **cambios):
    cab = dict(base)
    cab.update(cambios)
    return cab


class Guardas(unittest.TestCase):
    """C1, C2, C3 y C5 (las guardas de llave e identidad, y el cuerpo, todas antes de NocoDB)."""

    @classmethod
    def setUpClass(cls):
        cls.s = Servidor().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.s.__exit__(None, None, None)

    def test_C1_la_llave_se_mira_antes_de_nocodb(self):
        buena = self.s.buena()
        casos = [("sin_cabecera", {k: v for k, v in buena.items() if k != CABECERA_LLAVE}),
                 ("mala", con_cabeceras(buena, **{CABECERA_LLAVE: "llave-equivocada-de-prueba"})),
                 ("vacia", con_cabeceras(buena, **{CABECERA_LLAVE: ""})),
                 ("del_portal", con_cabeceras(buena, **{CABECERA_LLAVE: self.s.llaves["PERSONAS_PORTAL_LLAVE"]})),
                 ("de_natalia", con_cabeceras(buena, **{CABECERA_LLAVE: self.s.llaves["PERSONAS_NATALIA_LLAVE"]}))]
        for grupo in grupos_de_llave():
            if grupo != VARIABLE_LLAVE:
                casos.append(("de_" + grupo, con_cabeceras(buena, **{CABECERA_LLAVE: self.s.llaves[grupo]})))
        for nombre, cab in casos:
            with self.subTest(caso=nombre):
                codigo, resp = self.s.pedir(RUTA % "crear", cabeceras=cab)
                self.assertEqual((codigo, resp), (401, ERROR_LLAVE))
                self.assertEqual(self.s.doble.pedidos, [], "llegó a NocoDB sin la llave de cálculo")

    def test_C1b_con_cuerpo_roto_y_llave_mala_tambien_401(self):
        cab = con_cabeceras(self.s.buena(), **{CABECERA_LLAVE: "llave-equivocada-de-prueba"})
        codigo, resp = self.s.pedir(RUTA % "crear", crudo="{no es json", cabeceras=cab)
        self.assertEqual((codigo, resp), (401, ERROR_LLAVE))
        self.assertEqual(self.s.doble.pedidos, [])

    def test_C2_sin_identidad_400_y_nada_llega_a_nocodb(self):
        buena = self.s.buena()
        casos = [("sin_cabecera", {CABECERA_LLAVE: buena[CABECERA_LLAVE]}),
                 ("vacia", con_cabeceras(buena, **{CABECERA_QUIEN: ""})),
                 ("solo_espacios", con_cabeceras(buena, **{CABECERA_QUIEN: "   "}))]
        for nombre, cab in casos:
            with self.subTest(caso=nombre):
                codigo, resp = self.s.pedir(RUTA % "crear", cabeceras=cab)
                self.assertEqual((codigo, resp), (400, ERROR_IDENTIDAD))
                self.assertEqual(self.s.doble.pedidos, [], "llegó a NocoDB sin identidad")

    def test_C3_cuerpo_que_no_es_objeto_400_y_nada_llega_a_nocodb(self):
        for nombre, crudo in [("roto", "{no es json"), ("vacio", ""), ("lista", "[1, 2]")]:
            with self.subTest(caso=nombre):
                codigo, resp = self.s.pedir(RUTA % "crear", crudo=crudo, cabeceras=self.s.buena())
                self.assertEqual((codigo, resp), (400, ERROR_ILEGIBLE))
                self.assertEqual(self.s.doble.pedidos, [])


class SinCalculos(unittest.TestCase):
    """C4 y C5: con las guardas bien, todo nombre contesta 404 y nada llega a NocoDB."""

    @classmethod
    def setUpClass(cls):
        cls.s = Servidor().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.s.__exit__(None, None, None)

    def test_C4_todo_nombre_contesta_404_sin_calculo(self):
        for nombre in ["reabrir", "resolver", "unir", "borrar", "no_existe", "Crear", "a", "a/b", ""]:
            with self.subTest(nombre=nombre):
                codigo, resp = self.s.pedir(RUTA % nombre, cabeceras=self.s.buena())
                self.assertEqual((codigo, resp), (404, ERROR_SIN_CALCULO))
                self.assertEqual(self.s.doble.pedidos, [], "el cálculo sin registrar mandó un pedido a NocoDB")

    def test_C5_llave_vacia_en_la_variable_no_abre_la_ruta(self):
        with Servidor(extra={VARIABLE_LLAVE: ""}) as s:
            for cab in [s.buena(), con_cabeceras(s.buena(), **{CABECERA_LLAVE: ""})]:
                codigo, resp = s.pedir(RUTA % "crear", cabeceras=cab)
                self.assertEqual((codigo, resp), (401, ERROR_LLAVE))
                self.assertEqual(s.doble.pedidos, [])


class TablaDeCalculos(unittest.TestCase):
    """C6: la tabla de cálculos tiene los grupos (a), (b), (c) y (d) de P11-6 (cada grupo que se registre cambia esta prueba)."""

    def test_C6_la_tabla_tiene_los_grupos_a_b_c_y_d(self):
        self.assertEqual(set(personas_cuenta.CALCULOS),
                         {"crear", "editar", "crear_checkin", "editar_checkin", "editar_aprendizaje", "entrada", "cara",
                          "permiso", "baja", "foto"})


class ContratoConElClienteDeLaApp(unittest.TestCase):
    """C7: el cliente real de la App (`panel_reenvio.calcular_personas`) contra el servidor real del programa, en los CASOS DE ERROR
    (llave, sin cálculo, sin llave, identidad). El caso de éxito (200 y `coincide`) lo cubre K2 en `test_contrato_app_p11.py`."""

    CLIENTE = Path(__file__).resolve().parent / "cliente_app_calcular.py"

    def llamar(self, rama, entorno, nombre, cuerpo, quien):
        env = dict(esc.ENTORNO_MINIMO)
        env.update(entorno)
        salida = subprocess.run([sys.executable, "-B", str(self.CLIENTE), rama, nombre, json.dumps(cuerpo), quien], env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        return json.loads(salida.stdout.strip().splitlines()[-1])

    def test_C7_el_cliente_de_la_app_lee_cada_caso_como_debe(self):
        rama = os.environ.get("PERSONAS_APP_RAMA", "").strip()
        if not rama:
            self.skipTest("falta la variable PERSONAS_APP_RAMA: la rama de la App con panel_reenvio.py (App 3ffe870). "
                          "Sin ella no hay contrato con el cliente real.")
        with Servidor() as s:
            base = "http://127.0.0.1:%d" % s.puerto
            buena = {"PERSONAS_BASE": base, VARIABLE_LLAVE: LLAVE_CUENTA}
            fallo = {"calculado": False, "cuenta": None}
            casos = [
                ("sin_calculo_con_identidad_utf8", buena, "reabrir", CUERPO, QUIEN,   # «reabrir» no tiene cálculo (grupo (e) de P11-6, pendiente)
                 dict(fallo, motivo="sin_calculo")),
                ("llave_rechazada", dict(buena, **{VARIABLE_LLAVE: "llave-equivocada-de-prueba"}), "crear", CUERPO, QUIEN,
                 dict(fallo, motivo="llave_rechazada")),
                ("sin_llave_no_pide", dict(buena, **{VARIABLE_LLAVE: ""}), "crear", CUERPO, QUIEN,
                 dict(fallo, motivo="sin_llave")),
                ("sin_identidad_400", buena, "crear", CUERPO, "",
                 dict(fallo, motivo="otro_codigo")),
            ]
            for nombre, entorno, ruta, cuerpo, quien, esperado in casos:
                with self.subTest(caso=nombre):
                    self.assertEqual(self.llamar(rama, entorno, ruta, cuerpo, quien), esperado)
                    self.assertEqual(s.doble.pedidos, [], "el cliente llegó a NocoDB")


if __name__ == "__main__":
    unittest.main()
