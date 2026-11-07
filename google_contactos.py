# -*- coding: utf-8 -*-
"""Contactos de Google, piezas P0, P1 y P3 de `disenos/registro-contactos-google/DISENO.md`.

P0 y P1 solo leen (la ruta `conteo` y `contar`, sin escribir nada). P3 (`sincronizar`) lleva los contactos de Google
a las fichas POR LA PUERTA (`personas.recibir`, origen `google`, sin `recibir_y_unir`: nunca une sola). Por defecto
SOLO CUENTA; escribe únicamente si la variable `CONTACTOS_GOOGLE_MODO` vale EXACTAMENTE `escribir` (`modo`). Lo que
sigue es de P0 y P1:

Qué hace:
  · `configuracion(env)`: las tres credenciales de la cuenta caribbeandreamstudios, por nombre de variable.
    Si falta alguna, levanta `SinCredencial` con los nombres que faltan, ANTES de llamar a Google.
  · `token_de_acceso` y `leer_contactos`: canjean el token de refresco por uno de acceso y leen TODA la
    libreta con la People API (`people.connections.list`), siguiendo `nextPageToken`.
  · `contar(contactos, fichas)`: cuenta, sin escribir nada, cómo casan los contactos con las fichas de
    NocoDB. Solo devuelve cifras.

Qué NO hace: no escribe en Google ni en NocoDB, no crea ni une fichas, no pasa ningún dato por la puerta
(`recibir`). Para casar usa las funciones de la puerta (`personas.normalizar_telefono`, `personas.clave_correo`,
`personas.clave_nombre`, `personas._telefono_de_ficha`) y REPITE en forma de índice la regla de
`personas._celda_es_el_numero` (`_fichas_por_telefono`). Que el índice dé lo mismo que `personas._puerta_ficha_tiene`
lo prueba `tests/test_google_contactos_cuenta.py::test_la_forma_del_telefono_sigue_la_regla_de_la_puerta`; si la
puerta cambia su regla, esa prueba tiene que caerse. Lectura de fichas: la misma de la puerta, fuera de su candado
(ver el reporte: es una decisión pendiente de la sala).

Forma de la respuesta de Google (de la documentación oficial, ver el archivo de pruebas
`tests/test_google_contactos_cuenta.py`): `connections[]`, `nextPageToken`, `totalItems`; y dentro de cada
persona `names[].displayName`, `phoneNumbers[].value`, `emailAddresses[].value`. Lo comprobado es la
documentación. P1 (`conteo`) sí corrió contra Google y NocoDB de producción el 26-oct-2026, solo lectura, con la sala
(`DISENO.md`, «Conteo P1 en producción»). P2 y P3 no se han corrido contra Google real: sus pruebas usan dobles.

P2 (fichas → Google, SOLO CUENTA, `contar_desde_fichas`): `contacto_de_ficha` arma lo que la ficha le daría a Google,
en la misma forma que `_persona`; `contar_desde_fichas` cuenta cómo casa con la libreta. Es puro: no llama a Google ni a
NocoDB. `sincronizar` lo devuelve en `desde_fichas`, con la misma lectura de fichas que usa P3.

P4 (NocoDB → Google, al final del archivo): crea contactos en Google para las fichas que Google no tiene
(`people:createContact`) y agrega al contacto casado el correo que le falta (`updateContact`, con su etag). Enlaza cada
ficha creada en la columna `google_id`. No borra, no pisa, no toca fichas unidas, quitadas, con aviso abierto ni con
un choque de nombre. Solo escribe con `CONTACTOS_GOOGLE_MODO` = `escribir` (la misma compuerta de P3).

P6 (el reloj, al final del archivo): un hilo dentro de la App que corre `sincronizar` cada hora. Apagado por defecto:
solo arranca si `CONTACTOS_GOOGLE_RELOJ` vale `encendido`. Escribe solo si ADEMÁS `CONTACTOS_GOOGLE_MODO` vale `escribir`.
Una corrida a la vez dentro del proceso; cada corrida deja una línea `[CONTACTOS-RELOJ]` con cifras y códigos.
"""

import itertools
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import personas

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CONTACTOS_URL = "https://people.googleapis.com/v1/people/me/connections"
# Las tres variables de Railway (`registro-cds`). Los valores nunca se imprimen ni se devuelven.
VARIABLE_ID = "GOOGLE_CONTACTOS_CLIENT_ID"
VARIABLE_SECRETO = "GOOGLE_CONTACTOS_CLIENT_SECRET"
VARIABLE_REFRESCO = "GOOGLE_CONTACTOS_REFRESH_TOKEN"
VARIABLES = (VARIABLE_ID, VARIABLE_SECRETO, VARIABLE_REFRESCO)
# Solo estos campos: lo demás de la libreta no se pide y no se guarda.
CAMPOS_PERSONA = "names,phoneNumbers,emailAddresses,metadata"   # `metadata` trae el etag de cada contacto (P4 lo necesita)
TAMANO_PAGINA = 1000        # máximo que acepta la People API para `pageSize`
MAX_PAGINAS = 1000          # frontera de seguridad: una libreta de más de 1 000 000 de contactos no es esta


class SinCredencial(Exception):
    """Falta una de las variables de Google. `faltan` trae solo sus NOMBRES."""

    def __init__(self, faltan):
        super().__init__("falta la credencial de Google")
        self.faltan = tuple(faltan)


class ErrorGoogle(Exception):
    """Google (o la red) no contestó como se esperaba. Lleva la etapa y el código HTTP, nunca el cuerpo
    de la respuesta ni el token."""

    def __init__(self, etapa, codigo):
        super().__init__(f"Google: {etapa} ({codigo})")
        self.etapa = etapa
        self.codigo = codigo


def _pedir(url, datos=None, cabeceras=None, timeout=30):
    """Una llamada HTTP con la librería estándar (la App no tiene dependencias). Con `datos` (un dict)
    es un POST de formulario; sin `datos`, un GET. Devuelve el JSON. Un error se levanta como
    `ErrorGoogle` con solo el código: el cuerpo no sale de aquí."""
    cab = dict(cabeceras or {})
    cuerpo = None
    metodo = "GET"
    if datos is not None:
        cuerpo = urllib.parse.urlencode(datos).encode()
        cab["Content-Type"] = "application/x-www-form-urlencoded"
        metodo = "POST"
    req = urllib.request.Request(url, data=cuerpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorGoogle("pedido", e.code) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ErrorGoogle("red", 0) from None


def configuracion(env):
    """Las tres credenciales, de `env` (el dict de la App). Sin alguna, `SinCredencial` con sus nombres."""
    faltan = [v for v in VARIABLES if not str(env.get(v, "") or "").strip()]
    if faltan:
        raise SinCredencial(faltan)
    return {"client_id": str(env[VARIABLE_ID]).strip(),
            "client_secret": str(env[VARIABLE_SECRETO]).strip(),
            "refresh_token": str(env[VARIABLE_REFRESCO]).strip()}


def token_de_acceso(cfg, pedir=_pedir):
    """Canjea el token de refresco por uno de acceso (vale una hora). Sin `access_token` en la respuesta,
    `ErrorGoogle`."""
    r = pedir(GOOGLE_TOKEN_URL, datos={"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
                                       "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"})
    tok = r.get("access_token") if isinstance(r, dict) else None
    if not isinstance(tok, str) or not tok:
        raise ErrorGoogle("token", "sin_token")
    return tok


def _fuente_de_contacto(p):
    """La fuente de tipo CONTACT de una persona de Google (con su `etag`), tal como la dio Google; o `None`."""
    md = p.get("metadata") if isinstance(p, dict) else None
    fuentes = md.get("sources") if isinstance(md, dict) else None
    for s in (fuentes or []):
        if isinstance(s, dict) and s.get("type") == "CONTACT" and isinstance(s.get("etag"), str) and s["etag"]:
            return s
    return None


def _persona(p):
    """Una persona de Google, reducida a lo que se cuenta: el nombre, los teléfonos normalizados (con
    `personas.normalizar_telefono`) y los correos validados (con `personas.clave_correo`, en minúsculas). Para P4 guarda
    además el `resourceName` (`rn`, o `None`), la fuente CONTACT con su etag (`fuente`) y los correos tal como vienen
    (`correos_crudos`), porque `updateContact` reemplaza la lista entera."""
    if not isinstance(p, dict):
        p = {}
    rn = p.get("resourceName")
    rn = rn if isinstance(rn, str) and rn.startswith("people/") else None
    crudos = [c for c in (p.get("emailAddresses") or []) if isinstance(c, dict)]
    nombre = ""
    for n in (p.get("names") or []):
        if isinstance(n, dict) and str(n.get("displayName") or "").strip():
            nombre = str(n["displayName"]).strip()
            break
    telefonos = []
    for t in (p.get("phoneNumbers") or []):
        d = personas.normalizar_telefono(t.get("value")) if isinstance(t, dict) else None
        if d:
            telefonos.append(d)
    correos = []
    for c in (p.get("emailAddresses") or []):
        k = personas.clave_correo(c.get("value")) if isinstance(c, dict) else None
        if k:
            correos.append(k)
    return {"nombre": nombre, "telefonos": telefonos, "correos": correos, "rn": rn,
            "fuente": _fuente_de_contacto(p), "correos_crudos": crudos}


def leer_contactos(token, pedir=_pedir, pagina=TAMANO_PAGINA, max_paginas=MAX_PAGINAS):
    """TODA la libreta: sigue `nextPageToken` hasta que no venga. Un token repetido o más páginas que
    `max_paginas` levantan `ErrorGoogle` (no se cuenta a medias en silencio)."""
    contactos, sig_pagina, vistos = [], None, set()
    cab = {"Authorization": "Bearer " + token}
    for _ in range(max_paginas):
        q = {"personFields": CAMPOS_PERSONA, "pageSize": str(pagina)}
        if sig_pagina:
            q["pageToken"] = sig_pagina
        r = pedir(GOOGLE_CONTACTOS_URL + "?" + urllib.parse.urlencode(q), cabeceras=cab)
        if not isinstance(r, dict):
            raise ErrorGoogle("contactos", "forma")
        for p in (r.get("connections") or []):
            contactos.append(_persona(p))
        sig = r.get("nextPageToken")
        if not sig:
            return contactos
        if not isinstance(sig, str) or sig in vistos:
            raise ErrorGoogle("paginado", "repetido")
        vistos.add(sig)
        sig_pagina = sig
    raise ErrorGoogle("paginado", "demasiadas_paginas")


def _claves_de_ficha(f):
    """Las claves con que una ficha puede casar, las mismas reglas de la puerta (comprobado en la prueba de arriba):
      · `fuerte`: el teléfono de cada casilla con `personas._telefono_de_ficha` (los de forma de teléfono).
      · `cruda`: los dígitos de cada casilla con `personas.normalizar_telefono` (para un número que no tiene
        forma de teléfono, como lo compara `personas._celda_es_el_numero`).
      · `correo`: el correo de cada casilla con `personas.clave_correo`."""
    fuerte, cruda, correo = set(), set(), set()
    for c in ("telefono", "telefono_2"):
        t = personas._telefono_de_ficha(f.get(c))
        if t is not None:
            fuerte.add(t)
        r = personas.normalizar_telefono(f.get(c))
        if r is not None:
            cruda.add(r)
    for c in ("email", "email_2"):
        k = personas.clave_correo(f.get(c))
        if k:
            correo.add(k)
    return fuerte, cruda, correo


def _indices(fichas):
    """Para cada clave, el conjunto de fichas (por `Id`) que la tienen. Índice de las mismas claves que
    `personas._celda_es_el_numero` y `personas.clave_correo` comparan (ver `_claves_de_ficha`), para no hacer
    una comparación por cada par contacto–ficha."""
    fuerte, cruda, correo = {}, {}, {}
    for f in fichas:
        fid = f.get("Id")
        t_f, t_r, c = _claves_de_ficha(f)
        for k in t_f:
            fuerte.setdefault(k, set()).add(fid)
        for k in t_r:
            cruda.setdefault(k, set()).add(fid)
        for k in c:
            correo.setdefault(k, set()).add(fid)
    return fuerte, cruda, correo


def _fichas_por_telefono(v, fuerte, cruda):
    """Lo mismo que `personas._celda_es_el_numero`, en índice: con forma de teléfono se compara con la
    forma fuerte; sin ella, con los dígitos crudos."""
    tabla = fuerte if personas._telefono_de_ficha(v) is not None else cruda
    return tabla.get(v, set())


def _nombre_distinto(nombre_google, ficha):
    """Dos nombres distintos, comparados con `personas.clave_nombre` (sin tildes, mayúsculas ni espacios
    dobles). Si uno de los dos está vacío, no hay choque de nombre."""
    if ficha is None:
        return False
    a = personas.clave_nombre(nombre_google)
    b = personas.clave_nombre(ficha.get("nombre"))
    return bool(a and b and a != b)


def _tiene_dato(f):
    """¿La ficha tiene algún teléfono o correo con el que una persona de Google pueda casar?"""
    t_f, t_r, c = _claves_de_ficha(f)
    return bool(t_f or t_r or c)


CLAVES_CONTEO = (
    "contactos_en_google", "con_telefono", "con_correo", "sin_telefono_ni_correo",
    "casan_por_telefono", "casan_por_correo", "casan_por_los_dos_con_la_misma_ficha",
    "casan_solo_por_telefono", "casan_solo_por_correo",
    "chocan", "chocan_fichas_distintas", "chocan_mismo_telefono_nombre_distinto",
    "sin_ficha",
    "fichas_en_nocodb", "fichas_con_dato_de_casar", "fichas_no_en_google", "fichas_no_en_google_sin_dato",
)


def contar(contactos, fichas):
    """Cuenta, sin escribir nada, cómo casa cada contacto de Google con las fichas. Cada contacto cae en UNA
    de estas cuentas (mutuamente excluyentes, salvo `casan_por_*`, que son vistas que se pueden solapar):
      · sin ficha: ni su teléfono ni su correo casan con ninguna ficha.
      · chocan: casan con dos o más fichas distintas, o su teléfono casa con una ficha cuyo nombre es distinto
        (con `personas.clave_nombre`; un nombre vacío no cuenta como distinto).
      · casan por los dos con la misma ficha: teléfono y correo casan con la misma ficha, sin choque.
      · casan solo por teléfono / solo por correo: una sola vía, sin choque.
    Y de las fichas: cuántas hay en la base, cuántas tienen algo con qué casar, y cuántas no casan con
    ningún contacto de Google (de ellas, cuántas no tienen nada con qué casar)."""
    fuerte, cruda, correo = _indices(fichas)
    por_id = {f.get("Id"): f for f in fichas if f.get("Id") is not None}
    out = dict.fromkeys(CLAVES_CONTEO, 0)
    casadas = set()
    for c in contactos:
        out["contactos_en_google"] += 1
        tels, mails = c["telefonos"], c["correos"]
        if tels:
            out["con_telefono"] += 1
        if mails:
            out["con_correo"] += 1
        if not tels and not mails:
            out["sin_telefono_ni_correo"] += 1
        ft = set()
        for v in tels:
            ft |= _fichas_por_telefono(v, fuerte, cruda)
        fc = set()
        for m in mails:
            fc |= correo.get(m, set())
        if ft:
            out["casan_por_telefono"] += 1
        if fc:
            out["casan_por_correo"] += 1
        u = ft | fc
        casadas |= u
        if not u:
            out["sin_ficha"] += 1
        elif len(u) > 1:
            out["chocan"] += 1
            out["chocan_fichas_distintas"] += 1
        elif len(ft) == 1 and _nombre_distinto(c["nombre"], por_id.get(next(iter(ft)))):
            out["chocan"] += 1
            out["chocan_mismo_telefono_nombre_distinto"] += 1
        elif ft and fc:
            out["casan_por_los_dos_con_la_misma_ficha"] += 1
        elif ft:
            out["casan_solo_por_telefono"] += 1
        else:
            out["casan_solo_por_correo"] += 1
    out["fichas_en_nocodb"] = len(por_id)
    for fid, f in por_id.items():
        con_dato = _tiene_dato(f)
        if con_dato:
            out["fichas_con_dato_de_casar"] += 1
        if fid not in casadas:
            out["fichas_no_en_google"] += 1
            if not con_dato:
                out["fichas_no_en_google_sin_dato"] += 1
    return out


def conteo(env, leer_fichas, pedir=_pedir):
    """Todo el conteo de P1: credenciales (sin ellas, `SinCredencial` antes de tocar Google), token, la
    libreta entera, las fichas con `leer_fichas()` (la misma lectura que usa la puerta) y `contar`.
    Solo lectura: ningún POST ni PATCH sale de aquí, salvo el canje de token que Google exige."""
    cfg = configuracion(env)
    token = token_de_acceso(cfg, pedir)
    contactos = leer_contactos(token, pedir)
    return contar(contactos, leer_fichas())


# ---------------------------------------------------------------------------------------------------------------
# P3: Google → fichas de Personas, por la puerta. Solo altas y casillas vacías; lo distinto va a «Por resolver».
# ---------------------------------------------------------------------------------------------------------------

ORIGEN = "google"                       # el `origen` que la puerta acepta para esto (`personas.PUERTA_ORIGENES`)
VARIABLE_MODO = "CONTACTOS_GOOGLE_MODO"
MODO_ESCRIBIR = "escribir"              # el valor EXACTO. Sin quitar espacios ni pasar a minúsculas (como `entrada_modo`).


def modo(env):
    """`escribir` solo si la variable vale exactamente `escribir`. Ausente, vacía, con espacios, en mayúsculas o
    cualquier otra cosa: `contar`."""
    valor = env.get(VARIABLE_MODO)
    return MODO_ESCRIBIR if isinstance(valor, str) and valor == MODO_ESCRIBIR else "contar"


def dato_de_contacto(c, indices=None):
    """Lo que la puerta recibe de un contacto (ya reducido por `_persona`): origen `google`, su nombre, un teléfono como
    `telefono_dicho` y un correo como `correo`. Con `indices` (de `_indices(fichas)`), el primer teléfono (y el primer
    correo) que CASA con una ficha va primero: así un contacto que casa por su segundo teléfono se liga a esa ficha y no
    nace duplicado (P1 lo cuenta como casado). Sin casamiento, va el primero de la lista. Lo que no va (el resto de
    teléfonos y correos) no entra: el camino de sistema no trae casillas secundarias (`casilla_secundaria_sin_pantalla`)."""
    tels, mails = list(c["telefonos"]), list(c["correos"])
    if indices is not None:
        fuerte, cruda, correo = indices
        tels = sorted(tels, key=lambda v: 0 if _fichas_por_telefono(v, fuerte, cruda) else 1)   # estable: el orden se mantiene
        mails = sorted(mails, key=lambda m: 0 if correo.get(m) else 1)
    d = {"origen": ORIGEN}
    if c["nombre"]:
        d["nombre"] = c["nombre"]
    if tels:
        d["telefono_dicho"] = tels[0]
    if mails:
        d["correo"] = mails[0]
    return d


def _sumar(cuenta, clave):
    k = "-" if clave is None else str(clave)
    cuenta[k] = cuenta.get(k, 0) + 1


def _resumen(resultados):
    """Cifras de una pasada de la puerta. Solo cuentas: ni nombres, ni teléfonos, ni correos, ni Ids."""
    out = {"contactos": 0, "estado": {}, "accion": {}, "altas": 0, "valores": {}, "casillas": {}, "avisos": {},
           "avisos_total": 0, "avisos_informativos": 0, "avisos_por_resolver": 0}
    for r in resultados:
        out["contactos"] += 1
        _sumar(out["estado"], r.get("estado"))
        _sumar(out["accion"], r.get("accion"))
        # Una alta: en contar, la puerta dice `crearia` (su acción queda `no_tocada`); al escribir, `accion` = `creada`. Al escribir
        # cuenta toda alta con `Id`: la base contestó con el número de la ficha, así que la ficha existe, aunque la relectura
        # después falle o no coincida (la puerta lo dice con su `sin_confirmar`). Sin `Id` (la base no lo dio) no cuenta: `ficha_id`
        # se fija solo cuando la base devuelve el `Id`.
        if r.get("crearia") is True or (r.get("accion") == "creada" and r.get("ficha_id") is not None):
            out["altas"] += 1
        for v in (r.get("valores") or {}).values():
            _sumar(out["valores"], v.get("resultado"))
            if v.get("resultado") in ("guardado", "guardaria"):
                _sumar(out["casillas"], v.get("en"))
        for a in (r.get("avisos") or []):
            _sumar(out["avisos"], a.get("tipo"))
            out["avisos_total"] += 1
            out["avisos_informativos" if a.get("informativo") else "avisos_por_resolver"] += 1
    return out


def sincronizar(env, recibir, pedir=_pedir, contactos=None, leer_fichas=None, pedir_json=None, enlazar=None, esperar=None):
    """P3. Primero SIEMPRE una pasada que solo cuenta (`recibir(dato, solo_contar=True)` por cada contacto): es lo
    que la puerta haría, sin escribir nada. Solo si `modo(env)` es `escribir`, una segunda pasada con
    `solo_contar=False`. `recibir` es `personas.recibir` (la puerta real); se pasa como parámetro para probarla con
    NocoDB doblado. `leer_fichas` (por defecto, la lectura de la puerta) da las fichas para elegir, por contacto, el teléfono
    y el correo que casan (`dato_de_contacto`). Lo que no cabe en la puerta (el resto de teléfonos y correos) se cuenta aparte.

    Devuelve `{"modo", "contar", "escrito", "sin_pasar", "desde_fichas"}`: `escrito` es `None` si solo contó; `desde_fichas` es
    P2 (`contar_desde_fichas`), contado antes de cualquier escritura. Sin credenciales, levanta
    `SinCredencial` antes de tocar Google; un error de Google, `ErrorGoogle`. Nada de esto se escribe en Google."""
    cfg = configuracion(env)
    token = token_de_acceso(cfg, pedir)
    if contactos is None:
        contactos = leer_contactos(token, pedir)
    fichas = (leer_fichas or personas._leer_fichas_de_la_puerta)()   # UNA lectura: para elegir el teléfono y el correo que casan, y para P2
    indices = _indices(fichas)
    datos = [dato_de_contacto(c, indices) for c in contactos]
    sin_pasar = {"telefonos_extra": sum(max(0, len(c["telefonos"]) - 1) for c in contactos),
                 "correos_extra": sum(max(0, len(c["correos"]) - 1) for c in contactos)}
    cuenta = _resumen([recibir(d, solo_contar=True) for d in datos])
    desde = contar_desde_fichas(contactos, fichas)   # P2: solo cuenta, antes de cualquier escritura
    pedir_json = pedir_json or _pedir_json
    enlazar = enlazar or personas.enlazar_ficha_con_google
    esperar = esperar or time.sleep
    if modo(env) != MODO_ESCRIBIR:
        p4 = desde_personas_a_google(token, contactos, False, pedir_json, enlazar, esperar)   # P4: solo cuenta
        return {"modo": "contar", "contar": cuenta, "escrito": None, "sin_pasar": sin_pasar, "desde_fichas": desde, "p4": p4}
    # La columna `google_id` se comprueba ANTES de cualquier escritura de la corrida (también la de P3): sin ella no se escribe nada.
    try:
        columna_ok = personas.columna_google_id_existe()
    except Exception as e:  # noqa: BLE001
        p4 = {"estado": "no_se_pudo_leer", "motivo": type(e).__name__, "escrito": None}
        return {"modo": "escribir", "contar": cuenta, "escrito": None, "sin_pasar": sin_pasar, "desde_fichas": desde,
                "p4": p4, "aviso": NADA_SE_ESCRIBIO}
    if not columna_ok:
        p4 = desde_personas_a_google(token, contactos, False, pedir_json, enlazar, esperar)   # solo cuenta, para ver el plan
        return {"modo": "escribir", "contar": cuenta, "escrito": None, "sin_pasar": sin_pasar, "desde_fichas": desde,
                "p4": p4, "aviso": NADA_SE_ESCRIBIO_SIN_COLUMNA}
    escrito = _resumen([recibir(d, solo_contar=False) for d in datos])
    p4 = desde_personas_a_google(token, contactos, True, pedir_json, enlazar, esperar)   # P4 va DESPUÉS de P3: lee las fichas ya escritas
    return {"modo": "escribir", "contar": cuenta, "escrito": escrito, "sin_pasar": sin_pasar, "desde_fichas": desde, "p4": p4}


# ---------------------------------------------------------------------------------------------------------------
# P2: fichas de Personas → Google. SOLO CUENTA: arma lo que la ficha le daría a Google y cuenta cómo casa con la
# libreta. No escribe nada, ni en Google ni en NocoDB, y no pasa por la puerta.
# ---------------------------------------------------------------------------------------------------------------

def _vacia(celda):
    return str(celda or "").strip() == ""


def _clave_telefono(celda):
    """La clave con que una casilla de la ficha casa con un teléfono de Google, o `None` si no se puede enviar. Es la misma
    regla que `personas._celda_es_el_numero`, en forma de clave: con forma de teléfono (`personas._telefono_de_ficha`), el
    número; sin ella, los dígitos, pero solo si esos dígitos tampoco tienen forma de teléfono. Una casilla con letras y forma
    de teléfono (p. ej. con «x») no casa con nada y no se envía. Que da lo mismo que la puerta lo prueba
    `tests/test_google_contactos_fichas.py` (`test_la_clave_de_cada_casilla_casa_como_la_puerta`)."""
    t = personas._telefono_de_ficha(celda)
    if t is not None:
        return t
    n = personas.normalizar_telefono(celda)
    if n is not None and personas._telefono_de_ficha(n) is None:
        return n
    return None


def contacto_de_ficha(f):
    """Lo que la ficha le daría a Google, en la forma de `_persona` (nombre, teléfonos y correos ya en clave). Teléfonos: las
    casillas `telefono` y `telefono_2` por `_clave_telefono`, sin repetir. Correos: `email` y `email_2` por
    `personas.clave_correo`, sin repetir. Una casilla que no se puede enviar no entra (la cuenta la ve en `casillas_no_enviables`).
    No escribe nada: es lo que P4 mandaría; por ahora solo se compara."""
    tels, mails = [], []
    for c in ("telefono", "telefono_2"):
        k = _clave_telefono(f.get(c))
        if k and k not in tels:
            tels.append(k)
    for c in ("email", "email_2"):
        k = personas.clave_correo(f.get(c))
        if k and k not in mails:
            mails.append(k)
    return {"nombre": str(f.get("nombre") or "").strip(), "telefonos": tels, "correos": mails}


CLAVES_DESDE_FICHAS = (
    "fichas", "fichas_con_dato", "fichas_sin_dato", "fichas_que_google_no_tiene",
    "fichas_casadas", "casadas_telefono_que_google_no_tiene", "casadas_correo_que_google_no_tiene",
    "casadas_nombre_distinto", "casillas_no_enviables", "contactos_sin_ficha",
)


def contar_desde_fichas(contactos, fichas):
    """P2, solo cuenta, de las fichas hacia Google. `contactos` (de `_persona`) y `fichas` (la lectura de la puerta, que ya deja
    fuera las unidas y las quitadas). Cuenta:
      · fichas con dato: tienen algún teléfono o correo enviable (`contacto_de_ficha`). Sin dato, no casan con nadie.
      · fichas que Google no tiene: con dato, y ninguno de sus teléfonos ni correos está en la libreta.
      · casadas: con dato y con al menos un teléfono o correo en la libreta. De ellas: cuántas tienen un teléfono o un correo
        que la libreta no tiene, y cuántas tienen un nombre que ninguno de sus contactos casados tiene (`clave_nombre`; un
        nombre vacío no es choque).
      · casillas no enviables: casillas con texto que no son teléfono ni correo con forma. No entran en la comparación.
      · contactos sin ficha: ni su teléfono ni su correo casan con ninguna ficha (la misma cuenta que `contar`, `sin_ficha`).
    No hace ninguna llamada: ni a Google ni a NocoDB."""
    tel_g, mail_g = set(), set()
    por_tel, por_mail = {}, {}
    for i, c in enumerate(contactos):
        for t in c["telefonos"]:
            tel_g.add(t)
            por_tel.setdefault(t, set()).add(i)
        for m in c["correos"]:
            mail_g.add(m)
            por_mail.setdefault(m, set()).add(i)
    out = dict.fromkeys(CLAVES_DESDE_FICHAS, 0)
    tel_f, mail_f = set(), set()
    for f in fichas:
        g = contacto_de_ficha(f)
        tel_f.update(g["telefonos"])
        mail_f.update(g["correos"])
    for c in contactos:
        if not any(t in tel_f for t in c["telefonos"]) and not any(m in mail_f for m in c["correos"]):
            out["contactos_sin_ficha"] += 1
    for f in fichas:
        out["fichas"] += 1
        for campo in ("telefono", "telefono_2"):
            if not _vacia(f.get(campo)) and _clave_telefono(f.get(campo)) is None:
                out["casillas_no_enviables"] += 1
        for campo in ("email", "email_2"):
            if not _vacia(f.get(campo)) and personas.clave_correo(f.get(campo)) is None:
                out["casillas_no_enviables"] += 1
        g = contacto_de_ficha(f)
        if not g["telefonos"] and not g["correos"]:
            out["fichas_sin_dato"] += 1
            continue
        out["fichas_con_dato"] += 1
        casados = set()
        for t in g["telefonos"]:
            casados |= por_tel.get(t, set())
        for m in g["correos"]:
            casados |= por_mail.get(m, set())
        if not casados:
            out["fichas_que_google_no_tiene"] += 1
            continue
        out["fichas_casadas"] += 1
        if any(t not in tel_g for t in g["telefonos"]):
            out["casadas_telefono_que_google_no_tiene"] += 1
        if any(m not in mail_g for m in g["correos"]):
            out["casadas_correo_que_google_no_tiene"] += 1
        nf = personas.clave_nombre(g["nombre"])
        nombres = {personas.clave_nombre(contactos[i]["nombre"]) for i in casados} - {None}
        if nf and nombres and nf not in nombres:
            out["casadas_nombre_distinto"] += 1
    return out


# ---------------------------------------------------------------------------------------------------------------
# P4: NocoDB → Google. Crea contactos para las fichas que Google no tiene y agrega a un contacto casado el correo que
# le falta. Solo escribe si `sincronizar` lo pide (modo `escribir`). Escrituras en serie, con tope por corrida.
# ---------------------------------------------------------------------------------------------------------------

NADA_SE_ESCRIBIO = "No se escribió nada en Google ni en NocoDB: no se pudo comprobar la columna google_id de personas."
NADA_SE_ESCRIBIO_SIN_COLUMNA = ("Falta la columna google_id en personas: no se escribió nada en Google ni en NocoDB "
                                "(tampoco la pasada de la puerta).")
GOOGLE_CREAR_URL = "https://people.googleapis.com/v1/people:createContact"
GOOGLE_ACTUALIZAR_URL = "https://people.googleapis.com/v1/{rn}:updateContact"
CAMPOS_ESCRITURA = "names,phoneNumbers,emailAddresses,metadata"
TOPE_ESCRITURAS = 500      # pedidos de escritura (altas y correos) por corrida; lo que sobra queda para la siguiente
REINTENTOS = 3             # en 429 o 5xx: hasta tres reintentos, con espera fija y corta
ESPERAS = (5, 15, 30)      # segundos antes de cada reintento
ERRORES_400_SEGUIDOS_MAX = 3   # tres 400 seguidos en actualizaciones (etag ajeno o pedido malo) paran la corrida
CLAVES_P4 = ("a_crear", "a_agregar_correo", "correos_a_agregar", "saltadas_aviso_o_por_resolver",
             "saltadas_clave_compartida", "saltadas_unida_a", "saltadas_quitada", "saltadas_ya_enlazada",
             "saltadas_casa_con_varios", "saltadas_nombre_distinto", "saltadas_sin_etag", "sin_id")


def _pedir_json(url, cuerpo, metodo, cabeceras=None, timeout=30):
    """Una escritura con cuerpo JSON (la People API lo pide así). Devuelve el JSON de la respuesta. Un error sale como
    `ErrorGoogle` con solo el código, nunca el cuerpo ni el token."""
    cab = dict(cabeceras or {})
    cab["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"), headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorGoogle("pedido", e.code) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ErrorGoogle("red", 0) from None


def _reintentable(codigo):
    return codigo == 429 or (isinstance(codigo, int) and 500 <= codigo <= 599)


def _con_reintentos(hacer, esperar):
    """Llama `hacer()`; en 429 o 5xx espera y vuelve a intentar, como mucho `REINTENTOS` veces. Lo demás sale enseguida."""
    for intento in range(REINTENTOS + 1):
        try:
            return hacer()
        except ErrorGoogle as e:
            if not _reintentable(e.codigo) or intento == REINTENTOS:
                raise
            esperar(ESPERAS[min(intento, len(ESPERAS) - 1)])
    raise ErrorGoogle("reintentos", "agotados")   # no se llega: el bucle siempre devuelve o levanta


def plan_desde_personas(contactos, fichas, ids_aviso, columna_ok):
    """Lo que P4 haría, sin escribir nada. `contactos` (de `_persona`), `fichas` (todas, con `unida_a` y `quitada_el`),
    `ids_aviso` (fichas con aviso abierto o en «Por resolver») y `columna_ok` (la columna `google_id` existe).
    Devuelve `{"cuentas": {...solo cifras...}, "crear": [...], "agregar": [...]}`. Una ficha con dato que Google no tiene
    va a «crear»; una ficha que casa con UN contacto cuyo nombre no choca, y cuyo correo Google no tiene, va a «agregar».
    Una clave (teléfono o correo) que quieren escribir dos fichas distintas hace que se salten las dos."""
    tel_g, mail_g, por_tel, por_mail = set(), set(), {}, {}
    for i, c in enumerate(contactos):
        for t in c["telefonos"]:
            tel_g.add(t)
            por_tel.setdefault(t, set()).add(i)
        for m in c["correos"]:
            mail_g.add(m)
            por_mail.setdefault(m, set()).add(i)
    cuentas = dict.fromkeys(CLAVES_P4, 0)
    crear, agregar = [], []
    for f in fichas:
        fid = f.get("Id")
        if not isinstance(fid, int) or isinstance(fid, bool):
            cuentas["sin_id"] += 1
            continue
        g = contacto_de_ficha(f)
        if not g["telefonos"] and not g["correos"]:
            continue                                   # sin dato: ni casa ni se crea (P2 lo cuenta)
        if personas.ficha_unida(f):
            cuentas["saltadas_unida_a"] += 1
            continue
        if personas.ficha_quitada(f):
            cuentas["saltadas_quitada"] += 1
            continue
        if columna_ok and str(f.get(personas.CAMPO_GOOGLE_ID) or "").strip():
            cuentas["saltadas_ya_enlazada"] += 1
            continue
        if fid in ids_aviso:
            cuentas["saltadas_aviso_o_por_resolver"] += 1
            continue
        casados = set()
        for t in g["telefonos"]:
            casados |= por_tel.get(t, set())
        for m in g["correos"]:
            casados |= por_mail.get(m, set())
        if not casados:
            crear.append({"ficha_id": fid, "nombre": g["nombre"], "telefonos": g["telefonos"], "correos": g["correos"]})
            continue
        if len(casados) != 1:
            cuentas["saltadas_casa_con_varios"] += 1
            continue
        c = contactos[next(iter(casados))]
        if _nombre_distinto(c["nombre"], f):
            cuentas["saltadas_nombre_distinto"] += 1
            continue
        faltan = [m for m in g["correos"] if m not in mail_g]
        if not faltan:
            continue
        if not c.get("rn") or not (c.get("fuente") or {}).get("etag"):
            cuentas["saltadas_sin_etag"] += 1
            continue
        agregar.append({"ficha_id": fid, "rn": c["rn"], "etag": c["fuente"]["etag"],
                        "crudos": list(c["correos_crudos"]), "correos": faltan})
    # Una clave que quieren escribir dos fichas distintas: se saltan las dos (no nacen dos contactos con el mismo dato).
    usos = {}
    for x in crear:
        for t in x["telefonos"]:
            usos.setdefault(("t", t), set()).add(x["ficha_id"])
        for m in x["correos"]:
            usos.setdefault(("m", m), set()).add(x["ficha_id"])
    for x in agregar:
        for m in x["correos"]:
            usos.setdefault(("m", m), set()).add(x["ficha_id"])
    compartidas = {fid for fs in usos.values() if len(fs) > 1 for fid in fs}
    crear_ok = []
    for x in crear:
        if x["ficha_id"] in compartidas:
            cuentas["saltadas_clave_compartida"] += 1
        else:
            crear_ok.append(x)
    agregar_ok = []
    for x in agregar:
        if x["ficha_id"] in compartidas:
            cuentas["saltadas_clave_compartida"] += 1
        else:
            agregar_ok.append(x)
    cuentas["a_crear"] = len(crear_ok)
    cuentas["a_agregar_correo"] = len(agregar_ok)
    cuentas["correos_a_agregar"] = sum(len(x["correos"]) for x in agregar_ok)
    return {"cuentas": cuentas, "crear": crear_ok, "agregar": agregar_ok}


def ejecutar_desde_personas(plan, token, pedir_json, enlazar, esperar, tope=TOPE_ESCRITURAS):
    """Escribe el plan, en serie. «creado» solo si Google devolvió el `resourceName` y `enlazar` confirmó la ficha. Si el
    enlace falla, se cuenta `creado_sin_enlace`: lo creado en Google no se deshace, y la ficha puede quedar sin `google_id`
    (si el PATCH no entró) o con él (si entró y solo falló la relectura). La siguiente corrida no crea otro contacto: una
    ficha con `google_id` se salta, y una sin él casa con lo creado por teléfono o correo. Si NocoDB lanza una excepción al
    enlazar, el alta cuenta igual como `creado_sin_enlace` y la corrida para (`parada` = `enlace:<tipo>`). «agregado» solo si
    la respuesta trae el correo. El alta no se reintenta: un 5xx en el alta para la corrida con `parada` = `alta_incierta`
    (Google pudo haber guardado el contacto; la ficha queda pendiente y sin `google_id`). Para ante un error de Google que no se reintenta (salvo un 400 de una actualización de correo: ese no cuenta,
    sigue con el siguiente, y la corrida para tras tres seguidos), ante un tope, o si Google no confirma un alta.
    `pendientes` cuenta lo que no se hizo. Solo cifras: nada de nombres, teléfonos ni correos."""
    cab = {"Authorization": "Bearer " + token}
    out = {"creados": 0, "creado_sin_enlace": 0, "alta_incierta": 0, "correos_agregados": 0, "no_confirmados": 0, "errores_400": 0,
           "pendientes": 0, "parada": None, "tope": tope}
    trabajo = [("crear", x) for x in plan["crear"]] + [("agregar", x) for x in plan["agregar"]]
    hechas, seguidos400 = 0, 0
    for idx, (tipo, x) in enumerate(trabajo):
        if hechas >= tope:
            out["parada"], out["pendientes"] = "tope", len(trabajo) - idx
            break
        hechas += 1
        try:
            if tipo == "crear":
                nombre = x["nombre"]
                cuerpo = {}
                if nombre:
                    cuerpo["names"] = [{"givenName": nombre}]
                if x["telefonos"]:
                    cuerpo["phoneNumbers"] = [{"value": t} for t in x["telefonos"]]
                if x["correos"]:
                    cuerpo["emailAddresses"] = [{"value": m} for m in x["correos"]]
                url = GOOGLE_CREAR_URL + "?" + urllib.parse.urlencode({"personFields": CAMPOS_ESCRITURA})
                r = pedir_json(url, cuerpo, "POST", cab)   # el alta NO se reintenta: un 5xx puede ser un alta guardada (ver `alta_incierta`)
                rn = r.get("resourceName") if isinstance(r, dict) else None
                if not isinstance(rn, str) or not rn.startswith("people/"):
                    out["no_confirmados"] += 1
                    out["parada"], out["pendientes"] = "alta_sin_confirmar", len(trabajo) - idx
                    break
                try:
                    enlazado = enlazar(x["ficha_id"], rn)
                except Exception as e_enlace:  # noqa: BLE001  (NocoDB falló al enlazar: el alta YA está hecha en Google)
                    out["creado_sin_enlace"] += 1
                    out["parada"], out["pendientes"] = "enlace:" + type(e_enlace).__name__, len(trabajo) - idx - 1
                    break
                if enlazado:
                    out["creados"] += 1
                else:
                    out["creado_sin_enlace"] += 1
            else:
                cuerpo = {"metadata": {"sources": [{"type": "CONTACT", "etag": x["etag"]}]},
                          "emailAddresses": x["crudos"] + [{"value": m} for m in x["correos"]]}
                url = GOOGLE_ACTUALIZAR_URL.format(rn=x["rn"]) + "?" + urllib.parse.urlencode(
                    {"updatePersonFields": "emailAddresses", "personFields": CAMPOS_ESCRITURA})
                r = _con_reintentos(lambda: pedir_json(url, cuerpo, "PATCH", cab), esperar)
                vistos = {str(e.get("value", "")).strip().lower() for e in (r.get("emailAddresses") or [])
                          if isinstance(e, dict)} if isinstance(r, dict) else set()
                if isinstance(r, dict) and r.get("resourceName") == x["rn"] and all(m in vistos for m in x["correos"]):
                    out["correos_agregados"] += len(x["correos"])
                else:
                    out["no_confirmados"] += 1
            seguidos400 = 0
        except ErrorGoogle as e:
            if tipo == "crear" and isinstance(e.codigo, int) and 500 <= e.codigo <= 599:
                # Alta incierta: Google pudo haber guardado el contacto y no lo sabemos. No se reintenta (decisión de Tiziano:
                # nunca dos personas con el mismo número). La ficha queda pendiente, sin google_id, y la corrida para.
                out["alta_incierta"] += 1
                out["parada"], out["pendientes"] = "alta_incierta", len(trabajo) - idx
                break
            if tipo == "agregar" and e.codigo == 400:          # etag distinto (otro cambió el contacto) o pedido que Google no acepta
                out["errores_400"] += 1
                seguidos400 += 1
                if seguidos400 >= ERRORES_400_SEGUIDOS_MAX:
                    out["parada"], out["pendientes"] = "400_seguidos", len(trabajo) - idx
                    break
                continue
            out["parada"], out["pendientes"] = f"{e.etapa}:{e.codigo}", len(trabajo) - idx
            break
        except Exception as e:  # noqa: BLE001  (cualquier otro fallo: se para y se dice; lo ya escrito en Google no se deshace)
            out["parada"], out["pendientes"] = type(e).__name__, len(trabajo) - idx
            break
    return out


def desde_personas_a_google(token, contactos, escribir, pedir_json, enlazar, esperar, tope=TOPE_ESCRITURAS):
    """P4 completo: lee las fichas (con `google_id` si la columna existe) y los avisos abiertos, arma el plan y, solo si
    `escribir`, lo ejecuta. Sin la columna, no escribe nada y lo dice. Si la lectura de avisos no es completa, no escribe
    nada. Devuelve solo cifras y el estado."""
    try:
        columna_ok = personas.columna_google_id_existe()
        fichas = personas.leer_fichas_para_google(columna_ok)
        estado_av, ids_av = personas.ids_por_resolver()
    except Exception as e:  # noqa: BLE001
        return {"estado": "no_se_pudo_leer", "motivo": type(e).__name__, "escrito": None}
    if estado_av != "ok":
        return {"estado": "avisos_no_leidos", "motivo": estado_av, "escrito": None}
    plan = plan_desde_personas(contactos, fichas, ids_av, columna_ok)
    out = {"estado": "ok", "columna_google_id": columna_ok, "cuentas": plan["cuentas"], "escrito": None}
    if not escribir:
        return out
    if not columna_ok:
        out["aviso"] = "Falta la columna google_id en personas: no se escribió nada en Google ni en NocoDB."
        return out
    out["escrito"] = ejecutar_desde_personas(plan, token, pedir_json, enlazar, esperar, tope)
    return out


# ---------------------------------------------------------------------------------------------------------------
# P6: el reloj. Un hilo dentro de la App (`registro-cds`) que corre `sincronizar` cada hora: lo mismo que
# `tools/sincronizar_contactos_google.py` corre a mano. Apagado por defecto: sin `CONTACTOS_GOOGLE_RELOJ` = `encendido`,
# no arranca ningún hilo y ninguna corrida toca Google ni NocoDB. Encendido, `sincronizar` decide la escritura igual que
# a mano: solo escribe si `CONTACTOS_GOOGLE_MODO` = `escribir`. El reloj no tiene compuerta de escritura propia.
# Los candados de la puerta son del proceso: el hilo corre DENTRO del proceso de la App, así que los comparte.
# ---------------------------------------------------------------------------------------------------------------

VARIABLE_RELOJ = "CONTACTOS_GOOGLE_RELOJ"
RELOJ_ENCENDIDO = "encendido"     # el valor EXACTO, como `modo` con `escribir`
INTERVALO_SEG = 3600              # cada hora. Fijo: no hay variable de frecuencia (Tiziano, 2-nov-2026: «Bueno pues dale»)
ETIQUETA_LINEA = "[CONTACTOS-RELOJ]"
_CANDADO_CORRIDA = threading.Lock()   # una corrida a la vez dentro del proceso (`correr_una_vez`)
_CORRIDAS = itertools.count(1)        # número de cada intento, para leerlos en el registro


def reloj_encendido(env):
    """`True` solo si `CONTACTOS_GOOGLE_RELOJ` vale exactamente `encendido`. Ausente, vacía, con espacios o en otras
    mayúsculas: apagado."""
    valor = env.get(VARIABLE_RELOJ)
    return isinstance(valor, str) and valor == RELOJ_ENCENDIDO


def _cifras(r):
    """Las cifras de una corrida, como pares (clave, valor). Solo números y códigos: ni nombres, ni teléfonos, ni correos,
    ni Ids de fichas, ni el texto de ningún aviso."""
    cont = r.get("contar") or {}
    esc = r.get("escrito") or {}
    p4 = r.get("p4") or {}
    cu = p4.get("cuentas") or {}
    p4e = p4.get("escrito") or {}
    return [
        ("modo", r.get("modo")),
        ("contactos", cont.get("contactos", 0)),
        ("puerta_altas", cont.get("altas", 0)),
        ("puerta_altas_escritas", esc.get("altas", 0) if esc else "-"),
        ("p4", p4.get("estado")),
        ("p4_a_crear", cu.get("a_crear", "-")),
        ("p4_a_agregar_correo", cu.get("a_agregar_correo", "-")),
        ("p4_creados", p4e.get("creados", "-")),
        ("p4_correos_agregados", p4e.get("correos_agregados", "-")),
        ("p4_parada", p4e.get("parada") or "-"),
        ("aviso", "si" if r.get("aviso") else "no"),
    ]


def _escribir_linea(numero, estado, resultado=None, motivo=None, segundos=None):
    """Una línea de resumen en el registro de la App por corrida del reloj: `[CONTACTOS-RELOJ] corrida=N estado=… motivo=… <cifras>
    segundos=N`. Durante esa corrida la puerta calla sus líneas de registro `[PUERTA-FICHAS]` y `[PUERTA-FICHAS-ORIGEN]`
    (flag `personas.SILENCIO_PUERTA_REGISTRO`). Los `[warn] puerta de fichas` de un fallo de la base (por ejemplo, un rechazo
    al crear una ficha) NO se callan: salen aparte, uno por fallo, junto a la línea de resumen. Sin fallo de la base, el
    resumen es la única línea de la corrida. El `motivo` es un código (nombre de una clase de excepción, `etapa:codigo` de
    Google, o nombres de variables), nunca el texto de un error."""
    partes = ["corrida=%d" % numero, "estado=%s" % estado]
    if motivo is not None:
        partes.append("motivo=%s" % motivo)
    if resultado is not None:
        partes += ["%s=%s" % (k, v) for k, v in _cifras(resultado)]
    if segundos is not None:
        partes.append("segundos=%d" % segundos)
    print(ETIQUETA_LINEA + " " + " ".join(partes), flush=True)


def correr_una_vez(env, recibir=None, **dobles):
    """Una corrida del reloj: `sincronizar` (P3 + P4) con `personas.recibir` (la puerta) y `personas.enlazar_ficha_con_google`,
    los de la App. `recibir` y `dobles` (`pedir`, `leer_fichas`, `pedir_json`, `enlazar`, `esperar`) existen para las
    pruebas; el reloj no los pasa.

    Apagado: no hace nada y devuelve `None` (no toca Google ni NocoDB). Si la corrida anterior sigue, esta no arranca:
    deja su línea con `estado=ya_corriendo` y devuelve `ya_corriendo`. Si no, devuelve el estado de la corrida:
    `ok`, `sin_credencial`, `error_google` o `error`. NUNCA levanta una excepción: un fallo queda en su línea y el hilo sigue."""
    if not reloj_encendido(env):
        return None
    numero = next(_CORRIDAS)
    if not _CANDADO_CORRIDA.acquire(blocking=False):
        _escribir_linea(numero, "ya_corriendo", motivo="la corrida anterior sigue")
        return "ya_corriendo"
    inicio = time.monotonic()
    resultado, motivo = None, None
    try:
        personas.SILENCIO_PUERTA_REGISTRO.activo = True    # solo este hilo: la puerta calla su línea por contacto
        try:
            resultado = sincronizar(env, recibir or personas.recibir, **dobles)
            estado = "ok"
        except SinCredencial as e:
            estado, motivo = "sin_credencial", ",".join(e.faltan)      # solo los NOMBRES de las variables
        except ErrorGoogle as e:
            estado, motivo = "error_google", "%s:%s" % (e.etapa, e.codigo)   # sin el cuerpo de Google ni el token
        except Exception as e:  # noqa: BLE001  (cualquier otro fallo: se dice con el nombre de su clase, no con su texto)
            estado, motivo = "error", type(e).__name__
    finally:
        personas.SILENCIO_PUERTA_REGISTRO.activo = False
        _CANDADO_CORRIDA.release()
    _escribir_linea(numero, estado, resultado, motivo, round(time.monotonic() - inicio))
    return estado


def reloj(env, recibir=None, pausa=None, intervalo=INTERVALO_SEG, vueltas=None, **dobles):
    """El hilo: una corrida, una pausa de `intervalo` segundos y otra vez. En producción no tiene tope (`vueltas` es None).
    `vueltas` y `pausa` existen para las pruebas: no se espera de verdad. Una corrida que falla no lo para
    (`correr_una_vez` no levanta excepciones)."""
    pausa = pausa or time.sleep
    n = 0
    while vueltas is None or n < vueltas:
        n += 1
        correr_una_vez(env, recibir, **dobles)
        pausa(intervalo)


def arrancar_reloj(env):
    """Lo llama `server.main()` al arrancar el servidor (NO al importar `server`). Apagado: una línea de aviso y ningún hilo.
    Encendido: un hilo daemon con `reloj`. Devuelve el hilo, o `None`."""
    if not reloj_encendido(env):
        print(ETIQUETA_LINEA + " apagado: %s no vale '%s'. No corre nada." % (VARIABLE_RELOJ, RELOJ_ENCENDIDO), flush=True)
        return None
    hilo = threading.Thread(target=reloj, args=(env,), daemon=True, name="contactos-google-reloj")
    hilo.start()
    print(ETIQUETA_LINEA + " encendido: corre cada %d segundos." % INTERVALO_SEG, flush=True)
    return hilo
