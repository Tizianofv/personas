# -*- coding: utf-8 -*-
"""Las escrituras de fichas que la App de registro sirve a Registro, portadas al programa de Personas: `guardar_cara`,
`crear_persona` y `editar_persona`, con los helpers del check-in que la App tiene en `server.py` (`campos_persona`,
`PersonaRechazada`, los textos `CHECKIN_*`, `_rechazo_del_checkin` y `_dato_del_checkin`), copiados de `server.py` de la
App en `0b48b5d`.

Las escrituras de verdad son de `personas.py` (`recibir` y `escribir_cara`). Este módulo arma lo que entra y lo que sale,
como en la App. Los nombres que la App toma de `server.py` y que viven en `personas.py` se enlazan aquí abajo, igual que
hace la App al final de su `server.py`.

Lo que NO es igual que la App: `guardar_cara` no actualiza ninguna caché de caras (la App tiene `_caras_cache`, en su
`server.py`; el programa no la tiene, y no la lee nadie aquí). Lo demás de los tres es el texto de la App.
"""
import re

import base
import personas

CARA_DIMS = base.CARA_DIMS
FichaQuitada = base.FichaQuitada
FichaUnida = base.FichaUnida

normalizar_telefono = personas.normalizar_telefono
PERSONA_FIELDS = personas.PERSONA_FIELDS
CASILLAS_DE_PANTALLA = personas.CASILLAS_DE_PANTALLA
PUERTA_CLAVES_DE_PANTALLA = personas.PUERTA_CLAVES_DE_PANTALLA
recibir = personas.recibir
respuesta_de_rechazo = personas.respuesta_de_rechazo
avisos_para_la_pantalla = personas.avisos_para_la_pantalla
puerta_sin_confirmar = personas.puerta_sin_confirmar
escribir_cara = personas.escribir_cara
sonda_de_tabla = personas.sonda_de_tabla


def guardar_cara(persona_id, vec):
    """Mete la cara en las ranuras de esa ficha, rotando, y devuelve cuántas quedaron. Lo escribe `personas.escribir_cara`
    (lee las ranuras en vivo, bajo el candado de la ficha, y hace un PATCH de la columna de caras). Si la ficha está unida
    a otra, levanta `FichaUnida`; si está guardada aparte, `FichaQuitada`. En los dos casos no escribe nada."""
    ranuras = escribir_cara(persona_id, vec)
    return len(ranuras)


def campos_persona(datos, body):
    """Campos opcionales compartidos entre crear y editar."""
    if "telefono" in datos:
        body["telefono"] = normalizar_telefono(datos.get("telefono"))   # → 18091234567 (wa_id)
    # El SEGUNDO teléfono y el SEGUNDO correo (parte 4 del diseño `registro-dueno-de-las-fichas`): el mismo trato que los
    # principales. **Las dos columnas tienen que existir en NocoDB** (las crea la sala antes de desplegar): lo que la puerta
    # lea o escriba de ellas falla si no están. La pantalla solo manda estas dos claves cuando tiene algo que decir de ellas
    # (`06-checkin.js`). Vaciar el segundo desde el check-in SÍ se puede: entonces llega vacío y se escribe `None`, igual que
    # el principal.
    if "telefono_2" in datos:
        body["telefono_2"] = normalizar_telefono(datos.get("telefono_2"))
    if "email_2" in datos:
        body["email_2"] = (datos.get("email_2") or "").strip() or None
    for campo in ("instagram", "email", "notas"):
        if campo in datos:
            body[campo] = (datos.get(campo) or "").strip() or None
    # MultiSelect: NocoDB espera string separado por comas; vacío → null
    for campo in ("instrumento", "genero"):
        if campo in datos:
            v = datos.get(campo)
            if isinstance(v, list):
                v = ",".join(x.strip() for x in v if x and x.strip())
            body[campo] = (v or "").strip() or None
    # 🔑 «POSIBLE PROVEEDOR» (pieza 2 del módulo Proveedores, diseño `disenos/proveedores/DISENO.md`). La pantalla manda la clave
    # `proveedor` SOLO cuando hay algo que decir (al crear, marcada; al editar, si la casilla cambió respecto de lo que cargó) y SOLO
    # como booleano de verdad: `true` → «Si» (la única opción de la columna, tal cual), `false` → vacío. Cualquier otra forma
    # (`"false"`, `1`, `"Si"`, una lista, `null`) NO se interpreta: 400, sin escribir nada. Va en `body`, y `_dato_del_checkin` lo
    # reparte a `otros` → la puerta (`recibir`): no hay otro camino hacia la columna. **La columna tiene que existir en NocoDB.**
    if "proveedor" in datos:
        marca = datos.get("proveedor")
        if marca is True:
            body["Posible_proveedor"] = "Si"
        elif marca is False:
            body["Posible_proveedor"] = None
        else:
            raise ValueError("«Posible proveedor» solo puede ser sí o no")
    if "cumpleanos" in datos:
        # Cumpleanos es texto día/mes (DD/MM); sin año (no aporta para felicitar).
        v = (datos.get("cumpleanos") or "").strip()
        if v and not re.fullmatch(r"\d{2}/\d{2}", v):
            raise ValueError("Cumpleaños inválido (formato DD/MM)")
        body["Cumpleanos"] = v or None
    return body


class PersonaRechazada(Exception):
    """El check-in NO guardó a la persona y ya sabe qué contestar: `(codigo, datos)` listos para `send_json`. Hoy solo
    sale de la comprobación «¿ya lo tiene otra ficha?» de la puerta (`personas.recibir`)."""

    def __init__(self, codigo, datos):
        super().__init__(str(datos.get("error", "")))
        self.codigo, self.datos = codigo, datos


# Lo que se le dice a quien está en el mostrador cuando el número ya es de otra ficha (el resto de la frase —de quién es y que
# no se guardó nada— la arma `respuesta_de_rechazo`, la misma que usan el portal «Personas» y la ficha del Aprendizaje). Buscar por
# el número sirve siempre: el buscador del check-in compara dígitos del teléfono (`buscar_personas`), tenga nombre o no la ficha.
CHECKIN_TELEFONO_QUE_HACER = "Búscala por ese número y regístrala a ella."
# Y cuando no se pudo comprobar (NocoDB no contestó). Al crear, lo que de verdad funciona sin comprobar es crearla sin número (sin
# teléfono no hay nada que comparar) y ponérselo después; al editar NO se puede decir eso (dejar el campo vacío borraría el número
# que tiene), así que solo se dice que se reintente: guardar sin cambiar el número tampoco compara, pero eso no lo decide quien lee.
CHECKIN_SI_NO_SE_PUDO_CREAR = "Inténtalo otra vez en un momento; si hay gente esperando, créala sin número y se lo pones después."
CHECKIN_SI_NO_SE_PUDO_EDITAR = "Inténtalo otra vez en un momento."
# Cuando la puerta no pudo CONFIRMAR lo que escribió (la base dijo que sí y la relectura no lo muestra): ni «actualizados» ni «registrado».
CHECKIN_SIN_CONFIRMAR_EDITAR = ("No se pudo confirmar que el cambio quedó guardado. NO lo des por guardado: busca a la persona y mira cómo quedó "
                                "antes de repetirlo.")
CHECKIN_SIN_CONFIRMAR_CREAR = ("La persona se creó (ficha n.º %s), pero no se pudo confirmar que sus datos quedaron bien guardados, así que NO quedó "
                               "registrada en la sesión. NO la crees otra vez: búscala por su nombre, mira cómo quedó y regístrala a ella.")
CHECKIN_SI_NO_SE_PUDO_CREAR_SIN = {         # según lo que no se pudo comprobar: el número, el correo o los dos
    ("correo",): "Inténtalo otra vez en un momento; si hay gente esperando, créala sin correo y se lo pones después.",
    ("telefono", "correo"): "Inténtalo otra vez en un momento; si hay gente esperando, créala sin número ni correo y se lo pones después.",
}


# Y para el correo: buscarlo por el correo no sirve en el check-in (el buscador compara nombre, WhatsApp, Instagram y dígitos del teléfono, no el
# correo), así que se manda a buscarla por su nombre; si esa ficha no tiene nombre, se dice (no saldría).
CHECKIN_CORREO_QUE_HACER = "Búscala por su nombre y regístrala a ella."
CHECKIN_CORREO_QUE_HACER_SIN_NOMBRE = "Esa ficha no tiene nombre, así que no sale al buscar por nombre."


def _rechazo_del_checkin(res, sin_escribir, si_no_se_pudo):
    """La respuesta del check-in cuando la puerta (`recibir`) no dejó pasar el teléfono o el correo, o `None` si lo dejó pasar."""
    que_correo = CHECKIN_CORREO_QUE_HACER if (res.get("de") or {}).get("nombre") else CHECKIN_CORREO_QUE_HACER_SIN_NOMBRE
    if si_no_se_pudo == CHECKIN_SI_NO_SE_PUDO_CREAR:         # lo que de verdad funciona sin comprobar es crearla SIN lo que se iba a comparar
        si_no_se_pudo = CHECKIN_SI_NO_SE_PUDO_CREAR_SIN.get(tuple(res.get("comprobaba") or ()), si_no_se_pudo)
    return respuesta_de_rechazo(res, sin_escribir, CHECKIN_TELEFONO_QUE_HACER, que_correo, si_no_se_pudo)


def _dato_del_checkin(body, ficha_id):
    """Lo que el check-in escribió en `body` (ya armado por `campos_persona`), repartido para la puerta: nombre, los dos
    teléfonos y los dos correos van como valores de la puerta; lo demás (Instagram, notas, instrumento, género, cumpleaños) es
    de la pantalla y viaja en `otros`. Las cuatro casillas de identidad NO pueden viajar en `otros`: la puerta rechaza un
    `otros` que traiga una columna de identidad (`otros_ilegible`)."""
    dato = {"origen": "checkin", "pantalla": True, "telefono_sin_forma_ok": True, "releer": PERSONA_FIELDS,
            "otros": {k: v for k, v in body.items() if k not in PUERTA_CLAVES_DE_PANTALLA and k != "Id"}}
    if ficha_id is not None:
        dato["ficha_id"] = ficha_id
    for campo, clave in CASILLAS_DE_PANTALLA:
        if campo in body:
            dato[clave] = body[campo]
    return dato


def editar_persona(persona_id, datos):
    body = {"Id": persona_id}
    if "nombre" in datos:
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            raise ValueError("El nombre no puede quedar vacío")
        body["nombre"] = nombre
    campos_persona(datos, body)
    # 🔴 Desde el 8-oct-2026 el check-in escribe por la PUERTA (`recibir`), la misma que el portal y la ficha del Aprendizaje: ella compara un
    # teléfono o un correo NUEVO con TODAS las fichas, con el MISMO candado desde la comprobación hasta el `PATCH` (Tiziano, 7-oct-2026:
    # «9)Si»), y es quien escribe. Vaciar el teléfono o el correo no se comprueba (no se decidió). FRONTERA: el candado es del proceso (un
    # solo `python3 server.py`); no cubre a Natalia ni a quien escriba en NocoDB directo.
    res = recibir(_dato_del_checkin(body, persona_id))
    rechazo = _rechazo_del_checkin(res, "No se guardó nada.", CHECKIN_SI_NO_SE_PUDO_EDITAR)
    if rechazo:
        raise PersonaRechazada(*rechazo)
    if res["excepcion"] is not None:          # la base falló al escribir o al releer: lo de siempre (500), no un «guardado»
        raise res["excepcion"]
    if puerta_sin_confirmar(res) or not isinstance(res["releida"], dict):
        # la puerta no pudo confirmar que lo escrito quedó: el check-in NO contesta éxito (antes contestaba 200 con la ficha releída)
        raise PersonaRechazada(502, {"motivo": "sin_confirmar", "sin_confirmar": True, "error": CHECKIN_SIN_CONFIRMAR_EDITAR})
    persona = dict(res["releida"])
    if res["avisos"]:
        persona["avisos"] = avisos_para_la_pantalla(res)      # la ruta los saca de la ficha y los pone aparte
    return persona


def crear_persona(datos):
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre es obligatorio")
    body = campos_persona(datos, {"nombre": nombre})
    body = {k: v for k, v in body.items() if v is not None}
    # 🔴 Igual que `editar_persona`: la ficha nace por la PUERTA, así que un alta del check-in y una del portal (o dos mostradores) con el
    # mismo número o el mismo correo no dejan dos fichas. Sin teléfono ni correo, ni lectura de todas las fichas ni candado.
    res = recibir(_dato_del_checkin(body, None))
    rechazo = _rechazo_del_checkin(res, "No se creó nada.", CHECKIN_SI_NO_SE_PUDO_CREAR)
    if rechazo:
        raise PersonaRechazada(*rechazo)
    if res["etapa"] == "escritura" and res["excepcion"] is not None:
        raise res["excepcion"]
    if res["ficha_id"] is None:
        raise RuntimeError("la base no dijo el número de la ficha nueva")
    if puerta_sin_confirmar(res):
        # la ficha YA nació, pero la puerta no confirmó sus valores: no se registra en la sesión ni se dice «creada»; la pantalla cierra el formulario.
        # 🔴 NO se levanta: lo que `una_vez` recuerda es la ESCRITURA. Si se levantara, el reintento con la misma llave crearía a la persona otra vez
        # (la ficha ya existe). Se devuelve marcado y la ruta contesta 502 DESPUÉS de la puerta de «no entra dos veces» (el reintento recibe lo mismo).
        return {"Id": res["ficha_id"], "_sin_confirmar": {"motivo": "creada_sin_confirmar", "sin_confirmar": True, "id": res["ficha_id"],
                                                          "error": CHECKIN_SIN_CONFIRMAR_CREAR % res["ficha_id"]}}
    rec = dict(res["rec"]) if isinstance(res["rec"], dict) else {"Id": res["ficha_id"]}
    if res["avisos"]:
        rec["avisos"] = avisos_para_la_pantalla(res)
    if isinstance(res["releida"], dict):
        rec["_releida"] = res["releida"]         # la fila ya releída por la puerta: la ruta no la lee otra vez
    return rec
