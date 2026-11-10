# -*- coding: utf-8 -*-
"""P11-6, GRUPO (e): el cálculo de RESOLVER, REABRIR (la bandeja de «Por resolver»), BORRAR y DEVOLVER (`personas_cuenta.CALCULOS`,
filas 4, 5, 9 y 10 del diseño).

La App escribe estas cuatro en su modo contar (nombres de `escritura_de_personas_para_cuenta`, `registro/server.py`):
  resolver  POST /api/portal-personas/por-resolver/resolver   -> `personas.portal_por_resolver_marcar` (marca un renglón resuelto)
  reabrir   POST /api/portal-personas/por-resolver/reabrir    -> la misma función con `reabrir=True`
  borrar    POST /api/portal-personas/<id>/borrar             -> `personas.quitar_ficha` (registro en `personas_quitadas` y ficha)
  devolver  POST /api/portal-personas/<id>/devolver           -> `personas.devolver_ficha`
Las cuatro corren la MISMA función de escritura con `solo_contar=True` y `planeados`: decide y rechaza igual, y en vez de cada escritura
guarda la forma del renglón en `planeados`. Las relecturas que confirman lo que se acaba de planear no se hacen en el cálculo (se dan por
buenas): lo que la App compara es lo que NocoDB confirmó, así que el cálculo predice el camino de éxito.

Qué garantiza y con qué prueba:
  E1  PAREJA en los escenarios de `ESCENARIOS`: el cálculo dice EXACTAMENTE lo que la escritura mandó a NocoDB (forma de la App, en orden).
  E2  CERO ESCRITURAS AL CALCULAR: en cada escenario, el cálculo no manda POST, PATCH, PUT ni DELETE.
  E3  RECHAZOS IGUALES Y SIN ESCRIBIR: en cada rechazo, el cálculo da el MISMO código y cuerpo que la escritura, y la escritura no escribió.
  E4  REGISTRO: los cuatro nombres están en `CALCULOS` y en `RUTAS`, y la ruta ajena se rechaza con 400.
  E5  NINGUNA CACHÉ: el cálculo no invalida `personas`, `portal` ni `caras` (la escritura sí lo hace, y eso no cambia).

Lo que NO ve (declarado): la escritura de la App en vivo (K2e en `test_contrato_app_p11.py` compara con la escritura del programa
capturada en el doble); los hilos propios; las escrituras de otros procesos entre el cálculo y la escritura; una caída de NocoDB en
mitad de la escritura (el cálculo supone que cada escritura se confirma); el aviso de «Por resolver» que nombra fichas (la rama roja de
`_por_resolver_marcar_aviso`) solo se cubre si un escenario la alcanza (ver `ESCENARIOS`).
"""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import doble_nocodb  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import test_calcular_grupo_a as g  # noqa: E402

QUIEN = g.QUIEN
AHORA = g.AHORA
GRUPO_E = ("resolver", "reabrir", "borrar", "devolver")
TEXTO_RUTA_AJENA = personas_cuenta.ERROR_RUTA_AJENA["error"]
NOMBRE_DE_TABLA = {doble_nocodb.T_PERSONAS: "personas", doble_nocodb.TABLA_ANOTACIONES: "anotaciones", doble_nocodb.T_BANDEJA: "bandeja",
                   doble_nocodb.T_QUITADAS: "quitadas"}


PERSONA_DUPLICADA = {"Id": 5, "nombre": "Persona de prueba 2", "nombre_whatsapp": "", "telefono": "18097770005", "telefono_2": "",
                     "bsuid": None, "email": "", "email_2": "", "instagram": "", "Cumpleanos": None, "credito": 0, "quitada_el": None,
                     "unida_a": None, "CreatedAt": "2026-10-05T10:00:00Z"}


class Corrida(g.Corrida):
    """La corrida de grupo (a) con las tablas de este grupo: el registro de borrados y las de `revisar_borrado`, y filas de prueba extra."""

    def __init__(self, bandeja_extra=(), quitadas_extra=(), **kw):
        super().__init__(**kw)
        self.parches += [
            mock.patch.object(base, "T_PERSONAS_QUITADAS", doble_nocodb.T_QUITADAS),
            mock.patch.object(base, "T_MERCADEO_ENVIOS", doble_nocodb.T_MERCADEO_ENVIOS),
            mock.patch.object(base, "T_UNIONES_PERSONAS", doble_nocodb.T_UNIONES),
        ]
        # Una persona más con el NOMBRE de la ficha 2: forma un grupo «Se llaman igual» de «Por resolver» (la ficha 4 está unida y no sale).
        self.doble.tablas[doble_nocodb.T_PERSONAS].append(dict(PERSONA_DUPLICADA))
        for fila in bandeja_extra:
            self.doble.tablas[doble_nocodb.T_BANDEJA].append(dict(fila))
        for fila in quitadas_extra:
            self.doble.tablas[doble_nocodb.T_QUITADAS].append(dict(fila))


def forma_app(escrituras):
    """Lo que la App ve de estas escrituras (contrato de `panel_reenvio.calcular_personas`): una fila por registro, sin `Id`."""
    filas = []
    for e in escrituras:
        registros = e["cuerpo"] if isinstance(e["cuerpo"], list) else [e["cuerpo"]]
        for reg in registros:
            filas.append({"tabla": NOMBRE_DE_TABLA[e["tabla"]], "metodo": e["metodo"], "enlace": None,
                          "valores": {k: v for k, v in reg.items() if k != "Id"}})
    return filas


def ruta_de(nombre, ficha):
    if nombre == "resolver":
        return "/api/portal-personas/por-resolver/resolver"
    if nombre == "reabrir":
        return "/api/portal-personas/por-resolver/reabrir"
    if nombre == "borrar":
        return "/api/portal-personas/%d/borrar" % ficha
    if nombre == "devolver":
        return "/api/portal-personas/%d/devolver" % ficha
    raise AssertionError(nombre)


def cuerpo_del_calculo(nombre, ficha, pedido):
    """El cuerpo que manda la App al cálculo: el pedido más `ruta_de_la_escritura`."""
    return dict(pedido, **{personas_cuenta.CLAVE_RUTA: ruta_de(nombre, ficha or 0)})


def filas_de_la_corrida(bandeja_extra=(), quitadas_extra=()):
    """Las tablas que tiene una `Corrida` con esos extras, sin arrancar nada (para el programa de verdad, que las monta en su doble)."""
    tablas = {t: copy.deepcopy(doble_nocodb.TABLAS[t]) for t in (doble_nocodb.T_PERSONAS, doble_nocodb.T_BANDEJA, doble_nocodb.T_QUITADAS)}
    tablas[doble_nocodb.T_PERSONAS].append(dict(PERSONA_DUPLICADA))
    tablas[doble_nocodb.T_BANDEJA] += [dict(f) for f in bandeja_extra]
    tablas[doble_nocodb.T_QUITADAS] += [dict(f) for f in quitadas_extra]
    return tablas


def clave_del_grupo():
    """La clave de un grupo de «Por resolver» de los datos del doble (las fichas 1 y 4 comparten teléfono)."""
    with Corrida() as w:
        grupos = personas.por_resolver_grupos([p["publica"] for p in personas.portal_personas_todas()])
        return grupos[0]["clave"]


def antes_de(ficha_id):
    """Lo que el registro guarda de la ficha antes de borrarla: las 8 casillas de la unión y la marca en vacío (como `quitar_ficha`)."""
    fila = next(p for p in doble_nocodb.PERSONAS + [PERSONA_DUPLICADA] if p["Id"] == ficha_id)
    antes = {c: fila.get(c) for c in personas.UNION_COLUMNAS_QUE_SE_VACIAN}
    antes[personas.QUITAR_MARCA] = None
    return antes


def escribir(nombre, ficha, cuerpo):
    """La escritura de verdad, como la llama la ruta de la App (sin `solo_contar`)."""
    if nombre == "resolver":
        return personas.portal_por_resolver_marcar(cuerpo.get("clave"), QUIEN)
    if nombre == "reabrir":
        return personas.portal_por_resolver_marcar(cuerpo.get("clave"), QUIEN, reabrir=True)
    if nombre == "borrar":
        return personas.quitar_ficha(ficha, cuerpo.get("clave"), QUIEN)
    if nombre == "devolver":
        return personas.devolver_ficha(ficha, QUIEN)
    raise AssertionError(nombre)


def escenarios():
    """(nombre, ficha, pedido, etiqueta, kwargs de la corrida). Los de éxito escriben; los de rechazo no escriben.
    Ficha 3: borrada (su registro `quitada` está en el doble). Ficha 4: ya devuelta. Ficha 1 y 4: comparten teléfono (un grupo)."""
    clave = clave_del_grupo()
    renglon_resuelto = {"Id": 9, "clave": clave, "origen": "por-resolver", "estado": "resuelto", "resuelto_por": QUIEN, "resuelto_en": AHORA,
                        "tipo_aviso": "telefono", "ficha_id": 1, "otra_ficha_id": 4, "resultado": "{}"}
    quitando = {"Id": 7, "ficha_id": 5, "estado": "quitando", "clave": "clave-de-prueba-quitando", "creada_por": QUIEN,
                "creada_en": "2026-10-08T12:00:00Z", "antes": json.dumps(antes_de(5)), "medido": "{}"}
    return [
        ("resolver", None, {"clave": clave}, "resolver el grupo de la misma persona", {}),
        ("reabrir", None, {"clave": clave}, "reabrir un renglón resuelto", {"bandeja_extra": [renglon_resuelto]}),
        ("reabrir", None, {"clave": clave}, "reabrir sin marca (ya estaba)", {}),
        ("borrar", 5, {"clave": "clave-de-prueba-uno"}, "borrar una ficha viva", {}),
        ("borrar", 5, {"clave": "clave-de-prueba-quitando"}, "seguir un borrado a medias", {"quitadas_extra": [quitando]}),
        ("borrar", 2, {"clave": "clave-de-prueba-dos"}, "borrar una ficha con parada (rechazo)", {}),
        ("devolver", 3, {}, "devolver la ficha guardada aparte", {}),
        ("resolver", None, {"clave": "no-es-una-clave"}, "clave que no es de ningún renglón (rechazo)", {}),
        ("devolver", 4, {}, "devolver una ficha ya devuelta (rechazo)", {}),
        ("borrar", 3, {"clave": "clave-de-prueba-tres"}, "borrar una ficha que ya está borrada (rechazo)", {}),
        ("borrar", 2, {}, "borrar sin clave (rechazo)", {}),
    ]


def _pareja(testcase, nombre, ficha, pedido, etiqueta, kw):
    """Corre la escritura y el cálculo sobre dobles propios y compara (E1, E3); el cálculo no escribe (E2)."""
    with Corrida(**kw) as w:
        codigo_w, datos_w = escribir(nombre, ficha, dict(pedido))
        escrituras_w = w.escrituras()
    with Corrida(**kw) as c:
        codigo_c, datos_c = personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
        escrituras_c = c.escrituras()
    testcase.assertEqual(escrituras_c, [], "E2: el cálculo mandó escrituras (%s)" % etiqueta)
    if codigo_w == 200 and codigo_c == 200 and isinstance(datos_c, dict) and "escrituras" in datos_c:
        testcase.assertEqual(datos_c["escrituras"], forma_app(escrituras_w), "E1: el cálculo no dice lo que la escritura mandó (%s)" % etiqueta)
        return escrituras_w
    testcase.assertEqual((codigo_c, datos_c), (codigo_w, datos_w), "E3: el rechazo no es el mismo (%s)" % etiqueta)
    testcase.assertEqual(escrituras_w, [], "E3: la escritura rechazada escribió (%s)" % etiqueta)
    return None


class GrupoE(unittest.TestCase):
    def test_E1_E2_E3_pareja_cero_escrituras_y_rechazos_iguales(self):
        for nombre, ficha, pedido, etiqueta, kw in escenarios():
            with self.subTest(escenario=etiqueta):
                _pareja(self, nombre, ficha, pedido, etiqueta, kw)

    def test_E1_los_escenarios_de_exito_escriben_lo_que_se_espera(self):
        """Que la pareja no sea vacía: cada escenario de éxito escribe algo, y el cálculo lo dice."""
        escriben = {"resolver", "reabrir", "borrar", "devolver"}
        for nombre, ficha, pedido, etiqueta, kw in escenarios():
            if etiqueta.endswith("(rechazo)") or etiqueta == "reabrir sin marca (ya estaba)":
                continue
            with self.subTest(escenario=etiqueta):
                escritas = _pareja(self, nombre, ficha, pedido, etiqueta, kw)
                self.assertTrue(escritas, "la escritura no escribió nada en un escenario de éxito (%s)" % etiqueta)
                self.assertIn(nombre, escriben)

    def test_E4_registro_y_ruta_ajena(self):
        for nombre in GRUPO_E:
            self.assertIn(nombre, personas_cuenta.CALCULOS, nombre)
            self.assertIn(nombre, personas_cuenta.RUTAS, nombre)
        with Corrida() as c:
            codigo, datos = personas_cuenta.calcular("borrar", cuerpo_del_calculo("devolver", 3, {}), QUIEN)
            self.assertEqual((codigo, datos), (400, personas_cuenta.ERROR_RUTA_AJENA))
            self.assertEqual(c.escrituras(), [])

    def test_E5_ninguna_cache_se_invalida_al_calcular(self):
        for nombre, ficha, pedido, etiqueta, kw in escenarios():
            with self.subTest(escenario=etiqueta):
                with Corrida(**kw):                 # la corrida invalida sus cachés al entrar: el contador va después
                    with mock.patch.object(personas, "invalidate_personas") as inv_p, \
                            mock.patch.object(personas, "invalidate_portal_personas") as inv_portal, \
                            mock.patch.object(personas, "_union_tirar_caches") as tirar:
                        personas_cuenta.calcular(nombre, cuerpo_del_calculo(nombre, ficha, dict(pedido)), QUIEN)
                self.assertEqual((inv_p.call_count, inv_portal.call_count, tirar.call_count), (0, 0, 0), etiqueta)


if __name__ == "__main__":
    unittest.main()
