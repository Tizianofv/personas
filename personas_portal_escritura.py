# -*- coding: utf-8 -*-
"""Las ESCRITURAS del portal que sirve el programa (paso 5c, parte 3): crear una persona, editarla, anotar su permiso, y marcar o
reabrir un renglón de «Por resolver». Son las cinco rutas de `servidor.PORTAL_ESCRITURA`, con la misma lógica que
`Handler.portal_personas_post` de la App de registro (`594ec12`), SIN su puerta de sesión (esa la mira la App antes de reenviar).

`responder(nombre, ruta, grupos, crudo, quien)` devuelve `(código, cuerpo)`: lo que la App mandaría con `send_json`. `quien` es el
de la cabecera X-Personas-Portal-Quien (lo pone la App con `firma_escrita()`); el `quien` que venga en el cuerpo NO se lee.

Orden, igual que la App: (1) el cuerpo se lee (vacío = `{}`; no es JSON = 400 «llegó ilegible»; otro error = 500); (2) la acción;
(3) cualquier error no previsto = 500 con los textos de la App (uno si ya salió una escritura a NocoDB, otro si no).

Lo que cada acción hace (las funciones son las de `personas.py`, copia de la App):
  crear     `personas.crear_persona_portal`, con `una_vez` («portal-persona-crear») y `ya_creada` si se repite
  editar    `personas.editar_persona_portal`, con `una_vez` («portal-persona-editar») y `ya_guardado` si se repite
  permiso   `personas.anotar_permiso`, SIN `una_vez` (a propósito, como la App)
  resolver  `personas.portal_por_resolver_marcar(clave, quien)`
  reabrir   `personas.portal_por_resolver_marcar(clave, quien, reabrir=True)`

`una_vez` y `escribir_una_vez` son copias de `server.py` de la App (`594ec12`, líneas 2172-2225 y 12902): una caché en memoria de
cada `clave_envio` (600 s, 2000 entradas). Solo vive en este proceso, como en la App.
"""
import copy
import hashlib
import json
import threading
import time

import base
import personas

ERROR_ILEGIBLE = "El pedido llegó ilegible. No se guardó nada."
ERROR_SIN_CONFIRMAR = ("Algo falló en el servidor y no se pudo confirmar si quedó guardado. NO lo des por guardado: abre la ficha de "
                       "nuevo, o busca a la persona, y mira cómo quedó antes de repetirlo.")
ERROR_ANTES_DE_GUARDAR = "Algo falló en el servidor antes de guardar nada. No se guardó nada."

UNA_VEZ_VIDA_S = 600
UNA_VEZ_MAX = 2000
_UNA_VEZ = {}                      # (ámbito, llave) -> {huella, lock, hecho, res, t, usos}
_UNA_VEZ_LOCK = threading.Lock()


def llave_de_envio(cuerpo):
    """La llave que mandó la pantalla (`clave_envio`), o None (sin llave = se escribe como siempre)."""
    if not isinstance(cuerpo, dict):
        return None
    return str(cuerpo.get("clave_envio") or "").strip()[:100] or None


def escribir_una_vez(ambito, llave, contenido, escribir, exito=None):
    """Devuelve `(resultado, repetido)`. `repetido=True` = no se escribió nada, es lo ya guardado. Copia de `escribir_una_vez` de la
    App: `exito` recuerda solo el resultado que lo cumple; `contenido` (ruta y cuerpo) decide si dos envíos con la misma llave son el
    mismo envío."""
    if llave is None:
        return escribir(), False
    huella = hashlib.sha256(json.dumps(contenido, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    clave = (ambito, llave)
    with _UNA_VEZ_LOCK:
        ahora = time.monotonic()
        for k in [k for k, e in _UNA_VEZ.items() if e["usos"] == 0 and ahora - e["t"] > UNA_VEZ_VIDA_S]:
            del _UNA_VEZ[k]
        e = _UNA_VEZ.get(clave)
        if e is None or e["huella"] != huella:
            while len(_UNA_VEZ) >= UNA_VEZ_MAX:
                libre = next((k for k, x in _UNA_VEZ.items() if x["usos"] == 0), None)
                if libre is None:
                    break
                del _UNA_VEZ[libre]
            e = {"huella": huella, "lock": threading.Lock(), "hecho": False, "res": None, "t": ahora, "usos": 0}
            _UNA_VEZ[clave] = e
        e["usos"] += 1
    try:
        with e["lock"]:
            if e["hecho"]:
                return copy.deepcopy(e["res"]), True
            res = escribir()
            if exito is not None and not exito(res):
                return res, False
            e["res"] = copy.deepcopy(res)
            e["hecho"] = True
            e["t"] = time.monotonic()
            return res, False
    finally:
        with _UNA_VEZ_LOCK:
            e["usos"] -= 1


def una_vez(ambito, ruta, cuerpo, escribir, exito=None):
    """`escribir_una_vez` con la llave del cuerpo y el contenido «ruta + cuerpo», como `Handler.una_vez` de la App."""
    return escribir_una_vez(ambito, llave_de_envio(cuerpo), {"ruta": ruta, "cuerpo": cuerpo}, escribir, exito)


def leer_cuerpo(crudo):
    """El cuerpo como lo lee `Handler.read_json` de la App: vacío = `{}`; si no es JSON, levanta (`JSONDecodeError`)."""
    if not crudo:
        return {}
    return json.loads(crudo.decode())


def _ejecutar(nombre, ruta, grupos, cuerpo, quien):
    if nombre == "editar":
        pid = int(grupos[0])
        (codigo, datos), repetido = una_vez(
            "portal-persona-editar", ruta, cuerpo, lambda: personas.editar_persona_portal(pid, cuerpo, quien),
            exito=lambda r: r[0] == 200 and r[1].get("estado") == "guardado")
        return codigo, (dict(datos, ya_guardado=True) if repetido else datos)
    if nombre == "crear":
        (codigo, datos), repetido = una_vez(
            "portal-persona-crear", ruta, cuerpo, lambda: personas.crear_persona_portal(cuerpo, quien),
            exito=lambda r: r[0] == 201 and r[1].get("estado") == "creada")
        return codigo, (dict(datos, ya_creada=True) if repetido else datos)
    if nombre == "permiso":
        return personas.anotar_permiso(int(grupos[0]), cuerpo, quien)
    if nombre in ("resolver", "reabrir"):
        clave = cuerpo.get("clave") if isinstance(cuerpo, dict) else None
        return personas.portal_por_resolver_marcar(clave, quien, reabrir=(nombre == "reabrir"))
    raise ValueError("acción de escritura del portal desconocida: %r" % (nombre,))


def _error_inesperado():
    if base.escrituras_mandadas_en_este_pedido() > 0:
        return 500, {"estado": "sin_confirmar", "sin_confirmar": True, "error": ERROR_SIN_CONFIRMAR}
    return 500, {"error": ERROR_ANTES_DE_GUARDAR}


def responder(nombre, ruta, grupos, crudo, quien):
    """Corre la escritura `nombre` y devuelve `(código, cuerpo)`, con los mismos errores que la App (ver la docstring del módulo)."""
    try:
        cuerpo = leer_cuerpo(crudo)
        return _ejecutar(nombre, ruta, grupos, cuerpo, quien)
    except json.JSONDecodeError:
        return 400, {"error": ERROR_ILEGIBLE}
    except Exception:  # noqa: BLE001 — la pantalla dice que falló; nunca el texto crudo de la excepción
        return _error_inesperado()
