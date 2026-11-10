# -*- coding: utf-8 -*-
"""Los escenarios de la MEMORIA DE NATALIA hacia Personas (P8a-1): `POST /api/servicio/personas/memoria`. Los usan DOS cosas:
  · `tools/generar_memoria_de_la_app.py`: corre la App de registro (`142d45f`, copia `git archive`) con su `editar` del portal (la
    misma puerta, `editar_persona_portal`) contra el doble, con los pedidos de `DORADOS`, y guarda lo que contesta
    (`contrato_dorado/memoria.json`);
  · `tests/test_memoria_natalia.py`: corre `servidor.py` del repo contra el mismo doble y compara paso a paso con esa foto. Los
    escenarios que la App no contesta igual (llave, identidad, campos fuera de la lista) son de la prueba, no de la foto.

Llave: cabecera `X-Personas-Natalia-Llave` (`PERSONAS_NATALIA_LLAVE`). Símbolos: `natalia` (la buena), `mala`, `vacia` (cabecera con texto
vacío), `portal` (la llave de OTRO grupo), o `None` (sin cabecera). Identidad: cabecera `X-Personas-Natalia-Quien`; `None` = sin cabecera.
Solo los pasos con llave `natalia` y identidad `QUIEN` son dorados (se usan en la foto y en la App).
"""
import json
import subprocess
import tempfile
import urllib.error
import urllib.request

import doble_escrituras
import escenarios_portal_escrituras as esc  # `_puerto_libre`, `_esperar_arriba`, `ENTORNO_BASE`, `ENTORNO_MINIMO`, `VALORES`, `normalizar`
import reloj

RUTA = "/api/servicio/personas/memoria"
RUTA_APP = "/api/portal-personas/%d/editar"          # el `editar` del portal de la App, con el `id` del cuerpo
CABECERA_LLAVE = "X-Personas-Natalia-Llave"
CABECERA_QUIEN = "X-Personas-Natalia-Quien"
VALORES_NATALIA = {"natalia": "llave-de-prueba-natalia-personas"}   # valor de PRUEBA: solo lo usa el harness
QUIEN = "Natalia"
ENTORNO_NATALIA = {"PERSONAS_NATALIA_LLAVE": VALORES_NATALIA["natalia"]}


# Las 12 columnas de la memoria que el doble no tenía (las demás, como `instagram`, ya están en sus filas). El TIPO de cada una es un
# supuesto del doble (no medido en la base real): texto, lista de opciones para `instrumento` y `genero`. Lo que decide la App con
# ese tipo (`_forma_de_columna`) es lo que se compara, no el tipo real de la base.
_OPCIONES_INSTRUMENTO = [{"title": "Guitarra"}, {"title": "Productor"}, {"title": "DJ"}]
_OPCIONES_GENERO = [{"title": "Mujer"}, {"title": "Hombre"}]
COLUMNAS_MEMORIA = [
    {"title": "instrumento", "uidt": "MultiSelect", "system": False, "colOptions": {"options": _OPCIONES_INSTRUMENTO}},
    {"title": "genero", "uidt": "MultiSelect", "system": False, "colOptions": {"options": _OPCIONES_GENERO}},
    {"title": "Cumpleanos", "uidt": "SingleLineText", "system": False},
    {"title": "Tono", "uidt": "SingleLineText", "system": False},
    {"title": "Clave", "uidt": "SingleLineText", "system": False},
    {"title": "Preferencias_operativas", "uidt": "LongText", "system": False},
    {"title": "Comportamiento_reserva", "uidt": "LongText", "system": False},
    {"title": "Sensibilidad_precio", "uidt": "SingleLineText", "system": False},
    {"title": "Riesgo_noshow", "uidt": "SingleLineText", "system": False},
    {"title": "Resumen", "uidt": "LongText", "system": False},
    {"title": "notas", "uidt": "LongText", "system": False},
    {"title": "instagram", "uidt": "SingleLineText", "system": False},
]


def _valor_llave(simbolo):
    if simbolo == "natalia":
        return VALORES_NATALIA["natalia"]
    if simbolo == "portal":
        return esc.VALORES["portal"]
    if simbolo == "vacia":
        return ""
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def _paso(cuerpo=None, crudo=None, llave="natalia", quien=QUIEN):
    paso = {"llave": llave, "quien": quien}
    if crudo is not None:
        paso["crudo"] = crudo
    else:
        paso["cuerpo"] = cuerpo
    return paso


def cabeceras_del_paso(paso):
    """Las cabeceras del paso (sin `Content-Length`). La identidad va como UTF-8 en latin-1, igual que el portal (`esc.cabeceras_del_paso`)."""
    cabeceras = {"Content-Type": "application/json"}
    if paso.get("llave") is not None:
        cabeceras[CABECERA_LLAVE] = _valor_llave(paso["llave"])
    if paso.get("quien") is not None:
        cabeceras[CABECERA_QUIEN] = paso["quien"].encode("utf-8").decode("latin-1")
    return cabeceras


def _pedir(puerto, paso):
    datos = esc.datos_del_paso(paso)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, RUTA), data=datos, method="POST", headers=cabeceras_del_paso(paso))
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


def ejecutar(escenario, cwd):
    """Corre los pasos contra `servidor.py` del repo (`reloj.comando_programa`, con el día fijado) y el doble. Devuelve
    `(pasos, errores_del_doble)`. Cada paso lleva código, respuesta y los pedidos que llegaron al doble en ese paso."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()), caidas_una_vez=escenario.get("caidas_una_vez", ()),
                                             columnas_personas=COLUMNAS_MEMORIA, caidas_fila=escenario.get("caidas_fila", ()))
    url_doble = doble.arrancar()
    puerto = esc._puerto_libre()
    entorno = dict(esc.ENTORNO_MINIMO)
    entorno.update(esc.ENTORNO_BASE)
    entorno.update(ENTORNO_NATALIA)
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(escenario.get("entorno", {}))
    with tempfile.TemporaryFile() as errores_de_arranque:
        proceso = subprocess.Popen(reloj.comando_programa(), cwd=cwd, env=entorno, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=errores_de_arranque)
        try:
            esc._esperar_arriba(puerto, proceso)
            doble.pedidos.clear()
            pasos = []
            for paso in escenario["pasos"]:
                antes = len(doble.pedidos)
                codigo, cuerpo = _pedir(puerto, paso)
                registro = {"status": codigo, "respuesta": cuerpo, "pedidos": doble.pedidos[antes:]}
                registro.update({"crudo": paso["crudo"]} if "crudo" in paso else {"cuerpo": paso["cuerpo"]})
                pasos.append(registro)
            return pasos, list(doble.errores)
        finally:
            proceso.terminate()
            proceso.wait(timeout=10)
            doble.parar()


# Cuerpo bueno para las guardas: la ficha 2 (un solo renglón en el doble) y un campo de los 12 con su base.
CUERPO_BUENO = {"id": 2, "base": {"notas": ""}, "cambios": {"notas": "nota de prueba"}}

# DORADOS: la App `editar` del portal y la memoria contestan lo mismo a estos pasos (sin `clave_envio`: la App no lo usa aquí).
DORADOS = [
    {"nombre": "guardado_y_repetido", "pasos": [
        _paso({"id": 2, "base": {"instagram": "", "Tono": "", "Resumen": ""},
               "cambios": {"instagram": "natalia_dos", "Tono": "Cercano, de tú", "Resumen": "Toca guitarra; pide sesiones de mañana."}}),
        _paso({"id": 2, "base": {"instagram": "", "Tono": "", "Resumen": ""},
               "cambios": {"instagram": "natalia_dos", "Tono": "Cercano, de tú", "Resumen": "Toca guitarra; pide sesiones de mañana."}}),
    ]},
    {"nombre": "cambio_entre_medio_409", "pasos": [
        _paso({"id": 2, "base": {"instagram": "vieja"}, "cambios": {"instagram": "otra"}}),
    ]},
    {"nombre": "sin_cambios", "pasos": [_paso({"id": 2, "base": {"instagram": ""}, "cambios": {"instagram": ""}})]},
    {"nombre": "sin_ficha_404", "pasos": [_paso({"id": 99, "base": {"notas": ""}, "cambios": {"notas": "x"}})]},
    {"nombre": "quitada_409", "pasos": [_paso({"id": 3, "base": {"instagram": ""}, "cambios": {"instagram": "x"}})]},
    {"nombre": "base_falta_400", "pasos": [_paso({"id": 2, "base": {}, "cambios": {"Tono": "x"}})]},
    {"nombre": "valor_no_texto_400", "pasos": [_paso({"id": 2, "base": {"Tono": ""}, "cambios": {"Tono": 7}})]},
    {"nombre": "instrumento_fuera_de_lista_422", "pasos": [
        _paso({"id": 2, "base": {"instrumento": ""}, "cambios": {"instrumento": "Teclado inventado"}})]},
    # Cumpleanos como texto (SingleLineText en el doble, tipo supuesto): la App lo guarda. El tipo real en la base no está medido.
    {"nombre": "cumpleanos_texto_200", "pasos": [_paso({"id": 2, "base": {"Cumpleanos": ""}, "cambios": {"Cumpleanos": "14/03"}})]},
    {"nombre": "lectura_caida_502", "caidas": ["GET"], "pasos": [_paso(CUERPO_BUENO)]},
    # Solo la lectura de la fila cae (la metadata sigue): aquí el 502 sale de `filas`, no de la lectura de columnas.
    {"nombre": "fila_caida_502", "caidas_fila": ["GET"], "pasos": [_paso(CUERPO_BUENO)]},
    {"nombre": "escritura_caida_502", "caidas": ["PATCH"], "pasos": [_paso(CUERPO_BUENO)]},
]

# GUARDA DE LA LLAVE (solo la prueba): sin la llave buena, 401 y cero pedidos. El cuerpo y la identidad son buenos.
GUARDA = [
    {"nombre": "llave_ausente", "pasos": [_paso(CUERPO_BUENO, llave=None)]},
    {"nombre": "llave_mala", "pasos": [_paso(CUERPO_BUENO, llave="mala")]},
    {"nombre": "llave_del_portal", "pasos": [_paso(CUERPO_BUENO, llave="portal")]},
    {"nombre": "cabecera_vacia_con_variable_vacia", "entorno": {"PERSONAS_NATALIA_LLAVE": ""}, "pasos": [_paso(CUERPO_BUENO, llave="vacia")]},
    {"nombre": "variable_vacia_con_cabecera_buena", "entorno": {"PERSONAS_NATALIA_LLAVE": ""}, "pasos": [_paso(CUERPO_BUENO, llave="natalia")]},
]

# IDENTIDAD (solo la prueba): sin quien de la cabecera, 400 y cero pedidos.
IDENTIDAD = [
    {"nombre": "sin_quien", "pasos": [_paso(CUERPO_BUENO, quien=None)]},
    {"nombre": "quien_vacio", "pasos": [_paso(CUERPO_BUENO, quien="")]},
    {"nombre": "quien_solo_espacios", "pasos": [_paso(CUERPO_BUENO, quien="   ")]},
]

# FUERA DE LA LISTA (solo la prueba): identidad de la ficha, campos que no son de la memoria, cuerpo roto. 400 y cero pedidos a NocoDB.
FUERA = [
    {"nombre": "%s_fuera" % c, "pasos": [_paso({"id": 2, "base": {c: ""}, "cambios": {c: "x"}})]}
    for c in ("nombre", "email", "nombre_whatsapp", "telefono", "telefono_2", "email_2", "Posible_proveedor", "credito", "caras", "bsuid")
] + [
    {"nombre": "sin_id", "pasos": [_paso({"base": {"notas": ""}, "cambios": {"notas": "x"}})]},
    {"nombre": "id_texto", "pasos": [_paso({"id": "2", "base": {"notas": ""}, "cambios": {"notas": "x"}})]},
    {"nombre": "base_faltante", "pasos": [_paso({"id": 2, "cambios": {"notas": "x"}})]},
    {"nombre": "cuerpo_roto", "pasos": [_paso(crudo="{no es json")]},
]
