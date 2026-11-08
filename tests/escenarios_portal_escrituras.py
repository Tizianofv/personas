# -*- coding: utf-8 -*-
"""Los escenarios de las ESCRITURAS del portal (paso 5c, parte 3): crear, editar, anotar permiso, resolver y reabrir. Los usan DOS cosas:
  · `tools/generar_portal_escrituras_de_la_app.py`: corre la App de registro (`594ec12`, copia `git archive`) con su
    `Handler.portal_personas` contra el doble, y guarda lo que contesta y lo que el doble recibe (`contrato_dorado/portal_escrituras.json`);
  · `tests/test_portal_escrituras.py`: corre `servidor.py` del repo contra el mismo doble y compara paso a paso con esa foto.

Cada escenario arranca un proceso nuevo (App o repo) y un doble nuevo, y corre sus pasos en orden. Un paso es un pedido POST con
cabeceras del portal. Los valores de llave se nombran con un SÍMBOLO (`portal`, `escritura`, `lectura_mercadeo`, `lectura_registro`,
`vacia`, `mala`, `ausente`); los valores reales están en `VALORES` y no se guardan en ningún registro.

Campos de un paso:
  ruta, cuerpo (objeto) o crudo (texto que se manda tal cual),
  llave (símbolo; por defecto `portal`, `None` = sin cabecera),
  quien (texto; `None` = sin cabecera; el texto va como UTF-8 en la cabecera),
  tipo (texto; por defecto `A`; `None` = sin cabecera).
Los pasos del DORADO son los que tienen llave `portal`, `quien` no vacío y tipo `A`: la App no tiene identidad (la pone el
programa), así que solo esos pasos se comparan con la App. Lo que no es dorado (llaves, identidad) se prueba en `test_portal_escrituras.py`.

Lo que se apunta de cada paso: el código, el cuerpo de la respuesta y los pedidos que llegaron al doble durante el paso
(método, ruta, query y cuerpo; nunca las cabeceras).
"""
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import doble_escrituras
import doble_nocodb

RUTA_PORTAL = "/api/portal-personas"
CABECERA_LLAVE = "X-Personas-Portal-Llave"
CABECERA_QUIEN = "X-Personas-Portal-Quien"
CABECERA_TIPO = "X-Personas-Portal-Tipo"

# Valores de PRUEBA (no son secretos). Solo los usa el harness, nunca un registro.
VALORES = {
    "portal": "llave-de-prueba-portal-personas",
    "escritura": "llave-de-prueba-escritura-registro-personas",
    "lectura_mercadeo": "llave-de-prueba-lectura-mercadeo-personas",
    "lectura_registro": "llave-de-prueba-lectura-registro-personas",
}
QUIEN_DORADO = "Ana Pérez"       # con tilde: la prueba de la cabecera UTF-8 (lo que la App pone, sin codificar)

# Entorno de los dos lados. Las tablas de NocoDB las dan las constantes del doble (las mismas que usan las lecturas del portal).
ENTORNO_BASE = {
    "PERSONAS_PORTAL_LLAVE": VALORES["portal"],
    "PERSONAS_REGISTRO_ESCRITURA_LLAVE": VALORES["escritura"],
    "PERSONAS_LECTURA_LLAVE": VALORES["lectura_mercadeo"],
    "PERSONAS_REGISTRO_LLAVE": VALORES["lectura_registro"],
    "NOCODB_T_PERSONAS_ANOTACIONES": doble_nocodb.TABLA_ANOTACIONES,
    "NOCODB_T_PERSONAS_QUITADAS": doble_nocodb.T_QUITADAS,
    "NOCODB_T_BANDEJA_PERSONAS": doble_nocodb.T_BANDEJA,
}
ENTORNO_MINIMO = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}


def _p(ruta, cuerpo=None, crudo=None, llave="portal", quien=QUIEN_DORADO, tipo="A", nombre=None):
    paso = {"ruta": ruta, "llave": llave, "quien": quien, "tipo": tipo}
    if crudo is not None:
        paso["crudo"] = crudo
    else:
        paso["cuerpo"] = cuerpo
    if nombre is not None:
        paso["nombre"] = nombre
    return paso


CREAR = {"cambios": {"nombre": "Portal Uno", "telefono": "8095550201", "email": "portal.uno@ejemplo.test", "instagram": "portal_uno"}}
# «base» es lo que la ficha decía al abrirla (la App lo compara antes de escribir): aquí, la persona 2 tal como está en el doble.
EDITAR = {"id": 2, "base": {"nombre": "Persona de prueba 2", "instagram": ""},
          "cambios": {"nombre": "Persona Dos Editada", "instagram": "persona_dos"}}
PERMISO = {"valor": "no", "visto": 2}           # el último renglón de permiso de la persona 2 es el Id 2 del doble
CLAVE_RESUELTO = "resuelto-" + "a" * 40          # formato válido; no es ningún renglón de «Por resolver» del doble
CLAVE_AVISO = "aviso-" + "b" * 40                # formato válido de aviso; no existe en el doble
RUTA_EDITAR = RUTA_PORTAL + "/2/editar"
RUTA_PERMISO = RUTA_PORTAL + "/2/permiso"
RUTA_RESOLVER = RUTA_PORTAL + "/por-resolver/resolver"
RUTA_REABRIR = RUTA_PORTAL + "/por-resolver/reabrir"

ESCENARIOS = [
    {"nombre": "crear_ok", "pasos": [
        _p(RUTA_PORTAL, CREAR),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Dos"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Tres", "telefono": "8095550203"}, "clave_envio": "envio-crear-1"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Portal Tres", "telefono": "8095550203"}, "clave_envio": "envio-crear-1"}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Otro cuerpo"}, "clave_envio": "envio-crear-1"}),
    ]},
    {"nombre": "crear_errores", "pasos": [
        _p(RUTA_PORTAL, {"cambios": {"nombre": "x", "caras": "no"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": 5}}),
        _p(RUTA_PORTAL, {"cambios": {"telefono": "8095550202"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Con telefono corto", "telefono": "12"}}),
        _p(RUTA_PORTAL, {"cambios": {"nombre": "Repetido", "telefono": "18097770001"}}),
        _p(RUTA_PORTAL, {"sin_cambios": True}),
        _p(RUTA_PORTAL, [1, 2]),
        _p(RUTA_PORTAL, crudo="{"),
        _p(RUTA_PORTAL, crudo=""),
    ]},
    {"nombre": "crear_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_PORTAL, CREAR)]},
    {"nombre": "crear_escritura_caida", "caidas": ["POST"], "pasos": [_p(RUTA_PORTAL, CREAR)]},
    {"nombre": "editar_ok", "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-1")),
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-1")),
        _p(RUTA_EDITAR, EDITAR),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"instagram": "persona_dos"}, "cambios": {"instagram": "persona_tres"}}),
        _p(RUTA_PORTAL + "/1/editar", {"id": 1, "base": {}, "cambios": {}}),
    ]},
    {"nombre": "editar_errores", "pasos": [
        _p(RUTA_PORTAL + "/2/editar", {"id": 3, "cambios": {"nombre": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "cambios": "x"}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "cambios": {"caras": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"nombre": "Persona de prueba 2"}, "cambios": {"nombre": 7}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "base": {"telefono": "18097770002"}, "cambios": {"telefono": "18097770001"}}),
        _p(RUTA_PORTAL + "/99/editar", {"id": 99, "base": {"nombre": "x"}, "cambios": {"nombre": "x"}}),
        _p(RUTA_PORTAL + "/2/editar", crudo="x"),
        _p(RUTA_PORTAL + "/2/editar", crudo=""),
    ]},
    {"nombre": "editar_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_EDITAR, EDITAR)]},
    {"nombre": "editar_escritura_caida", "caidas": ["PATCH"], "pasos": [_p(RUTA_EDITAR, EDITAR)]},
    {"nombre": "permiso_ok", "pasos": [
        _p(RUTA_PERMISO, PERMISO),
        _p(RUTA_PERMISO, {"valor": "si", "visto": 2}),
        _p(RUTA_PERMISO, {"valor": "si", "visto": 3}),
    ]},
    {"nombre": "permiso_errores", "pasos": [
        _p(RUTA_PERMISO, {"valor": "tal vez", "visto": 2}),
        _p(RUTA_PERMISO, {"valor": "no"}),
        _p(RUTA_PERMISO, {"valor": "no", "visto": 2, "quien": "Otra Persona"}),
        _p(RUTA_PERMISO, {"valor": "no", "visto": 2, "canal": "carta"}),
        _p(RUTA_PORTAL + "/99/permiso", {"valor": "no", "visto": None}),
        _p(RUTA_PERMISO, crudo="{"),
        _p(RUTA_PERMISO, {}),
    ]},
    {"nombre": "permiso_lectura_caida", "caidas": ["GET"], "pasos": [_p(RUTA_PERMISO, PERMISO)]},
    {"nombre": "permiso_escritura_caida", "caidas": ["POST"], "pasos": [_p(RUTA_PERMISO, PERMISO)]},
    {"nombre": "resolver_errores", "pasos": [
        _p(RUTA_RESOLVER, {}),
        _p(RUTA_RESOLVER, {"clave": "x"}),
        _p(RUTA_RESOLVER, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_RESOLVER, {"clave": CLAVE_AVISO}),
        _p(RUTA_REABRIR, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_REABRIR, {"clave": "x"}),
        _p(RUTA_RESOLVER, crudo="{"),
    ]},
    {"nombre": "resolver_bandeja_caida", "caidas": ["GET"], "pasos": [
        _p(RUTA_RESOLVER, {"clave": CLAVE_RESUELTO}),
        _p(RUTA_REABRIR, {"clave": CLAVE_RESUELTO}),
    ]},
    # Un fallo de escritura NO se recuerda como guardado: el segundo envío con la MISMA clave tiene que volver a escribir.
    {"nombre": "editar_reintento_tras_fallo", "caidas_una_vez": ["PATCH"], "pasos": [
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-fallo")),
        _p(RUTA_EDITAR, dict(EDITAR, clave_envio="envio-editar-fallo")),
    ]},
    {"nombre": "crear_reintento_tras_fallo", "caidas_una_vez": ["POST"], "pasos": [
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-crear-fallo")),
        _p(RUTA_PORTAL, dict(CREAR, clave_envio="envio-crear-fallo")),
    ]},
    {"nombre": "quien_del_cuerpo_no_cuenta", "pasos": [
        _p(RUTA_PORTAL, {"quien": "Otra Persona", "cambios": {"nombre": "Quien Cuerpo"}}),
        _p(RUTA_PORTAL + "/2/editar", {"id": 2, "quien": "Otra Persona", "base": {"nombre": "Persona de prueba 2"},
                                       "cambios": {"nombre": "Quien Cuerpo Dos"}}),
    ]},
]

# Pasos que la App no contesta igual (no tiene identidad): ver `es_dorado`.


def es_dorado(paso):
    """¿Este paso se compara con la App? Solo con llave del portal, identidad (quien no vacío) y tipo «A»."""
    return paso.get("llave") == "portal" and bool(paso.get("quien")) and paso.get("tipo") == "A"


AHORA = "<ahora>"


def normalizar(valor):
    """Quita de un registro lo que depende de la hora de la corrida: el valor de cualquier clave `cuando` que sea una fecha ISO se
    cambia por «<ahora>». Lo aplican la foto y la prueba, a los dos lados, así que la comparación no ve la hora. Lo que sí se comprueba
    (en `test_portal_escrituras.py`) es que ese valor sea una fecha ISO con zona y no otra cosa."""
    if isinstance(valor, dict):
        return {k: (AHORA if k == "cuando" and _es_iso(v) else normalizar(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [normalizar(v) for v in valor]
    return valor


def _es_iso(v):
    from datetime import datetime
    if not isinstance(v, str):
        return False
    try:
        return datetime.fromisoformat(v) is not None and ("+" in v or "Z" in v)
    except ValueError:
        return False


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _valor_llave(simbolo):
    if simbolo in VALORES:
        return VALORES[simbolo]
    if simbolo == "vacia":
        return ""
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def cabeceras_del_paso(paso):
    """Las cabeceras que manda un paso (sin `Content-Length`, que pone `urllib`). El `quien` va como UTF-8 en bytes: se pasa como
    texto «latin-1» porque `http.client` solo escribe latin-1; así la cabecera llega con los bytes UTF-8 de `quien`."""
    cabeceras = {"Content-Type": "application/json"}
    if paso.get("llave") is not None:
        cabeceras[CABECERA_LLAVE] = _valor_llave(paso["llave"])
    if paso.get("quien") is not None:
        cabeceras[CABECERA_QUIEN] = paso["quien"].encode("utf-8").decode("latin-1")
    if paso.get("tipo") is not None:
        cabeceras[CABECERA_TIPO] = paso["tipo"]
    return cabeceras


def datos_del_paso(paso):
    if "crudo" in paso:
        return paso["crudo"].encode("utf-8")
    return json.dumps(paso["cuerpo"]).encode("utf-8")


def _pedir(puerto, paso):
    datos = datos_del_paso(paso)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, paso["ruta"]), data=datos, method="POST",
                                 headers=cabeceras_del_paso(paso))
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


def ejecutar(escenario, comando, cwd, entorno_extra=None):
    """Corre los pasos de un escenario contra `comando` (un servidor en PORT, con NOCODB_BASE puesto al doble). Devuelve
    (pasos, errores_del_doble). Cada paso dice código, respuesta y los pedidos que llegaron al doble en ese paso. El proceso y el doble
    se cierran al terminar, pase lo que pase."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()), caidas_una_vez=escenario.get("caidas_una_vez", ()))
    url_doble = doble.arrancar()
    puerto = _puerto_libre()
    entorno = dict(ENTORNO_MINIMO)
    entorno.update(ENTORNO_BASE)
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(escenario.get("entorno", {}))
    entorno.update(entorno_extra or {})
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
                registro = {"ruta": paso["ruta"], "status": codigo, "respuesta": cuerpo, "pedidos": doble.pedidos[antes:]}
                if "crudo" in paso:
                    registro["crudo"] = paso["crudo"]
                else:
                    registro["cuerpo"] = paso["cuerpo"]
                pasos.append(registro)
            return pasos, list(doble.errores)
        finally:
            proceso.terminate()
            proceso.wait(timeout=10)
            doble.parar()
