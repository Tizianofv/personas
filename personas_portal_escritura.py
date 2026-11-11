# -*- coding: utf-8 -*-
"""Las ESCRITURAS del portal que sirve el programa (paso 5c, parte 3): crear una persona, editarla, anotar su permiso, y marcar o
reabrir un renglón de «Por resolver». Son las rutas del portal de `servidor.PORTAL_ESCRITURA` (y, desde la parte 7, las dos de sesión del check-in, `crear_checkin` y
`editar_checkin`, de `PORTAL_ESCRITURA` y `PORTAL_ESCRITURA_PATCH`), con la misma lógica que
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
  unir      `personas.unir_fichas(ficha, otra, resoluciones, clave, quien, queda_visto)`, SIN `una_vez` (la App no lo usa aquí)
  continuar `personas.continuar_union(ficha)` (la App NO le pasa `quien`); el aviso de «Por resolver» sí lleva `quien`
  deshacer  `personas.deshacer_union(ficha, quien, union_visto, sobra_esperada)`, SIN `una_vez`
  borrar    `personas.quitar_ficha(ficha, clave, quien)` (parte 5). La clave del cuerpo; SIN `una_vez`
  devolver  `personas.devolver_ficha(ficha, quien)` (parte 5), SIN `una_vez`. Ninguna de las dos mira `puede_borrar_fichas`: lo mira la App
  crear_checkin   `personas_escrituras.crear_persona(cuerpo)` con `una_vez` («persona», sin `exito`: como la App, la ficha recordada es la que
                  nació); la respuesta es la de `do_POST` de la App (parte 7, tipo C). SIN `quien`: la App no lo escribe.
  editar_checkin  `personas_escrituras.editar_persona(id, cuerpo)`, SIN `una_vez` (la App tampoco): la respuesta es la de `do_PATCH`
                  (parte 7, tipo C). SIN `quien`.
  editar_aprendizaje  `personas.editar_ficha_cliente(identidad, cuerpo, quien)` con `una_vez` («ficha-editar», `ya_guardado` si se repite),
                  como `do_POST` de la App en `/api/aprendizaje/fichas/<id>/editar` (P6, tipo C). `quien` DE LA CABECERA (la App lo calcula
                  con `firma_escrita()`); la respuesta es la de `do_POST` de la App, con sus errores.

Las tres de unión, como `Handler.portal_personas_post` de la App: validan el cuerpo (400 con sus textos), leen la clave del aviso
(`aviso`) y, si la unión o el deshacer salen bien, marcan el aviso (`_con_el_aviso_marcado`, copia de `Handler.con_el_aviso_marcado`).

`una_vez` y `escribir_una_vez` son copias de `server.py` de la App (`594ec12`, líneas 2172-2225 y 12902): una caché en memoria de
cada `clave_envio` (600 s, 2000 entradas). Solo vive en este proceso, como en la App.
"""
import copy
import hashlib
import json
import re
import threading
import time

import base
import personas
import personas_escrituras

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


def _con_el_aviso_marcado(aviso, modo, estado, codigo, datos, quien):
    """Copia de `Handler.con_el_aviso_marcado` de la App: si el pedido vino de un aviso y salió bien, marca el aviso y suma `aviso`."""
    if aviso and codigo == 200 and isinstance(datos, dict) and datos.get("estado") == estado:
        return dict(datos, aviso=personas.marcar_aviso_de_la_union(aviso, modo, datos, quien))
    return datos


def _unir(ficha, cuerpo, quien, solo_contar=False, planeados=None):
    """Copia del bloque `mu` de `portal_personas_post` de la App (`594ec12`). Con `solo_contar` (P11-6f, el cálculo de `unir`) no escribe:
    las escrituras quedan en `planeados`. Un pedido con aviso de «Por resolver» marca además la bandeja: eso no se calcula (`SinCalculoDeUnion`)."""
    otra = cuerpo.get("otra") if isinstance(cuerpo, dict) else None
    otra = int(otra) if isinstance(otra, str) and re.fullmatch(r"\d{1,9}", otra) else otra
    resoluciones = cuerpo.get("resoluciones") if isinstance(cuerpo, dict) else None
    if isinstance(otra, bool) or not isinstance(otra, int) or not 0 < otra < 10 ** 9 or not (resoluciones is None or isinstance(resoluciones, dict)):
        return 400, {"ok": False, "error": "El pedido para unir no está completo: faltan la otra ficha o las resoluciones no son un diccionario."}
    visto = cuerpo.get("queda") if isinstance(cuerpo, dict) else None
    if visto is not None and (isinstance(visto, bool) or not isinstance(visto, int) or not 0 < visto < 10 ** 9):
        return 400, {"ok": False, "error": "El pedido para unir no está completo: `queda` tiene que ser el número de una ficha."}
    aviso, mal = personas.aviso_del_pedido(cuerpo)
    if mal:
        return 400, {"ok": False, "error": mal}
    if solo_contar:
        if aviso:
            raise personas.SinCalculoDeUnion("aviso_de_por_resolver")
        codigo, datos = personas.unir_fichas(ficha, otra, resoluciones, cuerpo.get("clave"), quien, queda_visto=visto,
                                             solo_contar=True, planeados=planeados)
        return codigo, datos
    codigo, datos = personas.unir_fichas(ficha, otra, resoluciones, cuerpo.get("clave"), quien, queda_visto=visto)
    return codigo, _con_el_aviso_marcado(aviso, "unir", "unida", codigo, datos, quien)


def _continuar(ficha, cuerpo, quien, solo_contar=False, planeados=None):
    """Copia del bloque `mc` de `portal_personas_post` de la App (`594ec12`): `continuar_union` no recibe `quien`. Con `solo_contar` (P11-6f,
    el cálculo de `continuar`) no escribe: las escrituras quedan en `planeados`. Un pedido con aviso de «Por resolver» marca además la
    bandeja: eso no se calcula (`SinCalculoDeUnion`), igual que en `unir`."""
    aviso, mal = personas.aviso_del_pedido(cuerpo)
    if mal:
        return 400, {"ok": False, "error": mal}
    if solo_contar:
        if aviso:
            raise personas.SinCalculoDeUnion("aviso_de_por_resolver")
        return personas.continuar_union(ficha, solo_contar=True, planeados=planeados)
    codigo, datos = personas.continuar_union(ficha)
    return codigo, _con_el_aviso_marcado(aviso, "unir", "unida", codigo, datos, quien)


def _deshacer(ficha, cuerpo, quien, solo_contar=False, planeados=None):
    """Copia del bloque `md` de `portal_personas_post` de la App (`594ec12`). Con `solo_contar` (P11-6f, el cálculo de `deshacer`) no escribe:
    las escrituras quedan en `planeados`. Un pedido con aviso de «Por resolver» que salga bien marca además la bandeja: eso no se calcula
    (`SinCalculoDeUnion`), igual que en `unir`. Un aviso que no sale bien (un rechazo) no marca nada, y ese rechazo sí se predice."""
    visto = cuerpo.get("union") if isinstance(cuerpo, dict) else None
    if visto is not None and (isinstance(visto, bool) or not isinstance(visto, int) or not 0 < visto < 10 ** 9):
        return 400, {"ok": False, "error": "El pedido para deshacer no está completo: `union` tiene que ser el número de una unión."}
    esperada = cuerpo.get("sobra") if isinstance(cuerpo, dict) else None
    if esperada is not None and (isinstance(esperada, bool) or not isinstance(esperada, int) or not 0 < esperada < 10 ** 9):
        return 400, {"ok": False, "error": "El pedido para deshacer no está completo: `sobra` tiene que ser el número de una ficha."}
    aviso, mal = personas.aviso_del_pedido(cuerpo)
    if mal:
        return 400, {"ok": False, "error": mal}
    codigo, datos = personas.deshacer_union(ficha, quien, union_visto=visto, sobra_esperada=esperada, solo_contar=solo_contar, planeados=planeados)
    if solo_contar:
        if aviso and codigo == 200:
            raise personas.SinCalculoDeUnion("aviso_de_por_resolver")
        return codigo, datos
    return codigo, _con_el_aviso_marcado(aviso, "deshacer", "deshecha", codigo, datos, quien)


# Parte 7: las escrituras de SESIÓN (check-in, tipo C). Sus errores no son los del portal: los de `do_POST` y `do_PATCH` de la App.
# P6: la ficha del Aprendizaje también es de sesión (tipo C) y lleva `quien` de la cabecera, así que `_responder_de_sesion` lo recibe.
ACCIONES_DE_SESION = ("crear_checkin", "editar_checkin", "editar_aprendizaje")


def _leer_o_minimo(ruta, campos, minimo):
    """Copia de `leer_o_minimo` de la App: si la RELECTURA de la ficha recién escrita falla, devuelve lo que ya se sabe de lo escrito. Una
    lectura que falla después de escribir no convierte un guardado en un error (el mostrador repetiría y se duplicaría)."""
    try:
        return base.nc("GET", ruta, query={"fields": campos})
    except Exception:  # noqa: BLE001 — como la App: el aviso va al log de la App; aquí no se escribe nada
        return dict(minimo)


def _respuesta_de_crear_checkin(datos, rec, repetido):
    """Copia del tramo de `POST /api/personas` de `Handler.do_POST` (App `594ec12`, líneas 17043-17060): 502 si la ficha nació y no se
    confirmó; si no, 201 con la ficha releída (o la mínima) y `ya_guardado` cuando el envío se repitió; `avisos` aparte si los hay."""
    if rec.get("_sin_confirmar"):
        return 502, rec["_sin_confirmar"]
    avisos = rec.get("avisos")
    persona = rec.get("_releida") or _leer_o_minimo(
        "/api/v2/tables/%s/records/%s" % (base.T_PERSONAS, rec["Id"]), personas.PERSONA_FIELDS,
        dict({k: v for k, v in rec.items() if k not in ("avisos", "_releida")},
             nombre=(datos.get("nombre") or "").strip(), telefono=(datos.get("telefono") or "").strip()))
    salida = {"persona": persona}                  # `respuesta_una_vez` de la App
    if repetido:
        salida["ya_guardado"] = True
    if avisos:
        salida = dict(salida, avisos=avisos)
    return 201, salida


def _ejecutar(nombre, ruta, grupos, cuerpo, quien):
    if nombre == "crear_checkin":
        rec, repetido = una_vez("persona", ruta, cuerpo, lambda: personas_escrituras.crear_persona(cuerpo))
        return _respuesta_de_crear_checkin(cuerpo, rec, repetido)
    if nombre == "editar_checkin":
        # Copia de `do_PATCH` de la App (línea 17487): sin `una_vez`; `avisos` van aparte de la ficha.
        persona = personas_escrituras.editar_persona(int(grupos[0]), cuerpo)
        avisos = persona.pop("avisos", None)
        return 200, dict({"persona": persona}, **({"avisos": avisos} if avisos else {}))
    if nombre == "editar_aprendizaje":
        # Copia del tramo de `do_POST` de la App para `/api/aprendizaje/fichas/<id>/editar` (8c9d21a): `una_vez` con la llave del cuerpo y
        # `ya_guardado` si se repite. La función es la de la App (`personas.editar_ficha_cliente`; cadena comparada por AST, sin diferencias).
        identidad = grupos[0]
        (codigo, datos), repetido = una_vez(
            "ficha-editar", ruta, cuerpo, lambda: personas.editar_ficha_cliente(identidad, cuerpo, quien),
            exito=lambda r: r[0] == 200 and r[1].get("estado") == "guardado")
        return codigo, (dict(datos, ya_guardado=True) if repetido else datos)
    if nombre == "unir":
        return _unir(int(grupos[0]), cuerpo, quien)
    if nombre == "continuar":
        return _continuar(int(grupos[0]), cuerpo, quien)
    if nombre == "deshacer":
        return _deshacer(int(grupos[0]), cuerpo, quien)
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
    # Parte 5: la App pide `puede_borrar_fichas` ANTES de llegar aquí (no se copia). Sin `una_vez`: la clave del borrado es lo que
    # impide borrar dos veces, y devolver lo impide el registro y su relectura. Como `Handler.portal_personas_post` de la App.
    if nombre == "borrar":
        clave = cuerpo.get("clave") if isinstance(cuerpo, dict) else None
        return personas.quitar_ficha(int(grupos[0]), clave, quien)
    if nombre == "devolver":
        return personas.devolver_ficha(int(grupos[0]), quien)
    raise ValueError("acción de escritura del portal desconocida: %r" % (nombre,))


def _error_inesperado():
    if base.escrituras_mandadas_en_este_pedido() > 0:
        return 500, {"estado": "sin_confirmar", "sin_confirmar": True, "error": ERROR_SIN_CONFIRMAR}
    return 500, {"error": ERROR_ANTES_DE_GUARDAR}


def _responder_de_sesion(nombre, ruta, grupos, crudo, quien=None):
    """Las escrituras de SESIÓN (check-in, tipo C), con los errores de `do_POST` y `do_PATCH` de la App: un `ValueError` (también el JSON
    ilegible, que la App lee con `read_json`) da 400 con su texto; `PersonaRechazada` da su código y sus datos; cualquier otro error da 500
    con `str(e)`, como `do_POST` de la App. `quien` solo lo usa la ficha del Aprendizaje; el check-in no lo escribe."""
    try:
        return _ejecutar(nombre, ruta, grupos, leer_cuerpo(crudo), quien)
    except personas_escrituras.PersonaRechazada as e:
        return e.codigo, e.datos
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:  # noqa: BLE001 — como la App: el texto de la excepción llega a la pantalla
        return 500, {"error": str(e)}


def responder(nombre, ruta, grupos, crudo, quien):
    """Corre la escritura `nombre` y devuelve `(código, cuerpo)`, con los mismos errores que la App (ver la docstring del módulo)."""
    if nombre in ACCIONES_DE_SESION:
        return _responder_de_sesion(nombre, ruta, grupos, crudo, quien)
    try:
        cuerpo = leer_cuerpo(crudo)
        return _ejecutar(nombre, ruta, grupos, cuerpo, quien)
    except json.JSONDecodeError:
        return 400, {"error": ERROR_ILEGIBLE}
    except Exception:  # noqa: BLE001 — la pantalla dice que falló; nunca el texto crudo de la excepción
        return _error_inesperado()
