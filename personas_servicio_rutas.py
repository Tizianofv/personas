# -*- coding: utf-8 -*-
"""LAS CUATRO RUTAS DE SERVICIO DE PERSONAS QUE PIDEN REGISTRO Y CAJA. Solo lectura.

Forma tomada del encargo de la sala (4-nov-2026), que cita `disenos/personas-programa-aparte/DISENO.md` (paso 4 y tabla de la
sección 3) y `disenos/registro-caja-programa-aparte/DISENO.md` 2.1.1. Esos archivos no se leyeron desde este árbol.

Rutas (en `PERSONAS_LECTURA_POST` de `server.py`, despachadas por `Handler.personas_lectura_post`, que valida cada una con SU llave:
cabecera `X-Personas-Registro-Llave`, variable `PERSONAS_REGISTRO_LLAVE`. La de Mercadeo (`X-Personas-Lectura-Llave`,
`PERSONAS_LECTURA_LLAVE`) NO las abre, y la de Registro no abre las de Mercadeo. El agente `personas_registro` de la tabla de credenciales
da el permiso `lee_personas_registro`):
  POST /api/servicio/personas/credito  {"telefono": "<texto>"}
       → 200 {"credito": <número>, "persona_id": <entero o null>}. Sin ficha: credito 0, persona_id null.
  POST /api/servicio/personas/buscar   {"q": "<texto>", "limite": <entero 1..12>}
       → 200 {"personas": [ficha, …]}, con las fichas que devuelve `personas.buscar_personas` (mismo score, mismo orden).
         Con `q` de menos de 2 caracteres (después de recortar) → {"personas": []} SIN leer Personas.
  POST /api/servicio/personas/creditos-vivos  {}
       → 200 {"fichas": [ {Id, nombre, telefono, credito}, … ]}: las de `personas.fichas_con_credito_vivo()` (credito > 0, lista bruta).
         Hay créditos vivos si la lista no está vacía. Ante fallo: 502.
  POST /api/servicio/personas/bandeja  {"estados": [...], "campos": "...", "pagina": <1..1000>, "tope": <1..1000>, "cursor": <0 o más>}
       → 200 {"filas": [fila, …], "ultima": <bool>}. Forma del cliente de Registro (`personas_cliente.py`): una sola llamada para todos los
         estados, filas por `Id` mayor que `cursor` (los `Id` son únicos en la tabla), cada fila con su `estado`, en orden de `Id`.
         `pagina` son las filas por lectura de NocoDB. `tope` son las lecturas de NocoDB que se permiten, contadas juntas para todos los estados
         (como el cuadro); cada estado hace siempre su primera lectura. Si el tope corta antes de terminar: 200 con las filas que quedan
         hasta el `Id` confirmado de todos los estados, y `ultima` falso. Solo 502 si NocoDB falla o no confirma una página.
         NocoDB que no confirma una página, o que falla: 502. Si el tope corta, NO es 502: ver arriba.

Cada función devuelve `(codigo, cuerpo)` y recibe `s`, el módulo `server`, igual que `personas_lectura`.

Lectura: las cuatro usan el lector ESTRICTO de Personas (`personas._anotaciones_leer_tabla`), no `nc_list_all` ni `get_personas`:
`nc_list_all` da por última una respuesta sin `pageInfo` y `get_personas` la toma como lista completa, y eso daría un vacío falso.
Ante cualquier fallo de la lectura: 502 con mensaje fijo, nunca una lista vacía ni un crédito 0.

No pasan por `personas_servicio.Puerta`: esa puerta es para los módulos de zona (Mercadeo, chat, Proveedores, Lucy). Esta ruta
llama a `personas` directo, igual que `personas_lectura.py`.

La bandeja es de Personas (pregunta 2 de la sección 1 de Caja, cerrada por la sala principal el 4-nov-2026: decisión 2 del diseño de Personas).
Este módulo solo la lee, con `s.T_BANDEJA_PERSONAS`; no cambia quién la llama.
"""
import re

import personas

CREDITO_CAMPOS = "Id,credito"
PERSONA_CAMPOS_BUSCAR = personas.PERSONA_FIELDS + ",unida_a,quitada_el"
BUSCAR_LIMITE_MAX = 12
BUSCAR_TEXTO_MINIMO = 2
# Frontera declarada: los estados que lee el cuadro de la entrada (`server._cuadro_leer`). Una prueba exige que sean los mismos.
BANDEJA_ESTADOS = ("contado", "descartado")
BANDEJA_PAGINA_MAX = 1000
BANDEJA_TOPE_MAX = 1000
_CAMPO = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
ERROR_FIJO_LECTURA = {"ok": False, "error": "No se pudo leer Personas. Inténtalo en un momento."}
ERROR_FIJO_BANDEJA = {"ok": False, "error": "No se pudo leer la bandeja de la entrada. Inténtalo en un momento."}
ERROR_BANDEJA_SIN_TABLA = {"ok": False, "error": "La bandeja de la entrada no está configurada."}


def _entero_en(v, minimo, maximo):
    """Un entero de verdad (ni `True`, ni texto, ni decimal) entre `minimo` y `maximo` (o sin techo si `maximo` es `None`)."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimo and (maximo is None or v <= maximo)


def _telefono_de_credito(telefono):
    """El mismo recorte que `personas.credito_de_cliente`: solo dígitos, y 10 dígitos reciben el «1» de República Dominicana."""
    tel = re.sub(r"\D", "", str(telefono or ""))
    if len(tel) == 10:
        tel = "1" + tel
    return tel


def credito(s, cuerpo):
    if not (isinstance(cuerpo, dict) and set(cuerpo) == {"telefono"} and isinstance(cuerpo["telefono"], str)):
        return 400, {"ok": False, "error": "El pedido de crédito es {\"telefono\": \"…\"}, en texto."}
    tel = _telefono_de_credito(cuerpo["telefono"])
    if not tel:
        return 200, {"credito": 0.0, "persona_id": None}
    try:
        filas = personas._anotaciones_leer_tabla(s.T_PERSONAS, CREDITO_CAMPOS, "(telefono,eq,%s)" % tel)
        if not filas:
            return 200, {"credito": 0.0, "persona_id": None}
        persona_id = personas._anotaciones_entero(filas[0].get("Id"))
        if persona_id is None:
            raise ValueError("Id sin forma de entero")
        return 200, {"credito": float(filas[0].get("credito") or 0), "persona_id": persona_id}
    except Exception:                                    # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: no hay dato firme que dar
        return 502, dict(ERROR_FIJO_LECTURA)


def buscar(s, cuerpo):
    if not (isinstance(cuerpo, dict) and set(cuerpo) == {"q", "limite"} and isinstance(cuerpo["q"], str)
            and _entero_en(cuerpo["limite"], 1, BUSCAR_LIMITE_MAX)):
        return 400, {"ok": False, "error": "El pedido de buscar es {\"q\": \"…\", \"limite\": 1 a 12}."}
    q = cuerpo["q"].strip()
    if len(q) < BUSCAR_TEXTO_MINIMO:
        return 200, {"personas": []}
    try:
        filas = personas._anotaciones_leer_tabla(s.T_PERSONAS, PERSONA_CAMPOS_BUSCAR)
        fichas = [{k: v for k, v in f.items() if k not in ("unida_a", "quitada_el")}
                  for f in filas if not personas.ficha_fuera(f)]
        return 200, {"personas": personas.buscar_en_fichas(fichas, q, cuerpo["limite"])}
    except Exception:                                    # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: nunca una lista vacía falsa
        return 502, dict(ERROR_FIJO_LECTURA)


CREDITOS_VIVOS_CAMPOS = "Id,nombre,telefono,credito"


def creditos_vivos(s, cuerpo):
    """La forma de `personas.fichas_con_credito_vivo()` (la que pide el reporte mensual): las fichas con `credito > 0`, con
    `Id`, `nombre`, `telefono` y `credito`. Lista bruta, sin filtrar; la leen con el lector estricto, no con `nc_list_all`."""
    if cuerpo != {}:
        return 400, {"ok": False, "error": "El pedido de creditos-vivos es {}: no lleva parámetros."}
    try:
        return 200, {"fichas": personas._anotaciones_leer_tabla(s.T_PERSONAS, CREDITOS_VIVOS_CAMPOS, "(credito,gt,0)")}
    except Exception:                                    # noqa: BLE001 — `_NoSeSupo` o cualquier fallo: nunca una lista vacía falsa
        return 502, dict(ERROR_FIJO_LECTURA)


def _leer_pagina_de_la_bandeja(s, estados, campos, cursor, pagina, tope):
    """Una página de la bandeja para TODOS los `estados`: `(filas, ultima)`. Las filas salen por `Id` mayor que `cursor`, en orden de `Id`,
    cada una con su `estado`. Lee con `s._bandeja_pagina` (la lectura de la entrada, que confirma cada página con `isLastPage`).

    El tope cuenta las lecturas de NocoDB de todos los estados juntos (como `_bandeja_leer`). Cada estado hace siempre su primera lectura,
    así que la página nunca queda vacía sin razón. Si el tope corta antes de terminar, se devuelven las filas hasta el `Id` que TODOS los
    estados confirman (el menor de los `Id` donde se cortó un estado), con `ultima` falso: lo que venga después se pide con ese `cursor`.
    """
    lecturas, leidas, corte = 0, [], {}
    for estado in estados:
        cur, primera = cursor, True
        while True:
            if not primera and lecturas >= tope:
                corte[estado] = cur                          # aquí se cortó: lo leído de este estado llega hasta `cur`
                break
            primera = False
            pagina_leida, ultima_del_estado = s._bandeja_pagina(estado, cur, pagina, campos)
            lecturas += 1
            leidas.extend((f["Id"], dict(f, estado=estado)) for f in pagina_leida)
            if ultima_del_estado:
                break                                        # este estado terminó: no pone corte
            if not pagina_leida or pagina_leida[-1]["Id"] <= cur:
                raise s._EntradaSinConfirmar()
            cur = pagina_leida[-1]["Id"]
    if corte:
        limite = min(corte.values())
        leidas = [(i, f) for i, f in leidas if i <= limite]
        ultima = False
    else:
        ultima = True
    leidas.sort(key=lambda par: par[0])
    return [f for _, f in leidas], ultima


def bandeja(s, cuerpo):
    claves = {"estados", "campos", "pagina", "tope", "cursor"}
    if not (isinstance(cuerpo, dict) and set(cuerpo) == claves):
        return 400, {"ok": False, "error": "El pedido de bandeja es {estados, campos, pagina, tope, cursor}."}
    estados, campos = cuerpo["estados"], cuerpo["campos"]
    # Tipos ANTES que `set`: un elemento no hashable (lista, dict) no debe lanzar, debe ser 400.
    if not (isinstance(estados, list) and estados and all(isinstance(e, str) for e in estados)
            and len(set(estados)) == len(estados) and all(e in BANDEJA_ESTADOS for e in estados)):
        return 400, {"ok": False, "error": "estados: lista de «contado» y «descartado», sin repetir."}
    if not isinstance(campos, str):
        return 400, {"ok": False, "error": "campos: nombres de columna separados por coma, con Id."}
    partes = [c.strip() for c in campos.split(",")]
    if any(not _CAMPO.match(c) for c in partes) or "Id" not in partes:
        return 400, {"ok": False, "error": "campos: nombres de columna separados por coma, con Id."}
    if not (_entero_en(cuerpo["pagina"], 1, BANDEJA_PAGINA_MAX) and _entero_en(cuerpo["tope"], 1, BANDEJA_TOPE_MAX)
            and _entero_en(cuerpo["cursor"], 0, None)):
        return 400, {"ok": False, "error": "pagina (1 a 1000), tope (1 a 1000) y cursor (0 o más): enteros."}
    if not s.T_BANDEJA_PERSONAS:
        return 503, dict(ERROR_BANDEJA_SIN_TABLA)
    try:
        filas, ultima = _leer_pagina_de_la_bandeja(s, tuple(estados), ",".join(partes), cuerpo["cursor"], cuerpo["pagina"], cuerpo["tope"])
    except Exception:                                    # noqa: BLE001 — NocoDB falló o no confirmó una página: nunca un conteo firme falso
        return 502, dict(ERROR_FIJO_BANDEJA)
    return 200, {"filas": filas, "ultima": ultima}
