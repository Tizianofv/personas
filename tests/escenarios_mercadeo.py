# -*- coding: utf-8 -*-
"""Los escenarios de MERCADEO hacia PERSONAS (P7): la baja y la foto. Los usan DOS cosas:
  · `tools/generar_mercadeo_de_la_app.py`: corre la App de registro (`8c9d21a`, copia `git archive`) con sus `Handler.mercadeo_baja` y
    `Handler.mercadeo_foto` contra el doble, y guarda lo que contesta y lo que el doble recibe (`contrato_dorado/mercadeo.json`);
  · `tests/test_mercadeo_servicio.py`: corre `servidor.py` del repo contra el mismo doble y compara paso a paso con esa foto.

Cada escenario arranca un proceso nuevo (App o repo) y un doble nuevo, y corre sus pasos en orden.
Un paso es un POST a una de las dos rutas. Se nombra con un símbolo, no con la ruta: `@baja` y `@foto` (la ruta de cada lado va en
`RUTAS`). Así la foto guarda el mismo nombre para los dos lados.

Llaves. Cada lado mira SU cabecera: la App `X-Mercadeo-Llave` (`MERCADEO_LLAVE_SERVICIO`), el programa `X-Personas-Mercadeo-Llave`
(`PERSONAS_MERCADEO_LLAVE`). El valor del paso es un símbolo: `mercadeo` (la buena), `mala`, `vacia` (cabecera con texto vacío), `entrada`
(la llave de OTRO grupo: `PERSONAS_ENTRADA_LLAVE` en el programa), o `None` (sin cabecera). Solo el símbolo `mercadeo` es dorado.

Campos de un paso: ruta (`@baja` o `@foto`), cuerpo (objeto) o crudo (texto que se manda tal cual), llave (símbolo, por defecto `mercadeo`).
Lo que se apunta de cada paso: código, cuerpo de la respuesta y los pedidos que llegaron al doble durante el paso (método, ruta, query, cuerpo).

El día de hoy se fija (`tests/reloj.py`): `dicho_el` igual al día fijado se normaliza a «<hoy>» en la foto y en la comparación.
"""
import json
import subprocess
import tempfile

import doble_escrituras
import escenarios_portal_escrituras as esc  # `_puerto_libre`, `_esperar_arriba`, `ENTORNO_BASE`, `ENTORNO_MINIMO`, `normalizar` (los mismos del portal)
import reloj

# Valores de PRUEBA (no son secretos). Solo los usa el arnés, nunca un registro.
VALORES = {
    "mercadeo": "llave-de-prueba-mercadeo-personas",
    "entrada": "llave-de-prueba-entrada-personas",
}
CABECERA = {"app": "X-Mercadeo-Llave", "programa": "X-Personas-Mercadeo-Llave"}
RUTAS = {
    "app": {"@baja": "/api/servicio/mercadeo/baja", "@foto": "/api/servicio/mercadeo/foto"},
    "programa": {"@baja": "/api/servicio/personas/mercadeo/baja", "@foto": "/api/servicio/personas/mercadeo/foto"},
}
# Las variables de llave de cada lado (solo nombres de variable; los valores son de prueba).
LLAVES_DEL_LADO = {
    "app": {"MERCADEO_LLAVE_SERVICIO": VALORES["mercadeo"]},
    "programa": {"PERSONAS_MERCADEO_LLAVE": VALORES["mercadeo"], "PERSONAS_ENTRADA_LLAVE": VALORES["entrada"]},
}
DIA = reloj.DIA_FIJO

# Identidades del doble: «18097770002» es la ficha 2 (una sola); «18097770001» son las fichas 1 y 4 (un grupo); «18090009999» no existe.
IDENTIDAD_UNA = "18097770002"
IDENTIDAD_GRUPO = "18097770001"
IDENTIDAD_NINGUNA = "18090009999"

BAJA_OK = {"identidad": IDENTIDAD_UNA, "dicho_el": DIA, "clave": "baja-prueba-0001"}
FOTO_NO = {"identidad": IDENTIDAD_UNA, "valor": "no"}
FOTO_SI = {"identidad": IDENTIDAD_UNA, "valor": "si"}


def _b(cuerpo=None, crudo=None, llave="mercadeo"):
    return _paso("@baja", cuerpo, crudo, llave)


def _f(cuerpo=None, crudo=None, llave="mercadeo"):
    return _paso("@foto", cuerpo, crudo, llave)


def _paso(ruta, cuerpo, crudo, llave):
    paso = {"ruta": ruta, "llave": llave}
    if crudo is not None:
        paso["crudo"] = crudo
    else:
        paso["cuerpo"] = cuerpo
    return paso


# DORADOS: todos llevan la llave buena, así que la App y el programa deben contestar lo mismo.
ESCENARIOS = [
    {"nombre": "baja_ok", "pasos": [_b(BAJA_OK), _b(BAJA_OK)]},
    {"nombre": "baja_grupo", "pasos": [_b({"identidad": IDENTIDAD_GRUPO, "dicho_el": DIA, "clave": "baja-prueba-grupo"})]},
    {"nombre": "baja_sin_ficha", "pasos": [_b(dict(BAJA_OK, identidad=IDENTIDAD_NINGUNA))]},
    {"nombre": "baja_errores", "pasos": [
        _b({}),
        _b(dict(BAJA_OK, identidad="")),
        _b(dict(BAJA_OK, clave="")),
        _b(dict(BAJA_OK, clave="x" * 201)),
        _b(dict(BAJA_OK, dicho_el="2026-13-45")),
        _b(dict(BAJA_OK, extra=1)),
        _b(dict(BAJA_OK, identidad=7)),
        _b(crudo="{"),
    ]},
    {"nombre": "baja_sin_tabla", "entorno": {"NOCODB_T_PERSONAS_ANOTACIONES": ""}, "pasos": [_b(BAJA_OK)]},
    {"nombre": "baja_lectura_caida", "caidas": ["GET"], "pasos": [_b(BAJA_OK)]},
    {"nombre": "baja_escritura_caida", "caidas": ["POST"], "pasos": [_b(BAJA_OK)]},
    # Un fallo no se recuerda como anotado: el reintento (mismo pedido) vuelve a escribir.
    {"nombre": "baja_reintento_tras_fallo", "caidas_una_vez": ["POST"], "pasos": [_b(BAJA_OK), _b(BAJA_OK)]},
    {"nombre": "foto_ok", "pasos": [_f(FOTO_NO), _f(FOTO_NO), _f(FOTO_SI)]},
    {"nombre": "foto_grupo", "pasos": [_f({"identidad": IDENTIDAD_GRUPO, "valor": "no"})]},
    {"nombre": "foto_sin_ficha", "pasos": [_f(dict(FOTO_NO, identidad=IDENTIDAD_NINGUNA))]},
    {"nombre": "foto_errores", "pasos": [
        _f(dict(FOTO_NO, valor="tal vez")),
        _f({"identidad": IDENTIDAD_UNA}),
        _f({"valor": "no"}),
        _f(dict(FOTO_NO, quien="Otro")),
        _f(dict(FOTO_NO, identidad="")),
        _f(dict(FOTO_NO, identidad=5)),
        _f(crudo="{"),
    ]},
    {"nombre": "foto_sin_tabla", "entorno": {"NOCODB_T_PERSONAS_ANOTACIONES": ""}, "pasos": [_f(FOTO_NO)]},
    {"nombre": "foto_lectura_caida", "caidas": ["GET"], "pasos": [_f(FOTO_NO)]},
    {"nombre": "foto_escritura_caida", "caidas": ["POST"], "pasos": [_f(FOTO_NO)]},
    {"nombre": "foto_reintento_tras_fallo", "caidas_una_vez": ["POST"], "pasos": [_f(FOTO_NO), _f(FOTO_NO)]},
]

# GUARDA (solo el programa): llave ausente, mala, vacía, la de otro grupo, o la variable vacía. Cada paso tiene que dar 401 y NO llegar
# a NocoDB. Un cuerpo roto con la llave mala también da 401 (la llave va antes que el cuerpo).
GUARDA = [
    {"nombre": "llave_ausente", "pasos": [_b(BAJA_OK, llave=None), _f(FOTO_NO, llave=None)]},
    {"nombre": "llave_mala", "pasos": [_b(BAJA_OK, llave="mala"), _f(FOTO_NO, llave="mala")]},
    {"nombre": "llave_vacia", "pasos": [_b(BAJA_OK, llave="vacia"), _f(FOTO_NO, llave="vacia")]},
    {"nombre": "llave_de_la_entrada", "pasos": [_b(BAJA_OK, llave="entrada"), _f(FOTO_NO, llave="entrada")]},
    {"nombre": "llave_mala_cuerpo_roto", "pasos": [_b(crudo="{", llave="mala"), _f(crudo="{", llave="mala")]},
    {"nombre": "variable_vacia_con_cabecera_vacia", "entorno": {"PERSONAS_MERCADEO_LLAVE": ""},
     "pasos": [_b(BAJA_OK, llave="vacia"), _f(FOTO_NO, llave="vacia")]},
]


def valor_llave(simbolo):
    if simbolo in VALORES:
        return VALORES[simbolo]
    if simbolo == "vacia":
        return ""
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def cabeceras_del_paso(lado, paso):
    cabeceras = {"Content-Type": "application/json"}
    if paso.get("llave") is not None:
        cabeceras[CABECERA[lado]] = valor_llave(paso["llave"])
    return cabeceras


def datos_del_paso(paso):
    if "crudo" in paso:
        return paso["crudo"].encode("utf-8")
    return json.dumps(paso["cuerpo"]).encode("utf-8")


def _pedir(puerto, lado, paso):
    import urllib.error
    import urllib.request
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, RUTAS[lado][paso["ruta"]]), data=datos_del_paso(paso),
                                 method="POST", headers=cabeceras_del_paso(lado, paso))
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


def ejecutar(escenario, lado, comando, cwd):
    """Corre los pasos de un escenario contra `comando` (el servidor de `lado`, en PORT, con NOCODB_BASE puesto al doble). Devuelve
    `(pasos, errores_del_doble)`. Cada paso dice código, respuesta y los pedidos que llegaron al doble en ese paso. El proceso y el doble
    se cierran al terminar, pase lo que pase."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()), caidas_una_vez=escenario.get("caidas_una_vez", ()),
                                             union=False)
    url_doble = doble.arrancar()
    puerto = esc._puerto_libre()
    entorno = dict(esc.ENTORNO_MINIMO)
    entorno.update(esc.ENTORNO_BASE)
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(LLAVES_DEL_LADO[lado])
    entorno.update(escenario.get("entorno", {}))
    with tempfile.TemporaryFile() as errores_de_arranque:
        proceso = subprocess.Popen(comando, cwd=cwd, env=entorno, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errores_de_arranque)
        try:
            esc._esperar_arriba(puerto, proceso)
            doble.pedidos.clear()
            pasos = []
            for paso in escenario["pasos"]:
                antes = len(doble.pedidos)
                codigo, cuerpo = _pedir(puerto, lado, paso)
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
