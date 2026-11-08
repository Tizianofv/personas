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

Lo que NO está aquí (declarado en `servidor.PORTAL_FUERA_DEL_PROGRAMA`): `entrada/cuadro`. `borrar/revisar` sí está (parte 5): la App
lo contesta con 502 si NocoDB falla al leer la ficha (el 404 de «ficha» es solo para `ficha`, como en la App: su `m` es la ficha).

Parte 6 (tipo C): `buscar` (`GET /api/personas?q=`) e `instrumentos` (`GET /api/persona-instrumentos`). No son del portal: la App las
contesta en `do_GET`, bajo `autorizado()`, y su error no pasa por `portal_personas_get`. Su error es el de `do_GET` de la App: 500 con
el texto de la excepción (`{"error": str(e)}`), no el 502 del portal. Ver `DE_SESION`.
"""
import re

import base
import personas

ERROR_LECTURA = "No se pudo leer la base de personas. Inténtalo en un momento."
FICHA_NO_ESTA = "Esa persona ya no está en la base."
# Las lecturas de tipo C (parte 6): sus errores salen como en el `do_GET` de la App (500 con el texto), no como en el portal (502).
DE_SESION = ("buscar", "instrumentos")


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


def _borrar_revisar(grupos, consulta):
    """`GET /api/portal-personas/<id>/borrar/revisar`: qué pasaría al borrar la ficha, sin escribir (parte 5). La App pide el permiso
    `puede_borrar_fichas` antes; aquí no se mira. 404 de la función si la ficha no está (cuerpo de `revisar_borrado`)."""
    return personas.revisar_borrado(int(grupos[0]))


def _buscar(grupos, consulta):
    """`GET /api/personas?q=` (tipo C): el buscador del check-in y de los selectores. Igual que la App con la bandera
    `PROGRAMA_REGISTRO_LECTURAS_PERSONAS` APAGADA (su `do_GET`, línea 16226 en 594ec12): con menos de 2 caracteres (ya recortados)
    contesta `[]` sin leer NocoDB; si no, `personas.buscar_personas`, la función que la App llama en esa ruta. Con la bandera ENCENDIDA
    la App va por `buscar_de_personas` (el servicio de Personas por red); este programa no lo replica: sirve el camino de bandera apagada."""
    busq = (consulta.get("q") or "").strip()
    if len(busq) < 2:
        return 200, {"personas": []}
    return 200, {"personas": personas.buscar_personas(busq)}


def _instrumentos(grupos, consulta):
    """`GET /api/persona-instrumentos` (tipo C): las opciones del MultiSelect `instrumento` de Personas. Igual que
    `opciones_instrumento_persona` de la App: `_opciones_select(T_PERSONAS, "instrumento")`, la misma lectura de `base.py`."""
    return 200, {"instrumentos": base._opciones_select(base.T_PERSONAS, "instrumento")}


FUNCIONES = {
    "lista": _lista, "ficha": _ficha, "nueva": _nueva, "borradas": _borradas,
    "por_resolver": _por_resolver, "unir_revisar": _unir_revisar, "borrar_revisar": _borrar_revisar,
    "buscar": _buscar, "instrumentos": _instrumentos,
}


def _error(nombre, e):
    """Lo que contesta cada lectura cuando lanza. Las del portal, como `portal_personas_get`; las de tipo C, como `do_GET` de la App."""
    if nombre in DE_SESION:
        return 500, {"error": str(e)}
    if isinstance(e, base.ErrorDeNocodb):
        if nombre == "ficha" and e.status == 404:
            return 404, {"ok": False, "error": FICHA_NO_ESTA}
        return 502, {"ok": False, "error": ERROR_LECTURA}
    if isinstance(e, personas.PortalNoCargo):
        return 502, {"ok": False, "error": str(e) + " Inténtalo otra vez."}
    return 502, {"ok": False, "error": ERROR_LECTURA}     # la pantalla dice que falló; nunca una lista corta


def responder(nombre, grupos, consulta):
    """Corre la lectura `nombre` y devuelve `(código, cuerpo)`, con los mismos errores que la App (ver la docstring del módulo)."""
    try:
        return FUNCIONES[nombre](grupos, consulta)
    except Exception as e:  # noqa: BLE001 — cada error se contesta según la tabla de `_error`
        return _error(nombre, e)
