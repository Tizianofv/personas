# -*- coding: utf-8 -*-
"""Los escenarios de las ESCRITURAS del portal (paso 5c, parte 3): crear, editar, anotar permiso, resolver y reabrir. Los usan DOS cosas:
  · `tools/generar_portal_escrituras_de_la_app.py`: corre la App de registro (`594ec12`, copia `git archive`) con su
    `Handler.portal_personas` contra el doble, y guarda lo que contesta y lo que el doble recibe (`contrato_dorado/portal_escrituras.json`);
  · `tests/test_portal_escrituras.py`: corre `servidor.py` del repo contra el mismo doble y compara paso a paso con esa foto.

Cada escenario arranca un proceso nuevo (App o repo) y un doble nuevo, y corre sus pasos en orden. Un paso es un pedido POST con
cabeceras del portal. Los valores de llave se nombran con un SÍMBOLO (`portal`, `escritura`, `lectura_mercadeo`, `lectura_registro`,
`vacia`, `mala`, `ausente`); los valores reales están en `VALORES` y no se guardan en ningún registro.

Campos de un paso:
  ruta, cuerpo (objeto) o crudo (texto que se manda tal cual),
  llave (símbolo; por defecto `portal`, `None` = sin cabecera),
  quien (texto; `None` = sin cabecera; el texto va como UTF-8 en la cabecera),
  tipo (texto; por defecto `A`; `None` = sin cabecera).
Los pasos del DORADO son los que tienen llave `portal`, `quien` no vacío y tipo `A`: la App no tiene identidad (la pone el
programa), así que solo esos pasos se comparan con la App. Lo que no es dorado (llaves, identidad) se prueba en `test_portal_escrituras.py`.

Lo que se apunta de cada paso: el código, el cuerpo de la respuesta y los pedidos que llegaron al doble durante el paso
(método, ruta, query y cuerpo; nunca las cabeceras).
"""
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import doble_escrituras
import doble_nocodb

RUTA_PORTAL = "/api/portal-personas"
CABECERA_LLAVE = "X-Personas-Portal-Llave"
CABECERA_QUIEN = "X-Personas-Portal-Quien"
CABECERA_TIPO = "X-Personas-Portal-Tipo"

# Valores de PRUEBA (no son secretos). Solo los usa el harness, nunca un registro.
VALORES = {
    "portal": "llave-de-prueba-portal-personas",
    "escritura": "llave-de-prueba-escritura-registro-personas",
    "lectura_mercadeo": "llave-de-prueba-lectura-mercadeo-personas",
    "lectura_registro": "llave-de-prueba-lectura-registro-personas",
}
QUIEN_DORADO = "Ana Pérez"       # con tilde: la prueba de la cabecera UTF-8 (lo que la App pone, sin codificar)

# Entorno de los dos lados. Las tablas de NocoDB las dan las constantes del doble (las mismas que usan las lecturas del portal).
ENTORNO_BASE = {
    "PERSONAS_PORTAL_LLAVE": VALORES["portal"],
    "PERSONAS_REGISTRO_ESCRITURA_LLAVE": VALORES["escritura"],
    "PERSONAS_LECTURA_LLAVE": VALORES["lectura_mercadeo"],
    "PERSONAS_REGISTRO_LLAVE": VALORES["lectura_registro"],
    "NOCODB_T_PERSONAS_ANOTACIONES": doble_nocodb.TABLA_ANOTACIONES,
    "NOCODB_T_PERSONAS_QUITADAS": doble_nocodb.T_QUITADAS,
    "NOCODB_T_BANDEJA_PERSONAS": doble_nocodb.T_BANDEJA,
}
ENTORNO_MINIMO = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}


def _p(ruta, cuerpo=None, crudo=None, llave="portal", quien=QUIEN_DORADO, tipo="A", nombre=None, metodo="POST"):
    paso = {"ruta": ruta, "llave": llave, "quien": quien, "tipo": tipo, "metodo": metodo}
    if crudo is not None:
        paso["crudo"] = crudo
    else:
        paso["cuerpo"] = cuerpo
    if nombre is not None:
        paso["nombre"] = nombre
    return paso


CREAR = {"cambios": {"nombre": "Portal Uno", "telefono": "8095550201", "email": "portal.uno@ejemplo.test", "instagram": "portal_uno"}}
# «base» es lo que la ficha decía al abrirla (la App lo compara antes de escribir): aquí, la persona 2 tal como está en el doble.
EDITAR = {"id": 2, "base": {"nombre": "Persona de prueba 2", "instagram": ""},
          "cambios": {"nombre": "Persona Dos Editada", "instagram": "persona_dos"}}
PERMISO = {"valor": "no", "visto": 2}           # el último renglón de permiso de la persona 2 es el Id 2 del doble
CLAVE_RESUELTO = "resuelto-" + "a" * 40          # formato válido; no es ningún renglón de «Por resolver» del doble
CLAVE_AVISO = "aviso-" + "b" * 40                # formato válido de aviso; no existe en el doble
RUTA_EDITAR = RUTA_PORTAL + "/2/editar"
RUTA_PERMISO = RUTA_PORTAL + "/2/permiso"
RUTA_RESOLVER = RUTA_PORTAL + "/por-resolver/resolver"
RUTA_REABRIR = RUTA_PORTAL + "/por-resolver/reabrir"

ESCENARIOS = [
    {"nombre": "crear_ok", "pasos": [
        _p(RUTA_PORTAL, CREAR),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Dos"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Tres", "telefono": "8095550203"}, "clave_envio": "envio-crear-1"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Tres", "telefono": "8095550203"}, "clave_envio": "envio-crear-1"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Otro cuerpo"}, "clave_envio": "envio-crear-1"}),
    ]},
    {"nombre": "crear_errores", "pasos": [
        _p(RUTA_PORTAL, {"cambios": {"nombre": "x", "caras": "no"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": 5}}),
        _p(RUTA_PORTAL, {"cambios": {"telefono": "8095550202"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Con telefono corto", "telefono": "12"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Repetido", "telefono": "18097770001"}}),
        _p(RUTA_PORTAL, {"sin_cambios": True}),
        _p(RUTA_PORTAL, [1, 2]),
        _p(RUTA_PORTAL, crudo="{"),
        _p(RUTA_PORTAL, crudo=""),
    ]},
    {"nombre": "crear_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_PORTAL, CREAR)]},
    {"nombre": "crear_escritura_caida", "caidas": ["POST"], "pasos": [_p(RUTA_PORTAL, CREAR)]},
    {"nombre": "editar_ok", "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-1")),
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-1")),
        _p(RUTA_EDITAR, EDITAR),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"instagram": "persona_dos"}, "cambios": {"instagram": "persona_tres"}}),
        _p(RUTA_PORTAL + "/1/editar", {"id": 1, "base": {}, "cambios": {}}),
    ]},
    {"nombre": "editar_errores", "pasos": [
        _p(RUTA_PORTAL + "/2/editar", {"id": 3, "cambios": {"nombre": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "cambios": "x"}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "cambios": {"caras": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"nombre": "Persona de prueba 2"}, "cambios": {"nombre": 7}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"telefono": "18097770002"}, "cambios": {"telefono": "18097770001"}}),
        _p(RUTA_PORTAL + "/99/editar", {"id": 99, "base": {"nombre": "x"}, "cambios": {"nombre": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", crudo="x"),
        _p(RUTA_PORTAL + "/2/editar", crudo=""),
    ]},
    {"nombre": "editar_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_EDITAR, EDITAR)]},
    {"nombre": "editar_escritura_caida", "caidas": ["PATCH"], "pasos": [_p(RUTA_EDITAR, EDITAR)]},
    {"nombre": "permiso_ok", "pasos": [
        _p(RUTA_PERMISO, PERMISO),
        _p(RUTA_PERMISO, {"valor": "si", "visto": 2}),
        _p(RUTA_PERMISO, {"valor": "si", "visto": 3}),
    ]},
    {"nombre": "permiso_errores", "pasos": [
        _p(RUTA_PERMISO, {"valor": "tal vez", "visto": 2}),
        _p(RUTA_PERMISO, {"valor": "no"}),
        _p(RUTA_PERMISO, {"valor": "no", "visto": 2, "quien": "Otra Persona"}),
        _p(RUTA_PERMISO, {"valor": "no", "visto": 2, "canal": "carta"}),
        _p(RUTA_PORTAL + "/99/permiso", {"valor": "no", "visto": None}),
        _p(RUTA_PERMISO, crudo="{"),
        _p(RUTA_PERMISO, {}),
    ]},
    {"nombre": "permiso_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_PERMISO, PERMISO)]},
    {"nombre": "permiso_escritura_caida", "caidas": ["POST"], "pasos": [_p(RUTA_PERMISO, PERMISO)]},
    {"nombre": "resolver_errores", "pasos": [
        _p(RUTA_RESOLVER, {}),
        _p(RUTA_RESOLVER, {"clave": "x"}),
        _p(RUTA_RESOLVER, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_RESOLVER, {"clave": CLAVE_AVISO}),
        _p(RUTA_REABRIR, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_REABRIR, {"clave": "x"}),
        _p(RUTA_RESOLVER, crudo="{"),
    ]},
    {"nombre": "resolver_bandeja_caida", "caidas": ["GET"], "pasos": [
        _p(RUTA_RESOLVER, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_REABRIR, {"clave": CLAVE_RESUELTO}),
    ]},
    # Un fallo de escritura NO se recuerda como guardado: el segundo envío con la MISMA clave tiene que volver a escribir.
    {"nombre": "editar_reintento_tras_fallo", "caidas_una_vez": ["PATCH"], "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-fallo")),
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-fallo")),
    ]},
    {"nombre": "crear_reintento_tras_fallo", "caidas_una_vez": ["POST"], "pasos": [
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-crear-fallo")),
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-crear-fallo")),
    ]},
    # La regla entera de la App: un envío se recuerda SOLO si `exito` de la App dice que sí. Un par por código; el 2.º envío
    # (misma clave) no debe traer ya_guardado / ya_creada salvo que el 1.º haya sido éxito.
    {"nombre": "editar_reintento_200_guardado", "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-r-200")), _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-r-200"))]},
    {"nombre": "editar_reintento_200_sin_cambios", "pasos": [
        _p(RUTA_EDITAR, {"id": 2, "base": {"instagram": ""}, "cambios": {"instagram": ""}, "clave_envio": "envio-r-sc"}),
        _p(RUTA_EDITAR, {"id": 2, "base": {"instagram": ""}, "cambios": {"instagram": ""}, "clave_envio": "envio-r-sc"})]},
    {"nombre": "editar_reintento_400", "pasos": [
        _p(RUTA_EDITAR, {"id": 2, "base": {"nombre": "Persona de prueba 2"}, "cambios": {"nombre": 7}, "clave_envio": "envio-r-400"}),
        _p(RUTA_EDITAR, {"id": 2, "base": {"nombre": "Persona de prueba 2"}, "cambios": {"nombre": 7}, "clave_envio": "envio-r-400"})]},
    {"nombre": "editar_reintento_404", "pasos": [
        _p(RUTA_PORTAL + "/99/editar", {"id": 99, "base": {"nombre": "x"}, "cambios": {"nombre": "x"}, "clave_envio": "envio-r-404"}),
        _p(RUTA_PORTAL + "/99/editar", {"id": 99, "base": {"nombre": "x"}, "cambios": {"nombre": "x"}, "clave_envio": "envio-r-404"})]},
    {"nombre": "editar_reintento_409", "pasos": [
        _p(RUTA_EDITAR, {"id": 2, "base": {"telefono": "18097770002"}, "cambios": {"telefono": "18097770001"}, "clave_envio": "envio-r-409"}),
        _p(RUTA_EDITAR, {"id": 2, "base": {"telefono": "18097770002"}, "cambios": {"telefono": "18097770001"}, "clave_envio": "envio-r-409"})]},
    {"nombre": "crear_reintento_201", "pasos": [
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-r-c201")), _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-r-c201"))]},
    {"nombre": "crear_reintento_400", "pasos": [
        _p(RUTA_PORTAL, {"cambios": {"nombre": 5}, "clave_envio": "envio-r-c400"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": 5}, "clave_envio": "envio-r-c400"})]},
    {"nombre": "crear_reintento_409", "pasos": [
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Repetida", "telefono": "18097770001"}, "clave_envio": "envio-r-c409"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Repetida", "telefono": "18097770001"}, "clave_envio": "envio-r-c409"})]},
    {"nombre": "crear_reintento_422", "pasos": [
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Corto", "telefono": "12"}, "clave_envio": "envio-r-c422"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Corto", "telefono": "12"}, "clave_envio": "envio-r-c422"})]},
    # Misma clave, cuerpo DISTINTO: es un envío nuevo (la huella del cuerpo decide), no un repetido. El 2.º no trae ya_*.
    {"nombre": "editar_cuerpo_distinto", "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-cd-e")),
        _p(RUTA_EDITAR, {"id": 2, "base": {"instagram": "persona_dos"}, "cambios": {"instagram": "otra_cuenta"},
                         "clave_envio": "envio-cd-e"})]},
    {"nombre": "crear_cuerpo_distinto", "pasos": [
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-cd-c")),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Cuatro", "telefono": "8095550204"}, "clave_envio": "envio-cd-c"})]},
    {"nombre": "quien_del_cuerpo_no_cuenta", "pasos": [
        _p(RUTA_PORTAL, {"quien": "Otra Persona", "cambios": {"nombre": "Quien Cuerpo"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "quien": "Otra Persona", "base": {"nombre": "Persona de prueba 2"},
                                       "cambios": {"nombre": "Quien Cuerpo Dos"}}),
    ]},
]

# UNIÓN (paso 5c, parte 4). Los escenarios de unir van en el modo de unión del doble (`"union": True`, con la tabla de uniones
# en el entorno). Sin esa variable, la App y el programa contestan 503 «sin_registro» sin tocar NocoDB.
RUTA_UNIR = RUTA_PORTAL + "/11/unir"
RUTA_CONTINUAR = RUTA_PORTAL + "/11/unir/continuar"
RUTA_DESHACER = RUTA_PORTAL + "/11/unir/deshacer"
ENTORNO_UNION = {"NOCODB_T_UNIONES_PERSONAS": doble_escrituras.T_UNIONES}
CLAVE_UNION = "union-prueba-0001"          # formato válido (`[A-Za-z0-9_-]{8,64}`)
CLAVE_AVISO_UNION = "aviso-" + "c" * 40    # formato válido de aviso; no existe en el doble

ESCENARIOS_UNION = [
    {"nombre": "unir_sin_registro", "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION}),
        _p(RUTA_CONTINUAR, {}),
        _p(RUTA_DESHACER, {}),
    ]},
    {"nombre": "unir_errores", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_UNIR, {}),
        _p(RUTA_UNIR, {"otra": "x", "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 12, "resoluciones": "x", "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 12, "queda": "x", "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 12, "aviso": "no-es-clave", "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 11, "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 99, "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 12}),
        _p(RUTA_UNIR, {"otra": 12, "clave": "x"}),
        _p(RUTA_UNIR, crudo="{"),
    ]},
    {"nombre": "unir_lectura_caida", "union": True, "entorno": ENTORNO_UNION, "caidas": ["GET"], "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION})]},
    {"nombre": "unir_escritura_caida", "union": True, "entorno": ENTORNO_UNION, "caidas": ["POST"], "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION})]},
    {"nombre": "unir_ok", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION}),
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION}),
    ]},
    {"nombre": "unir_queda_cambio", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "queda": 12, "clave": CLAVE_UNION}),
    ]},
    {"nombre": "unir_con_aviso", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION, "aviso": CLAVE_AVISO_UNION}),
    ]},
    # Una unión que se corta a mitad (la primera escritura PATCH cae una vez): queda «en curso». Después, `continuar` la termina
    # (sin `quien`: la App no lo pasa) y `deshacer` la deshace. Con repetición, cada pedido sigue lo que quedó.
    {"nombre": "unir_a_medias_y_continuar", "union": True, "entorno": ENTORNO_UNION, "caidas_una_vez": ["PATCH"], "pasos": [
        _p(RUTA_UNIR, {"otra": 12, "clave": CLAVE_UNION}),
        _p(RUTA_CONTINUAR, {}),
        _p(RUTA_CONTINUAR, {}),
        _p(RUTA_DESHACER, {}),
        _p(RUTA_DESHACER, {"union": 1, "sobra": 12}),
    ]},
    {"nombre": "continuar_sin_union", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_CONTINUAR, {}),
        _p(RUTA_CONTINUAR, {"aviso": "no-es-clave"}),
        _p(RUTA_CONTINUAR, crudo="{"),
    ]},
    {"nombre": "continuar_lectura_caida", "union": True, "entorno": ENTORNO_UNION, "caidas": ["GET"], "pasos": [
        _p(RUTA_CONTINUAR, {}),
    ]},
    {"nombre": "deshacer_errores", "union": True, "entorno": ENTORNO_UNION, "pasos": [
        _p(RUTA_DESHACER, {}),
        _p(RUTA_DESHACER, {"union": "x"}),
        _p(RUTA_DESHACER, {"sobra": "x"}),
        _p(RUTA_DESHACER, {"aviso": "no-es-clave"}),
        _p(RUTA_DESHACER, crudo="{"),
    ]},
    {"nombre": "deshacer_lectura_caida", "union": True, "entorno": ENTORNO_UNION, "caidas": ["GET"], "pasos": [
        _p(RUTA_DESHACER, {}),
    ]},
]

ESCENARIOS.extend(ESCENARIOS_UNION)

# BORRAR y DEVOLVER una ficha (paso 5c, parte 5). La App pide el permiso `puede_borrar_fichas` antes de reenviar; el programa no lo mira,
# y el generador de la foto lo da por bueno (su driver). Ficha 1: sin paradas (`puede: true`), sin crédito, sin permiso anotado. Ficha 2:
# con crédito (parada 1). Ficha 3: ya guardada aparte (registro `quitada`). Ficha 4: unida a la 1 (parada 5). Ficha 99: no existe.
# Las tablas de envíos y de uniones van en el entorno de estos escenarios (sin ellas, «revisar» cuenta esas cifras como no medidas).
CLAVE_BORRAR = "borrado-prueba-0001"     # formato válido (`[A-Za-z0-9_-]{8,64}`)
CLAVE_BORRAR_2 = "borrado-prueba-0002"
ENTORNO_BORRAR = {"NOCODB_T_MERCADEO_ENVIOS": doble_nocodb.T_MERCADEO_ENVIOS, "NOCODB_T_UNIONES_PERSONAS": doble_nocodb.T_UNIONES}

ESCENARIOS_BORRAR = [
    {"nombre": "borrar_ok", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/1/devolver", {}),
        _p(RUTA_PORTAL + "/1/devolver", {}),
    ]},
    {"nombre": "borrar_paradas", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/2/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/3/borrar", {"clave": CLAVE_BORRAR_2}),
        _p(RUTA_PORTAL + "/4/borrar", {"clave": CLAVE_BORRAR_2}),
    ]},
    {"nombre": "borrar_errores", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {}),
        _p(RUTA_PORTAL + "/1/borrar", {"clave": "x"}),
        _p(RUTA_PORTAL + "/1/borrar", {"clave": 7}),
        _p(RUTA_PORTAL + "/99/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/1/borrar", crudo="{"),
    ]},
    {"nombre": "borrar_sin_registro", "entorno": dict(ENTORNO_BORRAR, NOCODB_T_PERSONAS_QUITADAS=""), "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
    ]},
    {"nombre": "borrar_lectura_caida", "entorno": ENTORNO_BORRAR, "caidas": ["GET"], "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR})]},
    {"nombre": "borrar_escritura_caida", "entorno": ENTORNO_BORRAR, "caidas": ["POST"], "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR})]},
    {"nombre": "borrar_patch_caida", "entorno": ENTORNO_BORRAR, "caidas": ["PATCH"], "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR})]},
    # Un fallo a mitad (la primera escritura PATCH cae una vez): el mismo borrado, con la misma clave, termina el borrado.
    {"nombre": "borrar_repite_tras_fallo", "entorno": ENTORNO_BORRAR, "caidas_una_vez": ["PATCH"], "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
    ]},
    # Una clave ya usada para OTRA ficha: 409 `clave_repetida` (el registro de la 1.ª ficha tiene esa clave).
    {"nombre": "borrar_clave_repetida", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/2/borrar", {"clave": CLAVE_BORRAR}),
    ]},
    # Un borrado a medias (su PATCH cae una vez: queda `quitando`) y otro intento con OTRA clave sobre la misma ficha: 409 `otra_operacion`.
    {"nombre": "borrar_otra_operacion", "entorno": ENTORNO_BORRAR, "caidas_una_vez": ["PATCH"], "pasos": [
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR}),
        _p(RUTA_PORTAL + "/1/borrar", {"clave": CLAVE_BORRAR_2}),
    ]},
    {"nombre": "devolver_errores", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/1/devolver", {}),
        _p(RUTA_PORTAL + "/4/devolver", {}),
        _p(RUTA_PORTAL + "/99/devolver", {}),
        _p(RUTA_PORTAL + "/3/devolver", crudo="{"),
    ]},
    {"nombre": "devolver_sin_registro", "entorno": dict(ENTORNO_BORRAR, NOCODB_T_PERSONAS_QUITADAS=""), "pasos": [
        _p(RUTA_PORTAL + "/3/devolver", {}),
    ]},
    {"nombre": "devolver_ok", "entorno": ENTORNO_BORRAR, "pasos": [
        _p(RUTA_PORTAL + "/3/devolver", {}),
        _p(RUTA_PORTAL + "/3/devolver", {}),
    ]},
    {"nombre": "devolver_lectura_caida", "entorno": ENTORNO_BORRAR, "caidas": ["GET"], "pasos": [
        _p(RUTA_PORTAL + "/3/devolver", {})]},
    {"nombre": "devolver_escritura_caida", "entorno": ENTORNO_BORRAR, "caidas": ["PATCH"], "pasos": [
        _p(RUTA_PORTAL + "/3/devolver", {})]},
]
ESCENARIOS.extend(ESCENARIOS_BORRAR)

# Pasos que la App no contesta igual (no tiene identidad): ver `es_dorado`.


# Parte 7: los pasos de SESIÓN (check-in) llevan tipo «C». Un paso es dorado si su tipo es el de su ruta (`tipo_de_ruta`, «A» por defecto),
# así un paso de tipo «A» en una ruta «C» no entra en la foto (es un caso de I1, no de la App).
def _c(ruta, cuerpo=None, crudo=None, llave="portal", quien=QUIEN_DORADO, metodo="POST", nombre=None):
    """Un paso de sesión (check-in, tipo «C»): `_p` con el tipo de la ruta y el verbo."""
    paso = _p(ruta, cuerpo=cuerpo, crudo=crudo, llave=llave, quien=quien, tipo="C", nombre=nombre, metodo=metodo)
    paso["tipo_de_ruta"] = "C"
    return paso


def es_dorado(paso):
    """¿Este paso se compara con la App? Solo con llave del portal, identidad (quien no vacío) y el tipo que pide su ruta («A» en el
    portal, «C» en el check-in)."""
    return paso.get("llave") == "portal" and bool(paso.get("quien")) and paso.get("tipo") == paso.get("tipo_de_ruta", "A")


# Parte 7 (check-in, tipo «C»): crear (POST /api/personas) y editar (PATCH /api/personas/<id>). Cada código que da crear tiene un par de
# envíos con la misma clave (la regla de «envío hecho» de la App, `una_vez("persona")`). Editar no lleva `clave_envio`: la App no la usa.
RUTA_CHECKIN = "/api/personas"
RUTA_CHECKIN_EDITAR = "/api/personas/2"
ESCENARIOS_CHECKIN = [
    {"nombre": "checkin_crear_ok", "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "Checkin Uno", "telefono": "8095550401", "clave_envio": "envio-ck-1"}),
        _c(RUTA_CHECKIN, {"nombre": "Checkin Uno", "telefono": "8095550401", "clave_envio": "envio-ck-1"})]},
    {"nombre": "checkin_crear_cuerpo_distinto", "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "Checkin Dos", "telefono": "8095550402", "clave_envio": "envio-ck-2"}),
        _c(RUTA_CHECKIN, {"nombre": "Checkin Tres", "clave_envio": "envio-ck-2"})]},
    {"nombre": "checkin_crear_fallo", "caidas_una_vez": ["POST"], "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "Checkin Cuatro", "telefono": "8095550404", "clave_envio": "envio-ck-3"}),
        _c(RUTA_CHECKIN, {"nombre": "Checkin Cuatro", "telefono": "8095550404", "clave_envio": "envio-ck-3"})]},
    {"nombre": "checkin_crear_400", "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "", "clave_envio": "envio-ck-400"}),
        _c(RUTA_CHECKIN, {"nombre": "", "clave_envio": "envio-ck-400"})]},
    {"nombre": "checkin_crear_409", "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "Checkin Repetido", "telefono": "18097770001", "clave_envio": "envio-ck-409"}),
        _c(RUTA_CHECKIN, {"nombre": "Checkin Repetido", "telefono": "18097770001", "clave_envio": "envio-ck-409"})]},
    {"nombre": "checkin_crear_lectura_caida", "caidas": ["GET"], "pasos": [
        _c(RUTA_CHECKIN, {"nombre": "Checkin Caido", "telefono": "8095550405", "clave_envio": "envio-ck-500"}),
        _c(RUTA_CHECKIN, {"nombre": "Checkin Caido", "telefono": "8095550405", "clave_envio": "envio-ck-500"})]},
    {"nombre": "checkin_crear_ilegible", "pasos": [_c(RUTA_CHECKIN, crudo="{")]},
    {"nombre": "checkin_crear_lista", "pasos": [_c(RUTA_CHECKIN, [1, 2])]},
    {"nombre": "checkin_crear_sin_cuerpo", "pasos": [_c(RUTA_CHECKIN, crudo="")]},
    {"nombre": "checkin_editar_ok", "pasos": [_c(RUTA_CHECKIN_EDITAR, {"instagram": "checkin_dos"}, metodo="PATCH")]},
    {"nombre": "checkin_editar_nombre_vacio", "pasos": [_c(RUTA_CHECKIN_EDITAR, {"nombre": ""}, metodo="PATCH")]},
    {"nombre": "checkin_editar_telefono_repetido", "pasos": [_c(RUTA_CHECKIN_EDITAR, {"telefono": "18097770001"}, metodo="PATCH")]},
    {"nombre": "checkin_editar_ilegible", "pasos": [_c(RUTA_CHECKIN_EDITAR, crudo="x", metodo="PATCH")]},
    {"nombre": "checkin_editar_caida", "caidas": ["PATCH"], "pasos": [_c(RUTA_CHECKIN_EDITAR, {"instagram": "checkin_caido"}, metodo="PATCH")]},
    {"nombre": "checkin_editar_lectura_caida", "caidas": ["GET"], "pasos": [
        _c(RUTA_CHECKIN_EDITAR, {"instagram": "checkin_lectura"}, metodo="PATCH")]},
    {"nombre": "checkin_editar_sin_ficha", "pasos": [_c("/api/personas/99", {"instagram": "x"}, metodo="PATCH")]},
]
ESCENARIOS.extend(ESCENARIOS_CHECKIN)




AHORA = "<ahora>"


def es_clave_de_hora(clave):
    """Las claves donde se guarda la hora de la corrida: `cuando` (anotaciones), `quitada_el` (la marca de una ficha borrada, parte 5) y
    las que acaban en `_en` (`creada_en`, `terminada_en`, `deshecha_en`, `resuelto_en`, `devuelta_en`: el registro de uniones, de
    «Por resolver» y de borrados)."""
    return clave == "cuando" or clave == "quitada_el" or clave.endswith("_en")


def normalizar(valor):
    """Quita de un registro lo que depende de la hora de la corrida: el valor de cualquier clave de hora (`es_clave_de_hora`) que sea
    una fecha ISO se cambia por «<ahora>». Lo aplican la foto y la prueba, a los dos lados, así que la comparación no ve la hora. Lo que
    sí se comprueba (en `test_portal_escrituras.py`) es que ese valor sea una fecha ISO con zona y no otra cosa."""
    if isinstance(valor, dict):
        return {k: (AHORA if es_clave_de_hora(k) and _es_iso(v) else normalizar(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [normalizar(v) for v in valor]
    return valor


def _es_iso(v):
    from datetime import datetime
    if not isinstance(v, str):
        return False
    try:
        return datetime.fromisoformat(v) is not None and ("+" in v or "Z" in v)
    except ValueError:
        return False


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _valor_llave(simbolo):
    if simbolo in VALORES:
        return VALORES[simbolo]
    if simbolo == "vacia":
        return ""
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def cabeceras_del_paso(paso):
    """Las cabeceras que manda un paso (sin `Content-Length`, que pone `urllib`). El `quien` va como UTF-8 en bytes: se pasa como
    texto «latin-1» porque `http.client` solo escribe latin-1; así la cabecera llega con los bytes UTF-8 de `quien`."""
    cabeceras = {"Content-Type": "application/json"}
    if paso.get("llave") is not None:
        cabeceras[CABECERA_LLAVE] = _valor_llave(paso["llave"])
    if paso.get("quien") is not None:
        cabeceras[CABECERA_QUIEN] = paso["quien"].encode("utf-8").decode("latin-1")
    if paso.get("tipo") is not None:
        cabeceras[CABECERA_TIPO] = paso["tipo"]
    return cabeceras


def datos_del_paso(paso):
    if "crudo" in paso:
        return paso["crudo"].encode("utf-8")
    return json.dumps(paso["cuerpo"]).encode("utf-8")


def _pedir(puerto, paso):
    datos = datos_del_paso(paso)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, paso["ruta"]), data=datos, method=paso.get("metodo", "POST"),
                                 headers=cabeceras_del_paso(paso))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            codigo, bruto = r.status, r.read()
    except urllib.error.HTTPError as e:
        codigo, bruto = e.code, e.read()
    try:
        cuerpo = json.loads(bruto.decode("utf-8"))
    except ValueError:
        cuerpo = {"__no_json__": bruto.decode("utf-8", "replace")}
    return codigo, cuerpo


def _esperar_arriba(puerto, proceso):
    """Espera a que el servidor conteste. `config` sin llave da 401 y no lee NocoDB: contestar con cualquier código es estar arriba."""
    for _ in range(100):
        if proceso.poll() is not None:
            raise RuntimeError("el servidor se cerró al arrancar (código %s)" % proceso.returncode)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/servicio/personas/config" % puerto, timeout=5).close()
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("el servidor no levantó")


def ejecutar(escenario, comando, cwd, entorno_extra=None):
    """Corre los pasos de un escenario contra `comando` (un servidor en PORT, con NOCODB_BASE puesto al doble). Devuelve
    (pasos, errores_del_doble). Cada paso dice código, respuesta y los pedidos que llegaron al doble en ese paso. El proceso y el doble
    se cierran al terminar, pase lo que pase."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()), caidas_una_vez=escenario.get("caidas_una_vez", ()),
                                             union=escenario.get("union", False))
    url_doble = doble.arrancar()
    puerto = _puerto_libre()
    entorno = dict(ENTORNO_MINIMO)
    entorno.update(ENTORNO_BASE)
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(escenario.get("entorno", {}))
    entorno.update(entorno_extra or {})
    with tempfile.TemporaryFile() as errores_de_arranque:
        proceso = subprocess.Popen(comando, cwd=cwd, env=entorno, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errores_de_arranque)
        try:
            _esperar_arriba(puerto, proceso)
            doble.pedidos.clear()
            pasos = []
            for paso in escenario["pasos"]:
                antes = len(doble.pedidos)
                codigo, cuerpo = _pedir(puerto, paso)
                registro = {"ruta": paso["ruta"], "status": codigo, "respuesta": cuerpo, "pedidos": doble.pedidos[antes:]}
                if "crudo" in paso:
                    registro["crudo"] = paso["crudo"]
                else:
                    registro["cuerpo"] = paso["cuerpo"]
                pasos.append(registro)
            return pasos, list(doble.errores)
        finally:
            proceso.terminate()
            proceso.wait(timeout=10)
            doble.parar()
