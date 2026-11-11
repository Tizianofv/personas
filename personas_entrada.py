# -*- coding: utf-8 -*-
"""LA ENTRADA DE NATALIA EN EL PROGRAMA DE PERSONAS (P5a + P5b de `disenos/personas-programa-aparte/UNA-SOLA-PUERTA.md`).

`POST /api/servicio/personas/entrada` (cuerpo `{"fila": n}`): la misma respuesta y las mismas escrituras en la bandeja y en las
fichas que `POST /api/fichas/entrada` de la App de registro en `8c9d21a`. Copia de la entrada de la App: `entrada_fichas`,
`entrada_procesar`, `entrada_barrer`, `_entrada_resumen`, `_entrada_cuerpo`, `_entrada_leer_resultado`, `_entrada_confirmado`,
`_entrada_dato`, `_entrada_registrar` y el modo. Los cambios son solo de nombre: `nc` es `base.nc`; la lectura de una fila es
`personas._entrada_leer_fila`; la puerta es `personas.recibir_y_unir`.

LA LLAVE NO VIVE AQUÍ: la mira `servidor.py` antes de leer el cuerpo (`PERSONAS_ENTRADA_LLAVE`, cabecera `X-Personas-Entrada-Llave`).
La App sigue mirando su propia llave (`X-Fichas-Llave`, `FICHAS_LLAVE_SERVICIO`) antes de reenviar.

EL MODO: `FICHAS_ENTRADA_MODO`, leído de la variable de este proceso con el mismo nombre y el mismo valor por defecto que la App:
solo el valor exacto `escribir` escribe; ausente, vacío o cualquier otra cosa, `contar`.

Lo que NO está aquí, a propósito: `entrada_barrer_al_arrancar` (la App la llama al arrancar, `main()`) y `apuntar_no_son_la_misma`
(no entra en la ruta de la entrada: la usa el portal, `personas.py`). El cierre de la App (que deje de atender la entrada y solo
reenvíe) es otra pieza.

El cursor (`_ENTRADA_CURSOR`) y el candado (`_ENTRADA_LOCK`) son de este proceso: dos procesos que barran la bandeja a la vez no se
ven. Mientras la App y el programa atiendan la misma ruta, ese riesgo existe; la pieza siguiente deja una sola.
"""
import ast
import json
import os
import re
import threading

import base as _base
import personas

ENTRADA_TOPE_BARRIDO = 5        # filas pendientes que cada llamada procesa antes de la pedida (igual que la App)
ENTRADA_MODO_ESCRIBIR = "escribir"
ENTRADA_FUERA_DEL_CONJUNTO = "fuera_del_conjunto"
ENTRADA_ESTADO_ESCRIBIENDO = "escribiendo"     # la marca "la escritura de esta fila ya empezó": la pone la entrada escribiendo, antes de escribir nada más
ENTRADA_UNION_CONFIRMADA = ("unida", "no_se_pudo", "no_son_la_misma", "credito")     # lo que la unión sola puede contestar escribiendo y deja la fila apuntable
ENTRADA_VALOR_CLARO = ("guardado", "ya_estaba", "no_guardado")                           # lo que un valor puede decir en una fila apuntada como hecha
_ENTRADA_CASILLAS = ("id_whatsapp", "telefono_meta", "telefono_dicho", "nombre", "nombre_perfil", "correo")
_ENTRADA_PROPIOS = ("pendiente", "contado", "descartado", "escribiendo", "ninguna:origen_desconocido")
_ENTRADA_VOCABULARIO = []
_ENTRADA_LOCK = threading.Lock()
_ENTRADA_CURSOR = [0]
_entrada_id = _base._entrada_id
_EntradaSinConfirmar = _base._EntradaSinConfirmar


class _EntradaAMedias(_EntradaSinConfirmar):
    """La fila lleva la marca `escribiendo` (la escritura ya empezó) y la entrada está contando: contar no la toca ni la cambia."""


class _EntradaResultadoIlegible(Exception):
    """El `resultado` guardado en una fila no tiene la forma que escribe la entrada."""


def entrada_modo():
    """LA PUERTA ÚNICA DEL MODO: `escribir` solo con el valor EXACTO `escribir` en `FICHAS_ENTRADA_MODO` (sin quitar espacios ni mayúsculas);
    ausente, vacío o cualquier otra cosa, `contar`. Es la única función que lee la variable."""
    return "escribir" if os.environ.get("FICHAS_ENTRADA_MODO") == ENTRADA_MODO_ESCRIBIR else "contar"


def _entrada_vocabulario():
    """Las palabras con forma de código que escribe `personas.py` en su código, más las que escribe la entrada."""
    if not _ENTRADA_VOCABULARIO:
        try:
            with open(personas.__file__, encoding="utf-8") as f:
                arbol = ast.parse(f.read())
            palabras = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and re.fullmatch(r"[a-z_][a-z0-9_]{0,39}", n.value)}
        except Exception:                                     # noqa: BLE001
            palabras = set()
        _ENTRADA_VOCABULARIO.append(frozenset(palabras | set(_ENTRADA_PROPIOS) | set(personas.PUERTA_CASOS) | set(personas.PUERTA_AVISOS)))
    return _ENTRADA_VOCABULARIO[0]


def _entrada_codigo(x, conjunto=None):
    """`x` si está en su conjunto conocido (por omisión el vocabulario de la puerta); si no, un marcador fijo."""
    if x is None:
        return None
    return x if isinstance(x, str) and x in (conjunto if conjunto is not None else _entrada_vocabulario()) else ENTRADA_FUERA_DEL_CONJUNTO


def _entrada_resumen(r, modo="contar"):
    """El resultado de la puerta reducido a códigos de su conjunto e Ids de ficha; `modo` es el que corrió (`contar` | `escribir`)."""
    union = r.get("union")
    casos = set(personas.PUERTA_CASOS) | set(_ENTRADA_PROPIOS)
    valores = {}
    for k, v in (r.get("valores") or {}).items():
        if isinstance(v, dict):
            valores[_entrada_codigo(k)] = {c: _entrada_codigo(v.get(c)) for c in ("resultado", "motivo", "en")}
    avisos = [{"tipo": _entrada_codigo(a.get("tipo"), personas.PUERTA_AVISOS), "ficha_id": _entrada_id(a.get("ficha_id")), "otra_ficha_id": _entrada_id(a.get("otra_ficha_id"))}
              for a in (r.get("avisos") or []) if isinstance(a, dict)]
    return {"modo": "escribir" if modo == "escribir" else "contar", "estado": _entrada_codigo(r.get("estado")), "accion": _entrada_codigo(r.get("accion")), "caso": _entrada_codigo(r.get("caso"), casos),
            "crearia": r.get("crearia") is True, "union": _entrada_codigo(union.get("estado")) if isinstance(union, dict) else None,
            "valores": valores, "avisos": avisos}


def _entrada_leer_resultado(texto):
    """El `resultado` guardado en una fila, con la forma de `_entrada_resumen`; levanta `_EntradaResultadoIlegible` si no es de esa forma."""
    if texto is None or texto == "":
        return _entrada_resumen({})
    try:
        d = json.loads(texto)
    except (TypeError, ValueError) as e:
        raise _EntradaResultadoIlegible() from e
    texto_o_nada = lambda v: v is None or isinstance(v, str)             # noqa: E731
    entero_o_nada = lambda v: v is None or _entrada_id(v) is not None     # noqa: E731
    if not isinstance(d, dict) or not all(texto_o_nada(d.get(k)) for k in ("modo", "estado", "accion", "caso", "union")):
        raise _EntradaResultadoIlegible()
    if not (d.get("crearia") is None or isinstance(d["crearia"], bool)):
        raise _EntradaResultadoIlegible()
    valores, avisos = d.get("valores", {}), d.get("avisos", [])
    if not isinstance(valores, dict) or not isinstance(avisos, list):
        raise _EntradaResultadoIlegible()
    if not all(isinstance(v, dict) and all(texto_o_nada(v.get(c)) for c in ("resultado", "motivo", "en")) for v in valores.values()):
        raise _EntradaResultadoIlegible()
    if not all(isinstance(a, dict) and isinstance(a.get("tipo"), str) and entero_o_nada(a.get("ficha_id")) and entero_o_nada(a.get("otra_ficha_id")) for a in avisos):
        raise _EntradaResultadoIlegible()
    return _entrada_resumen(dict(d, union={"estado": d.get("union")} if d.get("union") is not None else None), modo=d.get("modo"))


def _entrada_cuerpo(fila):
    """La respuesta de la ruta para una fila de la bandeja, armada con lo que la fila guarda; levanta `_EntradaResultadoIlegible`."""
    guardado = _entrada_leer_resultado(fila.get("resultado"))
    return {"modo": guardado["modo"], "fila": fila.get("Id"), "estado": _entrada_codigo(fila.get("estado")), "ficha_id": _entrada_id(fila.get("ficha_id")),
            "accion": guardado["accion"], "caso": guardado["caso"], "valores": guardado["valores"], "avisos": guardado["avisos"]}


def _entrada_dato(fila):
    """El dato de la puerta con las casillas que la fila trae escritas."""
    dato = {"origen": fila.get("origen")}
    if isinstance(fila.get("clave"), str) and fila["clave"].strip():
        dato["clave"] = fila["clave"].strip()
    for c in _ENTRADA_CASILLAS:
        v = fila.get(c)
        if v is not None and not isinstance(v, (bool, dict, list)) and str(v).strip():
            dato[c] = str(v).strip()
    return dato


def _entrada_registrar(fila, estado, resumen, ficha_id, fallo="-", modo="contar"):
    origen = fila.get("origen") if fila.get("origen") in _base.ENTRADA_ORIGENES else "desconocido"
    print("[ENTRADA-FICHAS] modo=%s fila=%s origen=%s estado=%s accion=%s caso=%s ficha_id=%s avisos=%s fallo=%s" % (
        "escribir" if modo == "escribir" else "contar", fila.get("Id"), origen, estado, resumen.get("accion") or "-", resumen.get("caso") or "-", ficha_id if ficha_id is not None else "-",
        ",".join(a["tipo"] for a in resumen.get("avisos", [])) or "-", fallo))


def _entrada_confirmado(r):
    """¿Lo que la puerta contestó escribiendo se puede apuntar en la fila como hecho? Solo si todo quedó confirmado: un `guardado` solo cuenta con la fila
    releída, ningún valor quedó sin confirmar, la unión (si la hubo) tiene un resultado conocido y cada aviso quedó apuntado en la bandeja. Lo demás
    deja la fila `pendiente`: un `por_resolver` solo vale con un aviso no informativo ya apuntado (el que «Por resolver» muestra); la repetición lo termina (la puerta encuentra lo que ya escribió y la unión se reanuda por su clave)."""
    estado = r.get("estado")
    if estado == "rechazado":
        return True
    if estado not in ("aplicado", "por_resolver"):
        return False
    valores = r.get("valores") or {}
    if not all(isinstance(v, dict) and v.get("resultado") in ENTRADA_VALOR_CLARO for v in valores.values()):
        return False
    if any(v["resultado"] == "guardado" for v in valores.values()) and not isinstance(r.get("releida"), dict):
        return False
    union = r.get("union")
    if union is not None and not (isinstance(union, dict) and union.get("estado") in ENTRADA_UNION_CONFIRMADA):
        return False
    avisos = r.get("avisos") or []
    if not all(isinstance(a, dict) and a.get("apuntado") is True for a in avisos):
        return False
    if estado == "por_resolver":                              # nadie ve una fila `por_resolver`: tiene que haber un aviso apuntado que una persona tenga que mirar
        return any(a.get("informativo") is False and a.get("tipo") in personas.PUERTA_AVISOS for a in avisos)
    return estado != "aplicado" or _entrada_id(r.get("ficha_id")) is not None


def entrada_procesar(fila, solo_contar=False, mandaria=None):
    """Pasa una fila pendiente por la puerta y apunta el resultado en la misma fila; devuelve la fila apuntada. Contando (`entrada_modo`) no escribe
    ninguna ficha y la deja `contado`; escribiendo, la puerta y la unión sola escriben de verdad y la fila queda `aplicado` o `por_resolver`
    (`descartado` si la puerta la rechazó). Lo que no se confirma deja la fila `pendiente` y levanta `_EntradaSinConfirmar`."""
    # 🔑 `solo_contar` (P11-6, grupo b): recorre lo mismo que la entrada en modo contar, pero no escribe: lo que mandaría a la bandeja
    # se añade a `mandaria` (tabla, método y cuerpo) y se devuelve la fila como si estuviera apuntada.
    modo = "contar" if solo_contar else entrada_modo()
    escribe = modo == "escribir"
    if fila.get("estado") == ENTRADA_ESTADO_ESCRIBIENDO and not escribe:      # contar solo toca filas `pendiente`: una marcada no se cuenta ni se cambia
        _entrada_registrar(fila, ENTRADA_ESTADO_ESCRIBIENDO, {}, None, "escritura_a_medias", modo)
        raise _EntradaAMedias()
    if escribe and fila.get("estado") != ENTRADA_ESTADO_ESCRIBIENDO:           # lo PRIMERO, antes de escribir nada más: marcar esta fila y releer que quedó
        try:
            _base.nc("PATCH", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records", body={"Id": fila["Id"], "estado": ENTRADA_ESTADO_ESCRIBIENDO})
            marcada = personas._entrada_leer_fila(fila["Id"])
            if marcada is None or marcada.get("estado") != ENTRADA_ESTADO_ESCRIBIENDO:
                raise _EntradaSinConfirmar()
        except Exception as e:                                # noqa: BLE001
            _entrada_registrar(fila, "sin_confirmar", {}, None, "sin_marca:" + _base._resumen_del_fallo(e), modo)
            raise _EntradaSinConfirmar() from e
        fila = dict(fila, estado=ENTRADA_ESTADO_ESCRIBIENDO)
    if fila.get("origen") in _base.ENTRADA_ORIGENES:
        try:
            r = personas.recibir_y_unir(_entrada_dato(fila), solo_contar=not escribe)
        except Exception as e:                                # noqa: BLE001
            _entrada_registrar(fila, "sin_confirmar", {}, None, _base._resumen_del_fallo(e), modo)
            raise _EntradaSinConfirmar() from e
        if r.get("estado") == "sin_confirmar" or (escribe and not _entrada_confirmado(r)):
            union = r.get("union")
            sin_destino = "puerta" if r.get("estado") == "sin_confirmar" else "sin_destino:estado=%s:union=%s" % (
                _entrada_codigo(r.get("estado")), _entrada_codigo(union.get("estado")) if isinstance(union, dict) else "-")
            _entrada_registrar(fila, "sin_confirmar", {}, None, sin_destino, modo)
            raise _EntradaSinConfirmar()
    else:
        r = {"estado": "rechazado", "accion": "no_tocada", "caso": "ninguna:origen_desconocido", "valores": {}, "avisos": []}
    resumen = _entrada_resumen(r, modo)
    estado = "descartado" if r.get("estado") == "rechazado" else (r["estado"] if escribe else "contado")
    ficha_id = _entrada_id(r.get("ficha_id"))
    if ficha_id is None:                                      # dos fichas, la misma persona: la puerta nombra primero la de quien escribe
        ficha_id = next((a["ficha_id"] for a in resumen["avisos"] if a["tipo"] == "misma_persona"), None)
    if ficha_id is None and escribe:                          # escribiendo, la fila nombra una ficha de su aviso: así, al resolverlo, «Por resolver» la devuelve a `pendiente`
        ficha_id = next((a["ficha_id"] for a in resumen["avisos"] if a["ficha_id"] is not None), None)
    otra = next((a["otra_ficha_id"] for a in resumen["avisos"] if a["otra_ficha_id"] is not None), None)
    cambios = {"estado": estado, "resultado": json.dumps(resumen, sort_keys=True, ensure_ascii=True)}
    if ficha_id is not None:
        cambios["ficha_id"] = ficha_id
    if otra is not None:
        cambios["otra_ficha_id"] = otra
    if solo_contar:
        mandaria.append({"tabla": _base.T_BANDEJA_PERSONAS, "metodo": "PATCH", "cuerpo": dict(cambios, Id=fila["Id"])})
        return dict(fila, **cambios)
    try:
        _base.nc("PATCH", f"/api/v2/tables/{_base.T_BANDEJA_PERSONAS}/records", body=dict(cambios, Id=fila["Id"]))
        if escribe:                                           # escribiendo, la fila no dice `aplicado` si al releerla no dice TODO lo que se escribió en ella (el `resultado` también)
            apuntada = personas._entrada_leer_fila(fila["Id"])
            if apuntada is None or any(apuntada.get(k) != v for k, v in cambios.items()):
                raise _EntradaSinConfirmar()
    except Exception as e:                                    # noqa: BLE001
        _entrada_registrar(fila, "sin_confirmar", resumen, ficha_id, _base._resumen_del_fallo(e), modo)
        raise _EntradaSinConfirmar() from e
    _entrada_registrar(fila, estado, resumen, ficha_id, modo=modo)
    return dict(fila, **cambios)


def _entrada_estados_que_procesa():
    """Los estados de fila que la entrada procesa en el modo de ahora: contando, `pendiente`; escribiendo, también la que ya lleva la marca `escribiendo` (se reanuda)."""
    return ("pendiente", ENTRADA_ESTADO_ESCRIBIENDO) if entrada_modo() == "escribir" else ("pendiente",)


def entrada_barrer(tope):
    """Procesa hasta `tope` filas con `Id` mayor que el último intentado (al llegar al final vuelve a empezar); devuelve las filas apuntadas por su `Id`.
    Contando mira solo las `pendiente` (una sola lectura, como siempre); escribiendo también las marcadas `escribiendo`."""
    hechas = {}
    estados = _entrada_estados_que_procesa()
    try:
        filas = []
        for estado in estados:
            lista = personas._entrada_lista_pendientes(estado, _ENTRADA_CURSOR[0], tope)
            filas += [f for f in ((lista.get("list") if isinstance(lista, dict) else None) or []) if isinstance(f, dict) and _entrada_id(f.get("Id")) is not None]
        filas = sorted(filas, key=lambda f: f["Id"])[:int(tope)]
    except Exception as e:                                    # noqa: BLE001
        print("[ENTRADA-FICHAS] barrido sin leer la bandeja fallo=%s" % _base._resumen_del_fallo(e))
        return hechas
    _ENTRADA_CURSOR[0] = filas[-1]["Id"] if len(filas) >= tope else 0
    for pendiente in filas:
        with _ENTRADA_LOCK:
            try:
                fila = personas._entrada_leer_fila(pendiente["Id"])
                if fila is not None and fila.get("estado") in estados:
                    hechas[fila["Id"]] = entrada_procesar(fila)
            except _EntradaSinConfirmar:
                pass
    return hechas


def entrada_fichas(fila_id):
    """La entrada de Natalia: barre pendientes y cuenta la fila pedida. Devuelve `(código HTTP, cuerpo)`; todo error lleva texto fijo."""
    try:
        hechas = entrada_barrer(ENTRADA_TOPE_BARRIDO)
        if fila_id in hechas:
            return 200, _entrada_cuerpo(hechas[fila_id])
        with _ENTRADA_LOCK:
            fila = personas._entrada_leer_fila(fila_id)
            if fila is None:
                return 404, {"error": "fila_inexistente"}
            if fila.get("estado") in ("pendiente", ENTRADA_ESTADO_ESCRIBIENDO):      # contando, una marcada levanta `_EntradaAMedias` (409); escribiendo, se reanuda
                fila = entrada_procesar(fila)
            return 200, _entrada_cuerpo(fila)
    except _EntradaResultadoIlegible:
        return 422, {"error": "resultado_ilegible"}
    except _EntradaAMedias:
        return 409, {"error": "escritura_a_medias"}
    except _EntradaSinConfirmar:
        return 502, {"error": "sin_confirmar"}
    except Exception as e:                                    # noqa: BLE001
        print("[ENTRADA-FICHAS] fila=%s estado=sin_confirmar fallo=%s" % (fila_id, _base._resumen_del_fallo(e)))
        return 502, {"error": "sin_confirmar"}


def entrada_calculada(fila_id):
    """EL CÁLCULO DE LA ENTRADA (contar; P11-6, grupo b): lo que `entrada_fichas(fila_id)` mandaría a la bandeja, sin mandarlo. Recorre lo
    mismo que la entrada: barre las pendientes (hasta el tope, en orden de Id) y luego la fila pedida si el barrido no la tocó. No toca el
    cursor (`_ENTRADA_CURSOR` es de la App, otro proceso). Si el barrido llega al tope, el cursor de la App puede saltar filas: 409 `barrido_lleno`."""
    mandaria = []
    try:
        lista = personas._entrada_lista_pendientes("pendiente", 0, ENTRADA_TOPE_BARRIDO)
        filas = [f for f in ((lista.get("list") if isinstance(lista, dict) else None) or []) if isinstance(f, dict) and _entrada_id(f.get("Id")) is not None]
        filas = sorted(filas, key=lambda f: f["Id"])[:ENTRADA_TOPE_BARRIDO]
        if len(filas) >= ENTRADA_TOPE_BARRIDO:
            return 409, {"error": "barrido_lleno"}
        tocadas = set()
        for pendiente in filas:
            fila = personas._entrada_leer_fila(pendiente["Id"])
            if fila is not None and fila.get("estado") == "pendiente":
                try:
                    entrada_procesar(fila, solo_contar=True, mandaria=mandaria)
                except _EntradaSinConfirmar:
                    pass                                  # como el barrido de la entrada: esa fila no sale, y sigue
                tocadas.add(fila["Id"])
        if fila_id not in tocadas:
            fila = personas._entrada_leer_fila(fila_id)
            if fila is None:
                return 404, {"error": "fila_inexistente"}
            if fila.get("estado") == ENTRADA_ESTADO_ESCRIBIENDO:
                return 409, {"error": "escritura_a_medias"}
            if fila.get("estado") == "pendiente":
                entrada_procesar(fila, solo_contar=True, mandaria=mandaria)
        return 200, {"ok": True, "estado": "calculado", "escrituras": mandaria}
    except _EntradaSinConfirmar:
        return 502, {"error": "sin_confirmar"}
    except Exception:                                     # noqa: BLE001
        return 502, {"error": "sin_confirmar"}


def _entrada_planear_escribir(fila, mandaria):
    """Lo que `entrada_procesar` (modo escribir) mandaría para una fila pendiente o marcada, SIN mandarlo (P11-entrada-escribir): la marca
    `escribiendo` si la fila no la lleva, lo que la puerta escribiría (`recibir_y_unir(planeados=...)`) y el PATCH final, en ese orden. No
    relee ni comprueba lo releído (no se escribió nada): lo que la escritura confirmaría se da por escrito. Un resultado que la escritura
    dejaría sin confirmar, o cualquier aviso, levanta `personas.SinCalculoDeEntrada`."""
    if fila.get("estado") != ENTRADA_ESTADO_ESCRIBIENDO:
        mandaria.append({"tabla": _base.T_BANDEJA_PERSONAS, "metodo": "PATCH", "cuerpo": {"Id": fila["Id"], "estado": ENTRADA_ESTADO_ESCRIBIENDO}})
        fila = dict(fila, estado=ENTRADA_ESTADO_ESCRIBIENDO)
    if fila.get("origen") in _base.ENTRADA_ORIGENES:
        r = personas.recibir_y_unir(_entrada_dato(fila), planeados=mandaria)
    else:
        r = {"estado": "rechazado", "accion": "no_tocada", "caso": "ninguna:origen_desconocido", "valores": {}, "avisos": []}
    estado = "descartado" if r.get("estado") == "rechazado" else r.get("estado")
    if estado not in ("descartado", "aplicado"):
        raise personas.SinCalculoDeEntrada("estado_no_predecible")
    resumen = _entrada_resumen(r, "escribir")
    ficha = r.get("ficha_id")
    ficha_id = personas.CALCULO_FICHA_NUEVA if ficha == personas.CALCULO_FICHA_NUEVA else _entrada_id(ficha)
    if ficha_id is None and estado == "aplicado":
        raise personas.SinCalculoDeEntrada("aplicado_sin_ficha")
    cambios = {"estado": estado, "resultado": json.dumps(resumen, sort_keys=True, ensure_ascii=True)}
    if ficha_id is not None:
        cambios["ficha_id"] = ficha_id
    mandaria.append({"tabla": _base.T_BANDEJA_PERSONAS, "metodo": "PATCH", "cuerpo": dict(cambios, Id=fila["Id"])})


def entrada_calculada_escribir(fila_id):
    """EL CÁLCULO DE LA ENTRADA CON EL MODO `escribir` (P11-entrada-escribir): lo que `entrada_fichas(fila_id)` escribiría con esta bandeja, sin
    escribir nada. Recorre lo mismo que el barrido de la entrada (las `pendiente` y las marcadas `escribiendo`, hasta el tope, en orden de Id)
    y luego la fila pedida si el barrido no la tocó. Solo predice lo que puede: UNA fila procesada, sin unión empezada ni aviso
    (`personas.SinCalculoDeEntrada` → 409 `no_se_calcula_en_escribir`). Dos o más filas procesadas → 409 `varias_filas_no_se_calculan`: la
    segunda vería lo que la primera escribió, y el cálculo no lo ve. Cursor 0, como `entrada_calculada`."""
    try:
        filas = []
        for estado in ("pendiente", ENTRADA_ESTADO_ESCRIBIENDO):
            lista = personas._entrada_lista_pendientes(estado, 0, ENTRADA_TOPE_BARRIDO)
            filas += [f for f in ((lista.get("list") if isinstance(lista, dict) else None) or []) if isinstance(f, dict) and _entrada_id(f.get("Id")) is not None]
        filas = sorted(filas, key=lambda f: f["Id"])[:ENTRADA_TOPE_BARRIDO]
        if len(filas) >= ENTRADA_TOPE_BARRIDO:
            return 409, {"error": "barrido_lleno"}
        procesadas = []
        for pendiente in filas:
            fila = personas._entrada_leer_fila(pendiente["Id"])
            if fila is not None and fila.get("estado") in ("pendiente", ENTRADA_ESTADO_ESCRIBIENDO):
                procesadas.append(fila["Id"])
        if fila_id not in procesadas:
            fila = personas._entrada_leer_fila(fila_id)
            if fila is None:
                return 404, {"error": "fila_inexistente"}
            if fila.get("estado") in ("pendiente", ENTRADA_ESTADO_ESCRIBIENDO):
                procesadas.append(fila_id)
        if len(procesadas) > 1:
            return 409, {"error": "varias_filas_no_se_calculan"}
        mandaria = []
        for id_fila in procesadas:
            _entrada_planear_escribir(personas._entrada_leer_fila(id_fila), mandaria)
        return 200, {"ok": True, "estado": "calculado", "escrituras": mandaria}
    except personas.SinCalculoDeEntrada:
        return 409, {"error": "no_se_calcula_en_escribir"}
    except Exception:                                     # noqa: BLE001
        return 502, {"error": "sin_confirmar"}


def entrada_de_natalia(pedido):
    """`POST /api/servicio/personas/entrada`, después de la llave (que mira `servidor.py`). Devuelve `(código, cuerpo)`.

    Mismo orden que la App después de su llave: la forma del pedido (`{"fila": n}`, solo esa clave, `n` entero mayor que 0), la bandeja
    configurada (`NOCODB_T_BANDEJA_PERSONAS`, o 503), la entrada, y al final el contador de escrituras se pone en cero (como la App: el
    texto de los errores de esta ruta no se reescribe por las escrituras de la bandeja que ya hizo)."""
    fila = pedido.get("fila") if isinstance(pedido, dict) and set(pedido) == {"fila"} else None
    if not isinstance(fila, int) or isinstance(fila, bool) or fila < 1:
        return 400, {"error": "pedido_ilegible"}
    if not _base.T_BANDEJA_PERSONAS:
        return 503, {"error": "sin_bandeja"}
    codigo, cuerpo = entrada_fichas(fila)
    _base.estrenar_la_cuenta_de_escrituras()
    return codigo, cuerpo
