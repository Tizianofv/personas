# -*- coding: utf-8 -*-
"""P11-proveedores: `editar` del cálculo para las DOS rutas de Proveedores que la App nombra igual (`personas_cuenta.RUTAS_ALTERNAS`):
`POST /api/proveedores/<id>/editar` y `POST /api/personas/<id>/precio-referencia` (`registro/server.py` 11547-11548).

Qué garantiza y con qué prueba:
  G1  PAREJA: para un cuerpo que la validación de la App acepta, lo que el cálculo dice es EXACTAMENTE lo que escribe la escritura del
      programa (`personas.editar_persona_portal`, la del portal), en el mismo doble de NocoDB. Clases: `ParejaConLaEscritura`.
  G2  CERO ESCRITURAS: el cálculo no manda ninguna escritura, ni con la base caída en lecturas ni en escrituras.
  G3  RECHAZOS: un cuerpo que la validación de la App rechaza da el mismo código y el mismo cuerpo, sin escribir. Los valores esperados
      de estos rechazos están FIJADOS A MANO (copiados de `registro/proveedores.py`, `proveedores_validar`).
  G4  CONTRATO CON LA APP (sólo con `PERSONAS_APP_RAMA`): las reglas, los textos y los patrones de ruta son los de la App (lectura de su
      código con `ast`), y para cada cuerpo de la tabla, la App en vivo (su `Handler.do_POST`, con sus guardas de sesión dadas por
      buenas, como en `tools/generar_portal_escrituras_de_la_app.py`) contesta lo mismo que el cálculo y escribe lo mismo.
      Sin `PERSONAS_APP_RAMA` la clase se SALTA (`skipped`), y la sala la corre con la variable puesta.
  G5  REGISTRO: `RUTAS_ALTERNAS["editar"]` tiene las dos rutas; `CALCULOS` y `RUTAS` no cambian (la prueba C6 lo vigila).

Lo que NO ve (declarado): la llave de envío y la firma del servidor (`clave_envio` y `firma_escrita` de la App: los pone o los exige la
ruta, antes de llegar a la validación; el cálculo no los repite). Las lecturas de NocoDB no se comparan, solo las escrituras.
"""
import base64
import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ / "tools"))
import base  # noqa: E402
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402
import generar_portal_escrituras_de_la_app as gen  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
from test_calcular_grupo_a import Corrida, forma_app  # noqa: E402

RAMA = os.environ.get("PERSONAS_APP_RAMA", "").strip()
QUIEN = "Prueba"
COLUMNA = esc.COLUMNA_PRECIO
METODOS_ESCRITURA = ("POST", "PATCH", "PUT", "DELETE")
RUTA_PROVEEDORES = "/api/proveedores/2/editar"
RUTA_PRECIO = "/api/personas/2/precio-referencia"
RUTAS = (RUTA_PROVEEDORES, RUTA_PRECIO)

# Textos fijados a mano, copiados de la App (`registro/personas.py` FICHA_ERROR_SIN_ESCRIBIR y `registro/proveedores.py`).
FIJO_SIN_ESCRIBIR = "No se guardó nada."
FIJO_SIN_COLUMNA = ("La base todavía no tiene la columna «Precio de referencia» en personas, o no es un número: "
                    "no se guardó nada. Avisa a Tiziano antes de repetirlo.")

# Cuerpos de la tabla. `valido` = la validación de la App los acepta (la escritura del portal los escribe o los rechaza igual que la App).
CUERPOS = {
    "precio_nuevo": {"id": 2, "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-1"},
    "precio_mismo_numero": {"id": 2, "base": {"Precio_referencia": "1500"}, "cambios": {"Precio_referencia": "1500.00"}, "clave_envio": "envio-p-2"},
    "precio_quitar": {"id": 2, "base": {"Precio_referencia": "1500"}, "cambios": {"Precio_referencia": ""}, "clave_envio": "envio-p-3"},
    "precio_negativo": {"id": 2, "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "-1500"}, "clave_envio": "envio-p-4"},
    "cambio_entre_medio": {"id": 2, "base": {"Precio_referencia": "900"}, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-5"},
    "precio_texto": {"id": 2, "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "abc"}, "clave_envio": "envio-p-6"},
    "sin_base": {"id": 2, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-7"},
    "campo_ajeno": {"id": 2, "base": {"nombre": "Persona de prueba 2"}, "cambios": {"nombre": "Otro"}, "clave_envio": "envio-p-8"},
    "campo_ajeno_y_precio": {"id": 2, "base": {"Precio_referencia": "", "nombre": "P"},
                             "cambios": {"Precio_referencia": "1500", "nombre": "Otro"}, "clave_envio": "envio-p-9"},
    "cambios_vacios": {"id": 2, "base": {}, "cambios": {}, "clave_envio": "envio-p-10"},
    "sin_cambios_clave": {"id": 2, "base": {"Precio_referencia": ""}, "clave_envio": "envio-p-11"},
    "cambios_no_son_objeto": {"id": 2, "base": {}, "cambios": "1500", "clave_envio": "envio-p-12"},
    "id_de_otra_ficha": {"id": 3, "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-13"},
    "id_texto": {"id": "2", "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-14"},
    "id_bool": {"id": True, "base": {"Precio_referencia": ""}, "cambios": {"Precio_referencia": "1500"}, "clave_envio": "envio-p-15"},
}
VALIDOS = ("precio_nuevo", "precio_mismo_numero", "precio_quitar", "precio_negativo", "cambio_entre_medio", "precio_texto", "sin_base")


def _cuerpo_del_calculo(ruta, cuerpo):
    """Lo que la App manda al cálculo: el mismo cuerpo más `ruta_de_la_escritura` (la dirección va en la ruta, igual que la escritura)."""
    return dict(cuerpo, ruta_de_la_escritura=ruta)


def _numero(texto):
    if texto in ("", None):
        return None
    try:
        return int(texto)
    except ValueError:
        return float(texto)


def _sembrar(doble, cuerpo):
    """Pone en la ficha 2 del doble el precio que dice la base del cuerpo (lo que la persona vio al abrir). Sin `base`, no toca nada."""
    base = cuerpo.get("base") if isinstance(cuerpo, dict) else None
    if not isinstance(base, dict) or "Precio_referencia" not in base:
        return
    for fila in doble.tablas[doble_nocodb.T_PERSONAS]:
        if fila["Id"] == 2:
            fila["Precio_referencia"] = _numero(base["Precio_referencia"])


class _Sembrada(Corrida):
    """Un `Corrida` cuyo precio de la ficha 2 es el de la base del cuerpo: así la validación y la comparación de la escritura ven lo mismo."""

    def __init__(self, cuerpo, **kw):
        super().__init__(**kw)
        self.cuerpo = cuerpo

    def __enter__(self):
        ahora = super().__enter__()
        _sembrar(self.doble, self.cuerpo)
        return ahora


def _escrituras_de(pedidos):
    """Las escrituras de una lista de pedidos del doble, en la forma del cálculo (`forma_app`): `{tabla, metodo, cuerpo}`."""
    salida = []
    for p in pedidos:
        if p["metodo"] in METODOS_ESCRITURA:
            tabla = p["ruta"].split("/api/v2/tables/")[1].split("/")[0]
            salida.append({"tabla": tabla, "metodo": p["metodo"], "cuerpo": p["cuerpo"]})
    return salida


def _escribir_en_el_programa(cuerpo):
    """La escritura de verdad del programa para la ficha 2: el `editar` del portal, con el cuerpo sin la ruta (igual que la ruta del portal)."""
    return personas.editar_persona_portal(2, dict(cuerpo, id=2), QUIEN, solo_contar=False)


class ParejaConLaEscritura(unittest.TestCase):
    """G1, G2, G3 (fijados a mano), G5. Corre el programa de verdad, sin la App."""

    def test_G1_pareja_con_la_escritura_del_portal_para_cada_cuerpo_valido(self):
        for nombre in VALIDOS:
            for ruta in RUTAS:
                with self.subTest(cuerpo=nombre, ruta=ruta):
                    with _Sembrada(CUERPOS[nombre], columnas_personas=[COLUMNA]) as w:
                        codigo_w, datos_w = _escribir_en_el_programa(CUERPOS[nombre])
                        escrituras_w = forma_app(_escrituras_de(w.doble.pedidos))
                    with _Sembrada(CUERPOS[nombre], columnas_personas=[COLUMNA]) as c:
                        codigo_c, datos_c = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS[nombre]), QUIEN)
                        escrituras_c = c.escrituras()
                    self.assertEqual(escrituras_c, [], "G2: el cálculo mandó escrituras")
                    self.assertEqual(codigo_c, codigo_w, "G1: código distinto")
                    if codigo_w == 200:
                        self.assertEqual(datos_c["escrituras"], escrituras_w, "G1: el cálculo no dice lo que la escritura mandó")
                    else:
                        self.assertEqual(datos_c, datos_w, "G1: rechazo distinto del de la escritura")

    def test_G1_el_precio_nuevo_es_un_patch_del_precio_y_nada_mas(self):
        """Lo que el cálculo dice para el precio nuevo, fijado a mano (el mismo `PATCH` que mide la App y el programa)."""
        with Corrida(columnas_personas=[COLUMNA]) as c:
            codigo, datos = personas_cuenta.calcular("editar", _cuerpo_del_calculo(RUTA_PRECIO, CUERPOS["precio_nuevo"]), QUIEN)
        self.assertEqual(codigo, 200)
        self.assertEqual(datos["escrituras"], [{"tabla": "personas", "metodo": "PATCH", "enlace": None,
                                                "valores": {"Precio_referencia": 1500}}])
        self.assertEqual(datos["sin_valor"], [])

    def test_G2_cero_escrituras_con_la_base_caida_en_escrituras_o_en_lecturas(self):
        for nombre in CUERPOS:
            for ruta in RUTAS:
                for caidas in (("POST", "PATCH", "PUT", "DELETE"), ("GET",)):
                    with self.subTest(cuerpo=nombre, ruta=ruta, caidas=caidas):
                        with _Sembrada(CUERPOS[nombre], columnas_personas=[COLUMNA], caidas=caidas) as c:
                            personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS[nombre]), QUIEN)
                            self.assertEqual(c.escrituras(), [], "el cálculo mandó una escritura")

    def test_G3_rechazos_fijados_a_mano(self):
        """Los rechazos de la validación, con el texto y el código que tienen en la App (copiados a mano, no leídos del cálculo)."""
        fijados = [
            ("campo_ajeno", 400, {"error": "esos campos no se pueden escribir desde aquí: nombre. " + FIJO_SIN_ESCRIBIR,
                                  "campos_rechazados": ["nombre"]}),
            ("campo_ajeno_y_precio", 400, {"error": "esos campos no se pueden escribir desde aquí: nombre. " + FIJO_SIN_ESCRIBIR,
                                           "campos_rechazados": ["nombre"]}),
            ("cambios_vacios", 400, {"error": "no hay nada que guardar. " + FIJO_SIN_ESCRIBIR}),
            ("sin_cambios_clave", 400, {"error": "no hay nada que guardar. " + FIJO_SIN_ESCRIBIR}),
            ("cambios_no_son_objeto", 400, {"error": "no hay nada que guardar. " + FIJO_SIN_ESCRIBIR}),
            ("id_de_otra_ficha", 400, {"error": "el número de la ficha no coincide con el de la dirección. " + FIJO_SIN_ESCRIBIR}),
            ("id_texto", 400, {"error": "el número de la ficha no coincide con el de la dirección. " + FIJO_SIN_ESCRIBIR}),
            ("id_bool", 400, {"error": "el número de la ficha no coincide con el de la dirección. " + FIJO_SIN_ESCRIBIR}),
        ]
        for nombre, codigo_esperado, cuerpo_esperado in fijados:
            for ruta in RUTAS:
                with self.subTest(cuerpo=nombre, ruta=ruta), _Sembrada(CUERPOS[nombre], columnas_personas=[COLUMNA]) as c:
                    codigo, datos = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS[nombre]), QUIEN)
                    self.assertEqual((codigo, datos), (codigo_esperado, cuerpo_esperado))
                    self.assertEqual(c.escrituras(), [])

    def test_G3_la_columna_que_no_es_numero_da_502_fijado_a_mano(self):
        for ruta in RUTAS:
            with self.subTest(ruta=ruta), Corrida(columnas_personas=()) as c:
                codigo, datos = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS["precio_nuevo"]), QUIEN)
                self.assertEqual((codigo, datos), (502, {"error": FIJO_SIN_COLUMNA, "estado": "no_guardado"}))
                self.assertEqual(c.escrituras(), [])

    def test_G5_registro_de_las_dos_rutas(self):
        self.assertEqual(len(personas_cuenta.RUTAS_ALTERNAS["editar"]), 2)
        for ruta in RUTAS:
            self.assertTrue(any(p.fullmatch(ruta) for p in personas_cuenta.RUTAS_ALTERNAS["editar"]), ruta)
        self.assertIsNone(personas_cuenta.RUTAS["editar"][1].fullmatch(RUTA_PRECIO), "la ruta del portal no debe cambiar")
        self.assertIn("editar", personas_cuenta.CALCULOS)

    def test_G5_una_ruta_ajena_con_el_nombre_editar_sigue_dando_400(self):
        for ruta in ("/api/proveedores/2/editar/extra", "/api/personas/2/precio-referencia/x", "/api/proveedores/2/borrar"):
            with self.subTest(ruta=ruta), Corrida(columnas_personas=[COLUMNA]) as c:
                codigo, _ = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS["precio_nuevo"]), QUIEN)
                self.assertEqual(codigo, 400)
                self.assertEqual(c.escrituras(), [])


# ---------- G4: la App en vivo (solo con PERSONAS_APP_RAMA) ----------

_PARCHE_EN_EL_DRIVER = [
    ("    def veredicto(self):\n",
     "    def entra_personas(self):\n        return True\n    def entra_proveedores(self):\n        return True\n"
     "    def _motivo_compras_proveedores(self):\n        return None\n    def veredicto(self):\n"),
    ("        self._quien = quien\n", "        self._quien = quien\n        self.command = 'POST'\n"),
    ("SimpleNamespace(entra=True, es_admin=True)", "SimpleNamespace(entra=True, es_admin=True, token=None)"),
]


def _driver_de_la_app():
    texto = gen.DRIVER
    for antes, despues in _PARCHE_EN_EL_DRIVER:
        assert texto.count(antes) == 1, antes
        texto = texto.replace(antes, despues)
    return texto


TOPE_APP_S = 240   # tope de UNA App en vivo (arranque y una petición). Pasado el tope, la prueba sale roja; nunca espera sin fin.


def _app(doble, ruta, cuerpo):
    """Una petición POST a la App (un proceso por petición, como la foto): `(codigo, respuesta, escrituras)`. Las escrituras son las del
    doble de la App en esa petición. Si la App no contesta en `TOPE_APP_S`, `subprocess.run` mata el proceso y aquí sale un AssertionError."""
    antes = len(doble.pedidos)
    entrada = json.dumps({"ruta": ruta, "quien": QUIEN, "metodo": "POST",
                          "datos_b64": base64.b64encode(json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")).decode("ascii")}) + "\n"
    entorno = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "NOCODB_BASE": doble.url, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba",
               "NOCODB_T_PERSONAS_ANOTACIONES": esc.ENTORNO_BASE["NOCODB_T_PERSONAS_ANOTACIONES"],
               "NOCODB_T_PERSONAS_QUITADAS": esc.ENTORNO_BASE["NOCODB_T_PERSONAS_QUITADAS"],
               "NOCODB_T_BANDEJA_PERSONAS": esc.ENTORNO_BASE["NOCODB_T_BANDEJA_PERSONAS"]}
    try:
        proceso = subprocess.run([sys.executable, "-I", "-B", "-c", _driver_de_la_app()], cwd=RAMA, env=entorno, input=entrada,
                                 capture_output=True, text=True, encoding="utf-8", timeout=TOPE_APP_S)
    except subprocess.TimeoutExpired:
        raise AssertionError("la App en vivo no contestó en %d s a %s (cuerpo %s); el proceso se mató" % (TOPE_APP_S, ruta, cuerpo))
    lineas = [l for l in proceso.stdout.splitlines() if l.startswith("PASO ")]
    if proceso.returncode != 0 or len(lineas) != 1:
        raise AssertionError("la App no contestó (%s) a %s: %s" % (proceso.returncode, ruta, proceso.stderr[-600:]))
    dato = json.loads(lineas[0][len("PASO "):])
    return dato["status"], esc.normalizar(dato["respuesta"]), _escrituras_de(doble.pedidos[antes:])


@unittest.skipUnless(RAMA, "falta PERSONAS_APP_RAMA: sin la App no hay contraste en vivo (G4)")
class ContratoConLaApp(unittest.TestCase):
    """G4: las constantes y los patrones de la App (lectura con `ast`), y la App en vivo contra el cálculo. Sin `subTest` en las
    pruebas en vivo: la primera diferencia o el primer tope corta la prueba, con el cuerpo y la ruta en el mensaje."""

    def _constantes(self, archivo):
        arbol = ast.parse((Path(RAMA) / archivo).read_text(encoding="utf-8"))
        salida = {}
        for nodo in arbol.body:
            if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
                try:
                    salida[nodo.targets[0].id] = ast.literal_eval(nodo.value)
                except ValueError:
                    pass
        return salida

    def test_reglas_y_textos_son_los_de_la_app(self):
        prov = self._constantes("proveedores.py")
        pers = self._constantes("personas.py")
        self.assertEqual(prov["PROVEEDORES_EDITABLES"], personas_cuenta.PROVEEDORES_EDITABLES)
        self.assertEqual(prov["PROVEEDORES_SIN_COLUMNA"], personas_cuenta.PROVEEDORES_SIN_COLUMNA)
        self.assertEqual(pers["FICHA_ERROR_SIN_ESCRIBIR"], personas_cuenta._FICHA_ERROR_SIN_ESCRIBIR)
        self.assertEqual(prov["PROVEEDORES_SIN_COLUMNA"], FIJO_SIN_COLUMNA)
        self.assertEqual(pers["FICHA_ERROR_SIN_ESCRIBIR"], FIJO_SIN_ESCRIBIR)

    def test_patrones_de_ruta_son_los_de_la_app(self):
        prov = self._constantes("proveedores.py")
        pers = self._constantes("personas.py")
        pat_prov, pat_precio = personas_cuenta.RUTAS_ALTERNAS["editar"]
        self.assertEqual(pat_prov.pattern, prov["PROVEEDORES_RUTA"] + r"/(\d{1,9})/editar")
        self.assertEqual(pat_precio.pattern, pers["PERSONAS_PRECIO_REFERENCIA_PATRON"])

    def test_la_app_y_el_calculo_contestan_lo_mismo_y_escriben_lo_mismo(self):
        """Para cada cuerpo y cada ruta, un doble FRESCO de la App sembrado con la base del cuerpo (y otro para el cálculo). Si la App
        rechaza: el mismo código y cuerpo, y ninguna escritura. Si la App escribe: el cálculo dice esas mismas escrituras."""
        for nombre, cuerpo in CUERPOS.items():
            for ruta in RUTAS:
                etiqueta = "cuerpo=%s ruta=%s" % (nombre, ruta)
                doble_app = doble_escrituras.DobleEscrituras(columnas_personas=[COLUMNA])
                doble_app.url = doble_app.arrancar()
                try:
                    _sembrar(doble_app, cuerpo)
                    codigo_app, datos_app, escrituras_app = _app(doble_app, ruta, dict(cuerpo))
                finally:
                    doble_app.parar()
                with _Sembrada(cuerpo, columnas_personas=[COLUMNA]) as c:
                    codigo_c, datos_c = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, cuerpo), QUIEN)
                    escrituras_c = c.escrituras()
                self.assertEqual(escrituras_c, [], "G2 (%s)" % etiqueta)
                if codigo_app == 200:
                    self.assertEqual(codigo_c, 200, "G1 contra la App: código (%s)" % etiqueta)
                    self.assertEqual(datos_c["escrituras"], forma_app(escrituras_app), "G1 contra la App (%s)" % etiqueta)
                else:
                    self.assertEqual(escrituras_app, [], "la App rechazó y escribió (%s)" % etiqueta)
                    self.assertEqual((codigo_c, datos_c), (codigo_app, datos_app), "G3 contra la App (%s)" % etiqueta)

    def test_la_app_sin_columna_de_precio_da_lo_mismo_que_el_calculo(self):
        for ruta in RUTAS:
            doble_app = doble_escrituras.DobleEscrituras(columnas_personas=())
            doble_app.url = doble_app.arrancar()
            try:
                codigo_app, datos_app, escrituras_app = _app(doble_app, ruta, dict(CUERPOS["precio_nuevo"]))
            finally:
                doble_app.parar()
            with Corrida(columnas_personas=()) as c:
                codigo_c, datos_c = personas_cuenta.calcular("editar", _cuerpo_del_calculo(ruta, CUERPOS["precio_nuevo"]), QUIEN)
            self.assertEqual(escrituras_app, [], "la App sin columna escribió (%s)" % ruta)
            self.assertEqual((codigo_c, datos_c), (codigo_app, datos_app), "sin columna (%s)" % ruta)
            self.assertEqual(c.escrituras(), [], "el cálculo sin columna escribió (%s)" % ruta)


if __name__ == "__main__":
    unittest.main()
