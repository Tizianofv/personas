# -*- coding: utf-8 -*-
"""Pieza 1 de `disenos/natalia-correos-y-fichas/DISENO.md`: el correo cuenta como identidad por el camino de SISTEMA.

Un dato de sistema (sin `pantalla`) que trae SOLO su correo se busca por correo antes de crear. Si hay ficha con ese correo, se
devuelve esa; si no, se crea una ficha con él y se anota el origen `correo`. Lo que trae teléfono o ID no cambia.

Qué garantiza y con qué prueba (todo por `recibir` real, contra el doble de NocoDB que guarda de verdad, `tests/doble_escrituras.py`):
  C1  solo correo nuevo: crea UNA ficha con el correo en minúsculas y sin espacios, y anota el origen `correo`.
  C2  solo correo que ya existe: devuelve esa ficha; no crea ni escribe nada.
  C3  el mismo correo con mayúsculas o espacios es el mismo: la comparación pasa a minúsculas EN LOS DOS LADOS (una ficha con el
      correo guardado en mayúsculas también se encuentra).
  C4  dos pedidos a la vez con el mismo correo nuevo: UNA sola ficha. Lo garantiza `_FICHA_TELEFONO_LOCK`, que cubre la lectura de
      las fichas y el alta. El doble de la prueba espera a que los dos pedidos hayan leído antes de dejar seguir a ninguno: sin el
      candado, los dos crean; con él, el segundo espera y ve la ficha del primero.
  C5  un correo de una ficha que llega con un teléfono dictado distinto del de esa ficha: `por_resolver` y no se escribe nada.
  C6  lo de hoy con teléfono o ID: NO cambia. Los casos y sus resultados se fijaron corriéndolos contra el árbol de `5343421`
      (el que era `main` antes de esta pieza; ver `GOLDEN_HOY` abajo). Esta misma prueba corre también en ese árbol.
  C7  sin identidad sigue igual: un nombre solo, un correo sin forma o vacío: `sin_identidad`, cero escrituras.
  H1  hermano: `recibir` con origen `google` (lo llama `google_contactos.sincronizar`): busca por correo antes de crear.
  H2  hermano: `recibir_y_unir` (lo llama `personas_entrada`, la entrada de Natalia): busca por correo antes de crear.
  H3  hermano: `recibir_y_unir` con `planeados` (el cálculo del modo escribir de la entrada): planea el alta solo si no hay ficha.
  H4  hermano: `recibir(solo_contar=True)` (el cálculo): dice que crearía solo si no hay ficha con ese correo.
  F1  la lista de quién llama a la puerta sale del código (AST): ve las llamadas POR NOMBRE (`recibir(...)`, `x.recibir_y_unir(...)`)
      dentro de una función. Si aparece una función nueva que llama por nombre, la prueba se pone roja y hay que decidir su camino
      (sistema o pantalla). NO ve: (a) un alias (`_ALIAS = personas.recibir` y luego `_ALIAS(...)`: la llamada no tiene el nombre
      `recibir`); (b) una llamada nueva dentro de una función que ya está en la lista (la lista es por función, no por línea); (c) una
      llamada a nivel de módulo (fuera de cualquier `def`). Esos tres casos no los vigila esta prueba: los cubre el revisor al leer
      el diff y el grep de la escritura de fichas en el reporte.
  O1  el vocabulario de orígenes: `correo` está en `PUERTA_ORIGENES` y tiene etiqueta; las etiquetas son EXACTAMENTE esas claves.

Lo que NO ve (declarado): el doble no imita los códigos de error de NocoDB; una operación que cae se simula con `caidas` (no se usa
aquí). La concurrencia de C4 es entre hilos de un solo proceso (el candado es del proceso, ver el mapa); no prueba dos procesos.
"""
import ast
import contextlib
import io
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import personas  # noqa: E402
import personas_entrada  # noqa: E402
import doble_nocodb  # noqa: E402
from test_calcular_grupo_a import Corrida  # noqa: E402

T_PERSONAS = doble_nocodb.T_PERSONAS
T_ANOTACIONES = doble_nocodb.TABLA_ANOTACIONES
NOMBRE_DE_TABLA = {T_PERSONAS: "personas", T_ANOTACIONES: "anotaciones", doble_nocodb.T_BANDEJA: "bandeja"}


def _ficha(Id, nombre, telefono="", email="", bsuid=None):
    """Una ficha de prueba con todas las columnas que la puerta lee (datos ficticios)."""
    return {"Id": Id, "nombre": nombre, "nombre_whatsapp": "", "telefono": telefono, "telefono_2": "", "bsuid": bsuid,
            "email": email, "email_2": "", "instagram": "", "Cumpleanos": None, "credito": 0, "quitada_el": None,
            "unida_a": None, "CreatedAt": "2026-11-01T10:00:00Z"}


def _sin_ruido(fn):
    """La puerta imprime sus líneas `[warn]`/`[PUERTA-FICHAS]`; aquí no hacen falta."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _correr(fn, preparar=None):
    """Una corrida nueva (doble limpio). `preparar(c)` agrega fichas al doble antes de la llamada. Devuelve `(corrida, resultado)`."""
    with Corrida() as c:
        if preparar is not None:
            preparar(c)
        c.nueva_id = max(f["Id"] for f in c.doble.tablas[T_PERSONAS]) + 1     # después de `preparar`: el número que la base asigna
        return c, _sin_ruido(lambda: fn(c))


def _resumen(c, r):
    """Lo que contesta la puerta y lo que escribió la base, con el número nuevo cambiado por `<nueva>`. Es la forma de comparar C6."""
    escrituras = []
    for e in c.escrituras():
        cuerpo = e["cuerpo"]
        if isinstance(cuerpo, dict):
            cuerpo = {k: ("<nueva>" if v == c.nueva_id else v) for k, v in cuerpo.items()}
        escrituras.append([NOMBRE_DE_TABLA.get(e["tabla"], e["tabla"]), e["metodo"], cuerpo])
    ficha = r.get("ficha_id")
    return {"estado": r["estado"], "motivo": r["motivo"], "accion": r["accion"],
            "ficha_id": "<nueva>" if ficha == c.nueva_id else ficha,
            "avisos": [a["tipo"] for a in r["avisos"]],
            "valores": {k: v["resultado"] for k, v in sorted(r["valores"].items())},
            "escrituras": escrituras}


def _solo_personas(c):
    return [e for e in c.escrituras() if e["tabla"] == T_PERSONAS]


def _escrituras_a_personas(c):
    """Lo que se escribió en la tabla de fichas (crear o cambiar). La bandeja y las anotaciones van aparte."""
    return _solo_personas(c)


def _tipos_de_aviso(c):
    """Los avisos que la puerta dejó en la bandeja, en orden. Un aviso informativo (`ligado_por_correo`) SÍ se escribe, a propósito."""
    return [e["cuerpo"]["tipo_aviso"] for e in c.escrituras() if e["tabla"] == doble_nocodb.T_BANDEJA]


# ---- Los casos de C6: pedidos de sistema CON teléfono o ID. Las fichas del doble: 1 (tel 18097770001, bsuid DO.0000000000000001,
# correo p1@ejemplo.test), 2 (tel 18097770002, correo p2@ejemplo.test), 3 (quitada), 4 (unida a la 1).
def _fichas_extra_c6(c):
    c.doble.tablas[T_PERSONAS].append(_ficha(5, "Sin Telefono Con Correo", email="sincel@ejemplo.test"))


CASOS_C6 = {
    "dictado_nuevo": {"origen": "mensaje", "telefono_dicho": "18095550111"},
    "dictado_existente_con_formato": {"origen": "mensaje", "telefono_dicho": "(809) 777-0001"},
    "meta_nuevo_con_nombre": {"origen": "mensaje", "telefono_meta": "18095550112", "nombre": "Nuevo Meta"},
    "meta_existente_y_bsuid_nuevo": {"origen": "mensaje", "id_whatsapp": "DO.0000000000000002", "telefono_meta": "18097770002"},
    "solo_id_nuevo": {"origen": "mensaje", "id_whatsapp": "DO.0000000000000009"},
    "id_de_una_y_meta_de_otra": {"origen": "mensaje", "id_whatsapp": "DO.0000000000000001", "telefono_meta": "18097770002"},
    "meta_de_una_y_correo_de_otra": {"origen": "mensaje", "telefono_meta": "18097770001", "correo": "p2@ejemplo.test"},
    "dictado_y_correo_nuevos": {"origen": "dictado", "telefono_dicho": "18095550113", "correo": "nuevo@ejemplo.test"},
    "dictado_de_otra_con_correo_nuevo": {"origen": "reserva", "telefono_dicho": "18097770002", "correo": "nuevo2@ejemplo.test"},
    "meta_nuevo_y_dictado_de_otra": {"origen": "mensaje", "telefono_meta": "18095550115", "telefono_dicho": "18097770002"},
    "google_con_telefono_nuevo": {"origen": "google", "telefono_dicho": "18095550114", "nombre": "Contacto G"},
    "telefono_de_quitada": {"origen": "mensaje", "telefono_dicho": "18097770003"},
    "correo_de_sin_telefono_y_dictado_nuevo": {"origen": "mensaje", "correo": "sincel@ejemplo.test", "telefono_dicho": "18095550199"},
    "telefono_invalido_sin_identidad": {"origen": "mensaje", "telefono_dicho": "12"},
}

# Lo que dio cada caso de C6 corriendo esta misma prueba (`_resumen`) contra el árbol de `5343421`, antes de esta pieza.
# Se fijó con `CASOS_C6` y `_fichas_extra_c6` tal como están aquí. Un cambio aquí es un cambio de conducta con teléfono o ID.
GOLDEN_HOY = {'dictado_nuevo': {'estado': 'aplicado',
                   'motivo': None,
                   'accion': 'creada',
                   'ficha_id': '<nueva>',
                   'avisos': [],
                   'valores': {'telefono': 'guardado'},
                   'escrituras': [['personas', 'POST', {'telefono': '18095550111'}],
                                  ['anotaciones',
                                   'POST',
                                   {'ficha_id': '<nueva>',
                                    'clase': 'origen',
                                    'valor': 'mensaje',
                                    'dicho_el': '2026-11-10',
                                    'quien': 'sistema',
                                    'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'dictado_existente_con_formato': {'estado': 'aplicado',
                                   'motivo': None,
                                   'accion': 'sin_cambios',
                                   'ficha_id': 1,
                                   'avisos': ['ligado_por_dictado'],
                                   'valores': {'telefono': 'ya_estaba'},
                                   'escrituras': [['bandeja',
                                                   'POST',
                                                   {'clave': 'aviso-f230e2dd057d6e6b90a7fa6bc1ed7904d3cc7b12',
                                                    'origen': 'mensaje',
                                                    'estado': 'informativo',
                                                    'tipo_aviso': 'ligado_por_dictado',
                                                    'ficha_id': 1,
                                                    'resultado': '{"accion": "sin_cambios", "estado": '
                                                                 '"aplicado", "valores": {"telefono": '
                                                                 '"ya_estaba"}}',
                                                    'telefono_dicho': '18097770001'}]]},
 'meta_nuevo_con_nombre': {'estado': 'aplicado',
                           'motivo': None,
                           'accion': 'creada',
                           'ficha_id': '<nueva>',
                           'avisos': [],
                           'valores': {'nombre': 'guardado', 'telefono': 'guardado'},
                           'escrituras': [['personas',
                                           'POST',
                                           {'telefono': '18095550112', 'nombre': 'Nuevo Meta'}],
                                          ['anotaciones',
                                           'POST',
                                           {'ficha_id': '<nueva>',
                                            'clase': 'origen',
                                            'valor': 'mensaje',
                                            'dicho_el': '2026-11-10',
                                            'quien': 'sistema',
                                            'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'meta_existente_y_bsuid_nuevo': {'estado': 'aplicado',
                                  'motivo': None,
                                  'accion': 'completada',
                                  'ficha_id': 2,
                                  'avisos': [],
                                  'valores': {'id_whatsapp': 'guardado', 'telefono': 'ya_estaba'},
                                  'escrituras': [['personas',
                                                  'PATCH',
                                                  {'bsuid': 'DO.0000000000000002', 'Id': 2}]]},
 'solo_id_nuevo': {'estado': 'aplicado',
                   'motivo': None,
                   'accion': 'creada',
                   'ficha_id': '<nueva>',
                   'avisos': [],
                   'valores': {'id_whatsapp': 'guardado'},
                   'escrituras': [['personas', 'POST', {'bsuid': 'DO.0000000000000009'}],
                                  ['anotaciones',
                                   'POST',
                                   {'ficha_id': '<nueva>',
                                    'clase': 'origen',
                                    'valor': 'mensaje',
                                    'dicho_el': '2026-11-10',
                                    'quien': 'sistema',
                                    'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'id_de_una_y_meta_de_otra': {'estado': 'por_resolver',
                              'motivo': None,
                              'accion': 'no_tocada',
                              'ficha_id': None,
                              'avisos': ['misma_persona'],
                              'valores': {'id_whatsapp': 'no_guardado', 'telefono': 'no_guardado'},
                              'escrituras': [['bandeja',
                                              'POST',
                                              {'clave': 'aviso-2e8077adcf21d89ae5c09c19776b9fd554680891',
                                               'origen': 'mensaje',
                                               'estado': 'por_resolver',
                                               'tipo_aviso': 'misma_persona',
                                               'ficha_id': 1,
                                               'otra_ficha_id': 2,
                                               'resultado': '{"accion": "no_tocada", "estado": '
                                                            '"por_resolver", "valores": {"id_whatsapp": '
                                                            '"no_guardado", "telefono": "no_guardado"}}',
                                               'id_whatsapp': 'DO.0000000000000001',
                                               'telefono_meta': '18097770002'}]]},
 'meta_de_una_y_correo_de_otra': {'estado': 'por_resolver',
                                  'motivo': None,
                                  'accion': 'no_tocada',
                                  'ficha_id': None,
                                  'avisos': ['misma_persona'],
                                  'valores': {'correo': 'no_guardado', 'telefono': 'no_guardado'},
                                  'escrituras': [['bandeja',
                                                  'POST',
                                                  {'clave': 'aviso-d6d31f8bad8ad1fb53fe03111adbd4461b18381d',
                                                   'origen': 'mensaje',
                                                   'estado': 'por_resolver',
                                                   'tipo_aviso': 'misma_persona',
                                                   'ficha_id': 1,
                                                   'otra_ficha_id': 2,
                                                   'resultado': '{"accion": "no_tocada", "estado": '
                                                                '"por_resolver", "valores": {"correo": '
                                                                '"no_guardado", "telefono": "no_guardado"}}',
                                                   'telefono_meta': '18097770001',
                                                   'correo': 'p2@ejemplo.test'}]]},
 'dictado_y_correo_nuevos': {'estado': 'aplicado',
                             'motivo': None,
                             'accion': 'creada',
                             'ficha_id': '<nueva>',
                             'avisos': [],
                             'valores': {'correo': 'guardado', 'telefono': 'guardado'},
                             'escrituras': [['personas',
                                             'POST',
                                             {'telefono': '18095550113', 'email': 'nuevo@ejemplo.test'}],
                                            ['anotaciones',
                                             'POST',
                                             {'ficha_id': '<nueva>',
                                              'clase': 'origen',
                                              'valor': 'dictado',
                                              'dicho_el': '2026-11-10',
                                              'quien': 'sistema',
                                              'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'dictado_de_otra_con_correo_nuevo': {'estado': 'por_resolver',
                                      'motivo': None,
                                      'accion': 'sin_cambios',
                                      'ficha_id': 2,
                                      'avisos': ['ligado_por_dictado', 'otro_valor'],
                                      'valores': {'correo': 'no_guardado', 'telefono': 'ya_estaba'},
                                      'escrituras': [['bandeja',
                                                      'POST',
                                                      {'clave': 'aviso-320ae2975208294ff619aea23306b88450075990',
                                                       'origen': 'reserva',
                                                       'estado': 'informativo',
                                                       'tipo_aviso': 'ligado_por_dictado',
                                                       'ficha_id': 2,
                                                       'resultado': '{"accion": "sin_cambios", "estado": '
                                                                    '"por_resolver", "valores": {"correo": '
                                                                    '"no_guardado", "telefono": '
                                                                    '"ya_estaba"}}',
                                                       'telefono_dicho': '18097770002',
                                                       'correo': 'nuevo2@ejemplo.test'}],
                                                     ['bandeja',
                                                      'POST',
                                                      {'clave': 'aviso-a456a349cb1c61d35b2008b120f6bc5767160af3',
                                                       'origen': 'reserva',
                                                       'estado': 'por_resolver',
                                                       'tipo_aviso': 'otro_valor',
                                                       'ficha_id': 2,
                                                       'resultado': '{"accion": "sin_cambios", "estado": '
                                                                    '"por_resolver", "valores": {"correo": '
                                                                    '"no_guardado", "telefono": '
                                                                    '"ya_estaba"}}',
                                                       'telefono_dicho': '18097770002',
                                                       'correo': 'nuevo2@ejemplo.test'}]]},
 'meta_nuevo_y_dictado_de_otra': {'estado': 'por_resolver',
                                  'motivo': None,
                                  'accion': 'creada',
                                  'ficha_id': '<nueva>',
                                  'avisos': ['telefono_ajeno'],
                                  'valores': {'telefono': 'guardado', 'telefono_dicho': 'no_guardado'},
                                  'escrituras': [['personas', 'POST', {'telefono': '18095550115'}],
                                                 ['anotaciones',
                                                  'POST',
                                                  {'ficha_id': '<nueva>',
                                                   'clase': 'origen',
                                                   'valor': 'mensaje',
                                                   'dicho_el': '2026-11-10',
                                                   'quien': 'sistema',
                                                   'cuando': '2026-11-10T12:00:00+00:00'}],
                                                 ['bandeja',
                                                  'POST',
                                                  {'clave': 'aviso-d7276c0dc227b9a187ae42500e2461fe94baf3b1',
                                                   'origen': 'mensaje',
                                                   'estado': 'por_resolver',
                                                   'tipo_aviso': 'telefono_ajeno',
                                                   'ficha_id': '<nueva>',
                                                   'otra_ficha_id': 2,
                                                   'resultado': '{"accion": "creada", "estado": '
                                                                '"por_resolver", "valores": {"telefono": '
                                                                '"guardado", "telefono_dicho": '
                                                                '"no_guardado"}}',
                                                   'telefono_meta': '18095550115',
                                                   'telefono_dicho': '18097770002'}]]},
 'google_con_telefono_nuevo': {'estado': 'aplicado',
                               'motivo': None,
                               'accion': 'creada',
                               'ficha_id': '<nueva>',
                               'avisos': [],
                               'valores': {'nombre': 'guardado', 'telefono': 'guardado'},
                               'escrituras': [['personas',
                                               'POST',
                                               {'telefono': '18095550114', 'nombre': 'Contacto G'}],
                                              ['anotaciones',
                                               'POST',
                                               {'ficha_id': '<nueva>',
                                                'clase': 'origen',
                                                'valor': 'google',
                                                'dicho_el': '2026-11-10',
                                                'quien': 'sistema',
                                                'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'telefono_de_quitada': {'estado': 'aplicado',
                         'motivo': None,
                         'accion': 'creada',
                         'ficha_id': '<nueva>',
                         'avisos': [],
                         'valores': {'telefono': 'guardado'},
                         'escrituras': [['personas', 'POST', {'telefono': '18097770003'}],
                                        ['anotaciones',
                                         'POST',
                                         {'ficha_id': '<nueva>',
                                          'clase': 'origen',
                                          'valor': 'mensaje',
                                          'dicho_el': '2026-11-10',
                                          'quien': 'sistema',
                                          'cuando': '2026-11-10T12:00:00+00:00'}]]},
 'correo_de_sin_telefono_y_dictado_nuevo': {'estado': 'aplicado',
                                            'motivo': None,
                                            'accion': 'completada',
                                            'ficha_id': 5,
                                            'avisos': ['ligado_por_correo'],
                                            'valores': {'correo': 'ya_estaba', 'telefono': 'guardado'},
                                            'escrituras': [['personas',
                                                            'PATCH',
                                                            {'telefono': '18095550199', 'Id': 5}],
                                                           ['bandeja',
                                                            'POST',
                                                            {'clave': 'aviso-62d467f5161d329400830a69788d2a3907fe3b98',
                                                             'origen': 'mensaje',
                                                             'estado': 'informativo',
                                                             'tipo_aviso': 'ligado_por_correo',
                                                             'ficha_id': 5,
                                                             'resultado': '{"accion": "completada", '
                                                                          '"estado": "aplicado", "valores": '
                                                                          '{"correo": "ya_estaba", '
                                                                          '"telefono": "guardado"}}',
                                                             'telefono_dicho': '18095550199',
                                                             'correo': 'sincel@ejemplo.test'}]]},
 'telefono_invalido_sin_identidad': {'estado': 'rechazado',
                                     'motivo': 'sin_identidad',
                                     'accion': 'no_tocada',
                                     'ficha_id': None,
                                     'avisos': [],
                                     'valores': {'telefono': 'no_guardado'},
                                     'escrituras': []}}


class CorreoComoIdentidad(unittest.TestCase):

    # ---------------------------------------------------------------- C1 a C3: solo correo, por la puerta de sistema
    def test_C1_solo_correo_nuevo_crea_una_ficha_y_anota_el_origen(self):
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "Nueva.Persona@Mail.com "}))
        self.assertEqual(r["estado"], "aplicado", r)
        self.assertEqual(r["accion"], "creada", r)
        self.assertEqual(r["ficha_id"], c.nueva_id)
        self.assertEqual([(e["metodo"], e["cuerpo"]) for e in _solo_personas(c)], [("POST", {"email": "nueva.persona@mail.com"})])
        anotaciones = [e for e in c.escrituras() if e["tabla"] == T_ANOTACIONES]
        self.assertEqual(len(anotaciones), 1, anotaciones)
        self.assertEqual((anotaciones[0]["cuerpo"]["clase"], anotaciones[0]["cuerpo"]["valor"], anotaciones[0]["cuerpo"]["ficha_id"]),
                         ("origen", "correo", c.nueva_id))

    def test_C2_solo_correo_que_ya_existe_devuelve_esa_ficha_y_no_escribe(self):
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "p2@ejemplo.test"}))
        self.assertEqual(r["estado"], "aplicado", r)
        self.assertEqual(r["accion"], "sin_cambios", r)
        self.assertEqual(r["ficha_id"], 2)
        self.assertEqual(_escrituras_a_personas(c), [], "una ficha que ya tiene el correo no se toca")
        self.assertEqual(_tipos_de_aviso(c), ["ligado_por_correo"], "solo el aviso informativo de que el dato quedó en esa ficha")

    def test_C3_el_mismo_correo_con_mayusculas_o_espacios_es_el_mismo(self):
        # una ficha guardada con el correo en mayúsculas (dato viejo): se encuentra con el mismo correo en minúsculas
        def guardada_mixta(c):
            c.doble.tablas[T_PERSONAS].append(_ficha(5, "Mixta", email="Mixta@Ejemplo.TEST"))
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "  mixta@ejemplo.test "}), preparar=guardada_mixta)
        self.assertEqual((r["estado"], r["accion"], r["ficha_id"]), ("aplicado", "sin_cambios", 5), r)
        self.assertEqual(_escrituras_a_personas(c), [])
        # dos pedidos seguidos con el mismo correo escrito de dos formas: una sola ficha
        def dos_veces(c):
            a = personas.recibir({"origen": "correo", "correo": "Nueva@Mail.com"})
            b = personas.recibir({"origen": "correo", "correo": "  NUEVA@mail.COM  "})
            return a, b
        c, (a, b) = _correr(dos_veces)
        self.assertEqual(a["accion"], "creada")
        self.assertEqual((b["accion"], b["ficha_id"]), ("sin_cambios", a["ficha_id"]), b)
        self.assertEqual(len(_solo_personas(c)), 1, _solo_personas(c))

    # ---------------------------------------------------------------- C4: dos pedidos a la vez
    def test_C4_dos_pedidos_a_la_vez_con_el_mismo_correo_dan_una_sola_ficha(self):
        original = personas._leer_fichas_de_la_puerta
        # Los dos pedidos leen las fichas y luego esperan, con tope de 3 s, a que el otro también haya leído. Con el candado, el
        # segundo no puede leer hasta que el primero termina: la espera caduca (el primero sigue solo) y el segundo ve la ficha
        # que el primero creó. Sin el candado, los dos leen antes de que nadie escriba, y los dos crean.
        barrera = threading.Barrier(2, timeout=3)

        def leer_y_esperar():
            fichas = original()
            try:
                barrera.wait()
            except threading.BrokenBarrierError:
                pass
            return fichas

        resultados = []
        dato = {"origen": "correo", "correo": "Doble@Mail.com"}

        def pedir():
            resultados.append(personas.recibir(dict(dato)))

        with Corrida() as c:
            c.nueva_id = max(f["Id"] for f in c.doble.tablas[T_PERSONAS]) + 1
            with mock.patch.object(personas, "_leer_fichas_de_la_puerta", leer_y_esperar):
                hilos = [threading.Thread(target=lambda: _sin_ruido(pedir)) for _ in range(2)]
                for h in hilos:
                    h.start()
                for h in hilos:
                    h.join(60)
                self.assertFalse(any(h.is_alive() for h in hilos), "un pedido no terminó")
            altas = [e for e in _solo_personas(c) if e["metodo"] == "POST"]
        self.assertEqual(len(resultados), 2, resultados)
        self.assertEqual(len(altas), 1, "dos pedidos a la vez con el mismo correo crearon %d fichas" % len(altas))
        self.assertEqual(sorted(x["accion"] for x in resultados), ["creada", "sin_cambios"], resultados)
        self.assertEqual(resultados[0]["ficha_id"], resultados[1]["ficha_id"])

    # ---------------------------------------------------------------- C5: el correo de otra ficha con un teléfono distinto
    def test_C5_correo_de_otra_ficha_con_telefono_distinto_queda_por_resolver_y_no_escribe(self):
        def otra_ficha(c):
            c.doble.tablas[T_PERSONAS].append(_ficha(5, "Otra Persona", telefono="18097779999", email="otra@ejemplo.test"))
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "otra@ejemplo.test", "telefono_dicho": "18095550123"}),
                       preparar=otra_ficha)
        self.assertEqual(r["estado"], "por_resolver", r)
        self.assertIn("otro_valor", [a["tipo"] for a in r["avisos"]])
        self.assertEqual(_escrituras_a_personas(c), [], "el teléfono distinto no se escribe en la ficha del correo, ni se crea una ficha")
        self.assertEqual(_tipos_de_aviso(c), ["ligado_por_correo", "otro_valor"], "los dos avisos quedan en la bandeja para resolver")

    # ---------------------------------------------------------------- C6: con teléfono o ID, lo de hoy
    def test_C6_con_telefono_o_ID_lo_de_hoy_no_cambia(self):
        for nombre, dato in CASOS_C6.items():
            with self.subTest(caso=nombre):
                c, r = _correr(lambda c, d=dato: personas.recibir(dict(d)), preparar=_fichas_extra_c6)
                self.assertIn(nombre, GOLDEN_HOY, "falta el resultado de hoy de %s" % nombre)
                self.assertEqual(_resumen(c, r), GOLDEN_HOY[nombre])

    # ---------------------------------------------------------------- C7: sin identidad, igual
    def test_C7_sin_identidad_sigue_rechazando_sin_escribir(self):
        # Origen `mensaje` (existe en los dos árboles), para que la prueba mida la regla de identidad y no el vocabulario de orígenes.
        for dato in ({"origen": "mensaje", "nombre": "Solo Nombre"},
                     {"origen": "mensaje", "correo": "no es un correo"},
                     {"origen": "mensaje", "correo": "   "},
                     {"origen": "mensaje", "nombre": "Solo Nombre y Correo vacio", "correo": ""}):
            with self.subTest(dato=dato):
                c, r = _correr(lambda c, d=dato: personas.recibir(dict(d)))
                self.assertEqual((r["estado"], r["motivo"]), ("rechazado", "sin_identidad"), r)
                self.assertEqual(c.escrituras(), [])

    # ---------------------------------------------------------------- H1 a H4: los hermanos, por cada forma de llegar por sistema
    def test_H1_recibir_con_origen_google_busca_por_correo_antes_de_crear(self):
        c, r = _correr(lambda c: personas.recibir({"origen": "google", "correo": "p1@ejemplo.test"}))
        self.assertEqual((r["accion"], r["ficha_id"]), ("sin_cambios", 1), r)
        self.assertEqual(c.escrituras(), [])
        c, r = _correr(lambda c: personas.recibir({"origen": "google", "correo": "contacto@ejemplo.test"}))
        self.assertEqual(r["accion"], "creada", r)
        self.assertEqual(len(_solo_personas(c)), 1)

    def test_H2_recibir_y_unir_busca_por_correo_antes_de_crear(self):
        c, r = _correr(lambda c: personas.recibir_y_unir({"origen": "mensaje", "correo": "p2@ejemplo.test"}))
        self.assertEqual((r["accion"], r["ficha_id"]), ("sin_cambios", 2), r)
        self.assertEqual(_escrituras_a_personas(c), [])
        self.assertEqual(_tipos_de_aviso(c), ["ligado_por_correo"])
        c, r = _correr(lambda c: personas.recibir_y_unir({"origen": "mensaje", "correo": "entrada@ejemplo.test"}))
        self.assertEqual(r["accion"], "creada", r)
        self.assertEqual(len(_solo_personas(c)), 1)

    def test_H3_recibir_y_unir_planeado_no_planea_alta_si_el_correo_ya_tiene_ficha(self):
        # Con la ficha que ya tiene el correo, la puerta deja el aviso `ligado_por_correo`, y el cálculo del modo escribir NO predice
        # con avisos (`_recibir_planeado` levanta `SinCalculoDeEntrada`, igual que hoy con un dictado que liga). No planea un alta.
        planeados = []
        with Corrida() as c:
            c.nueva_id = max(f["Id"] for f in c.doble.tablas[T_PERSONAS]) + 1
            with self.assertRaises(personas.SinCalculoDeEntrada):
                _sin_ruido(lambda: personas.recibir_y_unir({"origen": "mensaje", "correo": "p1@ejemplo.test"}, planeados=planeados))
        self.assertFalse([p for p in planeados if p["tabla"] == T_PERSONAS and p["metodo"] == "POST"], planeados)
        self.assertEqual(c.escrituras(), [])

    def test_H3b_recibir_y_unir_planeado_planea_el_alta_si_el_correo_es_nuevo(self):
        planeados = []
        c, r = _correr(lambda c: personas.recibir_y_unir({"origen": "mensaje", "correo": "nuevo.planeado@ejemplo.test"}, planeados=planeados))
        altas = [p for p in planeados if p["tabla"] == T_PERSONAS and p["metodo"] == "POST"]
        self.assertEqual(altas, [{"tabla": T_PERSONAS, "metodo": "POST", "cuerpo": {"email": "nuevo.planeado@ejemplo.test"}}], planeados)
        self.assertEqual(c.escrituras(), [], "el cálculo no escribe")

    def test_H4_recibir_solo_contar_dice_que_crearia_solo_si_no_hay_ficha(self):
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "p1@ejemplo.test"}, solo_contar=True))
        self.assertFalse([m for m in r.get("mandaria", []) if m["tabla"] == T_PERSONAS and m["metodo"] == "POST"], r)
        c, r = _correr(lambda c: personas.recibir({"origen": "correo", "correo": "nuevo.contar@ejemplo.test"}, solo_contar=True))
        self.assertTrue([m for m in r.get("mandaria", []) if m["tabla"] == T_PERSONAS and m["metodo"] == "POST"], r)
        self.assertEqual(c.escrituras(), [], "solo_contar no escribe")

    # ---------------------------------------------------------------- F1: quién llama a la puerta, sacado del código
    def test_F1_quien_llama_a_la_puerta_es_el_que_se_clasifico(self):
        llamadores = set()
        for ruta in sorted(RAIZ.glob("*.py")):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
            for fn in ast.walk(arbol):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for nodo in ast.walk(fn):
                    if not isinstance(nodo, ast.Call):
                        continue
                    f = nodo.func
                    nombre = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                    if nombre in ("recibir", "recibir_y_unir", "_puerta_recibir", "_recibir_planeado"):
                        llamadores.add((ruta.name, fn.name))
        # Sistema (sin `pantalla`): por ellos se busca por correo. Pantalla: las de la App y del portal, que NO cambian aquí.
        sistema = {("google_contactos.py", "sincronizar"), ("personas_entrada.py", "_entrada_planear_escribir"),
                   ("personas_entrada.py", "entrada_procesar")}
        pantalla = {("personas.py", "crear_persona_portal"), ("personas.py", "_guardar_edicion_de_persona"),
                    ("personas_escrituras.py", "crear_persona"), ("personas_escrituras.py", "editar_persona")}
        internos = {("personas.py", "recibir"), ("personas.py", "recibir_y_unir"), ("personas.py", "_recibir_planeado"),
                    ("personas.py", "_union_sola_unida"), ("personas.py", "_union_sola_sin_lo_ajeno")}
        self.assertEqual(llamadores, sistema | pantalla | internos,
                         "llamadores nuevos o cambiados: decidir si su alta busca por correo (sistema) o es pantalla")

    # ---------------------------------------------------------------- O1: el vocabulario de orígenes
    def test_O1_correo_es_un_origen_con_etiqueta_y_las_etiquetas_son_las_mismas_claves(self):
        self.assertIn("correo", personas.PUERTA_ORIGENES)
        self.assertEqual(set(personas.ORIGEN_ETIQUETAS), set(personas.PUERTA_ORIGENES))
        self.assertEqual(personas.origen_etiqueta("correo"), "Correo")


if __name__ == "__main__":
    unittest.main()
