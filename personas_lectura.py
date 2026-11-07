# -*- coding: utf-8 -*-
"""LAS CINCO RUTAS DE LECTURA DE PERSONAS PARA MERCADEO (P2 de `disenos/mercadeo-programa-aparte/DISENO.md`, sección 4.8).

Las llama Mercadeo, cuando pase al programa aparte, con la llave `PERSONAS_LECTURA_LLAVE` (cabecera `X-Personas-Lectura-Llave`,
permiso `lee_personas_mercadeo`). En P2 nadie las llama todavía.

Rutas (todas de SOLO LECTURA: ninguna escribe, ninguna pasa un `PATCH`, `POST` o `DELETE` a NocoDB):
  POST /api/servicio/personas/identidad   {"identidad": "<teléfono o ID de WhatsApp>"}  → clave, número y fichas de ESA identidad
  POST /api/servicio/personas/fichas      {}                                             → TODA la tabla de fichas, sin filtrar
  POST /api/servicio/personas/pagina      {q, orden, desde, limite, ver, col}           → una página de la lista (`portal_personas_pagina`)
  POST /api/servicio/personas/anotaciones {campos?, where?}                             → filas de la tabla de anotaciones
  GET  /api/servicio/personas/config                                                    → constantes `PORTAL_*` y nombres de error

Cada función devuelve `(codigo, cuerpo)`. `s` es el módulo `server`: se le pide cada nombre al momento de la llamada, igual que la
puerta `mercadeo_personas.Puerta`, para que lo que una prueba reemplaza en `server` lo vea la ruta.

Qué sale por cada una (campos exactos):
  · fichas: todas las columnas que NocoDB devuelve para `personas` sin `fields`, leídas con el lector ESTRICTO de Personas
    (`personas._anotaciones_leer_tabla`, el que usan leads y embudo). Salen TODAS las filas, también las unidas y las guardadas
    (`quitada_el`): el filtro se queda en cada consumidor.
  · identidad: `clave` (texto o `null`), `numero` (texto o `null`), `fichas` (filas de `fichas` cuyo teléfono da esa clave, sin las
    guardadas aparte `quitada_el`). Las dos lecturas (el número y las fichas) son el lector ESTRICTO de Personas.
  · anotaciones: las columnas de `campos` (o todas si no hay `campos`) de `T_PERSONAS_ANOTACIONES`, filtradas por `where`, leídas
    con el mismo lector estricto que fichas.
  · pagina: la salida de `personas.portal_personas_pagina` leyendo con el lector ESTRICTO de la lista (`personas._portal_leer_todas_estricta`)
    y el ESTRICTO de asistencias (`personas._portal_leer_asistencias_estricta`), no con los de producción. Es la misma salida que la función
    directa con esos dos lectores; los lectores de producción no cambian.
  · config: `PORTAL_PAGINA`, `PORTAL_PAGINA_MAX`, `PORTAL_BUSQUEDA_MAX`, `PORTAL_ORDEN_POR_OMISION` y `errores` (los dos nombres).

Errores de lectura: `identidad`, `fichas`, `anotaciones` y `pagina` contestan 502 con `ERROR_FIJO_LECTURA` cuando el lector estricto no puede
dar la tabla COMPLETA (respuesta sin `pageInfo`, total que no cuadra o que no es entero, fila ilegible, páginas que no terminan, error de
NocoDB): nunca 200 con una lista corta. `pagina` lee también `asistencias` con el lector ESTRICTO (`_portal_leer_asistencias_estricta`, con tope
de páginas): si no las puede dar completas, 502 con el mismo mensaje fijo; nunca 200 con `actividad_vieja`. El lector laxo de asistencias
(`_portal_leer_asistencias`, sin tope) sigue en la lista de producción y en la ficha abierta, y esta ruta no lo usa.

`where` de anotaciones: lista de tripletas `[campo, operador, valor]`, unidas con `~and`. El campo es un identificador; el operador
es uno de `OPERADORES`; el valor es texto de hasta `VALOR_MAX` caracteres SIN `(`, `)`, `,` ni `~` (esos caracteres romperían la
sintaxis de NocoDB). Cualquier otra forma es 400 sin leer nada.
"""
import re

import personas

OPERADORES = ("eq", "neq", "gt", "gte", "lt", "lte", "like")
VALOR_MAX = 200
_CAMPO = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_VALOR_PROHIBIDO = re.compile(r"[(),~]")
ERRORES_CON_NOMBRE = ("PortalNoCargo", "_NoSeSupo")
ERROR_FIJO_LECTURA = {"ok": False, "error": "No se pudo leer Personas. Inténtalo en un momento."}


def _pedido_identidad(cuerpo):
    if isinstance(cuerpo, dict) and set(cuerpo) == {"identidad"} and isinstance(cuerpo["identidad"], str) and cuerpo["identidad"].strip():
        return cuerpo["identidad"].strip(), None
    return None, "El pedido es {\"identidad\": \"…\"}: el teléfono o el ID de WhatsApp, en texto."


def _fichas_para_numero(s, where):
    """Lo que pide la regla de identidades para sacar el número (`Id`, `telefono`, `bsuid`), con el lector ESTRICTO de Personas."""
    return personas._anotaciones_leer_tabla(s.T_PERSONAS, "Id,telefono,bsuid", where)


def identidad(s, cuerpo):
    ident, error = _pedido_identidad(cuerpo)
    if error:
        return 400, {"ok": False, "error": error}
    try:
        clave = personas.clave_telefono(ident)
        numero = personas.numeros_de_identidades_estricto([ident], lambda where: _fichas_para_numero(s, where))[ident]
        fichas = []
        if clave is not None:
            fichas = [f for f in personas._anotaciones_leer_tabla(s.T_PERSONAS)
                      if not personas.ficha_quitada(f) and personas._telefono_de_ficha(f.get("telefono")) == clave]
    except Exception:                                    # noqa: BLE001 — el texto del error no sale (puede traer datos de NocoDB)
        return 502, dict(ERROR_FIJO_LECTURA)
    return 200, {"clave": clave, "numero": numero, "fichas": fichas}


def fichas(s, cuerpo):
    if cuerpo != {}:
        return 400, {"ok": False, "error": "El pedido de fichas es {}: no lleva parámetros."}
    try:
        filas = personas._anotaciones_leer_tabla(s.T_PERSONAS)
    except Exception:                                    # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: no hay lista completa
        return 502, dict(ERROR_FIJO_LECTURA)
    return 200, filas


def _campos_validos(campos):
    if campos is None:
        return None
    if not isinstance(campos, str):
        return "campos"
    partes = [c.strip() for c in campos.split(",")]
    if not partes or any(not _CAMPO.match(c) for c in partes):
        return "campos"
    return ",".join(partes)


def _where_valido(where):
    if where is None:
        return None, None
    if not isinstance(where, list) or not where:
        return None, "where"
    trozos = []
    for t in where:
        if not (isinstance(t, list) and len(t) == 3):
            return None, "where"
        campo, op, valor = t
        if not (isinstance(campo, str) and _CAMPO.match(campo)) or op not in OPERADORES:
            return None, "where"
        if not isinstance(valor, str) or len(valor) > VALOR_MAX or _VALOR_PROHIBIDO.search(valor):
            return None, "where"
        trozos.append("(%s,%s,%s)" % (campo, op, valor))
    return "~and".join(trozos), None


def anotaciones(s, cuerpo):
    if not isinstance(cuerpo, dict) or not set(cuerpo) <= {"campos", "where"}:
        return 400, {"ok": False, "error": "El pedido de anotaciones es {campos?, where?}."}
    campos = _campos_validos(cuerpo.get("campos"))
    if campos == "campos":
        return 400, {"ok": False, "error": "campos: nombres de columna separados por coma."}
    where, error = _where_valido(cuerpo.get("where"))
    if error:
        return 400, {"ok": False, "error": "where: lista de [campo, operador, valor] con operadores conocidos y valores sin ( ) , ~."}
    if not s.T_PERSONAS_ANOTACIONES:
        return 503, {"ok": False, "error": "La tabla de anotaciones no está configurada."}
    try:
        filas = personas._anotaciones_leer_tabla(s.T_PERSONAS_ANOTACIONES, campos, where)
    except Exception:                                    # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: no hay lista completa
        return 502, dict(ERROR_FIJO_LECTURA)
    return 200, filas


def pagina(s, cuerpo):
    claves = {"q", "orden", "desde", "limite", "ver", "col"}
    if not isinstance(cuerpo, dict) or not set(cuerpo) <= claves:
        return 400, {"ok": False, "error": "El pedido de pagina es {q?, orden?, desde?, limite?, ver?, col?}."}
    q = cuerpo.get("q", "")
    orden = cuerpo.get("orden", "asc")
    desde = cuerpo.get("desde", 0)
    limite = cuerpo.get("limite", personas.PORTAL_PAGINA)
    ver = cuerpo.get("ver")
    col = cuerpo.get("col", personas.PORTAL_ORDEN_POR_OMISION)
    malos = (not isinstance(q, str) or len(q) > personas.PORTAL_BUSQUEDA_MAX
             or orden not in ("asc", "desc")
             or isinstance(desde, bool) or not isinstance(desde, int) or desde < 0
             or isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= personas.PORTAL_PAGINA_MAX
             or col not in personas.PORTAL_ORDENABLES
             or (ver is not None and (isinstance(ver, bool) or not isinstance(ver, int))))
    if malos:
        return 400, {"ok": False, "error": "Parámetros de la página fuera de forma."}
    try:
        salida = personas.portal_personas_pagina(q, orden, desde, limite, ver=ver, col=col, leer=personas._portal_leer_todas_estricta,
                                                 leer_asistencias=personas._portal_leer_asistencias_estricta)
    except Exception as e:                               # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: no hay lista completa
        if type(e).__name__ in ERRORES_CON_NOMBRE:
            return 502, dict(ERROR_FIJO_LECTURA)
        return 502, dict(ERROR_FIJO_LECTURA)
    return 200, salida


def config(s):
    return 200, {"PORTAL_PAGINA": personas.PORTAL_PAGINA,
                 "PORTAL_PAGINA_MAX": personas.PORTAL_PAGINA_MAX,
                 "PORTAL_BUSQUEDA_MAX": personas.PORTAL_BUSQUEDA_MAX,
                 "PORTAL_ORDEN_POR_OMISION": personas.PORTAL_ORDEN_POR_OMISION,
                 "errores": list(ERRORES_CON_NOMBRE)}
