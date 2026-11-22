# -*- coding: utf-8 -*-
"""F6-2 en el programa de Personas (disenos/mercadeo-formularios/F6-PLAN.md, decisiones de la sala del 21-nov-2026): el origen
«formulario» en la entrada de fichas, y su permiso de promociones (la casilla `acepta`).

  L1  «formulario» está en `PUERTA_ORIGENES`, en `ORIGEN_ETIQUETAS` (con «Formulario») y en `base.ENTRADA_ORIGENES`; la constante
      `personas_entrada.ENTRADA_ORIGEN_FORMULARIO` es ese mismo valor.
  P1  fila de origen `formulario` con `acepta` = sí (o «si», o `true`): la ficha nace, la fila queda `aplicado` y el permiso queda
      anotado una sola vez: valor `si`, canal `formulario`, quien `natalia`.
  P2  `formulario` sin `acepta`, o con `no`, `false`, vacío o «tal vez»: la fila queda `aplicado` y no se anota ningún permiso.
  P3  otro origen con `acepta` = sí: la casilla se ignora; no se anota ningún permiso.
  P4  el permiso no se confirma (la respuesta no es 200 `anotado`/`ya_estaba`, o levanta): la fila NO queda `aplicado`, la entrada
      contesta 502, y repetir la fila lo termina con un solo permiso.
  P5  contar (`FICHAS_ENTRADA_MODO` ausente) no escribe el permiso.
  P6  el cálculo en `escribir` de una fila formulario con `acepta` = sí contesta 409 y no escribe (el permiso no se predice); sin
      `acepta` el cálculo sigue prediciendo como antes.

Corre por el camino de producción: la entrada de verdad (`personas_entrada.entrada_fichas`, la puerta, `anotar_permiso`) contra el
doble de NocoDB de `tests/doble_escrituras.py`. Lo que se parchea: `personas.anotar_permiso` en P4, para fallar el permiso a propósito,
y `DobleEscrituras.responder` solo para una cosa declarada abajo.

Lo que NO ve (declarado): el doble no completa las columnas de una fila NUEVA de `personas` (NocoDB real devuelve todas, con `null`), y
la lectura del grupo de la ficha exige `unida_a` en cada fila. Por eso la prueba añade `unida_a` y `quitada_el` en `null` a cada POST de
`personas` (los dos nombres salen de `personas.py`, la lectura de grupo). Los permisos se miden como diferencia contra la semilla del doble,
que ya trae un permiso propio. Datos inventados.

    PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -m unittest tests.test_entrada_formulario
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_entrada  # noqa: E402
from test_calcular_grupo_b import Corrida, QUIEN, cuerpo_del_calculo, fila, T_BANDEJA  # noqa: E402

ESCRIBIR = {"FICHAS_ENTRADA_MODO": "escribir"}
CONTAR = {"FICHAS_ENTRADA_MODO": "contar"}
COLUMNAS_QUE_NOCODB_DEVUELVE = {"unida_a": None, "quitada_el": None}
_RESPONDER_ORIGINAL = doble_escrituras.DobleEscrituras.responder


def _responder_con_columnas_de_nocodb(self, metodo, ruta, query, cuerpo):
    """El doble guarda una fila nueva tal cual llega; NocoDB real devuelve todas las columnas. Se añaden las que lee la lectura del grupo."""
    if metodo == "POST" and ruta == "/api/v2/tables/%s/records" % doble_nocodb.T_PERSONAS and isinstance(cuerpo, dict):
        cuerpo = {**COLUMNAS_QUE_NOCODB_DEVUELVE, **cuerpo}
    return _RESPONDER_ORIGINAL(self, metodo, ruta, query, cuerpo)


def ids_de_permisos(w):
    return {x["Id"] for x in w.doble.tablas[doble_nocodb.TABLA_ANOTACIONES] if x.get("clase") == "permiso"}


def permisos_nuevos(w, antes):
    """Los renglones de permiso que la entrada escribió (los que no estaban antes): (ficha, valor, canal, quien)."""
    return [(x.get("ficha_id"), x.get("valor"), x.get("canal"), x.get("quien"))
            for x in w.doble.tablas[doble_nocodb.TABLA_ANOTACIONES] if x.get("clase") == "permiso" and x["Id"] not in antes]


def estado_de(w, Id):
    return next(f.get("estado") for f in w.doble.tablas[T_BANDEJA] if f.get("Id") == Id)


def formulario(Id, telefono, nombre, **extra):
    return fila(Id, origen="formulario", telefono_meta=telefono, nombre=nombre, **extra)


def permiso_que_falla(veces, como="respuesta"):
    """Parchea `personas.anotar_permiso`: las primeras `veces` llamadas fallan (con 502 o levantando); luego, la de verdad."""
    original = personas.anotar_permiso
    cuenta = {"n": veces}

    def falso(*args, **kwargs):
        if cuenta["n"] > 0:
            cuenta["n"] -= 1
            if como == "levanta":
                raise RuntimeError("fallo de prueba del permiso")
            return 502, {"ok": False, "estado": "sin_confirmar"}
        return original(*args, **kwargs)
    return mock.patch.object(personas, "anotar_permiso", side_effect=falso)


class _Base(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.object(doble_escrituras.DobleEscrituras, "responder", _responder_con_columnas_de_nocodb)
        parche.start()
        self.addCleanup(parche.stop)


class ListasDelPrograma(unittest.TestCase):
    def test_L1_formulario_esta_en_las_tres_listas_y_tiene_etiqueta(self):
        self.assertIn("formulario", personas.PUERTA_ORIGENES)
        self.assertEqual(personas.ORIGEN_ETIQUETAS.get("formulario"), "Formulario")
        self.assertEqual(personas.origen_etiqueta("formulario"), "Formulario")
        self.assertIn("formulario", base.ENTRADA_ORIGENES)
        self.assertEqual(personas_entrada.ENTRADA_ORIGEN_FORMULARIO, "formulario")


class PermisoDeFormulario(_Base):
    def test_P1_acepta_si_nace_la_ficha_y_el_permiso_queda_una_vez(self):
        for acepta in ("sí", "si", True):
            with self.subTest(acepta=acepta):
                filas = [formulario(1, "18095550301", "Formulario Uno", acepta=acepta)]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(1)
                    self.assertEqual(codigo, 200, cuerpo)
                    self.assertEqual(cuerpo["estado"], "aplicado", cuerpo)
                    self.assertEqual(estado_de(w, 1), "aplicado")
                    self.assertEqual(permisos_nuevos(w, antes), [(cuerpo["ficha_id"], "si", "formulario", "natalia")])

    def test_P2_sin_acepta_o_acepta_que_no_es_si_no_anota_permiso(self):
        for extra in ({}, {"acepta": "no"}, {"acepta": False}, {"acepta": ""}, {"acepta": "tal vez"}):
            with self.subTest(extra=extra):
                filas = [formulario(2, "18095550302", "Formulario Dos", **extra)]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(2)
                    self.assertEqual((codigo, cuerpo["estado"]), (200, "aplicado"), cuerpo)
                    self.assertEqual(permisos_nuevos(w, antes), [])

    def test_P3_otro_origen_con_acepta_si_ignora_la_casilla(self):
        for origen in ("mensaje", "dictado", "reserva", "recuperado"):
            with self.subTest(origen=origen):
                filas = [fila(3, origen=origen, telefono_meta="18095550303", nombre="Otro Origen", acepta="sí")]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(3)
                    self.assertEqual(codigo, 200, cuerpo)
                    self.assertEqual(permisos_nuevos(w, antes), [], origen)

    def test_P4_si_el_permiso_no_se_confirma_la_fila_no_dice_aplicado_y_repetir_lo_termina(self):
        for como in ("respuesta", "levanta"):
            with self.subTest(como=como):
                # Una segunda fila pendiente (Id 40, mensaje) va después: el fallo de la fila 4 no debe cortar el barrido.
                filas = [formulario(4, "18095550304", "Formulario Cuatro", acepta="sí"),
                         fila(40, origen="mensaje", telefono_meta="18095550399", nombre="Otra Fila")]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    # Dos fallos: el barrido de la entrada reintenta la fila dentro de la misma petición.
                    with permiso_que_falla(2, como):
                        codigo, cuerpo = personas_entrada.entrada_fichas(4)
                    self.assertEqual((codigo, cuerpo), (502, {"error": "sin_confirmar"}))
                    self.assertNotEqual(estado_de(w, 4), "aplicado")
                    self.assertEqual(estado_de(w, 40), "aplicado", "el fallo del permiso cortó el barrido")
                    self.assertEqual(permisos_nuevos(w, antes), [])
                    codigo2, cuerpo2 = personas_entrada.entrada_fichas(4)
                    self.assertEqual((codigo2, cuerpo2["estado"]), (200, "aplicado"), cuerpo2)
                    self.assertEqual(estado_de(w, 4), "aplicado")
                    self.assertEqual(permisos_nuevos(w, antes), [(cuerpo2["ficha_id"], "si", "formulario", "natalia")])

    def test_P5_contar_no_escribe_el_permiso(self):
        filas = [formulario(5, "18095550305", "Formulario Cinco", acepta="sí")]
        with mock.patch.dict(os.environ, CONTAR), Corrida(filas) as w:
            antes = ids_de_permisos(w)
            codigo, cuerpo = personas_entrada.entrada_fichas(5)
            self.assertEqual(codigo, 200, cuerpo)
            self.assertEqual(permisos_nuevos(w, antes), [])

    def test_P6_el_calculo_en_escribir_dice_409_si_hay_permiso_y_predice_sin_el(self):
        con = [formulario(6, "18095550306", "Formulario Seis", acepta="sí")]
        with mock.patch.dict(os.environ, ESCRIBIR), Corrida(con) as c:
            codigo, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(6), QUIEN)
            self.assertEqual(codigo, 409)
            self.assertEqual(c.escrituras(), [], "el cálculo escribió")
        sin = [formulario(6, "18095550306", "Formulario Seis")]
        with mock.patch.dict(os.environ, ESCRIBIR), Corrida(sin) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(6), QUIEN)
            self.assertEqual(codigo, 200, datos)
            self.assertEqual(c.escrituras(), [], "el cálculo escribió")


class ListasDeWeb(unittest.TestCase):
    """W2 (disenos/web-reservas-a-fichas/DISENO.md, plan final 21-nov-2026): el origen «web» en todas las listas, con su etiqueta y su canal."""

    def test_W0_web_esta_en_las_listas_tiene_etiqueta_y_su_canal_de_permiso(self):
        self.assertIn("web", personas.PUERTA_ORIGENES)
        self.assertIn("web", base.ENTRADA_ORIGENES)
        self.assertIn("web", personas.ANOTACIONES_CANALES)
        self.assertEqual(personas.ORIGEN_ETIQUETAS.get("web"), "Web")
        self.assertEqual(personas.origen_etiqueta("web"), "Web")
        self.assertEqual(set(personas.ORIGEN_ETIQUETAS), set(personas.PUERTA_ORIGENES))
        self.assertEqual(personas_entrada.ENTRADA_PERMISO_CANAL, {"formulario": "formulario", "web": "web"})


class EntradaWeb(_Base):
    """W2: el origen «web» pasa por la entrada de fichas; con `acepta` = sí anota el permiso con canal `web` (quien natalia), dentro de la entrada."""

    def web(self, Id, telefono, nombre, **extra):
        return fila(Id, origen="web", telefono_meta=telefono, nombre=nombre, **extra)

    def test_W1_web_acepta_si_nace_la_ficha_y_el_permiso_con_canal_web(self):
        for acepta in ("sí", "si", True):
            with self.subTest(acepta=acepta):
                filas = [self.web(11, "18095550311", "Web Uno", acepta=acepta)]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(11)
                    self.assertEqual(codigo, 200, cuerpo)
                    self.assertEqual(cuerpo["estado"], "aplicado", cuerpo)
                    self.assertEqual(estado_de(w, 11), "aplicado")
                    self.assertEqual(permisos_nuevos(w, antes), [(cuerpo["ficha_id"], "si", "web", "natalia")])

    def test_W2_web_sin_acepta_o_acepta_que_no_es_si_no_anota_permiso(self):
        for extra in ({}, {"acepta": "no"}, {"acepta": False}, {"acepta": ""}, {"acepta": "tal vez"}):
            with self.subTest(extra=extra):
                filas = [self.web(12, "18095550312", "Web Dos", **extra)]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(12)
                    self.assertEqual((codigo, cuerpo["estado"]), (200, "aplicado"), cuerpo)
                    self.assertEqual(permisos_nuevos(w, antes), [])

    def test_W3_web_solo_correo_no_se_descarta_y_crea_la_ficha(self):
        for extra in ({}, {"acepta": "sí"}):
            with self.subTest(extra=extra):
                filas = [fila(13, origen="web", correo="ana.web.sola@ejemplo.test", nombre="Ana Web Sola", **extra)]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(13)
                    self.assertEqual((codigo, cuerpo.get("estado")), (200, "aplicado"), cuerpo)
                    self.assertEqual(estado_de(w, 13), "aplicado")
                    esperado = [(cuerpo["ficha_id"], "si", "web", "natalia")] if extra else []
                    self.assertEqual(permisos_nuevos(w, antes), esperado)

    def test_W4_pareja_otro_origen_con_acepta_si_no_anota_permiso(self):
        # La pareja de W1: el mismo `acepta` = sí, otros orígenes. Una prueba que solo mira `web` no ve una guarda que anote a todos.
        for origen in ("correo", "mensaje", "dictado", "reserva", "recuperado"):
            with self.subTest(origen=origen):
                filas = [fila(14, origen=origen, telefono_meta="18095550314", nombre="Otro Origen Web", correo="otro.web@ejemplo.test", acepta="sí")]
                with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
                    antes = ids_de_permisos(w)
                    codigo, cuerpo = personas_entrada.entrada_fichas(14)
                    self.assertEqual(codigo, 200, cuerpo)
                    self.assertEqual(permisos_nuevos(w, antes), [], origen)

    def test_W5_web_si_el_permiso_no_se_confirma_la_fila_no_dice_aplicado_y_repetir_lo_termina(self):
        filas = [self.web(15, "18095550315", "Web Cinco", acepta="sí")]
        with mock.patch.dict(os.environ, ESCRIBIR), Corrida(filas) as w:
            antes = ids_de_permisos(w)
            with permiso_que_falla(2, "respuesta"):
                codigo, cuerpo = personas_entrada.entrada_fichas(15)
            self.assertEqual((codigo, cuerpo), (502, {"error": "sin_confirmar"}))
            self.assertNotEqual(estado_de(w, 15), "aplicado")
            self.assertEqual(permisos_nuevos(w, antes), [])
            codigo2, cuerpo2 = personas_entrada.entrada_fichas(15)
            self.assertEqual((codigo2, cuerpo2["estado"]), (200, "aplicado"), cuerpo2)
            self.assertEqual(permisos_nuevos(w, antes), [(cuerpo2["ficha_id"], "si", "web", "natalia")])

    def test_W6_web_contar_no_escribe_el_permiso(self):
        filas = [self.web(16, "18095550316", "Web Seis", acepta="sí")]
        with mock.patch.dict(os.environ, CONTAR), Corrida(filas) as w:
            antes = ids_de_permisos(w)
            codigo, cuerpo = personas_entrada.entrada_fichas(16)
            self.assertEqual(codigo, 200, cuerpo)
            self.assertEqual(permisos_nuevos(w, antes), [])

    def test_W7_web_calculo_en_escribir_dice_409_si_hay_permiso(self):
        con = [self.web(17, "18095550317", "Web Siete", acepta="sí")]
        with mock.patch.dict(os.environ, ESCRIBIR), Corrida(con) as c:
            codigo, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(17), QUIEN)
            self.assertEqual(codigo, 409)
            self.assertEqual(c.escrituras(), [], "el cálculo escribió")


if __name__ == "__main__":
    unittest.main()
