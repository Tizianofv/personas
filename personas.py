# -*- coding: utf-8 -*-
"""LA ZONA «PERSONAS» del servidor: la caché de personas, el BSUID y los teléfonos, el portal «Personas» y la edición de la ficha.

Salió de `server.py` el 7-oct-2026 (paso 6 del plano `disenos/registro-division-por-zonas/PLANO.md`). Es el primer módulo
de zona del servidor y estrena la técnica; el mapa de cómo se parte y cómo se muda otra zona está en
`Levantamientos INFO/registro/como-esta-partido-el-servidor.md`.

LA TÉCNICA DE ESTE REPO, en cuatro reglas:
  1. Este módulo NO importa al servidor: en este repo no hay servidor de la App. `tests/test_sin_app.py` vigila los `import`
     y los nombres `server` y `S`; su frontera está declarada en esa prueba.
  2. Lo que no está definido aquí y no es de Python se escribe `_base.<nombre>` (`base.py`: constantes y el cliente de NocoDB).
  3. Lo que sí está definido aquí se llama por su nombre.
  4. `_base.<nombre>` se busca en el módulo `base` al momento de la llamada, así que lo que una prueba reemplaza en `base`
     lo ve este código.
Cada función se copió de la App (`0b48b5d`) cambiando `S.<x>` por `_base.<x>` o por `<x>`; la equivalencia se comprobó por AST
con los docstrings quitados. Lo que se evalúa al importar y depende de otra zona no está aquí: `PORTAL_COLUMNAS_VETADAS` vive
en `base.py`.
"""
import contextlib
import hashlib
import json
import re
import threading
import time
import unicodedata
from datetime import date, timedelta, timezone
from datetime import datetime as _fecha_hora      # con alias: `datetime` es un nombre que las pruebas reasignan en el servidor y aquí se escribiría `_base.datetime`
import base as _base   # la base de Personas (constantes y cliente de NocoDB); antes era `S.` de server.py



def ficha_unida(fila):
    """¿Esta fila de `personas` está marcada como unida a otra? Sí si `unida_a` trae algo escrito."""
    v = fila.get("unida_a") if isinstance(fila, dict) else None
    return v is not None and str(v).strip() != ""


def ficha_quitada(fila):
    """¿Esta fila de `personas` está guardada aparte (la quitaron de Personas)? Sí si `quitada_el` trae algo escrito.
    Diseño `disenos/registro-borrar-fichas/DISENO.md` §5.1: la fila no se borra; se vacían sus casillas de contacto y se marca."""
    v = fila.get("quitada_el") if isinstance(fila, dict) else None
    return v is not None and str(v).strip() != ""


def sonda_de_tabla():
    """Una lectura de UNA fila de `personas` sin datos (`limit 1`, solo `Id`): sirve para saber que NocoDB contesta antes de escribir
    (G-C6 de las escrituras de Registro). Es la puerta quien lee; quien llama no toca la tabla. Solo lee. Si no contesta, levanta.
    """
    _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records", query={"limit": 1, "fields": "Id"})


def leer_ficha_para_lucy(persona_id):
    """La fila de `personas` con ese `Id`, con los campos de `_base.CAMPOS_DE_UNA_FICHA`. `None` si no existe o no vino como fila.
    Es la lectura que `server.py` hacía directo (`_leer_una_ficha_para_lucy`); Lucy la pide ahora por la puerta (paso 3c). Solo lee."""
    try:
        fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(persona_id)}", query={"fields": _base.CAMPOS_DE_UNA_FICHA})
    except _base.ErrorDeNocodb as e:
        if e.status == 404:
            return None
        raise
    return fila if isinstance(fila, dict) and fila.get("Id") is not None else None


def ficha_fuera(fila):
    """¿Esta ficha NO se muestra ni se usa como una ficha viva? Sí si está unida a otra o guardada aparte. La usan los lectores
    de la lista de personas (`get_personas`, `_portal_leer_todas`, `_portal_leer_fila`, proveedores, la lectura de la puerta,
    `_puerta_recibir`). Otros lectores de `server.py` (`guardar_cara`, `hacer_checkin`, Lucy, la revisión y el re-leer de la
    unión) comparan `ficha_quitada` o `ficha_unida` directamente: ver `Levantamientos INFO/registro/las-fichas-de-clientes.md`."""
    return ficha_unida(fila) or ficha_quitada(fila)


# ---------- cache de personas (para búsqueda con normalización) ----------

_personas_cache = {"data": None, "ts": 0.0}
_personas_lock = threading.Lock()
PERSONAS_TTL = 60  # segundos

# `Posible_proveedor` (pieza 2 del módulo Proveedores): la casilla del ✎ del check-in la carga de aquí. `Precio_referencia` NO va: el check-in no la toca.
PERSONA_FIELDS = "Id,nombre,nombre_whatsapp,telefono,telefono_2,instagram,email,email_2,instrumento,genero,Cumpleanos,notas,Posible_proveedor"


def get_personas(force=False):
    with _personas_lock:
        fresh = _personas_cache["data"] is not None and (time.time() - _personas_cache["ts"]) < PERSONAS_TTL
        if fresh and not force:
            return _personas_cache["data"]
        # Las fichas unidas a otra y las guardadas aparte no salen; `unida_a` y `quitada_el` se piden para saberlo y no viajan.
        data = [{k: v for k, v in p.items() if k not in ("unida_a", "quitada_el")}
                for p in _base.nc_list_all(_base.T_PERSONAS, {"fields": PERSONA_FIELDS + ",unida_a,quitada_el"}) if not ficha_fuera(p)]
        _personas_cache["data"] = data
        _personas_cache["ts"] = time.time()
        return data


def invalidate_personas():
    with _personas_lock:
        _personas_cache["data"] = None
    # La lista del portal «Personas» es otra copia de la misma tabla: se tira con ésta. Se resuelve el
    # nombre al llamar (la función se define más abajo en el archivo).
    invalidate_portal_personas()


def normalizar(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def solo_digitos(s):
    return re.sub(r"\D", "", str(s or ""))


# ── Personas SIN TELÉFONO (BSUID de WhatsApp) ────────────────────────────────────────
#
# Desde 2026 Meta identifica a algunas personas con un **BSUID** (Business-Scoped User ID)
# en vez de un número: `DO.4596590323916838` — dos letras de país, un punto y hasta 128
# alfanuméricos. Existe para que la gente pueda usar un @usuario y **esconder su teléfono
# del negocio**. Ya viene en casi todo el tráfico (212 mensajes medidos el 27-ago, 188 de
# ellos junto al teléfono): **no es un caso raro, es lo que viene siendo normal.**
#
# 🔴 EL BSUID SE GUARDA Y SE PASA COMPLETO, NUNCA `solo_digitos()`:
# `re.sub(r"\D","",…)` lo deja en `4596590323916838` — **dieciséis dígitos que el sistema
# acepta como un teléfono internacional perfectamente válido**, y con eso le crea una ficha
# fantasma a una persona. El prefijo no es decoración: es lo único que lo distingue.
RE_BSUID = re.compile(r"\A[A-Z]{2}\.[A-Za-z0-9]{1,128}\Z")

# El identificador de una conversación en las URLs: un teléfono O un BSUID. Se escribe una
# sola vez y se usa en las tres rutas — cuando esto era `(\d+)` a secas, las conversaciones
# sin teléfono aparecían en la lista y daban **404 al abrirlas**, que es peor que no
# mostrarlas: promete algo que no cumple.
RE_IDENT_CONV = r"(\d+|[A-Za-z]{2}\.[A-Za-z0-9]{1,128})"


def es_bsuid(x):
    """True si la identidad es un BSUID (persona sin teléfono) y no un número."""
    return bool(RE_BSUID.match(str(x or "")))


def _identidad_hacia_natalia(x):
    """Cómo viaja la LLAVE de una conversación hacia Natalia: un teléfono en dígitos, y
    cualquier otra cosa (un BSUID) ENTERA. Nunca `solo_digitos()` sobre lo que no sea ya
    solo dígitos: le arrancaría el `DO.` y dejaría dieciséis dígitos que parecen un teléfono.

    Esto decide la FORMA de la llave, no si la persona «tiene número»: eso lo decide solo
    `numero_de_identidad`, mirando la ficha.
    """
    x = str(x or "")
    return x if not x.isdigit() else solo_digitos(x)


# 🔴 LA PUERTA ÚNICA DE «¿TIENE NÚMERO?» (29-sep-2026). Antes era `sin_numero(x)`, que decidía
# por la FORMA de la identidad: todo BSUID daba «Sin número» aunque su ficha en `personas`
# tuviera teléfono —quien escribe con @usuario y ya dejó su número en una reserva se veía sin
# número—. Tiziano: «en la página de las conversaciones, abajo de su nombre también dice sin
# número».
#
# Ahora se mira la FICHA: `personas.bsuid` → `personas.telefono`. Devuelve el número (solo
# dígitos) o `None`. Cae del lado de «Sin número» —lo de antes— cuando no se puede afirmar:
#   · la identidad no es ni un teléfono ni un BSUID válido;
#   · NocoDB no contesta (la página sigue funcionando, mostrando la identidad);
#   · no hay ficha con ese `bsuid`;
#   · hay MÁS DE UNA ficha con ese `bsuid` (aunque coincidan: no se elige una);
#   · la ficha tiene el teléfono vacío o algo que no es un teléfono.
# El BSUID nunca se pasa por `solo_digitos()` (ver arriba): un teléfono de la ficha que sean
# dieciséis dígitos —el BSUID pelado— no se acepta como número.
_TEL_FICHA_MIN, _TEL_FICHA_MAX = 8, 15     # E.164: un teléfono internacional tiene ≤ 15 dígitos


def _telefono_de_ficha(celda):
    """El teléfono de una celda de `personas.telefono`, en dígitos, o `None` si no lo es."""
    txt = str(celda or "").strip()
    if not txt or re.search(r"[^\d\s()+\-]", txt):
        return None
    d = solo_digitos(txt)
    if not (_TEL_FICHA_MIN <= len(d) <= _TEL_FICHA_MAX):
        return None
    return normalizar_telefono(d)


def _numeros_de_identidades(idents, leer_fichas, tragar):
    """EL CUERPO ÚNICO de la regla (`{identidad: número o None}`): un número es él mismo; un ID de WhatsApp da el teléfono de la ÚNICA ficha que lo tiene, si es válido; todo lo demás, `None`.
    `leer_fichas(where)` devuelve las filas de `personas` (`Id,telefono,bsuid`) para ese `where` (por cada 80 BSUID distintos, nunca una por conversación). `tragar`: si la lectura levanta, `True` = se
    imprime un aviso y esas identidades quedan en `None` (lo de siempre); `False` = el error sube (quien llama no puede dar por buena una lista corta)."""
    idents = [str(i or "").strip() for i in idents]
    salida = {}
    bsuids = []
    for i in idents:
        if i.isdigit():
            salida[i] = i
        elif es_bsuid(i):
            salida[i] = None
            if i not in bsuids:
                bsuids.append(i)
        else:
            salida[i] = None
    for k in range(0, len(bsuids), 80):
        lote = bsuids[k:k + 80]
        where = "~or".join(f"(bsuid,eq,{b})" for b in lote)
        try:
            fichas = leer_fichas(where)
        except Exception as e:
            if not tragar:
                raise
            print(f"[aviso] no se pudo leer la ficha por bsuid ({type(e).__name__}): "
                  "se muestra la identidad")                  # NocoDB caído: lado de «Sin número»
            continue
        por_bsuid = {}
        for f in fichas:
            # Solo cuentan las filas cuyo `bsuid` es EXACTAMENTE uno de los PEDIDOS en este
            # lote: si el `where` dejara pasar fichas ajenas (o con `bsuid` vacío), se ignoran y
            # no le dan número a nadie. Sin `.strip()`: NocoDB compara `eq` exacto (medido el
            # 29-sep-2026: con un espacio de más, o en minúsculas, 0 filas), así que una fila con
            # espacios no puede llegar por un `eq` bien hecho; si llegara, cae del lado seguro.
            b = str(f.get("bsuid") or "")
            if b in lote:
                por_bsuid.setdefault(b, []).append(f)
        for b, fs in por_bsuid.items():
            if len(fs) == 1:
                salida[b] = _telefono_de_ficha(fs[0].get("telefono"))
    return salida


def _leer_fichas_por_bsuid(where):
    return _base.nc_list_all(_base.T_PERSONAS, {"where": where, "fields": "Id,telefono,bsuid"})


def numeros_de_identidades(idents):
    """`{identidad: número o None}` para todas las identidades de la lista, con UNA consulta
    a `personas` por cada 80 BSUID distintos (nunca una por conversación). Si NocoDB no contesta, esas identidades
    quedan en `None` (aviso en el registro). La regla está en `_numeros_de_identidades`."""
    return _numeros_de_identidades(idents, _leer_fichas_por_bsuid, True)


def numeros_de_identidades_estricto(idents, leer_fichas):
    """LA MISMA regla (`_numeros_de_identidades`), con la lectura de fichas que pone quien llama (`leer_fichas(where)`) y SIN tragar el error: si la lectura levanta, esto levanta. Para
    quien no puede dar por buena una lista corta (Leads)."""
    return _numeros_de_identidades(idents, leer_fichas, False)


def numero_de_identidad(ident):
    """El número de esta conversación o `None`. UNA sola puerta: ver el bloque de arriba."""
    return numeros_de_identidades([ident])[str(ident or "").strip()]


# 🔴 ESTE TEXTO CAMBIÓ POR UNA ORDEN DE TIZIANO (27-ago-2026). Antes decía «No se le puede
# ligar un comprobante ni cobrarle desde acá», y su respuesta fue, textual:
# *«es grabe hay que poder ligar comprobante cobrar desde la app»*.
#
# 🔑 EL PROBLEMA NO ERA QUE FUERA FALSO —hoy es cierto: el matcher busca sesiones POR
# TELÉFONO, así que sin número no hay candidatas— **era que describía un callejón sin
# salida, y la salida existe: pedirle el número.** Un cartel que solo enumera lo que no se
# puede hacer deja a quien lo lee sin nada que hacer; y quien lo lee es la persona que
# tiene al cliente escribiendo del otro lado, en el único momento en que pedírselo es fácil.
#
# Por eso ahora nombra el límite Y la salida, en ese orden. El arreglo de fondo (que el
# dinero acepte una segunda llave) es grande y va con levantamiento; esto es la mitad
# barata y no lo reemplaza.
MOTIVO_SIN_NUMERO = ("Escribió con usuario de WhatsApp y no compartió su número. "
                     "Se le puede escribir igual, pero para cobrarle o ligarle un "
                     "comprobante hay que pedirle el número.")


def normalizar_telefono(s):
    """Formato canónico = wa_id de WhatsApp: solo dígitos, con el 1 de país, sin + ni espacios
    (ej. 18091234567). 10 dígitos (área+número RD) → se antepone el 1. Vacío → None.
    Números que no calzan el patrón RD se dejan en solo-dígitos (no se mutilan)."""
    d = solo_digitos(s)
    if not d:
        return None
    if len(d) == 10:                       # 809/829/849 + 7 dígitos → falta el 1
        d = "1" + d
    return d


def buscar_personas(q, limit=12):
    """El buscador del check-in y de «Personas». **Los teléfonos de la ficha son los DOS** (principal y secundario, parte 4):
    quien teclea el segundo número encuentra a la persona, igual que con el primero."""
    return buscar_en_fichas(get_personas(), q, limit)


def buscar_en_fichas(fichas, q, limit=12):
    """La regla del buscador sobre una lista de fichas ya leída: `buscar_personas` le pasa la caché de `get_personas`, y la ruta
    de servicio `personas_servicio_rutas.buscar` le pasa una lectura estricta. Mismo orden por score y mismo tope."""
    qn = normalizar(q)
    qd = solo_digitos(q)
    resultados = []
    for p in fichas:
        nombre = normalizar(p.get("nombre"))
        wsp = normalizar(p.get("nombre_whatsapp"))
        ig = normalizar(p.get("instagram"))
        tels = [d for d in (solo_digitos(p.get("telefono")), solo_digitos(p.get("telefono_2"))) if d]
        score = 0
        if qn:
            if nombre.startswith(qn) or any(w.startswith(qn) for w in nombre.split()):
                score = 3
            elif qn in nombre or qn in wsp or qn in ig:
                score = 2
        if len(qd) >= 4 and any(qd in tel for tel in tels):
            score = max(score, 3)
        if score:
            resultados.append((score, p))
    resultados.sort(key=lambda t: (-t[0], normalizar(t[1].get("nombre"))))
    return [p for _, p in resultados[:limit]]


# ═══════════════════════════════════════════════════════════════════════════════════════

# ---------- el portal «Personas» — PARTE 1 de 4: VER (entrar, lista, buscar, ordenar, abrir la ficha) ----------
#
# Pedido de Tiziano (6-oct-2026): «Oye quiero un portal en el app que se llame personas donde pueda ver
# todo lo que veo en personas en Noco». Diseño y maqueta aprobados: `disenos/registro-portal-personas/`.
# Esta parte NO escribe nada: lee la tabla `personas` (`T_PERSONAS`) directo, por `nc()`, sin pasar por
# Natalia. Las partes 2 (editar y crear), 3 (borrar) y 4 (unir) cuelgan de la misma puerta y la misma lista.
#
# 🔑 UNA SOLA PUERTA: `Handler.entra_personas()`. Todas las rutas del portal viven bajo
# `PORTAL_PERSONAS_RUTA` y pasan por el MISMO `if` de `do_GET`; una prueba saca las rutas del fuente y exige
# que ninguna se salte la puerta.
#
# 🔴 QUÉ COLUMNAS VIAJAN AL NAVEGADOR — tres cubos, y lo no clasificado NO viaja:
#   · VISIBLES: las de `PORTAL_FICHA_GRUPOS` (lo único que se le pide a NocoDB, con `fields=`, y lo único que
#     se deja pasar a la respuesta aunque NocoDB mandara más).
#   · VETADAS: `caras` (datos biométricos) y las que `_APRENDIZAJE_CAMPOS_NUNCA` ya declara nunca-al-navegador,
#     MENOS `credito`: el crédito a favor sí se ve en este portal (está en la maqueta aprobada y la puerta es
#     solo de quien pasa `entra_personas()`); en el espacio de aprendizaje de Natalia sigue vetado, como estaba.
#   · NO SON DATO: llaves, fechas del sistema y columnas de enlace (sesiones, pagos…), que nunca se piden.
# Una columna que aparezca mañana en la tabla y no esté en ninguno de los tres cubos no se pide ni se manda:
# `portal_columnas_sin_clasificar` la nombra y la pantalla lo dice, hasta que alguien la clasifique.
PORTAL_PERSONAS_RUTA = "/api/portal-personas"
PORTAL_PAGINA = 50          # filas por página si el pedido no dice
PORTAL_PAGINA_MAX = 100     # techo de filas por página
PORTAL_CACHE_SEG = 30       # cuánto dura la lista entera en memoria (se tira también al escribir una persona)
PORTAL_BUSQUEDA_MAX = 100   # letras de la búsqueda que se miran
PORTAL_ACTIVIDAD_REINTENTO_SEG = 5   # si no se pudo leer `asistencias`, la lista (con lo viejo) dura esto y no `PORTAL_CACHE_SEG`: se vuelve a intentar pronto (número de diseño, no medido)

# (llave de la columna, etiqueta, tipo para dibujarla). El orden y las etiquetas son los de la maqueta.
PORTAL_FICHA_GRUPOS = (
    ("Contacto", (
        ("nombre", "Nombre", "texto"),
        ("telefono", "Teléfono", "texto"),
        ("telefono_2", "Teléfono 2", "texto"),
        ("nombre_whatsapp", "Nombre en WhatsApp", "texto"),
        ("email", "Email", "texto"),
        ("email_2", "Email 2", "texto"),
        ("instagram", "Instagram", "texto"),
        ("Cumpleanos", "Cumpleaños", "texto"),
        ("instrumento", "Instrumento", "texto"),
        ("genero", "Género", "texto"),
    )),
    ("Perfil", (
        ("Tono", "Tono", "largo"),
        ("Clave", "Clave", "largo"),
        ("Preferencias_operativas", "Preferencias operativas", "largo"),
        ("Comportamiento_reserva", "Comportamiento de reserva", "largo"),
        ("Resumen", "Resumen", "largo"),
        ("notas", "Notas", "largo"),
        ("Sensibilidad_precio", "Sensibilidad al precio", "largo"),
        ("Riesgo_noshow", "Riesgo de no-show", "texto"),
        ("Consumo", "Consumo", "largo"),
    )),
    ("Actividad (lo llena el sistema)", (
        ("Visitas", "Visitas", "numero"),
        ("Ultima_visita", "Última visita", "fecha"),
        ("credito", "Crédito a favor", "dinero"),
        ("Monto_tipico", "Monto típico", "texto"),
        ("Forma_pago", "Forma de pago", "texto"),
        ("Sala_preferida", "Sala preferida", "texto"),
        ("Fuentes", "Fuentes", "texto"),
        ("Agendo", "Agendó", "texto"),
        ("Maestro_id", "Id en Maestro Clientes", "numero"),
    )),
    # 🧾 «Proveedor» (módulo Proveedores, pieza 1, 14-oct-2026; va al final para no mover los grupos de antes): una marca y un número por persona, en la ficha y no en una tabla aparte
    # (`disenos/proveedores/DISENO.md`, §2). `Posible_proveedor` es un SingleSelect de una sola opción, `Si` (vacío = no es proveedor);
    # `Precio_referencia` es un Decimal en RD$ sin unidad (por hora o por trabajo va en las notas). Las crea la sala en NocoDB ANTES de desplegar.
    ("Proveedor", (
        ("Posible_proveedor", "Posible proveedor", "texto"),
        ("Precio_referencia", "Precio de referencia (RD$)", "dinero"),
    )),
)
PORTAL_COLUMNAS_VISIBLES = tuple(llave for _, campos in PORTAL_FICHA_GRUPOS for llave, _, _ in campos)
# Lo que lleva cada fila de la lista (las ocho columnas de la maqueta; una persona se identifica por `Id`). `telefono_2` y
# `email_2` no se pintan en la lista: viajan porque «Por resolver» calcula sus grupos de estas mismas filas (`por_resolver_grupos`)
# y porque buscar en la lista tiene que encontrar el segundo número y el segundo correo (`_portal_preparar`).
PORTAL_LISTA_CAMPOS = ("Id", "nombre", "nombre_whatsapp", "telefono", "telefono_2", "email", "email_2", "instagram", "Cumpleanos", "Visitas",
                       "Ultima_visita", "credito")
PORTAL_COLUMNAS_NO_DATO = frozenset({
    "Id", "CreatedAt", "UpdatedAt",
    "inscripciones", "Maestro Clientes",                        # marcadores de columnas de enlace
    "inscripciones1", "pagos", "sesiones", "proyectos", "asistencias_link",  # enlaces a otras tablas
    "unida_a",                                                # la marca de una ficha unida a otra
    "quitada_el",                                             # la marca de una ficha guardada aparte (borrada de Personas)
})
_PORTAL_TIPOS_DE_ENLACE = frozenset({"LinkToAnotherRecord", "Links", "ForeignKey"})


def portal_columnas_sin_clasificar(columnas_meta):
    """Títulos de columnas reales (la lista de `/meta/tables/<id>`) que no están en ningún cubo. Las de
    infraestructura (`system`) y las de enlace (por su tipo, no por su nombre) no cuentan."""
    conocidas = set(PORTAL_COLUMNAS_VISIBLES) | set(_base.PORTAL_COLUMNAS_VETADAS) | PORTAL_COLUMNAS_NO_DATO
    sin = set()
    for c in columnas_meta or []:
        if not isinstance(c, dict) or c.get("title") in conocidas:
            continue
        if c.get("system") is True or c.get("uidt") in _PORTAL_TIPOS_DE_ENLACE:
            continue
        sin.add(str(c.get("title")))
    return sorted(sin)


_portal_sin_clasificar_cache = {"valor": None, "ts": 0.0}
PORTAL_SIN_CLASIFICAR_SEG = 300


def portal_sin_clasificar_ahora():
    """Lista de columnas sin clasificar, o `None` si no se pudo comprobar. Nunca levanta: es un aviso,
    no una condición para ver la lista. Se relee cada `PORTAL_SIN_CLASIFICAR_SEG`."""
    c = _portal_sin_clasificar_cache
    if c["valor"] is not None and time.time() - c["ts"] < PORTAL_SIN_CLASIFICAR_SEG:
        return c["valor"]
    try:
        meta = _base._opciones_select(_base.T_PERSONAS, None, columnas=_base.TODAS_LAS_COLUMNAS)
    except Exception as e:  # noqa: BLE001
        print(f"[portal-personas] no se pudo comprobar las columnas: {type(e).__name__}")
        return None
    c["valor"], c["ts"] = portal_columnas_sin_clasificar(meta), time.time()
    return c["valor"]


class PortalNoCargo(Exception):
    """La lista de personas no se pudo leer completa. El texto es el que se le dice a la persona."""


def _portal_leer_todas():
    """TODAS las personas, con los campos de la lista, página por página hasta la última. Las unidas a otra y las guardadas aparte no salen.

    🔴 Ni una consulta se queda en la primera página (NocoDB pagina de 200 en 200). Y no se fía de
    `nc_list_all`, que da por última una respuesta sin `pageInfo`: acá una respuesta sin saber si hay más
    páginas, o que dice un total que no coincide con lo recibido, es un error y no una lista corta."""
    filas, desde, total = [], 0, None
    while True:
        pag = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records",
                 query={"fields": ",".join(PORTAL_LISTA_CAMPOS + ("unida_a", "quitada_el")), "limit": 200, "offset": desde})
        info = pag.get("pageInfo") if isinstance(pag, dict) else None
        if not isinstance(info, dict) or not isinstance(info.get("isLastPage"), bool):
            raise PortalNoCargo("NocoDB no dijo si había más páginas de personas.")
        trozo = [x for x in pag.get("list", []) if isinstance(x, dict)]
        filas.extend(trozo)
        if info["isLastPage"]:
            total = info.get("totalRows")
            break
        if not trozo:
            raise PortalNoCargo("NocoDB dijo que había más personas y no mandó ninguna.")
        desde += len(trozo)
    if isinstance(total, int) and not isinstance(total, bool) and total != len(filas):
        raise PortalNoCargo(f"La lista de personas llegó incompleta ({len(filas)} de {total}).")
    return [f for f in filas if not ficha_fuera(f)]


def _portal_leer_todas_estricta():
    """Lo mismo que `_portal_leer_todas` (los mismos campos, las mismas fichas fuera), pero con el lector ESTRICTO de Personas
    (`_anotaciones_leer_tabla`): da TODAS las personas o levanta `_NoSeSupo`. No tiene el `while True` de `_portal_leer_todas`: el tope de
    páginas es `ANOTACIONES_PAGINAS_MAX`. La usa solo la ruta de Mercadeo (`personas_lectura.pagina`), por `portal_personas_pagina(leer=...)`."""
    filas = _anotaciones_leer_tabla(_base.T_PERSONAS, ",".join(PORTAL_LISTA_CAMPOS + ("unida_a", "quitada_el")))
    return [f for f in filas if not ficha_fuera(f)]


# ---------- «Última visita» y «Visitas»: se CALCULAN al leer, de `asistencias` + lo viejo guardado ----------
# `personas.Visitas` y `personas.Ultima_visita` son columnas viejas que nadie actualiza (ni la App ni Natalia las escriben: `git grep`, 13-oct-2026);
# lo real está en `asistencias` (un check-in por fila). LA REGLA, en dos líneas:
#   · última visita = la más reciente entre el día (hora de Santo Domingo) del check-in más nuevo de la ficha y la `Ultima_visita` vieja;
#   · visitas, CON fecha vieja legible = las `Visitas` viejas + los check-ins de un día POSTERIOR a esa fecha (lo de ese día o anterior se supone ya contado en el número viejo);
#     SIN fecha vieja legible = el MAYOR entre las `Visitas` viejas y la cantidad de check-ins, nunca la suma (sin fecha no se sabe qué check-ins ya estaban en el número viejo):
#     no cuenta doble, pero CUENTA DE MENOS si había visitas viejas y check-ins distintos. Un `Visitas` viejo que no es número cuenta como 0.
#     CON fecha vieja SUPONE que el `Visitas` viejo contaba hasta esa fecha (sin comprobar): si ya incluía un check-in posterior a ella, ese se cuenta dos veces (cuenta de MÁS).
# Lo que NO se comprobó: que `Visitas` vieja cuente exactamente hasta su `Ultima_visita` (lo mide la sala con un guion de solo lectura contra producción).
# NO se escribe nada en la base: ni en `personas` ni en `asistencias`. Un check-in cuya fecha no se lee, o cuya `persona_id` no es un número, no cuenta.
# Si `asistencias` no se puede leer, las filas se quedan con lo viejo y la respuesta lo dice (`actividad_vieja`): nunca se inventa una fecha.
_RE_CHECKIN = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?)?", re.ASCII)


def _dia_de_checkin(v):
    """El día `AAAA-MM-DD`, en hora de Santo Domingo, de un `checkin_at` (lo guarda la App en UTC con zona; NocoDB lo devuelve con `T` o con espacio).
    Sin zona se toma como UTC; sin hora, el día tal cual. `None` si no es una fecha que exista."""
    if not isinstance(v, str):
        return None
    m = _RE_CHECKIN.fullmatch(v.strip())
    if not m:
        return None
    a, mes, d, hh, mm, ss, zona = m.groups()
    try:
        if hh is None:
            return date(int(a), int(mes), int(d)).isoformat()
        if zona in (None, "Z"):
            tz = timezone.utc
        else:
            limpio = zona[1:].replace(":", "")
            horas, minutos = int(limpio[:2]), int(limpio[2:4] or 0)
            tz = timezone((1 if zona[0] == "+" else -1) * timedelta(hours=horas, minutes=minutos))
        momento = _fecha_hora(int(a), int(mes), int(d), int(hh), int(mm), int(ss or 0), tzinfo=tz)
        return momento.astimezone(_base.TZ).date().isoformat()
    except (ValueError, OverflowError):
        return None


def _portal_leer_asistencias(persona_id=None):
    """LECTOR LAXO de producción: los check-ins (`persona_id`, `checkin_at`) de TODAS las fichas, o solo de una, página por página hasta la última.
    Estricta como `_portal_leer_todas` (una respuesta sin saber si hay más páginas, o con un total que no coincide, levanta), PERO SIN TOPE DE PÁGINAS:
    con un `isLastPage` que nunca llega, no termina. La usan la lista de producción (`portal_personas_con_actividad()` sin `leer_asistencias`) y la
    ficha abierta. La ruta de Mercadeo (`personas_lectura.pagina`) NO la usa: lee con `_portal_leer_asistencias_estricta`."""
    filas, desde = [], 0
    while True:
        q = {"fields": "persona_id,checkin_at", "limit": 200, "offset": desde}
        if persona_id is not None:
            q["where"] = f"(persona_id,eq,{int(persona_id)})"
        pag = _base.nc("GET", f"/api/v2/tables/{_base.T_ASISTENCIAS}/records", query=q)
        info = pag.get("pageInfo") if isinstance(pag, dict) else None
        if not isinstance(info, dict) or not isinstance(info.get("isLastPage"), bool):
            raise PortalNoCargo("NocoDB no dijo si había más páginas de asistencias.")
        trozo = [x for x in pag.get("list", []) if isinstance(x, dict)]
        filas.extend(trozo)
        if info["isLastPage"]:
            total = info.get("totalRows")
            if isinstance(total, int) and not isinstance(total, bool) and total != len(filas):
                raise PortalNoCargo(f"La lista de asistencias llegó incompleta ({len(filas)} de {total}).")
            return filas
        if not trozo:
            raise PortalNoCargo("NocoDB dijo que había más asistencias y no mandó ninguna.")
        desde += len(trozo)


# Mismo número que `ANOTACIONES_PAGINAS_MAX` (el estricto de fichas, más abajo en este archivo); `test_personas_lectura` exige que sean iguales.
ASISTENCIAS_PAGINAS_MAX = 500


def _portal_leer_asistencias_estricta():
    """LECTOR ESTRICTO de asistencias (el que usa la ruta de Mercadeo, `personas_lectura.pagina`): TODOS los check-ins de todas las fichas, página por
    página hasta la última, o levanta `PortalNoCargo`. Levanta ante: la respuesta no es un objeto con lista (`list`) y `pageInfo.isLastPage` booleano;
    un renglón de la lista que no es objeto; `totalRows` que falta, no es un entero (texto, None, booleano, decimal) o cambia entre páginas; el total de
    la última página que no cuadra con lo recibido; una página intermedia vacía; o `isLastPage` que no llega dentro de `ASISTENCIAS_PAGINAS_MAX` páginas
    (no hay bucle sin fin). Un error de NocoDB no se traga: sube a quien llama. Solo `GET`. Si no levanta, devuelve lo mismo que el laxo sin fichas."""
    filas, desde, total = [], 0, None
    for _ in range(ASISTENCIAS_PAGINAS_MAX):
        pag = _base.nc("GET", f"/api/v2/tables/{_base.T_ASISTENCIAS}/records",
                   query={"fields": "persona_id,checkin_at", "limit": 200, "offset": desde})
        info = pag.get("pageInfo") if isinstance(pag, dict) else None
        trozo = pag.get("list") if isinstance(pag, dict) else None
        if not isinstance(trozo, list) or not isinstance(info, dict) or not isinstance(info.get("isLastPage"), bool):
            raise PortalNoCargo("NocoDB no dijo si había más páginas de asistencias.")
        if not all(isinstance(x, dict) for x in trozo):
            raise PortalNoCargo("NocoDB mandó una asistencia que no es una fila.")
        visto = info.get("totalRows")
        if isinstance(visto, bool) or not isinstance(visto, int):
            raise PortalNoCargo("NocoDB no dijo cuántas asistencias había.")
        if total is not None and visto != total:
            raise PortalNoCargo("El total de asistencias cambió mientras se leía.")
        total = visto
        filas.extend(trozo)
        if info["isLastPage"]:
            if total != len(filas):
                raise PortalNoCargo(f"La lista de asistencias llegó incompleta ({len(filas)} de {total}).")
            return filas
        if not trozo:
            raise PortalNoCargo("NocoDB dijo que había más asistencias y no mandó ninguna.")
        desde += len(trozo)
    raise PortalNoCargo("La lista de asistencias no terminó dentro del tope de páginas.")


def _portal_dias_de_visita(asistencias):
    """`{Id de la ficha: [días AAAA-MM-DD de sus check-ins]}` de las filas de `asistencias`. Lo que no se lee (sin ficha numérica, sin fecha) no entra."""
    dias = {}
    for a in asistencias:
        pid = a.get("persona_id")
        if isinstance(pid, str) and pid.strip().isdigit():
            pid = int(pid.strip())
        if isinstance(pid, bool) or not isinstance(pid, int):
            continue
        dia = _dia_de_checkin(a.get("checkin_at"))
        if dia:
            dias.setdefault(pid, []).append(dia)
    return dias


def _portal_actividad_de(fila, dias):
    """`(Visitas, Ultima_visita)` de una ficha: lo viejo guardado en `fila` + los check-ins `dias` (la regla de arriba). Sin check-ins, lo viejo tal cual."""
    if not dias:
        return fila.get("Visitas"), fila.get("Ultima_visita")
    viejo_dia = _leer_fecha(fila.get("Ultima_visita"))
    viejo_texto = str(fila.get("Ultima_visita")).strip()[:10] if viejo_dia is not None else None
    viejas = _leer_numero(fila.get("Visitas")) or 0
    if viejo_texto is None:
        ultima, n = max(dias), max(viejas, len(dias))              # sin fecha vieja: el mayor, nunca la suma
    else:
        ultima, n = max(max(dias), viejo_texto), viejas + len([d for d in dias if d > viejo_texto])
    return (int(n) if n == int(n) else n), ultima


def _portal_con_actividad(fila, dias_de_la_ficha):
    """Una copia de la fila de `personas` con `Visitas` y `Ultima_visita` calculadas (la fila que viene de la base no se toca)."""
    visitas, ultima = _portal_actividad_de(fila, dias_de_la_ficha)
    return dict(fila, Visitas=visitas, Ultima_visita=ultima)


def _portal_con_actividad_de_una(fila):
    """`(fila con la actividad calculada, actividad_vieja)` para UNA ficha (la abierta). Si `asistencias` no se pudo leer: la fila tal cual y `True`."""
    try:
        dias = _portal_dias_de_visita(_portal_leer_asistencias(fila.get("Id"))).get(fila.get("Id"), [])
    except Exception as e:  # noqa: BLE001 — la ficha se ve igual, con lo viejo y avisando
        print(f"[portal-personas] no se pudo leer la actividad de la ficha ({type(e).__name__})")
        return fila, True
    return _portal_con_actividad(fila, dias), False


# ---------- ordenar la lista del portal por una columna ----------
# Cada columna que se puede ordenar tiene UN lector: recibe lo que NocoDB guardó en la celda y devuelve una clave
# comparable, o `None` si no hay nada que ordenar ahí (vacío) o si la celda tiene una forma que el lector no sabe leer.
# Ese `None` va al final de la lista en los dos sentidos: una forma rara nunca se ordena "a ojo". Todas las claves de
# una columna son del mismo tipo (texto, número o fecha), así que nunca se comparan peras con manzanas.
_RE_NUMERO = re.compile(r"-?\d+(\.\d+)?", re.ASCII)
_RE_FECHA = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", re.DOTALL | re.ASCII)
_RE_CUMPLE = re.compile(r"(\d{2})/(\d{2})", re.ASCII)        # DD/MM: la única forma que escribe la App (`campos_persona`)


def _leer_texto(v):
    """Un texto sin mayúsculas ni tildes (como se ordena el nombre). Vacío o solo espacios: sin valor. Algo que no es
    texto: sin forma que leer."""
    if not isinstance(v, str):
        return None
    return normalizar(v) or None


def _leer_nombre(v):
    """El nombre se lee como siempre se leyó: `str()` de lo que haya, sin espacios en los bordes."""
    texto = str(v or "").strip()
    return normalizar(texto) if texto else None


def _leer_numero(v):
    """Un número: un entero o decimal de verdad, o un texto que sea exactamente un número. Nada más (un `True`, un
    `NaN`, «12 visitas» o una lista no se leen)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        t = v.strip()
        if not _RE_NUMERO.fullmatch(t):
            return None
        v = t
    elif not isinstance(v, (int, float)):
        return None
    try:
        n = float(v)
    except (OverflowError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _leer_credito(v):
    """El crédito es un número; pero la pantalla muestra «—» cuando es cero (`personasDinero`), así que cero cuenta como
    sin valor: no se ordena una columna donde lo que se ve es una raya."""
    n = _leer_numero(v)
    return None if n is None or round(n, 2) == 0 else n


def _leer_fecha(v):
    """Una fecha `AAAA-MM-DD` (NocoDB tipo Date; si trae hora después, se ignora). Una fecha que no existe no se lee."""
    if not isinstance(v, str):
        return None
    m = _RE_FECHA.fullmatch(v.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).toordinal()
    except ValueError:
        return None


def _leer_cumple(v):
    """Un cumpleaños, ordenado por (mes, día): de enero a diciembre. Dos formas: `DD/MM` (la que escribe la App) y la fecha
    completa `AAAA-MM-DD` (se ignora el año; tiene que ser una fecha que exista). Un día que ese mes no tiene no se lee
    (el 29/02 sí existe en `DD/MM`). Medido por la sala el 8-oct-2026 en producción: 96 `DD/MM`, 4 `AAAA-MM-DD`, 656 vacíos."""
    if not isinstance(v, str):
        return None
    t = v.strip()
    if len(t) == 10 and _RE_FECHA.fullmatch(t):
        try:
            d = date(int(t[:4]), int(t[5:7]), int(t[8:]))
        except ValueError:
            return None
        return (d.month, d.day)
    m = _RE_CUMPLE.fullmatch(t)
    if not m:
        return None
    dia, mes = int(m.group(1)), int(m.group(2))
    try:
        date(2000, mes, dia)             # 2000 fue bisiesto: el 29/02 existe
    except ValueError:
        return None
    return (mes, dia)


# col (lo que viaja en `?col=`) -> (la columna de `personas` de donde sale, el lector). Es LA lista de lo ordenable:
# el servidor rechaza cualquier otra cosa y la pantalla trae sus encabezados de `public/index.html` (una prueba exige que
# sean los mismos).
PORTAL_ORDENABLES = {
    "nombre": ("nombre", _leer_nombre),
    "cumple": ("Cumpleanos", _leer_cumple),
    "visitas": ("Visitas", _leer_numero),
    "ultima_visita": ("Ultima_visita", _leer_fecha),
    "credito": ("credito", _leer_credito),
    "correo": ("email", _leer_texto),
}
PORTAL_ORDEN_POR_OMISION = "nombre"


def _portal_preparar(fila):
    """Una fila de la lista lista para buscar y ordenar: lo que se muestra + lo que se compara."""
    publica = {k: fila.get(k) for k in PORTAL_LISTA_CAMPOS}
    nombre = str(fila.get("nombre") or "").strip()
    ig = normalizar(fila.get("instagram")).lstrip("@")
    # El texto y los teléfonos de la búsqueda llevan las DOS casillas de cada clase: el segundo número y el segundo correo son
    # de esta persona igual que los primeros (parte 4). Los teléfonos van en una lista aparte, nunca pegados: dos números
    # distintos concatenados formarían un número que no existe.
    # `nombre_whatsapp` también se busca (igual que `buscar_personas`, el buscador del check-in): una ficha que solo tiene ese nombre se halla por él.
    texto = " ".join(x for x in (normalizar(nombre), normalizar(fila.get("nombre_whatsapp")), normalizar(fila.get("email")),
                                 normalizar(fila.get("email_2")), ig) if x)
    claves = {col: leer(fila.get(campo)) for col, (campo, leer) in PORTAL_ORDENABLES.items()}
    return {"publica": publica, "claves": claves, "texto": texto,
            "tels": [d for d in (re.sub(r"\D", "", str(fila.get("telefono") or "")),
                                 re.sub(r"\D", "", str(fila.get("telefono_2") or ""))) if d]}


_portal_cache = {"filas": None, "ts": 0.0, "vieja": False}
_portal_lock = threading.Lock()
# La memoria de la RUTA de Mercadeo (`personas_lectura.pagina`, con `_portal_leer_todas_estricta`). Aparte de la de arriba: nada que
# leyó el lector laxo de la lista de producción puede llegar a esa ruta. Se invalida junto con la de producción.
_portal_cache_estricta = {"filas": None, "ts": 0.0, "vieja": False}
_portal_lock_estricta = threading.Lock()


def portal_personas_con_actividad(leer=None, leer_asistencias=None):
    """`(filas, vieja)`: la lista entera, preparada, Y la bandera de ESA misma lista, tomadas juntas bajo el mismo candado (una sola foto de la memoria).
    `Visitas` y `Ultima_visita` de cada fila salen calculadas (ver «Última visita» arriba): `asistencias` se lee UNA vez por cada vez que se arma la lista (no una por ficha).
    Si no se pudo leer, las filas llevan lo viejo y `vieja` es `True`. Quien necesite las filas y la bandera (la lista de Personas, Leads) usa ESTA función: pedir las dos
    cosas por separado deja un hueco entre medias en el que otro pedido puede rearmar la memoria y dar filas de una lista con la bandera de otra.
    `leer` y `leer_asistencias` van JUNTOS o no van (si uno falta con el otro, `ValueError`: así no se mezcla la memoria estricta con el lector laxo).
    Sin los dos, es la lista de producción: `_portal_leer_todas` y `_portal_leer_asistencias` (laxo) con la memoria de producción (`_portal_cache`); si las
    asistencias no se pueden leer, las filas salen con lo viejo y `vieja` es `True`. Con los dos, la memoria es `_portal_cache_estricta`, las asistencias
    las lee `leer_asistencias` (la ruta de Mercadeo pasa `_portal_leer_asistencias_estricta`) y NO se traga el error: si `leer` o `leer_asistencias` levantan,
    no se guarda nada y la excepción sube a quien llama."""
    if (leer is None) != (leer_asistencias is None):
        raise ValueError("leer y leer_asistencias van juntos: o los dos, o ninguno")
    if leer is None:
        memoria, candado, leer = _portal_cache, _portal_lock, _portal_leer_todas
    else:
        memoria, candado = _portal_cache_estricta, _portal_lock_estricta
    with candado:
        espera = PORTAL_ACTIVIDAD_REINTENTO_SEG if memoria["vieja"] else PORTAL_CACHE_SEG
        if memoria["filas"] is not None and time.time() - memoria["ts"] < espera:
            return memoria["filas"], memoria["vieja"]
        filas = leer()
        if leer_asistencias is not None:
            dias, vieja = _portal_dias_de_visita(leer_asistencias()), False      # estricto: un error sube, no se guarda nada
        else:
            try:
                dias = _portal_dias_de_visita(_portal_leer_asistencias())
                vieja = False
            except Exception as e:  # noqa: BLE001 — la lista se ve igual, con lo viejo y avisando
                print(f"[portal-personas] no se pudo leer la actividad ({type(e).__name__})")
                dias, vieja = {}, True
        preparadas = [_portal_preparar(_portal_con_actividad(f, dias.get(f.get("Id"), []))) for f in filas]
        memoria["filas"], memoria["ts"], memoria["vieja"] = preparadas, time.time(), vieja
        return preparadas, vieja


def portal_personas_todas():
    """La lista entera, preparada (las filas de `portal_personas_con_actividad()`). Si necesitas también la bandera de `actividad_vieja`, pídelas JUNTAS con esa función."""
    return portal_personas_con_actividad()[0]


def portal_actividad_vieja():
    """¿La lista en memoria se armó SIN poder leer `asistencias` (o sea, con `Visitas` y `Ultima_visita` viejas)?"""
    with _portal_lock:
        return _portal_cache["vieja"]


def invalidate_portal_personas():
    with _portal_lock:
        _portal_cache["filas"] = None
    with _portal_lock_estricta:
        _portal_cache_estricta["filas"] = None


def _portal_es_el_id(p, digitos):
    """¿Este número es el `Id` (el número de ficha) de esta persona? Igualdad EXACTA de valor: «146» es la ficha 146, no la 14
    ni la 1460; con ceros a la izquierda («0146») también vale, porque es el mismo número."""
    idp = p["publica"].get("Id")
    return bool(digitos) and bool(re.fullmatch(r"\d+", digitos)) and isinstance(idp, int) and int(digitos) == idp


def _portal_coincide(p, tokens, solo_digitos):
    """¿Esta persona coincide? Sin mayúsculas ni tildes. El teléfono se compara solo en dígitos: con o sin
    guiones, espacios, paréntesis o `+`. Cada palabra tiene que estar en el nombre, los correos o el Instagram
    (o ser parte de alguno de sus teléfonos, o ser el número de su ficha, `_portal_es_el_id`); y un número entero
    escrito de corrido también vale (como parte de un teléfono o como número de ficha)."""
    if solo_digitos and (any(solo_digitos in t for t in p["tels"]) or _portal_es_el_id(p, solo_digitos)):
        return True
    for t in tokens:
        sin_arroba = t.lstrip("@")
        if t in p["texto"] or (sin_arroba and sin_arroba in p["texto"]):
            continue
        d = re.sub(r"[\s\-().+]", "", t)
        if d.isdigit() and (any(d in tel for tel in p["tels"]) or _portal_es_el_id(p, d)):
            continue
        return False
    return True


def _portal_coincidentes(q, todas):
    """Las personas PREPARADAS (`publica`, `claves`, `texto`, `tels`) de `todas` (la lista en memoria, que quien llama leyó UNA vez)
    que coinciden con la búsqueda, en el orden en que están; sin búsqueda, todas, en una lista nueva. Es la única búsqueda de la
    lista: la usan la página y las coincidencias."""
    consulta = normalizar(q)[:PORTAL_BUSQUEDA_MAX]
    if not consulta:
        return list(todas)
    tokens = consulta.split()
    solo_digitos = re.sub(r"\D", "", consulta) if re.fullmatch(r"[\d\s\-().+]+", consulta) else ""
    return [p for p in todas if _portal_coincide(p, tokens, solo_digitos)]


def portal_personas_coincidencias(q):
    """Las filas PÚBLICAS de las personas que coinciden con la búsqueda, sin ordenar ni recortar (el orden es el de la lista
    en memoria). Son los MISMOS objetos que guarda la memoria de la lista y que usa el portal: quien las reciba solo las lee."""
    return [p["publica"] for p in _portal_coincidentes(q, portal_personas_todas())]


def portal_personas_pagina(q, orden, desde, limite, ver=None, col=PORTAL_ORDEN_POR_OMISION, solo=None, leer=None, leer_asistencias=None):
    """Una página de la lista: la búsqueda y el orden se aplican a TODAS las personas, y después se recorta.
    `solo` (opcional): una función que recibe la fila pública de cada persona que coincide con la búsqueda y dice si se queda;
    se aplica a todas, después de buscar y antes de ordenar y recortar (así `coincidencias` y `hay_mas` cuentan las que se
    quedan). Con `solo=None` es la lista de siempre. `total` es el de toda la lista, antes de buscar y de `solo`.
    Se ordena por la columna `col` (una de `PORTAL_ORDENABLES`; otra cosa levanta `ValueError`, nunca se ignora callada):
    texto sin tildes ni mayúsculas, números como números, fechas como fechas. Las personas sin valor en esa columna, o con
    una forma que no se sabe leer, van al final en los dos sentidos, por `Id`. El empate se resuelve por `Id`.
    `leer` y `leer_asistencias` (opcionales, de a dos: ver `portal_personas_con_actividad`). Sin ellos, es la lista de producción, con el lector
    laxo de asistencias: si las asistencias no se pueden leer, da la lista COMPLETA con lo viejo y `vieja` en `True`. La ruta de Mercadeo pasa
    `_portal_leer_todas_estricta` y `_portal_leer_asistencias_estricta`: entonces una lectura rota de la LISTA o de las ASISTENCIAS levanta (nunca una lista
    cortada, ni una lista con la actividad vieja pasada por completa)."""
    if col not in PORTAL_ORDENABLES:
        raise ValueError("columna de orden desconocida")
    if (leer is None) != (leer_asistencias is None):
        raise ValueError("leer y leer_asistencias van juntos: o los dos, o ninguno")
    todas, vieja = portal_personas_con_actividad() if leer is None else portal_personas_con_actividad(leer, leer_asistencias)      # UNA sola foto de la memoria: `total`, las coincidencias y la bandera salen de la misma lista
    hallan = _portal_coincidentes(q, todas)
    if solo is not None:
        hallan = [p for p in hallan if solo(p["publica"])]
    con = sorted((p for p in hallan if p["claves"][col] is not None), key=lambda p: (p["claves"][col], p["publica"]["Id"] or 0),
                 reverse=(orden == "desc"))
    sin = sorted((p for p in hallan if p["claves"][col] is None), key=lambda p: p["publica"]["Id"] or 0)
    ordenadas = con + sin
    trozo = ordenadas[desde:desde + limite]
    salida = {"ok": True, "total": len(todas), "coincidencias": len(ordenadas), "desde": desde,
              "orden": orden, "col": col, "hay_mas": desde + len(trozo) < len(ordenadas),
              "filas": [p["publica"] for p in trozo],
              "columnas_sin_clasificar": portal_sin_clasificar_ahora() if desde == 0 else None}
    if vieja:
        salida["actividad_vieja"] = True      # solo cuando pasa: `Visitas` y `Ultima_visita` de esta lista son las viejas guardadas (no se pudo leer `asistencias`)
    if ver is not None:
        # Dónde le toca a esa persona con esta búsqueda y este orden (`None` = no coincide): para mostrar la que
        # acaba de guardarse o crearse donde está, o decir que ya no coincide.
        posiciones = [p["publica"]["Id"] for p in ordenadas]
        salida["ver"] = {"Id": ver, "posicion": posiciones.index(ver) if ver in posiciones else None}
    return salida


def _portal_edicion(formas_fuera, base_de):
    """El bloque `edicion` de la respuesta de una ficha: qué campos se escriben, con qué forma, y lo que decían al abrir."""
    formas, fuera = formas_fuera
    return {"disponible": True, "campos": formas, "base": {c: base_de(c) for c in formas},
            "no_disponibles": fuera}


def _portal_ficha_de_fila(fila, edicion=True):
    """La ficha armada con una fila ya leída: grupos de la maqueta, y, si se pide, qué se puede editar de ella.
    Cada campo editable lleva su `forma` (la que NocoDB dice de la columna real). Nunca levanta por la edición: si no
    se pudo preparar, la ficha se ve igual y `edicion` dice por qué no se edita."""
    fila, actividad_vieja = _portal_con_actividad_de_una(fila)      # `Visitas` y `Ultima_visita` calculadas (solo en lo que se enseña)
    ed = None
    if edicion:
        try:
            ed = _portal_edicion(formas_de_ficha(PORTAL_EDITABLES, multiples=True),
                                 lambda c: _ficha_a_texto(fila.get(c)))
        except _base.SoloLectura:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[portal-personas] edición no disponible ({type(e).__name__})")
            ed = {"disponible": False, "error": "No se pudo preparar la edición (NocoDB no contestó). "
                                                "La ficha se ve, pero por ahora no se edita."}
    formas = (ed or {}).get("campos") or {}
    grupos = [{"titulo": titulo,
               "campos": [dict({"llave": k, "etiqueta": etq, "tipo": tipo, "valor": fila.get(k)},
                               **({"forma": formas[k]} if k in formas else {}))
                          for k, etq, tipo in cs]}
              for titulo, cs in PORTAL_FICHA_GRUPOS]
    salida = {"ok": True, "id": fila["Id"], "nombre": str(fila.get("nombre") or "").strip(), "grupos": grupos}
    if actividad_vieja:
        salida["actividad_vieja"] = True
    if ed is not None:
        salida["edicion"] = ed
    mercadeo = anotaciones_de_la_ficha(fila["Id"])      # permiso, baja y por dónde entró: SOLO PARA VER; sin la variable es `None` y no hay clave
    if mercadeo is not None:
        salida["mercadeo"] = mercadeo
    return salida


def _portal_leer_fila(persona_id):
    """La fila de `personas` por su `Id`, con las columnas visibles y solo ellas; `ErrorDeNocodb(404)` si no existe, está unida a otra o está guardada aparte."""
    fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(persona_id)}",
              query={"fields": ",".join(["Id"] + list(PORTAL_COLUMNAS_VISIBLES) + ["unida_a", "quitada_el"])})
    if not isinstance(fila, dict) or fila.get("Id") is None or ficha_fuera(fila):
        raise _base.ErrorDeNocodb(404, "persona sin fila")
    return fila


def portal_persona_ficha(persona_id):
    """La ficha de UNA persona, leída de su fila por `Id` (no por teléfono): tenga o no teléfono se abre.
    Solo salen las columnas visibles, en los grupos de la maqueta; lo demás se queda aquí."""
    salida = _portal_ficha_de_fila(_portal_leer_fila(persona_id))
    if _base.T_UNIONES_PERSONAS:
        try:
            salida["union"] = union_que_se_puede_deshacer(persona_id)      # lo que la pantalla necesita para ofrecer «Deshacer la unión»
        except _base.SoloLectura:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[portal-personas] no se pudo leer si la ficha tiene una unión ({type(e).__name__})")
    return salida


def portal_persona_nueva():
    """La ficha VACÍA de «+ Nueva persona»: solo los campos que se escriben, cada uno con su forma real."""
    formas, fuera = formas_de_ficha(PORTAL_EDITABLES, multiples=True)
    grupos = []
    for titulo, cs in PORTAL_FICHA_GRUPOS:
        campos = [{"llave": k, "etiqueta": etq, "tipo": tipo, "valor": None, "forma": formas[k]}
                  for k, etq, tipo in cs if k in formas]
        if campos:
            grupos.append({"titulo": titulo, "campos": campos})
    return {"ok": True, "nueva": True, "id": 0, "nombre": "", "grupos": grupos,
            "edicion": {"disponible": True, "campos": formas, "base": {c: "" for c in formas},
                        "no_disponibles": fuera}}


def _portal_posicion(persona_id, q, orden, col=PORTAL_ORDEN_POR_OMISION):
    """Dónde le toca a esta persona en la lista con esta búsqueda y este orden: `{"Id", "posicion"}`, con `posicion`
    `None` si no coincide con la búsqueda. Sale de la misma lista y las mismas reglas que `portal_personas_pagina`."""
    return portal_personas_pagina(q, orden, 0, 1, ver=persona_id, col=col)["ver"]


def _portal_con_ficha_releida(datos, persona_id):
    """Agrega a una respuesta de «guardado» o «creada» la ficha RELEÍDA de la base. Si no se pudo releer, la respuesta
    sigue diciendo que SÍ se guardó (`ficha: None` y un aviso): lo escrito ya está en la base."""
    try:
        datos["ficha"] = _portal_ficha_de_fila(_portal_leer_fila(persona_id))
    except _base.SoloLectura:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[portal-personas] se escribió y no se pudo releer la ficha ({type(e).__name__})")
        datos["ficha"] = None
        datos["aviso"] = ("Se guardó, pero no se pudo volver a leer la ficha completa. Ábrela de nuevo para ver cómo quedó.")
    return datos


def editar_persona_portal(persona_id, cuerpo, quien, solo_contar=False):
    """Guarda cambios desde el portal: la misma puerta que la ficha del Aprendizaje (`_guardar_edicion_de_persona`),
    con la fila leída por `Id` y `PORTAL_EDITABLES`. Devuelve `(codigo, dict)`; si se guardó (o ya estaba así) trae la
    ficha releída y dónde le toca en la lista (`q`/`orden` del pedido)."""
    if not isinstance(cuerpo, dict):
        return 400, {"error": "pedido ilegible. " + FICHA_ERROR_SIN_ESCRIBIR}
    if cuerpo.get("id") != persona_id:
        return 400, {"error": "el número de la ficha no coincide con el de la dirección. " + FICHA_ERROR_SIN_ESCRIBIR}

    def filas(cols):
        try:
            fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(persona_id)}",
                      query={"fields": ",".join(["Id"] + list(dict.fromkeys(cols)))})
        except _base.ErrorDeNocodb as e:
            if e.status == 404:
                return []
            raise
        return [fila] if isinstance(fila, dict) and fila.get("Id") is not None else []

    codigo, datos = _guardar_edicion_de_persona(cuerpo, quien, PORTAL_EDITABLES, filas, "PORTAL-PERSONA-EDITADA", portal=True,
                                                solo_contar=solo_contar)
    if codigo == 200 and datos.get("estado") in ("guardado", "sin_cambios") and not solo_contar:
        _portal_con_ficha_releida(datos, persona_id)
        datos["en_lista"] = _portal_en_lista(persona_id, cuerpo)
    return codigo, datos


def _portal_en_lista(persona_id, cuerpo):
    """Dónde le toca en la lista que la persona tiene a la vista, o `None` si no se pudo calcular (no es un fallo del guardado)."""
    q, orden = cuerpo.get("q"), cuerpo.get("orden")
    col = cuerpo.get("col", PORTAL_ORDEN_POR_OMISION)       # un pedido sin `col` es del orden de siempre: por nombre
    if not isinstance(q, str) or orden not in ("asc", "desc") or not isinstance(col, str) or col not in PORTAL_ORDENABLES:
        return None
    try:
        return _portal_posicion(persona_id, q, orden, col)
    except _base.SoloLectura:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[portal-personas] no se pudo calcular dónde queda en la lista ({type(e).__name__})")
        return None


def crear_persona_portal(cuerpo, quien, solo_contar=False):
    """«+ Nueva persona». Devuelve `(codigo, dict)`. Mismas reglas de valores que al guardar (`_ficha_valor_para_nocodb`) y
    la MISMA comprobación de teléfono y correo repetido (la puerta, `recibir`, bajo `_FICHA_TELEFONO_LOCK`: dos «Crear» a la vez
    del mismo número no dejan dos fichas, dentro de este proceso). Exige al menos el nombre; sin teléfono se permite.
    La fila nace como las de `crear_persona` (nombre y lo que se escribió; nada más), con dos diferencias: el teléfono se
    valida con `_telefono_de_ficha` (de 8 a 15 dígitos) y se pueden llenar los campos de Perfil."""
    sin = "No se creó nada."
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("cambios"), dict):
        return 400, {"error": "pedido ilegible. " + sin}
    cambios = cuerpo["cambios"]
    fuera = sorted(str(c) for c in cambios if c not in PORTAL_EDITABLES)
    if fuera:
        return 400, {"error": "esos campos no se pueden escribir desde aquí: %s. %s" % (", ".join(fuera), sin),
                     "campos_rechazados": fuera}
    if any(not isinstance(v, str) for v in cambios.values()):
        return 400, {"error": "los valores van como texto. " + sin}
    try:
        formas, _ = formas_de_ficha(PORTAL_EDITABLES, multiples=True)
    except _base.SoloLectura:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"[portal-personas] crear: no se pudo leer las columnas ({type(e).__name__})")
        return 502, {"error": "No se pudo leer cómo es la tabla de personas. " + sin}
    nuevos = {}
    for c, texto in cambios.items():
        if c not in formas:
            return 400, {"error": "%s no se puede escribir ahora. %s" % (PORTAL_EDITABLES[c], sin),
                         "campos_rechazados": [c]}
        if _ficha_canon(formas[c], texto) is None:
            continue                                   # vacío al crear = no se manda (como `crear_persona`)
        try:
            nuevos[c] = _ficha_valor_para_nocodb(c, formas[c], texto, True)
        except ValueError as e:
            datos = {"error": "%s. %s" % (e, sin), "campo": c}
            if formas[c]["tipo"] in ("seleccion", "multiple"):
                datos["opciones"] = formas[c]["opciones"]
            return 422, datos
    if "nombre" not in nuevos:
        return 422, {"error": "Ponle al menos el nombre. " + sin, "campo": "nombre"}
    # 🔑 La ficha nace por la PUERTA (`recibir`): ella compara el teléfono y el correo con TODAS las fichas, bajo `_FICHA_TELEFONO_LOCK`
    # hasta el `POST`, y es quien escribe. Aquí solo se traduce su respuesta.
    dato = {"origen": "portal", "pantalla": True, "nombre": nuevos["nombre"],
            "otros": {c: v for c, v in nuevos.items() if c not in PUERTA_CLAVES_DE_PANTALLA}}
    for campo, clave in CASILLAS_DE_PANTALLA:
        if campo in nuevos:
            dato[clave] = nuevos[campo]
    res = recibir(dato, solo_contar=solo_contar)
    rechazo = respuesta_de_rechazo(res, sin)
    if rechazo:
        return rechazo
    if solo_contar:
        return calculo_de_escrituras(res["mandaria"], 201)
    if res["etapa"] == "escritura":
        if res["motivo"] == "base_rechazo":
            return 502, {"estado": "no_creada", "sin_confirmar": True,
                         "error": "La base de datos rechazó la ficha nueva, así que lo normal es que no se haya "
                                  "creado. Antes de repetirlo, búscala por su nombre."}
        if res["motivo"] == "sin_id":
            return 502, {"estado": "sin_confirmar", "sin_confirmar": True,
                         "error": "No se pudo confirmar si la persona se creó (la base no dijo su número). NO la crees "
                                  "otra vez todavía: búscala por su nombre."}
        return 502, {"estado": "sin_confirmar", "sin_confirmar": True,
                     "error": "No se pudo confirmar si la persona se creó. NO la crees otra vez todavía: "
                              "búscala por su nombre y, solo si no aparece, vuelve a intentarlo."}
    if puerta_sin_confirmar(res):
        # la ficha YA nació (la base dio su número) pero la puerta no pudo confirmar sus valores: no se dice «creada»
        return 502, {"estado": "sin_confirmar", "sin_confirmar": True, "id": res["ficha_id"],
                     "error": "La persona se creó (ficha n.º %s), pero no se pudo confirmar que sus datos quedaron bien guardados. NO la crees otra vez: "
                              "búscala por su nombre y revisa cómo quedó." % res["ficha_id"]}
    nuevo_id = res["ficha_id"]
    print(f"[PORTAL-PERSONA-CREADA] persona_id={nuevo_id} quien={quien} campos={','.join(sorted(nuevos))}")
    datos = {"ok": True, "estado": "creada", "id": nuevo_id}
    if res["avisos"]:
        datos["avisos"] = avisos_para_la_pantalla(res)
    _portal_con_ficha_releida(datos, nuevo_id)
    datos["en_lista"] = _portal_en_lista(nuevo_id, cuerpo)
    return 201, datos


# ---------- el espacio de aprendizaje: EDITAR LA FICHA DE UN CLIENTE ----------
#
# Pedido de Tiziano (5-oct-2026, con una captura de la ficha): «Dice muchas cosas que no tienen
# sentido para mi, y no es editable quiero poder editarlo». Maqueta aprobada: `disenos/registro-
# ficha-cliente/maqueta-v2-aprobada.html` («Si asi me gusta»). Sobre por dónde se guarda: «Creo
# que es mejor que la misma App edite sin pasar por Natalia que crees?» → la sala estuvo de
# acuerdo → «Si». **La App escribe DIRECTO en la fila del cliente en `personas`**, por `nc()` y
# por la puerta única de «esta escritura no entra dos veces»; Natalia no interviene.
#
# 🔑 UNA SOLA LISTA DE LO EDITABLE: `FICHA_EDITABLES`. El servidor la usa para aceptar o
# rechazar, y la pantalla no decide qué es editable: ofrece edición solo en las filas a las que
# ella le pasa una llave (las llamadas a `aprCampoFila` con tercer argumento en `app.js`, más el nombre del título) Y que
# el servidor declaró en `edicion.campos` al abrir la ficha. Esas 11 llaves son una segunda lista
# escrita a mano en la pantalla, pero solo puede RECORTAR a la del servidor, nunca ampliarla
# (Nombre en WhatsApp y Actividad no llevan llave). Lo no declarado NO se escribe, y no
# hay otra forma de pedirlo.
#
# 🔴 LO QUE NO ESTÁ EN LA LISTA, UNO POR UNO (`FICHA_NO_EDITABLES`): en la duda, queda sin
# editar y se le dijo a Tiziano para que decida.
FICHA_EDITABLES = {
    # Contacto
    # 🔴 «Nombre» y «Teléfono» se abren a edición el 7-oct-2026 (Tiziano, 6-oct: «no puedo editar la
    # informacion de contacto en el aprendizaje» → «3) Nombre y teléfono»). El teléfono es la llave con la que
    # el sistema reconoce a la persona: antes de escribirlo el servidor comprueba que no sea de OTRA ficha
    # (la puerta, `recibir`, con un candado hasta el `PATCH`: ver «UN SOLO CANDADO» en
    # `editar_ficha_cliente`, que dice la garantía y su frontera) y, si la ficha ya tenía uno, mide qué queda atado
    # al número viejo y pide confirmación (`medir_atado_al_telefono`). Esta App no mueve chats, reservas ni crédito.
    "nombre": "Nombre",
    "telefono": "Teléfono",
    "email": "Email",
    "instagram": "Instagram",
    "Cumpleanos": "Cumpleaños",
    # Perfil: lo que Natalia lee (y lo que no) para hablarle a este cliente.
    "Tono": "Tono",
    "Clave": "Clave",
    "Preferencias_operativas": "Preferencias operativas",
    "Comportamiento_reserva": "Comportamiento de reserva",
    "Resumen": "Resumen",
    "notas": "Notas",
    "Sensibilidad_precio": "Sensibilidad al precio",
    "Riesgo_noshow": "Riesgo de no-show",
}

FICHA_NO_EDITABLES = {
    "bsuid": "es la llave de identidad de quien escribe con @usuario (`RE_BSUID`); además no sale "
             "hacia el navegador (`_APRENDIZAJE_CAMPOS_NUNCA`).",
    "nombre_whatsapp": "lo pone el cliente desde su perfil de WhatsApp; esta app nunca lo escribe, y "
                       "Natalia lo escribe sola solo si la ficha no lo tiene ya (la sala lo leyó en "
                       "`natalia/agent/memoria.py:556-560` el 6-oct-2026). Tiziano decidió el 6-oct-2026 que "
                       "no se edita (se abrieron «Nombre» y «Teléfono», este no).",
    "instrumento": "es un MultiSelect (varias opciones) y la maqueta no lo trae: editarlo es otra "
                   "pantalla. Ya se edita en «Personas» (`editar_persona`).",
    "genero": "MultiSelect, no sale en la ficha.",
    "credito": "dinero: Natalia lo resta y la App lo devuelve; no se escribe a mano (`credito_de_cliente`).",
    "caras": "biométrico: solo lo escribe la cámara del check-in (`guardar_cara`).",
}

# 👥 LO QUE SE ESCRIBE DESDE EL PORTAL «PERSONAS» (parte 2): una sola lista, que decide. Es la de la ficha del Aprendizaje
# más `instrumento` y `genero` (MultiSelect: la maqueta del portal los trae editables) y más **las dos casillas nuevas de la
# parte 4, `telefono_2` y `email_2`**. «Nombre en WhatsApp», todo Actividad (visitas, crédito…), Consumo, Id en Maestro
# Clientes, `bsuid` y `caras` NO están: se ven y no se escriben. La pantalla no amplía esta lista: lo no declarado no se escribe
# aunque llegue en el pedido.
#
# 🔑 POR QUÉ LAS DOS CASILLAS NUEVAS ESTÁN AQUÍ Y NO EN `FICHA_EDITABLES`: la ficha del Aprendizaje se pinta con la respuesta de
# NATALIA (su grupo «Contacto» sale de ahí) y Natalia no manda `telefono_2`/`email_2` —viven en la tabla de la App—, así que
# ofrecerlas allí daría una ficha que CAMBIA DE FORMA según se pueda editar o no (con edición salen dos renglones más; sin
# edición, no), que es justo lo que prohíbe su guarda de aspecto (`tests/test_ficha_editar_aspecto.py`). En el portal «Personas»
# la ficha se lee ENTERA de la tabla (`PORTAL_FICHA_GRUPOS`), así que ahí se ven y se editan siempre, como sus principales.
PORTAL_EDITABLES = dict(FICHA_EDITABLES, telefono_2="Teléfono 2", email_2="Email 2",
                        instrumento="Instrumento", genero="Género",
                        Posible_proveedor="Posible proveedor", Precio_referencia="Precio de referencia")

# Cuántos caracteres admite un valor de texto (un `Resumen` largo cabe de sobra).
FICHA_TEXTO_MAX = 4000
_FICHA_TIPOS_TEXTO = ("SingleLineText", "LongText", "Email", "URL")
_FICHA_TIPOS_NUMERO = ("Number", "Decimal")
FICHA_ERROR_SIN_ESCRIBIR = "No se guardó nada."
FICHA_UNIDA = "Esta ficha se unió a otra y ya no se edita."
FICHA_QUITADA = "Esta ficha fue borrada de Personas y ya no se edita."
FICHA_ERROR_SIN_CONFIRMAR = (
    "No se pudo confirmar que el cambio quedó guardado: la base no contestó bien o lo que se leyó "
    "después no coincide con lo que escribiste. NO lo des por guardado: abre la ficha de nuevo y "
    "mira cómo quedó antes de repetirlo.")


def _forma_de_columna(campo, col, multiples):
    """La forma que tiene una columna REAL de NocoDB para esta pantalla, o `None` si no se
    sabe editar. Sale de lo que NocoDB dice (`uidt` y las opciones de la lista), no de lo que
    esta función creía: si mañana una columna cambia de tipo, cambia sola."""
    uidt = col.get("uidt")
    # Un teléfono es lo que NOCODB dice que es un teléfono (`PhoneNumber`), no lo que se llame el campo: así `telefono` y
    # `telefono_2` se tratan igual sin escribir una lista de nombres. Se acepta también texto simple en las casillas de
    # teléfono de la puerta (`CAMPOS_TELEFONO`: `telefono` es `PhoneNumber` en producción —medido el 7-oct-2026, `dt`
    # varchar—, pero si cambiara de tipo la pantalla sigue sabiendo escribirlas); cualquier otro tipo no se ofrece.
    if uidt == "PhoneNumber" or campo in CAMPOS_TELEFONO:
        return {"tipo": "telefono"} if uidt in ("PhoneNumber", "SingleLineText") else None
    if uidt == "MultiSelect" and multiples:
        # Varias opciones de una lista cerrada. NocoDB las guarda y las devuelve como texto separado por comas
        # (así las escribe también `campos_persona`, la del check-in).
        return {"tipo": "multiple", "opciones": _base._opciones_de_columna(col)}
    if uidt in _FICHA_TIPOS_TEXTO:
        return {"tipo": "texto"}
    if campo == "Cumpleanos":
        return None          # el cumpleaños es texto DD/MM (`campos_persona`); otra cosa, no se toca
    if uidt == "SingleSelect":
        return {"tipo": "seleccion", "opciones": _base._opciones_de_columna(col)}
    if uidt in _FICHA_TIPOS_NUMERO:
        return {"tipo": "numero"}
    if uidt == "Date":
        return {"tipo": "fecha"}
    return None


def formas_de_ficha(editables, multiples):
    """`({campo: forma}, {campo: motivo})` de los campos de `editables` (por omisión `FICHA_EDITABLES`), leídos de la
    descripción real de la tabla `personas`. Un campo cuya columna no existe o es de un tipo que
    esta pantalla no sabe editar NO se ofrece (cae del lado de no escribir)."""
    columnas = _base._opciones_select(_base.T_PERSONAS, None, columnas=list(editables))
    formas, fuera = {}, {}
    for campo in editables:
        col = columnas.get(campo)
        if col is None:
            fuera[campo] = "la columna no existe en NocoDB"
            continue
        forma = _forma_de_columna(campo, col, multiples)
        if forma is None:
            fuera[campo] = "tipo de columna que esta pantalla no sabe editar (%s)" % col.get("uidt")
        else:
            formas[campo] = forma
    return formas, fuera


def _ficha_a_texto(v):
    """El valor de una celda, como texto para la pantalla: vacío es `""`, un número entero
    no lleva `.0`."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Sí" if v else "No"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return ",".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def _ficha_canon(forma, v):
    """El valor en su forma COMPARABLE: `None` si está vacío. Dos valores que dicen lo mismo
    dan lo mismo (`" Baja "` y `"Baja"`; `12` y `"12.0"`)."""
    t = _ficha_a_texto(v).replace("\r\n", "\n").strip()
    if t == "":
        return None
    if forma["tipo"] == "telefono":
        # Dos formas de escribir el mismo número son el mismo valor (`809-555-0101` y `18095550101`); lo
        # que no es un teléfono se deja como llegó (se rechaza más abajo, no se adivina).
        return _telefono_de_ficha(t) or t
    if forma["tipo"] == "multiple":
        # Las mismas opciones en otro orden son el mismo valor.
        return ",".join(sorted({x.strip() for x in t.split(",") if x.strip()})) or None
    if forma["tipo"] == "numero":
        if not re.fullmatch(r"-?\d+(\.\d+)?", t):
            return t                  # «12,5» o «1,500» son ambiguos: no se adivinan (se rechazan)
        n = float(t)
        return str(int(n)) if n.is_integer() else repr(n)
    return t


def _ficha_valor_para_nocodb(campo, forma, texto, correo_estricto):
    """El texto que escribió la persona → el valor que se manda a NocoDB (`None` = vaciar).
    Levanta `ValueError` con la frase para la persona. `correo_estricto` (solo el portal «Personas»): el correo
    tiene que tener forma de correo; la ficha del Aprendizaje sigue como estaba."""
    etiqueta = PORTAL_EDITABLES[campo]
    c = _ficha_canon(forma, texto)
    if c is None:
        if campo == "nombre":
            raise ValueError("El nombre no puede quedar vacío")
        if campo == "telefono":
            raise ValueError("El teléfono no se puede dejar vacío desde aquí: es con lo que se reconoce a la persona")
        return None
    if forma["tipo"] == "telefono":
        d = _telefono_de_ficha(c)
        if d is None:
            raise ValueError("«%s» no es un teléfono válido: escribe solo números, con o sin +, espacios, "
                             "guiones o paréntesis, de %d a %d dígitos" % (c, _TEL_FICHA_MIN, _TEL_FICHA_MAX))
        return d
    if forma["tipo"] == "seleccion":
        if c not in forma["opciones"]:
            raise ValueError("«%s» no es una opción válida de %s" % (c, etiqueta))
        return c
    if forma["tipo"] == "multiple":
        elegidas = set(c.split(","))
        malas = sorted(x for x in elegidas if x not in forma["opciones"])
        if malas:
            raise ValueError("«%s» no es una opción válida de %s" % (malas[0], etiqueta))
        return ",".join(o for o in forma["opciones"] if o in elegidas)     # en el orden de la lista de NocoDB
    if forma["tipo"] == "numero":
        # Sin signo menos: los números que la ficha escribe son cantidades (hoy, el precio de referencia). `_ficha_canon` sí lee
        # un `-` para comparar lo que ya hay guardado, pero escribir un negativo no se acepta.
        if not re.fullmatch(r"\d+(\.\d+)?", c):
            raise ValueError("%s tiene que ser un número sin signo menos (con punto para los decimales)" % etiqueta)
        n = float(c)
        return int(n) if n.is_integer() else n
    if forma["tipo"] == "fecha":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", c):
            raise ValueError("%s tiene que ser una fecha AAAA-MM-DD" % etiqueta)
        try:
            date.fromisoformat(c)
        except ValueError:
            raise ValueError("%s no es una fecha que exista" % etiqueta)
        return c
    if len(c) > FICHA_TEXTO_MAX:
        raise ValueError("%s es demasiado largo (máximo %d caracteres)" % (etiqueta, FICHA_TEXTO_MAX))
    if correo_estricto and campo == "email" and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", c):
        raise ValueError("«%s» no parece un correo (falta el @ o el dominio)" % c)
    if campo == "Cumpleanos" and not re.fullmatch(r"\d{2}/\d{2}", c):
        raise ValueError("Cumpleaños inválido (formato DD/MM)")      # la misma regla de `campos_persona`
    return c


def _filas_de_identidad(identidad, campos):
    """Las filas de `personas` que son de ESTA identidad (teléfono o BSUID), con `Id` y `campos`.
    **Es el servidor quien decide qué fila es**: la identidad de la dirección, no un `Id` que
    mande la pantalla."""
    ident = str(identidad or "").strip()
    if es_bsuid(ident):
        donde = f"(bsuid,eq,{ident})"
    elif ident.isdigit():
        donde = f"(telefono,eq,{normalizar_telefono(ident)})"
    else:
        return []
    return _base.nc_list_all(_base.T_PERSONAS, {"where": donde, "fields": ",".join(["Id"] + list(campos))})


def _celda_es_el_numero(celda, nuevo):
    """¿Esta celda de `personas.telefono` es el número `nuevo` (ya normalizado, solo dígitos)? **La única forma de comparar un
    teléfono con una celda**: la usa la puerta (`recibir`): ¿lo tiene otra ficha?, ¿ya era el de esta ficha?
      · `nuevo` con forma de teléfono (`_telefono_de_ficha`: de 8 a 15 dígitos) → se compara por VALOR con lo que esa función saca
        de la celda; una celda con letras u otro texto que no es un teléfono no cuenta. Es lo que siempre hicieron el portal y la
        ficha del Aprendizaje, y sus entradas SIEMPRE tienen esa forma (`_ficha_valor_para_nocodb` rechaza lo demás).
      · `nuevo` SIN forma de teléfono (menos de 8 o más de 15 dígitos: solo lo escribe el check-in, que lo acepta como está) → se
        compara por sus DÍGITOS normalizados contra los dígitos de la celda, que es como el check-in los escribe
        (`campos_persona`). Así dos fichas no quedan con el mismo número tenga el largo que tenga, sin rechazar ninguno.
        Frontera: una celda con letras y dígitos cuenta por sus dígitos (cuenta de más, nunca de menos)."""
    if _telefono_de_ficha(nuevo) is not None:
        return _telefono_de_ficha(celda) == nuevo
    return normalizar_telefono(celda) == nuevo


def _contar_filas(tabla, donde, campo):
    """Cuántas filas de `tabla` cumplen `donde` (`pageInfo.totalRows`, que NocoDB trae siempre: medido en
    producción el 7-oct-2026 sobre `sesiones`, `conversaciones` y `personas`), o `None` si no se pudo medir."""
    try:
        r = _base.nc("GET", f"/api/v2/tables/{tabla}/records", query={"where": donde, "limit": 1, "fields": campo})
        n = (r.get("pageInfo") or {}).get("totalRows")
    except _base.SoloLectura:
        raise
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] no se pudo medir lo atado al teléfono ({type(e).__name__})")
        return None
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def medir_atado_al_telefono(viejo, fila):
    """Qué hay HOY atado al número viejo de ESTA ficha, medido en el momento. Es lo que la pantalla le dice
    a la persona antes de confirmar. Cada cifra es un entero o `None` ("no se pudo medir"):
      · `reservas`: filas de `sesiones` con `telefono_cliente` = el número (de ahí cuelgan el crédito y los
        comprobantes de cada reserva: `estado_credito`, `comprobantes_de_telefono`);
      · `mensajes`: filas de `conversaciones` con `telefono` = el número (`conversacion_mensajes`);
      · `credito`: el saldo de la columna `credito` de ESTA fila (se queda con la ficha; lo que se pierde es
        encontrarlo por el número viejo: `credito_de_cliente`);
      · `libro_en_natalia`: SIEMPRE `True` — el libro de movimientos vive en la base de Natalia y esta App no
        puede medir cuántos movimientos tiene atados al número viejo.
    Esta App no mueve nada de eso."""
    try:
        credito = round(float(fila.get("credito") or 0), 2)
    except (TypeError, ValueError):
        credito = None
    # El número de las conversaciones sale de la PUERTA ÚNICA de número (`numero_de_identidad`), como en el
    # resto de la App: para un teléfono en dígitos es él mismo; si el texto de la celda no es un teléfono
    # no hay a qué conversación atarlo y se dice «no se pudo medir».
    numero = numero_de_identidad(viejo)
    # 🔴 Una celda que no es un teléfono en dígitos (trae `)`, `,`, letras…) NO se mete en una consulta
    # `where`: saldría mal armada y daría un conteo equivocado. Ahí la respuesta es «no se pudo medir».
    consultable = bool(re.fullmatch(r"\d+", str(viejo)))
    return {"reservas": (_contar_filas(_base.T_SESIONES, f"(telefono_cliente,eq,{viejo})", "Id") if consultable else None),
            "mensajes": (_contar_filas(_base.T_CONVERSACIONES, f"(telefono,eq,{numero})", "id") if numero else None),
            "credito": credito, "libro_en_natalia": True}


def edicion_de_ficha(datos, identidad):
    """`datos["edicion"]`: qué se puede editar de ESTA ficha y con qué forma, o por qué no.
    NUNCA levanta: leer la ficha no puede romperse porque la edición no se pudo preparar; en ese
    caso la ficha se ve igual de hoy, sin edición, y lo dice."""
    def no(motivo, error=""):
        salida = {"disponible": False, "motivo": motivo}
        if error:
            salida["error"] = error
        return salida

    if not isinstance(datos, dict) or datos.get("ok") is False:
        return datos
    f = datos.get("ficha")
    if datos.get("duplicada") is True:
        datos["edicion"] = no("duplicada", "Este cliente tiene más de una ficha: no se edita ninguna "
                              "hasta que se resuelva fuera de esta pantalla.")
        return datos
    if datos.get("encontrada") is not True or not isinstance(f, dict):
        datos["edicion"] = no("sin_ficha", "Este cliente no tiene ficha: no hay nada que editar.")
        return datos
    if isinstance(f.get("Id"), bool) or not isinstance(f.get("Id"), int):
        datos["edicion"] = no("sin_ficha", "La ficha no trae su número: no se puede editar.")
        return datos
    try:
        formas, fuera = formas_de_ficha(FICHA_EDITABLES, False)    # la ficha del Aprendizaje: sin listas de opciones
        filas = _filas_de_identidad(identidad, formas)
    except Exception as e:                       # noqa: BLE001 — la lectura no se rompe por esto
        print(f"[warn] edición de ficha no disponible ({type(e).__name__})")
        datos["edicion"] = no("no_se_pudo_leer", "No se pudo preparar la edición (NocoDB no contestó). "
                              "La ficha se ve, pero por ahora no se edita.")
        return datos
    if len(filas) != 1:
        datos["edicion"] = no("duplicada" if len(filas) > 1 else "sin_ficha",
                              "No se encontró una única ficha para este cliente: no se edita.")
        return datos
    fila = filas[0]
    if fila.get("Id") != f.get("Id"):
        datos["edicion"] = no("otra_ficha", "La ficha que mandó Natalia no es la que tiene la App: "
                              "no se edita.")
        return datos
    datos["edicion"] = {
        "disponible": True,
        "id": fila["Id"],
        "campos": formas,
        "base": {c: _ficha_a_texto(fila.get(c)) for c in formas},
        "no_disponibles": fuera,
    }
    return datos


_FICHA_TELEFONO_LOCK = threading.Lock()
# Un candado por ficha, que toma cada escritura por su `Id` (la puerta al editar, la cámara y la unión al marcarla): entre leer si la ficha
# está unida y escribir en ella, la unión no puede marcarla. Va aparte del de teléfono para que guardar sin teléfono no espere a ese,
# y es por ficha para que editar una no espere a editar otra.
_FICHA_CANDADOS = {}
_FICHA_CANDADOS_LOCK = threading.Lock()


def _candado_de_ficha(ficha_id):
    with _FICHA_CANDADOS_LOCK:
        return _FICHA_CANDADOS.setdefault(int(ficha_id), threading.Lock())


def _cara_calculada(persona_id, vec):
    """La cuenta de la cara, SIN candado y SIN escribir: lee la ficha EN VIVO y aplica sus guardas (guardada aparte, unida). Devuelve
    `(ranuras, cuerpo)`: las ranuras que quedan y el cuerpo del PATCH de la columna de caras. Quien llama toma el candado de la ficha."""
    fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(persona_id)}", query={"fields": f"Id,unida_a,quitada_el,{_base.CARA_COLUMNA}"})
    if ficha_quitada(fila):
        raise _base.FichaQuitada(persona_id)
    if ficha_unida(fila):
        raise _base.FichaUnida(persona_id)
    ranuras = _base._caras_de_celda(fila.get(_base.CARA_COLUMNA)) + [tuple(vec)]
    ranuras = ranuras[-_base.CARA_RANURAS:]
    cuerpo = {"Id": persona_id, _base.CARA_COLUMNA: _base.CARA_SEPARADOR.join(_base._cara_a_base64(v) for v in ranuras)}
    return ranuras, cuerpo


def cara_calculada(persona_id, vec):
    """LO QUE `escribir_cara` ESCRIBIRÍA, sin escribir (lo usa el cálculo del modo que solo cuenta, `personas_cuenta`). Toma el mismo
    candado de la ficha y devuelve `(ranuras, cuerpo)`. No llama a ninguna escritura ni toca caché alguna."""
    with _candado_de_ficha(persona_id):
        return _cara_calculada(persona_id, vec)


def escribir_cara(persona_id, vec):
    """La ÚNICA escritura de la columna de caras que sale de este módulo: lee las ranuras de esa ficha EN VIVO, bajo su candado,
    y escribe UNA sola columna (`_base.CARA_COLUMNA`). Si la ficha está unida (`_base.FichaUnida`) o guardada aparte (`_base.FichaQuitada`),
    no escribe. Devuelve la lista de ranuras que quedan; la caché la actualiza el que llama (`guardar_cara`, en `server.py`), fuera
    de este candado, como siempre."""
    with _candado_de_ficha(persona_id):      # la unión marca una ficha bajo este candado: entre leer la marca y escribir la cara no puede marcarla
        ranuras, cuerpo = _cara_calculada(persona_id, vec)
        _base.nc("PATCH", f"/api/v2/tables/{_base.T_PERSONAS}/records", body=cuerpo)
    return ranuras


# El mismo valor en las dos casillas de una ficha. 🔑 SE VEAN O NO LAS DOS CASILLAS, la frase tiene que decir algo que quien la
# lee pueda hacer: el portal «Personas» y el ✎ del check-in enseñan las dos, así que se le manda a borrar una; la ficha del
# Aprendizaje solo enseña una (su «Contacto» sale de lo que manda Natalia), así que ahí se le dice DÓNDE está la otra.
MISMO_VALOR_SE_VEN_LAS_DOS = "Bórralo de una de las dos."
MISMO_VALOR_UNA_SOLA_A_LA_VISTA = ("Esta pantalla solo enseña una de las dos casillas: ábrela en «Personas», que sí las enseña "
                                   "las dos, y bórralo de la que sobre.")


def respuesta_de_rechazo(r, sin_escribir, que_hacer="Unir fichas se hace aparte, no desde aquí.", que_hacer_correo=None, si_no_se_pudo="",
                         mismo_valor=MISMO_VALOR_SE_VEN_LAS_DOS):
    """`None` si la puerta (`recibir`) NO rechazó la escritura de una pantalla; si la rechazó, `(codigo, dict)` listo para contestar y
    quien llama NO escribe. Lo que contesta, y es lo único que una pantalla dice de un rechazo:
      · `409 {motivo: "telefono_repetido" | "correo_repetido", de: {Id, nombre}, error}` — ese teléfono o correo ya es de OTRA ficha
        (en su casilla principal o en la secundaria: las dos cuentan);
      · `409 {motivo: "mismo_valor", error}` — el mismo teléfono (o el mismo correo) en las DOS casillas de ESTA ficha;
      · `409 {motivo: "unida" | "quitada", error}` — la ficha se unió a otra o la guardaron aparte (borrada): no se edita;
      · `502 {motivo: "no_se_pudo_comprobar", error}` — no se pudo leer las fichas para comprobarlo;
      · `400 {motivo: "forma_invalida", error}` — un valor que la puerta no sabe leer.
    `sin_escribir` es la frase final («No se guardó nada.» / «No se creó nada.»); `que_hacer` es lo último que se le dice a quien
    está delante cuando el teléfono es de otra (por omisión lo del portal; el check-in dice cómo registrar a la ficha que ya
    existe) y `que_hacer_correo` lo mismo para el correo (por omisión, `que_hacer`); `si_no_se_pudo` lo que se agrega cuando NO se
    pudo comprobar; `mismo_valor` es lo que se le dice a quien escribió en una casilla el valor de la hermana, y lo elige la
    pantalla porque depende de si ENSEÑA las dos casillas o una (`MISMO_VALOR_SE_VEN_LAS_DOS` / `..._UNA_SOLA_A_LA_VISTA`).
    **Es la única que arma estas frases** para el teléfono y el correo: el check-in, el portal y la ficha del Aprendizaje la comparten."""
    if r.get("motivo") == "no_se_pudo_comprobar" and "comprobaba" in r and not r["comprobaba"]:
        return 502, {"motivo": "no_se_pudo_comprobar", "error": ("No se pudo leer la ficha. " + sin_escribir + " " + si_no_se_pudo).strip()}
    if r.get("motivo") == "no_se_pudo_comprobar":
        que = r.get("comprobaba") or ["telefono"]
        cosa = {("telefono",): "ese número", ("correo",): "ese correo"}.get(tuple(que), "ese número o ese correo")
        return 502, {"motivo": "no_se_pudo_comprobar",
                     "error": ("No se pudo comprobar si %s ya es de otra persona. " % cosa + sin_escribir + " " + si_no_se_pudo).strip()}
    if r.get("estado") != "rechazado":
        return None
    otra = r.get("de")
    if r.get("motivo") in ("telefono_repetido", "correo_repetido") and otra:
        quien_es = ("«%s»" % otra["nombre"]) if otra["nombre"] else "una ficha sin nombre"
        if r["motivo"] == "telefono_repetido":
            return 409, {"motivo": "telefono_repetido", "de": otra,
                         "error": "Ese número ya es de otra persona: %s (ficha n.º %s). %s %s" % (quien_es, otra["Id"], sin_escribir, que_hacer)}
        return 409, {"motivo": "correo_repetido", "de": otra,
                     "error": "Ese correo ya es de otra persona: %s (ficha n.º %s). %s %s"
                              % (quien_es, otra["Id"], sin_escribir, que_hacer_correo or que_hacer)}
    if r.get("motivo") == "mismo_valor":
        cosa = "número" if r.get("llave") == "telefono" else "correo"
        return 409, {"motivo": "mismo_valor", "campo": r.get("llave"),
                     "error": "Ese %s ya está en la otra casilla de esta misma ficha: no puede quedar dos veces en la misma "
                              "persona. %s %s" % (cosa, mismo_valor, sin_escribir)}
    if r.get("motivo") == "unida":
        return 409, {"motivo": "unida", "error": FICHA_UNIDA + " " + sin_escribir}
    if r.get("motivo") == "quitada":
        return 409, {"motivo": "quitada", "error": FICHA_QUITADA + " " + sin_escribir}
    return 400, {"motivo": "forma_invalida", "error": "Un dato no tiene la forma que se espera. " + sin_escribir}


PUERTA_RESULTADOS_CLAROS = ("guardado", "ya_estaba", "no_guardado")      # lo único que una ruta sabe leer de un valor; lo demás NO es «guardado»


def puerta_sin_confirmar(r):
    """¿La puerta NO confirmó lo que escribió? **La única regla de «guardado» para TODAS las rutas que llaman a `recibir`**: una ruta solo puede contestar
    éxito si esto da `False`. Es `True` si el estado no es `aplicado`/`por_resolver`, o si algún valor trae un resultado que no es
    `guardado`/`ya_estaba`/`no_guardado` (`sin_confirmar`, o uno que la ruta no sabe clasificar: cae del lado que no dice «guardado»)."""
    if not isinstance(r, dict) or r.get("estado") not in ("aplicado", "por_resolver"):
        return True
    valores = r.get("valores")
    if not isinstance(valores, dict):
        return True
    return any(not isinstance(v, dict) or v.get("resultado") not in PUERTA_RESULTADOS_CLAROS for v in valores.values())


def avisos_para_la_pantalla(r):
    """Los avisos de la respuesta de la puerta, en lo único que una pantalla necesita: de qué tipo, qué dicen y de qué fichas."""
    return [{"tipo": a["tipo"], "texto": a["texto"], "ficha_id": a.get("ficha_id"), "otra_ficha_id": a.get("otra_ficha_id")}
            for a in r.get("avisos") or []]


def _guardar_edicion_de_persona(cuerpo, quien, editables, leer_filas, rastro, portal, solo_contar=False):
    """Escribe en la ficha de una persona. Devuelve `(codigo, dict)`.

    🔑 ES LA ÚNICA PUERTA PARA ESCRIBIR LOS CAMPOS DE UNA PERSONA (y su teléfono) DESDE LAS PANTALLAS DE FICHAS: la
    usan la ficha del Aprendizaje (`editar_ficha_cliente`: `editables` = `FICHA_EDITABLES`, la fila sale de la identidad) y
    el portal «Personas» (`editar_persona_portal`: `editables` = `PORTAL_EDITABLES`, la fila sale del `Id`). `leer_filas(cols)`
    devuelve las filas de la persona con `Id` y esas columnas; `rastro` es la etiqueta de la línea de registro. `solo_contar=True`
    (el cálculo de P11-6) hace lo mismo hasta la escritura, sin escribir, y devuelve lo que se mandaría (`calculo_de_escrituras`). `portal` (SIN valor por omisión: cada pantalla dice cuál es; `True` solo el portal «Personas»): admite las listas
    de varias opciones y exige forma de correo; la ficha del Aprendizaje queda como estaba.

    Orden y razones (todo antes de escribir, nada a medias):
      1. Lo pedido: solo campos de `FICHA_EDITABLES`; cualquier otro se rechaza sin tocar nada.
      2. La fila la decide el servidor por la identidad; el `Id` que manda la pantalla solo se
         COMPARA. Cero fichas, dos o más, u otra: no se escribe.
      3. Cada valor se valida contra la forma real de la columna (la lista cerrada, el número…).
      4. Lo que hay HOY en la ficha se compara con lo que la persona vio al abrir (`base`):
         si alguien lo cambió en medio, 409 y no se pisa nada. Si ya está como lo pide, no se
         escribe.
      5. UN solo PATCH con todos los campos, y se RELEE: solo se dice «guardado» si lo releído
         es lo pedido.
    """
    if not isinstance(cuerpo, dict):
        return 400, {"error": "pedido ilegible. " + FICHA_ERROR_SIN_ESCRIBIR}
    cambios, base = cuerpo.get("cambios"), cuerpo.get("base")
    if not isinstance(cambios, dict) or not cambios:
        return 400, {"error": "no hay nada que guardar. " + FICHA_ERROR_SIN_ESCRIBIR}
    if not isinstance(base, dict):
        base = {}
    fuera = sorted(str(c) for c in cambios if c not in editables)
    if fuera:
        return 400, {"error": "esos campos no se pueden editar desde aquí: %s. %s"
                              % (", ".join(fuera), FICHA_ERROR_SIN_ESCRIBIR),
                     "campos_rechazados": fuera}
    if any(not isinstance(v, str) for v in cambios.values()):
        return 400, {"error": "los valores van como texto. " + FICHA_ERROR_SIN_ESCRIBIR}
    pedida = cuerpo.get("id")
    if isinstance(pedida, bool) or not isinstance(pedida, int):
        return 400, {"error": "falta el número de la ficha. " + FICHA_ERROR_SIN_ESCRIBIR}
    campos = list(cambios)
    try:
        formas, _ = formas_de_ficha(editables, multiples=portal)
        filas = leer_filas(campos + (["credito"] if "telefono" in campos else []) + ["quitada_el"])
    except _base.SoloLectura:
        raise
    except Exception as e:                       # noqa: BLE001
        print(f"[warn] editar ficha: no se pudo leer ({type(e).__name__})")
        return 502, {"error": "No se pudo leer la ficha en la base. " + FICHA_ERROR_SIN_ESCRIBIR}
    if not filas:
        return 404, {"motivo": "sin_ficha",
                     "error": "Este cliente no tiene ficha. " + FICHA_ERROR_SIN_ESCRIBIR}
    if len(filas) > 1:
        return 409, {"motivo": "duplicada",
                     "error": "Este cliente tiene más de una ficha: no se edita ninguna. "
                              + FICHA_ERROR_SIN_ESCRIBIR}
    fila = filas[0]
    if fila.get("Id") != pedida:
        return 409, {"motivo": "otra_ficha",
                     "error": "La ficha que abriste ya no es la de este cliente. Ábrela de nuevo. "
                              + FICHA_ERROR_SIN_ESCRIBIR}
    # Antes del atajo «sin cambios» (abajo): una ficha guardada aparte no se edita ni con valores iguales a los que tiene.
    if ficha_quitada(fila):
        return 409, {"motivo": "quitada", "error": FICHA_QUITADA + " " + FICHA_ERROR_SIN_ESCRIBIR}
    nuevos = {}
    for c in campos:
        if c not in formas:
            return 400, {"error": "%s no se puede editar ahora. %s"
                                  % (editables[c], FICHA_ERROR_SIN_ESCRIBIR),
                         "campos_rechazados": [c]}
        if c not in base:
            return 400, {"error": "falta lo que decía %s al abrir. %s"
                                  % (editables[c], FICHA_ERROR_SIN_ESCRIBIR)}
        if c in ("nombre", "telefono") and _ficha_canon(formas[c], cambios[c]) is None \
                and _ficha_canon(formas[c], fila.get(c)) is None:
            nuevos[c] = None      # ya estaba vacío y sigue vacío: no se le obliga a nadie a llenarlo
            continue
        try:
            nuevos[c] = _ficha_valor_para_nocodb(c, formas[c], cambios[c], portal)
        except ValueError as e:
            datos = {"error": "%s. %s" % (e, FICHA_ERROR_SIN_ESCRIBIR), "campo": c}
            if formas[c]["tipo"] == "seleccion":
                datos["opciones"] = formas[c]["opciones"]
            return 422, datos
    conflictos, a_escribir = {}, {}
    for c in campos:
        hoy = _ficha_canon(formas[c], fila.get(c))
        if hoy == _ficha_canon(formas[c], nuevos[c]):
            continue                              # ya está como lo pide: no se escribe
        if hoy != _ficha_canon(formas[c], base[c]):
            conflictos[c] = _ficha_a_texto(fila.get(c))
        else:
            a_escribir[c] = nuevos[c]
    if conflictos:
        return 409, {"motivo": "cambio_entre_medio", "conflictos": conflictos,
                     "error": "Alguien cambió esta ficha mientras la editabas (%s). No se pisó nada: "
                              "abre la ficha de nuevo y vuelve a escribir tu cambio."
                              % ", ".join(editables[c] for c in conflictos)}
    if not a_escribir:
        if solo_contar:
            return calculo_de_escrituras([], 200)            # nada que escribir: el cálculo dice lo mismo, sin escrituras
        return 200, {"ok": True, "estado": "sin_cambios",
                     "base": {c: _ficha_a_texto(fila.get(c)) for c in campos}}
    # 🔴 UN SOLO CANDADO ENTRE «¿ya lo tiene otra?» Y EL `PATCH` (7-oct-2026, testigo: sin él, dos guardados a la vez del mismo
    # número en dos fichas pasaban la comprobación los dos y escribían los dos). Desde el 8-oct-2026 lo toma la PUERTA (`recibir`), no esta
    # función: GARANTÍA, tal como la cumple el código: dentro de ESTE proceso, dos guardados a la vez de un teléfono o de un correo por la
    # puerta no terminan los dos en «guardado»: uno gana y al otro se le dice que ya es de otra persona. FRONTERA: el candado es del
    # proceso (`Procfile`: `web: python3 server.py`, un `ThreadingHTTPServer`, sin varios trabajadores; con varias réplicas de Railway NO se
    # comparte) y no cubre a Natalia ni a nadie que escriba en la base por otro lado.
    def confirmar_el_cambio_de_telefono(_plan):
        """Corre DENTRO del candado, ya decidido que el número está libre y antes del `PATCH`: cambiar el teléfono de quien ya tenía uno
        necesita la confirmación de ESE cambio exacto."""
        if "telefono" not in a_escribir:
            return None
        nuevo = a_escribir["telefono"]
        viejo = _telefono_de_ficha(fila.get("telefono")) or str(fila.get("telefono") or "").strip()
        if viejo and viejo != nuevo:
            conf = cuerpo.get("confirmo_telefono")
            if not (isinstance(conf, dict) and conf.get("de") == viejo and conf.get("a") == nuevo):
                try:
                    atado = medir_atado_al_telefono(viejo, fila)
                except _base.SoloLectura:
                    raise
                return 409, {"motivo": "confirmar_cambio_telefono", "de": viejo, "a": nuevo, "atado": atado,
                             "error": "Cambiar el teléfono necesita tu confirmación. " + FICHA_ERROR_SIN_ESCRIBIR}
        return None

    dato = {"origen": "portal" if portal else "aprendizaje", "pantalla": True, "ficha_id": pedida,
            "releer": ",".join(campos),
            "otros": {c: v for c, v in a_escribir.items() if c not in PUERTA_CLAVES_DE_PANTALLA}}
    for campo, clave in CASILLAS_DE_PANTALLA:
        if campo in a_escribir:
            dato[clave] = a_escribir[campo]
    res = recibir(dato, solo_contar=solo_contar, antes_de_escribir=confirmar_el_cambio_de_telefono)
    if res["estado"] == "detenido":
        return res["respuesta"]
    # La frase del «mismo valor en las dos casillas» la elige la pantalla: el portal las enseña las dos; la ficha del
    # Aprendizaje, no (su «Contacto» sale de lo que manda Natalia), así que ahí se le dice DÓNDE está la otra.
    rechazo = respuesta_de_rechazo(res, FICHA_ERROR_SIN_ESCRIBIR,
                                   mismo_valor=(MISMO_VALOR_SE_VEN_LAS_DOS if portal else MISMO_VALOR_UNA_SOLA_A_LA_VISTA))
    if rechazo:
        return rechazo
    if res["etapa"] == "escritura":
        if res["motivo"] == "base_rechazo":
            # `sin_confirmar: True` a propósito: el pedido YA salió hacia NocoDB, y `send_json` (la puerta única de los errores)
            # sobrescribiría este texto con el suyo si no lo ve.
            return 502, {"estado": "no_guardado", "sin_confirmar": True,
                         "error": "La base de datos rechazó el cambio, así que lo normal es que no se "
                                  "haya guardado. Antes de repetirlo, abre la ficha de nuevo y mira "
                                  "cómo quedó."}
        return 502, {"estado": "sin_confirmar", "sin_confirmar": True, "error": FICHA_ERROR_SIN_CONFIRMAR}
    if solo_contar:
        return calculo_de_escrituras(res["mandaria"], 200)     # antes del «sin cambios» de la escritura: su lectura de la ficha es de la escritura
    if not res["escrito"] and not dato["otros"]:
        # la puerta vio que lo pedido ya estaba (p. ej. el mismo correo con otras mayúsculas): nada que escribir
        return 200, {"ok": True, "estado": "sin_cambios", "base": {c: _ficha_a_texto(fila.get(c)) for c in campos}}
    # 🔑 LA HUELLA: quién (firma del servidor) cambió qué (nombres de campo, NUNCA los valores: los registros no llevan datos de
    # clientes) en qué ficha (el número de fila). Es lo que dejan las escrituras hermanas de la ficha (la línea `[CAMARA]`).
    print(f"[{rastro}] persona_id={pedida} quien={quien} campos={','.join(sorted(a_escribir))}")
    releida = res["releida"]
    if puerta_sin_confirmar(res) or not isinstance(releida, dict):
        return 502, {"estado": "sin_confirmar", "sin_confirmar": True, "error": FICHA_ERROR_SIN_CONFIRMAR}
    mal = [c for c in dato["otros"]
           if _ficha_canon(formas[c], releida.get(c)) != _ficha_canon(formas[c], a_escribir[c])]
    if mal:
        print(f"[warn] editar ficha: lo releído no es lo escrito ({','.join(mal)})")
        return 502, {"estado": "sin_confirmar", "sin_confirmar": True, "error": FICHA_ERROR_SIN_CONFIRMAR}
    salida = {"ok": True, "estado": "guardado", "campos": sorted(a_escribir),
              "base": {c: _ficha_a_texto(releida.get(c)) for c in campos}}
    if "telefono" in a_escribir:
        salida["identidad_nueva"] = a_escribir["telefono"]     # con ésta se vuelve a abrir la ficha
    if res["avisos"]:
        salida["avisos"] = avisos_para_la_pantalla(res)
    return 200, salida


def editar_memoria_de_natalia(cuerpo, quien, editables):
    """P8a-1: la memoria de Natalia escribe en la ficha por el programa. La fila sale del `id` del cuerpo (la misma lectura que
    `editar_persona_portal`) y la puerta es `_guardar_edicion_de_persona` con `editables` (los campos que no son de identidad, en
    `personas_memoria.MEMORIA_CAMPOS`). Misma respuesta que `editar_persona_portal` de la App (`ficha` releída y `en_lista`):
    la App no pasa `clave_envio` por esta ruta, así que no hay `una_vez`. Devuelve `(codigo, dict)`."""
    if not isinstance(cuerpo, dict):
        return 400, {"error": "pedido ilegible. " + FICHA_ERROR_SIN_ESCRIBIR}
    pid = cuerpo.get("id")
    if isinstance(pid, bool) or not isinstance(pid, int):
        return 400, {"error": "falta el número de la ficha. " + FICHA_ERROR_SIN_ESCRIBIR}

    def filas(cols):
        try:
            fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(pid)}",
                            query={"fields": ",".join(["Id"] + list(dict.fromkeys(cols)))})
        except _base.ErrorDeNocodb as e:
            if e.status == 404:
                return []
            raise
        return [fila] if isinstance(fila, dict) and fila.get("Id") is not None else []

    codigo, datos = _guardar_edicion_de_persona(cuerpo, quien, editables, filas, "MEMORIA-NATALIA-EDITADA", portal=True)
    if codigo == 200 and datos.get("estado") in ("guardado", "sin_cambios"):
        _portal_con_ficha_releida(datos, pid)
        datos["en_lista"] = _portal_en_lista(pid, cuerpo)
    return codigo, datos


def editar_ficha_cliente(identidad, cuerpo, quien, solo_contar=False):
    """La ficha del Aprendizaje: la fila sale de la identidad (teléfono o BSUID) de la dirección."""
    return _guardar_edicion_de_persona(cuerpo, quien, FICHA_EDITABLES,
                                       lambda cols: _filas_de_identidad(identidad, cols), "FICHA-EDITADA", False,
                                       solo_contar=solo_contar)


# ═══════════════════════════════════════════════════════════════════════════════════════
# LA PUERTA DE LAS FICHAS (parte 1 de `disenos/registro-dueno-de-las-fichas/DISENO.md`, 8-oct-2026)
# ═══════════════════════════════════════════════════════════════════════════════════════
#
# 🔑 `recibir()` ES EL ÚNICO SITIO QUE CREA FILAS DE `personas` Y QUE ESCRIBE `nombre`, `telefono`, `email`, `bsuid` Y
# `nombre_whatsapp`. Las cinco rutas de la App que escriben una persona (el check-in: `crear_persona` y `editar_persona`; el
# portal: `crear_persona_portal` y `_guardar_edicion_de_persona`, que usa también la ficha del Aprendizaje) le pasan el dato a
# esta función y traducen su respuesta. Lo único de `personas` que se escribe fuera es `caras` (`guardar_cara`, el vector de
# la cámara): no es un dato de identidad. `otros` (abajo) es lo que la pantalla ya validó y la puerta escribe en el mismo
# PATCH/POST sin decidirlo.
#
# LAS CUATRO REGLAS CON QUE SE COMPARA (una línea cada una; son las de la medición de la sala del 8-oct-2026, `medir_fichas.py`):
#   · teléfono: `_telefono_de_ficha(celda)` = sus dígitos (de 8 a 15, sin letras; `normalizar_telefono` antepone el 1 solo a los de 10 dígitos); una celda que no lo es no tiene teléfono.
#     (Solo el check-in puede mandar un número sin esa forma; ése se compara por sus dígitos: `_celda_es_el_numero`.)
#   · ID de WhatsApp (`bsuid`): la celda recortada, si tiene forma de BSUID (`es_bsuid`); se compara exacta.
#   · correo (`email`): la celda recortada y en minúsculas, si tiene forma `x@y.z` (`_RE_CORREO`); sin esa forma no tiene correo.
#   · nombre: `normalizar` (sin tildes ni mayúsculas) con los espacios de adentro colapsados.
#
# 🔑 UN TELÉFONO O UN CORREO NO PUEDE QUEDAR EN DOS FICHAS, NI DOS VECES EN LA MISMA, CONTANDO LAS CUATRO CASILLAS
# (`telefono`, `telefono_2`, `email`, `email_2`; parte 4 del diseño `disenos/registro-dueno-de-las-fichas/`). Lo decide ESTA
# función y nadie más, y lo decide mirando VALORES: con la lectura de TODAS las fichas y el candado, no con el `eq` de NocoDB
# ni con una lista escrita a mano. Las cuatro casillas se comparan con las MISMAS reglas de arriba: la principal y la secundaria
# de un teléfono, con la del teléfono; las dos de un correo, con la del correo.
#
# DOS FORMAS DE LLEGAR (las dice el dato, no el origen):
#   · `pantalla: True` — una PERSONA escribió estos valores en ESTA ficha (`ficha_id`) o en una nueva: lo que escribió REEMPLAZA
#     (también vaciar), y si un teléfono o un correo NUEVO ya es de otra ficha no se guarda NADA y se dice de quién es. De aquí
#     salen `telefono_dicho`, `telefono_2`, `correo` y `correo_2`: las cuatro casillas de identidad del dato de una pantalla.
#   · si no — un sistema (WhatsApp) trae datos de alguien: lo decide `_puerta_decidir_automatico`.
#
# NADA DICE «GUARDADO» SIN SER VERDAD: el resultado de cada valor sale de RELEER la fila. Si no se pudo releer, el valor es
# `sin_confirmar`, nunca `guardado`.
PUERTA_CAMPOS = "Id,nombre,nombre_whatsapp,telefono,email,telefono_2,email_2,bsuid,unida_a,quitada_el,credito"   # lo que la puerta lee de TODAS las fichas
# Los nombres de las dos casillas nuevas de la parte 4 (`telefono_2` y `email_2`): las secundarias, para decir en qué casilla
# quedó un valor. Las columnas existen siempre (la sala las crea antes de desplegar).
CAMPOS_SECUNDARIOS = ("telefono_2", "email_2")
PUERTA_ORIGENES = ("mensaje", "dictado", "reserva", "checkin", "portal", "aprendizaje", "recuperado", "google")
# valor de la respuesta → columna de `personas`
PUERTA_COLUMNA = {"id_whatsapp": "bsuid", "telefono": "telefono", "nombre": "nombre", "correo": "email",
                  "nombre_perfil": "nombre_whatsapp", "telefono_2": "telefono_2", "correo_2": "email_2"}
# Las cuatro casillas de identidad del dato de una PANTALLA: (valor de la puerta, columna de `personas`, de qué clase es
# el valor). `telefono_dicho` y `telefono_2` son de la clase `telefono`; `correo` y `correo_2`, de la clase `correo`.
PUERTA_CASILLAS = (("telefono_dicho", "telefono", "telefono"), ("telefono_2", "telefono_2", "telefono"),
                   ("correo", "email", "correo"), ("correo_2", "email_2", "correo"))
PUERTA_HERMANA = {"telefono": "telefono_2", "telefono_2": "telefono", "email": "email_2", "email_2": "email"}
# 🔑 DE LA CLAVE QUE USA UNA PANTALLA A LA DEL VALOR DE LA PUERTA: el nombre y las CUATRO casillas de identidad, sacadas de
# `PUERTA_CASILLAS` (no una lista tecleada aparte). Las rutas que llaman a la puerta desde una ficha (el check-in, el alta del
# portal y `_guardar_edicion_de_persona`) reparten con ESTA tabla: así ninguna casilla se cuela en `otros` (la puerta rechaza un
# `otros` con una columna de identidad, `otros_ilegible`) ni se queda sin escribir por un olvido.
CASILLAS_DE_PANTALLA = (("nombre", "nombre"),) + tuple((col, entrada) for entrada, col, _cls in PUERTA_CASILLAS)
PUERTA_CLAVES_DE_PANTALLA = {col for col, _entrada in CASILLAS_DE_PANTALLA}
# Las casillas de teléfono, por nombre de columna: la forma «es un teléfono» de una columna que NocoDB no declara `PhoneNumber`.
CAMPOS_TELEFONO = frozenset(col for _e, col, cls in PUERTA_CASILLAS if cls == "telefono")
# Los valores de identidad que la puerta sabe leer. La bandeja NO lleva las dos casillas nuevas (su tabla no tiene esas
# columnas: parte 4 del diseño no las agrega), por eso la lista de la bandeja es aparte (`_puerta_apuntar_en_bandeja`).
_PUERTA_VALORES = ("id_whatsapp", "telefono_meta", "telefono_dicho", "telefono_2", "nombre", "nombre_perfil",
                   "correo", "correo_2")
_RE_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_PUERTA_ENTRADA = ("clave", "origen", "pantalla", "ficha_id", "otros", "releer", "telefono_sin_forma_ok",
                   "id_whatsapp", "telefono_meta", "telefono_dicho", "telefono_2", "nombre", "nombre_perfil",
                   "correo", "correo_2")

# `caso` del camino de sistema: `<llave>:<qué pasó>`. La llave es por la que quedó determinada la ficha (`ninguna` si se crea o no se
# determinó); lo que pasó, lo que decidió la puerta.
PUERTA_LLAVES = ("id", "telefono_meta", "telefono_dicho", "correo", "ninguna")
PUERTA_QUE = ("crea", "completa", "sin_cambios", "misma_persona", "telefono_y_correo", "sin_decidir", "rechazado")
PUERTA_CASOS = tuple("%s:%s" % (llave, que) for llave in PUERTA_LLAVES for que in PUERTA_QUE)

# Los avisos que la puerta sabe dar: `tipo → (informativo, frase)`. Informativo = «no hay que hacer nada si está bien»; lo que
# NO está aquí cae del lado estricto (no informativo).
PUERTA_AVISOS = {
    "mismo_nombre": (True, "Ojo: ya hay otra ficha con ese mismo nombre (ficha n.º {otra}). Puede ser la misma persona."),
    "ligado_por_correo": (True, "Este dato quedó en la ficha n.º {ficha} porque trajo su correo."),
    "ligado_por_dictado": (True, "Este dato quedó en la ficha n.º {ficha} porque se dictó su número."),
    "id_cambiado": (True, "La ficha n.º {ficha} cambió de ID de WhatsApp porque llegó uno nuevo junto a su número."),
    "llave_repetida": (False, "Hay más de una ficha con el mismo dato (n.º {ficha} y n.º {otra}): ese dato no decide."),
    "telefono_y_correo": (False, "El teléfono es de la ficha n.º {ficha} y el correo de la n.º {otra}: no se guardó el dato."),
    "misma_persona": (False, "Las fichas n.º {ficha} y n.º {otra} parecen la misma persona: falta unirlas."),
    "unidas_solas": (True, "Las fichas n.º {otra} y n.º {ficha} se unieron solas: quedó la n.º {ficha}."),
    "otro_valor": (False, "La ficha n.º {ficha} ya tiene otro valor y no se cambió."),
    "telefono_ajeno": (False, "El número dictado es de la ficha n.º {otra}: no se guardó."),
}

# Los avisos que la puerta deja cuando UNIÓ dos fichas: son los únicos que «Por resolver» ofrece deshacer (`ficha_id` = la que quedó).
# Todos tienen que estar en `PUERTA_AVISOS` y ser informativos (la prueba lo exige).
PUERTA_AVISOS_DE_UNION = ("unidas_solas",)

# La frase de un aviso cuando su ficha todavía no existe (`ficha_id` en `None`); los demás avisos cambian «n.º {ficha}» por «nueva».
PUERTA_AVISO_FICHA_NUEVA = {
    "misma_persona": "La ficha nueva de este dato y la n.º {otra} parecen la misma persona: falta unirlas.",
}

# LA BANDEJA (tabla de NocoDB que crea la sala; su id llega por `NOCODB_T_BANDEJA_PERSONAS`): nombre de columna → tipo de NocoDB.
# Es la fuente de verdad de la definición: `comprobar_bandeja.py` la compara con la tabla real.
BANDEJA_COLUMNAS = {
    "clave": "SingleLineText", "origen": "SingleLineText", "id_whatsapp": "SingleLineText",
    "telefono_meta": "SingleLineText", "telefono_dicho": "SingleLineText", "nombre": "SingleLineText",
    "nombre_perfil": "SingleLineText", "correo": "SingleLineText", "estado": "SingleLineText", "resultado": "LongText",
    "ficha_id": "Number", "otra_ficha_id": "Number", "tipo_aviso": "SingleLineText", "resuelto_por": "SingleLineText",
    "resuelto_en": "DateTime",
}
BANDEJA_UNICA = "clave"


def clave_telefono(celda):
    """Regla de comparación del TELÉFONO: ver el bloque de arriba."""
    return _telefono_de_ficha(celda)


def clave_id(celda):
    """Regla de comparación del ID de WhatsApp: la celda recortada si tiene forma de BSUID."""
    t = str(celda or "").strip()
    return t if t and es_bsuid(t) else None


def clave_correo(celda):
    """Regla de comparación del CORREO: recortado y en minúsculas, si tiene forma de correo."""
    t = str(celda or "").strip()
    return t.lower() if _RE_CORREO.fullmatch(t) else None


def clave_nombre(celda):
    """Regla de comparación del NOMBRE: sin tildes ni mayúsculas y con los espacios de adentro colapsados."""
    return " ".join(normalizar(celda).split()) or None


def _leer_fichas_de_la_puerta():
    """UNA lectura de todas las fichas con lo único que la puerta compara. Se llama por su nombre en este módulo.

    🔴 **NO HAY REINTENTO** (9-oct-2026, tras un NO PASA del testigo). Hubo uno que, ante un rechazo de NocoDB, volvía a leer
    sin las dos columnas nuevas («por si la tabla todavía no las tiene»): un 429 de NocoDB bastaba para que la comprobación de
    teléfono repetido se saltara y el check-in creara una ficha con el número de otra. La sala crea las columnas ANTES de
    desplegar (`comprobar_columnas.py`), así que el código da por hecho que están; y si una lectura falla por lo que sea, se
    porta como cualquier lectura que falla: no se pudo comprobar, no se escribe, no se dice «guardado»."""
    return [f for f in _base.nc_list_all(_base.T_PERSONAS, {"fields": PUERTA_CAMPOS}) if not ficha_fuera(f)]


# ---------- P4 (contactos de Google): el enlace ficha ↔ contacto ----------
# La columna la crea la sala (SingleLineText). Guarda el `resourceName` del contacto de Google que se creó para la ficha.
CAMPO_GOOGLE_ID = "google_id"


def columna_google_id_existe():
    """¿Existe la columna `google_id` en `personas`? Usa la ÚNICA lectura del esquema que tiene la App (`_opciones_select`).
    Un error de NocoDB sale como excepción: quien llama no escribe nada."""
    return _base._opciones_select(_base.T_PERSONAS, None, columnas=(CAMPO_GOOGLE_ID,)).get(CAMPO_GOOGLE_ID) is not None


def leer_fichas_para_google(con_enlace):
    """TODAS las fichas, unidas y quitadas incluidas (para contarlas aparte), con lo que P4 compara; `google_id` solo si la
    columna existe. Quien llama decide qué entra."""
    campos = ",".join(PUERTA_CAMPOS.split(",") + ([CAMPO_GOOGLE_ID] if con_enlace else []))
    return _base.nc_list_all(_base.T_PERSONAS, {"fields": campos})


def ids_con_aviso_abierto():
    """`(estado, ids)`: los `Id` de fichas que aparecen en un aviso abierto de «Por resolver» (como `ficha_id` o `otra_ficha_id`).
    `estado` es `ok` solo si la bandeja se leyó entera; si no, quien llama no escribe nada."""
    estado, avisos = _por_resolver_leer_avisos()
    if estado != "ok":
        return estado, set()
    ids = set()
    for a in avisos:
        for c in ("ficha_id", "otra_ficha_id"):
            v = a.get(c)
            if isinstance(v, int) and not isinstance(v, bool):
                ids.add(v)
    return "ok", ids


def ids_por_resolver():
    """`(estado, ids)`: las fichas que «Por resolver» enseña. Son las de un aviso abierto de la bandeja (`ids_con_aviso_abierto`)
    y las de CUALQUIER grupo calculado (`por_resolver_grupos`, la misma función que usa el portal, sobre las filas de
    `portal_personas_todas`). `estado` es `ok` solo si la bandeja se leyó entera; si no, quien llama no escribe nada."""
    estado, ids = ids_con_aviso_abierto()
    if estado != "ok":
        return estado, set()
    for g in por_resolver_grupos([p["publica"] for p in portal_personas_todas()]):
        ids |= set(g["ids"])
    return "ok", ids


def enlazar_ficha_con_google(ficha_id, resource_name):
    """P4: guarda `resource_name` en la ficha. Bajo el candado de la ficha relee: solo escribe si la ficha sigue viva (ni unida
    ni quitada) y sin enlace. Relee después. Devuelve True solo si NocoDB devuelve ese mismo valor; si no, False (y no se dice
    «creado»). Un `resource_name` que no sea `people/…` no se guarda."""
    if not isinstance(resource_name, str) or not resource_name.startswith("people/"):
        return False
    fid = int(ficha_id)
    base = f"/api/v2/tables/{_base.T_PERSONAS}/records"
    with _candado_de_ficha(fid):
        antes = _base.nc("GET", f"{base}/{fid}", query={"fields": f"Id,unida_a,quitada_el,{CAMPO_GOOGLE_ID}"})
        if not isinstance(antes, dict) or antes.get("Id") != fid or ficha_fuera(antes):
            return False
        ya = antes.get(CAMPO_GOOGLE_ID)
        if ya == resource_name:
            return True
        if ya not in (None, ""):
            return False
        _base.nc("PATCH", base, body={"Id": fid, CAMPO_GOOGLE_ID: resource_name})
        despues = _base.nc("GET", f"{base}/{fid}", query={"fields": f"Id,{CAMPO_GOOGLE_ID}"})
        return isinstance(despues, dict) and despues.get(CAMPO_GOOGLE_ID) == resource_name


class _PuertaIlegible(Exception):
    """El dato que le llegó a la puerta no se sabe leer: no se escribe nada y se dice por qué (`str(e)` es el motivo)."""


def _puerta_leer_valor(campo, dato, laxo, pantalla):
    """`(clase, valor)`: `ausente` (no vino), `vacio` (vino vacío), `valor` (ya normalizado) o `invalido` (no se sabe leer)."""
    if campo not in dato:
        return "ausente", None
    v = dato[campo]
    if v is None:
        return "vacio", None
    if not isinstance(v, str):
        return "invalido", None
    t = v.strip()
    if not t:
        return "vacio", None
    if campo == "id_whatsapp":
        return ("valor", t) if clave_id(t) else ("invalido", None)
    if campo in ("telefono_meta", "telefono_dicho", "telefono_2"):
        if laxo:                                   # el check-in escribe los dígitos que le den (sin dígitos = vaciar)
            d = normalizar_telefono(t)
            return ("valor", d) if d else ("vacio", None)
        d = _telefono_de_ficha(t)
        return ("valor", d) if d else ("invalido", None)
    if campo in ("correo", "correo_2"):
        if clave_correo(t):
            return "valor", t.lower()
        return ("valor", t) if pantalla else ("invalido", None)   # una pantalla guarda lo que escribió; un sistema, solo un correo
    return "valor", t


def _puerta_leer_entrada(dato):
    """Valida y normaliza lo que llega. Levanta `_PuertaIlegible` con el motivo; lo que no sabe leer NO se escribe."""
    if not isinstance(dato, dict) or set(dato) - set(_PUERTA_ENTRADA):
        raise _PuertaIlegible("dato_ilegible")
    if dato.get("origen") not in PUERTA_ORIGENES:
        raise _PuertaIlegible("origen_desconocido")
    pantalla = dato.get("pantalla") is True
    ficha_id = dato.get("ficha_id")
    if ficha_id is not None and (isinstance(ficha_id, bool) or not isinstance(ficha_id, int) or not pantalla):
        raise _PuertaIlegible("ficha_id_ilegible")           # `ficha_id` solo viene de una pantalla que edita una ficha abierta
    otros = dato.get("otros") or {}
    if not isinstance(otros, dict) or set(otros) & (set(PUERTA_COLUMNA.values()) | {"Id"}):
        raise _PuertaIlegible("otros_ilegible")              # la identidad solo se escribe por los cinco valores de la puerta
    if pantalla and any(dato.get(c) is not None for c in ("telefono_meta", "id_whatsapp", "nombre_perfil")):
        raise _PuertaIlegible("pantalla_con_dato_de_sistema")    # una persona no escribe el ID ni el número que manda WhatsApp
    if not pantalla and any(dato.get(c) is not None for c in ("telefono_2", "correo_2")):
        raise _PuertaIlegible("casilla_secundaria_sin_pantalla")  # el dato de un sistema no trae casillas secundarias: la puerta decide cuál usar
    laxo = dato.get("telefono_sin_forma_ok") is True
    L = {c: _puerta_leer_valor(c, dato, laxo, pantalla) for c in _PUERTA_VALORES}
    return {"origen": dato["origen"], "pantalla": pantalla, "ficha_id": ficha_id, "otros": dict(otros), "L": L,
            "releer": str(dato.get("releer") or ""), "laxo": laxo, "clave": str(dato.get("clave") or "")}


def _puerta_aviso(tipo, ficha_id=None, otra_ficha_id=None, **extra):
    informativo, frase = PUERTA_AVISOS.get(tipo, (False, "Aviso sin clasificar."))
    if ficha_id is None:                                          # la ficha todavía no existe: el texto la llama «nueva», sin imprimir None
        frase = PUERTA_AVISO_FICHA_NUEVA.get(tipo) or frase.replace("n.º {ficha}", "nueva")
    return dict(extra, tipo=tipo, ficha_id=ficha_id, otra_ficha_id=otra_ficha_id, informativo=informativo,
                texto=frase.format(ficha=ficha_id, otra=otra_ficha_id))


def _puerta_plan(ficha_id, crear):
    return {"ficha_id": ficha_id, "crear": crear, "escribir": {}, "valores": {}, "avisos": [], "estado": "aplicado",
            "motivo": None, "de": None, "llave": None, "ficha": None, "detener": False, "claves": {}}


def _puerta_valor(resultado, motivo=None, **extra):
    r = {"resultado": resultado}
    if motivo:
        r["motivo"] = motivo
    r.update(extra)
    return r


def _puerta_dueno(f):
    return {"Id": f.get("Id"), "nombre": str(f.get("nombre") or "").strip()}


def _puerta_casilla(col):
    """En qué casilla quedó un valor, tal como lo dice la respuesta (`guardado` lo dice desde la parte 4)."""
    return "secundario" if col in CAMPOS_SECUNDARIOS else "principal"


def _puerta_ficha_tiene(fila, clase, valor):
    """¿ESTA ficha tiene ese valor, en la casilla principal o en la secundaria? La regla de la puerta para esa clase de valor
    (`_celda_es_el_numero` para el teléfono, `clave_correo` para el correo), aplicada a las DOS casillas de la clase.
    `valor` es el que llegó, ya normalizado; un correo sin forma no se compara con nadie (devuelve `False`)."""
    if clase == "telefono":
        return any(_celda_es_el_numero(fila.get(c), valor) for c in ("telefono", "telefono_2"))
    k = clave_correo(valor)
    return k is not None and any(clave_correo(fila.get(c)) == k for c in ("email", "email_2"))


def _puerta_mismo_valor(celda, valor, clase):
    """¿La casilla `celda` dice lo mismo que el `valor` que llegó? Sirve para las dos casillas de la MISMA ficha (la principal
    y la secundaria no pueden decir lo mismo): misma regla que `_puerta_ficha_tiene`, para una celda sola."""
    if str(celda or "").strip() == "" or str(valor or "").strip() == "":
        return False
    if clase == "telefono":
        return _celda_es_el_numero(celda, valor)
    k = clave_correo(valor)
    return k is not None and clave_correo(celda) == k


def _puerta_decidir_explicito(E, filas, actual):
    """Una persona escribió estos valores (`pantalla: True`). Reemplaza; si un teléfono o correo NUEVO es de otra ficha, rechaza todo.

    Las CUATRO casillas de identidad (`telefono_dicho`, `telefono_2`, `correo`, `correo_2`) se deciden aquí, con una sola regla:
    lo que la persona escribió se escribe (también vaciar); un valor que ESTA ficha ya tenía —en la principal o en la
    secundaria— no se compara con nadie; uno nuevo no puede ser de OTRA ficha ni estar ya en la casilla hermana de la misma."""
    L, fid = E["L"], E["ficha_id"]
    p = _puerta_plan(fid, fid is None)
    p["ficha"] = actual
    # nombre
    clase, v = L["nombre"]
    if clase == "valor":
        p["escribir"]["nombre"] = v
        p["valores"]["nombre"] = _puerta_valor("guardado")
    elif clase != "ausente":
        p["valores"]["nombre"] = _puerta_valor("no_guardado", "forma_invalida")
        p["estado"], p["motivo"], p["detener"] = "rechazado", "forma_invalida", True
    # 🔑 LAS CUATRO CASILLAS DE IDENTIDAD. `queda` dice cómo va a quedar cada casilla de `personas`: lo que llegó en el pedido,
    # o lo que la ficha tiene hoy si esa casilla no vino (una pantalla manda las cuatro, o solo las que cambió).
    queda = {col: (L[campo][1] if L[campo][0] != "ausente" else (actual or {}).get(col))
             for campo, col, _cls in PUERTA_CASILLAS}
    for campo, col, cls in PUERTA_CASILLAS:
        clase, v = L[campo]
        if clase == "ausente":
            continue
        if clase == "vacio":
            p["escribir"][col] = None
            p["valores"][campo] = _puerta_valor("guardado")
            continue
        if clase == "invalido":
            p["valores"][campo] = _puerta_valor("no_guardado", "forma_invalida")
            p["estado"], p["motivo"], p["detener"] = "rechazado", "forma_invalida", True
            continue
        if _puerta_mismo_valor(queda.get(PUERTA_HERMANA[col]), v, cls):    # la hermana de la MISMA ficha ya dice lo mismo
            p["valores"][campo] = _puerta_valor("no_guardado", "mismo_valor", en=_puerta_casilla(col))
            p["estado"], p["motivo"], p["detener"], p["llave"], p["de"] = "rechazado", "mismo_valor", True, cls, None
            continue
        ya = actual is not None and _puerta_ficha_tiene(actual, cls, v)    # lo ya guardado no se compara con nadie
        dueñas = [] if ya else [f for f in (filas or [])
                                if f.get("Id") != fid and _puerta_ficha_tiene(f, cls, v)]
        if dueñas:
            p["valores"][campo] = _puerta_valor("no_guardado", "de_otra_ficha", en=_puerta_casilla(col))
            if not p["detener"]:
                p["estado"], p["motivo"], p["detener"], p["llave"], p["de"] = (
                    "rechazado", "telefono_repetido" if cls == "telefono" else "correo_repetido", True, cls,
                    _puerta_dueno(dueñas[0]))
        else:                       # lo que una persona escribió se escribe (también lo que la ficha ya tenía: normaliza la celda)
            p["escribir"][col] = v
            p["valores"][campo] = _puerta_valor("guardado", en=_puerta_casilla(col))
    # aviso: el nombre completo de una ficha NUEVA ya es de otra (no bloquea; fila E3). Si no se pudo leer las fichas, se crea igual y sin aviso.
    clase, v = L["nombre"]
    if clase == "valor" and fid is None and filas is not None and not p["detener"]:
        llave = clave_nombre(v)
        otras = [f for f in filas if clave_nombre(f.get("nombre")) == llave]
        if otras:
            p["avisos"].append(_puerta_aviso("mismo_nombre", None, otras[0].get("Id")))
    return p


def _puerta_detener(p, estado, aviso, motivo, L):
    """La puerta no escribe nada: lo que llegó queda `no_guardado` con su motivo y el aviso dice por qué."""
    p["estado"], p["detener"] = estado, True
    if aviso is not None:
        p["avisos"].append(aviso)
    p["escribir"].clear()
    for c in _PUERTA_VALORES:
        if L[c][0] == "valor":
            p["valores"][_puerta_clave_de_valor(c, L)] = _puerta_valor("no_guardado", motivo)
    return p


def _puerta_clave_de_valor(campo, L):
    """Con qué nombre sale `campo` en `valores`: los dos teléfonos de un sistema son `telefono`, salvo el dictado cuando también
    vino el de Meta. Las dos casillas nuevas (`telefono_2`, `correo_2`) salen con su propio nombre: la pantalla que las escribió
    sabe cuál pidió, y cada una dice en qué casilla quedó."""
    if campo == "telefono_meta":
        return "telefono"
    if campo == "telefono_dicho":
        return "telefono_dicho" if L["telefono_meta"][0] == "valor" else "telefono"
    return campo


def _puerta_decidir_automatico(E, filas):
    """Decide qué hacer con un dato que no viene de una pantalla. `caso` = `<llave>:<qué pasó>` (`PUERTA_CASOS`)."""
    L = E["L"]
    p = _puerta_plan(None, False)
    V = {c: L[c][1] for c in L if L[c][0] == "valor"}
    meta, dicho = V.get("telefono_meta"), V.get("telefono_dicho")
    tel = meta or dicho
    correo, idw, nombre, perfil = V.get("correo"), V.get("id_whatsapp"), V.get("nombre"), V.get("nombre_perfil")
    for c in L:
        if L[c][0] == "invalido":                  # lo que no sabe leer no se escribe, y se dice
            p["valores"][_puerta_clave_de_valor(c, L)] = _puerta_valor("no_guardado", "forma_invalida")
    if not idw and not tel:                        # nada que identifique: no se crea ni se toca ninguna ficha
        p["caso"], p["motivo"] = "ninguna:rechazado", "sin_identidad"
        return _puerta_detener(p, "rechazado", None, "sin_identidad", L)

    # 🔑 LA DUEÑA SE BUSCA EN LAS DOS CASILLAS, con la misma función que el camino de pantalla (`_puerta_ficha_tiene`): una
    # ficha que tiene el número —o el correo— en su casilla secundaria ES la dueña.
    FT = [f for f in filas if tel and _puerta_ficha_tiene(f, "telefono", tel)]
    FC = [f for f in filas if correo and _puerta_ficha_tiene(f, "correo", correo)]
    FW = [f for f in filas if idw and clave_id(f.get("bsuid")) == idw]
    repetidas = set()
    for llave, lista, valor_clave in (("telefono", FT, "telefono"), ("correo", FC, "correo"), ("id_whatsapp", FW, "id_whatsapp")):
        if len(lista) >= 2:                        # C7: una llave en dos fichas no decide
            p["avisos"].append(_puerta_aviso("llave_repetida", lista[0].get("Id"), lista[1].get("Id"), llave=llave))
            lista.clear()
            repetidas.add(valor_clave)
    ft, fc, fw = (FT[0] if FT else None), (FC[0] if FC else None), (FW[0] if FW else None)

    # Quien escribe: la ficha del ID; si no, la del número que mandó Meta; si no, ninguna (nace la suya, o se liga si no trae ID ni número de Meta).
    if fw:
        quien, por, llave = fw, "id", "id"
    elif meta and ft:
        quien, por, llave = ft, "telefono", "telefono_meta"
    else:
        quien, por, llave = None, None, "ninguna"
    la_otra = prueba_de_la_otra = None
    if quien is not None:
        # Un número o un correo que señala OTRA ficha: dos fichas, la misma persona (A4, B3, C4, C5, C6). Se nombra primero la de quien escribe.
        for otra, prueba in ((ft, "meta" if meta else "dictado"), (fc, "correo")):
            if otra and otra.get("Id") != quien.get("Id"):
                p["caso"] = llave + ":misma_persona"
                return _puerta_detener(p, "por_resolver", _puerta_aviso("misma_persona", quien.get("Id"), otra.get("Id"), prueba=prueba), "por_resolver", L)
        elegida = quien
    else:
        if ft and fc and ft.get("Id") != fc.get("Id"):                   # el número dictado es de una ficha y el correo de otra
            p["caso"] = "ninguna:telefono_y_correo"
            return _puerta_detener(p, "por_resolver", _puerta_aviso("telefono_y_correo", ft.get("Id"), fc.get("Id")), "por_resolver", L)
        elegida, por, llave = ((ft, "telefono", "telefono_dicho") if ft else ((fc, "correo", "correo") if fc else (None, None, "ninguna")))
        if elegida is not None and (idw or meta):   # trae su ID o su número de Meta y ninguna ficha lo tiene: nace la suya y la otra es la misma persona
            la_otra, prueba_de_la_otra = elegida, ("dictado" if por == "telefono" else "correo")
            elegida, por, llave = None, None, "ninguna"
    if elegida is None and repetidas:                                    # nada decide: no se crea una ficha más con ese dato
        p["caso"] = "ninguna:sin_decidir"
        return _puerta_detener(p, "por_resolver", None, "por_resolver", L)
    ligada = quien is None and elegida is not None
    if elegida is not None:
        p["ficha_id"], p["ficha"] = elegida.get("Id"), elegida
        if ligada and E["origen"] == "google":                           # origen google: un contacto que casa con su ficha es lo esperado (la ficha ya tiene ese dato). No es novedad: no avisa, y así correr otra vez no deja filas nuevas.
            pass
        elif ligada and por == "correo":                                 # el dato no trae ID ni número de Meta: el correo es de una ficha
            p["avisos"].append(_puerta_aviso("ligado_por_correo", elegida.get("Id")))
        elif ligada:                                                     # el dato no trae ID ni número de Meta: el número dictado es de una ficha
            p["avisos"].append(_puerta_aviso("ligado_por_dictado", elegida.get("Id")))
    else:
        p["crear"] = True                                                # A1 / A7 / B1
    de_la_otra = set()
    if la_otra is not None:                                              # B2, B4, C4, C6: nace la ficha de quien escribe; lo que apunta a la otra no se escribe
        p["avisos"].append(_puerta_aviso("misma_persona", None, la_otra.get("Id"), prueba=prueba_de_la_otra, ficha_nueva=True))
        de_la_otra = {c for c, f in (("telefono", ft), ("correo", fc)) if f is not None}
    fch = elegida

    def vacia(col):
        return fch is None or str(fch.get(col) or "").strip() == ""

    def libre(col):
        return vacia(col) and col not in p["escribir"]

    def a_la_secundaria(valor_clave, sec, nuevo):
        p["escribir"][sec] = nuevo
        p["claves"][sec] = valor_clave
        p["valores"][valor_clave] = _puerta_valor("guardado", en=_puerta_casilla(sec))

    def poner(valor_clave, col, nuevo, ya, motivo, tipo_aviso="otro_valor", sec=None):
        """Completa `col` si está vacía; con `sec`, un valor nuevo cuya principal está ocupada va a la secundaria libre de la ficha de quien escribe."""
        if valor_clave in repetidas or valor_clave in de_la_otra:
            p["valores"][valor_clave] = _puerta_valor("no_guardado", "por_resolver")
        elif fch is not None and ya(fch):
            p["valores"][valor_clave] = _puerta_valor("ya_estaba")
        elif vacia(col):
            p["escribir"][col] = nuevo
            p["valores"][valor_clave] = _puerta_valor("guardado", en="principal")
        elif sec and quien is not None and libre(sec):
            a_la_secundaria(valor_clave, sec, nuevo)
        else:
            p["valores"][valor_clave] = _puerta_valor("no_guardado", motivo)
            if tipo_aviso:
                p["avisos"].append(_puerta_aviso(tipo_aviso, p["ficha_id"], None))

    if tel:
        poner("telefono", "telefono", tel, lambda f: _puerta_ficha_tiene(f, "telefono", tel), "por_resolver", sec="telefono_2")
    if meta and dicho and dicho != meta:                                 # B5 / B6: además del de WhatsApp, dictó otro
        ajena = [f for f in filas if _puerta_ficha_tiene(f, "telefono", dicho)]
        if ajena and (fch is None or ajena[0].get("Id") != fch.get("Id")):
            p["valores"]["telefono_dicho"] = _puerta_valor("no_guardado", "no_se_guarda_solo")
            p["avisos"].append(_puerta_aviso("telefono_ajeno", p["ficha_id"], ajena[0].get("Id")))
        elif fch is not None and _puerta_ficha_tiene(fch, "telefono", dicho):
            p["valores"]["telefono_dicho"] = _puerta_valor("ya_estaba")
        elif quien is not None and (not vacia("telefono") or "telefono" in p["escribir"]) and libre("telefono_2"):
            a_la_secundaria("telefono_dicho", "telefono_2", dicho)
        else:
            p["valores"]["telefono_dicho"] = _puerta_valor("no_guardado", "por_resolver")
            p["avisos"].append(_puerta_aviso("otro_valor", p["ficha_id"], None))
    if correo:
        poner("correo", "email", correo, lambda f: _puerta_ficha_tiene(f, "correo", correo), "por_resolver", sec="email_2")
    if nombre:
        # Un nombre distinto del que la ficha ya tiene NO se pisa (la puerta no decide quién se llama cómo), pero se avisa igual que un
        # correo o un teléfono que no caben: `otro_valor`, por la MISMA función `poner` (13-oct-2026, Tiziano: «Debe salir en Personas para
        # resolver»). «Mismo nombre» es `clave_nombre`. `nombre_perfil` (el nombre de WhatsApp) sigue sin aviso: cambia solo y seguido.
        poner("nombre", "nombre", nombre, lambda f: clave_nombre(f.get("nombre")) == clave_nombre(nombre), "por_resolver")
    if perfil:
        poner("nombre_perfil", "nombre_whatsapp", perfil, lambda f: clave_nombre(f.get("nombre_whatsapp")) == clave_nombre(perfil),
              "no_se_guarda_solo", None)
    if idw:
        if "id_whatsapp" not in repetidas and not vacia("bsuid") and clave_id(fch.get("bsuid")) != idw and meta and por == "telefono":
            p["escribir"]["bsuid"] = idw                                 # A3: el número manda y el ID nuevo reemplaza
            p["valores"]["id_whatsapp"] = _puerta_valor("guardado", en="principal")
            p["avisos"].append(_puerta_aviso("id_cambiado", p["ficha_id"], id_viejo=clave_id(fch.get("bsuid"))))
        else:                                                            # A2 / A5 / A7 / B4
            poner("id_whatsapp", "bsuid", idw, lambda f: clave_id(f.get("bsuid")) == idw, "por_resolver")
    if "nombre" in p["escribir"]:                                        # D3
        otras = [f for f in filas if f.get("Id") != p["ficha_id"] and clave_nombre(f.get("nombre")) == clave_nombre(nombre)]
        if otras:
            p["avisos"].append(_puerta_aviso("mismo_nombre", p["ficha_id"], otras[0].get("Id")))
    if any(not a["informativo"] for a in p["avisos"]):
        p["estado"] = "por_resolver"
    p["caso"] = "%s:%s" % (llave, "misma_persona" if la_otra is not None else ("crea" if p["crear"] else ("completa" if p["escribir"] else "sin_cambios")))
    return p


# 🔴 LA PUERTA LEE ELLA MISMA LA FICHA QUE VA A TOCAR, Y LA LEE DENTRO DEL CANDADO (9-oct-2026, tras un NO PASA del
# testigo). No puede depender de lo que le pase quien llama: `_guardar_edicion_de_persona` le manda una fila leída con SOLO
# las columnas que cambian, así que si el pedido traía `telefono` esa fila no traía `telefono_2`, la casilla hermana salía
# vacía y la puerta dejaba escribir en `telefono` el número que la ficha ya tenía en `telefono_2` (y contestaba «guardado»).
PUERTA_CAMPOS_DE_LA_FICHA = "Id,nombre,telefono,telefono_2,email,email_2,unida_a,quitada_el"     # las cuatro casillas, siempre


def _puerta_leer_la_ficha(fid):
    """La ficha que se va a tocar, como está HOY, con las CUATRO casillas. La lee la puerta (no la ruta) y dentro del candado.

    🔴 **CUALQUIER fallo de esta lectura levanta, y la puerta no escribe nada** (9-oct-2026, tras el NO PASA del testigo): un
    401, un 429, un 5xx, un corte de red, una respuesta que no es una fila… **y también un 404**, que se trata igual que los
    demás. Sin saber cómo está la ficha no se decide nada: la casilla hermana es la mitad de la garantía.

    **CUÁNDO SE LEE LA FICHA**: se lee cuando se juntan dos cosas — es una **pantalla** (`pantalla: True`) y **edita una ficha que
    ya existe** (`ficha_id`) —, sea cual sea el campo que cambia: la lectura dice si la ficha está unida a otra (entonces no se
    escribe) y, si el pedido trae una casilla de identidad con valor, con qué casilla hermana puede chocar. No se lee:
      · un **sistema** (sin `pantalla`) decide con la lista de TODAS las fichas (`_leer_fichas_de_la_puerta`): esta lectura no
        la hace (0 lecturas por Id);
      · un **alta** (sin `ficha_id`) no tiene ficha que leer.

    (Antes el 404 devolvía `{}` «porque esa ficha no tiene fila»: eso era un supuesto sobre cómo contesta NocoDB, y con la
    fila existiendo —el portal la había leído— dejaba escribir el valor de la casilla hermana en la principal. Lo cazó el
    testigo.)"""
    try:
        fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(fid)}", query={"fields": PUERTA_CAMPOS_DE_LA_FICHA})
    except _base.SoloLectura:
        raise
    if not isinstance(fila, dict):
        raise ValueError("la ficha que se iba a tocar no vino como una fila")
    return fila


def _puerta_que_comparar(E, actual):
    """Qué CLASES de valor (`telefono`/`correo`) hay que comparar con las DEMÁS fichas: las que traen un valor que ESTA ficha
    no tiene en ninguna de sus dos casillas. Lo que la ficha ya tenía no se compara con nadie (así una ficha que ya existe con
    un correo repetido sigue pudiéndose guardar); un correo sin forma tampoco (el check-in lo guarda tal cual)."""
    L, comparar = E["L"], []
    for campo, _col, cls in PUERTA_CASILLAS:
        if L[campo][0] != "valor":
            continue
        v = L[campo][1]
        if cls == "correo" and clave_correo(v) is None:
            continue
        if not _puerta_ficha_tiene(actual, cls, v):
            comparar.append(cls)
    return list(dict.fromkeys(comparar))


def _puerta_coincide(col, escrito, leido):
    """¿Lo releído en `col` es lo que se escribió? (vacío = vacío; teléfono por valor; correo sin mayúsculas; texto recortado).
    Vale para las cuatro casillas de identidad: `telefono_2` se comprueba como `telefono`, `email_2` como `email`."""
    texto = "" if leido is None else str(leido).strip()
    if escrito is None:
        return texto == ""
    if col in ("telefono", "telefono_2"):
        return _celda_es_el_numero(leido, escrito)
    if col in ("email", "email_2"):
        return texto.lower() == str(escrito).strip().lower()
    return texto == str(escrito).strip()


def _puerta_otro_coincide(escrito, leido):
    """¿Lo releído en una columna de `otros` (instagram, notas, instrumento, `Posible_proveedor`, lo que sea que no es identidad) es lo que se
    escribió? Vacío = vacío; texto recortado; un número vale por valor (`1500` = `1500.0`); una lista separada por comas vale sin importar el
    orden. Cualquier otra cosa NO coincide: cae del lado que no dice «guardado»."""
    def texto(v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x).strip() for x in v)
        return str(v).strip()
    a, b = texto(escrito), texto(leido)
    if a == b:
        return True
    try:
        if a and b and float(a) == float(b):
            return True
    except ValueError:
        pass
    if "," in a or "," in b:
        return sorted(x.strip() for x in a.split(",") if x.strip()) == sorted(x.strip() for x in b.split(",") if x.strip())
    return False


def _puerta_armar(E, p, **extra):
    """La respuesta de la puerta a partir del plan."""
    accion = "no_tocada"
    if p["ficha_id"] is not None and not p["detener"]:
        accion = "completada" if (p["escribir"] or E["otros"] or E["pantalla"]) else "sin_cambios"
    r = {"estado": p["estado"], "motivo": p["motivo"], "ficha_id": p["ficha_id"], "accion": accion,
         "valores": {k: dict(v) for k, v in p["valores"].items()}, "avisos": [dict(a) for a in p["avisos"]],
         "de": p["de"], "llave": p["llave"], "releida": None, "excepcion": None, "etapa": None, "rec": None,
         "escrito": sorted(p["escribir"])}
    if p.get("caso") is not None:
        r["caso"] = p["caso"]
    r.update(extra)
    return r


# Lo que el cálculo pone en lugar de un Id que la base todavía no asignó (un alta). La escritura lo cambia por el número real.
CALCULO_FICHA_NUEVA = "<nueva>"


def _puerta_escritura_personas(plan, E):
    """`(metodo, cuerpo)` de la escritura de la tabla de personas: lo que `_puerta_recibir` manda a NocoDB (POST si nace, PATCH si no).
    Lo usan la escritura y el cálculo: una sola forma del cuerpo."""
    cuerpo = dict(plan["escribir"], **E["otros"])
    if plan["crear"]:
        return "POST", {k: v for k, v in cuerpo.items() if v is not None}
    return "PATCH", dict(cuerpo, Id=plan["ficha_id"])


def _valores_de_bandeja(r):
    """Los resultados por valor tal como los guarda la bandeja: el cálculo los marca `guardaria`, y la escritura diría `guardado`."""
    return {k: ("guardado" if v["resultado"] in ("guardado", "guardaria") else v["resultado"]) for k, v in r["valores"].items()}


def _bandeja_fila(E, r, a, clave, accion):
    """La fila de la bandeja para un aviso (la misma que escribe `_puerta_apuntar_en_bandeja`, sin los nulos). `accion` es la que tiene
    la ficha DESPUÉS de escribir (`creada` si nació): el cálculo la pasa, la escritura la tiene en `r`."""
    L = E["L"]
    fila = {"clave": clave, "origen": E["origen"], "estado": "informativo" if a["informativo"] else "por_resolver",
            "tipo_aviso": a["tipo"], "ficha_id": a.get("ficha_id"), "otra_ficha_id": a.get("otra_ficha_id"),
            "resultado": json.dumps({"estado": r["estado"], "accion": accion, "valores": _valores_de_bandeja(r)}, sort_keys=True)}
    for campo in ("id_whatsapp", "telefono_meta", "telefono_dicho", "nombre", "nombre_perfil", "correo"):
        if L[campo][0] == "valor":
            fila[campo] = L[campo][1]
    return {k: v for k, v in fila.items() if v is not None}


def _puerta_bandeja_mandaria(E, r, avisos, accion):
    """Las filas que `_puerta_apuntar_en_bandeja` escribiría, en el mismo orden, sin escribirlas. Lee lo mismo que ella (la comprobación
    «ya está» de cada aviso); un aviso de una ficha que nace no puede estar ya, así que no se pregunta por él. Un aviso de ficha nueva
    lleva la clave `aviso-<nueva>` (su huella depende del número que asigna la base)."""
    tabla = _base.T_BANDEJA_PERSONAS
    out = []
    if not avisos or not tabla:
        return out
    base = f"/api/v2/tables/{tabla}/records"
    for a in avisos:
        if a.get("ficha_nueva") and a.get("ficha_id") is None:     # la misma regla que la escritura
            continue
        if a.get("ficha_id") == CALCULO_FICHA_NUEVA:
            clave = "aviso-" + CALCULO_FICHA_NUEVA
        else:
            clave = _puerta_clave_de_aviso(a, E)
            ya = _base.nc("GET", base, query={"where": f"(clave,eq,{clave})", "fields": "Id", "limit": 1})
            if isinstance(ya, dict) and ya.get("list"):
                continue
        out.append({"tabla": tabla, "metodo": "POST", "cuerpo": _bandeja_fila(E, r, a, clave, accion)})
    return out


def _puerta_recibir(E, solo_contar, antes_de_escribir):
    L, pantalla, fid = E["L"], E["pantalla"], E["ficha_id"]
    # Las CLASES de valor que este pedido trae con valor (una casilla vacía no choca con nada). `lee_la_ficha`: una pantalla edita una
    # ficha que ya existe; se lee, traiga o no casillas de identidad, para saber si está unida a otra y cómo está su casilla hermana.
    clases_con_valor = list(dict.fromkeys(cls for campo, _col, cls in PUERTA_CASILLAS if L[campo][0] == "valor"))
    lee_la_ficha = bool(pantalla and fid is not None)
    if pantalla:
        # Sin ficha (un alta) no hay nada que mirar en la ficha: todo valor se compara con las demás. Con ficha, `comparar`
        # se calcula dentro del candado, en cuanto se sabe cómo está ella hoy.
        comparar = [] if lee_la_ficha else clases_con_valor
        quiere_nombre = L["nombre"][0] == "valor" and fid is None
    else:
        comparar = [n for n, c in (("telefono", "telefono_meta"), ("telefono", "telefono_dicho"), ("correo", "correo"),
                                    ("id_whatsapp", "id_whatsapp")) if L[c][0] == "valor"]
        quiere_nombre = L["nombre"][0] == "valor"
        if not any(L[c][0] == "valor" for c in ("id_whatsapp", "telefono_meta", "telefono_dicho")):
            comparar, quiere_nombre = [], False      # sin ID ni teléfono el dato se rechaza: no hay nada que comparar
    comparar = list(dict.fromkeys(comparar))
    nacio = None                                  # el `Id` de la ficha que NACE en esta llamada (solo entonces se anota por dónde entró)
    # 🔑 EL CANDADO SE TOMA CUANDO HAY QUE DECIDIR SOBRE UNA CASILLA CON VALOR: una escritura de una casilla que la ficha ya tenía
    # también lo necesita —lo que decide es el valor de la ficha, y hay que leerlo y escribir sin que nadie se meta en medio—.
    # Una edición sin teléfono ni correo lee la ficha, pero sin el candado.
    with (_FICHA_TELEFONO_LOCK if (comparar or (lee_la_ficha and clases_con_valor)) else contextlib.nullcontext()), \
            (_candado_de_ficha(fid) if lee_la_ficha else contextlib.nullcontext()):
        actual = None
        if lee_la_ficha:
            try:
                actual = _puerta_leer_la_ficha(fid)
            except _base.SoloLectura:
                raise
            except Exception as e:                   # noqa: BLE001
                print(f"[warn] puerta de fichas: no se pudo leer la ficha que se iba a tocar ({type(e).__name__})")
                return {"estado": "sin_confirmar", "motivo": "no_se_pudo_comprobar", "ficha_id": fid, "accion": "no_tocada",
                        "valores": {}, "avisos": [], "de": None, "llave": None, "releida": None, "excepcion": e,
                        "etapa": "lectura", "rec": None, "escrito": [], "comprobaba": sorted(set(clases_con_valor))}
            if ficha_fuera(actual):
                p = _puerta_plan(fid, False)
                p["estado"], p["motivo"], p["detener"] = "rechazado", ("quitada" if ficha_quitada(actual) else "unida"), True
                return _puerta_armar(E, p)
            comparar = _puerta_que_comparar(E, actual)
        filas = None
        if comparar or quiere_nombre:
            try:
                filas = _leer_fichas_de_la_puerta()
            except _base.SoloLectura:
                raise
            except Exception as e:                   # noqa: BLE001
                print(f"[warn] puerta de fichas: no se pudo leer las fichas ({type(e).__name__})")
                if comparar:
                    return {"estado": "sin_confirmar", "motivo": "no_se_pudo_comprobar", "ficha_id": fid, "accion": "no_tocada",
                            "valores": {}, "avisos": [], "de": None, "llave": None, "releida": None, "excepcion": e,
                            "etapa": "lectura", "rec": None, "escrito": [], "comprobaba": comparar}
        plan = _puerta_decidir_explicito(E, filas, actual) if pantalla else _puerta_decidir_automatico(E, filas if filas is not None else [])
        if solo_contar:
            # 🔑 EL CÁLCULO: recorre lo mismo que la escritura (la misma decisión, el mismo `antes_de_escribir`) y dice lo que MANDARÍA
            # a NocoDB, en `mandaria`, sin mandarlo. Ningún `_base.nc` de escritura se llama desde aquí (las lecturas sí).
            r = _puerta_armar(E, plan, solo_contar=True, crearia=bool(plan["crear"] and not plan["detener"]))
            for v in r["valores"].values():
                if v["resultado"] == "guardado":
                    v["resultado"] = "guardaria"
            r["mandaria"] = []
            if plan["detener"]:
                return r
            if antes_de_escribir is not None:
                parada = antes_de_escribir(_puerta_armar(E, plan))
                if parada:
                    return _puerta_armar(E, plan, estado="detenido", respuesta=parada)
            if not (plan["escribir"] or E["otros"] or (pantalla and fid is not None)):
                return r
            metodo, cuerpo = _puerta_escritura_personas(plan, E)
            r["mandaria"].append({"tabla": _base.T_PERSONAS, "metodo": metodo, "cuerpo": cuerpo})
            if plan["crear"] and (_base.T_PERSONAS_ANOTACIONES or "").strip():
                r["mandaria"].append(_origen_escritura(CALCULO_FICHA_NUEVA, E["origen"]))
            return r
        if plan["detener"]:
            return _puerta_armar(E, plan)
        if antes_de_escribir is not None:
            parada = antes_de_escribir(_puerta_armar(E, plan))
            if parada:
                return _puerta_armar(E, plan, estado="detenido", respuesta=parada)
        r = _puerta_armar(E, plan)
        if not (plan["escribir"] or E["otros"] or (pantalla and fid is not None)):
            return r
        metodo, cuerpo = _puerta_escritura_personas(plan, E)
        try:
            rec = _base.nc(metodo, f"/api/v2/tables/{_base.T_PERSONAS}/records", body=cuerpo)
        except _base.SoloLectura:
            raise
        except Exception as e:                       # noqa: BLE001
            rechazo = isinstance(e, _base.ErrorDeNocodb) and e.status < 500
            print(f"[warn] puerta de fichas: la base {'no aceptó' if rechazo else 'falló al guardar'} "
                  f"({e.status if isinstance(e, _base.ErrorDeNocodb) else type(e).__name__})")
            for v in r["valores"].values():
                if v["resultado"] == "guardado":
                    v.update(resultado="no_guardado" if rechazo else "sin_confirmar", motivo="base_rechazo" if rechazo else "base_fallo")
            r.update(estado="sin_confirmar", motivo="base_rechazo" if rechazo else "base_fallo", excepcion=e, etapa="escritura",
                     accion="no_tocada" if rechazo else r["accion"])
            return r
        if plan["crear"]:
            nuevo = rec.get("Id") if isinstance(rec, dict) else None
            if isinstance(nuevo, bool) or not isinstance(nuevo, int):
                for v in r["valores"].values():
                    if v["resultado"] == "guardado":
                        v.update(resultado="sin_confirmar", motivo="sin_id")
                r.update(estado="sin_confirmar", motivo="sin_id", etapa="escritura", rec=rec, accion="creada")
                print("[warn] puerta de fichas: la base no confirmó el alta (sin Id)")   # S2: no se calla, ni en el reloj
                anotar_origen_al_nacer(None, E["origen"])      # sin `Id` no hay a quién anotar; solo deja su línea de registro (no toca la red)
                return r
            plan["ficha_id"] = r["ficha_id"] = nuevo
            nacio = nuevo
            r["accion"] = "creada"
            for a in r["avisos"]:
                if a["ficha_id"] is None:
                    a.update(_puerta_aviso(a["tipo"], nuevo, a["otra_ficha_id"]))
        r["rec"] = rec
        invalidate_personas()
    # Fuera del candado, ANTES de releer (una relectura que falla no puede dejar sin anotar a la ficha que ya nació): si la ficha NACIÓ en esta
    # llamada, el sistema anota por dónde entró (`anotar_origen_al_nacer`; nunca levanta y nunca cambia lo que contesta la puerta).
    if nacio is not None:
        anotar_origen_al_nacer(nacio, E["origen"])
    # Fuera del candado: se RELEE la fila, y el resultado de cada valor sale de lo releído.
    cols = ["Id"] + list(plan["escribir"]) + list(E["otros"]) + [c for c in E["releer"].split(",") if c]
    try:
        releida = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(plan['ficha_id'])}",
                       query={"fields": ",".join(dict.fromkeys(cols))})
        if not isinstance(releida, dict):
            raise ValueError("la relectura no es una fila")
    except _base.SoloLectura:
        raise
    except Exception as e:                           # noqa: BLE001
        print(f"[warn] puerta de fichas: se escribió y no se pudo releer ({type(e).__name__})")
        for v in r["valores"].values():
            if v["resultado"] == "guardado":
                v.update(resultado="sin_confirmar", motivo="sin_releer")
        r.update(estado="sin_confirmar", motivo="sin_releer", excepcion=e, etapa="relectura")
        return r
    r["releida"] = releida
    al_reves = {PUERTA_COLUMNA[k]: k for k in PUERTA_COLUMNA}
    mal = []
    for col, escrito in plan["escribir"].items():
        if not _puerta_coincide(col, escrito, releida.get(col)):
            mal.append(col)
            clave = plan["claves"].get(col) or ("telefono_dicho" if (col == "telefono" and "telefono_dicho" in r["valores"] and "telefono" not in r["valores"]) else al_reves[col])
            if clave in r["valores"] and r["valores"][clave]["resultado"] == "guardado":
                r["valores"][clave].update(resultado="sin_confirmar", motivo="no_coincide")
    # 🔑 `otros` TAMBIÉN se compara con lo releído (antes solo se miraba `plan["escribir"]`, o sea la identidad: un PATCH que la base dijo
    # «sí» y no aplicó a Instagram, notas o `Posible_proveedor` salía como «guardado»). Si algo no coincide la puerta NO confirma.
    mal_otros = [c for c, v in E["otros"].items() if not _puerta_otro_coincide(v, releida.get(c))]
    if mal_otros:
        print(f"[warn] puerta de fichas: lo releído no es lo escrito en otros ({','.join(mal_otros)})")
        mal = mal + mal_otros
    if mal:
        print(f"[warn] puerta de fichas: lo releído no es lo escrito ({','.join(mal)})")
        r.update(estado="sin_confirmar", motivo="no_coincide", etapa="relectura")
    return r


def _puerta_clave_de_aviso(a, E):
    """Qué hace igual a un aviso con otro: tipo, fichas y el valor que lo causó. Va hasheado y SIN SAL: la clave no deja el valor a la
    vista, pero ES su huella — quien tenga las fichas puede recalcularla y emparejarla. No es una garantía de privacidad."""
    L = E["L"]
    valor = "|".join(str(L[c][1]) for c in ("id_whatsapp", "telefono_meta", "telefono_dicho", "nombre", "correo") if L[c][0] == "valor")
    crudo = "|".join([a["tipo"], str(a.get("ficha_id")), str(a.get("otra_ficha_id")), valor])
    return "aviso-" + hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:40]


def _puerta_apuntar_en_bandeja(E, r):
    """Una fila de la bandeja por aviso (un aviso abierto igual se reusa). NUNCA levanta ni cambia lo que ya se escribió: sin la
    variable de la tabla, o con la bandeja caída, el aviso sale en la respuesta y en una línea de registro, y `apuntado` es falso."""
    for a in r["avisos"]:
        a["apuntado"] = False
    if not r["avisos"]:
        return
    tabla = _base.T_BANDEJA_PERSONAS
    if not tabla:
        return
    base = f"/api/v2/tables/{tabla}/records"
    L = E["L"]
    try:
        for a in r["avisos"]:
            if a.get("ficha_nueva") and a.get("ficha_id") is None:     # la ficha no se confirmó: no se apunta un aviso de una ficha sin Id
                continue
            clave = _puerta_clave_de_aviso(a, E)
            ya = _base.nc("GET", base, query={"where": f"(clave,eq,{clave})", "fields": "Id", "limit": 1})
            if isinstance(ya, dict) and ya.get("list"):
                a["apuntado"] = True
                continue
            _base.nc("POST", base, body=_bandeja_fila(E, r, a, clave, r["accion"]))
            a["apuntado"] = True
    except _base.SoloLectura:
        raise
    except Exception as e:                           # noqa: BLE001
        print(f"[warn] puerta de fichas: la bandeja no contestó ({type(e).__name__}); el aviso sale en la respuesta")


# Lo marca el reloj de contactos de Google (P6, `google_contactos.correr_una_vez`) en SU hilo: con el flag puesto, la puerta no
# imprime su línea `[PUERTA-FICHAS]` por contacto. Es `threading.local`: los demás hilos de la App siguen igual.
SILENCIO_PUERTA_REGISTRO = threading.local()


def _puerta_registrar(origen, r):
    """UNA línea de registro por llamada: de dónde vino, qué pasó y a qué ficha. NUNCA lleva datos de la persona.
    En el hilo del reloj de contactos de Google (`SILENCIO_PUERTA_REGISTRO.activo`) no imprime esta línea: la corrida deja su
    línea de resumen. Los `[warn] puerta de fichas` de un fallo de la base NO se callan: salen igual en esa corrida."""
    if getattr(SILENCIO_PUERTA_REGISTRO, "activo", False):
        return
    print("[PUERTA-FICHAS] origen=%s estado=%s motivo=%s accion=%s ficha_id=%s avisos=%s apuntados=%s" % (
        origen, r["estado"], r["motivo"] or "-", r["accion"], r["ficha_id"],
        ",".join(a["tipo"] for a in r["avisos"]) or "-", sum(1 for a in r["avisos"] if a.get("apuntado"))))


def calculo_de_escrituras(escrituras, codigo):
    """La respuesta de un cálculo que NO rechaza: el código que daría la escritura y lo que mandaría a NocoDB (nada se manda)."""
    return codigo, {"ok": True, "estado": "calculado", "escrituras": escrituras}


def _nc_o_plan(solo_contar, planeados, metodo, tabla, body):
    """Una escritura de NocoDB de los grupos (e) de P11-6 (resolver, reabrir, borrar, devolver). Sin `solo_contar` es la escritura de siempre.
    Con `solo_contar` no sale a la red: lo que mandaría queda en `planeados`, en su orden, y la función sigue como si hubiera salido bien."""
    if solo_contar:
        planeados.append({"tabla": tabla, "metodo": metodo, "cuerpo": body})
        return None
    return _base.nc(metodo, f"/api/v2/tables/{tabla}/records", body=body)


def recibir(dato, solo_contar=False, antes_de_escribir=None):
    """🔑 LA PUERTA: todo dato de una persona entra por aquí. Ver el bloque de arriba (las cuatro reglas y las dos formas de llegar).

    `dato` (solo estas claves; otra cosa se rechaza sin escribir): `origen`; `pantalla` (True = una persona escribió esto en una ficha);
    `ficha_id` (la ficha que esa pantalla edita; sin él, una ficha nueva); `id_whatsapp`, `telefono_meta`, `telefono_dicho`, `nombre`,
    `nombre_perfil`, `correo`, y —como dato de entrada, **solo con `pantalla`**— las dos casillas nuevas `telefono_2` y `correo_2`; `clave` (reservada para
    quien entregue datos de otro sistema); y lo que la puerta no decide: `otros` ({columna: valor} que la pantalla ya validó; NO puede
    traer columnas de identidad), `releer` (columnas de más que quiere de vuelta), `telefono_sin_forma_ok` (solo el check-in).
    **La ficha que se va a tocar NO se manda: la lee la puerta** (`_puerta_leer_la_ficha`), y una `fila_actual` en el dato se rechaza
    como cualquier clave que la puerta no conoce.
    `solo_contar=True` decide y dice qué haría, sin escribir nada. `antes_de_escribir(plan)` corre DENTRO del candado, tras decidir
    y antes de escribir; si devuelve algo, no se escribe y la respuesta lo trae en `respuesta` (`estado` «detenido»).

    Contesta (todo se puede leer en el diccionario): `estado` (aplicado | por_resolver | rechazado | sin_confirmar | detenido),
    `motivo`, `ficha_id`, `accion` (creada | completada | sin_cambios | no_tocada), `valores` (por cada valor recibido:
    `resultado` guardado | ya_estaba | no_guardado | sin_confirmar y su `motivo`; un `guardado` dice `en principal` o `en secundario`),
    `avisos`, `de`, `releida` (la fila releída; no es para sacarla del servidor), `excepcion`/`etapa` (si algo falló, para quien quiera
    repetirla) y `escrito` (las columnas)."""
    try:
        E = _puerta_leer_entrada(dato)
    except _PuertaIlegible as e:
        r = {"estado": "rechazado", "motivo": str(e), "ficha_id": None, "accion": "no_tocada", "valores": {}, "avisos": [],
             "de": None, "llave": None, "releida": None, "excepcion": None, "etapa": None, "rec": None, "escrito": []}
        _puerta_registrar(dato.get("origen") if isinstance(dato, dict) and dato.get("origen") in PUERTA_ORIGENES else "desconocido", r)
        return r
    r = _puerta_recibir(E, solo_contar, antes_de_escribir)
    if not solo_contar and r["estado"] not in ("rechazado", "detenido"):
        _puerta_apuntar_en_bandeja(E, r)
    elif solo_contar and r["estado"] not in ("rechazado", "detenido"):
        # Lo que la escritura apuntaría en la bandeja. Si la ficha nace, sus avisos llevan el número que la base asigna (la marca
        # `<nueva>`) y su acción es `creada`: calculado aquí, sin tocar lo que `r` contesta a quien llama.
        crea = any(e["metodo"] == "POST" and e["tabla"] == _base.T_PERSONAS for e in r.get("mandaria", []))
        avisos = [dict(a, **_puerta_aviso(a["tipo"], CALCULO_FICHA_NUEVA, a["otra_ficha_id"])) if
                  (crea and a["ficha_id"] is None) else a for a in r["avisos"]]
        r["mandaria"] = r.get("mandaria", []) + _puerta_bandeja_mandaria(E, r, avisos, "creada" if crea else r["accion"])
    _puerta_registrar(E["origen"], r)
    return r


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# «POR RESOLVER» (parte 3 del diseño `disenos/registro-dueno-de-las-fichas/`): las fichas que parecen la misma persona.
#
# 🔑 LA LISTA NO SE GUARDA: se CALCULA de las fichas cada vez que se abre, con las MISMAS reglas de la puerta (`clave_correo` y
# `clave_nombre`, ninguna regla aparte). La bandeja guarda SOLO lo que alguien decidió: una fila `resuelto-…` por renglón
# marcado, con quién y cuándo. Así no hay segunda copia de «quiénes son duplicados» que se pueda descuadrar, y lo que se marcó
# no vuelve a salir aunque la puerta vuelva a ver lo mismo (la puerta no lee estas filas ni las escribe: su `clave` empieza
# distinto y su `origen` es otro).
#   · Un renglón es un GRUPO: todas las fichas que comparten el mismo correo (o el mismo nombre completo), dos o más.
#   · Su `clave` = hash de (tipo, ids de las fichas del grupo, valor compartido). Si entra una ficha más al grupo, o cambia el
#     valor, la clave es otra y el renglón vuelve a salir: lo marcado era de ESE grupo.
#     ⚠️ La clave va hasheada y SIN SAL: no deja el valor a la vista, pero ES la huella de ese valor (un correo o un nombre completo, que
#     tienen poca entropía) — quien tenga las fichas puede recalcularla y emparejarla. NO es una garantía de privacidad: la fila de la
#     bandeja lleva esa huella, no el valor en claro, y eso es todo lo que se puede decir.
#   · «Resolver» solo marca (estado `resuelto`, `resuelto_por`, `resuelto_en`): no toca ninguna ficha. Unir y desligar son las
#     partes 4 y 5. «Reabrir» devuelve el estado a `por_resolver` (la fila no se borra; `resuelto_por/en` quedan como la última marca).
#   · Los avisos que la puerta apunta en la bandeja (`aviso-…`) también salen aquí (`_por_resolver_leer_avisos`); marcar uno cambia el `estado` de su fila a `resuelto`.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
POR_RESOLVER_ORIGEN = "por-resolver"
# (tipo, columnas de `personas` donde vive el valor —una o dos: el correo se mira en las DOS casillas, la principal y la
#  secundaria—, regla de la puerta, frase del renglón). Una ficha puede caer en dos grupos de correo, uno por cada casilla.
POR_RESOLVER_TIPOS = (
    ("mismo_correo", ("email", "email_2"), clave_correo, "Tienen el mismo correo"),
    ("mismo_nombre", ("nombre",), clave_nombre, "Se llaman igual"),
)
RE_CLAVE_POR_RESOLVER = re.compile(r"resuelto-[0-9a-f]{40}")
_POR_RESOLVER_LOCK = threading.Lock()          # el proceso es uno solo (`Procfile`): dos marcas a la vez no crean dos filas
POR_RESOLVER_SIN_BANDEJA = ("No se puede marcar nada ahora: falta conectar la bandeja de avisos. "
                            "La lista se ve, pero no se sabe qué estaba ya resuelto.")
POR_RESOLVER_BANDEJA_CAIDA = ("No se pudo leer lo que ya se marcó como resuelto: puede que alguno de estos renglones ya lo estuviera. "
                              "Por ahora no se puede marcar nada. Inténtalo en un momento.")


def _celda_texto(v):
    """Una celda de `personas` lista para mostrar: texto sin espacios en los bordes; lo que no es texto ni número, vacío."""
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, (int, float)):
        return str(v)
    return " ".join(v.split()) if isinstance(v, str) else ""


def _por_resolver_ficha(i, f):
    """Las celdas de una ficha que «Por resolver» enseña."""
    return {"id": i, "nombre": _celda_texto(f.get("nombre")), "telefono": _celda_texto(f.get("telefono")),
            "telefono_2": _celda_texto(f.get("telefono_2")),
            "correo": _celda_texto(f.get("email")), "correo_2": _celda_texto(f.get("email_2")),
            "instagram": _celda_texto(f.get("instagram")),
            "visitas": _celda_texto(f.get("Visitas")),
            "ultima_visita": _celda_texto(f.get("Ultima_visita"))}


def por_resolver_grupos(filas):
    """Los grupos de fichas que parecen la misma persona, calculados de `filas` (cada una con `Id`, `nombre`, `email`, …) con
    las reglas de la puerta. Cada grupo: `clave`, `tipo`, `titulo`, `valor`, `buscar`, `ids` y `fichas`. Determinista: primero los
    de correo, luego los de nombre, y dentro de cada tipo por el número de ficha más bajo.

    Un valor se busca en TODAS las columnas de su tipo (`POR_RESOLVER_TIPOS`): el correo, en la casilla principal y en la
    secundaria. Una ficha con dos correos distintos puede salir en dos grupos, uno por cada uno."""
    por_id = {}
    for f in filas:
        i = f.get("Id") if isinstance(f, dict) else None
        if isinstance(i, int) and not isinstance(i, bool) and i not in por_id:
            por_id[i] = f
    grupos = []
    for tipo, campos, regla, titulo in POR_RESOLVER_TIPOS:
        por_valor = {}
        for i in sorted(por_id):
            for campo in campos:
                k = regla(por_id[i].get(campo))
                if not k:
                    continue
                grupo = por_valor.setdefault(k, {"ids": [], "valor": _celda_texto(por_id[i].get(campo))})
                if i not in grupo["ids"]:
                    grupo["ids"].append(i)
        for k, grupo in sorted(por_valor.items(), key=lambda kv: kv[1]["ids"][0]):
            ids = grupo["ids"]
            if len(ids) < 2:
                continue
            crudo = "|".join([tipo, ",".join(str(i) for i in ids), k])
            valor = grupo["valor"]
            grupos.append({
                "clave": "resuelto-" + hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:40], "tipo": tipo, "titulo": titulo,
                "valor": valor, "buscar": valor, "ids": ids,
                "fichas": [_por_resolver_ficha(i, por_id[i]) for i in ids]})
    return grupos


def _por_resolver_tabla():
    """La tabla de la bandeja (`''` si no está conectada). Es la única forma en que «Por resolver» llega a la variable `T_BANDEJA_PERSONAS`."""
    return _base.T_BANDEJA_PERSONAS


def _por_resolver_leer_marcas():
    """Lo que alguien decidió: `(estado, {clave: {"Id", "estado", "resuelto_por", "resuelto_en"}})`. `estado` = `ok`,
    `sin_configurar` (no hay variable de la tabla) o `no_contesto` (la bandeja falló o contestó algo que no se entiende): en los dos
    últimos NO se sabe qué estaba resuelto y quien llama no lo da por sabido. Si hay dos filas con la misma clave manda la de `Id` más alto."""
    tabla = _por_resolver_tabla()
    if not tabla:
        return "sin_configurar", {}
    try:
        filas = _base.nc_list_all(tabla, {"where": f"(origen,eq,{POR_RESOLVER_ORIGEN})",
                                      "fields": "Id,clave,estado,resuelto_por,resuelto_en"})
    except _base.SoloLectura:
        raise
    except Exception as e:                           # noqa: BLE001
        print(f"[warn] por resolver: la bandeja no contestó ({type(e).__name__})")
        return "no_contesto", {}
    if not isinstance(filas, list):
        return "no_contesto", {}
    marcas = {}
    for f in filas:
        if not isinstance(f, dict) or not isinstance(f.get("clave"), str) or not isinstance(f.get("Id"), int):
            continue
        antes = marcas.get(f["clave"])
        if antes is None or f["Id"] > antes["Id"]:
            marcas[f["clave"]] = {"Id": f["Id"], "estado": f.get("estado"), "resuelto_por": f.get("resuelto_por"),
                                  "resuelto_en": f.get("resuelto_en")}
    return "ok", marcas


RE_CLAVE_AVISO = re.compile(r"aviso-[0-9a-f]{40}")
PUERTA_AVISO_ESTADOS = ("informativo", "por_resolver")
POR_RESOLVER_AVISOS_CAIDOS = "No se pudieron leer los avisos de la entrada. Lo demás de esta lista sí se ve."
POR_RESOLVER_AVISOS_TOPE_FRASE = "Hay más avisos de la entrada de los que se muestran aquí."
POR_RESOLVER_AVISOS_TOPE = 100
POR_RESOLVER_AVISOS_CAMPOS = "Id,clave,estado,origen,tipo_aviso,ficha_id,otra_ficha_id,CreatedAt"


def _es_aviso_de_la_puerta(f):
    """¿La puerta escribió esta fila de la bandeja como un aviso? Lo dicen su clave, su origen y su tipo."""
    return (isinstance(f, dict) and isinstance(f.get("Id"), int) and isinstance(f.get("clave"), str) and RE_CLAVE_AVISO.fullmatch(f["clave"]) is not None
            and f.get("origen") in PUERTA_ORIGENES and isinstance(f.get("tipo_aviso"), str) and f["tipo_aviso"] != "")


def _es_aviso_abierto(f):
    """¿Es un aviso de la puerta que nadie ha marcado?"""
    return _es_aviso_de_la_puerta(f) and f.get("estado") in PUERTA_AVISO_ESTADOS


def _por_resolver_leer_avisos():
    """Los avisos de la puerta sin marcar y cómo salió la lectura (`ok`, `incompleto`, `sin_configurar` o `no_contesto`)."""
    if not _por_resolver_tabla():
        return "sin_configurar", []
    por_clave = {}

    def visitar(_estado, f):
        if _es_aviso_abierto(f):
            por_clave[f["clave"]] = f
    try:
        completo = _base._bandeja_leer(PUERTA_AVISO_ESTADOS, POR_RESOLVER_AVISOS_CAMPOS, visitar, 200, POR_RESOLVER_AVISOS_TOPE)
    except _base.SoloLectura:
        raise
    except Exception as e:                           # noqa: BLE001
        print(f"[warn] por resolver: los avisos de la entrada no se pudieron leer ({type(e).__name__})")
        return "no_contesto", []
    return ("ok" if completo else "incompleto"), sorted(por_clave.values(), key=lambda f: f["Id"])


def _entero_o_nada(v):
    return v if isinstance(v, int) else None


def _por_resolver_aviso_de(fila):
    """El aviso de una fila de la bandeja tal como lo cuenta la puerta (`_puerta_aviso`). Un tipo que no está en `PUERTA_AVISOS`, o al que le
    falta el número de ficha que su frase nombra, sale «sin clasificar» (y por eso rojo: lo que no se sabe leer cae del lado estricto)."""
    tipo = _celda_texto(fila.get("tipo_aviso"))
    ficha, otra = _entero_o_nada(fila.get("ficha_id")), _entero_o_nada(fila.get("otra_ficha_id"))
    plantilla = PUERTA_AVISOS.get(tipo, (False, ""))[1]
    falta = (not plantilla) or ("{ficha}" in plantilla and ficha is None) or ("{otra}" in plantilla and otra is None)
    return _puerta_aviso("" if falta else tipo, ficha, otra)


def _por_resolver_aviso_es_rojo(fila):
    """¿Espera por Tiziano? Es la única regla del color: la usan el renglón y el marcado."""
    return not _por_resolver_aviso_de(fila)["informativo"]


def _por_resolver_renglon_aviso(fila, por_id):
    """El renglón de un aviso de la puerta, con su color, su frase, las fichas que nombra y lo que se le puede hacer (`deshacer`, `unir`)."""
    tipo = _celda_texto(fila.get("tipo_aviso"))
    ids = [i for i in (_entero_o_nada(fila.get("ficha_id")), _entero_o_nada(fila.get("otra_ficha_id"))) if i is not None]
    aviso = _por_resolver_aviso_de(fila)
    rojo = not aviso["informativo"]
    fichas = []
    for i in ids:
        if i in por_id:
            ficha = _por_resolver_ficha(i, por_id[i])
            ficha["buscar"] = ficha["nombre"] or ficha["telefono"] or ficha["correo"]
            fichas.append(ficha)
    quedo = _entero_o_nada(fila.get("ficha_id"))
    # `deshacer`: la ficha que quedó, si el aviso es de una unión y esa ficha está en la lista (si no, no hay de dónde deshacer).
    sobro = _entero_o_nada(fila.get("otra_ficha_id"))
    deshacer = quedo if (not rojo and tipo in PUERTA_AVISOS_DE_UNION and quedo in por_id and sobro is not None) else None
    return {"clave": fila["clave"], "tipo": tipo, "color": "rojo" if rojo else "amarillo", "frase": aviso["texto"],
            "ids": ids, "fichas": fichas, "cuando": _celda_texto(fila.get("CreatedAt")),
            "deshacer": deshacer, "deshacer_sobra": sobro if deshacer is not None else None, "unir": rojo and bool(fichas)}


def _por_resolver_avisos_de_la_puerta(por_id):
    """Los renglones de los avisos de la puerta sin marcar, rojos primero, y la frase de aviso si no se pudieron leer."""
    estado, filas = _por_resolver_leer_avisos()
    renglones = [_por_resolver_renglon_aviso(f, por_id) for f in filas]
    renglones.sort(key=lambda r: r["color"] != "rojo")
    return renglones, {"no_contesto": POR_RESOLVER_AVISOS_CAIDOS, "incompleto": POR_RESOLVER_AVISOS_TOPE_FRASE}.get(estado, "")


def portal_por_resolver():
    """La pantalla «Por resolver»: lo que falta decidir, lo ya marcado y los avisos de la puerta; levanta `PortalNoCargo` si las fichas no cargan."""
    filas = [p["publica"] for p in portal_personas_todas()]
    estado_bandeja, marcas = _por_resolver_leer_marcas()
    abiertos, resueltos = [], []
    for g in por_resolver_grupos(filas):
        m = marcas.get(g["clave"])
        if m and m["estado"] == "resuelto":
            resueltos.append(dict(g, resuelto_por=_celda_texto(m["resuelto_por"]), resuelto_en=_celda_texto(m["resuelto_en"])))
        else:
            abiertos.append(g)
    aviso = {"ok": "", "sin_configurar": POR_RESOLVER_SIN_BANDEJA, "no_contesto": POR_RESOLVER_BANDEJA_CAIDA}[estado_bandeja]
    avisos_puerta, avisos_puerta_aviso = _por_resolver_avisos_de_la_puerta({f["Id"]: f for f in filas if isinstance(f.get("Id"), int)})
    return {"ok": True, "bandeja": estado_bandeja, "se_puede_marcar": estado_bandeja == "ok", "aviso": aviso,
            "abiertos": abiertos, "resueltos": resueltos, "fichas_leidas": len(filas),
            "avisos_puerta": avisos_puerta, "avisos_puerta_aviso": avisos_puerta_aviso}


def _ahora_utc():
    """La hora de una marca, en UTC y con su desfase escrito (así la guarda la columna `DateTime` de la bandeja)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _por_resolver_sin_confirmar():
    return 502, {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True,
                 "error": "No se pudo confirmar si quedó guardado. NO lo des por hecho: abre «Por resolver» de nuevo y míralo antes de repetirlo."}


def _por_resolver_rojo_sin_confirmar():
    """LA RESPUESTA ÚNICA de un rojo que no quedó confirmado como marcado, sea por lo que sea. Lleva siempre `datos_sin_saber: true` (la pantalla dice siempre la
    misma frase) y nunca afirma que no se escribió nada: antes de fallar pudieron volver datos de la entrada a la cola."""
    return 502, {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "datos_sin_saber": True,
                 "error": "El renglón no quedó confirmado como marcado. Abre «Por resolver» y míralo antes de repetirlo."}


POR_RESOLVER_DATO_CAMPOS = "Id,clave,estado,origen,tipo_aviso,ficha_id,otra_ficha_id"


def _es_fila_de_dato_por_resolver(f):
    """¿Es una fila de DATO de la entrada (la que escribió Natalia y la App apuntó) que quedó esperando? Su `origen` es uno de los de la entrada y
    no lleva tipo de aviso: así no se confunde con un aviso de la puerta, una marca de «Por resolver» ni un apunte «no son la misma»."""
    return (isinstance(f, dict) and isinstance(f.get("Id"), int) and f.get("estado") == "por_resolver" and f.get("origen") in _base.ENTRADA_ORIGENES
            and not (isinstance(f.get("tipo_aviso"), str) and f["tipo_aviso"] != "") and not _es_aviso_de_la_puerta(f))


def _por_resolver_filas_de_dato(fichas):
    """Las filas de dato `por_resolver` que nombran alguna de esas fichas (`ficha_id` u `otra_ficha_id`), por `Id`; levanta si la lectura no fue completa."""
    halladas = {}

    def visitar(_estado, f):
        nombradas = {n for n in (f.get("ficha_id"), f.get("otra_ficha_id")) if isinstance(n, int) and not isinstance(n, bool)} if isinstance(f, dict) else set()
        if _es_fila_de_dato_por_resolver(f) and nombradas & fichas:
            halladas[f["Id"]] = f
    if not _base._bandeja_leer(("por_resolver",), POR_RESOLVER_DATO_CAMPOS, visitar, 200, POR_RESOLVER_AVISOS_TOPE):
        raise ValueError("la lectura de la bandeja no llegó al final")
    return halladas


def _por_resolver_devolver_datos(fichas, solo_contar=False, planeados=None):
    """Pone en `pendiente` las filas de dato `por_resolver` de esas fichas y las vuelve a leer. Devuelve cuántas volvieron, o `None` si algo no se
    pudo leer, escribir o confirmar (nunca dice que volvieron sin haberlo releído). Lo que se levante sube: la puerta del rojo (`_por_resolver_marcar_aviso`) lo trata.
    Con `solo_contar` (P11-6e) no escribe ni relee: pone en `planeados` lo que volvería a `pendiente` y devuelve cuántas filas son."""
    filas = _por_resolver_filas_de_dato(fichas)
    for i in sorted(filas):
        _nc_o_plan(solo_contar, planeados, "PATCH", _por_resolver_tabla(), body={"Id": i, "estado": "pendiente"})
    if solo_contar:
        return len(filas)
    if filas and set(_por_resolver_filas_de_dato(fichas)) & set(filas):
        return None
    return len(filas)


def _por_resolver_marcar_aviso(clave, quien, vale=None, solo_contar=False, planeados=None):
    """Marca como resuelta la fila de aviso de la puerta con esa clave; devuelve `(código, datos)`.
    `vale` (opcional): función que dice si una fila de ese aviso es de lo que se hizo (la usa `marcar_aviso_de_la_union`); si alguna fila no vale, no se marca
    nada y contesta 409 `no_es_de_esta_union`. Sin `vale` se porta como siempre (el botón «Visto» / «Resuelto»)."""
    tabla = _por_resolver_tabla()
    if not tabla:
        return 503, {"ok": False, "error": POR_RESOLVER_SIN_BANDEJA}
    quien = _celda_texto(quien)
    base = f"/api/v2/tables/{tabla}/records"

    def leer():
        pagina = _base.nc("GET", base, query={"where": f"(clave,eq,{clave})", "fields": "Id,clave,estado,origen,tipo_aviso,ficha_id,otra_ficha_id", "limit": 200})
        lista = pagina.get("list") if isinstance(pagina, dict) else None
        return [f for f in lista if _es_aviso_de_la_puerta(f)]

    with _POR_RESOLVER_LOCK:
        try:
            filas = leer()
        except _base.SoloLectura:
            raise
        except Exception as e:                       # noqa: BLE001
            print(f"[warn] por resolver: la bandeja no contestó ({type(e).__name__})")
            return 502, {"ok": False, "error": POR_RESOLVER_BANDEJA_CAIDA}
        if vale is not None and not all(vale(f) for f in filas):
            return 409, {"ok": False, "estado": "no_es_de_esta_union",
                         "error": "Ese aviso no es de esta unión, así que no se marcó."}
        abiertas = [f for f in filas if _es_aviso_abierto(f)]
        if not abiertas:
            if any(f.get("estado") == "resuelto" for f in filas):
                return 200, {"ok": True, "estado": "resuelto", "ya_estaba": True, "clave": clave}
            return 409, {"ok": False, "estado": "ya_no_aplica",
                         "error": "Ese renglón ya no existe: las fichas cambiaron. Abre «Por resolver» de nuevo."}
        # Un rojo que se resuelve devuelve a la cola los datos de la entrada que esperaban por él. Va ANTES de marcar el aviso: si no se
        # confirma, el renglón sigue en la lista y se puede volver a pulsar.
        fichas = {n for f in abiertas if _por_resolver_aviso_es_rojo(f) for n in (f.get("ficha_id"), f.get("otra_ficha_id")) if isinstance(n, int) and not isinstance(n, bool)}

        def terminar():
            volvieron = _por_resolver_devolver_datos(fichas, solo_contar, planeados) if fichas else 0
            if volvieron is None:
                return _por_resolver_sin_confirmar()
            try:
                for f in abiertas:
                    _nc_o_plan(solo_contar, planeados, "PATCH", tabla, body={"Id": f["Id"], "estado": "resuelto", "resuelto_por": quien, "resuelto_en": _ahora_utc()})
            except _base.SoloLectura:
                raise
            except Exception as e:                       # noqa: BLE001
                print(f"[warn] por resolver: no se pudo escribir en la bandeja ({type(e).__name__})")
                return _por_resolver_sin_confirmar()
            if solo_contar:                              # (P11-6e) no se relee: lo que se planeó es lo que quedaría
                return 200, {"ok": True, "estado": "resuelto", "ya_estaba": False, "clave": clave, "filas_de_dato": volvieron}
            try:
                releidas = leer()
            except _base.SoloLectura:
                raise
            except Exception:                            # noqa: BLE001
                return _por_resolver_sin_confirmar()
            if any(_es_aviso_abierto(f) for f in releidas) or not any(f.get("estado") == "resuelto" for f in releidas):
                return _por_resolver_sin_confirmar()
            return 200, {"ok": True, "estado": "resuelto", "ya_estaba": False, "clave": clave, "filas_de_dato": volvieron}

        if not fichas:
            return terminar()
        # 🔑 LA PUERTA DEL ROJO. Todo intento de marcar un rojo que nombra fichas pasa por aquí, venga del botón «Resuelto» o de unir. Se decide mirando el
        # RESULTADO, no la clase del fallo ni el paso en que ocurrió (no hay lista de casos): si no es el marcado confirmado —una excepción de cualquier
        # tipo, incluida `SoloLectura`, un código que no es el de éxito, una escritura ignorada, una relectura que no cuadra— la respuesta es siempre la
        # misma y lleva `datos_sin_saber`, porque antes de fallar pudieron volver datos a la cola.
        try:
            codigo, datos = terminar()
        except Exception as e:                           # noqa: BLE001
            print(f"[warn] por resolver: marcar un rojo no se confirmó ({type(e).__name__})")
            return _por_resolver_rojo_sin_confirmar()
        if codigo == 200 and isinstance(datos, dict) and datos.get("estado") == "resuelto":
            return codigo, datos
        return _por_resolver_rojo_sin_confirmar()


# ---------- el aviso se marca solo después de unir o deshacer desde él ----------
# Quien decide es el SERVIDOR, no la pantalla: la pantalla solo dice «vengo del aviso X» (`aviso` en el cuerpo del pedido de unir, terminar o deshacer);
# el servidor marca únicamente si la unión o el deshacer que él mismo acaba de contestar bien es de ESE aviso (`_aviso_es_de_la_union`), y con el mismo
# camino del botón «Visto» / «Resuelto» (`_por_resolver_marcar_aviso`: relee, y en un rojo devuelve antes los datos de la entrada a `pendiente`).
def _aviso_es_de_la_union(modo, queda, sobra):
    """La regla de «este aviso es de esta unión», mirando la fila del aviso (no la pantalla). `deshacer` = un aviso amarillo de una unión de la puerta cuyas
    dos fichas son las de la unión deshecha. `unir` = un aviso rojo que nombra DOS fichas distintas, y la unión fue entre esas dos (en cualquier orden); o que
    nombra UNA sola, y esa es una de las dos unidas. Cuántas nombra lo dice la fila. Cualquier otro caso: la unión queda hecha y el aviso no se marca."""
    def vale(f):
        tipo = _celda_texto(f.get("tipo_aviso"))
        nombradas = {n for n in (_entero_o_nada(f.get("ficha_id")), _entero_o_nada(f.get("otra_ficha_id"))) if n is not None}
        if modo == "deshacer":
            return (not _por_resolver_aviso_es_rojo(f) and tipo in PUERTA_AVISOS_DE_UNION
                    and _entero_o_nada(f.get("ficha_id")) == queda and _entero_o_nada(f.get("otra_ficha_id")) == sobra)
        if modo != "unir" or not _por_resolver_aviso_es_rojo(f) or not nombradas:
            return False
        return nombradas == {queda, sobra} if len(nombradas) == 2 else nombradas <= {queda, sobra}
    return vale


def aviso_del_pedido(cuerpo):
    """El `aviso` que trae el cuerpo de un pedido de unir, terminar o deshacer: `(clave o None, error o None)`. Algo que no sea la clave de un aviso es un error."""
    if not isinstance(cuerpo, dict) or "aviso" not in cuerpo or cuerpo["aviso"] is None:
        return None, None
    a = cuerpo["aviso"]
    if isinstance(a, str) and RE_CLAVE_AVISO.fullmatch(a):
        return a, None
    return None, "El pedido no está completo: `aviso` tiene que ser la clave de un aviso de «Por resolver»."


def marcar_aviso_de_la_union(clave, modo, datos, quien):
    """Después de una unión (`modo` `unir`) o un deshacer (`deshacer`) que el servidor contestó bien (`datos` es su respuesta con `queda` y `sobra`), marca el
    aviso `clave` de «Por resolver». Devuelve lo que pasó, para decírselo tal cual: `{clave, marcado, ya_estaba, filas_de_dato}` si quedó marcado (releído),
    o `{clave, marcado: False, motivo}`. Nunca levanta: lo que ya salió bien no se esconde porque el aviso no se pudo marcar."""
    queda, sobra = _entero_o_nada(datos.get("queda")), _entero_o_nada(datos.get("sobra"))
    if queda is None or sobra is None:
        return {"clave": clave, "marcado": False, "motivo": "ya_no_aplica"}
    try:
        codigo, r = _por_resolver_marcar_aviso(clave, quien, _aviso_es_de_la_union(modo, queda, sobra))
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] por resolver: el aviso no se pudo marcar después de unir o deshacer ({type(e).__name__})")
        return dict({"clave": clave, "marcado": False, "motivo": "sin_confirmar"}, **({"datos_sin_saber": True} if modo == "unir" else {}))
    if codigo == 200 and r.get("estado") == "resuelto":
        return {"clave": clave, "marcado": True, "ya_estaba": r.get("ya_estaba") is True,
                "filas_de_dato": r["filas_de_dato"] if isinstance(r.get("filas_de_dato"), int) else 0}
    if codigo == 409 and r.get("estado") in ("no_es_de_esta_union", "ya_no_aplica"):
        return {"clave": clave, "marcado": False, "motivo": r["estado"]}
    # la marca de los datos (`datos_sin_saber`) viene de la puerta del rojo; un unir (rojo) que falla de cualquier otra forma también la lleva
    sin_saber = r.get("datos_sin_saber") is True or (modo == "unir" and codigo != 503)
    return dict({"clave": clave, "marcado": False, "motivo": "sin_bandeja" if codigo == 503 else "sin_confirmar"}, **({"datos_sin_saber": True} if sin_saber else {}))


def portal_por_resolver_marcar(clave, quien, reabrir=False, solo_contar=False, planeados=None):
    """Marca un renglón de «Por resolver» como resuelto, o con `reabrir` deshace la marca; devuelve `(código, datos)`.
    `solo_contar` (P11-6e): no escribe; lo que escribiría va a `planeados` y, si contesta 200, es lo que pasaría."""
    if not reabrir and isinstance(clave, str) and RE_CLAVE_AVISO.fullmatch(clave):
        return _por_resolver_marcar_aviso(clave, quien, solo_contar=solo_contar, planeados=planeados)
    if not isinstance(clave, str) or not RE_CLAVE_POR_RESOLVER.fullmatch(clave):
        return 400, {"ok": False, "error": "Falta el renglón que se quiere marcar."}
    tabla = _por_resolver_tabla()
    if not tabla:
        return 503, {"ok": False, "error": POR_RESOLVER_SIN_BANDEJA}
    quien = _celda_texto(quien)
    if not quien:
        return 400, {"ok": False, "error": "No se pudo verificar quién marca."}
    queda = "abierto" if reabrir else "resuelto"
    with _POR_RESOLVER_LOCK:
        if not solo_contar:
            invalidate_portal_personas()
        grupo = next((g for g in por_resolver_grupos([p["publica"] for p in portal_personas_todas()]) if g["clave"] == clave), None)
        if grupo is None:
            return 409, {"ok": False, "estado": "ya_no_aplica",
                         "error": "Ese renglón ya no existe: las fichas cambiaron. Abre «Por resolver» de nuevo."}
        estado_bandeja, marcas = _por_resolver_leer_marcas()
        if estado_bandeja != "ok":
            return 502, {"ok": False, "error": POR_RESOLVER_BANDEJA_CAIDA}
        fila = marcas.get(clave)
        if (fila is not None and fila["estado"] == "resuelto") == (not reabrir):
            return 200, {"ok": True, "estado": queda, "ya_estaba": True, "clave": clave}      # ya estaba como se pide
        base = f"/api/v2/tables/{tabla}/records"
        try:
            if reabrir:
                _nc_o_plan(solo_contar, planeados, "PATCH", tabla, body={"Id": fila["Id"], "estado": "por_resolver"})
            else:
                ahora = _ahora_utc()
                if fila is not None:
                    _nc_o_plan(solo_contar, planeados, "PATCH", tabla, body={"Id": fila["Id"], "estado": "resuelto", "resuelto_por": quien, "resuelto_en": ahora})
                else:
                    _nc_o_plan(solo_contar, planeados, "POST", tabla, body={"clave": clave, "origen": POR_RESOLVER_ORIGEN, "estado": "resuelto",
                                             "tipo_aviso": grupo["tipo"], "ficha_id": grupo["ids"][0], "otra_ficha_id": grupo["ids"][1],
                                             "resultado": json.dumps({"fichas": grupo["ids"]}), "resuelto_por": quien, "resuelto_en": ahora})
        except _base.SoloLectura:
            raise
        except Exception as e:                       # noqa: BLE001
            print(f"[warn] por resolver: no se pudo escribir en la bandeja ({type(e).__name__})")
            return _por_resolver_sin_confirmar()
        if solo_contar:                                  # (P11-6e) lo que se planeó es lo que quedaría: no se relee
            return 200, {"ok": True, "estado": queda, "ya_estaba": False, "clave": clave}
        estado_bandeja, marcas = _por_resolver_leer_marcas()
        releida = marcas.get(clave)
        if estado_bandeja != "ok" or releida is None:
            return _por_resolver_sin_confirmar()
        if reabrir:
            bien = releida["estado"] != "resuelto"
        else:
            bien = releida["estado"] == "resuelto" and releida["resuelto_por"] == quien
        if not bien:
            return _por_resolver_sin_confirmar()
        return 200, {"ok": True, "estado": queda, "ya_estaba": False, "clave": clave}



# ---------- LA UNIÓN: revisar qué pasaría al unir dos fichas (no escribe) ----------
# Cada columna de `personas` que tiene regla de unión. La clase dice cómo se suman las dos fichas en esa casilla.
UNION_CLASES = {
    "telefono": "telefonos", "telefono_2": "telefonos",
    "email": "correos", "email_2": "correos",
    "bsuid": "id_whatsapp",
    "nombre": "nombre", "nombre_whatsapp": "nombre",
    "instagram": "texto", "Cumpleanos": "texto", "Monto_tipico": "texto", "Forma_pago": "texto", "Sala_preferida": "texto",
    "Fuentes": "texto", "Maestro Clientes": "texto", "inscripciones": "texto", "Riesgo_noshow": "texto", "Agendo": "texto",
    "Ultima_visita": "texto", "Maestro_id": "texto",
    "Posible_proveedor": "texto",
    "Precio_referencia": "numero",       # se compara por su valor: `1500`, `1500.0` y `1500.00` son el mismo precio (no chocan)
    "Visitas": "visitas",
    "notas": "largo", "Tono": "largo", "Clave": "largo", "Resumen": "largo", "Comportamiento_reserva": "largo",
    "Preferencias_operativas": "largo", "Sensibilidad_precio": "largo", "Consumo": "largo",
    "instrumento": "lista", "genero": "lista",
    "caras": "caras",
    "credito": "credito",
}
UNION_GRUPOS = {"telefonos": ("telefono", "telefono_2"), "correos": ("email", "email_2")}
UNION_CLAVE_DE_GRUPO = {"telefonos": clave_telefono, "correos": clave_correo}
UNION_CAPACIDAD = 2          # casillas de teléfono y de correo que tiene una ficha
UNION_SEPARADOR_DE_TEXTOS = "\n\n"
UNION_SIN_CONTAR = {"contado": False, "que": ["asistencias", "sesiones", "proyectos", "pagos"],
                    "motivo": "Esta revisión no cuenta lo que cuelga de cada ficha."}


def union_clasificar_columnas(columnas_meta):
    """`(clases, sin_clasificar, ausentes)` de la lista real de columnas (la meta de `personas`).
    `clases` es `{columna: clase}` de las que tienen regla y existen; `sin_clasificar` son los títulos que no tienen regla
    ni son del sistema, de enlace o de `PORTAL_COLUMNAS_NO_DATO`; `ausentes` son columnas con regla que la tabla no trae."""
    clases, sin = {}, set()
    for c in columnas_meta or []:
        if not isinstance(c, dict):
            continue
        titulo = c.get("title")
        if titulo in UNION_CLASES:
            clases[titulo] = UNION_CLASES[titulo]
        elif titulo in PORTAL_COLUMNAS_NO_DATO or c.get("system") is True or c.get("uidt") in _PORTAL_TIPOS_DE_ENLACE:
            continue
        else:
            sin.add(str(titulo))
    return clases, sorted(sin), sorted(set(UNION_CLASES) - set(clases))


def _union_texto(v):
    """El valor de una celda como texto recortado, con los números enteros sin `.0`; vacío es `""`."""
    return _ficha_a_texto(v).replace("\r\n", "\n").strip()


def _union_clave_de_celda(clave, texto):
    """La clave con que se compara una celda no vacía: la de la regla, o su texto en minúsculas si la regla no la lee."""
    return clave(texto) or "texto:" + texto.lower()


def _union_numero(v):
    n = _leer_numero(v)
    return None if n is None else (int(n) if n == int(n) else n)


def _union_credito(f):
    """`(monto, legible)` del crédito de una ficha: vacío es 0; un texto que no es número no es legible."""
    v = f.get("credito")
    if v is None or str(v).strip() == "":
        return 0, True
    n = _leer_numero(v)
    return (n, True) if n is not None else (None, False)


def union_quien_queda(a, b):
    """`(queda, sobra, por_que)` con las dos fichas leídas: la que tiene crédito; si ninguna, la de más `Visitas`; si empatan,
    la de `Id` menor. Si las dos tienen crédito, la de `Id` menor y `por_que` es `credito_en_las_dos`."""
    con_credito = [f for f in (a, b) if (_union_credito(f)[0] or 0) != 0]
    if len(con_credito) == 1:
        q, motivo = con_credito[0], "credito"
    elif len(con_credito) == 2:
        q, motivo = min(a, b, key=lambda f: f["Id"]), "credito_en_las_dos"
    else:
        va, vb = (_leer_numero(f.get("Visitas")) or 0 for f in (a, b))
        if va != vb:
            q, motivo = (a if va > vb else b), "visitas"
        else:
            q, motivo = min(a, b, key=lambda f: f["Id"]), "id_menor"
    return q, (b if q is a else a), motivo


def _union_opcion(id_, de, valor, oculto=False):
    return {"id": id_, "de": de} if oculto else {"id": id_, "de": de, "valor": valor}


def _union_simple(col, clase, q, s, oculto):
    """Una casilla de una sola celda. Vacías o iguales se suman; distintas chocan."""
    tq, ts = _union_texto(q.get(col)), _union_texto(s.get(col))
    clave = {"nombre": clave_nombre, "id_whatsapp": clave_id}.get(clase)
    if clase == "visitas":
        kq, ks = _union_numero(q.get(col)), _union_numero(s.get(col))
    elif clase == "numero":
        # Se compara por su valor: vacía es `None`; un número (o un texto que es exactamente un número) vale su número; lo que no se
        # lee como número se compara como texto (dos textos distintos que no son número siguen chocando).
        def por_valor(valor, texto):
            n = _union_numero(valor) if texto else None
            return (texto or None) if n is None else n
        kq, ks = por_valor(q.get(col), tq), por_valor(s.get(col), ts)
    elif clave:
        kq, ks = (clave(tq) or tq if tq else None), (clave(ts) or ts if ts else None)
    else:
        kq, ks = tq or None, ts or None
    salida = {"casilla": col, "clase": clase}
    if kq is None or ks is None or kq == ks:
        por_que = "vacias" if kq is None and ks is None else "una_vacia" if kq is None or ks is None else "iguales"
        salida.update(estado="suma", por_que=por_que)
        if not oculto:
            salida["resultado"] = tq or ts
        return salida
    opciones = [_union_opcion("queda", "queda", tq, oculto), _union_opcion("sobra", "sobra", ts, oculto)]
    if clase == "largo":
        opciones.append(_union_opcion("juntar", "las_dos", tq + UNION_SEPARADOR_DE_TEXTOS + ts))
    if clase == "visitas":
        opciones.append(_union_opcion("sumar", "las_dos", str(kq + ks)))
    salida.update(estado="choque", opciones=opciones)
    return salida


def _union_lista(col, q, s):
    """`instrumento` y `genero`: las opciones de las dos fichas, sin repetir. No choca."""
    vistas = []
    for f in (q, s):
        for x in _union_texto(f.get(col)).split(","):
            x = x.strip()
            if x and x not in vistas:
                vistas.append(x)
    return {"casilla": col, "clase": "lista", "estado": "suma", "resultado": ",".join(vistas)}


def _union_caras(col, q, s):
    """`caras`: se cuentan, no se enseñan. Quedan las últimas `CARA_RANURAS` de las dos juntas."""
    nq, ns = (len(_base._caras_de_celda(f.get(col))) for f in (q, s))
    return {"casilla": col, "clase": "caras", "estado": "suma", "caras_que_quedan": min(nq + ns, _base.CARA_RANURAS)}


def _union_contacto(grupo, q, s):
    """Teléfonos o correos: los distintos de las dos fichas. Si son 2 o menos caben; el principal de la que queda sigue
    principal y, si no tiene, entra el de la otra. Si son más, chocan."""
    clase = grupo
    cols = UNION_GRUPOS[grupo]
    clave = UNION_CLAVE_DE_GRUPO[grupo]
    vistos = {}
    for quien, f in (("queda", q), ("sobra", s)):
        for c in cols:
            t = _union_texto(f.get(c))
            if t:
                e = vistos.setdefault(_union_clave_de_celda(clave, t), {"valor": t, "de": []})
                if quien not in e["de"]:
                    e["de"].append(quien)
    salida = {"casilla": grupo, "clase": clase, "columnas": list(cols)}
    if len(vistos) > UNION_CAPACIDAD:
        opciones = [dict(e, clave=k) for k, e in vistos.items()]
        if grupo == "telefonos":
            for o in opciones:
                o["reservas"] = _contar_filas(_base.T_SESIONES, f"(telefono_cliente,eq,{o['clave']})", "Id") if o["clave"].isdigit() else None
        for o in opciones:
            o.pop("clave")
        tq = _union_texto(q.get(cols[0]))
        salida.update(estado="choque", cabe=UNION_CAPACIDAD, principal_de_la_que_queda=tq or None, opciones=opciones)
        return salida
    clave_p = None
    for f in (q, s):
        t = _union_texto(f.get(cols[0]))
        if t:
            clave_p = _union_clave_de_celda(clave, t)
            break
    resto = [k for k in vistos if k != clave_p]
    orden = ([clave_p] if clave_p else []) + resto
    valores = [vistos[k]["valor"] for k in orden] + [""] * UNION_CAPACIDAD
    salida.update(estado="suma", resultado=dict(zip(cols, valores[:UNION_CAPACIDAD])))
    return salida


def _union_casillas(clases, q, s):
    """Una entrada por casilla (o por grupo de teléfonos y de correos), en el orden de la ficha del portal.
    Una columna de `PORTAL_COLUMNAS_NO_DATO` no se enseña ni choca: sale `se_conserva`, sin valores."""
    ocultas = set(_base.PORTAL_COLUMNAS_VETADAS)
    orden = [c for c in PORTAL_COLUMNAS_VISIBLES if c in clases] + [c for c in clases if c not in PORTAL_COLUMNAS_VISIBLES]
    hechas, salida = set(), []
    for col in orden:
        clase = clases[col]
        if col in PORTAL_COLUMNAS_NO_DATO:
            salida.append({"casilla": col, "clase": clase, "estado": "se_conserva"})
        elif clase in UNION_GRUPOS:
            if clase not in hechas:
                hechas.add(clase)
                salida.append(_union_contacto(clase, q, s))
        elif clase == "credito":
            salida.append({"casilla": col, "clase": clase, "estado": "no_se_escribe"})
        elif clase == "lista":
            salida.append(_union_lista(col, q, s))
        elif clase == "caras":
            salida.append(_union_caras(col, q, s))
        else:
            salida.append(_union_simple(col, clase, q, s, col in ocultas))
    return salida


def _union_leer_ficha(ficha_id, campos):
    """La fila de `personas` por su `Id`, con `campos`, o `None` si no existe."""
    try:
        fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records/{int(ficha_id)}", query={"fields": ",".join(["Id"] + list(campos))})
    except _base.ErrorDeNocodb as e:
        if e.status == 404:
            return None
        raise
    return fila if isinstance(fila, dict) and fila.get("Id") is not None else None


def revisar_union(id_a, id_b):
    """Qué pasaría al unir las fichas `id_a` e `id_b`, sin escribir nada. Devuelve `(código, datos)`.
    Las columnas se clasifican de la meta real de `personas`; si hay una sin regla o una con regla que falta, no se une.
    `datos` trae cuál queda, cada casilla (se suma o choca, con sus opciones) y los motivos por los que no se puede unir."""
    codigo, datos, contexto = _union_revisar_completo(id_a, id_b)
    if codigo == 200 and contexto is not None and isinstance(datos.get("casillas"), list):
        datos = _union_rotular_actividad(datos)
    return codigo, datos


UNION_ROTULO_DATO_VIEJO = "dato guardado, de antes de los check-ins"
UNION_NOTA_ACTIVIDAD = "Después de unir, la última visita y las visitas se calculan solas con los check-ins."
UNION_CASILLAS_DE_ACTIVIDAD = ("Visitas", "Ultima_visita")


def _union_rotular_actividad(datos):
    """SOLO LO QUE SE ENSEÑA: en la revisión, `Visitas` y `Ultima_visita` son lo GUARDADO de cada ficha (las columnas viejas) y llevan `rotulo` (`UNION_ROTULO_DATO_VIEJO`); la
    respuesta trae además `nota_actividad`: después de unir, esas dos se calculan solas con los check-ins (lo de la lista de Personas). La revisión NO calcula ni promete un resultado para
    ellas: el calculado depende de qué fecha se escoja aparte y de qué check-ins mueve la unión (la que sobra pierde el suyo si es de la misma sesión). Devuelve una copia; no lee ni escribe nada.
    `_union_revisar_completo` (lo que usan `unir_fichas` y deshacer) no pasa por aquí."""
    casillas = [dict(c, rotulo=UNION_ROTULO_DATO_VIEJO) if c.get("casilla") in UNION_CASILLAS_DE_ACTIVIDAD else c for c in datos["casillas"]]
    return dict(datos, casillas=casillas, nota_actividad=UNION_NOTA_ACTIVIDAD)


def _union_revisar_completo(id_a, id_b):
    """Lo que hace `revisar_union`, y además las filas leídas: devuelve `(código, datos, contexto)`, con `contexto = (q, s)` las dos
    fichas leídas (la que queda y la que sobra) o `None` si no se llegaron a leer."""
    if id_a == id_b:
        return 400, {"ok": False, "error": "Hay que escoger otra ficha, no la misma."}, None
    clases, sin, ausentes = union_clasificar_columnas(_base._opciones_select(_base.T_PERSONAS, None, columnas=_base.TODAS_LAS_COLUMNAS))
    motivos = []
    if sin:
        motivos.append({"motivo": "casilla_sin_clasificar", "casillas": sin, "texto": "No sé unir estas casillas: " + ", ".join(sin) + "."})
    if ausentes:
        motivos.append({"motivo": "casilla_ausente", "casillas": ausentes, "texto": "La tabla no trae estas casillas: " + ", ".join(ausentes) + "."})
    if motivos:
        return 200, {"ok": True, "unible": False, "motivos": motivos, "cuelga": UNION_SIN_CONTAR}, None
    filas = [_union_leer_ficha(i, list(clases) + ["unida_a", "quitada_el"]) for i in (id_a, id_b)]
    if None in filas:
        return 404, {"ok": False, "error": "Una de las dos fichas ya no está en la base."}, None
    q, s, por_que = union_quien_queda(*filas)
    unidas = [f["Id"] for f in filas if ficha_unida(f)]
    if unidas:
        motivos.append({"motivo": "ficha_unida", "ids": unidas, "texto": "Una de las dos fichas ya se unió a otra."})
    quitadas = [f["Id"] for f in filas if ficha_quitada(f)]
    if quitadas:
        motivos.append({"motivo": "ficha_quitada", "ids": quitadas, "texto": "Una de las dos fichas fue borrada de Personas."})
    if por_que == "credito_en_las_dos":
        motivos.append({"motivo": "credito_en_las_dos", "texto": "Las dos fichas tienen crédito a favor."})
    if not all(_union_credito(f)[1] for f in filas):
        motivos.append({"motivo": "credito_ilegible", "texto": "El crédito de una de las fichas no se puede leer."})
    casillas = _union_casillas(clases, q, s)
    quien = lambda f: {"id": f["Id"], "nombre": str(f.get("nombre") or "").strip()}      # noqa: E731
    return 200, {"ok": True, "unible": not motivos, "motivos": motivos, "queda": quien(q), "sobra": quien(s), "por_que_queda": por_que,
                 "casillas": casillas, "choques": [c["casilla"] for c in casillas if c["estado"] == "choque"], "cuelga": UNION_SIN_CONTAR}, (q, s)


# ---------- REVISAR EL BORRADO DE UNA FICHA (P2: sin escribir) ----------
# Diseño `disenos/registro-borrar-fichas/DISENO.md` §5.2 (las paradas) y §7 P2. Esta sección SOLO LEE: dice si la ficha se
# podría borrar y, si no, por qué. Lo que no se pudo medir frena (falla cerrado): nunca vale 0 por defecto.
# Lo que cuelga se lee de la propia App (NocoDB); el enlace de proyectos (`L_PERSONA_PROYECTOS`) es provisional hasta que Lucy confirme.
BORRAR_CAMPOS_DE_LA_FICHA = ("nombre", "telefono", "telefono_2", "bsuid", "credito", "unida_a", "quitada_el")
# Estados de un envío que ya no pueden salir. Todo lo demás de `MERCADEO_ENVIO_ESTADOS` (y lo que no esté en esa lista) frena.
BORRAR_ENVIOS_FINALES = ("aceptado", "no_salio", "quitado")
BORRAR_PERMISOS_QUE_FRENAN = ("no", "baja")
# El número de cada parada es el de §5.2 del diseño; «no se pudo medir» es la 7 (no está en el diseño: es la regla de falla cerrado).
# Cada cifra de `cuelga` y el nombre con el que sale en la parada 7. Una clave nueva de `cuelga` sin nombre aquí da error (falla cerrado).
BORRAR_CUELGA_NOMBRES = {"reservas": "reservas", "reservas_por_venir": "reservas", "visitas": "visitas", "mensajes": "mensajes",
                         "envios_por_salir": "envíos de Mercadeo", "proyectos": "proyectos", "pagos": "pagos"}
BORRAR_PARADAS = {"credito_a_favor": 1, "reserva_por_venir": 2, "envio_por_salir": 3, "no_escribir": 4, "permiso_no_se_supo": 4,
                  "ficha_ya_fuera": 5, "union_abierta": 5, "de_un_proyecto": 6, "no_se_pudo_medir": 7}


def _borrar_envios_vivos():
    """Los estados de `MERCADEO_ENVIO_ESTADOS` que todavía pueden salir: la lista se saca de ahí, no se teclea."""
    return tuple(e for e in _base.MERCADEO_ENVIO_ESTADOS if e not in BORRAR_ENVIOS_FINALES)


def _borrar_envios_vivos_de(ficha_id):
    """Los envíos de Mercadeo que todavía pueden salir y que llevan a esta ficha. `ficha_ids` se lee como enteros («8,9»): un
    `like` trae de más (un «18» para el 8) y aquí se filtra por valor exacto. Un estado que no está en la lista cuenta como vivo."""
    vivos = _borrar_envios_vivos()
    filas = _base.nc_list_all(_base.T_MERCADEO_ENVIOS, {"where": f"(ficha_ids,like,%{int(ficha_id)}%)", "fields": "Id,ficha_ids,estado"})
    salida = []
    for e in filas:
        ids = {int(x) for x in re.split(r"[,\s]+", str(e.get("ficha_ids") or "").strip()) if x.isdigit()}
        estado = str(e.get("estado") or "").strip()
        if int(ficha_id) in ids and (estado in vivos or estado not in _base.MERCADEO_ENVIO_ESTADOS):
            salida.append(e)
    return salida


def _borrar_ids_ligados(enlace, ficha_id):
    """Los `Id` ligados a la ficha por ese enlace (proyectos, pagos). Levanta si no se pudo leer: quien llama lo cuenta como no medido."""
    return _union_leer_enlace(_base.T_PERSONAS, enlace, ficha_id)


def _borrar_reservas(tels):
    """`(todas, por_venir)`: las sesiones de esos teléfonos (la misma regla que Lucy, `_sesiones_por_telefono`). Por venir: no terminal
    (`ESTADOS_TERMINALES`) y con fecha de hoy en adelante, en hora de Santo Domingo. Sin fecha, o con una que no se entiende, cuenta
    como por venir (lado estricto)."""
    filas = _base._sesiones_por_telefono(tels)
    hoy = _fecha_hora.now(_base.TZ).strftime("%Y-%m-%d")
    por_venir = []
    for s in filas:
        if str(s.get("estado") or "").strip().upper() in _base.ESTADOS_TERMINALES:
            continue
        fecha = str(s.get("fecha") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) or fecha >= hoy:
            por_venir.append(s)
    return filas, por_venir


def _borrar_union_abierta(ficha_id):
    """Las uniones sin terminar (`en_curso` o `deshaciendo`) que tocan esta ficha. Una fila cuyos `Id` no se leen cuenta como de ella."""
    if not _base.T_UNIONES_PERSONAS:
        raise ValueError("sin la tabla de uniones")
    salida = []
    for u in _union_en_curso():
        qid, sid = _union_numero(u.get("queda_id")), _union_numero(u.get("sobra_id"))
        if ficha_id in (qid, sid) or None in (qid, sid):
            salida.append(u)
    return salida


def _borrar_telefonos(fila):
    """Los teléfonos de la ficha en la forma que comparan las demás lecturas (`clave_telefono`), sin repetir."""
    tels = []
    for celda in (fila.get("telefono"), fila.get("telefono_2")):
        t = clave_telefono(celda)
        if t and t not in tels:
            tels.append(t)
    return tels


def _borrar_mensajes(fila, tels):
    """Cuántos mensajes de chat cuelgan de la ficha: por cada teléfono (`medir_atado_al_telefono`) y por su ID de WhatsApp si lo tiene.
    `None` si alguna de las lecturas no se pudo hacer."""
    total = 0
    for t in tels:
        n = medir_atado_al_telefono(t, fila)["mensajes"]
        if n is None:
            return None
        total += n
    bsuid = str(fila.get("bsuid") or "").strip()
    if bsuid:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", bsuid):
            return None
        # La puerta de número dice con qué número se guarda esta identidad (o ninguno). Si ese número ya se contó por su teléfono, no se
        # cuenta dos veces; si no hay número, la conversación va por el propio ID de WhatsApp.
        numero = numero_de_identidad(bsuid)
        if numero is None or numero not in tels:
            n = _contar_filas(_base.T_CONVERSACIONES, f"(telefono,eq,{numero or bsuid})", "id")
            if n is None:
                return None
            total += n
    return total


def revisar_borrado(ficha_id):
    """Qué pasaría si se borrara la ficha `ficha_id`, SIN escribir nada. Devuelve `(código, datos)`:
      · `datos["puede"]`: `True` solo si no hay ninguna parada;
      · `datos["paradas"]`: `[{numero, motivo, texto}]`, una por cada cosa que frena (los números son los de `BORRAR_PARADAS`);
      · `datos["cuelga"]`: las cifras de lo que hay atado (visitas, reservas, reservas por venir, pagos, proyectos, mensajes, envíos
        por salir). Una cifra que no se pudo medir sale `None` y frena (parada 7): nunca 0 por defecto.
    Sin datos de otras personas: solo cuentas y frases de esta ficha. 404 si la ficha no está en la base."""
    fila = _union_leer_ficha(ficha_id, BORRAR_CAMPOS_DE_LA_FICHA)
    if fila is None:
        return 404, {"ok": False, "error": "Esa persona ya no está en la base."}
    paradas, sin_medir, cuelga = [], [], {}

    def para(motivo, texto):
        paradas.append({"numero": BORRAR_PARADAS[motivo], "motivo": motivo, "texto": texto})

    def no_medido(que):
        sin_medir.append(que)

    if ficha_unida(fila):
        para("ficha_ya_fuera", "Esta ficha ya se unió a otra: no se borra desde aquí.")
    if ficha_quitada(fila):
        para("ficha_ya_fuera", "Esta ficha ya fue borrada: no se vuelve a borrar.")

    monto, legible = _union_credito(fila)
    if not legible or monto is None:
        no_medido("crédito")
    elif monto != 0:
        para("credito_a_favor", f"Tiene RD$ {monto:,.2f} a su favor.")

    tels = _borrar_telefonos(fila)
    try:
        todas, por_venir = _borrar_reservas(tels)
        cuelga["reservas"], cuelga["reservas_por_venir"] = len(todas), len(por_venir)
        if por_venir:
            para("reserva_por_venir", "Tiene una reserva por venir.")
    except Exception:  # noqa: BLE001 — la puerta de abajo lo cuenta como no medido
        cuelga["reservas"] = cuelga["reservas_por_venir"] = None

    cuelga["visitas"] = _contar_filas(_base.T_ASISTENCIAS, f"(persona_id,eq,{int(ficha_id)})", "Id")

    cuelga["mensajes"] = _borrar_mensajes(fila, tels)

    if not _base.T_MERCADEO_ENVIOS:
        cuelga["envios_por_salir"] = None
    else:
        try:
            vivos = _borrar_envios_vivos_de(ficha_id)
            cuelga["envios_por_salir"] = len(vivos)
            if vivos:
                para("envio_por_salir", "Tiene un mensaje de Mercadeo por salir.")
        except Exception:  # noqa: BLE001 — la puerta de abajo lo cuenta como no medido
            cuelga["envios_por_salir"] = None

    permiso = _permiso_de_la_ficha_sin_levantar(ficha_id)
    if permiso is None:
        no_medido("permiso")
    elif not permiso.get("sabido"):
        para("permiso_no_se_supo", "No se pudo saber si pidió que no le escribamos: no se borra.")
    elif permiso.get("permiso") in BORRAR_PERMISOS_QUE_FRENAN:
        para("no_escribir", "Pidió que no le escribamos (o está dada de baja).")

    try:
        abiertas = _borrar_union_abierta(ficha_id)
        if abiertas:
            para("union_abierta", "Tiene una unión sin terminar: hay que terminarla o deshacerla antes.")
    except Exception:  # noqa: BLE001
        no_medido("uniones")

    try:
        proyectos = _borrar_ids_ligados(_base.L_PERSONA_PROYECTOS, ficha_id)
        cuelga["proyectos"] = len(proyectos)
        if proyectos:
            para("de_un_proyecto", "Está en un proyecto: no se borra desde aquí. Hay que sacarla de ese proyecto antes.")
    except Exception:  # noqa: BLE001 — la puerta de abajo lo cuenta como no medido
        cuelga["proyectos"] = None

    try:
        cuelga["pagos"] = len(_borrar_ids_ligados(_base.L_PERSONA_PAGOS, ficha_id))
    except Exception:  # noqa: BLE001 — la puerta de abajo lo cuenta como no medido
        cuelga["pagos"] = None

    # UNA sola puerta para todo `cuelga`: cualquier cifra que quedó en None frena (parada 7). Una lectura nueva que no la
    # ponga en None, o que ponga 0 al fallar, es lo que vigila `tests/test_revisar_borrado.py` (CadaCifraFrena).
    for clave, valor in cuelga.items():
        if valor is None:
            sin_medir.append(BORRAR_CUELGA_NOMBRES[clave])
    sin_medir = list(dict.fromkeys(sin_medir))
    if sin_medir:
        para("no_se_pudo_medir", "No se pudo medir: " + ", ".join(sin_medir) + ". Inténtalo otra vez.")
    return 200, {"ok": True, "puede": not paradas, "paradas": paradas, "cuelga": cuelga}


# ---------- BORRAR UNA FICHA (P3: guardar aparte, con registro; escribe) ----------
# Diseño `disenos/registro-borrar-fichas/DISENO.md` §5.1 (qué se guarda), §5.3 (el orden de «borrar») y §7 P3. NO se borra ninguna fila:
# la ficha se queda con su `Id`, se vacían las 8 casillas que vacía la unión y se pone la marca `quitada_el`; lo que tenía va a una fila
# de `personas_quitadas`, que nunca se borra. La App no hace DELETE a `personas` ni a `personas_quitadas` (`tests/test_quitar_ficha.py`).
# `credito` no se escribe nunca. Todo el borrado corre bajo `_FICHA_TELEFONO_LOCK` y el candado de la ficha (el mismo orden que la unión).
QUITAR_REGISTRO_COLUMNAS = {
    "clave": "SingleLineText", "estado": "SingleLineText", "ficha_id": "Number", "antes": "LongText", "medido": "LongText",
    "creada_por": "SingleLineText", "creada_en": "SingleLineText", "devuelta_por": "SingleLineText", "devuelta_en": "SingleLineText",
}
QUITAR_MARCA = "quitada_el"
QUITAR_ESTADOS = ("quitando", "quitada", "devolviendo", "devuelta")
# «Borrada», para todo el que lo decide: un registro en este estado es una ficha guardada aparte que se puede devolver. La lista «Borradas»
# (`listar_borradas`) y «ya estaba» de `quitar_ficha` leen este mismo valor: si uno cambia, cambian los dos.
QUITAR_ESTADO_BORRADA = "quitada"
_RE_CLAVE_DE_BORRADO = re.compile(r"[A-Za-z0-9_-]{8,64}")
_QUITAR_TEXTO_SIN_CONFIRMAR = ("No se pudo confirmar el borrado. La ficha puede haber quedado a medias: ábrela y mira antes de darla por "
                               "borrada. Repite el mismo borrado para terminarlo; no la des por borrada todavía.")
_QUITAR_TEXTO_CAMBIO = ("Algo cambió mientras la borrabas (alguien escribió en la ficha o apareció algo que frena). No se terminó: la ficha "
                        "no quedó borrada. Ábrela y mira antes de volver a intentar.")


def _quitar_registros(donde):
    """Las filas de `personas_quitadas` que cumplen `donde`. Lo que no venga como lista levanta."""
    filas = _base.nc_list_all(_base.T_PERSONAS_QUITADAS, {"where": donde})
    if not isinstance(filas, list):
        raise ValueError("el registro de borrados no vino como lista")
    return filas


def _quitar_leer_registro(rid):
    """La fila de `personas_quitadas` con ese `Id`, o `None` si no existe."""
    try:
        fila = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS_QUITADAS}/records/{int(rid)}")
    except _base.ErrorDeNocodb as e:
        if e.status == 404:
            return None
        raise
    return fila if isinstance(fila, dict) and fila.get("Id") is not None else None


def _quitar_antes_de(registro):
    """Lo que el registro guardó de la ficha antes de borrarla (`antes`), o `None` si no se puede leer completo."""
    try:
        antes = json.loads(registro.get("antes") or "")
    except (TypeError, ValueError):
        return None
    claves = list(UNION_COLUMNAS_QUE_SE_VACIAN) + [QUITAR_MARCA]
    return antes if isinstance(antes, dict) and all(c in antes for c in claves) else None


def _quitar_medido(datos):
    """Solo cifras: lo que colgaba de la ficha y las paradas que se revisaron. Sin ningún dato de la persona."""
    return {"cuelga": dict(datos["cuelga"]), "paradas_revisadas": sorted(set(BORRAR_PARADAS.values()))}


def _quitar_confirmar_alta(clave, cuerpo):
    """El `Id` del registro que se acaba de apuntar, o `None` si no se puede confirmar: se relee por la clave y tiene que ser
    exactamente lo que se mandó (una sola fila)."""
    try:
        filas = _quitar_registros(f"(clave,eq,{clave})")
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] borrar: no se pudo releer el registro ({type(e).__name__})")
        return None
    iguales = [f for f in filas if f.get("clave") == clave and f.get("estado") == "quitando" and _union_numero(f.get("ficha_id")) == cuerpo["ficha_id"]
               and f.get("antes") == cuerpo["antes"] and f.get("medido") == cuerpo["medido"]]
    if len(iguales) != 1 or isinstance(iguales[0].get("Id"), bool) or not isinstance(iguales[0].get("Id"), int):
        return None
    return iguales[0]["Id"]


def _quitar_ya_hecha(q):
    """¿La ficha ya quedó borrada como la deja el paso 4? Guardada aparte, no unida, y las 8 casillas vacías."""
    return ficha_quitada(q) and not ficha_unida(q) and all(_union_texto(q.get(c)) == "" for c in UNION_COLUMNAS_QUE_SE_VACIAN)


def _quitar_sin_cambios(q, antes):
    """¿La ficha sigue como el registro la guardó? Las 8 casillas igual que en `antes` y ni unida ni guardada aparte."""
    return not ficha_fuera(q) and all(_union_mismo(c, q.get(c), antes[c]) for c in UNION_COLUMNAS_QUE_SE_VACIAN)


def _quitar_ficha_confirmada(qid):
    """Paso 5, la lectura de la ficha: releída, quedó borrada como la deja el paso 4."""
    q = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
    return q is not None and _quitar_ya_hecha(q)


def _quitar_cuerpo_de_la_ficha():
    """Lo que el paso 4 escribe en la ficha: las 8 casillas a vacío y la marca con la hora. `credito` no está nunca."""
    cuerpo = {c: None for c in UNION_COLUMNAS_QUE_SE_VACIAN}
    cuerpo[QUITAR_MARCA] = _ahora_utc()
    if "credito" in cuerpo:
        raise ValueError("el borrado no escribe el crédito")
    return cuerpo


def _quitar_sin_confirmar(rid, motivo):
    return {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "motivo": motivo, "quitada_id": rid,
            "puede_repetir": True, "error": _QUITAR_TEXTO_SIN_CONFIRMAR}


def _quitar_cambio(rid, paradas=None):
    return {"ok": False, "motivo": "cambio_mientras_la_borrabas", "quitada_id": rid, "paradas": paradas or [],
            "error": _QUITAR_TEXTO_CAMBIO}


def quitar_ficha(ficha_id, clave, quien, solo_contar=False, planeados=None):
    """Borra (guarda aparte) la ficha `ficha_id`. `clave` identifica el intento: repetirlo con la misma clave no hace otro borrado y
    sigue donde se quedó. Devuelve `(código, datos)`. Pasos del diseño §5.3:
      0 `revisar_borrado`: cualquier parada frena SIN escribir (409 `paradas`); 404 si la ficha no existe.
      1 Si ya hay un registro con esa clave, se mira su estado y no se crea otro; si hay otra operación de la ficha sin terminar, 409.
      2 Se apunta el registro en `quitando` con lo que la ficha tenía (`antes`) y lo medido, y se relee: sin confirmar, la ficha no se toca.
      3 Dentro de los candados se relee la ficha: si cambió en lo que el registro guardó o apareció una parada, se para (409
        `cambio_mientras_la_borrabas`) y el registro queda `quitando`. Si la ficha ya quedó borrada (una repetición), este paso se salta.
      4 Un solo `PATCH` a la ficha: las 8 casillas a vacío y `quitada_el`.
      5 Se releen la ficha y el registro, y solo entonces el registro pasa a `quitada`. Nunca se contesta `ok` sin esa relectura.
    Si algo falla después del paso 2, la respuesta es 502 `sin_confirmar` y repetir con la misma clave termina el borrado.
    503 sin la tabla de registro (no escribe nada). Lo que contesta el servidor lo decide esta función; el `quien` sale de la firma."""
    if not _base.T_PERSONAS_QUITADAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede borrar ahora: falta conectar el registro de borrados. No se hizo nada."}
    if not isinstance(clave, str) or not _RE_CLAVE_DE_BORRADO.fullmatch(clave):
        return 400, {"ok": False, "motivo": "clave", "error": "Falta la clave del intento."}
    qid = int(ficha_id)
    rid, tocado, ya_estaba, antes = None, False, False, None
    with _FICHA_TELEFONO_LOCK, _candado_de_ficha(qid):
        try:
            previas = _quitar_registros(f"(clave,eq,{clave})")
            if len(previas) > 1:
                return 409, {"ok": False, "motivo": "clave_repetida", "error": "Esa clave ya se usó varias veces. No se hizo nada."}
            r = previas[0] if previas else None
            tocado = r is not None          # ya hay un registro: si algo falla de aquí en adelante, no se dice «no se hizo nada»
            if r is not None and _union_numero(r.get("ficha_id")) != qid:
                return 409, {"ok": False, "motivo": "clave_repetida", "error": "Esa clave ya se usó para otra ficha. No se hizo nada."}
            if r is not None and r.get("estado") == QUITAR_ESTADO_BORRADA:
                ya_estaba, rid = True, int(r["Id"])
            elif r is not None and r.get("estado") == "quitando":
                rid = int(r["Id"])
                antes = _quitar_antes_de(r)
                if antes is None:
                    return 502, {"ok": False, "motivo": "registro_ilegible", "error": "El registro de este borrado no se puede leer. No se tocó la ficha."}
            elif r is not None:
                return 409, {"ok": False, "motivo": "borrado_en_otro_estado", "quitada_id": int(r["Id"]),
                             "error": "Ese borrado ya no se puede seguir. No se hizo nada."}
            else:
                otras = [x for x in _quitar_registros(f"(ficha_id,eq,{qid})") if x.get("estado") in ("quitando", "devolviendo")]
                if otras:
                    return 409, {"ok": False, "motivo": "otra_operacion", "error": "Esta ficha tiene otro borrado o una devolución sin terminar. No se hizo nada."}
                codigo, datos = revisar_borrado(qid)
                if codigo != 200:
                    return codigo, datos
                if not datos["puede"]:
                    return 409, {"ok": False, "motivo": "paradas", "paradas": datos["paradas"], "cuelga": datos["cuelga"],
                                 "error": "Esta ficha no se puede borrar ahora. No se hizo nada."}
                fila = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
                if fila is None:
                    return 404, {"ok": False, "error": "Esa persona ya no está en la base."}
                antes = {c: fila.get(c) for c in UNION_COLUMNAS_QUE_SE_VACIAN}
                antes[QUITAR_MARCA] = None
                cuerpo = {"clave": clave, "estado": "quitando", "ficha_id": qid, "antes": _union_json(antes),
                          "medido": _union_json(_quitar_medido(datos)), "creada_por": quien, "creada_en": _ahora_utc()}
                tocado = True
                _nc_o_plan(solo_contar, planeados, "POST", _base.T_PERSONAS_QUITADAS, body=cuerpo)
                rid = PREVISTO_ID_BASE + 1 if solo_contar else _quitar_confirmar_alta(clave, cuerpo)
                if rid is None:
                    return 502, {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "motivo": "no_se_pudo_apuntar",
                                 "error": "No se pudo apuntar el borrado, así que la ficha no se tocó. Inténtalo otra vez."}
            if not ya_estaba:
                q = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
                if q is None:
                    return 409, {"ok": False, "motivo": "ficha_desaparecio", "quitada_id": rid, "error": "Esa persona ya no está en la base."}
                if not _quitar_ya_hecha(q):
                    if not _quitar_sin_cambios(q, antes):
                        return 409, _quitar_cambio(rid)
                    codigo, datos = revisar_borrado(qid)
                    if codigo != 200 or not datos["puede"]:
                        return 409, _quitar_cambio(rid, datos.get("paradas") if codigo == 200 else None)
                    tocado = True
                    _nc_o_plan(solo_contar, planeados, "PATCH", _base.T_PERSONAS, body=dict(_quitar_cuerpo_de_la_ficha(), Id=qid))
            if solo_contar:
                # (P11-6e) Solo el cálculo: las relecturas que siguen confirman lo que se acaba de planear; no se leen. Lo que falta es el paso 5.
                if not ya_estaba:
                    _nc_o_plan(True, planeados, "PATCH", _base.T_PERSONAS_QUITADAS, body={"Id": rid, "estado": "quitada"})
                return 200, {"ok": True, "estado": "quitada", "ficha": qid, "quitada_id": rid, "ya_estaba": ya_estaba}
            if not _quitar_ficha_confirmada(qid):
                return 502, _quitar_sin_confirmar(rid, "ficha_sin_confirmar")
            rr = _quitar_leer_registro(rid)
            if rr is None or rr.get("estado") not in ("quitando", QUITAR_ESTADO_BORRADA):
                return 502, _quitar_sin_confirmar(rid, "registro_sin_confirmar")
            if rr.get("estado") == "quitando":
                _base.nc("PATCH", f"/api/v2/tables/{_base.T_PERSONAS_QUITADAS}/records", body={"Id": rid, "estado": "quitada"})
                rr = _quitar_leer_registro(rid)
                if rr is None or rr.get("estado") != QUITAR_ESTADO_BORRADA:
                    return 502, _quitar_sin_confirmar(rid, "registro_sin_confirmar")
            return 200, {"ok": True, "estado": "quitada", "ficha": qid, "quitada_id": rid, "ya_estaba": ya_estaba}
        except _base.SoloLectura:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] borrar: no se terminó ({type(e).__name__})")
            if not tocado:
                return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer la base para borrar. No se hizo nada. Inténtalo en un momento."}
            return 502, _quitar_sin_confirmar(rid, "no_termino")
        finally:
            if not solo_contar:        # (P11-6e) el cálculo no toca las cachés
                _union_tirar_caches()      # la cámara y las listas leen cachés: tienen que ver la ficha como quedó


def continuar_quitar(ficha_id):
    """Termina el borrado a medias de `ficha_id` (su registro está `quitando`): vuelve a correr `quitar_ficha` con la clave que el
    registro guardó, desde donde quedó. Sin registro en curso, 404. No pone candados por su cuenta: los pone `quitar_ficha`."""
    if not _base.T_PERSONAS_QUITADAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede borrar ahora: falta conectar el registro de borrados. No se hizo nada."}
    try:
        mios = [r for r in _quitar_registros(f"(ficha_id,eq,{int(ficha_id)})") if r.get("estado") == "quitando"]
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] borrar: no se pudo leer el registro para continuar ({type(e).__name__})")
        return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer el registro de borrados. Inténtalo en un momento."}
    if not mios:
        return 404, {"ok": False, "motivo": "sin_borrado_en_curso", "error": "Esta ficha no tiene un borrado sin terminar."}
    if len(mios) > 1:
        return 409, {"ok": False, "motivo": "clave_repetida", "error": "Esta ficha tiene más de un borrado sin terminar. No se hizo nada."}
    return quitar_ficha(int(ficha_id), mios[0].get("clave"), mios[0].get("creada_por") or "")


# ---------- DEVOLVER UNA FICHA (P4: vuelve lo que guardó el registro; escribe) ----------
# Diseño `disenos/registro-borrar-fichas/DISENO.md` §5.3 («Devolver») y §7 P4. El mismo orden que el borrado: primero el registro (`devolviendo`),
# después UN `PATCH` a la ficha (las 8 casillas de `antes` y la marca a vacío), después se relee la ficha, y solo entonces el registro pasa a
# `devuelta` y se relee. Repetir, o retomar un `devolviendo` a medias, da lo mismo. La ficha vuelve con su mismo `Id`. No hay DELETE y no se
# escribe `credito` (`tests/test_devolver_ficha.py`).
DEVOLVER_ESTADOS_ACTIVOS = (QUITAR_ESTADO_BORRADA, "quitando", "devolviendo")
_DEVOLVER_TEXTO_SIN_CONFIRMAR = ("No se pudo confirmar la devolución. La ficha puede haber quedado a medias: ábrela y mira antes de darla por "
                                 "devuelta. Repite la misma devolución para terminarla; no la des por devuelta todavía.")
_DEVOLVER_TEXTO_OCUPADO = ("No se devolvió: el teléfono, el correo o el ID de WhatsApp de esa persona ya los tiene otra ficha. Si es la misma "
                           "persona, borra o une la otra ficha primero. No se hizo nada.")
_DEVOLVER_TEXTO_CAMBIO = "Algo cambió mientras la devolvías. No se terminó: ábrela y mira antes de volver a intentar."


def _devolver_restaurada(q, antes):
    """¿La ficha está como la guardó el registro? Las 8 casillas de `antes`, sin marca, y ni unida ni guardada aparte."""
    return not ficha_fuera(q) and all(_union_mismo(c, q.get(c), antes[c]) for c in UNION_COLUMNAS_QUE_SE_VACIAN)


def _devolver_cuerpo_de_la_ficha(antes):
    """Lo que el `PATCH` de la devolución escribe en la ficha: las 8 casillas de `antes` y la marca a vacío. `credito` no está nunca."""
    cuerpo = {c: antes[c] for c in UNION_COLUMNAS_QUE_SE_VACIAN}
    cuerpo[QUITAR_MARCA] = None
    if "credito" in cuerpo:
        raise ValueError("la devolución no escribe el crédito")
    return cuerpo


def _devolver_ocupado(qid, antes):
    """El `Id` de OTRA ficha viva que ya tiene un teléfono, un correo o un ID de WhatsApp de `antes`, o `None`. Lo decide la misma regla
    que la puerta (`_puerta_ficha_tiene`, que mira las dos casillas de cada clase). Un dato de `antes` que no se sabe leer levanta: lado estricto."""
    telefonos = []
    for c in ("telefono", "telefono_2"):
        if _union_texto(antes[c]):
            n = _telefono_de_ficha(antes[c])
            if n is None:
                raise ValueError("un teléfono de antes que no se sabe leer")
            telefonos.append(n)
    correos = []
    for c in ("email", "email_2"):
        if _union_texto(antes[c]):
            if clave_correo(antes[c]) is None:
                raise ValueError("un correo de antes que no se sabe leer")
            correos.append(antes[c])
    bsuid = _union_texto(antes["bsuid"])
    if bsuid and clave_id(bsuid) is None:
        raise ValueError("un ID de WhatsApp de antes que no se sabe leer")
    for f in _leer_fichas_de_la_puerta():             # solo fichas vivas: una guardada aparte ya no tiene teléfono ni correo
        if f.get("Id") == qid:
            continue
        if (any(_puerta_ficha_tiene(f, "telefono", n) for n in telefonos)
                or any(_puerta_ficha_tiene(f, "correo", m) for m in correos)
                or (bsuid and clave_id(f.get("bsuid")) == clave_id(bsuid))):
            return int(f["Id"])
    return None


def _devolver_sin_confirmar(rid, motivo):
    return {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "motivo": motivo, "devuelta_id": rid,
            "puede_repetir": True, "error": _DEVOLVER_TEXTO_SIN_CONFIRMAR}


def _devolver_sin_activo(qid, todos):
    """Sin registro activo (ni `quitada`, ni `quitando`, ni `devolviendo`). Si el último borrado ya quedó `devuelta` y la ficha sigue como lo
    dejó la devolución, es un reintento que llega tarde: 200 `ya_estaba`, tras releer. Si no, la ficha no está guardada aparte: 409, sin escribir."""
    devueltas = [r for r in todos if r.get("estado") == "devuelta"]
    if devueltas:
        ultima = max(devueltas, key=lambda r: int(r["Id"]))
        antes = _quitar_antes_de(ultima)
        if antes is not None:
            q = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
            if q is not None and _devolver_restaurada(q, antes):
                return 200, {"ok": True, "estado": "devuelta", "ficha": qid, "devuelta_id": int(ultima["Id"]), "ya_estaba": True}
    return 409, {"ok": False, "motivo": "no_borrada", "error": "Esa ficha no está guardada aparte. No se hizo nada."}


def devolver_ficha(ficha_id, quien, solo_contar=False, planeados=None):
    """Devuelve la ficha `ficha_id` a como la guardó su registro en `personas_quitadas`, con su mismo `Id`. Devuelve `(código, datos)`:
      0 Se buscan los registros de la ficha. Uno activo (`quitada`, `quitando` o `devolviendo`): se sigue con él. Ninguno: 200 `ya_estaba` si el
        último ya quedó `devuelta` y la ficha sigue como lo dejó la devolución; si no, 409 `no_borrada`. Más de uno activo: 409 `otra_operacion`.
      1 La ficha tiene que estar guardada aparte (su marca), salvo que una devolución anterior ya la haya restaurado a medias (`devolviendo`).
        Sin marca y sin eso: 409 `viva`, sin escribir. Una `devolviendo` sin marca que no quedó como `antes`: 409 `cambio_mientras_la_devolvias`.
      2 Si la ficha no está ya restaurada, ningún teléfono, correo o ID de WhatsApp de `antes` lo tiene otra ficha viva: si no, 409 `ocupado`.
      3 El registro pasa a `devolviendo` y se relee; sin confirmar, 502 y la ficha no se toca.
      4 Un solo `PATCH` a la ficha: las 8 casillas de `antes` y la marca a vacío (si no estaba ya así).
      5 Se relee la ficha. Solo si quedó como `antes`, el registro pasa a `devuelta` (con `devuelta_por` y `devuelta_en`) y se relee: solo
        entonces se contesta 200.
    503 sin la tabla de registro (no escribe nada). Nunca `DELETE`; `credito` no se escribe."""
    if not _base.T_PERSONAS_QUITADAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede devolver ahora: falta conectar el registro de borrados. No se hizo nada."}
    qid = int(ficha_id)
    rid, tocado = None, False
    with _FICHA_TELEFONO_LOCK, _candado_de_ficha(qid):
        try:
            todos = [r for r in _quitar_registros(f"(ficha_id,eq,{qid})") if _union_numero(r.get("ficha_id")) == qid]
            activos = [r for r in todos if r.get("estado") in DEVOLVER_ESTADOS_ACTIVOS]
            if len(activos) > 1:
                return 409, {"ok": False, "motivo": "otra_operacion", "error": "Esta ficha tiene más de un registro de borrado sin cerrar. No se hizo nada."}
            if not activos:
                return _devolver_sin_activo(qid, todos)
            r = activos[0]
            rid = int(r["Id"])
            antes = _quitar_antes_de(r)
            if antes is None:
                return 502, {"ok": False, "motivo": "registro_ilegible", "error": "El registro de este borrado no se puede leer. No se tocó la ficha."}
            q = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
            if q is None:
                return 404, {"ok": False, "error": "Esa persona ya no está en la base."}
            ya = _devolver_restaurada(q, antes)
            if not ficha_quitada(q) and not (r["estado"] == "devolviendo" and _devolver_restaurada(q, antes)):
                if r["estado"] == "devolviendo":
                    return 409, {"ok": False, "motivo": "cambio_mientras_la_devolvias", "devuelta_id": rid, "error": _DEVOLVER_TEXTO_CAMBIO}
                return 409, {"ok": False, "motivo": "viva", "error": "Esa ficha no está guardada aparte. No se hizo nada."}
            if not ya:
                ocupada = _devolver_ocupado(qid, antes)
                if ocupada is not None:
                    return 409, {"ok": False, "motivo": "ocupado", "de": ocupada, "error": _DEVOLVER_TEXTO_OCUPADO}
            if r["estado"] != "devolviendo":
                tocado = True
                _nc_o_plan(solo_contar, planeados, "PATCH", _base.T_PERSONAS_QUITADAS, body={"Id": rid, "estado": "devolviendo"})
                if not solo_contar:                      # (P11-6e) el cálculo no relee lo que planea
                    rr = _quitar_leer_registro(rid)
                    if rr is None or rr.get("estado") != "devolviendo":
                        return 502, _devolver_sin_confirmar(rid, "no_se_pudo_apuntar")
            tocado = True
            if not ya:
                _nc_o_plan(solo_contar, planeados, "PATCH", _base.T_PERSONAS, body=dict(_devolver_cuerpo_de_la_ficha(antes), Id=qid))
            if not solo_contar:
                q2 = _union_leer_ficha(qid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a", QUITAR_MARCA])
                if q2 is None or not _devolver_restaurada(q2, antes):
                    return 502, _devolver_sin_confirmar(rid, "ficha_sin_confirmar")
            _nc_o_plan(solo_contar, planeados, "PATCH", _base.T_PERSONAS_QUITADAS, body={"Id": rid, "estado": "devuelta", "devuelta_por": quien, "devuelta_en": _ahora_utc()})
            if not solo_contar:
                rr = _quitar_leer_registro(rid)
                if rr is None or rr.get("estado") != "devuelta":
                    return 502, _devolver_sin_confirmar(rid, "registro_sin_confirmar")
            return 200, {"ok": True, "estado": "devuelta", "ficha": qid, "devuelta_id": rid, "ya_estaba": False}
        except _base.SoloLectura:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] devolver: no se terminó ({type(e).__name__})")
            if not tocado:
                return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer la base para devolver. No se hizo nada. Inténtalo en un momento."}
            return 502, _devolver_sin_confirmar(rid, "no_termino")
        finally:
            if not solo_contar:        # (P11-6e) el cálculo no toca las cachés
                _union_tirar_caches()      # la cámara y las listas leen cachés: tienen que ver la ficha como quedó


# ---------- LA LISTA «BORRADAS» (P6: lo que se puede devolver; no escribe) ----------
# Diseño `disenos/registro-borrar-fichas/DISENO.md` §7 P6. Solo lo que la pantalla muestra: nombre, cuándo y quién (más el `Id` de la
# ficha, para el botón «Devolver»). Un borrado a medias o ya devuelto no sale. Tests: `tests/test_borradas_lista.py`.
def listar_borradas():
    """Las fichas guardadas aparte que se pueden devolver: sus registros en `QUITAR_ESTADO_BORRADA`. Por cada una devuelve `ficha` (el `Id`),
    `nombre` (el que tenía, de `antes`; `None` si `antes` no se puede leer), `cuando` (`creada_en`) y `quien` (`creada_por`). Devuelve
    `(código, datos)`. 503 sin la tabla de registro; 502 si no se puede leer. No escribe nada."""
    if not _base.T_PERSONAS_QUITADAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede ver la lista ahora: falta conectar el registro de borrados."}
    try:
        registros = _quitar_registros(f"(estado,eq,{QUITAR_ESTADO_BORRADA})")
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] borradas: no se pudo leer el registro ({type(e).__name__})")
        return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer la lista de borradas. Inténtalo en un momento."}
    filas = []
    for r in registros:
        if r.get("estado") != QUITAR_ESTADO_BORRADA:          # por si la red devuelve más de lo pedido: el mismo criterio que la consulta
            continue
        antes = _quitar_antes_de(r)
        nombre = None
        if antes is not None:
            nombre = _union_texto(antes.get("nombre")) or _union_texto(antes.get("nombre_whatsapp")) or ""
        filas.append({"ficha": _union_numero(r.get("ficha_id")), "nombre": nombre,
                      "cuando": r.get("creada_en") or "", "quien": r.get("creada_por") or ""})
    filas.sort(key=lambda f: f["cuando"], reverse=True)
    return 200, {"ok": True, "filas": filas}


# ---------- LA UNIÓN: unir dos fichas (escribe) ----------
# Una unión pasa por un registro (una fila de `uniones_personas`) y por ocho pasos; cada paso mira antes de escribir y se puede repetir.
# Si algo se corta, `continuar_union` vuelve a correr desde el plan guardado en el registro. Con un doble de NocoDB que falla en cada llamada
# deja el mismo estado que una corrida sin cortes (`tests/test_union_unir.py`); contra el NocoDB real no se ha probado.
# Se pone `unida` solo después de volver a leer las dos fichas y sus enlaces. La ficha que sobra queda vacía y marcada (`unida_a`).
UNION_REGISTRO_COLUMNAS = {
    "clave": "SingleLineText", "estado": "SingleLineText", "queda_id": "Number", "sobra_id": "Number",
    "plan": "LongText", "antes": "LongText", "creada_por": "SingleLineText", "creada_en": "SingleLineText",
    "terminada_en": "SingleLineText", "deshecha_por": "SingleLineText", "deshecha_en": "SingleLineText",
}
UNION_ESTADOS = ("en_curso", "unida", "deshaciendo", "deshecha")
UNION_COLUMNAS_QUE_SE_VACIAN = ("nombre", "nombre_whatsapp", "telefono", "telefono_2", "email", "email_2", "bsuid", "caras")
UNION_PASADAS = 3                # veces que se repiten los pasos 2 a 4 si la ficha que sobra recibe algo nuevo
_RE_CLAVE_DE_UNION = re.compile(r"[A-Za-z0-9_-]{8,64}")
_UNION_LOCK = threading.Lock()   # una unión a la vez en este proceso
_UNION_TEXTO_SIN_CONFIRMAR = ("La unión no se terminó. Las dos fichas pueden haber quedado a medias: ábrelas y usa «Terminar la unión». "
                              "No la des por hecha.")


class _UnionParada(Exception):
    """Una unión que se detiene con la respuesta ya armada (`codigo`, `datos`)."""

    def __init__(self, codigo, datos):
        super().__init__(datos.get("motivo"))
        self.codigo, self.datos = codigo, datos


def _union_no(codigo, motivo, texto, **extra):
    return _UnionParada(codigo, dict({"ok": False, "motivo": motivo, "error": texto}, **extra))


def _union_sin_confirmar(union_id, motivo, texto=_UNION_TEXTO_SIN_CONFIRMAR):
    return 502, {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "motivo": motivo, "union_id": union_id,
                 "puede_terminar": True, "error": texto}


def _union_json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _union_mismo(col, a, b):
    """¿Dos celdas de `col` dicen lo mismo? Igual texto; en teléfonos y correos, igual por la regla de la puerta."""
    ta, tb = _union_texto(a), _union_texto(b)
    if ta == tb:
        return True
    if UNION_CLASES.get(col) == "numero" and ta and tb:
        na, nb = _union_numero(a), _union_numero(b)
        return na is not None and na == nb
    clave = UNION_CLAVE_DE_GRUPO.get(UNION_CLASES.get(col))
    return bool(clave and ta and tb and clave(ta) is not None and clave(ta) == clave(tb))


def _union_caras_texto(*celdas):
    """Las caras legibles de las celdas, una tras otra, y las últimas `CARA_RANURAS`. Cada celda aporta como mucho las suyas últimas."""
    trozos = []
    for celda in celdas:
        buenos = [t.strip() for t in str(celda or "").split(_base.CARA_SEPARADOR) if t.strip() and _base._cara_desde_base64(t.strip()) is not None]
        trozos += buenos[-_base.CARA_RANURAS:]
    return _base.CARA_SEPARADOR.join(trozos[-_base.CARA_RANURAS:])


def _union_resolver_contacto(c, q, s, eleccion, cuerpo, faltan, malas):
    """Teléfonos o correos: si caben se suman; si chocan, `eleccion` es la lista (de 1 a 2) de los que se quedan, el primero principal."""
    grupo, cols = c["casilla"], c["columnas"]
    clave = UNION_CLAVE_DE_GRUPO[grupo]
    if c["estado"] == "suma":
        finales = [c["resultado"][col] for col in cols]
    else:
        if eleccion is None:
            faltan.append(grupo)
            return
        ofrecidos = {_union_clave_de_celda(clave, o["valor"]): o["valor"] for o in c["opciones"]}
        if not isinstance(eleccion, list) or not 1 <= len(eleccion) <= UNION_CAPACIDAD or not all(isinstance(x, str) for x in eleccion):
            malas.append(grupo)
            return
        claves = [_union_clave_de_celda(clave, _union_texto(x)) for x in eleccion]
        if len(set(claves)) != len(claves) or any(k not in ofrecidos for k in claves):
            malas.append(grupo)
            return
        finales = ([ofrecidos[k] for k in claves] + [""] * UNION_CAPACIDAD)[:UNION_CAPACIDAD]
    for col, nuevo in zip(cols, finales):
        if not _union_mismo(col, nuevo, q.get(col)):
            cuerpo[col] = nuevo or None


def _union_resolver(casillas, q, s, resoluciones):
    """`(cuerpo, faltan, malas)`: lo que hay que escribir en la ficha que queda (solo las casillas que cambian), las casillas que chocan
    y no traen resolución, y las resoluciones que no son una de las opciones ofrecidas. `credito` no entra en el cuerpo."""
    resol = resoluciones if isinstance(resoluciones, dict) else {}
    cuerpo, faltan, malas = {}, [], []
    for c in casillas:
        nombre, estado, clase = c["casilla"], c["estado"], c["clase"]
        if estado == "no_se_escribe":
            continue
        if clase in UNION_GRUPOS:
            _union_resolver_contacto(c, q, s, resol.get(nombre), cuerpo, faltan, malas)
        elif clase == "lista":
            if c["resultado"] != _union_texto(q.get(nombre)):
                cuerpo[nombre] = c["resultado"] or None
        elif clase == "caras":
            nuevo = _union_caras_texto(q.get(nombre), s.get(nombre))
            if nuevo != _union_caras_texto(q.get(nombre)):
                cuerpo[nombre] = nuevo or None
        elif estado in ("suma", "se_conserva"):
            if not _union_texto(q.get(nombre)) and _union_texto(s.get(nombre)):
                cuerpo[nombre] = s.get(nombre)
        elif estado == "choque":
            eleccion = resol.get(nombre)
            if eleccion is None:
                faltan.append(nombre)
            elif eleccion not in [o["id"] for o in c["opciones"]]:
                malas.append(nombre)
            elif eleccion == "sobra":
                cuerpo[nombre] = s.get(nombre)
            elif eleccion == "juntar":
                cuerpo[nombre] = _union_texto(q.get(nombre)) + UNION_SEPARADOR_DE_TEXTOS + _union_texto(s.get(nombre))
            elif eleccion == "sumar":
                total = _union_numero(q.get(nombre)) + _union_numero(s.get(nombre))
                cuerpo[nombre] = int(total) if total == int(total) else total
        else:
            malas.append(nombre)
    choques = {c["casilla"] for c in casillas if c["estado"] == "choque"}
    malas += [k for k in resol if k not in choques]
    return cuerpo, faltan, sorted(set(malas))


# --- lo que cuelga de una ficha ---

def _union_leer_enlace(tabla, enlace, registro):
    """Los `Id` ligados a `registro` por ese enlace, de todas las páginas. Lo que no venga como lista levanta."""
    ids, desde = [], 0
    for _ in range(50):
        pagina = _base.nc("GET", _base.nc_link_path(tabla, enlace, registro), query={"limit": 200, "offset": desde})
        lista = pagina if isinstance(pagina, list) else pagina.get("list") if isinstance(pagina, dict) else None
        if not isinstance(lista, list):
            raise ValueError("el enlace no vino como lista")
        ids += [int(x["Id"]) for x in lista if isinstance(x, dict) and x.get("Id") is not None]
        info = pagina.get("pageInfo") if isinstance(pagina, dict) else None
        if (info.get("isLastPage", True) if isinstance(info, dict) else len(lista) < 200):
            return sorted(set(ids))
        desde += 200
    raise ValueError("el enlace tiene demasiadas páginas")


def _union_asistencias_de(ficha_id):
    """Las asistencias de una ficha, por `persona_id`, de menor a mayor `Id`."""
    filas = _base.nc_list_all(_base.T_ASISTENCIAS, {"where": f"(persona_id,eq,{int(ficha_id)})",
                                            "fields": "Id,titulo,checkin_at,registrado_por,persona_id,sesion_id"})
    for a in filas:
        if isinstance(a.get("Id"), bool) or not isinstance(a.get("Id"), int):
            raise ValueError("una asistencia no trae su Id")
        if isinstance(a.get("sesion_id"), bool) or not isinstance(a.get("sesion_id"), int):
            raise _union_no(409, "asistencia_sin_sesion", "Una asistencia de la ficha no dice a qué sesión es: la App no sabe moverla.")
    return sorted(filas, key=lambda a: a["Id"])


def _union_lo_de_sobra(ficha_id):
    """Lo que cuelga de la ficha: sus asistencias y los `Id` de sus sesiones, proyectos, pagos e inscripciones."""
    return {"asistencias": _union_asistencias_de(ficha_id),
            "sesiones": _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_SESIONES, ficha_id),
            "proyectos": _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PROYECTOS, ficha_id),
            "pagos": _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, ficha_id),
            "inscripciones": _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_INSCRIPCIONES, ficha_id)}


def _union_queda_algo(lo):
    return any(lo[k] for k in ("asistencias", "sesiones", "proyectos", "pagos"))


def _union_ids(plan, clave):
    """Los `Id` de las entradas del plan en `clave` (`sesiones`, `proyectos` o `pagos`)."""
    return [e["id"] for e in plan[clave]]


def _union_completar_plan(plan, lo, asistencias_de_la_que_queda, enlaces_de_la_que_queda):
    """Agrega al plan lo de `lo` que el plan no tiene; devuelve si cambió. Cada asistencia y cada enlace nuevo lleva su marca:
    `mover`, o `ya_tenia_la_que_queda` si la que queda ya lo tenía cuando se leyó. Lo que el plan ya trae no se toca ni se marca otra vez.
    `asistencias_de_la_que_queda()` y `enlaces_de_la_que_queda(clave)` se llaman solo si hay algo nuevo."""
    cambio = False
    ya = {e["sesion"] for e in plan["asistencias"]}
    nuevas = [a for a in lo["asistencias"] if a["sesion_id"] not in ya]
    if nuevas:
        tiene = {a["sesion_id"] for a in asistencias_de_la_que_queda()}
        for a in nuevas:
            accion = "ya_tenia_la_que_queda" if a["sesion_id"] in tiene else "mover"
            plan["asistencias"].append({"sesion": a["sesion_id"], "checkin_at": a.get("checkin_at"), "registrado_por": a.get("registrado_por"),
                                        "titulo": a.get("titulo"), "accion": accion})
            tiene.add(a["sesion_id"])
        cambio = True
    for clave, de_sobra in (("sesiones", set(lo["sesiones"]) | {e["sesion"] for e in plan["asistencias"]}),
                            ("proyectos", set(lo["proyectos"])), ("pagos", set(lo["pagos"]))):
        nuevos = sorted(de_sobra - set(_union_ids(plan, clave)))
        if nuevos:
            tiene = set(enlaces_de_la_que_queda(clave))
            plan[clave] = sorted(plan[clave] + [{"id": n, "accion": "ya_tenia_la_que_queda" if n in tiene else "mover"} for n in nuevos],
                                 key=lambda e: e["id"])
            cambio = True
    return cambio


def _union_enlaces_de(ficha_id):
    """`enlaces_de_la_que_queda` para `_union_completar_plan`: lee el enlace de la ficha según la clave."""
    enlaces = {"sesiones": _base.L_PERSONA_SESIONES, "proyectos": _base.L_PERSONA_PROYECTOS, "pagos": _base.L_PERSONA_PAGOS}
    return lambda clave: _union_leer_enlace(_base.T_PERSONAS, enlaces[clave], ficha_id)


# --- el registro ---

def _union_filas_del_registro(donde):
    filas = _base.nc_list_all(_base.T_UNIONES_PERSONAS, {"where": donde})
    if not isinstance(filas, list):
        raise ValueError("el registro no vino como lista")
    return filas


def _union_en_curso():
    """Las filas del registro con una unión sin terminar (`en_curso` o `deshaciendo`)."""
    return [u for estado in ("en_curso", "deshaciendo") for u in _union_filas_del_registro(f"(estado,eq,{estado})")]


def _union_de_la_ficha(filas, ficha_id):
    return sorted((u for u in filas if ficha_id in (int(u["queda_id"]), int(u["sobra_id"]))), key=lambda u: int(u["Id"]))


class SinCalculoDeUnion(Exception):
    """P11-6f: un camino de `unir` que el cálculo (`solo_contar`) no puede predecir con fidelidad. `motivo` es una clave fija. Se lanza
    ANTES de escribir lo que no se sabe, o después de planear escrituras que la escritura de verdad sí haría: en ese caso la unión
    ya habría movido cosas y el cálculo no las dice (`personas_cuenta._calc_unir` contesta «sin cálculo»)."""

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def _union_nc(solo_contar, planeados, metodo, tabla, body):
    """Una escritura de filas de `unir` (POST, PATCH o DELETE a `records`). Con `solo_contar` no sale a la red: queda en `planeados`, en orden."""
    if solo_contar:
        planeados.append({"tabla": tabla, "metodo": metodo, "cuerpo": body})
        return None
    return _base.nc(metodo, f"/api/v2/tables/{tabla}/records", body=body)


def _enlace_nombre(enlace):
    """El nombre `L_*` de la constante de `base` con ese id: es el que la App ve (`_nombre_de_enlace` de la App). Sin nombre, no se predice."""
    nombres = sorted(n for n, v in vars(_base).items() if n.startswith("L_") and v and v == enlace)
    if not nombres:
        raise SinCalculoDeUnion("enlace_sin_nombre")
    return "enlace:" + nombres[0]


def _union_escribir_ficha(ficha_id, cuerpo, solo_contar=False, planeados=None):
    """El `PATCH` a `personas` de la unión. `credito` no se escribe."""
    if "credito" in cuerpo or "Id" in cuerpo:
        raise ValueError("la unión no escribe esa casilla")
    _union_nc(solo_contar, planeados, "PATCH", _base.T_PERSONAS, dict(cuerpo, Id=int(ficha_id)))


def _union_tirar_caches():
    invalidate_personas()
    invalidate_portal_personas()
    _base.invalidate_caras()


# --- los pasos 2 a 5: mover lo que cuelga de la ficha que sobra ---

def _union_ligar(tabla, enlace, registro, destinos, solo_contar=False, planeados=None):
    """Liga `registro` de `tabla` con los `Id` de `destinos` por ese enlace (el `POST` de enlace de `hacer_checkin`). Con `solo_contar`
    queda en `planeados` con su registro y sus ligados (P11-6f), sin salir a la red."""
    if solo_contar:
        planeados.append({"tabla": tabla, "metodo": "POST", "enlace": _enlace_nombre(enlace), "registro": int(registro),
                          "ligados": [int(d) for d in destinos]})
        return
    _base.nc("POST", _base.nc_link_path(tabla, enlace, registro), body=[{"Id": d} for d in destinos])


def _union_desligar(tabla, enlace, registro, destinos, solo_contar=False, planeados=None):
    """Quita el vínculo de `registro` con `destinos` (el `DELETE` que hace `nc_unlink`). Con `solo_contar` queda en `planeados` (P11-6f)."""
    if solo_contar:
        if destinos:
            planeados.append({"tabla": tabla, "metodo": "DELETE", "enlace": _enlace_nombre(enlace), "registro": int(registro),
                              "ligados": [int(d) for d in destinos]})
        return
    _base.nc_unlink(tabla, enlace, registro, destinos)


def _union_asegurar_enlace(tabla, enlace, registro, destino, solo_contar=False, planeados=None):
    if destino not in _union_leer_enlace(tabla, enlace, registro):
        _union_ligar(tabla, enlace, registro, [destino], solo_contar, planeados)


def _union_crear_asistencia(entrada, qid, titulo):
    """Una asistencia de `qid` en la sesión de `entrada`, con el mismo `POST` y los mismos enlaces de `hacer_checkin`."""
    rec = _base.nc("POST", f"/api/v2/tables/{_base.T_ASISTENCIAS}/records", body={
        "titulo": titulo, "checkin_at": entrada["checkin_at"], "registrado_por": entrada["registrado_por"],
        "persona_id": qid, "sesion_id": entrada["sesion"]})
    aid = rec.get("Id") if isinstance(rec, dict) else None
    if isinstance(aid, bool) or not isinstance(aid, int):
        raise ValueError("la asistencia nueva no trajo su Id")
    _union_ligar(_base.T_ASISTENCIAS, _base.L_ASIS_PERSONA, aid, [qid])
    _union_ligar(_base.T_ASISTENCIAS, _base.L_ASIS_SESION, aid, [entrada["sesion"]])
    return aid


def _union_mover_asistencias(plan, qid, sid, solo_contar=False, planeados=None):
    """Paso 2. Por cada asistencia del plan: si la que queda no tiene una en esa sesión se le crea, y después se borra la de la que sobra.
    Con `solo_contar` (P11-6f): crear una asistencia nueva no se predice (su `Id` lo asigna la base y es el registro de sus enlaces): se
    levanta `SinCalculoDeUnion`. Lo demás queda en `planeados`."""
    de_s = {}
    for a in _union_asistencias_de(sid):
        de_s.setdefault(a["sesion_id"], []).append(a)
    if not de_s:
        return
    de_q = {}
    for a in _union_asistencias_de(qid):
        de_q.setdefault(a["sesion_id"], []).append(a)
    for e in plan["asistencias"]:
        ses = e["sesion"]
        if not de_s.get(ses):
            continue
        if not de_q.get(ses):
            if solo_contar:
                raise SinCalculoDeUnion("asistencia_nueva")
            de_q[ses] = [{"Id": _union_crear_asistencia(e, qid, plan["titulo_q"])}]
        elif e["accion"] == "mover":
            aid = de_q[ses][0]["Id"]
            _union_asegurar_enlace(_base.T_ASISTENCIAS, _base.L_ASIS_PERSONA, aid, qid, solo_contar, planeados)
            _union_asegurar_enlace(_base.T_ASISTENCIAS, _base.L_ASIS_SESION, aid, ses, solo_contar, planeados)
        for a in de_s[ses]:
            _union_nc(solo_contar, planeados, "DELETE", _base.T_ASISTENCIAS, {"Id": a["Id"]})
        de_s[ses] = []


def _union_mover_enlaces(plan_ids, tabla, enlace_del_registro, enlace_de_la_ficha, qid, sid, solo_contar=False, planeados=None):
    """Pasos 3 y 4. Cada registro de `plan_ids` se liga a `qid` desde su lado y se desliga de `sid`."""
    if not plan_ids:
        return
    de_s = _union_leer_enlace(_base.T_PERSONAS, enlace_de_la_ficha, sid)
    de_q = _union_leer_enlace(_base.T_PERSONAS, enlace_de_la_ficha, qid)
    for r in plan_ids:
        if r not in de_q:
            _union_ligar(tabla, enlace_del_registro, r, [qid], solo_contar, planeados)
        if r in de_s:
            _union_desligar(tabla, enlace_del_registro, r, [sid], solo_contar, planeados)


def _union_mover_sesiones(plan, qid, sid, solo_contar=False, planeados=None):
    _union_mover_enlaces(_union_ids(plan, "sesiones"), _base.T_SESIONES, _base.L_MUSICOS, _base.L_PERSONA_SESIONES, qid, sid,
                         solo_contar, planeados)


def _union_mover_proyectos_y_pagos(plan, qid, sid, solo_contar=False, planeados=None):
    """Paso 4. Los proyectos se mueven desde el lado del proyecto; los pagos, desde el lado de la ficha."""
    _union_mover_enlaces(_union_ids(plan, "proyectos"), _base.T_PROYECTOS, _base.L_PROY_MIEMBROS, _base.L_PERSONA_PROYECTOS, qid, sid,
                         solo_contar, planeados)
    pagos = _union_ids(plan, "pagos")
    if pagos:
        de_s = _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, sid)
        de_q = _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, qid)
        nuevos = [p for p in pagos if p not in de_q]
        if nuevos:
            _union_ligar(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, qid, nuevos, solo_contar, planeados)
        quitar = [p for p in pagos if p in de_s]
        if quitar:
            _union_desligar(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, sid, quitar, solo_contar, planeados)


# --- los pasos 6 y 7: escribir las dos fichas ---

def _union_marcar(antes, qid, sid, solo_contar=False, planeados=None):
    """Pasos 6 y 7, bajo los candados. Se relee cada ficha: si una casilla que la unión usa cambió respecto al plan, se para.
    Si no, se escribe la que queda (paso 6) y se vacía y se marca la que sobra (paso 7). Lo ya escrito no se vuelve a escribir.
    Con `solo_contar` (P11-6f) las lecturas son las mismas, y los dos PATCH quedan en `planeados`; no se tiran cachés."""
    cols_q = list(antes["queda"])
    cols_s = list(dict.fromkeys(list(UNION_COLUMNAS_QUE_SE_VACIAN) + list(antes["lee_de_sobra"])))
    with _FICHA_TELEFONO_LOCK, _candado_de_ficha(min(qid, sid)), _candado_de_ficha(max(qid, sid)):
        try:
            q = _union_leer_ficha(qid, cols_q + ["unida_a", "quitada_el"])
            s = _union_leer_ficha(sid, cols_s + ["unida_a", "quitada_el"])
            if q is None or s is None:
                raise _union_no(409, "ficha_desaparecio", "Una de las dos fichas ya no está en la base.")
            if ficha_quitada(q) or ficha_quitada(s):
                raise _union_no(409, "ficha_quitada", "Una de las dos fichas se borró de Personas mientras unías.")
            if ficha_unida(q) or (ficha_unida(s) and _union_numero(s.get("unida_a")) != qid):
                raise _union_no(409, "ficha_unida", "Una de las dos fichas se unió a otra mientras unías.")
            cambio = [c for c, d in antes["queda"].items()
                      if not (_union_mismo(c, q.get(c), d["antes"]) or _union_mismo(c, q.get(c), d["despues"]))]
            cambio += [c for c in UNION_COLUMNAS_QUE_SE_VACIAN
                       if not (_union_mismo(c, s.get(c), antes["sobra"][c]["antes"]) or _union_texto(s.get(c)) == "")]
            cambio += [c for c, v in antes["lee_de_sobra"].items() if not _union_mismo(c, s.get(c), v)]
            if cambio:
                raise _union_no(409, "cambio_mientras_unias", "Una de las dos fichas cambió mientras unías. No se siguió.", casillas=sorted(set(cambio)))
            cuerpo_q = {c: d["despues"] for c, d in antes["queda"].items() if not _union_mismo(c, q.get(c), d["despues"])}
            if cuerpo_q:
                _union_escribir_ficha(qid, cuerpo_q, solo_contar, planeados)
            cuerpo_s = {c: None for c in UNION_COLUMNAS_QUE_SE_VACIAN if _union_texto(s.get(c)) != ""}
            if not ficha_unida(s):
                cuerpo_s["unida_a"] = qid
            if cuerpo_s:
                _union_escribir_ficha(sid, cuerpo_s, solo_contar, planeados)
        finally:
            if not solo_contar:       # (P11-6f) el cálculo no tira cachés
                _union_tirar_caches()      # la cámara lee las caras de una caché: tiene que verlas como quedaron


# --- el paso 8: volver a leer y cerrar ---

def _union_verificar(plan, antes, qid, sid):
    """Paso 8, la lectura. Devuelve la lista de lo que no cuadra (vacía si todo quedó como el plan)."""
    q = _union_leer_ficha(qid, list(antes["queda"]) + ["unida_a"])
    s = _union_leer_ficha(sid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a"])
    if q is None or s is None:
        return ["ficha"]
    mal = []
    if ficha_unida(q):
        mal.append("queda_marcada")
    mal += [c for c, d in antes["queda"].items() if not _union_mismo(c, q.get(c), d["despues"])]
    mal += [c for c in UNION_COLUMNAS_QUE_SE_VACIAN if _union_texto(s.get(c)) != ""]
    if _union_numero(s.get("unida_a")) != qid:
        mal.append("sobra_sin_marca")
    de_s = _union_lo_de_sobra(sid)
    mal += [k for k in ("asistencias", "sesiones", "proyectos", "pagos") if de_s[k]]
    de_q = {a["sesion_id"] for a in _union_asistencias_de(qid)}
    if any(e["sesion"] not in de_q for e in plan["asistencias"]):
        mal.append("asistencias_de_la_que_queda")
    for clave, enlace in (("sesiones", _base.L_PERSONA_SESIONES), ("proyectos", _base.L_PERSONA_PROYECTOS), ("pagos", _base.L_PERSONA_PAGOS)):
        if not set(_union_ids(plan, clave)) <= set(_union_leer_enlace(_base.T_PERSONAS, enlace, qid)):
            mal.append(clave + "_de_la_que_queda")
    return mal


def _union_cerrar(u, plan, antes, qid, sid, solo_contar=False, planeados=None):
    """Paso 8. Vuelve a leer las dos fichas y lo que cuelga; solo si todo cuadra pone la unión en `unida`, y vuelve a leer el registro.
    Con `solo_contar` (P11-6f) no relee: lo que se planeó se da por bueno (como en P11-6e), y solo queda en `planeados` el PATCH de `unida`."""
    uid = int(u["Id"])
    if solo_contar:
        _union_nc(True, planeados, "PATCH", _base.T_UNIONES_PERSONAS, {"Id": uid, "estado": "unida", "terminada_en": _ahora_utc()})
        return 200, {"ok": True, "estado": "unida", "union_id": uid, "queda": qid, "sobra": sid,
                     "movido": {k: len(plan[k]) for k in ("asistencias", "sesiones", "proyectos", "pagos")}}
    mal = _union_verificar(plan, antes, qid, sid)
    if mal:
        print(f"[warn] unión: lo releído no cuadra ({','.join(mal)})")
        return _union_sin_confirmar(uid, "no_cuadra", "Se escribió, pero al volver a leer las fichas algo no cuadra. NO la des por hecha: "
                                                        "usa «Terminar la unión» o mira las dos fichas.")
    _base.nc("PATCH", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records", body={"Id": uid, "estado": "unida", "terminada_en": _ahora_utc()})
    releida = _base.nc("GET", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records/{uid}")
    if not isinstance(releida, dict) or releida.get("estado") != "unida":
        return _union_sin_confirmar(uid, "registro_sin_confirmar")
    return 200, {"ok": True, "estado": "unida", "union_id": uid, "queda": qid, "sobra": sid,
                 "movido": {k: len(plan[k]) for k in ("asistencias", "sesiones", "proyectos", "pagos")}}


def _union_plan_al_dia(plan, qid, sid):
    """P11-6f (`continuar`): el cálculo supone que la ficha que sobra no tiene nada fuera del plan guardado. Si lo tiene, la unión de verdad lo
    agrega después de mover y hace una pasada más (con su `PATCH` del plan), y eso no se predice: `SinCalculoDeUnion("plan_incompleto")`.
    Solo lee: `_union_completar_plan` corre sobre una copia. En `unir` no debe saltar: su plan se armó con estas mismas lecturas, y las
    pruebas de `unir` (`test_calcular_grupo_f`) lo confirman. Esta función corre ANTES de planear nada. Si una lectura de aquí falla, el
    `except` de `_union_correr` levanta `fallo_despues_de_planear`; si la lectura trae un `_UnionParada` (p. ej. `asistencia_sin_sesion`,
    409), levanta `parada_despues_de_planear`. En los dos casos no se había planeado nada, así es también en `unir`, y el cálculo no lo
    contesta como 502 ni como 409 de la unión real."""
    lo = _union_lo_de_sobra(sid)
    if _union_completar_plan(json.loads(_union_json(plan)), lo, lambda: _union_asistencias_de(qid), _union_enlaces_de(qid)):
        raise SinCalculoDeUnion("plan_incompleto")


def _union_correr(u, solo_contar=False, planeados=None):
    """Pasos 2 a 8 de la unión del registro `u`, desde el plan guardado. Devuelve `(código, datos)`; sirve para empezar y para terminar.
    Con `solo_contar` (P11-6f) no escribe: las escrituras quedan en `planeados`, en orden. Tras los movimientos planeados la ficha que
    sobra queda sin nada (el plan se armó con todo lo que colgaba), así que no se relee lo que quedó: se usa esa lista vacía, y con ella
    el plan no cambia y la pasada termina en una vuelta. Eso vale solo sin escrituras ajenas sobre la ficha que sobra entre planear y mover (sin escrituras ajenas durante la unión; no medido, es una carrera). Cualquier parada o fallo DESPUÉS de planear escrituras no se predice: `SinCalculoDeUnion`. Con `solo_contar`, los dos motivos `parada_despues_de_planear` y `fallo_despues_de_planear` también salen de `_union_plan_al_dia`, que corre antes de planear (ver ahí)."""
    uid = int(u["Id"])
    try:
        qid, sid = int(u["queda_id"]), int(u["sobra_id"])
        plan, antes = json.loads(u["plan"]), json.loads(u["antes"])
        if not all(k in plan for k in ("titulo_q", "asistencias", "sesiones", "proyectos", "pagos")) \
                or not all(k in antes for k in ("queda", "sobra", "lee_de_sobra")):
            raise KeyError("el plan o el antes están incompletos")
    except (KeyError, TypeError, ValueError):
        return _union_sin_confirmar(uid, "registro_ilegible", "El registro de esta unión no se puede leer. No se tocó nada.")
    try:
        if solo_contar:
            _union_plan_al_dia(plan, qid, sid)
        for _ in range(UNION_PASADAS):
            _union_mover_asistencias(plan, qid, sid, solo_contar, planeados)
            _union_mover_sesiones(plan, qid, sid, solo_contar, planeados)
            _union_mover_proyectos_y_pagos(plan, qid, sid, solo_contar, planeados)
            if solo_contar:
                lo = {"asistencias": [], "sesiones": [], "proyectos": [], "pagos": [], "inscripciones": []}
            else:
                lo = _union_lo_de_sobra(sid)
            if _union_completar_plan(plan, lo, lambda: _union_asistencias_de(qid), _union_enlaces_de(qid)):
                _union_nc(solo_contar, planeados, "PATCH", _base.T_UNIONES_PERSONAS, {"Id": uid, "plan": _union_json(plan)})
            if not _union_queda_algo(lo):
                break
        else:
            return _union_sin_confirmar(uid, "no_termino", "A la ficha que sobra le siguen llegando cosas. Inténtalo de nuevo en un momento.")
        _union_marcar(antes, qid, sid, solo_contar, planeados)
        return _union_cerrar(u, plan, antes, qid, sid, solo_contar, planeados)
    except SinCalculoDeUnion:
        raise
    except _UnionParada as p:
        # Con `solo_contar`, este motivo también sale antes de planear: si `_union_plan_al_dia` trae un `_UnionParada`. El nombre dice «después»
        # por la pasada; ver `_union_plan_al_dia`.
        if solo_contar:
            raise SinCalculoDeUnion("parada_despues_de_planear")
        return p.codigo, dict(p.datos, union_id=uid, puede_terminar=False)
    except Exception as e:                                   # noqa: BLE001
        # Con `solo_contar`, este motivo también sale antes de planear: una lectura de `_union_plan_al_dia` que falla. Ver ahí.
        if solo_contar:
            raise SinCalculoDeUnion("fallo_despues_de_planear")
        print(f"[warn] unión: no se terminó ({type(e).__name__})")
        return _union_sin_confirmar(uid, "no_termino")
    finally:
        if not solo_contar:          # (P11-6f) el cálculo no tira cachés
            _union_tirar_caches()


# --- las dos entradas ---

def _union_cuerpo_del_registro(clave, qid, sid, plan, antes, quien):
    """La fila del registro de la unión, tal como la escribe `_union_apuntar` (P11-6f: la usa también el cálculo, sin escribirla)."""
    return {"clave": clave, "estado": "en_curso", "queda_id": qid, "sobra_id": sid, "plan": _union_json(plan), "antes": _union_json(antes),
            "creada_por": quien, "creada_en": _ahora_utc()}


def _union_apuntar(clave, qid, sid, plan, antes, quien):
    """Paso 1. Escribe la fila del registro y la vuelve a leer por su clave; si no se confirma, se para sin haber movido nada."""
    cuerpo = _union_cuerpo_del_registro(clave, qid, sid, plan, antes, quien)
    try:
        _base.nc("POST", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records", body=cuerpo)
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unión: el registro no confirmó la escritura ({type(e).__name__})")
    try:
        filas = _union_filas_del_registro(f"(clave,eq,{clave})")
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unión: no se pudo releer el registro ({type(e).__name__})")
        filas = []
    u = next((f for f in filas if f.get("clave") == clave and f.get("estado") == "en_curso" and f.get("plan") == cuerpo["plan"]
              and f.get("antes") == cuerpo["antes"] and _union_numero(f.get("queda_id")) == qid and _union_numero(f.get("sobra_id")) == sid), None)
    if u is None or isinstance(u.get("Id"), bool) or not isinstance(u.get("Id"), int):
        raise _union_no(502, "no_se_pudo_apuntar", "No se pudo apuntar la unión, así que no se movió nada. Inténtalo otra vez.", estado="sin_confirmar")
    return u


def _union_planear(id_a, id_b, resoluciones, queda_visto=None):
    """Paso 0, sin escribir. Devuelve `(qid, sid, plan, antes)` o levanta `_UnionParada` si algo impide unir."""
    codigo, datos, contexto = _union_revisar_completo(id_a, id_b)
    if codigo != 200:
        raise _UnionParada(codigo, datos)
    if not datos["unible"]:
        raise _union_no(409, "no_unible", "Estas dos fichas no se pueden unir ahora.", motivos=datos["motivos"])
    q, s = contexto
    if queda_visto is not None and q["Id"] != queda_visto:
        raise _union_no(409, "cambio_quien_queda", "La ficha que queda ya no es la que se vio al revisar. No se hizo nada: hay que revisar de nuevo.")
    cuerpo, faltan, malas = _union_resolver(datos["casillas"], q, s, resoluciones)
    if malas:
        raise _union_no(409, "resolucion_no_ofrecida", "Hay una resolución que no es una de las opciones ofrecidas.", casillas=malas)
    if faltan:
        raise _union_no(409, "falta_resolver", "Faltan casillas por resolver.", casillas=faltan)
    qid, sid = q["Id"], s["Id"]
    lo = _union_lo_de_sobra(sid)
    if lo["inscripciones"]:
        raise _union_no(409, "inscripciones_enlazadas", "La ficha que sobra tiene inscripciones enlazadas que la App no sabe mover.")
    sin_terminar = _union_en_curso()
    mias = _union_de_la_ficha(sin_terminar, qid) + _union_de_la_ficha(sin_terminar, sid)
    if mias:
        raise _union_no(409, "union_en_curso", "Una de las dos fichas tiene otra unión sin terminar.", union_id=int(mias[0]["Id"]))
    nombre = _union_texto(cuerpo["nombre"]) if "nombre" in cuerpo else _union_texto(q.get("nombre"))
    plan = {"titulo_q": nombre or f"persona {qid}", "asistencias": [], "sesiones": [], "proyectos": [], "pagos": []}
    _union_completar_plan(plan, lo, lambda: _union_asistencias_de(qid), _union_enlaces_de(qid))
    antes = {"queda": {c: {"antes": q.get(c), "despues": v} for c, v in cuerpo.items()},
             "sobra": {c: {"antes": s.get(c), "despues": None} for c in UNION_COLUMNAS_QUE_SE_VACIAN},
             "lee_de_sobra": {c: _union_texto(s.get(c)) for c in cuerpo if c not in UNION_COLUMNAS_QUE_SE_VACIAN}}
    antes["sobra"]["unida_a"] = {"antes": None, "despues": qid}
    return qid, sid, plan, antes


def unir_fichas(id_a, id_b, resoluciones, clave, quien, queda_visto=None, solo_contar=False, planeados=None):
    """Une las fichas `id_a` e `id_b`. Devuelve `(código, datos)`. Quién queda lo decide el servidor (`union_quien_queda`), y las
    casillas que chocan las vuelve a calcular con las fichas leídas ahora: `resoluciones` es `{casilla: opción}` (en teléfonos y correos,
    la lista de los que se quedan, el primero principal). `clave` identifica el intento: repetirlo no hace otra unión.
    `queda_visto` (opcional): el `Id` de la ficha que quien llama vio que quedaba; si ahora quedaría otra, no une y no escribe (409 `cambio_quien_queda`).
    Sin él se porta como siempre (así la llama `recibir_y_unir`, que no manda resoluciones)."""
    if not _base.T_UNIONES_PERSONAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede unir ahora: falta conectar el registro de uniones. No se hizo nada."}
    if not isinstance(clave, str) or not _RE_CLAVE_DE_UNION.fullmatch(clave):
        return 400, {"ok": False, "motivo": "clave", "error": "Falta la clave del intento."}
    with _UNION_LOCK:
        try:
            previas = _union_filas_del_registro(f"(clave,eq,{clave})")
            if previas:
                u = previas[0]
                if {_union_numero(u.get("queda_id")), _union_numero(u.get("sobra_id"))} != {id_a, id_b}:
                    return 409, {"ok": False, "motivo": "clave_repetida", "error": "Esa clave ya se usó para otras fichas."}
                if u.get("estado") == "unida":
                    return 200, {"ok": True, "estado": "unida", "ya_estaba": True, "union_id": int(u["Id"]),
                                 "queda": int(u["queda_id"]), "sobra": int(u["sobra_id"])}
                if u.get("estado") != "en_curso":
                    return 409, {"ok": False, "motivo": "union_en_otro_estado", "error": "Esa unión ya no se puede terminar.", "union_id": int(u["Id"])}
                if solo_contar:                              # (P11-6f) terminar una unión a medias no es `unir`: no se predice aquí
                    raise SinCalculoDeUnion("union_a_medias")
                return _union_correr(u)
            qid, sid, plan, antes = _union_planear(id_a, id_b, resoluciones, queda_visto)
            if solo_contar:
                # (P11-6f) el registro no se escribe ni se vuelve a leer: su `Id` es el previsto, y se planea su alta tal como la escribe `_union_apuntar`
                u = {"Id": PREVISTO_ID_BASE, "queda_id": qid, "sobra_id": sid, "plan": _union_json(plan), "antes": _union_json(antes)}
                _union_nc(True, planeados, "POST", _base.T_UNIONES_PERSONAS, _union_cuerpo_del_registro(clave, qid, sid, plan, antes, quien))
            else:
                u = _union_apuntar(clave, qid, sid, plan, antes, quien)
        except _UnionParada as p:
            return p.codigo, p.datos
        except _base.SoloLectura:
            raise
        except SinCalculoDeUnion:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] unión: no se pudo comprobar ({type(e).__name__})")
            return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer la base para unir. No se hizo nada. Inténtalo en un momento."}
        return _union_correr(u, solo_contar, planeados)


def continuar_union(ficha_id, solo_contar=False, planeados=None):
    """Termina la unión sin terminar de la ficha `ficha_id` (sea la que queda o la que sobra). Devuelve `(código, datos)`.
    Con `solo_contar` (P11-6f, el cálculo de `continuar`) no escribe. Los rechazos que se contestan ANTES de planear son los mismos que la
    unión real: 503 `sin_registro`, 502 `no_se_pudo_comprobar` (lectura del registro), 404 `sin_union_en_curso` y 502 `registro_ilegible`
    (plan o antes incompletos). Después de planear, o si una lectura previa para o falla (`_union_plan_al_dia`), el cálculo contesta
    404 «sin cálculo» (`SinCalculoDeUnion`), no el código de la unión real."""
    if not _base.T_UNIONES_PERSONAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede unir ahora: falta conectar el registro de uniones. No se hizo nada."}
    with _UNION_LOCK:
        try:
            mias = _union_de_la_ficha(_union_filas_del_registro("(estado,eq,en_curso)"), ficha_id)
        except _base.SoloLectura:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] unión: no se pudo leer el registro ({type(e).__name__})")
            return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer el registro de uniones. Inténtalo en un momento."}
        if not mias:
            return 404, {"ok": False, "motivo": "sin_union_en_curso", "error": "Esta ficha no tiene una unión sin terminar."}
        return _union_correr(mias[0], solo_contar, planeados)


# ---------- LA UNIÓN: deshacer ----------
# Deshacer sigue los pasos de la unión al revés, con lo que el registro guardó (`plan` y `antes`): devuelve las casillas de la ficha que quedó y de la
# que sobró, vuelve a crear las asistencias de la que sobró y devuelve los enlaces. Cada paso mira antes de escribir y se puede repetir: si se corta,
# volver a pedir «deshacer» sigue desde donde quedó (estado `deshaciendo`). Lo que alguien cambió después de unir no se pisa: se lista.
# Se pone `deshecha` solo después de volver a leer las dos fichas y lo que cuelga de ellas.
_DESHACER_TEXTO_SIN_CONFIRMAR = ("No se terminó de deshacer la unión. Las dos fichas pueden haber quedado a medias: ábrelas y vuelve a pulsar "
                                 "«Deshacer la unión». No la des por deshecha.")


def _deshacer_sin_confirmar(union_id, motivo, texto=_DESHACER_TEXTO_SIN_CONFIRMAR):
    return 502, {"ok": False, "estado": "sin_confirmar", "sin_confirmar": True, "motivo": motivo, "union_id": union_id,
                 "puede_deshacer": True, "error": texto}


def _deshacer_elegir(filas, ficha_id):
    """La unión de `ficha_id` que se deshace, entre las filas del registro de esa ficha: la que está sin terminar (`en_curso` o `deshaciendo`);
    si no hay, la última `unida` de la que ella es la que queda. `None` si no hay ninguna."""
    suyas = sorted((f for f in filas if ficha_id in (_union_numero(f.get("queda_id")), _union_numero(f.get("sobra_id")))), key=lambda f: int(f["Id"]))
    sin_terminar = [f for f in suyas if f.get("estado") in ("en_curso", "deshaciendo")]
    if sin_terminar:
        return sin_terminar[-1]
    unidas = [f for f in suyas if f.get("estado") == "unida" and _union_numero(f.get("queda_id")) == ficha_id]
    return unidas[-1] if unidas else None


def _deshacer_no_es_del_aviso():
    return 409, {"ok": False, "motivo": "no_es_la_union_del_aviso",
                 "error": "La unión que tiene esa ficha ahora no es la de este aviso. No se hizo nada."}


def union_que_se_puede_deshacer(ficha_id):
    """`{id, estado, queda, sobra}` de la unión de la ficha que se puede deshacer, o `None`. Es una lectura del registro; sin registro no lee nada."""
    if not _base.T_UNIONES_PERSONAS:
        return None
    filas = _union_filas_del_registro(f"(queda_id,eq,{int(ficha_id)})~or(sobra_id,eq,{int(ficha_id)})")
    u = _deshacer_elegir(filas, int(ficha_id))
    return None if u is None else {"id": int(u["Id"]), "estado": u["estado"], "queda": _union_numero(u.get("queda_id")), "sobra": _union_numero(u.get("sobra_id"))}


def _deshacer_queda(antes, qid):
    """Paso a. Cada casilla que la unión cambió en la ficha que quedó vuelve a lo que tenía, si sigue como la unión la dejó.
    Devuelve `(no_devuelto, rechazadas, contactos)`: las que cambiaron después, y los teléfonos y correos que tiene ahora."""
    contactos = [c for cols in UNION_GRUPOS.values() for c in cols]
    q = _union_leer_ficha(qid, list(dict.fromkeys(list(antes["queda"]) + contactos)) + ["unida_a"])
    if q is None:
        raise _union_no(409, "ficha_desaparecio", "Una de las dos fichas ya no está en la base.")
    if ficha_unida(q):
        raise _union_no(409, "queda_unida", "La ficha que quedó se unió después a otra. Primero hay que deshacer esa unión.")
    cuerpo, no = {}, []
    for c, d in antes["queda"].items():
        if _union_mismo(c, q.get(c), d["antes"]):
            continue
        if _union_mismo(c, q.get(c), d["despues"]):
            cuerpo[c] = d["antes"]
        else:
            no.append({"casilla": c, "ficha": "queda", "por_que": "cambio_despues"})
    if cuerpo:
        _union_escribir_ficha(qid, cuerpo)
    return no, {n["casilla"] for n in no}, {c: cuerpo[c] if c in cuerpo else q.get(c) for c in contactos}


def _deshacer_sobra(antes, qid, sid, rechazadas, contactos_de_q):
    """Paso b. La ficha que sobró recupera sus casillas y se le quita la marca. Un teléfono o correo que no pudo salir de la ficha que quedó
    no se le devuelve (quedaría en las dos); una casilla que ya tiene otro valor no se pisa. Devuelve lo que no se devolvió."""
    s = _union_leer_ficha(sid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a"])
    if s is None:
        raise _union_no(409, "ficha_desaparecio", "Una de las dos fichas ya no está en la base.")
    if ficha_unida(s) and _union_numero(s.get("unida_a")) != qid:
        raise _union_no(409, "cambio_mientras_deshacias", "La ficha que sobró se unió a otra. No se siguió.")
    grupo_con_rechazo = {g for g, cols in UNION_GRUPOS.items() if any(c in rechazadas for c in cols)}
    cuerpo, no = {}, []
    for c in UNION_COLUMNAS_QUE_SE_VACIAN:
        valor = antes["sobra"][c]["antes"]
        if _union_texto(valor) == "" or _union_mismo(c, s.get(c), valor):
            continue
        if _union_texto(s.get(c)) != "":
            no.append({"casilla": c, "ficha": "sobra", "por_que": "ya_tiene_otro_valor"})
            continue
        grupo = next((g for g, cols in UNION_GRUPOS.items() if c in cols), None)
        if grupo in grupo_con_rechazo and any(_union_mismo(c2, contactos_de_q.get(c2), valor) for c2 in UNION_GRUPOS[grupo]):
            no.append({"casilla": c, "ficha": "sobra", "por_que": "se_quedo_en_la_que_quedo"})
            continue
        cuerpo[c] = valor
    if ficha_unida(s):
        cuerpo["unida_a"] = None
    if cuerpo:
        _union_escribir_ficha(sid, cuerpo)
    return no


def _deshacer_asistencias(plan, qid, sid):
    """Paso c. Por cada asistencia del plan: si la que sobró no tiene una en esa sesión se le crea, y después, si la unión se la había traído
    (`mover`), se borra la de la que quedó."""
    de_s, de_q = {}, {}
    for destino, ficha in ((de_s, sid), (de_q, qid)):
        for a in _union_asistencias_de(ficha):
            destino.setdefault(a["sesion_id"], []).append(a)
    for e in plan["asistencias"]:
        ses = e["sesion"]
        if not de_s.get(ses):
            de_s[ses] = [{"Id": _union_crear_asistencia(e, sid, e.get("titulo"))}]
        else:
            aid = de_s[ses][0]["Id"]
            _union_asegurar_enlace(_base.T_ASISTENCIAS, _base.L_ASIS_PERSONA, aid, sid)
            _union_asegurar_enlace(_base.T_ASISTENCIAS, _base.L_ASIS_SESION, aid, ses)
        if e["accion"] == "mover":
            for a in de_q.get(ses, []):
                _base.nc("DELETE", f"/api/v2/tables/{_base.T_ASISTENCIAS}/records", body={"Id": a["Id"]})
            de_q[ses] = []


def _deshacer_enlaces(entradas, tabla, enlace_del_registro, enlace_de_la_ficha, qid, sid):
    """Paso d, sesiones y proyectos. Cada registro del plan se liga otra vez a la que sobró y, si la unión se lo había traído, se desliga de la que quedó."""
    if not entradas:
        return
    de_s = _union_leer_enlace(_base.T_PERSONAS, enlace_de_la_ficha, sid)
    de_q = _union_leer_enlace(_base.T_PERSONAS, enlace_de_la_ficha, qid)
    for e in entradas:
        if e["id"] not in de_s:
            _union_ligar(tabla, enlace_del_registro, e["id"], [sid])
        if e["accion"] == "mover" and e["id"] in de_q:
            _base.nc_unlink(tabla, enlace_del_registro, e["id"], [qid])


def _deshacer_pagos(plan, qid, sid):
    """Paso d, pagos: se ligan a la que sobró y se desligan de la que quedó desde el lado de la ficha, una llamada cada uno."""
    if not plan["pagos"]:
        return
    de_s = _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, sid)
    de_q = _union_leer_enlace(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, qid)
    volver = [e["id"] for e in plan["pagos"] if e["id"] not in de_s]
    if volver:
        _union_ligar(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, sid, volver)
    quitar = [e["id"] for e in plan["pagos"] if e["accion"] == "mover" and e["id"] in de_q]
    if quitar:
        _base.nc_unlink(_base.T_PERSONAS, _base.L_PERSONA_PAGOS, qid, quitar)


def _deshacer_verificar(plan, antes, qid, sid, no):
    """Paso e, la lectura. Devuelve la lista de lo que no cuadra (vacía si todo quedó como el registro dice)."""
    lq = {n["casilla"] for n in no if n["ficha"] == "queda"}
    ls = {n["casilla"] for n in no if n["ficha"] == "sobra"}
    q = _union_leer_ficha(qid, list(antes["queda"]) + ["unida_a"])
    s = _union_leer_ficha(sid, list(UNION_COLUMNAS_QUE_SE_VACIAN) + ["unida_a"])
    if q is None or s is None:
        return ["ficha"]
    mal = []
    if ficha_unida(q):
        mal.append("queda_marcada")
    if ficha_unida(s):
        mal.append("sobra_marcada")
    mal += [c for c, d in antes["queda"].items() if c not in lq and not _union_mismo(c, q.get(c), d["antes"])]
    mal += [c for c in UNION_COLUMNAS_QUE_SE_VACIAN
            if c not in ls and _union_texto(antes["sobra"][c]["antes"]) != "" and not _union_mismo(c, s.get(c), antes["sobra"][c]["antes"])]
    de_s = {a["sesion_id"] for a in _union_asistencias_de(sid)}
    de_q = {a["sesion_id"] for a in _union_asistencias_de(qid)}
    if any(e["sesion"] not in de_s or (e["accion"] == "mover" and e["sesion"] in de_q) for e in plan["asistencias"]):
        mal.append("asistencias")
    for clave, enlace in (("sesiones", _base.L_PERSONA_SESIONES), ("proyectos", _base.L_PERSONA_PROYECTOS), ("pagos", _base.L_PERSONA_PAGOS)):
        if plan[clave]:
            en_s, en_q = set(_union_leer_enlace(_base.T_PERSONAS, enlace, sid)), set(_union_leer_enlace(_base.T_PERSONAS, enlace, qid))
            if any(e["id"] not in en_s or (e["accion"] == "mover" and e["id"] in en_q) for e in plan[clave]):
                mal.append(clave)
    return mal


def _deshacer_correr(u, quien):
    """Deshace el registro `u` (`unida`, a medias o `deshaciendo`), de los pasos a a e. Devuelve `(código, datos)`; sirve para empezar y para seguir."""
    uid = int(u["Id"])
    try:
        qid, sid = int(u["queda_id"]), int(u["sobra_id"])
        plan, antes = json.loads(u["plan"]), json.loads(u["antes"])
        if not all(k in plan for k in ("asistencias", "sesiones", "proyectos", "pagos")) \
                or not all(k in antes for k in ("queda", "sobra")) or not all(c in antes["sobra"] for c in UNION_COLUMNAS_QUE_SE_VACIAN):
            raise KeyError("el plan o el antes están incompletos")
    except (KeyError, TypeError, ValueError):
        return _deshacer_sin_confirmar(uid, "deshacer_registro_ilegible", "El registro de esta unión no se puede leer. No se tocó nada.")
    try:
        marca = _union_leer_ficha(qid, ["unida_a"])
        if marca is None:
            raise _union_no(409, "ficha_desaparecio", "Una de las dos fichas ya no está en la base.")
        if ficha_unida(marca):
            raise _union_no(409, "queda_unida", "La ficha que quedó se unió después a otra. Primero hay que deshacer esa unión.")
        if u.get("estado") != "deshaciendo":
            _base.nc("PATCH", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records", body={"Id": uid, "estado": "deshaciendo"})
            if (_base.nc("GET", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records/{uid}") or {}).get("estado") != "deshaciendo":
                return _deshacer_sin_confirmar(uid, "deshacer_no_se_pudo_apuntar", "No se pudo apuntar que se iba a deshacer, así que no se tocó nada.")
        with _FICHA_TELEFONO_LOCK, _candado_de_ficha(min(qid, sid)), _candado_de_ficha(max(qid, sid)):
            try:
                no, rechazadas, contactos = _deshacer_queda(antes, qid)
                no += _deshacer_sobra(antes, qid, sid, rechazadas, contactos)
            finally:
                _union_tirar_caches()      # la cámara lee las caras de una caché: tiene que verlas como quedaron
        with _candado_de_ficha(min(qid, sid)), _candado_de_ficha(max(qid, sid)):
            _deshacer_asistencias(plan, qid, sid)
            _deshacer_enlaces(plan["sesiones"], _base.T_SESIONES, _base.L_MUSICOS, _base.L_PERSONA_SESIONES, qid, sid)
            _deshacer_enlaces(plan["proyectos"], _base.T_PROYECTOS, _base.L_PROY_MIEMBROS, _base.L_PERSONA_PROYECTOS, qid, sid)
            _deshacer_pagos(plan, qid, sid)
        mal = _deshacer_verificar(plan, antes, qid, sid, no)
        if mal:
            print(f"[warn] unión: lo releído al deshacer no cuadra ({','.join(mal)})")
            return _deshacer_sin_confirmar(uid, "deshacer_no_cuadra", "Se escribió, pero al volver a leer las fichas algo no cuadra. NO la des por deshecha: "
                                                                       "vuelve a pulsar «Deshacer la unión» o mira las dos fichas.")
        _base.nc("PATCH", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records", body={"Id": uid, "estado": "deshecha", "deshecha_por": quien, "deshecha_en": _ahora_utc()})
        releida = _base.nc("GET", f"/api/v2/tables/{_base.T_UNIONES_PERSONAS}/records/{uid}")
        if not isinstance(releida, dict) or releida.get("estado") != "deshecha":
            return _deshacer_sin_confirmar(uid, "deshacer_registro_sin_confirmar")
        return 200, dict({"ok": True, "estado": "deshecha", "union_id": uid, "queda": qid, "sobra": sid,
                          "sobra_nombre": _union_texto(antes["sobra"]["nombre"]["antes"]), "no_devuelto": no,
                          "devuelto": {k: len(plan[k]) for k in ("asistencias", "sesiones", "proyectos", "pagos")}},
                         **_deshacer_apunte(u, qid, sid, quien))
    except _UnionParada as p:
        return p.codigo, dict(p.datos, union_id=uid, puede_deshacer=False)
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unión: no se terminó de deshacer ({type(e).__name__})")
        return _deshacer_sin_confirmar(uid, "no_se_deshizo")
    finally:
        _union_tirar_caches()


def deshacer_union(ficha_id, quien, union_visto=None, sobra_esperada=None):
    """Deshace la unión de `ficha_id` (la que quedó, o cualquiera de las dos si la unión está a medias). Devuelve `(código, datos)`.
    `union_visto` (opcional): el `Id` de la unión que quien llama vio; si la que toca deshacer es otra, no hace nada; si ya está deshecha, lo dice.
    `sobra_esperada` (opcional): la ficha que tiene que haber sobrado en esa unión (la usa el renglón de «Por resolver», que solo puede deshacer la unión de SU
    aviso); si la unión que toca es con otra ficha, no hace nada, no apunta nada y contesta 409 `no_es_la_union_del_aviso`."""
    if not _base.T_UNIONES_PERSONAS:
        return 503, {"ok": False, "motivo": "sin_registro", "error": "No se puede deshacer ahora: falta conectar el registro de uniones. No se hizo nada."}
    with _UNION_LOCK:
        try:
            filas = _union_filas_del_registro(f"(queda_id,eq,{int(ficha_id)})~or(sobra_id,eq,{int(ficha_id)})")
            u = _deshacer_elegir(filas, int(ficha_id))
            if union_visto is not None:
                visto = next((f for f in filas if _union_numero(f.get("Id")) == union_visto), None)
                if visto is not None and visto.get("estado") == "deshecha":
                    q, so = _union_numero(visto.get("queda_id")), _union_numero(visto.get("sobra_id"))
                    if sobra_esperada is not None and so != sobra_esperada:
                        return _deshacer_no_es_del_aviso()
                    return 200, dict({"ok": True, "estado": "deshecha", "ya_estaba": True, "union_id": union_visto, "queda": q, "sobra": so},
                                     **_deshacer_apunte(visto, q, so, quien))      # si la respuesta anterior se perdió antes del apunte, este pedido lo termina
                if visto is None or u is None or int(u["Id"]) != union_visto:
                    return 409, {"ok": False, "motivo": "no_es_esa_union", "error": "La unión que se iba a deshacer ya no es la que toca. No se hizo nada."}
            if sobra_esperada is not None and u is not None and _union_numero(u.get("sobra_id")) != sobra_esperada:
                return _deshacer_no_es_del_aviso()
            if u is None:
                return 404, {"ok": False, "motivo": "sin_union_para_deshacer", "error": "Esta ficha no tiene una unión que se pueda deshacer."}
        except _base.SoloLectura:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[warn] unión: no se pudo leer el registro para deshacer ({type(e).__name__})")
            return 502, {"ok": False, "motivo": "no_se_pudo_comprobar", "error": "No se pudo leer el registro de uniones. No se hizo nada. Inténtalo en un momento."}
        return _deshacer_correr(u, quien)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# UNIR SOLA (parte 6 del diseño, S3b): `recibir_y_unir` pasa el dato por la puerta y, si dice «dos fichas, la misma persona», llama a
# `unir_fichas` fuera del candado de la puerta.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
NO_SON_LA_MISMA_ORIGEN = "no-son-la-misma"
UNION_SOLA_QUIEN = {"meta": "puerta (WhatsApp)", "dictado": "puerta (número dictado)", "correo": "puerta (correo)"}
UNION_SOLA_QUIEN_SIN_PRUEBA = "puerta"      # lo que queda en `creada_por` si la unión no trae prueba conocida
UNION_SOLA_VALOR = {"meta": "telefono", "dictado": "telefono", "correo": "correo"}


def _no_son_la_misma_clave(id_a, id_b):
    return "nosonlamisma-%d-%d" % (min(int(id_a), int(id_b)), max(int(id_a), int(id_b)))


def no_son_la_misma(id_a, id_b):
    """Si la bandeja trae el apunte «no son la misma» de las fichas `id_a` e `id_b`; levanta si no se pudo leer."""
    if not _base.T_BANDEJA_PERSONAS:
        raise ValueError("falta la bandeja")
    ya = _base.nc("GET", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records",
              query={"where": f"(clave,eq,{_no_son_la_misma_clave(id_a, id_b)})", "fields": "Id", "limit": 1})
    if not isinstance(ya, dict) or not isinstance(ya.get("list"), list):
        raise ValueError("la bandeja no vino como lista")
    return bool(ya["list"])


def apuntar_no_son_la_misma(id_a, id_b, quien):
    """Apunta en la bandeja que las fichas `id_a` e `id_b` no son la misma persona; devuelve si quedó apuntado."""
    try:
        if not no_son_la_misma(id_a, id_b):
            _base.nc("POST", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records",
                 body={"clave": _no_son_la_misma_clave(id_a, id_b), "origen": NO_SON_LA_MISMA_ORIGEN, "estado": "no_son_la_misma",
                       "ficha_id": min(int(id_a), int(id_b)), "otra_ficha_id": max(int(id_a), int(id_b)), "resuelto_por": quien})
        return no_son_la_misma(id_a, id_b)
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] no son la misma: no se pudo apuntar ({type(e).__name__})")
        return False


def _union_la_hizo_la_puerta(registro):
    """¿Esta fila del registro de uniones la escribió la puerta? Lo dice `creada_por`, que es el `quien` con que `_union_sola_unir` llamó a `unir_fichas`."""
    return isinstance(registro, dict) and registro.get("creada_por") in tuple(UNION_SOLA_QUIEN.values()) + (UNION_SOLA_QUIEN_SIN_PRUEBA,)


def _deshacer_apunte(registro, qid, sid, quien):
    """Al deshacer una unión: si la hizo la puerta, apunta «no son la misma» (la puerta no vuelve a unirlas) y dice si quedó apuntado
    (`{"no_son_la_misma": True|False}`, nunca True sin haberlo releído). Si no la hizo la puerta, no hace nada y no dice nada (`{}`)."""
    if not _union_la_hizo_la_puerta(registro):
        return {}
    if not (isinstance(qid, int) and isinstance(sid, int)):
        return {"no_son_la_misma": False}
    return {"no_son_la_misma": apuntar_no_son_la_misma(qid, sid, quien) is True}


def _union_sola_clave(E, id_a, id_b):
    """La clave de la unión: sale de la `clave` del dato; sin ella, de las dos fichas."""
    base = E["clave"] or "%d-%d" % (min(id_a, id_b), max(id_a, id_b))
    return "puerta-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:40]


def _union_sola_empezada(E):
    """La unión de este dato que quedó empezada o terminada, como `(queda, sobra, prueba)`, o `None`."""
    if not (E["clave"] and _base.T_UNIONES_PERSONAS):
        return None
    try:
        filas = _union_filas_del_registro(f"(clave,eq,{_union_sola_clave(E, 0, 0)})")
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unir sola: no se pudo leer el registro de uniones ({type(e).__name__})")
        return None
    for u in filas:
        if u.get("estado") in ("en_curso", "unida") and _union_numero(u.get("queda_id")) and _union_numero(u.get("sobra_id")):
            prueba = next((k for k, v in UNION_SOLA_QUIEN.items() if v == u.get("creada_por")), None)
            return _union_numero(u["queda_id"]), _union_numero(u["sobra_id"]), prueba
    return None


def _union_sola_unir(E, id_a, id_b, prueba):
    """Llama a `unir_fichas` y devuelve la unión como la cuenta la respuesta."""
    u = {"estado": None, "prueba": prueba, "ficha_id": id_a, "otra_ficha_id": id_b}
    codigo, datos = unir_fichas(id_a, id_b, {}, _union_sola_clave(E, id_a, id_b), UNION_SOLA_QUIEN.get(prueba, UNION_SOLA_QUIEN_SIN_PRUEBA))
    if codigo == 200 and datos.get("estado") == "unida":
        u.update(estado="unida", queda=datos["queda"], sobra=datos["sobra"], union_id=datos["union_id"])
    elif datos.get("sin_confirmar") or codigo == 502:
        u.update(estado="sin_confirmar", motivo=datos.get("motivo"))
    else:
        u.update(estado="no_se_pudo", codigo=codigo, motivo=datos.get("motivo"))
    return u


def _union_sola_guarda(prueba, q):
    """Si la guarda del crédito impide unir: la ficha `q` que quedaría tiene crédito y no tiene teléfono principal, y la prueba no es de WhatsApp."""
    credito, legible = _union_credito(q)
    return prueba != "meta" and legible and credito != 0 and not str(q.get("telefono") or "").strip()


def _union_sola_decidir(E, id_a, id_b, prueba, solo_contar):
    """Decide la unión de las dos fichas; contando dice lo que `revisar_union` ve, y lo que `unir_fichas` niega y `revisar_union` no ve, el conteo tampoco lo ve."""
    u = {"estado": None, "prueba": prueba, "ficha_id": id_a, "otra_ficha_id": id_b}
    try:
        if no_son_la_misma(id_a, id_b):
            u["estado"] = "no_son_la_misma"
            return u
        codigo, datos, contexto = _union_revisar_completo(id_a, id_b)
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unir sola: no se pudo comprobar ({type(e).__name__})")
        u.update(estado="sin_confirmar", motivo="no_se_pudo_comprobar")
        return u
    if contexto is not None:
        if _union_sola_guarda(prueba, contexto[0]):
            u["estado"] = "credito"
            return u
    if solo_contar:
        choques = (datos.get("choques") or []) if codigo == 200 else []
        u["estado"] = "sin_choques" if codigo == 200 and datos.get("unible") and not choques else "con_choques"
        if choques:
            u["choques"] = list(choques)
        return u
    return _union_sola_unir(E, id_a, id_b, prueba)


def _union_sola_responder(E, r, solo_contar, apuntar=True):
    if apuntar and not solo_contar and r["estado"] not in ("rechazado", "detenido"):
        _puerta_apuntar_en_bandeja(E, r)
    _puerta_registrar(E["origen"], r)
    return r


def _union_sola_unida(E, u, prueba):
    """Con las dos fichas ya unidas: vuelve a pasar el dato por la puerta y deja el aviso `unidas_solas`."""
    r = _puerta_recibir(E, False, None)
    r["avisos"].append(_puerta_aviso("unidas_solas", u["queda"], u["sobra"], prueba=prueba))
    r["union"] = u
    return r


def _union_sola_rechazo(dato, motivo):
    """La respuesta de rechazo de la puerta, con `motivo`, y su línea de registro."""
    r = dict(estado="rechazado", motivo=motivo, ficha_id=None, accion="no_tocada", valores={}, avisos=[], de=None, llave=None, releida=None,
             excepcion=None, etapa=None, rec=None, escrito=[])
    _puerta_registrar(dato.get("origen") if isinstance(dato, dict) and dato.get("origen") in PUERTA_ORIGENES else "desconocido", r)
    return r


UNION_SOLA_SENALADORES = (("telefono_meta", "telefono"), ("telefono_dicho", "telefono"), ("correo", "correo"))     # los valores de un dato de sistema que pueden señalar a otra ficha (`_puerta_decidir_automatico`: `ft` y `fc`)


def _union_sola_sin_lo_ajeno(dato, E, r, id_b):
    """Escribiendo, con el apunte «no son la misma» entre la ficha de quien escribe y la `id_b`: una persona ya dijo que no son la misma, así que NO queda nada por resolver
    contra esa ficha. NINGÚN valor del dato que sea de `id_b` se escribe (uno, dos o todos): cada uno queda `no_guardado/de_otra_ficha`. La ficha de quien escribe se completa con
    lo demás (una segunda pasada por la puerta con el dato sin esos valores; si la ficha acaba de nacer en esta misma vuelta, ya tiene lo suyo) y `estado` se recalcula:
    `aplicado` si no queda ningún aviso no informativo. Un valor que señale a una TERCERA ficha sin apunte sigue su camino normal (la segunda pasada lo avisa)."""
    try:
        otra = _puerta_leer_la_ficha(id_b)
    except _base.SoloLectura:
        raise
    except Exception as e:                                   # noqa: BLE001
        print(f"[warn] unir sola: no se pudo leer la ficha del apunte ({type(e).__name__})")
        r.update(estado="sin_confirmar", motivo="no_se_pudo_comprobar")
        return r
    L = E["L"]
    ajenos = [campo for campo, clase in UNION_SOLA_SENALADORES if L[campo][0] == "valor" and _puerta_ficha_tiene(otra, clase, L[campo][1])]
    d2 = {k: v for k, v in dato.items() if k not in ajenos}
    if r.get("accion") != "creada":
        try:
            E2 = _puerta_leer_entrada(d2)
        except _PuertaIlegible:
            E2 = None
        if E2 is not None:
            r2 = _puerta_recibir(E2, False, None)
            if r2["estado"] in ("aplicado", "por_resolver", "sin_confirmar"):
                r = r2
    for campo in ajenos:
        r["valores"][_puerta_clave_de_valor(campo, L)] = _puerta_valor("no_guardado", "de_otra_ficha")
    if r["estado"] in ("aplicado", "por_resolver"):
        r["estado"] = "por_resolver" if any(not a["informativo"] for a in r["avisos"]) else "aplicado"
    return r


def recibir_y_unir(dato, solo_contar=False):
    """Pasa `dato` de un sistema por la puerta y une solas las dos fichas cuando la puerta dice que son la misma persona; con `solo_contar` no escribe."""
    if isinstance(dato, dict) and dato.get("otros"):
        return _union_sola_rechazo(dato, "dato_de_sistema_con_otros")
    if isinstance(dato, dict) and dato.get("pantalla"):
        return _union_sola_rechazo(dato, "dato_de_pantalla")
    try:
        E = _puerta_leer_entrada(dato)
    except _PuertaIlegible as e:
        return _union_sola_rechazo(dato, str(e))
    empezada = None if solo_contar else _union_sola_empezada(E)
    if empezada is not None:                                 # un corte dejó la unión empezada o sin su aviso: se termina antes de pasar el dato
        u = _union_sola_unir(E, empezada[0], empezada[1], empezada[2])
        print("[UNION-SOLA] ficha=%s otra=%s prueba=%s resultado=%s" % (empezada[0], empezada[1], empezada[2], u["estado"]))
        if u["estado"] == "unida":
            return _union_sola_responder(E, _union_sola_unida(E, u, empezada[2]), False, apuntar=True)
        if u["estado"] == "sin_confirmar":
            r = dict(estado="sin_confirmar", motivo="union_sin_confirmar", ficha_id=None, accion="no_tocada", valores={}, avisos=[], de=None,
                     llave=None, releida=None, excepcion=None, etapa=None, rec=None, escrito=[], union=u)
            return _union_sola_responder(E, r, False, apuntar=False)
    r = _puerta_recibir(E, solo_contar, None)
    aviso = next((a for a in r["avisos"] if a["tipo"] == "misma_persona"), None)
    if aviso is None:
        return _union_sola_responder(E, r, solo_contar)
    id_a, id_b, prueba = aviso.get("ficha_id"), aviso.get("otra_ficha_id"), aviso.get("prueba")
    if id_a is None or id_b is None:
        r["union"] = {"estado": "alta_sin_evaluar" if solo_contar and aviso.get("ficha_nueva") else "sin_ficha", "prueba": prueba}
        return _union_sola_responder(E, r, solo_contar)
    u = _union_sola_decidir(E, id_a, id_b, prueba, solo_contar)
    print("[UNION-SOLA] ficha=%s otra=%s prueba=%s resultado=%s" % (id_a, id_b, prueba, u["estado"]))
    if u["estado"] == "unida":
        r = _union_sola_unida(E, u, prueba)
    elif u["estado"] == "no_son_la_misma":
        r["avisos"] = [a for a in r["avisos"] if a["tipo"] != "misma_persona"]
        clave = UNION_SOLA_VALOR.get(prueba)
        if clave in r["valores"] and r["valores"][clave].get("motivo") == "por_resolver":
            r["valores"][clave]["motivo"] = "de_otra_ficha"
        if not solo_contar:
            r = _union_sola_sin_lo_ajeno(dato, E, r, id_b)
    elif u["estado"] == "sin_confirmar":
        r.update(estado="sin_confirmar", motivo="union_sin_confirmar")
    r["union"] = u
    return _union_sola_responder(E, r, solo_contar, apuntar=r["estado"] != "sin_confirmar")


# ---------- LAS ANOTACIONES DE PERSONAS (permiso, baja y por dónde entró) — PIEZA 1: LEER (la escritura es la PIEZA 2, más abajo) ----------
# Diseño aprobado por Tiziano: `disenos/mercadeo/DISENO-personas-permiso-baja-origen.md` (secciones 4.1 a 4.3).
# LOS DATOS VIVEN EN UNA TABLA APARTE (`personas_anotaciones`, la crea la sala; su id llega por `NOCODB_T_PERSONAS_ANOTACIONES`) y NO en
# columnas de `personas`: una columna nueva ahí bloquea todas las uniones (`union_clasificar_columnas`). Las funciones de ESTA pieza solo LEEN: ninguna
# escribe nada, ni en `personas` ni en la tabla de anotaciones (lo vigilan `tests/test_anotaciones_leer.py` y `LasCincoRutas`). Quien escribe la tabla es
# `anotar_permiso` (permiso), `anotar_foto` (foto, D19a) y `anotar_origen_al_nacer` (origen), y nadie más.
# Sin la variable, la ficha no gana ninguna clave y nadie lee nada: la App contesta lo mismo que antes.
ANOTACIONES_PERMISOS = ("sin_preguntar", "si", "no", "baja")          # los únicos valores de un renglón `clase = permiso`
ANOTACIONES_FOTOS = ("si", "no")                                      # los únicos valores de un renglón `clase = foto` (D19a: permiso de usar las fotos); sin renglón, no se sabe
ANOTACIONES_CLASES = ("permiso", "origen", "foto")
# Columna → tipo de NocoDB. La tabla la crea la SALA con estas columnas (más el `Id` y las del sistema que NocoDB pone solo).
ANOTACIONES_COLUMNAS = {"ficha_id": "Number", "clase": "SingleLineText", "valor": "SingleLineText", "canal": "SingleLineText",
                        "dicho_el": "SingleLineText", "nota": "LongText", "quien": "SingleLineText", "cuando": "SingleLineText"}
ANOTACIONES_LEE = ("Id", "ficha_id", "clase", "valor", "canal", "dicho_el", "quien", "cuando")     # lo que se pide al leer (la nota no se necesita)
ANOTACIONES_PAGINAS_MAX = 500          # tope de seguridad contra un servidor que nunca dice «última»; no es una medición de nada


class _NoSeSupo(Exception):
    """Algo de lo que decide el estado no se pudo leer o no se entiende. `motivo` es un código corto, sin datos de nadie."""

    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


def _anotaciones_entero(v):
    """Un entero de verdad, o `None`. Un `True`, un decimal (aunque sea 7.0) o un texto (aunque sea «7») NO lo son: un tipo equivocado
    en un `Id`, un `ficha_id` o un `unida_a` es «no se pudo saber», no un número que se adivina. (Medido por la sala el 13-oct-2026: en
    producción esas columnas llegan como enteros.)"""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _anotaciones_leer_tabla(tabla, campos=None, where=None):
    """TODAS las filas de una tabla, página por página hasta la última, o `_NoSeSupo`. No se fía de `nc_list_all` (da por última una
    respuesta sin `pageInfo`). `campos` en `None` pide todas las columnas (sin `fields`, como `nc_list_all(tabla, {})`); `where` es el
    filtro de NocoDB tal cual (quien llama lo arma y lo valida). Es «no se pudo saber», nunca una lista corta que se da por buena, cuando: la respuesta no es una lista; falta
    `pageInfo.isLastPage` booleano; un renglón no es un objeto; en CUALQUIER página `totalRows` falta o no es un entero (texto, `None`,
    booleano, decimal); `totalRows` no es el mismo entero en todas las páginas; o en la última no coincide con lo recibido.
    DETECTA: que el total de filas cambie entre una página y la siguiente (un alta o un borrado a media lectura) o no cuadre con lo recibido;
    y, quienes la usan (`anotaciones_grupo` y `anotaciones_estado`), un `Id` repetido (una fila que se corrió de página).
    NO DETECTA: que se borre una fila y se cree otra durante la misma lectura, sin que el total cambie y sin repetir ningún `Id` (queda
    una fila sin leer y otra leída de más): lo único que la sala ha medido de cada página es `totalRows` e `isLastPage` (13-oct-2026), y ninguno
    cambia de valor con ese par. Un alta o un borrado justo durante la lectura da un «no se pudo saber» de más, transitorio: se acepta (falla cerrada)."""
    filas, desde, total = [], 0, None
    for _ in range(ANOTACIONES_PAGINAS_MAX):
        q = {} if campos is None else {"fields": campos}
        if where is not None:
            q["where"] = where
        q.update({"limit": 200, "offset": desde})
        pag = _base.nc("GET", f"/api/v2/tables/{tabla}/records", query=q)
        info = pag.get("pageInfo") if isinstance(pag, dict) else None
        trozo = pag.get("list") if isinstance(pag, dict) else None
        if not isinstance(trozo, list) or not isinstance(info, dict) or not isinstance(info.get("isLastPage"), bool):
            raise _NoSeSupo("lectura_sin_forma")
        if not all(isinstance(x, dict) for x in trozo):
            raise _NoSeSupo("fila_ilegible")
        visto = info.get("totalRows")
        if isinstance(visto, bool) or not isinstance(visto, int):
            raise _NoSeSupo("lectura_incompleta")
        if total is not None and visto != total:
            raise _NoSeSupo("lectura_cambio")           # la tabla cambió mientras se leía
        total = visto
        filas.extend(trozo)
        if info["isLastPage"]:
            if total != len(filas):
                raise _NoSeSupo("lectura_incompleta")
            return filas
        if not trozo:
            raise _NoSeSupo("lectura_incompleta")
        desde += len(trozo)
    raise _NoSeSupo("lectura_sin_fin")


def anotaciones_grupo(ficha_id, marcas):
    """El grupo de la ficha `ficha_id`: ella, más todas las fichas que hoy están unidas a ella siguiendo `unida_a` hasta el final
    (y si ella misma está unida, el grupo de la ficha donde terminó). `marcas` son las filas `{Id, unida_a}` de TODAS las fichas.
    Devuelve el conjunto de `Id`, o levanta `_NoSeSupo`. Función pura: no toca la red.
    «No se pudo saber» (nunca un grupo más chico) cuando: la ficha no está en `marcas`; un `Id` ilegible o repetido; una fila sin la clave `unida_a` (sin ella no se sabe si está unida); una marca que no es un
    número (podría apuntar a esta ficha); la cadena de la ficha o de alguna que llega a ella pasa de `SALTOS_DE_UNION` saltos; o la
    cadena de la ficha misma se corta o da vueltas. `unida_a` en `None`, vacía o en blanco es «no unida» (es lo que dice `ficha_unida`): no se
    puede distinguir de una ficha que nunca se unió, y no es un error. Una cadena ajena que muere en un `Id` que no existe, que da vueltas o que termina en
    OTRA ficha no llega a esta: se deja fuera (se sigue entera, sin tope, para saberlo)."""
    ids, padre = set(), {}
    for f in marcas:
        if not isinstance(f, dict):
            raise _NoSeSupo("ficha_ilegible")
        i = _anotaciones_entero(f.get("Id"))
        if i is None or i in ids or "unida_a" not in f:        # sin la clave no se sabe si está unida: NO es «no unida»
            raise _NoSeSupo("ficha_ilegible")
        ids.add(i)
        if ficha_unida(f):
            p = _anotaciones_entero(f.get("unida_a"))
            if p is None:
                raise _NoSeSupo("marca_ilegible")
            padre[i] = p
    q = _anotaciones_entero(ficha_id)
    if q is None or q not in ids:
        raise _NoSeSupo("ficha_no_esta")
    tope = _base.SALTOS_DE_UNION

    def seguir(i):
        """`(donde_termina, saltos)`; `donde_termina` es `None` si la cadena se corta o da vueltas."""
        visto, saltos = {i}, 0
        while i in padre:
            i, saltos = padre[i], saltos + 1
            if i not in ids or i in visto:
                return None, saltos
            visto.add(i)
        return i, saltos

    raiz, _ = seguir(q)
    if raiz is None:
        raise _NoSeSupo("cadena_rota")
    grupo = set()      # la ficha misma entra en el recorrido de abajo, que es donde se aplica el tope (a ella y a cada una que llega a su raíz)
    for i in ids:
        fin, n = seguir(i)
        if fin == raiz:
            if n > tope:
                raise _NoSeSupo("cadena_larga")
            grupo.add(i)
    return grupo


def _anotaciones_no_se_supo(motivo):
    # Sin la clave `permiso` a propósito: quien lea esto no puede tomar «no se supo» por «sin preguntar».
    return {"sabido": False, "motivo": motivo}


def anotaciones_estado(grupo, filas):
    """El estado de una persona, calculado AL LEER y sin tocar la red: `grupo` es el conjunto de `Id` de sus fichas
    (`anotaciones_grupo`) y `filas` las filas de la tabla de anotaciones.
      · PERMISO: gana el renglón de permiso con el `Id` MÁS ALTO de todo el grupo («gana lo último que se anotó», Tiziano). «Lo último» es el
        orden en que se anotó (el `Id` de la tabla), no la fecha `dicho_el` que escribe una persona; no hay empates (un `Id` repetido es «no se
        pudo saber»). Sin renglones de permiso en el grupo: `sin_preguntar`. «Desde cuándo», canal y quién salen del renglón que manda.
      · ORIGEN: al revés, el PRIMERO (el `Id` más bajo) de los renglones de origen del grupo: es la primera llegada. Sin renglón: `None`
        (sin anotar). Un valor que no se conoce se devuelve tal cual, sin adivinar. `origen_etiqueta` es el mismo origen en palabras para
        la pantalla (`origen_etiqueta`; `None` si no hay renglón; el valor tal cual si no tiene etiqueta).
      · `renglon_visto`: el `Id` del renglón de permiso que manda (o `None`), para que una escritura futura detecte que cambió.
    Falla CERRADA: lo que no se entiende da `{"sabido": False, "motivo": …}` y NUNCA un permiso: una fila que no es un objeto, con `Id` o
    `ficha_id` ilegible (podría ser de este grupo), un `Id` repetido, una `clase` que no es de las tres en una ficha del grupo, o un valor de
    permiso/origen/foto que no se conoce en el renglón que manda o en un renglón de origen o de foto del grupo. Los renglones de OTRAS fichas no cuentan.
      · FOTO (D19a): el renglón de foto con el `Id` MÁS ALTO del grupo («gana lo último»); sin renglón, `foto` trae `valor` None (no se sabe, nunca «no»).
    """
    try:
        grupo = {g for g in (_anotaciones_entero(x) for x in grupo)}
        if None in grupo or not grupo:
            raise _NoSeSupo("grupo_ilegible")
        vistos, permisos, origenes, fotos = set(), [], [], []
        for r in filas:
            if not isinstance(r, dict):
                raise _NoSeSupo("fila_ilegible")
            i, ficha = _anotaciones_entero(r.get("Id")), _anotaciones_entero(r.get("ficha_id"))
            if i is None or ficha is None or i in vistos:
                raise _NoSeSupo("fila_ilegible")
            vistos.add(i)
            if ficha not in grupo:
                continue
            clase = r.get("clase")
            if clase == "permiso":
                permisos.append((i, r))
            elif clase == "origen":
                origenes.append((i, r))
            elif clase == "foto":
                fotos.append((i, r))
            else:
                raise _NoSeSupo("clase_desconocida")
        salida = {"sabido": True, "permiso": "sin_preguntar", "desde": None, "canal": None, "quien": None, "origen": None, "origen_etiqueta": None,
                  "renglon_visto": None, "foto": {"valor": None, "quien": None, "cuando": None, "renglon": None}}
        if permisos:
            i, r = max(permisos, key=lambda t: t[0])
            if r.get("valor") not in ANOTACIONES_PERMISOS:
                raise _NoSeSupo("valor_desconocido")
            texto = lambda c: r.get(c) if isinstance(r.get(c), str) and r.get(c).strip() else None   # noqa: E731
            salida.update(permiso=r["valor"], desde=texto("dicho_el"), canal=texto("canal"), quien=texto("quien"), renglon_visto=i)
        if origenes:
            _, r = min(origenes, key=lambda t: t[0])
            if not isinstance(r.get("valor"), str) or not r["valor"].strip():
                raise _NoSeSupo("valor_desconocido")
            salida["origen"] = r["valor"].strip()
            salida["origen_etiqueta"] = origen_etiqueta(salida["origen"])
        if fotos:
            i, r = max(fotos, key=lambda t: t[0])
            if r.get("valor") not in ANOTACIONES_FOTOS:
                raise _NoSeSupo("valor_desconocido")
            salida["foto"] = {"valor": r["valor"], "quien": _texto_de_anotacion(r, "quien"), "cuando": _texto_de_anotacion(r, "cuando"), "renglon": i}
        return salida
    except _NoSeSupo as e:
        return _anotaciones_no_se_supo(e.motivo)


def _anotaciones_leer(persona_id, tabla):
    """LA lectura de las anotaciones: las marcas de unión de TODAS las fichas, el grupo de `persona_id`, la tabla entera y el estado.
    Devuelve `(grupo, filas, estado)` (el estado puede ser el de «no se pudo saber») o levanta lo que la red levante. Es la única que arma
    el estado: la ficha (`anotaciones_de_la_ficha`) y la escritura de permiso (`anotar_permiso`) leen por aquí."""
    marcas = _anotaciones_leer_tabla(_base.T_PERSONAS, "Id,unida_a")
    grupo = anotaciones_grupo(persona_id, marcas)
    filas = _anotaciones_leer_tabla(tabla, ",".join(ANOTACIONES_LEE))
    return grupo, filas, anotaciones_estado(grupo, filas)


def _permiso_de_la_ficha_sin_levantar(persona_id):
    """Lo que la ficha del portal muestra bajo la clave `mercadeo` (solo para VER), o `None` si no hay dónde leer (la variable
    `NOCODB_T_PERSONAS_ANOTACIONES` está vacía: la ficha queda como siempre, sin la clave). No levanta (salvo `BaseException`) y NUNCA contesta «sin preguntar»
    porque algo falló: cualquier error de lectura (NocoDB caído o con otro código, una respuesta rara, un total que no cuadra, una cadena de
    uniones rota) da `{"sabido": False, "motivo": …}`. Lee la tabla de anotaciones y las marcas de unión de TODAS las fichas
    (`Id` y `unida_a`) cada vez, sin caché."""
    try:
        tabla = (_base.T_PERSONAS_ANOTACIONES or "").strip()
    except Exception:  # noqa: BLE001
        print("[PERSONAS-ANOTACIONES] no se pudo leer (variable ilegible)")
        return _anotaciones_no_se_supo("lectura_fallo")
    if not tabla:
        return None
    try:
        return _anotaciones_leer(persona_id, tabla)[2]
    except _NoSeSupo as e:
        print(f"[PERSONAS-ANOTACIONES] no se pudo saber ({e.motivo})")
        return _anotaciones_no_se_supo(e.motivo)
    except Exception as e:  # noqa: BLE001
        print(f"[PERSONAS-ANOTACIONES] no se pudo leer ({type(e).__name__})")
        return _anotaciones_no_se_supo("lectura_fallo")


def anotaciones_de_la_ficha(persona_id):
    """Lo que la ficha del portal muestra bajo la clave `mercadeo`: la lectura de `_permiso_de_la_ficha_sin_levantar`.
    Es la ÚNICA función que arma esa clave: la llama `_portal_ficha_de_fila` (`tests/test_anotaciones_leer.py`)."""
    return _permiso_de_la_ficha_sin_levantar(persona_id)


# ---------- LAS ANOTACIONES DE PERSONAS — PIEZA 2: ANOTAR PERMISO Y BAJA (servidor) ----------
# Diseño aprobado por Tiziano: `disenos/mercadeo/DISENO-personas-permiso-baja-origen.md` (4.4 y garantías G1, G5 a G11, G13 y G15).
# UNA ruta, `POST /api/portal-personas/<id>/permiso`, detrás de la puerta de Personas (`Handler.portal_personas`). Esta función no sabe de HTTP.
# Lo que ESCRIBE: renglones de la tabla de anotaciones y NADA más (ni `personas`, ni la unión, ni la bandeja). Unir y deshacer siguen sin tocarla.
ANOTACIONES_CANALES = ("whatsapp", "instagram", "correo", "telefono", "en_persona", "formulario", "otro")     # por dónde lo dijo la persona
ANOTACIONES_PEDIDO_CLAVES = ("valor", "canal", "dicho_el", "nota", "visto", "confirmo", "clave_envio")       # lo ÚNICO que el pedido puede traer
ANOTACIONES_NOTA_MAX = 500              # decisión de diseño (no una medición): el largo de la nota, en caracteres
ANOTACIONES_DICHO_DESDE = "2020-01-01"  # decisión de diseño (no una medición): una fecha «dicho el» anterior a esta es un error de tecleo
_ANOTAR_SIN = "No se anotó nada."


def _anotar_pedido(cuerpo):
    """Valida el pedido SIN leer ni escribir nada. Devuelve `(pedido, None)` o `(None, frase)`.
    · Solo las claves de `ANOTACIONES_PEDIDO_CLAVES`: un `quien`, un `cuando` o un `ficha_id` en el cuerpo se rechaza (los decide el servidor).
    · `valor` uno de `ANOTACIONES_PERMISOS`; `canal` (opcional) uno de `ANOTACIONES_CANALES`; `dicho_el` (opcional) `AAAA-MM-DD`, un día de verdad, ni
      futuro (en Santo Domingo) ni anterior a `ANOTACIONES_DICHO_DESDE`; `nota` (opcional) texto de hasta `ANOTACIONES_NOTA_MAX`.
    · `visto` OBLIGATORIO: el `renglon_visto` que la pantalla tenía delante (`null` si no había ninguno). Sin él no se sabe qué vio quien anota.
    · `confirmo` (opcional): solo vale el booleano `true`; cualquier otro tipo es un error (la cadena «false» no se toma por verdadera)."""
    if not isinstance(cuerpo, dict):
        return None, "El pedido llegó ilegible."
    ajenas = sorted(str(k) for k in cuerpo if k not in ANOTACIONES_PEDIDO_CLAVES)
    if ajenas:
        return None, "El pedido trae cosas que no se pueden mandar: %s." % ", ".join(ajenas)
    valor = cuerpo.get("valor")
    if not isinstance(valor, str) or valor not in ANOTACIONES_PERMISOS:
        return None, "El valor tiene que ser uno de: %s." % ", ".join(ANOTACIONES_PERMISOS)
    canal = cuerpo.get("canal")
    if canal is not None and (not isinstance(canal, str) or canal not in ANOTACIONES_CANALES):
        return None, "El canal tiene que ser uno de: %s." % ", ".join(ANOTACIONES_CANALES)
    dicho = cuerpo.get("dicho_el")
    if dicho is not None:
        try:
            if not isinstance(dicho, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", dicho):
                raise ValueError
            date.fromisoformat(dicho)
        except ValueError:
            return None, "La fecha en que lo dijo tiene que ser un día de verdad, escrito AAAA-MM-DD."
        if dicho > _base.hoy_str():
            return None, "La fecha en que lo dijo no puede ser de un día que todavía no llega."
        if dicho < ANOTACIONES_DICHO_DESDE:
            return None, "La fecha en que lo dijo es demasiado vieja."
    nota = cuerpo.get("nota")
    if nota is not None:
        if not isinstance(nota, str):
            return None, "La nota tiene que ser texto."
        nota = nota.strip()
        if len(nota) > ANOTACIONES_NOTA_MAX:
            return None, "La nota es demasiado larga (tiene que quedar en %d caracteres o menos)." % ANOTACIONES_NOTA_MAX
    if "visto" not in cuerpo:
        return None, "Falta `visto`: el número del último renglón que viste (o null si no había ninguno)."
    visto = cuerpo["visto"]
    if visto is not None and (isinstance(visto, bool) or not isinstance(visto, int) or not 0 < visto < 10 ** 9):
        return None, "`visto` tiene que ser el número de un renglón, o null."
    confirmo = cuerpo.get("confirmo")
    if confirmo is not None and confirmo is not True and confirmo is not False:
        return None, "`confirmo` tiene que ser verdadero o falso."
    return {"valor": valor, "canal": canal, "dicho_el": dicho, "nota": nota or None, "visto": visto, "confirmo": confirmo is True}, None


def _anotar_no(codigo, estado, error, mercadeo=None, **extra):
    r = dict({"ok": False, "estado": estado, "error": error}, **extra)
    if mercadeo is not None:
        r["mercadeo"] = mercadeo
    return codigo, r


def _anotar_no_se_supo(e):
    """La lectura previa falló: no se escribe. 404 solo si la ficha de verdad no está en lo leído (la lectura fue completa)."""
    motivo = e.motivo if isinstance(e, _NoSeSupo) else "lectura_fallo"
    print(f"[PERSONAS-ANOTAR] no se pudo saber ({motivo})")
    if motivo == "ficha_no_esta":
        return _anotar_no(404, "no_existe", "Esa persona ya no está en la base. " + _ANOTAR_SIN)
    return _anotar_no(502, "no_se_pudo_saber", "No se pudo saber cómo está esta persona ahora. " + _ANOTAR_SIN + " Inténtalo en un momento.",
                      mercadeo=_anotaciones_no_se_supo(motivo))


# Solo el cálculo (`solo_contar`, P11-6d): los renglones que la escritura mandaría se suman a la lectura en memoria, para que el paso
# siguiente (otra ficha del mismo pedido) los vea como ya escritos. `PREVISTO_ID_BASE` es un número fuera de lo que la tabla da (decisión
# de diseño, no una medición): así el renglón previsto más nuevo es el de «gana lo último». Nada de esto sale a la red.
PREVISTO_ID_BASE = 10 ** 12


def _planear_renglones(tabla, base, destinos, ficha, previstas, filtrar_nulos):
    """Lo que la escritura mandaría (solo el cálculo): un POST por cada ficha de `destinos`, en el orden de la escritura (la ficha abierta
    al final). Cada uno se suma a `previstas`. `filtrar_nulos` igual que la escritura: el permiso no manda las columnas vacías; la foto sí."""
    planeados = []
    for destino in [i for i in destinos if i != ficha] + ([ficha] if ficha in destinos else []):
        fila = dict(base, ficha_id=destino)
        cuerpo = {k: v for k, v in fila.items() if v is not None} if filtrar_nulos else dict(fila)
        planeados.append({"tabla": tabla, "metodo": "POST", "cuerpo": cuerpo})
        previstas.append(dict(fila, Id=PREVISTO_ID_BASE + len(previstas) + 1))
    return planeados


def _con_previstas(leido, previstas):
    """La lectura de `_anotar_leer` con los renglones previstos sumados. Mismo grupo; el estado se calcula otra vez, y si no se sabe, levanta."""
    grupo, filas, _estado = leido
    filas = list(filas) + list(previstas)
    estado = anotaciones_estado(grupo, filas)
    if not estado["sabido"]:
        raise _NoSeSupo(estado["motivo"])
    return grupo, filas, estado


def _anotar_leer(ficha_id, tabla, previstas=None):
    """`(grupo, filas, estado)` con el estado SABIDO, o levanta `_NoSeSupo`. Cualquier otro fallo de lectura también es «no se pudo saber».
    `previstas` (solo el cálculo): los renglones que la escritura escribiría antes de esta lectura (`_planear_renglones`)."""
    try:
        leido = _anotaciones_leer(ficha_id, tabla)
    except _NoSeSupo:
        raise
    except Exception:  # noqa: BLE001
        raise _NoSeSupo("lectura_fallo")
    if not leido[2]["sabido"]:
        raise _NoSeSupo(leido[2]["motivo"])
    if previstas:
        return _con_previstas(leido, previstas)
    return leido


def anotar_permiso(ficha_id, cuerpo, quien, solo_contar=False, previstas=None):
    """Anota el permiso (`sin_preguntar` | `si` | `no` | `baja`) de la persona de la ficha `ficha_id`. Devuelve `(codigo, dict)`. El orden:
      1. Se valida el pedido (`_anotar_pedido`), sin leer ni escribir: 400. Sin la variable de la tabla: 503 `sin_tabla`.
      2. Se lee el grupo de la ficha (ella más las que hoy están unidas a ella; la ficha propia, una unida a otra o la que sobró dan el mismo grupo).
         No se pudo leer: 502 `no_se_pudo_saber`, o 404 si la ficha ya no está. NUNCA se escribe sin saber el estado.
      3. Se toman los candados de TODAS las fichas del grupo (en orden de número: el mismo orden que la unión, sin interbloqueo) y se lee de nuevo.
         Si el grupo cambió entre las dos lecturas: 409 `cambio`.
      4. «YA ESTABA» = el grupo lee lo pedido Y CADA ficha del grupo, mirada sola, también (lo que leería si se deshiciera la unión): 200 `ya_estaba`, sin escribir
         (aunque `visto` esté viejo: lo pedido ya es verdad en todas).
      4-bis. COMPLETAR: si el grupo lee lo pedido pero alguna ficha suelta no, se escribe SOLO en esas (a las que ya leen lo pedido no se les escribe otro renglón),
         sin pedir `visto` (completar no cambia lo que el grupo lee: el renglón más nuevo ya es lo pedido) y se contesta `anotado` con `solo_completo: true` o
         `sin_confirmar`, con las mismas exigencias de relectura. Si una de esas fichas tiene una BAJA propia y lo pedido no es `baja`, pide `confirmo: true`
         (409 `pide_confirmar`): completar no es una forma de quitar una baja sin confirmar. Si el grupo lee OTRA cosa no se completa: sigue lo de abajo.
      5. Si el último renglón de permiso del grupo no es el `visto` del pedido: 409 `cambio` («cambió mientras lo mirabas»), sin escribir.
      6. Si hoy es `baja` y se pide otra cosa (incluido `sin_preguntar`) sin `confirmo: true`: 409 `pide_confirmar`, sin escribir.
      7. Se escribe UN renglón por cada ficha del grupo (o solo las que faltan, si se completa; las otras primero, la ficha abierta al final). `quien` es el que decidió el servidor
         (`Handler.firma_escrita`), `cuando` la hora del servidor, `ficha_id` la de la dirección: nada de eso sale del cuerpo.
      8. Se RELEE (todavía bajo los candados) y solo si cada renglón escrito está en la tabla tal como se mandó y el permiso de la persona es el pedido
         se contesta 200 `anotado`. Si un `POST` falló, no devolvió su `Id`, o la relectura falló o no coincide: 502 `sin_confirmar`
         («no lo des por anotado, mira la ficha antes de repetir»). Un `POST` que falla corta la fila de escrituras.
    NO PASA POR `una_vez` (la ruta de `server.py` llama esta función directo): devolver lo guardado de un envío anterior diría «anotado: si» con la persona ya en «no»
    (medido por el testigo el 13-oct-2026). Cada pedido, repetido o no, se contesta leyendo ahora. Un reenvío (misma `clave_envio` o no; esa clave se acepta y se
    ignora) no escribe dos veces: si lo pedido ya es verdad contesta `ya_estaba`, y si no, `visto` ya no coincide (el primer envío cambió el renglón) y contesta 409 `cambio`
    con el estado de ahora. Un envío que quedó en `sin_confirmar` se puede reintentar: escribe si hace falta.
    «Ya estaba» y «anotado» siempre traen `mercadeo`, el estado releído. Un 409 trae el estado actual para que la pantalla se ponga al día.
    FRONTERAS: (a) los candados son de ESTE proceso; con más de una réplica dos personas anotando a la vez en réplicas distintas no se serializan
    (el segundo pedido igual se ve con `visto` viejo si el primero ya escribió, pero no hay candado que lo garantice); (b) un `POST` rechazado por NocoDB se
    contesta como `sin_confirmar` aunque casi seguro no escribió: no hay forma de probarlo; (c) lo anotado en una ficha NO vale para otra ficha de la
    misma persona que todavía no se unió; (d) no se mira `canal`, `dicho_el` ni `nota` para decidir «ya estaba»; (e) una ficha que se une DESPUÉS al grupo no tiene renglón propio y cuenta como «no lee lo pedido»: la próxima vez que se anote lo que el grupo ya lee, se le escribe
    su renglón (completar); (f) completar solo mira lo que cada ficha lee HOY: si un `POST` de completar falla, el siguiente intento completa lo que quede; lo que no se
    puede completar es una ficha cuyo renglón propio de baja se quiere cambiar sin `confirmo`; (g) las baja propias de fichas que ya estaban unidas cuando se anotó otra cosa
    (por la regla «gana lo último», decidida por Tiziano) se sobrescriben sin confirmar en el camino normal si el grupo no leía baja (hallazgo H2, en la cola de la sala)."""
    if solo_contar and previstas is None:
        previstas = []                                  # `solo_contar` (P11-6d): contesta lo que escribiría y no escribe nada
    pedido, error = _anotar_pedido(cuerpo)
    if error:
        return 400, {"ok": False, "estado": "pedido_malo", "error": error + " " + _ANOTAR_SIN}
    if not isinstance(quien, str) or not quien.strip():
        return 400, {"ok": False, "estado": "pedido_malo", "error": "No se pudo verificar quién anota. " + _ANOTAR_SIN}
    try:
        tabla = (_base.T_PERSONAS_ANOTACIONES or "").strip()
    except Exception:  # noqa: BLE001
        tabla = ""
    if not tabla:
        return 503, {"ok": False, "estado": "sin_tabla", "sin_tabla": True, "error": "Todavía no hay dónde guardar el permiso. " + _ANOTAR_SIN}
    ficha = _anotaciones_entero(ficha_id)
    try:
        grupo = anotaciones_grupo(ficha, _anotaciones_leer_tabla(_base.T_PERSONAS, "Id,unida_a"))
    except _NoSeSupo as e:
        return _anotar_no_se_supo(e)
    except Exception:  # noqa: BLE001
        return _anotar_no_se_supo(None)
    valor = pedido["valor"]
    with contextlib.ExitStack() as candados:
        for i in sorted(grupo):
            candados.enter_context(_candado_de_ficha(i))
        try:
            grupo2, filas, estado = _anotar_leer(ficha, tabla, previstas)
        except _NoSeSupo as e:
            return _anotar_no_se_supo(e)
        if grupo2 != grupo:
            return _anotar_no(409, "cambio", "Las fichas de esta persona cambiaron mientras anotabas (se unió o se deshizo una unión). " + _ANOTAR_SIN
                              + " Ábrela otra vez.", mercadeo=estado, motivo="grupo_cambio")
        # Lo que cada ficha del grupo, mirada SOLA, lee hoy (es lo que leería si se deshiciera la unión).
        propios = {}
        for i in sorted(grupo):
            propio = anotaciones_estado({i}, filas)
            if not propio["sabido"]:
                return _anotar_no_se_supo(_NoSeSupo(propio["motivo"]))
            propios[i] = propio["permiso"]
        faltan = [i for i in sorted(grupo) if propios[i] != valor]       # las fichas que NO leen lo pedido
        if estado["permiso"] == valor and not faltan:
            return 200, dict({"ok": True, "estado": "ya_estaba", "mercadeo": estado}, **({"escrituras": []} if solo_contar else {}))
        # COMPLETAR: la persona (el grupo) ya lee lo pedido pero alguna ficha suelta no. Completar no cambia lo que el grupo lee (el renglón más nuevo ya es lo pedido),
        # así que no pide `visto` y escribe solo en las fichas que faltan. Si el grupo lee OTRA cosa, no se completa: sigue el camino de siempre (`visto`, confirmar).
        completar = estado["permiso"] == valor
        if not completar:
            if estado["renglon_visto"] != pedido["visto"]:
                return _anotar_no(409, "cambio", "Esto cambió mientras lo mirabas: alguien más anotó algo. " + _ANOTAR_SIN + " Mira cómo está y vuelve a anotar.",
                                  mercadeo=estado, motivo="cambio_mientras_mirabas")
            if estado["permiso"] == "baja" and not pedido["confirmo"]:
                return _anotar_no(409, "pide_confirmar", "Esta persona tiene una BAJA. Cambiarla pide confirmar. " + _ANOTAR_SIN, mercadeo=estado, motivo="pide_confirmar")
        elif valor != "baja" and any(propios[i] == "baja" for i in faltan) and not pedido["confirmo"]:
            return _anotar_no(409, "pide_confirmar", "Una de las fichas de esta persona tiene una BAJA propia y esto la cambiaría. Cambiarla pide confirmar. " + _ANOTAR_SIN,
                              mercadeo=estado, motivo="pide_confirmar")
        destinos = faltan if completar else sorted(grupo)
        base = {"clase": "permiso", "valor": valor, "canal": pedido["canal"], "dicho_el": pedido["dicho_el"], "nota": pedido["nota"],
                "quien": quien.strip(), "cuando": _ahora_utc()}
        if solo_contar:
            planeados = _planear_renglones(tabla, base, destinos, ficha, previstas, filtrar_nulos=True)
            return 200, {"ok": True, "estado": "anotado", "renglones": len(planeados), "escrituras": planeados}
        escritos, fallo = [], False                 # [(ficha, Id)]
        for destino in [i for i in destinos if i != ficha] + ([ficha] if ficha in destinos else []):
            try:
                rec = _base.nc("POST", f"/api/v2/tables/{tabla}/records", body={k: v for k, v in dict(base, ficha_id=destino).items() if v is not None})
            except _base.SoloLectura:
                raise                               # lo dice `do_POST` (503; si algo ya salió, dice que no se sabe)
            except Exception:  # noqa: BLE001
                fallo = True
                break
            nuevo = _anotaciones_entero(rec.get("Id")) if isinstance(rec, dict) else None
            if nuevo is None:
                fallo = True
                break
            escritos.append((destino, nuevo))
        confirmado, nuevo_estado = False, None
        try:
            _, filas2, nuevo_estado = _anotar_leer(ficha, tabla)
            por_id = {f.get("Id"): f for f in filas2}
            confirmado = (not fallo and bool(escritos) and nuevo_estado["permiso"] == valor
                          and all(isinstance(por_id.get(i), dict) and por_id[i].get("ficha_id") == d and por_id[i].get("clase") == "permiso"
                                  and por_id[i].get("valor") == valor and por_id[i].get("quien") == base["quien"] for d, i in escritos))
        except Exception:  # noqa: BLE001
            confirmado = False
        if not confirmado:
            print(f"[PERSONAS-ANOTAR] sin confirmar valor={valor} renglones={len(escritos)}")
            return _anotar_no(502, "sin_confirmar", "No se pudo confirmar que quedó anotado. NO lo des por anotado: abre la ficha y mira cómo quedó antes de repetirlo.",
                              mercadeo=nuevo_estado, sin_confirmar=True)
        print(f"[PERSONAS-ANOTAR] anotado valor={valor} renglones={len(escritos)}")
        return 200, dict({"ok": True, "estado": "anotado", "renglones": len(escritos), "mercadeo": nuevo_estado}, **({"solo_completo": True} if completar else {}))


# ---------- LAS ANOTACIONES DE PERSONAS — PIEZA 5: LA BAJA QUE LLEGA DE NATALIA (Campañas A5) ----------
# Diseño aprobado: `disenos/mercadeo-campanas/DISENO.md`, pieza A5. `POST /api/servicio/mercadeo/baja` (de servidor a servidor, `X-Mercadeo-Llave`): cuando un cliente le dice a Natalia
# «no me escriban más», Natalia manda `{identidad, dicho_el, clave}` y la App anota `baja` (canal `whatsapp`, quien «Natalia») en TODAS las fichas de esa identidad.
# No hay un segundo escritor de la tabla de anotaciones: cada ficha se anota con `anotar_permiso` (la misma puerta que usa la pantalla, con sus candados, su relectura y su «ya estaba»);
# esta pieza solo (1) encuentra las fichas de la identidad con la regla de Leads (`numeros_de_identidades_estricto` + `clave_telefono` sobre las casillas de `LEADS_CASILLAS_DE_TELEFONO`)
# y (2) pone `visto`, que una baja no necesita del que llama: se prueba con `null` y, si la ficha ya tenía otro permiso, se repite UNA vez con el renglón que la respuesta 409 dice.
# Anotar una baja nunca quita una baja ni pide `confirmo`. `clave` se exige y se ignora (como `clave_envio` de `anotar_permiso`): repetir el mismo pedido contesta `ya_estaba` porque
# lo que decide es lo que la tabla lee AHORA, no una clave guardada. Las fichas que comparten el número se anotan todas; si una falla, se contesta `sin_confirmar` y repetir completa las que falten.
BAJA_NATALIA_QUIEN = "Natalia"
BAJA_NATALIA_CLAVES = ("identidad", "dicho_el", "clave")
BAJA_NATALIA_CLAVE_MAX = 200            # decisión de diseño (no una medición): el largo de la `clave`, en caracteres
_BAJA_SIN = "No se anotó nada."


def _baja_pedido(cuerpo):
    """Valida el pedido SIN leer ni escribir. `(pedido, None)` o `(None, frase)`: solo las tres claves, `identidad` y `clave` texto no vacío, `dicho_el` con la regla de `_anotar_pedido`."""
    if not isinstance(cuerpo, dict) or set(cuerpo) != set(BAJA_NATALIA_CLAVES):
        return None, "El pedido tiene que traer exactamente: %s." % ", ".join(BAJA_NATALIA_CLAVES)
    identidad, clave = cuerpo.get("identidad"), cuerpo.get("clave")
    if not isinstance(identidad, str) or not identidad.strip():
        return None, "`identidad` tiene que ser el número o el ID de WhatsApp de quien pidió la baja."
    if not isinstance(clave, str) or not clave.strip() or len(clave) > BAJA_NATALIA_CLAVE_MAX:
        return None, "`clave` tiene que ser un texto de hasta %d caracteres." % BAJA_NATALIA_CLAVE_MAX
    dicho = cuerpo.get("dicho_el")
    if not isinstance(dicho, str):
        return None, "`dicho_el` tiene que ser un día escrito AAAA-MM-DD."
    _, error = _anotar_pedido({"valor": "baja", "canal": "whatsapp", "dicho_el": dicho, "visto": None})
    if error:
        return None, error
    return {"identidad": identidad.strip(), "dicho_el": dicho}, None


def _baja_fichas_de(identidad):
    """Los `Id` de las fichas de esa identidad, de menor a mayor (puede ser `[]`). La regla de Leads: la identidad da UN número (`numeros_de_identidades_estricto`) y una ficha es de esa identidad si
    ese número es la clave de alguna de sus casillas de teléfono. Lectura estricta de `personas`: si no se puede leer completa, LEVANTA (nunca se anota sobre una lista corta)."""
    filas = _anotaciones_leer_tabla(_base.T_PERSONAS, "Id,telefono,telefono_2,bsuid")
    clave = clave_telefono(numeros_de_identidades_estricto([identidad], lambda _donde: filas)[identidad])
    if not clave:
        return []
    ids = set()
    for f in filas:
        i = _anotaciones_entero(f.get("Id"))
        if i is not None and clave in {clave_telefono(f.get(c)) for c in _base.LEADS_CASILLAS_DE_TELEFONO}:
            ids.add(i)
    return sorted(ids)


def _baja_anotar_una(ficha, dicho_el, solo_contar=False, previstas=None):
    """`anotar_permiso(baja)` en esa ficha. Sin `visto` del que llama: se prueba `null` y, si la respuesta es el 409 «cambió» con el renglón que manda hoy, se repite una vez con ese."""
    visto = None
    for _intento in range(2):                       # UNA sola llamada a `anotar_permiso` en el código: la repetición es este bucle
        codigo, datos = anotar_permiso(ficha, {"valor": "baja", "canal": "whatsapp", "dicho_el": dicho_el, "visto": visto}, BAJA_NATALIA_QUIEN,
                                       solo_contar=solo_contar, previstas=previstas)
        if not (codigo == 409 and datos.get("motivo") == "cambio_mientras_mirabas" and isinstance(datos.get("mercadeo"), dict)):
            break
        visto = datos["mercadeo"].get("renglon_visto")
    return codigo, datos


def baja_de_natalia(cuerpo, solo_contar=False):
    """`POST /api/servicio/mercadeo/baja` -> `(codigo, dict)`. Ya pasó la llave. El orden: pedido (400, sin leer nada); sin tabla de anotaciones (503); las fichas de la identidad (502 si no se pudieron leer
    completas; 404 `sin_ficha` si no hay ninguna); cada ficha con `anotar_permiso`. Contesta 200 `anotado` solo si CADA ficha quedó en baja y lo comprobó su relectura, y 200 `ya_estaba` si todas ya
    estaban; si alguna no se pudo anotar o confirmar, 502 `sin_confirmar` (con las que sí se anotaron ya escritas: repetir completa). Nunca viaja un dato de la persona."""
    pedido, error = _baja_pedido(cuerpo)
    if error:
        return 400, {"ok": False, "estado": "pedido_malo", "error": error + " " + _BAJA_SIN}
    try:
        tabla = (_base.T_PERSONAS_ANOTACIONES or "").strip()
    except Exception:  # noqa: BLE001
        tabla = ""
    if not tabla:
        return 503, {"ok": False, "estado": "sin_tabla", "error": "Todavía no hay dónde guardar el permiso. " + _BAJA_SIN}
    try:
        fichas = _baja_fichas_de(pedido["identidad"])
    except Exception as e:  # noqa: BLE001
        print(f"[PERSONAS-BAJA] no se pudieron leer las fichas ({type(e).__name__})")
        return 502, {"ok": False, "estado": "sin_confirmar", "error": "No se pudo leer las fichas. " + _BAJA_SIN}
    if not fichas:
        return 404, {"ok": False, "estado": "sin_ficha", "error": "No hay ninguna ficha con esa identidad. " + _BAJA_SIN}
    estados, planeados = [], []
    previstas = [] if solo_contar else None            # `solo_contar` (P11-6d): cada ficha ve lo que la anterior escribiría
    for ficha in fichas:
        codigo, datos = _baja_anotar_una(ficha, pedido["dicho_el"], solo_contar, previstas)
        if codigo != 200 or datos.get("estado") not in ("anotado", "ya_estaba"):
            if not solo_contar:
                print(f"[PERSONAS-BAJA] sin confirmar codigo={codigo} estado={datos.get('estado')} fichas={len(fichas)}")
            return 502, {"ok": False, "estado": "sin_confirmar", "error": "No se pudo confirmar que quedó anotado. NO lo des por anotado."}
        estados.append(datos["estado"])
        planeados.extend(datos.get("escrituras", []))
    estado = "ya_estaba" if all(e == "ya_estaba" for e in estados) else "anotado"
    if solo_contar:
        return 200, {"ok": True, "estado": estado, "fichas": len(fichas), "escrituras": planeados}
    print(f"[PERSONAS-BAJA] {estado} fichas={len(fichas)}")
    return 200, {"ok": True, "estado": estado, "fichas": len(fichas)}


# ---------- LAS ANOTACIONES DE PERSONAS — D19a: EL PERMISO DE FOTOS (lo anota Natalia, con la llave de Mercadeo) ----------
# Diseño aprobado: `disenos/mercadeo-gai/DISENO.md` §6.5, §7, §11 (fila D19a) y §11.1 («Natalia no anota un permiso que el cliente no dio»).
# Es un renglón `clase = foto` en LA MISMA tabla de anotaciones: sus columnas ya existen, así que no hay columna nueva que crear. `valor` es `si` o `no`;
# sin renglón de foto la ficha dice «no se sabe» (`foto.valor` = None), nunca «no».
# Lo escribe SOLO `anotar_foto`, y lo llama solo `foto_de_natalia`, detrás de la llave de Mercadeo (`Handler.mercadeo_foto`, `POST /api/servicio/mercadeo/foto`).
# `quien` lo pone el servidor (`FOTO_NATALIA_QUIEN`), `cuando` la hora del servidor y `ficha_id` la que decide el servidor: nada de eso sale del cuerpo.
# No hay `visto` ni `confirmo`: el permiso de fotos no tiene baja ni pregunta previa, y gana lo último que se anotó (como el de mensajes).
ANOTACIONES_FOTOS = ("si", "no")
FOTO_NATALIA_QUIEN = "Natalia"
FOTO_NATALIA_CLAVES = ("identidad", "valor")
_FOTO_SIN = "No se anotó nada."


def _texto_de_anotacion(renglon, columna):
    """El texto de una columna de un renglón de anotaciones, recortado; `None` si está vacío o no es texto."""
    valor = renglon.get(columna)
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def _foto_pedido(cuerpo):
    """Valida el pedido de Natalia SIN leer ni escribir: `(pedido, None)` o `(None, frase)`. Solo `identidad` (texto no vacío) y `valor` (`si` o `no`, texto exacto)."""
    if not isinstance(cuerpo, dict) or set(cuerpo) != set(FOTO_NATALIA_CLAVES):
        return None, "El pedido tiene que traer exactamente: %s." % ", ".join(FOTO_NATALIA_CLAVES)
    identidad, valor = cuerpo.get("identidad"), cuerpo.get("valor")
    if not isinstance(identidad, str) or not identidad.strip():
        return None, "`identidad` tiene que ser el número o el ID de WhatsApp de la persona."
    if not isinstance(valor, str) or valor not in ANOTACIONES_FOTOS:
        return None, "`valor` tiene que ser «si» o «no»."
    return {"identidad": identidad.strip(), "valor": valor}, None


def anotar_foto(ficha_id, valor, quien, solo_contar=False, previstas=None):
    """Anota el permiso de fotos (`si` | `no`) de la persona de la ficha `ficha_id`. Devuelve `(codigo, dict)`. El orden (el de `anotar_permiso`, sin `visto` ni baja):
      1. `valor` y `quien` se validan sin leer (400). Sin la variable de la tabla: 503 `sin_tabla`.
      2. Se lee el grupo de la ficha (ella más las que hoy están unidas). No se pudo: 502 `no_se_pudo_saber` (404 si la ficha ya no está). Nunca se escribe sin saber.
      3. Se toman los candados de TODAS las fichas del grupo y se lee otra vez. Si el grupo cambió entre las dos lecturas: 409 `cambio`.
      4. «YA ESTABA»: el grupo lee `valor` y cada ficha, mirada sola, también. 200 `ya_estaba`, sin escribir.
      5. Se escribe un renglón de foto SOLO en las fichas que no leen `valor` (la de la dirección al final). El renglón nuevo es el más alto: el grupo pasa a leer `valor`.
      6. Se RELEE bajo los candados: 200 `anotado` solo si cada renglón está en la tabla con su ficha, clase, valor y quien, y el grupo lee `valor`. Si no: 502 `sin_confirmar`.
    «Gana lo último» (`anotaciones_estado`). Sin renglón de foto, la ficha dice «no se sabe»."""
    if solo_contar and previstas is None:
        previstas = []                                  # `solo_contar` (P11-6d): contesta lo que escribiría y no escribe nada
    if valor not in ANOTACIONES_FOTOS:
        return 400, {"ok": False, "estado": "pedido_malo", "error": "`valor` tiene que ser «si» o «no». " + _FOTO_SIN}
    if not isinstance(quien, str) or not quien.strip():
        return 400, {"ok": False, "estado": "pedido_malo", "error": "No se pudo verificar quién anota. " + _FOTO_SIN}
    try:
        tabla = (_base.T_PERSONAS_ANOTACIONES or "").strip()
    except Exception:  # noqa: BLE001
        tabla = ""
    if not tabla:
        return 503, {"ok": False, "estado": "sin_tabla", "sin_tabla": True, "error": "Todavía no hay dónde guardar el permiso de fotos. " + _FOTO_SIN}
    ficha = _anotaciones_entero(ficha_id)
    try:
        grupo = anotaciones_grupo(ficha, _anotaciones_leer_tabla(_base.T_PERSONAS, "Id,unida_a"))
    except _NoSeSupo as e:
        return _anotar_no_se_supo(e)
    except Exception:  # noqa: BLE001
        return _anotar_no_se_supo(None)
    with contextlib.ExitStack() as candados:
        for i in sorted(grupo):
            candados.enter_context(_candado_de_ficha(i))
        try:
            grupo2, filas, estado = _anotar_leer(ficha, tabla, previstas)
        except _NoSeSupo as e:
            return _anotar_no_se_supo(e)
        if grupo2 != grupo:
            return _anotar_no(409, "cambio", "Las fichas de esta persona cambiaron mientras anotabas (se unió o se deshizo una unión). " + _FOTO_SIN
                              + " Ábrela otra vez.", mercadeo=estado, motivo="grupo_cambio")
        propios = {}
        for i in sorted(grupo):
            propio = anotaciones_estado({i}, filas)
            if not propio["sabido"]:
                return _anotar_no_se_supo(_NoSeSupo(propio["motivo"]))
            propios[i] = propio["foto"]["valor"]
        faltan = [i for i in sorted(grupo) if propios[i] != valor]
        if estado["foto"]["valor"] == valor and not faltan:
            return 200, dict({"ok": True, "estado": "ya_estaba", "mercadeo": estado}, **({"escrituras": []} if solo_contar else {}))
        base = {"clase": "foto", "valor": valor, "quien": quien.strip(), "cuando": _ahora_utc()}
        if solo_contar:
            planeados = _planear_renglones(tabla, base, faltan, ficha, previstas, filtrar_nulos=False)
            return 200, {"ok": True, "estado": "anotado", "renglones": len(planeados), "escrituras": planeados}
        escritos, fallo = [], False                 # [(ficha, Id)]
        for destino in [i for i in faltan if i != ficha] + ([ficha] if ficha in faltan else []):
            try:
                rec = _base.nc("POST", f"/api/v2/tables/{tabla}/records", body=dict(base, ficha_id=destino))
            except _base.SoloLectura:
                raise                               # lo dice `do_POST` (503; si algo ya salió, dice que no se sabe)
            except Exception:  # noqa: BLE001
                fallo = True
                break
            nuevo = _anotaciones_entero(rec.get("Id")) if isinstance(rec, dict) else None
            if nuevo is None:
                fallo = True
                break
            escritos.append((destino, nuevo))
        confirmado, nuevo_estado = False, None
        try:
            _, filas2, nuevo_estado = _anotar_leer(ficha, tabla)
            por_id = {f.get("Id"): f for f in filas2}
            confirmado = (not fallo and bool(escritos) and nuevo_estado["foto"]["valor"] == valor
                          and all(isinstance(por_id.get(i), dict) and por_id[i].get("ficha_id") == d and por_id[i].get("clase") == "foto"
                                  and por_id[i].get("valor") == valor and por_id[i].get("quien") == base["quien"] for d, i in escritos))
        except Exception:  # noqa: BLE001
            confirmado = False
        if not confirmado:
            print(f"[PERSONAS-FOTO] sin confirmar valor={valor} renglones={len(escritos)}")
            return _anotar_no(502, "sin_confirmar", "No se pudo confirmar que quedó anotado el permiso de fotos. NO lo des por anotado: abre la ficha y mira cómo quedó antes de repetirlo.",
                              mercadeo=nuevo_estado, sin_confirmar=True)
        print(f"[PERSONAS-FOTO] anotado valor={valor} renglones={len(escritos)}")
        return 200, {"ok": True, "estado": "anotado", "renglones": len(escritos), "mercadeo": nuevo_estado}


def foto_de_natalia(cuerpo, solo_contar=False):
    """`POST /api/servicio/mercadeo/foto` -> `(codigo, dict)`. Ya pasó la llave de Mercadeo. El orden: pedido (400, sin leer nada); sin tabla (503); las fichas de la
    identidad (`_baja_fichas_de`: 502 `no_se_pudo_saber` si no se pudieron leer completas; 404 `sin_ficha` si no hay ninguna); cada ficha con `anotar_foto`.
    200 `anotado` si alguna quedó escrita y todas están confirmadas; 200 `ya_estaba` si todas ya leían `valor`; 502 `sin_confirmar` si alguna no se pudo confirmar
    (repetir completa lo que falte). La respuesta no trae ningún dato de la persona: solo el estado y cuántas fichas."""
    pedido, error = _foto_pedido(cuerpo)
    if error:
        return 400, {"ok": False, "estado": "pedido_malo", "error": error + " " + _FOTO_SIN}
    try:
        tabla = (_base.T_PERSONAS_ANOTACIONES or "").strip()
    except Exception:  # noqa: BLE001
        tabla = ""
    if not tabla:
        return 503, {"ok": False, "estado": "sin_tabla", "sin_tabla": True, "error": "Todavía no hay dónde guardar el permiso de fotos. " + _FOTO_SIN}
    try:
        fichas = _baja_fichas_de(pedido["identidad"])
    except Exception:  # noqa: BLE001
        print("[PERSONAS-FOTO] no se pudieron leer las fichas")
        return 502, {"ok": False, "estado": "no_se_pudo_saber", "error": "No se pudo leer las fichas. " + _FOTO_SIN}
    if not fichas:
        return 404, {"ok": False, "estado": "sin_ficha", "error": "No hay ninguna ficha con esa identidad. " + _FOTO_SIN}
    estados, planeados = [], []
    previstas = [] if solo_contar else None            # `solo_contar` (P11-6d): cada ficha ve lo que la anterior escribiría
    for ficha in fichas:
        codigo, datos = anotar_foto(ficha, pedido["valor"], FOTO_NATALIA_QUIEN, solo_contar, previstas)
        if codigo != 200 or datos.get("estado") not in ("anotado", "ya_estaba"):
            if not solo_contar:
                print(f"[PERSONAS-FOTO] sin confirmar codigo={codigo} estado={datos.get('estado')} fichas={len(fichas)}")
            return 502, {"ok": False, "estado": "sin_confirmar", "error": "No se pudo confirmar que quedó anotado. NO lo des por anotado."}
        estados.append(datos["estado"])
        planeados.extend(datos.get("escrituras", []))
    estado = "ya_estaba" if all(e == "ya_estaba" for e in estados) else "anotado"
    if solo_contar:
        return 200, {"ok": True, "estado": estado, "fichas": len(fichas), "valor": pedido["valor"], "escrituras": planeados}
    print(f"[PERSONAS-FOTO] {estado} fichas={len(fichas)}")
    return 200, {"ok": True, "estado": estado, "fichas": len(fichas), "valor": pedido["valor"]}


# ---------- LAS ANOTACIONES DE PERSONAS — PIEZA 4: POR DÓNDE ENTRÓ (lo anota el sistema al NACER la ficha) ----------
# Una ficha nace en UN solo sitio de la App: el `POST` a `personas` de `_puerta_recibir` (rama `plan["crear"]`). Ahí, justo después de soltar el candado
# y antes de releer, se llama `anotar_origen_al_nacer`: un renglón `clase = origen` en la tabla de anotaciones con el `origen` que ya traía el dato
# (`PUERTA_ORIGENES`). Por eso no hay una línea por puerta que se pueda olvidar: la que se sume a `PUERTA_ORIGENES` y cree fichas queda cubierta.
#   · Lo que NO hace: no se anota al editar, ni al unir, ni al deshacer, ni a las fichas que ya existían (respuesta P1 de Tiziano, 13-oct-2026: «Se queda
#     sin anotar»), ni a las que Natalia crea por su cuenta sin pasar por la App. Una ficha cuyo renglón no se pudo escribir se queda sin anotar
#     (nadie lo reintenta: no hay forma de saber después que nació por esta puerta).
#   · NUNCA bloquea la puerta ni cambia lo que contesta: si no hay variable, la tabla está caída o rechaza, la ficha ya existe y solo queda una línea
#     de registro `[PUERTA-FICHAS-ORIGEN] … origen_anotado=no` para poder contar los huecos. «Anotado» (`si`) quiere decir que NocoDB devolvió el `Id`
#     del renglón; esta pieza NO relee el renglón.
#   · Quién la lee: `anotaciones_estado` (el PRIMER renglón de origen del grupo de fichas unidas) y su etiqueta, `origen_etiqueta`.
ORIGEN_QUIEN = "sistema"        # el `quien` del renglón: lo anota el sistema, no una persona
# El origen en palabras, para la ficha. La prueba `tests/test_origen_al_nacer.py` exige que las claves sean EXACTAMENTE `PUERTA_ORIGENES` (ni una puerta sin
# etiqueta ni una etiqueta de una puerta que no existe): una puerta nueva (Instagram) pone roja la prueba hasta que tenga la suya.
ORIGEN_ETIQUETAS = {
    "checkin": "Registro (check-in)",
    "google": "Google contactos",
    "portal": "Personas",
    "aprendizaje": "Aprendizaje",
    "mensaje": "Natalia: mensaje",
    "dictado": "Natalia: dictado",
    "reserva": "Natalia: reserva",
    "recuperado": "Natalia: recuperado",
}


def origen_etiqueta(valor):
    """El origen en palabras. Un valor que no tiene etiqueta (un renglón de otra época, o escrito a mano) se devuelve TAL CUAL, sin adivinar; `None` si no hay."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    return ORIGEN_ETIQUETAS.get(valor.strip(), valor.strip())


def _origen_escritura(ficha_id, origen):
    """La escritura de la anotación de origen (`clase = origen`) de una ficha que nace: `{tabla, metodo, cuerpo}`. La usa
    `anotar_origen_al_nacer` para mandarla y el cálculo (`recibir(solo_contar=True)`) para decir que la mandaría: una sola forma."""
    if origen not in PUERTA_ORIGENES:
        origen = "desconocido"
    cuerpo = {"ficha_id": ficha_id, "clase": "origen", "valor": origen, "dicho_el": _base.hoy_str(), "quien": ORIGEN_QUIEN,
              "cuando": _ahora_utc()}
    return {"tabla": (_base.T_PERSONAS_ANOTACIONES or "").strip(), "metodo": "POST", "cuerpo": cuerpo}


def anotar_origen_al_nacer(ficha_id, origen):
    """Escribe el renglón `clase = origen` de la ficha que ACABA de nacer y devuelve `"si"` o `"no"`. NO levanta (salvo `_base.SoloLectura`, que ya habría
    parado el `POST` de la ficha) y no relee. Deja UNA línea de registro `[PUERTA-FICHAS-ORIGEN] origen=<puerta> origen_anotado=<si|no>
    motivo=<…>` sin ningún dato de la persona (ni su `Id`); en el hilo del reloj de contactos de Google (`SILENCIO_PUERTA_REGISTRO`) esa
    línea no sale, pero el `POST` de la anotación sí se hace igual (solo se calla el registro, no la escritura). Motivos del `no`: `sin_id` (la base no dijo el número de la ficha), `sin_tabla` (sin
    `NOCODB_T_PERSONAS_ANOTACIONES`), `rechazo` (NocoDB contestó 4xx), `fallo` (5xx, sin red o cualquier otra cosa), `sin_renglon` (contestó sin el `Id`)."""
    if origen not in PUERTA_ORIGENES:
        origen = "desconocido"
    resultado, motivo, codigo = "no", "fallo", None
    try:
        if isinstance(ficha_id, bool) or not isinstance(ficha_id, int):
            motivo = "sin_id"
        elif not (_base.T_PERSONAS_ANOTACIONES or "").strip():
            motivo = "sin_tabla"
        else:
            esc = _origen_escritura(ficha_id, origen)
            rec = _base.nc("POST", f"/api/v2/tables/{esc['tabla']}/records", body=esc["cuerpo"])
            nuevo = rec.get("Id") if isinstance(rec, dict) else None
            if isinstance(nuevo, bool) or not isinstance(nuevo, int):
                motivo = "sin_renglon"
            else:
                resultado, motivo = "si", "-"
    except _base.SoloLectura:
        raise
    except Exception as e:                           # noqa: BLE001
        motivo = "rechazo" if isinstance(e, _base.ErrorDeNocodb) and e.status < 500 else "fallo"
        codigo = e.status if isinstance(e, _base.ErrorDeNocodb) else type(e).__name__
    if codigo is not None:
        # Un fallo de la base al anotar NO se calla, ni en el reloj (`SILENCIO_PUERTA_REGISTRO` calla solo la línea de registro):
        # el alta ya se hizo y la anotación no. Sin datos de la persona: solo el código.
        print(f"[warn] puerta de fichas: la anotación de origen no se guardó ({codigo})")
    if not getattr(SILENCIO_PUERTA_REGISTRO, "activo", False):
        print("[PUERTA-FICHAS-ORIGEN] origen=%s origen_anotado=%s motivo=%s" % (origen, resultado, motivo))
    return resultado


# ---------- Caja y el crédito a favor: las lecturas de la tabla de fichas (paso 2 de `disenos/personas-programa-aparte/DISENO.md`) ----------
# Salieron de `server.py` de la App con el mismo cuerpo. Lo que viene de otra zona va como `_base.<nombre>`.
# En este repo no hay llamadores fuera del módulo: quien los necesite los importa de aquí.


def credito_de_cliente(telefono):
    """Crédito a favor disponible (RD$) del cliente, por teléfono. 0 si no tiene ficha."""
    tel = re.sub(r"\D", "", str(telefono or ""))
    if len(tel) == 10:
        tel = "1" + tel
    if not tel:
        return 0.0, None
    rows = _base.nc_list_all(_base.T_PERSONAS, {"where": f"(telefono,eq,{tel})", "fields": "Id,credito"})
    if not rows:
        return 0.0, None
    return float(rows[0].get("credito") or 0), rows[0]["Id"]


def hay_creditos_vivos():
    """¿Hay AL MENOS UN cliente con crédito a favor en toda la casa? Una consulta, barata.

    No dice de quién ni cuánto —eso sería el dinero de otro cliente asomándose en la pantalla
    de éste—: solo si existe algo que encontrar. Es lo que decide si vale la pena avisar de una
    reserva sin teléfono (ver `estado_credito`): el día que nadie tenga crédito, ese aviso no
    podría revelar nada y no sale.
    """
    try:
        r = _base.nc("GET", f"/api/v2/tables/{_base.T_PERSONAS}/records",
                 query={"where": "(credito,gt,0)", "fields": "Id", "limit": 1})
        return bool(r.get("list"))
    except Exception as e:
        # Que no se pueda contestar NO puede tumbar la pantalla de pagos: se calla el aviso.
        print(f"[warn] no se pudo saber si hay créditos vivos: {e}")
        return False


def fichas_con_credito_vivo():
    """Las fichas con crédito a favor (`credito > 0`): `Id`, `nombre`, `telefono` y `credito`. El bloque de crédito del reporte mensual las pide aquí."""
    return _base.nc_list_all(_base.T_PERSONAS, {"where": "(credito,gt,0)",
                                        "fields": "Id,nombre,telefono,credito"})


# ---------- La entrada: las lecturas de la bandeja (paso 2b de `disenos/personas-programa-aparte/DISENO.md`) ----------
# La bandeja es de Personas (decisión 2): una sola tabla, un solo dueño. Estas lecturas salieron de `server.py` con el mismo cuerpo:
# lo que viene de otra zona va como `_base.<nombre>`. Las ESCRITURAS a la bandeja (los PATCH de la marca y del resultado) y su
# candado no están en este repo: quedan en la App de registro.


def _entrada_leer_fila(fila_id):
    """La fila de la bandeja con ese `Id`, o `None` si no existe. Levanta `_EntradaSinConfirmar` si no se pudo leer."""
    try:
        fila = _base.nc("GET", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records/{int(fila_id)}")
    except _base.ErrorDeNocodb as e:
        if e.status == 404:
            return None
        raise _base._EntradaSinConfirmar() from e
    except Exception as e:                                    # noqa: BLE001
        raise _base._EntradaSinConfirmar() from e
    return fila if isinstance(fila, dict) and fila.get("Id") == fila_id else None


def _entrada_lista_pendientes(estado, cursor, tope):
    """La lista de la bandeja con ese `estado` y `Id` mayor que `cursor`, hasta `tope` filas, tal como la devuelve NocoDB. La filtra y la ordena `entrada_barrer`."""
    return _base.nc("GET", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records",
                query={"where": "(estado,eq,%s)~and(Id,gt,%d)" % (estado, cursor), "sort": "Id", "limit": int(tope)})


def _bandeja_pagina(estado, cursor, limite, campos):
    """Una página de la bandeja con ese `estado` y `Id` mayor que `cursor`; devuelve `(filas, es_la_última)` y levanta si NocoDB no dice si es la última."""
    lista = _base.nc("GET", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records",
                 query={"where": "(estado,eq,%s)~and(Id,gt,%d)" % (estado, cursor), "sort": "Id", "limit": limite, "fields": campos})
    info = lista.get("pageInfo") if isinstance(lista, dict) else None
    if not isinstance(info, dict) or not isinstance(info.get("isLastPage"), bool):
        raise _base._EntradaSinConfirmar()
    pagina = lista.get("list")
    if not isinstance(pagina, list) or any(not isinstance(f, dict) or _base._entrada_id(f.get("Id")) is None for f in pagina):
        raise _base._EntradaSinConfirmar()
    return pagina, info["isLastPage"]
