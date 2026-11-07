# -*- coding: utf-8 -*-
"""Los escenarios de las escrituras de Registro en Personas, y cómo se corren. Lo usan DOS cosas, con la misma lista:
  · `tools/generar_escrituras_de_la_app.py`: corre la App de registro (copia `git archive 0b48b5d`) contra el doble y guarda lo que
    contesta y lo que el doble recibe, en `contrato_dorado/escrituras.json`;
  · `tests/test_escrituras_rutas.py`: corre `servidor.py` del repo contra el mismo doble y compara con ese archivo.

Cada escenario arranca un proceso nuevo (App o repo) y un doble nuevo, y corre sus pasos en orden. Un paso es un pedido HTTP
con una cabecera de llave, cuyo valor se nombra con un SÍMBOLO (`escritura`, `lectura_mercadeo`, `lectura_registro`, `vacia`,
`mala`, `ausente`): los valores reales están en `VALORES` y no se guardan en ningún registro.

Lo que se apunta de cada paso: el código, el cuerpo de la respuesta y los pedidos que llegaron al doble durante el paso
(método, ruta, query y cuerpo; nunca la cabecera).
"""
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import doble_escrituras

RUTA_ESCRITURA_CABECERA = "X-Personas-Registro-Escritura-Llave"
RUTA_LECTURA_REGISTRO_CABECERA = "X-Personas-Registro-Llave"
RUTA_LECTURA_MERCADEO_CABECERA = "X-Personas-Lectura-Llave"

# Valores de PRUEBA (no son secretos). Solo los usa el harness, nunca un registro.
VALORES = {
    "escritura": "llave-de-prueba-escritura-registro-personas",
    "lectura_mercadeo": "llave-de-prueba-lectura-mercadeo-personas",
    "lectura_registro": "llave-de-prueba-lectura-registro-personas",
}
ENTORNO_BASE = {
    "PERSONAS_LECTURA_LLAVE": VALORES["lectura_mercadeo"],
    "PERSONAS_REGISTRO_LLAVE": VALORES["lectura_registro"],
    "PERSONAS_REGISTRO_ESCRITURA_LLAVE": VALORES["escritura"],
}
ENTORNO_MINIMO = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}

VEC = [0.5] * 128
RUTA_CARA = "/api/servicio/personas/cara"
RUTA_NUEVA = "/api/servicio/personas/nueva"
RUTA_EDITAR = "/api/servicio/personas/editar"
RUTA_CREDITO = "/api/servicio/personas/credito"
RUTA_IDENTIDAD = "/api/servicio/personas/identidad"


def _esc(ruta, cuerpo=None, valor="escritura", crudo=None):
    paso = {"ruta": ruta, "cabecera": RUTA_ESCRITURA_CABECERA, "valor": valor}
    if crudo is not None:
        paso["crudo"] = crudo
    else:
        paso["cuerpo"] = cuerpo
    return paso


def _lectura(ruta, cabecera, cuerpo, valor):
    return {"ruta": ruta, "cabecera": cabecera, "valor": valor, "cuerpo": cuerpo}


CARA_OK = {"persona_id": 1, "vec": VEC}
NUEVA_OK = {"nombre": "  Nueva Uno  ", "telefono": "8095550101", "email": "nueva.uno@ejemplo.test", "notas": "nota de prueba",
            "instrumento": ["Guitarra", "Bajo"], "cumpleanos": "14/03"}
EDITAR_OK = {"persona_id": 2, "datos": {"nombre": "Persona Dos Editada", "notas": "nota de prueba"}}

ESCENARIOS = [
    {"nombre": "cara_rotacion", "pasos": [
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [0.5] * 128}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [0.25] * 128}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [0.75] * 128}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [0.125] * 128}),
        _esc(RUTA_CARA, {"persona_id": 2, "vec": [0.5] * 128}),
    ]},
    {"nombre": "cara_pedidos_malos", "pasos": [
        _esc(RUTA_CARA, {"persona_id": "1", "vec": VEC}),
        _esc(RUTA_CARA, {"persona_id": 0, "vec": VEC}),
        _esc(RUTA_CARA, {"persona_id": True, "vec": VEC}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [0.5] * 127}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": [True] + [0.5] * 127}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": "no es lista"}),
        _esc(RUTA_CARA, {"persona_id": 1, "vec": VEC, "extra": 1}),
        _esc(RUTA_CARA, crudo="no es json"),
        _esc(RUTA_CARA, {"persona_id": 4, "vec": VEC}),
        _esc(RUTA_CARA, {"persona_id": 3, "vec": VEC}),
        _esc(RUTA_CARA, {"persona_id": 99, "vec": VEC}),
    ]},
    {"nombre": "cara_lectura_caida", "caidas": ["GET"], "pasos": [
        _esc(RUTA_CARA, CARA_OK),
    ]},
    {"nombre": "cara_escritura_caida", "caidas": ["PATCH"], "pasos": [
        _esc(RUTA_CARA, CARA_OK),
    ]},
    {"nombre": "nueva_ok", "pasos": [
        _esc(RUTA_NUEVA, NUEVA_OK),
        _esc(RUTA_NUEVA, {"nombre": "Nueva Dos", "telefono": ""}),
    ]},
    {"nombre": "nueva_errores", "pasos": [
        _esc(RUTA_NUEVA, {}),
        _esc(RUTA_NUEVA, {"nombre": 5}),
        _esc(RUTA_NUEVA, {"nombre": "   "}),
        _esc(RUTA_NUEVA, [1, 2]),
        _esc(RUTA_NUEVA, {"nombre": "Con fecha", "cumpleanos": "1/1"}),
        _esc(RUTA_NUEVA, {"nombre": "Repetida", "telefono": "18097770001"}),
        _esc(RUTA_NUEVA, crudo="{"),
    ]},
    {"nombre": "nueva_lectura_caida", "caidas": ["GET"], "pasos": [
        _esc(RUTA_NUEVA, NUEVA_OK),
    ]},
    {"nombre": "nueva_escritura_caida", "caidas": ["POST"], "pasos": [
        _esc(RUTA_NUEVA, NUEVA_OK),
    ]},
    {"nombre": "editar_ok", "pasos": [
        _esc(RUTA_EDITAR, EDITAR_OK),
        _esc(RUTA_EDITAR, {"persona_id": 2, "datos": {"telefono": "8097770009"}}),
        _esc(RUTA_EDITAR, {"persona_id": 1, "datos": {}}),
    ]},
    {"nombre": "editar_errores", "pasos": [
        _esc(RUTA_EDITAR, {"persona_id": 0, "datos": {"nombre": "x"}}),
        _esc(RUTA_EDITAR, {"persona_id": "2", "datos": {"nombre": "x"}}),
        _esc(RUTA_EDITAR, {"persona_id": 2, "datos": "x"}),
        _esc(RUTA_EDITAR, {"persona_id": 2, "datos": {"nombre": "x"}, "extra": 1}),
        _esc(RUTA_EDITAR, {"persona_id": 2, "datos": {"nombre": "  "}}),
        _esc(RUTA_EDITAR, {"persona_id": 1, "datos": {"telefono": "18097770002"}}),
        _esc(RUTA_EDITAR, {"persona_id": 99, "datos": {"nombre": "x"}}),
        _esc(RUTA_EDITAR, crudo="x"),
    ]},
    {"nombre": "editar_lectura_caida", "caidas": ["GET"], "pasos": [
        _esc(RUTA_EDITAR, EDITAR_OK),
    ]},
    {"nombre": "llave_escrituras_por_ruta", "pasos": [
        paso
        for ruta, cuerpo in ((RUTA_CARA, CARA_OK), (RUTA_NUEVA, NUEVA_OK), (RUTA_EDITAR, EDITAR_OK))
        for paso in (_esc(ruta, cuerpo, valor="ausente"), _esc(ruta, cuerpo, valor="vacia"),
                     _esc(ruta, cuerpo, valor="lectura_mercadeo"), _esc(ruta, cuerpo, valor="lectura_registro"),
                     _esc(ruta, cuerpo, valor="mala"))
    ] + [_esc(RUTA_CARA, CARA_OK)]},
    {"nombre": "llave_variable_escritura_vacia", "entorno": {"PERSONAS_REGISTRO_ESCRITURA_LLAVE": ""}, "pasos": [
        _esc(RUTA_CARA, CARA_OK), _esc(RUTA_NUEVA, NUEVA_OK), _esc(RUTA_EDITAR, EDITAR_OK),
        _esc(RUTA_CARA, CARA_OK, valor="vacia"),
    ]},
    {"nombre": "lectura_con_llave_de_escritura", "pasos": [
        _lectura(RUTA_CREDITO, RUTA_LECTURA_REGISTRO_CABECERA, {"telefono": "18097770001"}, "escritura"),
        _lectura(RUTA_IDENTIDAD, RUTA_LECTURA_MERCADEO_CABECERA, {"identidad": "18097770001"}, "escritura"),
        _lectura(RUTA_CREDITO, RUTA_LECTURA_REGISTRO_CABECERA, {"telefono": "18097770001"}, "lectura_registro"),
    ]},
]


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _valor(simbolo):
    if simbolo in VALORES:
        return VALORES[simbolo]
    if simbolo == "vacia":
        return ""
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def _pedir(puerto, paso):
    if "crudo" in paso:
        datos = paso["crudo"].encode("utf-8")
    else:
        datos = json.dumps(paso["cuerpo"]).encode("utf-8")
    cabeceras = {"Content-Type": "application/json"}
    if paso["valor"] != "ausente":
        cabeceras[paso["cabecera"]] = _valor(paso["valor"])
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, paso["ruta"]), data=datos, method="POST", headers=cabeceras)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            codigo, bruto = r.status, r.read()
    except urllib.error.HTTPError as e:
        codigo, bruto = e.code, e.read()
    try:
        cuerpo = json.loads(bruto.decode("utf-8"))
    except ValueError:
        cuerpo = {"__no_json__": bruto.decode("utf-8", "replace")}
    return codigo, cuerpo


def _esperar_arriba(puerto, proceso):
    """Espera a que el servidor conteste. `config` sin llave da 401 y no lee NocoDB: contestar con cualquier código es estar arriba."""
    for _ in range(100):
        if proceso.poll() is not None:
            raise RuntimeError("el servidor se cerró al arrancar (código %s)" % proceso.returncode)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/servicio/personas/config" % puerto, timeout=5).close()
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("el servidor no levantó")


def ejecutar(escenario, comando, cwd, entorno_base=None):
    """Corre los pasos de un escenario contra `comando` (un servidor que escucha en PORT, con NOCODB_BASE puesto al doble).
    Devuelve (pasos, errores_del_doble). Cada paso dice código, respuesta y los pedidos que llegaron al doble en ese paso.
    El proceso y el doble se cierran al terminar, pase lo que pase."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()))
    url_doble = doble.arrancar()
    puerto = _puerto_libre()
    entorno = dict(ENTORNO_MINIMO)
    entorno.update(ENTORNO_BASE if entorno_base is None else entorno_base)
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(escenario.get("entorno", {}))
    with tempfile.TemporaryFile() as errores_de_arranque:
        proceso = subprocess.Popen(comando, cwd=cwd, env=entorno, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errores_de_arranque)
        try:
            _esperar_arriba(puerto, proceso)
            doble.pedidos.clear()
            pasos = []
            for paso in escenario["pasos"]:
                antes = len(doble.pedidos)
                codigo, cuerpo = _pedir(puerto, paso)
                registro = {"ruta": paso["ruta"], "cabecera": paso.get("cabecera"), "valor": paso.get("valor"),
                            "status": codigo, "respuesta": cuerpo, "pedidos": doble.pedidos[antes:]}
                if "crudo" in paso:
                    registro["crudo"] = paso["crudo"]
                elif "cuerpo" in paso:
                    registro["cuerpo"] = paso["cuerpo"]
                pasos.append(registro)
            return pasos, list(doble.errores)
        finally:
            proceso.terminate()
            proceso.wait(timeout=10)
            doble.parar()
