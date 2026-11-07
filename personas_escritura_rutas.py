# -*- coding: utf-8 -*-
"""ESCRITURAS DE FICHAS PARA REGISTRO, en el programa de Personas: cara, nueva y editar (paso 5b de
`disenos/personas-programa-aparte/DISENO.md`). Son las tres rutas que la App de registro (`0b48b5d`,
`personas_escritura_rutas.py`) ya sirve como servicio, con las mismas respuestas.

Rutas (en `ESCRITURA_RUTAS` de `servidor.py`). Cabecera `X-Personas-Registro-Escritura-Llave`, variable
`PERSONAS_REGISTRO_ESCRITURA_LLAVE`. La llave se mira ANTES de leer el cuerpo: sin ella, con otra, con la de Mercadeo
o con la de lectura de Registro, o con la variable vacía: 401 y no se lee ni se escribe nada.
  POST /api/servicio/personas/cara     {"persona_id": <entero>, "vec": [<128 números>]}  → 200 {"ok": true, "ranuras": <entero>}
  POST /api/servicio/personas/nueva    {"nombre": "<texto>", ...campos de la ficha}      → 200 {"ok": true, "persona": <ficha>}
  POST /api/servicio/personas/editar   {"persona_id": <entero>, "datos": {...}}          → 200 {"ok": true, "persona": <ficha>}

Si Personas no puede escribir o leer, la respuesta es 502 con «No se guardó» (nunca 200). Un pedido malo es 400 y no se
escribe. Una ficha unida o guardada aparte no admite cambio de cara: 409.

La cabecera se toma del despacho de la App (`Handler.personas_escritura_post`). El docstring de la App dice otra cabecera
(`X-Personas-Registro-Llave`), y eso está mal allí: no es la que el despacho mira.

Cada función devuelve `(codigo, cuerpo)` y recibe `s`: el módulo `personas_escrituras`, que tiene `guardar_cara`,
`crear_persona`, `editar_persona`, `PersonaRechazada`, `FichaUnida`, `FichaQuitada`, `CARA_DIMS` y `sonda_de_tabla`.
Lo que cambia respecto de la App: la sonda de `nueva` se llama como `s.sonda_de_tabla()` (la App la pide por
`s.puerta_personas`, que es la misma función de `personas.py`).
"""

ERROR_NO_SE_GUARDO = "No se guardó. Personas no responde. Inténtalo en un momento."


def _entero_positivo(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def cara(s, cuerpo):
    if not isinstance(cuerpo, dict) or set(cuerpo) != {"persona_id", "vec"} or not _entero_positivo(cuerpo["persona_id"]):
        return 400, {"ok": False, "error": "El pedido de cara es {persona_id: entero, vec: [números]}."}
    vec = cuerpo["vec"]
    if not isinstance(vec, list) or len(vec) != s.CARA_DIMS or not all(_numero(x) for x in vec):
        return 400, {"ok": False, "error": "vec son %d números." % s.CARA_DIMS}
    try:
        ranuras = s.guardar_cara(cuerpo["persona_id"], vec)
    except (s.FichaUnida, s.FichaQuitada):
        return 409, {"ok": False, "error": "La ficha está unida o guardada aparte: no admite cambio de cara. No se guardó."}
    except Exception:  # noqa: BLE001 — cualquier fallo de Personas: no se guardó, y se dice
        return 502, {"ok": False, "error": ERROR_NO_SE_GUARDO}
    return 200, {"ok": True, "ranuras": ranuras}


def nueva(s, cuerpo):
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("nombre"), str):
        return 400, {"ok": False, "error": "El pedido de nueva es una ficha con «nombre»."}
    try:
        # G-C6: antes de escribir, una lectura de la tabla. Si Personas no contesta, no sale ningún POST. (Frontera: si la lectura
        # pasa y el POST falla después, el POST SÍ salió.) La ruta no toca la tabla: la lee `personas.sonda_de_tabla`.
        s.sonda_de_tabla()
        rec = s.crear_persona(cuerpo)
    except s.PersonaRechazada as e:          # el número o el correo ya es de otra ficha: no se creó nada
        return e.codigo, e.datos
    except ValueError as e:                  # p. ej. nombre vacío: pedido malo
        return 400, {"ok": False, "error": str(e)}
    except Exception:  # noqa: BLE001
        return 502, {"ok": False, "error": ERROR_NO_SE_GUARDO}
    if isinstance(rec, dict) and rec.get("_sin_confirmar"):   # la ficha nació y no se pudo confirmar: no es un «guardado»
        return 502, rec["_sin_confirmar"]
    return 200, {"ok": True, "persona": rec}


def editar(s, cuerpo):
    if not isinstance(cuerpo, dict) or set(cuerpo) != {"persona_id", "datos"} or not _entero_positivo(cuerpo["persona_id"]) \
            or not isinstance(cuerpo["datos"], dict):
        return 400, {"ok": False, "error": "El pedido de editar es {persona_id: entero, datos: {…}}."}
    try:
        persona = s.editar_persona(cuerpo["persona_id"], cuerpo["datos"])
    except s.PersonaRechazada as e:          # rechazo de la puerta, o «sin confirmar» (la escritura pudo entrar: su texto lo dice)
        return e.codigo, e.datos
    except ValueError as e:
        return 400, {"ok": False, "error": str(e)}
    except Exception:  # noqa: BLE001
        return 502, {"ok": False, "error": ERROR_NO_SE_GUARDO}
    return 200, {"ok": True, "persona": persona}
