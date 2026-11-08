# -*- coding: utf-8 -*-
"""Las lecturas del portal que sirve el programa (paso 5c, partes 1 y 2): la misma lógica que `Handler.portal_personas_get`
de la App de registro (`594ec12`), SIN su puerta de sesión (esa la mira la App antes de reenviar).

`responder(nombre, grupos, consulta)` devuelve `(código, cuerpo)`, lo que la App mandaría con `send_json`. `nombre` es uno de
los de `servidor.PORTAL_LECTURA`; `grupos` son los grupos de la ruta (el número de la ficha, si lo tiene); `consulta` es el
diccionario de la URL (`dict(parse_qsl(...))`, como la App).

Los errores siguen el mismo orden que la App: primero los 400 de validación; después, lo que la función lance:
  - `ErrorDeNocodb` 404 en la ficha: 404 «Esa persona ya no está en la base.»
  - `ErrorDeNocodb` en cualquier otra: 502 «No se pudo leer la base de personas…»
  - `PortalNoCargo`: 502 con su texto y «Inténtalo otra vez.»
  - cualquier otra excepción: 502 con el texto genérico.
No se escriben logs (la App imprime el tipo de error; aquí no, para no sacar datos de clientes).

Lo que NO está aquí (declarado en `servidor.PORTAL_FUERA_DEL_PROGRAMA`): `entrada/cuadro` y `borrar/revisar`.
"""
import re

import base
import personas

ERROR_LECTURA = "No se pudo leer la base de personas. Inténtalo en un momento."
FICHA_NO_ESTA = "Esa persona ya no está en la base."


def _lista(grupos, consulta):
    """`GET /api/portal-personas`: la lista con búsqueda, orden y paginación (la App valida antes de leer)."""
    orden = consulta.get("orden") or "asc"
    if orden not in ("asc", "desc"):
        return 400, {"error": "orden no válido (asc o desc)"}
    col = consulta.get("col") or personas.PORTAL_ORDEN_POR_OMISION
    if col not in personas.PORTAL_ORDENABLES:
        return 400, {"error": "col no válida (una de: " + ", ".join(personas.PORTAL_ORDENABLES) + ")"}
    try:
        desde = int(consulta.get("desde") or 0)
        limite = int(consulta.get("limite") or personas.PORTAL_PAGINA)
    except ValueError:
        return 400, {"error": "desde y limite tienen que ser números"}
    if desde < 0 or not 1 <= limite <= personas.PORTAL_PAGINA_MAX:
        return 400, {"error": "desde o limite fuera de rango"}
    ver = consulta.get("ver")
    if ver is not None and not re.fullmatch(r"\d{1,9}", ver):
        return 400, {"error": "ver tiene que ser el número de una persona"}
    return 200, personas.portal_personas_pagina(consulta.get("q") or "", orden, desde, limite,
                                                int(ver) if ver is not None else None, col)


def _ficha(grupos, consulta):
    """`GET /api/portal-personas/<id>`: la ficha de una persona por su `Id`."""
    return 200, personas.portal_persona_ficha(int(grupos[0]))


def _nueva(grupos, consulta):
    """`GET /api/portal-personas/nueva`: la ficha vacía de «+ Nueva persona»."""
    return 200, personas.portal_persona_nueva()


def _borradas(grupos, consulta):
    """`GET /api/portal-personas/borradas`: la lista de fichas guardadas aparte que se pueden devolver."""
    return personas.listar_borradas()


def _por_resolver(grupos, consulta):
    """`GET /api/portal-personas/por-resolver`: lo que falta decidir y lo ya marcado."""
    return 200, personas.portal_por_resolver()


def _unir_revisar(grupos, consulta):
    """`GET /api/portal-personas/<id>/unir/revisar?otra=<id>`: qué pasaría al unir dos fichas, sin escribir nada."""
    otra = consulta.get("otra")
    if otra is None or not re.fullmatch(r"\d{1,9}", otra):
        return 400, {"ok": False, "error": "otra tiene que ser el número de la otra ficha"}
    return personas.revisar_union(int(grupos[0]), int(otra))


FUNCIONES = {
    "lista": _lista, "ficha": _ficha, "nueva": _nueva, "borradas": _borradas,
    "por_resolver": _por_resolver, "unir_revisar": _unir_revisar,
}


def responder(nombre, grupos, consulta):
    """Corre la lectura `nombre` y devuelve `(código, cuerpo)`, con los mismos errores que la App (ver la docstring del módulo)."""
    try:
        return FUNCIONES[nombre](grupos, consulta)
    except base.ErrorDeNocodb as e:
        if nombre == "ficha" and e.status == 404:
            return 404, {"ok": False, "error": FICHA_NO_ESTA}
        return 502, {"ok": False, "error": ERROR_LECTURA}
    except personas.PortalNoCargo as e:
        return 502, {"ok": False, "error": str(e) + " Inténtalo otra vez."}
    except Exception:  # noqa: BLE001 — la pantalla dice que falló; nunca una lista corta
        return 502, {"ok": False, "error": ERROR_LECTURA}
