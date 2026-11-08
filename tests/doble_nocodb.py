# -*- coding: utf-8 -*-
"""DOBLE DE NOCODB PARA LAS PRUEBAS DE CONTRATO del programa de Personas.

Copiado tal cual de `contrato_dorado/generar.py` de la App de registro, commit `0b48b5d` (sus datos ficticios, su clase
`Doble` que solo contesta GET, y los 16 pedidos `PEDIDOS` con los que se sacó `contrato_dorado/contrato.json`).
Responde solo en 127.0.0.1. No toca NocoDB real.
"""
import http.server
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

LLAVE_LECTURA = "llave-de-prueba-lectura-personas"
TABLA_ANOTACIONES = "tabla-anotaciones-prueba"
T_PERSONAS = "mhh7qqeru2ez8q1"        # constante de server.py (la App la usa tal cual)
T_ASISTENCIAS = "mt5snh0plx7z0ga"    # constante de server.py

PERSONAS = [
    {"Id": 1, "nombre": "Persona de prueba 1", "nombre_whatsapp": "", "telefono": "18097770001", "telefono_2": "",
     "bsuid": "DO.0000000000000001", "email": "p1@ejemplo.test", "email_2": "", "instagram": "", "Cumpleanos": "1990-03-14",
     "credito": 0, "quitada_el": None, "unida_a": None, "CreatedAt": "2026-10-01T10:00:00Z"},
    {"Id": 2, "nombre": "Persona de prueba 2", "nombre_whatsapp": "", "telefono": "18097770002", "telefono_2": "",
     "bsuid": None, "email": "p2@ejemplo.test", "email_2": "", "instagram": "", "Cumpleanos": None,
     "credito": 250, "quitada_el": None, "unida_a": None, "CreatedAt": "2026-10-02T10:00:00Z"},
    {"Id": 3, "nombre": "Persona de prueba 3", "nombre_whatsapp": "", "telefono": "18097770003", "telefono_2": "",
     "bsuid": None, "email": "", "email_2": "", "instagram": "", "Cumpleanos": None,
     "credito": 0, "quitada_el": "2026-10-05T00:00:00Z", "unida_a": None, "CreatedAt": "2026-10-03T10:00:00Z"},
    {"Id": 4, "nombre": "Persona de prueba 4", "nombre_whatsapp": "", "telefono": "18097770001", "telefono_2": "",
     "bsuid": None, "email": "", "email_2": "", "instagram": "", "Cumpleanos": None,
     "credito": 0, "quitada_el": None, "unida_a": 1, "CreatedAt": "2026-10-04T10:00:00Z"},
]
ANOTACIONES = [
    {"Id": 1, "ficha_id": 1, "clase": "origen", "valor": "instagram", "canal": "", "dicho_el": "", "quien": "", "cuando": "2026-10-02T09:00:00Z"},
    {"Id": 2, "ficha_id": 2, "clase": "permiso", "valor": "si", "canal": "", "dicho_el": "", "quien": "", "cuando": "2026-10-03T09:00:00Z"},
]
ASISTENCIAS = [
    {"Id": 1, "persona_id": 1, "checkin_at": "2026-10-20T12:00:00Z"},
    {"Id": 2, "persona_id": 2, "checkin_at": "2026-10-21T12:00:00Z"},
]
# El registro de fichas quitadas (`personas_quitadas`, paso 5c). Su id va en `NOCODB_T_PERSONAS_QUITADAS` tanto en las pruebas del repo
# como en la copia de la App que saca el dorado de `servidor.py` (ruta «borradas»). Dos filas: una «quitada» (sale en la lista) y una
# «devuelta» (no sale: la prueba mira que el filtro por estado funcione). Datos ficticios.
T_QUITADAS = "tabla-quitadas-prueba"
_ANTES_DE_PRUEBA = {"nombre": "Persona de prueba 3", "nombre_whatsapp": "", "telefono": "18097770003", "telefono_2": "",
                    "email": "", "email_2": "", "bsuid": None, "caras": None, "quitada_el": "2026-10-05T00:00:00Z"}
QUITADAS = [
    {"Id": 1, "ficha_id": 3, "estado": "quitada", "antes": json.dumps(_ANTES_DE_PRUEBA, ensure_ascii=False),
     "creada_por": "Persona de prueba quien", "creada_en": "2026-10-05T12:00:00Z"},
    {"Id": 2, "ficha_id": 4, "estado": "devuelta", "antes": json.dumps(dict(_ANTES_DE_PRUEBA, nombre="Persona de prueba 4"), ensure_ascii=False),
     "creada_por": "Persona de prueba quien", "creada_en": "2026-10-06T12:00:00Z"},
]
# La bandeja de «Por resolver» (`NOCODB_T_BANDEJA_PERSONAS`, paso 5c parte 2). Una marca de prueba que no coincide con ningún grupo real:
# la lista de «resueltos» de la pantalla queda vacía. Eso NO prueba la rama de «resueltos» (declarado en el mapa).
T_BANDEJA = "tabla-bandeja-prueba"
BANDEJA = [
    {"Id": 1, "origen": "por-resolver", "clave": "resuelto-" + "0" * 40, "estado": "resuelto",
     "resuelto_por": "Persona de prueba quien", "resuelto_en": "2026-10-07T12:00:00Z"},
]
# Tablas que LEE «revisar un borrado» (parte 5: `personas.revisar_borrado`) y que el doble no tenía. Van VACÍAS a propósito: ninguna
# ficha del doble tiene sesiones, conversaciones, envíos de Mercadeo ni uniones abiertas. Así la lectura de cada una contesta sin error
# (una tabla que no se conoce da error en el doble, y el dorado lo rechaza). Sus ids son los de la App (`base.T_SESIONES`,
# `base.T_CONVERSACIONES`) y los de prueba para las que van por variable de entorno (envíos y uniones).
T_SESIONES = "mja78x7qcagta8z"       # constante de base.py (la App la usa tal cual)
T_CONVERSACIONES = "mtfpik394m8r7ih"  # constante de base.py
T_MERCADEO_ENVIOS = "tabla-envios-prueba"  # va por NOCODB_T_MERCADEO_ENVIOS en el entorno de la foto y de la prueba
T_UNIONES = "tabla-uniones-prueba"         # va por NOCODB_T_UNIONES_PERSONAS en el entorno de la foto y de la prueba
TABLAS = {T_PERSONAS: PERSONAS, TABLA_ANOTACIONES: ANOTACIONES, T_ASISTENCIAS: ASISTENCIAS, T_QUITADAS: QUITADAS, T_BANDEJA: BANDEJA,
          T_SESIONES: [], T_CONVERSACIONES: [], T_MERCADEO_ENVIOS: [], T_UNIONES: []}

# Columnas que el doble declara para la tabla de Personas. Son las claves de las filas de prueba más UNA columna inventada
# («columna_de_prueba_sin_clasificar») que la App no conoce: así la lista de «sin clasificar» tiene contenido real que el contrato guarda.
# OJO: es el esquema del DOBLE, no el de NocoDB real (ver NUBE3_REPORTE.md).
_SISTEMA = {"Id", "CreatedAt", "UpdatedAt"}
COLUMNAS_META = {
    T_PERSONAS: [{"title": c, "uidt": "Number" if c == "Id" else "SingleLineText", "system": c in _SISTEMA}
                 for c in sorted({k for fila in PERSONAS for k in fila})]
                + [{"title": "columna_de_prueba_sin_clasificar", "uidt": "SingleLineText", "system": False}],
}
_CONDICION = re.compile(r"\((\w+),(eq|neq|gt|gte|lt|lte|like),([^)]*)\)")
_QUERY_PERMITIDA = {"fields", "where", "limit", "offset", "sort"}


class Doble:
    """Doble de NocoDB, solo GET. Lo que pide fuera de lo conocido se registra como error y responde 500 (la prueba lo ve)."""

    def __init__(self, caidas=()):
        self.errores = []
        self.no_get = []
        self.lecturas = 0
        self.servidor = None
        # `caidas`: métodos que responden 500 SIEMPRE (la base no contesta). Solo GET aquí. Un pedido caído no es un error del doble.
        self.caidas = set(caidas)
        self.caidas_servidas = 0

    def _filas(self, tabla, where):
        filas = list(TABLAS[tabla])
        if not where:
            return filas
        partes = _CONDICION.findall(where)
        separadores = set(re.findall(r"~(and|or)", where))
        residuo = re.sub(r"~(and|or)", "", _CONDICION.sub("", where))   # lo que queda fuera de las condiciones y de sus conectores
        if residuo.strip("~") or len(separadores) > 1:
            raise ValueError("where con forma no soportada")
        modo = separadores.pop() if separadores else "and"
        def cumple(fila):
            resultados = []
            for campo, op, valor in partes:
                v = fila.get(campo)
                v = "" if v is None else str(v)
                if op == "eq":
                    resultados.append(v == valor)
                elif op == "neq":
                    resultados.append(v != valor)
                elif op == "like":
                    resultados.append(valor.strip("%").lower() in v.lower())
                elif op in ("gt", "gte", "lt", "lte"):
                    # Comparación numérica (la que usan `Id` y `credito`). Un valor vacío no cumple.
                    if v == "":
                        resultados.append(False)
                    else:
                        a, b = float(v), float(valor)
                        resultados.append({"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op])
                else:
                    raise ValueError("operador de orden no soportado en el doble: " + op)
            return all(resultados) if modo == "and" else any(resultados)
        return [f for f in filas if cumple(f)]

    def responder(self, metodo, ruta, query):
        if metodo != "GET":
            self.no_get.append(metodo)
            return 405, {"msg": "doble: solo GET"}
        if "GET" in self.caidas:
            self.caidas_servidas += 1
            return 500, {"msg": "doble: la base no contesta"}
        # Enlaces (`/links/<enlace>/records/<Id>`): VACÍOS, como en el modo de unión de `doble_escrituras`. La ficha del doble no tiene
        # nada enlazado (proyectos, pagos). Una lectura de enlace cuenta como lectura, igual que las demás.
        if re.fullmatch(r"/api/v2/tables/([^/]+)/links/([^/]+)/records/(\d+)", ruta):
            self.lecturas += 1
            return 200, {"list": [], "pageInfo": {"totalRows": 0, "page": 1, "pageSize": 200, "isLastPage": True}}
        # La ruta de metadatos de una tabla (la que lee la App para saber sus columnas): se reconoce por su forma, y solo se lee.
        meta = re.fullmatch(r"/api/v2/[a-z]+/tables/([^/]+)", ruta)
        if meta:
            if meta.group(1) not in COLUMNAS_META:
                self.errores.append("metadatos de tabla desconocida: %s" % ruta)
                return 404, {"msg": "doble: tabla desconocida"}
            self.lecturas += 1
            return 200, {"id": meta.group(1), "columns": COLUMNAS_META[meta.group(1)]}
        # Un registro por su `Id` (`GET .../records/<Id>`, la forma que lee la ficha del portal). Si no existe: 404, como NocoDB.
        uno = re.fullmatch(r"/api/v2/tables/([^/]+)/records/(\d+)", ruta)
        if uno:
            if uno.group(1) not in TABLAS:
                self.errores.append("tabla desconocida: %s" % ruta)
                return 404, {"msg": "doble: tabla desconocida"}
            self.lecturas += 1
            for fila in TABLAS[uno.group(1)]:
                if fila.get("Id") == int(uno.group(2)):
                    return 200, dict(fila)
            return 404, {"msg": "doble: registro no existe"}
        m = re.fullmatch(r"/api/v2/tables/([^/]+)/records", ruta)
        if not m or m.group(1) not in TABLAS:
            self.errores.append("tabla desconocida: %s" % ruta)
            return 404, {"msg": "doble: tabla desconocida"}
        if set(query) - _QUERY_PERMITIDA:
            self.errores.append("query no soportada: %s" % sorted(set(query) - _QUERY_PERMITIDA))
            return 500, {"msg": "doble: query no soportada"}
        self.lecturas += 1
        tabla = m.group(1)
        try:
            filas = self._filas(tabla, query.get("where"))
        except ValueError as e:
            self.errores.append(str(e))
            return 500, {"msg": "doble: %s" % e}
        if query.get("fields"):
            campos = [c.strip() for c in query["fields"].split(",") if c.strip()]
            filas = [{c: f[c] for c in campos if c in f} for f in filas]
        limite = int(query.get("limit", 25))
        desde = int(query.get("offset", 0))
        pagina = filas[desde:desde + limite]
        total = len(filas)
        return 200, {"list": pagina, "pageInfo": {"totalRows": total, "page": desde // max(limite, 1) + 1,
                                                 "pageSize": limite, "isLastPage": desde + len(pagina) >= total}}

    def arrancar(self):
        doble = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
                codigo, cuerpo = doble.responder("GET", url.path, query)
                self._enviar(codigo, cuerpo)

            def _otro(self):
                doble.no_get.append(self.command)
                self._enviar(405, {"msg": "doble: solo GET"})

            do_POST = do_PUT = do_PATCH = do_DELETE = _otro

            def _enviar(self, codigo, cuerpo):
                datos = json.dumps(cuerpo).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

        self.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        return "http://127.0.0.1:%d" % self.servidor.server_address[1]

    def parar(self):
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()


# Entradas fijas. `con_llave`: si la cabecera va puesta. Cada una es (nombre, método, ruta, cuerpo, con_llave).
PEDIDOS = [
    ("config_con_llave", "GET", "/api/servicio/personas/config", None, True),
    ("config_sin_llave", "GET", "/api/servicio/personas/config", None, False),
    ("identidad_telefono", "POST", "/api/servicio/personas/identidad", {"identidad": "18097770001"}, True),
    ("identidad_bsuid", "POST", "/api/servicio/personas/identidad", {"identidad": "DO.0000000000000001"}, True),
    ("identidad_sin_ficha", "POST", "/api/servicio/personas/identidad", {"identidad": "18097770999"}, True),
    ("identidad_sin_llave", "POST", "/api/servicio/personas/identidad", {"identidad": "18097770001"}, False),
    ("fichas_con_llave", "POST", "/api/servicio/personas/fichas", {}, True),
    ("fichas_sin_llave", "POST", "/api/servicio/personas/fichas", {}, False),
    ("anotaciones_todas", "POST", "/api/servicio/personas/anotaciones", {}, True),
    ("anotaciones_filtradas", "POST", "/api/servicio/personas/anotaciones",
     {"campos": "Id,ficha_id,clase,valor", "where": [["clase", "eq", "origen"]]}, True),
    ("anotaciones_where_roto", "POST", "/api/servicio/personas/anotaciones",
     {"where": [["clase", "eq", "x(y"]]}, True),
    ("anotaciones_sin_llave", "POST", "/api/servicio/personas/anotaciones", {}, False),
    ("pagina_primera", "POST", "/api/servicio/personas/pagina", {"q": "", "desde": 0, "limite": 2}, True),
    ("pagina_busqueda", "POST", "/api/servicio/personas/pagina", {"q": "prueba de", "desde": 0, "limite": 10, "col": "nombre"}, True),
    ("pagina_columna_mala", "POST", "/api/servicio/personas/pagina", {"q": "", "col": "no_existe"}, True),
    ("pagina_sin_llave", "POST", "/api/servicio/personas/pagina", {"q": ""}, False),
]


def _pedir(puerto, nombre, metodo, ruta, cuerpo, con_llave):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    cabeceras = {"Content-Type": "application/json"} if datos is not None else {}
    if con_llave:
        cabeceras["X-Personas-Lectura-Llave"] = LLAVE_LECTURA
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, ruta), data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            codigo, bruto = r.status, r.read()
    except urllib.error.HTTPError as e:
        codigo, bruto = e.code, e.read()
    try:
        cuerpo_resp = json.loads(bruto.decode("utf-8"))
    except ValueError:
        cuerpo_resp = {"__no_json__": bruto.decode("utf-8", "replace")}
    return {"nombre": nombre, "metodo": metodo, "ruta": ruta, "cuerpo": cuerpo, "con_llave": con_llave,
            "status": codigo, "respuesta": cuerpo_resp}


