# -*- coding: utf-8 -*-
"""BASE DE PERSONAS: las constantes de NocoDB y el cliente de NocoDB que `personas.py` y las rutas necesitan.

Viene de la App de registro, commit `0b48b5d`, por bloques copiados por nombre. Las constantes se comparan
con la App en `tests/test_constantes_app.py` (valores de `constantes_app.json`, generados con `generar_constantes.py`).

Lo que NO viene (decisión de la sala, paso 5 de Personas):
  · el desvío de lectura a Postgres (`desvio_listo`, `_sondear`, `_por_desvio`, `DESVIO_*`): el cliente lee SIEMPRE NocoDB, sin plan B;
  · el envío de técnicos (`_anotar_envio_de_tecnicos`, `_envios_de_tecnicos`): `personas.py` no lo usa;
  · la lectura de variables de entorno desde un archivo `.env` (la App sí lo lee; aquí solo `os.environ`).
Sí viene, desde el paso 5b, el contador de escrituras por pedido (`_mi_pedido`, `estrenar_la_cuenta_de_escrituras`,
`escrituras_mandadas_en_este_pedido`) y la reescritura de los errores de un pedido que ya escribió (`marcar_fallo_tras_escribir`,
la regla de `send_json` de la App): sin ellos, las escrituras de Registro no contestarían lo mismo que la App cuando NocoDB falla
después de recibir una escritura.
`SoloLectura` se conserva porque `personas.py` la captura en varios sitios; este cliente no la levanta nunca.
Dos funciones entran tarde con `import personas` dentro (no al cargar), porque `personas.py` importa este módulo.
"""
import base64
import hmac
import json
import math
import os
import re
import socket
import struct
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


# Copiado de leads.py:61 (en la App, server.py lo re-exporta).
LEADS_CASILLAS_DE_TELEFONO = ("telefono", "telefono_2")

NOCODB_BASE = os.environ.get("NOCODB_BASE", "").strip().rstrip("/")
NOCODB_TOKEN = os.environ.get("NOCODB_TOKEN", "").strip()

T_SESIONES = "mja78x7qcagta8z"

T_PERSONAS = "mhh7qqeru2ez8q1"

T_BANDEJA_PERSONAS = os.environ.get("NOCODB_T_BANDEJA_PERSONAS", "").strip()

T_UNIONES_PERSONAS = os.environ.get("NOCODB_T_UNIONES_PERSONAS", "").strip()

T_PERSONAS_QUITADAS = os.environ.get("NOCODB_T_PERSONAS_QUITADAS", "").strip()

T_MERCADEO_ENVIOS = os.environ.get("NOCODB_T_MERCADEO_ENVIOS", "").strip()

T_PERSONAS_ANOTACIONES = os.environ.get("NOCODB_T_PERSONAS_ANOTACIONES", "").strip()

T_ASISTENCIAS = "mt5snh0plx7z0ga"

L_MUSICOS = "ctgr3ukg2fgp2ct"        # sesiones -> personas (m2m; columna renombrada a "Checkin" 19-jun, id estable)

L_ASIS_PERSONA = "c5feh1enr93lxdu"   # asistencias -> persona

L_ASIS_SESION = "c0rtlu1u4dt17kr"    # asistencias -> sesion

T_PROYECTOS = "mrgzxjc0ykmj9pk"

L_PROY_MIEMBROS = "c4dwqncvgjhq4m8"  # proyectos -> personas (miembros del proyecto)

L_PERSONA_SESIONES = "c4bb25mgcv6ghak"

L_PERSONA_PROYECTOS = "cknlb4k94rqjqhq"

L_PERSONA_PAGOS = "cz8lk59aw92xg9p"

L_PERSONA_INSCRIPCIONES = "c7ofb5a4o5qb1q2"

T_CONVERSACIONES = "mtfpik394m8r7ih"

ALQUILER_DESDE = "alquiler_desde"

ALQUILER_HASTA = "alquiler_hasta"

ALQUILER_DEPOSITO = "alquiler_deposito"

CASILLAS_ALQUILER = (ALQUILER_DESDE, ALQUILER_HASTA, ALQUILER_DEPOSITO)

ESTADOS_TERMINALES = ("CANCELADA", "POSPUESTA")

SESION_FIELDS = ("Id,fecha,sala,servicio,estado,nombre,hora_inicio,hora_fin,duracion_horas,"
                 "cantidad_personas,personas_real,horas_alquiler,monto_total,total_real,"
                 "descuento,descuento_motivo,proyecto,adicionales,instrumentacion,equipamiento_extra,"
                 # `asignado_a` es la PROMESA (quién se comprometió a atender) y `atendio` el
                 # ACTA (quién atendió). Se piden los dos y NO son redundantes: la app usa el
                 # primero solo para PRE-CARGAR el segundo en el check-in, y quien está en el
                 # mostrador puede cambiarlo. Que difieran es el dato — dice que alguien se
                 # comprometió y fue otro. Y como se cobra por horas ATENDIDAS, lo que se paga
                 # sigue a `atendio`, nunca a `asignado_a`.
                 "atendio,asignado_a,codigo,event_id,telefono_cliente,"
                 # El PAQUETE al que pertenece la reserva. Se piden los dos campos: el
                 # enlace trae el código, y `paquetes_id` es el respaldo para cuando no
                 # —un enlace de NocoDB vuelve con el `Id` y LA COLUMNA DE DISPLAY, nada
                 # más, así que el código depende de un ajuste de la UI que nadie vigila.
                 # Medido: los dos sobreviven a este `fields` explícito.
                 "paquetes,paquetes_id,"
                 "cuenta_cerrada_en,cuenta_cerrada_por,cuenta_nota,"
                 # AL1: periodo y depósito de un alquiler (la ficha los muestra; no se editan aquí).
                 + ",".join(CASILLAS_ALQUILER))

SESION_FIELDS_LUCY = SESION_FIELDS + ",visita_feedback"

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Santo_Domingo")
except Exception:
    TZ = timezone(timedelta(hours=-4))  # RD no tiene horario de verano

def hoy_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")

class SoloLectura(Exception):
    """NocoDB no contesta: se puede leer (por el desvío) pero NO se puede escribir.

    En este repo NO se levanta nunca: no hay desvío de lectura (ver el encabezado del módulo). Lo de abajo describe la App.

    🔑 NO hereda de `RuntimeError` a propósito. Media docena de sitios de este archivo hacen
    `except RuntimeError` alrededor de una escritura para seguir de largo con un aviso —son
    operaciones de segunda, como ligar un pago después de crearlo—. Si esto fuera un
    `RuntimeError`, esos `except` se lo tragarían y la pantalla diría que el pago se guardó.
    Siendo otra cosa, sube hasta el despachador y se convierte en un 503 con su motivo.

    📌 `pudo_salir` (14-sep-2026): ¿el pedido llegó a mandarse a NocoDB antes de esto? `nc()` lo
    sabe y lo dice: False cuando el desvío ya estaba declarado y ni se intentó, o cuando el
    fallo prueba que no salió (`_no_llego_a_salir`); True cuando `_nc_directo` YA mandó el
    pedido, falló, y ese fallo declaró la caída. Por defecto True:
    lo que no se sabe cuenta como «pudo salir», y entonces nadie puede afirmar «no se guardó».
    Y también es True si OTRO paso del mismo pedido de la persona ya se mandó (ver
    `_mi_pedido`): «este paso no salió» no es «no se guardó nada».
    `error` es el fallo original de NocoDB, si lo hubo.
    """

    def __init__(self, mensaje, pudo_salir=True, error=None):
        super().__init__(mensaje)
        self.pudo_salir = bool(pudo_salir)
        self.error = error

class ErrorDeNocodb(RuntimeError):
    """NocoDB CONTESTÓ con un código de error HTTP. `status` es ese código.

    🔑 Hereda de `RuntimeError` y conserva el mensaje de siempre (`NocoDB <código> en …`) a
    propósito: todos los `except RuntimeError` de este archivo, y `_es_respuesta_de_nocodb`,
    siguen viéndolo igual. Lo que agrega es el código como DATO, para que quien tenga que decidir
    por él (el aviso del guardado del conteo, `causa_del_fallo_al_guardar`) no tenga que leerlo
    del texto.
    """

    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status = int(status)

class EsquemaDeNocodbEsSoloLectura(RuntimeError):
    """La app pidió ESCRIBIR el esquema de NocoDB. No se manda: se corta acá.

    Se hereda de `RuntimeError` a propósito: los `except RuntimeError` que ya rodean a `nc()`
    la van a atrapar igual que a un error de NocoDB, así que un llamador viejo no revienta de
    una forma nueva. Y como es su propia clase, un test puede exigir exactamente ésta y no
    confundirla con «NocoDB devolvió 400»."""

_RUTA_ESQUEMA = re.compile(r"/meta/", re.I)

_VERBOS_QUE_LEEN = frozenset({"GET", "HEAD"})

def _es_escritura_de_esquema(method, path):
    """¿Este pedido escribiría el esquema de NocoDB? Mira los VALORES, no el código fuente."""
    return (str(method or "").strip().upper() not in _VERBOS_QUE_LEEN
            and bool(_RUTA_ESQUEMA.search(str(path or ""))))

MENSAJE_FALLO_TRAS_ESCRIBIR = (
    "Algo falló mientras se guardaba, y no se puede confirmar si lo que mandaste quedó "
    "guardado. NO lo repitas todavía: abre la cuenta (o el pago, o la caja) y mira si ya "
    "aparece. Solo si no aparece, vuelve a hacerlo. Detalle técnico: ")

# 📌 ¿ESTE PEDIDO YA MANDÓ ALGUNA ESCRITURA A NOCODB? Cuenta por hilo; `servidor.py` la pone en cero al empezar cada pedido.
# Igual que `_mi_pedido` de la App (`server.py`, `estrenar_la_cuenta_de_escrituras`).
_mi_pedido = threading.local()


def estrenar_la_cuenta_de_escrituras():
    _mi_pedido.escrituras = 0


def escrituras_mandadas_en_este_pedido():
    return getattr(_mi_pedido, "escrituras", 0)


def _no_llego_a_salir(e):
    """¿Este fallo prueba que el pedido NO llegó a NocoDB? Solo cuando ni la conexión se abrió: conexión rechazada o
    nombre que no resuelve. Todo lo demás deja abierta la posibilidad de que NocoDB lo recibiera (copiado de la App)."""
    return (isinstance(e, urllib.error.URLError)
            and isinstance(e.reason, (ConnectionRefusedError, socket.gaierror)))


def marcar_fallo_tras_escribir(status, obj):
    """La regla de `send_json` de la App: si este pedido ya mandó una escritura, un error (≥400, con cuerpo de dict) pudo
    haber quedado guardado. Se le pone delante el aviso y `sin_confirmar: true`. Un pedido sin escritura, igual que antes."""
    if status >= 400 and isinstance(obj, dict) and "sin_confirmar" not in obj and escrituras_mandadas_en_este_pedido() > 0:
        return dict(obj, error=MENSAJE_FALLO_TRAS_ESCRIBIR + str(obj.get("error", "")), sin_confirmar=True)
    return obj


def _nc_directo(method, path, body=None, query=None):
    """La llamada de siempre a la API v2 de NocoDB.

    Lo único que cambió (5-sep-2026): antes de armar la petición se comprueba que no sea una
    escritura al ESQUEMA. Ver el bloque de arriba. Paso 5b: cada escritura se cuenta ANTES de mandarla (si la
    respuesta se pierde, ya cuenta) y se descuenta solo si ni la conexión se abrió (como `_nc_directo` de la App)."""
    if _es_escritura_de_esquema(method, path):
        raise EsquemaDeNocodbEsSoloLectura(
            f"la app NO escribe el esquema de NocoDB, y este pedido lo haría: "
            f"{str(method).upper()} {path}. Quitar o reescribir las opciones de un select "
            f"BORRA el valor de las filas que lo tenían, en silencio y con HTTP 200 "
            f"(medido el 5-sep-2026). Agregar un nombre a `atendio` o `asignado_a` es un "
            f"clic a mano en NocoDB; la pantalla «El equipo» dice cuál falta.")
    url = NOCODB_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    es_escritura = str(method or "").strip().upper() not in _VERBOS_QUE_LEEN
    if es_escritura:
        _mi_pedido.escrituras = escrituras_mandadas_en_este_pedido() + 1
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"xc-token": NOCODB_TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        raise ErrorDeNocodb(e.code, f"NocoDB {e.code} en {method} {path}: {detail}")
    except Exception as e:
        if es_escritura and _no_llego_a_salir(e):
            # Ni la conexión se abrió: este pedido no cuenta como mandado.
            _mi_pedido.escrituras = max(0, escrituras_mandadas_en_este_pedido() - 1)
        raise

def nc(method, path, body=None, query=None):
    """Llamada a la API v2 de NocoDB. Sin el desvío de lectura de la App: si NocoDB no contesta, el error sale tal cual."""
    return _nc_directo(method, path, body, query)

# Copiado de mercadeo.py:1321 (en la App, server.py lo re-exporta).
MERCADEO_ENVIO_ESTADOS = {"pendiente": "Sin decidir", "aprobado": "Aprobado", "quitado": "Quitado", "en_camino": "En camino", "aceptado": "Aceptado por WhatsApp", "no_salio": "No salió"}      # cómo se dice cada estado de un mensaje en la pantalla de Aprobaciones

def nc_list_all(table, query=None):
    """Pagina hasta traer todos los registros de una tabla."""
    out, offset = [], 0
    while True:
        q = dict(query or {})
        q.update({"limit": 200, "offset": offset})
        page = nc("GET", f"/api/v2/tables/{table}/records", query=q)
        out.extend(page.get("list", []))
        info = page.get("pageInfo", {})
        if info.get("isLastPage", True):
            return out
        offset += 200

def nc_link_path(table, link_id, record_id):
    return f"/api/v2/tables/{table}/links/{link_id}/records/{int(record_id)}"

def nc_unlink(table, link_id, record_id, target_ids):
    """Quita el vínculo, NO la fila. Idempotente: sin objetivos no hace ni una request, y
    NocoDB acepta sin protestar que se le pida quitar un link que ya no está."""
    ids = [int(i) for i in (target_ids or [])]
    if not ids:
        return
    nc("DELETE", nc_link_path(table, link_id, record_id), body=[{"Id": i} for i in ids])

CARA_DIMS = 128

CARA_BYTES = CARA_DIMS * 4          # 512

CARA_B64_CHARS = 684                # len(base64.b64encode(b"\0" * 512))

CARA_RANURAS = 3

CARA_COLUMNA = "caras"

CARA_SEPARADOR = "|"

_caras_cache = {"data": None}

_caras_lock = threading.Lock()

def _cara_desde_base64(texto):
    """Los 128 `float32` de una cara, o `None` si eso no es una cara.

    `None` es el único «no»: quien llame decide qué contesta. Se rechaza lo que no mida 512
    bytes y lo que traiga un número que no sea finito — un `NaN` en un vector envenena toda
    comparación posterior, porque cualquier cuenta con él vuelve a dar `NaN` y el orden por
    distancia deja de significar nada.
    """
    if not isinstance(texto, str) or len(texto) != CARA_B64_CHARS:
        return None
    try:
        crudo = base64.b64decode(texto, validate=True)
    except (ValueError, TypeError):
        return None
    if len(crudo) != CARA_BYTES:
        return None
    # `<` = little-endian, DICHO. El navegador lo escribe con un `DataView` en little-endian
    # explícito (ver `vectorABase64` en `app.js`), así que acá no se supone la endianidad de
    # ninguna máquina: las dos puntas dicen lo mismo en voz alta.
    vec = struct.unpack("<%df" % CARA_DIMS, crudo)
    if not all(math.isfinite(x) for x in vec):
        return None
    return vec

def _cara_a_base64(vec):
    """El camino de vuelta, para guardar. Falla ruidoso si le dan algo que no es un vector."""
    if len(vec) != CARA_DIMS:
        raise ValueError(f"un vector de cara son {CARA_DIMS} números, vinieron {len(vec)}")
    return base64.b64encode(struct.pack("<%df" % CARA_DIMS, *vec)).decode("ascii")

def _caras_de_celda(texto):
    """Los vectores guardados en una celda, descartando en silencio lo que no lo sea.

    Lo ilegible se tira en vez de reventar: una celda que alguien tocó a mano en NocoDB no
    puede dejar sin cámara a todo el estudio. Lo que se pierde es un reconocimiento; lo que se
    ganaría rompiendo es nada.
    """
    salida = []
    for trozo in str(texto or "").split(CARA_SEPARADOR):
        trozo = trozo.strip()
        if not trozo:
            continue
        vec = _cara_desde_base64(trozo)
        if vec is not None:
            salida.append(vec)
    return salida[-CARA_RANURAS:]

def invalidate_caras():
    with _caras_lock:
        _caras_cache["data"] = None

class FichaUnida(Exception):
    """La ficha está marcada como unida a otra: no se le guarda una cara."""

class FichaQuitada(Exception):
    """La ficha está guardada aparte (la quitaron de Personas): no se le guarda una cara ni se le registra una visita."""

def _opciones_de_columna(col):
    """Los títulos de las opciones de UNA columna Select/MultiSelect, tal como NocoDB la describe."""
    return [o["title"] for o in (col.get("colOptions") or {}).get("options", [])]

TODAS_LAS_COLUMNAS = object()

def _opciones_select(table_id, titulo, columnas=None):
    """Opciones (títulos) de una columna Select/MultiSelect — fuente única = NocoDB.

    🔑 ES LA ÚNICA LECTURA DEL ESQUEMA DE LA APP (`tests/test_no_nace_otra_lista.py` cuenta los
    sitios donde aparece la ruta `/meta/`). Con `columnas` —una lista de títulos— devuelve en
    cambio `{título: columna o None}` con la descripción COMPLETA que NocoDB da de cada una
    (`uidt`, opciones…), en UNA sola lectura: es lo que usa la edición de la ficha para saber la
    forma real de cada campo. No hay otro sitio que lea el esquema."""
    m = nc("GET", f"/api/v2/meta/tables/{table_id}")
    if columnas is TODAS_LAS_COLUMNAS:
        return [c for c in m.get("columns", []) if isinstance(c, dict)]
    if columnas is not None:
        por_titulo = {c.get("title"): c for c in m.get("columns", [])}
        return {t: por_titulo.get(t) for t in columnas}
    col = next((c for c in m.get("columns", []) if c.get("title") == titulo), None)
    return _opciones_de_columna(col) if col else []

CAMPOS_DE_UNA_FICHA = "Id,telefono,telefono_2,unida_a,quitada_el"

SALTOS_DE_UNION = 10        # cuántas marcas `unida_a` se siguen antes de dar la ficha por inexistente

ENTRADA_ORIGENES = ("mensaje", "dictado", "reserva", "recuperado")

class _EntradaSinConfirmar(Exception):
    """Una lectura o escritura de la bandeja o de las fichas no se confirmó."""

def _entrada_id(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else None

def _bandeja_leer(estados, campos, visitar, tamano, tope, pagina_de=None):
    """Pasa a `visitar` las filas de la bandeja con alguno de esos `estados`, por páginas con cursor por `Id`; devuelve si no queda ninguna sin leer.

    `pagina_de` es quien lee una página (la de NocoDB por defecto, o la de Personas para el cuadro): misma forma, `(filas, es_la_última)`.
    El tope cuenta las lecturas de todos los estados juntos, en orden: al agotarse, la lectura siguiente es un sondeo de una fila.
    """
    lecturas = 0
    leer = pagina_de or _bandeja_pagina
    for estado in estados:
        cursor = 0
        while True:
            sondeo = lecturas >= tope
            lecturas += 1
            pagina, ultima = leer(estado, cursor, 1 if sondeo else tamano, campos)
            if sondeo:
                if pagina:
                    return False
                if not ultima:
                    raise _EntradaSinConfirmar()
                break
            for fila in pagina:
                visitar(estado, fila)
            if ultima:
                break
            if not pagina or pagina[-1]["Id"] <= cursor:
                raise _EntradaSinConfirmar()
            cursor = pagina[-1]["Id"]
    return True

def _bandeja_pagina(estado, cursor, limite, campos):
    """Una página de la bandeja. La lectura real es de `personas.py` (perezoso: `personas` importa este módulo)."""
    import personas
    return personas._bandeja_pagina(estado, cursor, limite, campos)


def _clave_telefono_de_personas(celda):
    """`personas.clave_telefono`, pedido al momento de la llamada (perezoso: `personas` importa este módulo)."""
    import personas
    return personas.clave_telefono(celda)

def _sesiones_por_telefono(tels):
    """Las sesiones cuyo `telefono_cliente` es uno de esos teléfonos.

    El `where` le pide a NocoDB, por igualdad exacta, el valor canónico de esos teléfonos —el
    que `clave_telefono` saca de la ficha—; el filtro de abajo aplica `clave_telefono` a cada
    fila devuelta y descarta las que no sean de la ficha.
    """
    if not tels:
        return []
    where = "~or".join(f"(telefono_cliente,eq,{t})" for t in tels)
    filas = nc_list_all(T_SESIONES, {"where": where, "fields": SESION_FIELDS_LUCY})
    return [f for f in filas if _clave_telefono_de_personas(f.get("telefono_cliente")) in tels]

_APRENDIZAJE_CAMPOS_NUNCA = ("caras", "bsuid", "credito")

PORTAL_COLUMNAS_VETADAS = tuple(sorted((set(_APRENDIZAJE_CAMPOS_NUNCA) | {CARA_COLUMNA}) - {"credito"}))
