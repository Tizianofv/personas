# -*- coding: utf-8 -*-
"""Los escenarios de la entrada de Natalia (`POST …/entrada`, P5a + P5b): los mismos pedidos contra la App y contra el programa.

  lado `app`:      `POST /api/fichas/entrada`, cabecera `X-Fichas-Llave`, variable `FICHAS_LLAVE_SERVICIO` (la App de registro).
  lado `programa`: `POST /api/servicio/personas/entrada`, cabecera `X-Personas-Entrada-Llave`, variable `PERSONAS_ENTRADA_LLAVE`.

Cada escenario arranca un proceso nuevo y un doble de NocoDB nuevo (`tests/doble_escrituras.py`) con su bandeja de prueba
(`T_BANDEJA_ENTRADA`, con las filas que el escenario necesita). `escenarios_entrada.ejecutar` devuelve, por paso, el código, la
respuesta y los pedidos que llegaron al doble en ese paso, y los pedidos que el doble no conoce (`errores`). La foto la saca
`tools/generar_entrada_de_la_app.py` del lado `app`; la prueba `tests/test_entrada.py` la repite en el lado `programa`.

Valores de prueba (no son secretos). Sin cabeceras de llave en ningún registro.
"""
import copy
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doble_escrituras  # noqa: E402
import doble_nocodb  # noqa: E402
import escenarios_escrituras  # noqa: E402  (puerto libre, espera de arranque, entorno mínimo)

RUTA = {"app": "/api/fichas/entrada", "programa": "/api/servicio/personas/entrada"}
CABECERA = {"app": "X-Fichas-Llave", "programa": "X-Personas-Entrada-Llave"}
VARIABLE_LLAVE = {"app": "FICHAS_LLAVE_SERVICIO", "programa": "PERSONAS_ENTRADA_LLAVE"}
VALOR_LLAVE = "llave-de-prueba-entrada-personas"
T_BANDEJA_ENTRADA = "tabla-bandeja-entrada-prueba"
# Las tablas que el doble declara, por su variable de entorno (las dos apps las leen igual).
ENTORNO_TABLAS = {
    "NOCODB_T_BANDEJA_PERSONAS": T_BANDEJA_ENTRADA,
    "NOCODB_T_UNIONES_PERSONAS": doble_nocodb.T_UNIONES,
    "NOCODB_T_PERSONAS_QUITADAS": doble_nocodb.T_QUITADAS,
    "NOCODB_T_PERSONAS_ANOTACIONES": doble_nocodb.TABLA_ANOTACIONES,
    "NOCODB_T_MERCADEO_ENVIOS": doble_nocodb.T_MERCADEO_ENVIOS,
}
RESULTADO_CONTADO = ('{"accion": "crea", "avisos": [], "caso": "crea", "crearia": true, "estado": "aplicado", "modo": "contar", '
                     '"union": null, "valores": {}}')


def fila(Id, estado="pendiente", origen="mensaje", **campos):
    """Una fila de la bandeja con las casillas que lee la entrada. `campos` pisa lo que haga falta."""
    base = {"Id": Id, "estado": estado, "origen": origen, "clave": "wa-%d" % Id, "id_whatsapp": None, "telefono_meta": None,
            "telefono_dicho": None, "nombre": None, "nombre_perfil": None, "correo": None, "ficha_id": None,
            "otra_ficha_id": None, "resultado": None}
    base.update(campos)
    return base


def bandeja(*filas):
    return {T_BANDEJA_ENTRADA: [copy.deepcopy(f) for f in filas]}


NUEVA = fila(1, telefono_meta="18097770501", nombre="Cliente Nueva Uno")
CON_TELEFONO_EXISTENTE = fila(1, telefono_meta="18097770001", nombre_perfil="Persona de prueba 1")
UNION = fila(1, telefono_meta="18090001101", nombre="Union Uno")

# Cada escenario: `pasos` (cada uno con `cuerpo` o `crudo`, y `valor` de la llave: valida, mala, vacia o ausente).
# `entorno` pisa el entorno base de ambos lados (solo lo que el escenario necesita).
ESCENARIOS = [
    {"nombre": "contar_crea_una_ficha_nueva", "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribir_crea_y_repite_sin_duplicar", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"}, "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}, {"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribir_completa_ficha_existente", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"}, "tablas": bandeja(CON_TELEFONO_EXISTENTE),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribir_une_dos_fichas_de_la_misma_persona", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"}, "union": True, "tablas": bandeja(UNION),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "modo_no_exacto_cuenta", "entorno": {"FICHAS_ENTRADA_MODO": "Escribir"}, "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "fila_inexistente", "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 99}, "valor": "valida"}]},
    {"nombre": "pedido_ilegible", "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {}, "valor": "valida"}, {"cuerpo": {"fila": "1"}, "valor": "valida"}, {"cuerpo": {"fila": 0}, "valor": "valida"},
               {"cuerpo": {"fila": 1, "otra": 2}, "valor": "valida"}, {"cuerpo": {"fila": True}, "valor": "valida"},
               {"crudo": "esto no es json", "valor": "valida"}]},
    {"nombre": "sin_bandeja", "entorno": {"NOCODB_T_BANDEJA_PERSONAS": ""}, "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "contar_caida_al_apuntar", "caidas": ("PATCH",), "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribir_caida_al_marcar", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"}, "caidas": ("PATCH",), "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribiendo_a_medias_cuenta_409", "tablas": bandeja(fila(1, estado="escribiendo", telefono_meta="18097770501")),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "escribiendo_a_medias_escribe_y_reanuda", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"},
     "tablas": bandeja(fila(1, estado="escribiendo", telefono_meta="18097770501")),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "ya_contada_responde_lo_guardado", "tablas": bandeja(fila(1, estado="contado", resultado=RESULTADO_CONTADO, telefono_meta="18097770501")),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "resultado_guardado_ilegible_422", "tablas": bandeja(fila(1, estado="contado", resultado="no es json", telefono_meta="18097770501")),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "origen_desconocido_descartado", "tablas": bandeja(fila(1, origen="otro", telefono_meta="18097770501")),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "valida"}]},
    {"nombre": "barrido_procesa_las_pendientes_antes", "entorno": {"FICHAS_ENTRADA_MODO": "escribir"},
     "tablas": bandeja(fila(1, telefono_meta="18097770501", nombre="Cliente A"), fila(2, telefono_meta="18097770502", nombre="Cliente B"),
                       fila(3, telefono_meta="18097770503", nombre="Cliente C")),
     "pasos": [{"cuerpo": {"fila": 3}, "valor": "valida"}]},
    {"nombre": "llave_mala_no_lee_ni_escribe", "tablas": bandeja(NUEVA),
     "pasos": [{"cuerpo": {"fila": 1}, "valor": "mala"}, {"cuerpo": {"fila": 1}, "valor": "vacia"}, {"cuerpo": {"fila": 1}, "valor": "ausente"}]},
]


_HORA = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00")


def horas_de_los_pedidos(pasos):
    """Los valores de `cuando` que llegaron al doble en los cuerpos de los pedidos (la hora de la escritura del origen)."""
    return [p["cuerpo"]["cuando"] for paso in pasos for p in paso["pedidos"]
            if isinstance(p.get("cuerpo"), dict) and "cuando" in p["cuerpo"]]


def normalizar_horas(pasos):
    """`cuando` es la hora en que la App o el programa anotan el origen de una ficha: cambia en cada corrida. En la foto y en la comparación
    va como `<hora>`. Quien llama debe haber comprobado antes que cada valor es una hora ISO (`horas_de_los_pedidos`, `_HORA`)."""
    for paso in pasos:
        for p in paso["pedidos"]:
            if isinstance(p.get("cuerpo"), dict) and "cuando" in p["cuerpo"]:
                p["cuerpo"]["cuando"] = "<hora>"
    return pasos


def _valor(simbolo):
    if simbolo == "valida":
        return VALOR_LLAVE
    if simbolo == "mala":
        return "llave-equivocada-de-prueba"
    if simbolo == "vacia":
        return ""
    if simbolo == "ausente":
        return None
    raise ValueError("símbolo de llave desconocido: %r" % simbolo)


def _pedir(puerto, lado, paso):
    datos = paso["crudo"].encode("utf-8") if "crudo" in paso else json.dumps(paso["cuerpo"]).encode("utf-8")
    cabeceras = {"Content-Type": "application/json"}
    valor = _valor(paso["valor"])
    if valor is not None:
        cabeceras[CABECERA[lado]] = valor
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (puerto, RUTA[lado]), data=datos, method="POST", headers=cabeceras)
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
    """Corre los pasos de un escenario contra `comando` (un servidor del lado `lado` que escucha en PORT, con NOCODB_BASE puesto al doble).
    Devuelve (pasos, errores_del_doble). El proceso y el doble se cierran al terminar, pase lo que pase."""
    doble = doble_escrituras.DobleEscrituras(caidas=escenario.get("caidas", ()), union=escenario.get("union", False))
    for tabla, filas in escenario.get("tablas", {}).items():
        doble.tablas[tabla] = copy.deepcopy(filas)
    url_doble = doble.arrancar()
    puerto = escenarios_escrituras._puerto_libre()
    entorno = dict(escenarios_escrituras.ENTORNO_MINIMO)
    entorno.update(ENTORNO_TABLAS)
    entorno.update({VARIABLE_LLAVE[lado]: VALOR_LLAVE})
    entorno.update({"HOST": "127.0.0.1", "PORT": str(puerto), "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba",
                    "APP_PIN": "pin-de-prueba"})
    entorno.update(escenario.get("entorno", {}))
    with tempfile.TemporaryFile() as errores_de_arranque:
        proceso = subprocess.Popen(comando, cwd=cwd, env=entorno, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=errores_de_arranque)
        try:
            escenarios_escrituras._esperar_arriba(puerto, proceso)
            doble.pedidos.clear()
            pasos = []
            for paso in escenario["pasos"]:
                antes = len(doble.pedidos)
                codigo, cuerpo = _pedir(puerto, lado, paso)
                registro = {"ruta": RUTA[lado], "valor": paso["valor"], "status": codigo, "respuesta": cuerpo,
                            "pedidos": doble.pedidos[antes:]}
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
