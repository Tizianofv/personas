# -*- coding: utf-8 -*-
"""DOBLE DE NOCODB QUE ESCRIBE, para las pruebas de las escrituras de Personas (paso 5b).

Sirve en 127.0.0.1 copias en memoria de las tablas de `doble_nocodb` (sus datos ficticios), y deja que se escriban:
  GET   /api/v2/tables/<t>/records            lista (where, fields, limit, offset)
  GET   /api/v2/tables/<t>/records/<id>       una fila; 404 si no existe
  PATCH /api/v2/tables/<t>/records            cuerpo: una fila o una lista; cada una por su Id; 404 si el Id no existe
  POST  /api/v2/tables/<t>/records            cuerpo: una fila o una lista; el Id nuevo es el mayor + 1
  GET   /api/v2/meta/tables/<t>               solo lectura: las columnas que el doble declara
Cualquier otro pedido se apunta en `errores` y responde 500 (la prueba lo ve).

`pedidos`: cada pedido que llega, en orden, con método, ruta, query (ordenada) y cuerpo. La cabecera NO se apunta: ahí va la
llave y `xc-token`, y ninguna de las dos debe quedar en un registro. `caidas`: métodos que responden 500 SIEMPRE (la base no
contesta para esa operación); el pedido se apunta igual, para que la prueba vea que salió y no se escribió.

Lo que NO ve (declarado): no imita los errores de NocoDB real (ni sus códigos ni sus textos); solo que una operación cae o
no cae. Solo 127.0.0.1. No toca NocoDB real.
"""
import copy
import http.server
import json
import re
import threading
import urllib.parse

import doble_nocodb

_CONDICION = re.compile(r"\((\w+),(eq|neq|gt|gte|lt|lte|like),([^)]*)\)")
_QUERY_PERMITIDA = {"fields", "where", "limit", "offset", "sort"}
_METODOS_CON_CUERPO = ("POST", "PATCH", "PUT", "DELETE")


class DobleEscrituras:
    def __init__(self, caidas=()):
        self.tablas = {t: copy.deepcopy(filas) for t, filas in doble_nocodb.TABLAS.items()}
        self.pedidos = []
        self.errores = []
        self.caidas = set(caidas)
        self.servidor = None
        self._cerrojo = threading.Lock()

    def _filas(self, tabla, where):
        filas = list(self.tablas[tabla])
        if not where:
            return filas
        partes = _CONDICION.findall(where)
        separadores = set(re.findall(r"~(and|or)", where))
        residuo = _CONDICION.sub("", where)
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
                else:
                    raise ValueError("operador no soportado en el doble de escrituras: " + op)
            return all(resultados) if modo == "and" else any(resultados)
        return [f for f in filas if cumple(f)]

    @staticmethod
    def _con_campos(fila, fields):
        if not fields:
            return dict(fila)
        campos = [c.strip() for c in fields.split(",") if c.strip()]
        return {c: fila[c] for c in campos if c in fila}

    def _buscar(self, tabla, id_fila):
        for fila in self.tablas[tabla]:
            if fila.get("Id") == id_fila:
                return fila
        return None

    def responder(self, metodo, ruta, query, cuerpo):
        with self._cerrojo:
            self.pedidos.append({"metodo": metodo, "ruta": ruta, "query": dict(sorted(query.items())), "cuerpo": cuerpo})
            if metodo in self.caidas:
                return 500, {"msg": "doble: la base no contesta"}
            if metodo == "GET":
                meta = re.fullmatch(r"/api/v2/meta/tables/([^/]+)", ruta)
                if meta:
                    if meta.group(1) not in self.tablas:
                        self.errores.append("metadatos de tabla desconocida: %s" % ruta)
                        return 404, {"msg": "doble: tabla desconocida"}
                    return 200, {"id": meta.group(1), "columns": doble_nocodb.COLUMNAS_META.get(meta.group(1), [])}
            m = re.fullmatch(r"/api/v2/tables/([^/]+)/records(?:/(\d+))?", ruta)
            if not m or m.group(1) not in self.tablas:
                self.errores.append("tabla o ruta desconocida: %s %s" % (metodo, ruta))
                return 404, {"msg": "doble: tabla desconocida"}
            if set(query) - _QUERY_PERMITIDA:
                self.errores.append("query no soportada: %s" % sorted(set(query) - _QUERY_PERMITIDA))
                return 500, {"msg": "doble: query no soportada"}
            tabla, id_ruta = m.group(1), m.group(2)
            if metodo == "GET" and id_ruta is not None:
                fila = self._buscar(tabla, int(id_ruta))
                if fila is None:
                    return 404, {"msg": "doble: no existe el registro"}
                return 200, self._con_campos(fila, query.get("fields"))
            if metodo == "GET" and id_ruta is None:
                try:
                    filas = self._filas(tabla, query.get("where"))
                except ValueError as e:
                    self.errores.append(str(e))
                    return 500, {"msg": "doble: %s" % e}
                filas = [self._con_campos(f, query.get("fields")) for f in filas]
                limite = int(query.get("limit", 25))
                desde = int(query.get("offset", 0))
                pagina = filas[desde:desde + limite]
                total = len(filas)
                return 200, {"list": pagina, "pageInfo": {"totalRows": total, "page": desde // max(limite, 1) + 1,
                                                         "pageSize": limite, "isLastPage": desde + len(pagina) >= total}}
            if metodo == "PATCH" and id_ruta is None:
                filas = cuerpo if isinstance(cuerpo, list) else [cuerpo]
                salida = []
                for entrada in filas:
                    fila = self._buscar(tabla, entrada.get("Id") if isinstance(entrada, dict) else None)
                    if fila is None:
                        return 404, {"msg": "doble: no existe el registro para el PATCH"}
                    fila.update({k: v for k, v in entrada.items() if k != "Id"})
                    salida.append(dict(fila))
                return 200, salida if isinstance(cuerpo, list) else salida[0]
            if metodo == "POST" and id_ruta is None:
                entradas = cuerpo if isinstance(cuerpo, list) else [cuerpo]
                salida = []
                for entrada in entradas:
                    if not isinstance(entrada, dict):
                        return 400, {"msg": "doble: el POST pide un objeto"}
                    nuevo_id = max([f.get("Id") or 0 for f in self.tablas[tabla]] + [0]) + 1
                    fila = {k: v for k, v in entrada.items() if k != "Id"}
                    fila = dict(fila, Id=nuevo_id)
                    self.tablas[tabla].append(fila)
                    salida.append(dict(fila))
                return 200, salida if isinstance(cuerpo, list) else salida[0]
            self.errores.append("método no soportado en el doble de escrituras: %s %s" % (metodo, ruta))
            return 405, {"msg": "doble: método no soportado"}

    def arrancar(self):
        doble = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _cuerpo(self):
                largo = int(self.headers.get("Content-Length") or 0)
                crudo = self.rfile.read(largo) if largo else b""
                if not crudo:
                    return None
                try:
                    return json.loads(crudo.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return {"__no_json__": crudo.decode("utf-8", "replace")}

            def _atender(self, metodo):
                url = urllib.parse.urlsplit(self.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
                cuerpo = self._cuerpo() if metodo in _METODOS_CON_CUERPO else None
                codigo, datos = doble.responder(metodo, url.path, query, cuerpo)
                self._enviar(codigo, datos)

            def do_GET(self):
                self._atender("GET")

            def do_POST(self):
                self._atender("POST")

            def do_PATCH(self):
                self._atender("PATCH")

            def do_PUT(self):
                self._atender("PUT")

            def do_DELETE(self):
                self._atender("DELETE")

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
