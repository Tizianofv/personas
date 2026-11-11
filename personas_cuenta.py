# -*- coding: utf-8 -*-
"""EL CÁLCULO DEL MODO QUE SOLO CUENTA DE PERSONAS (P11-5 y P11-6a, `disenos/personas-programa-aparte/P11-CONTAR.md`, sección 5).

  POST /calcular/<nombre>   cabeceras X-Personas-Cuenta-Llave (PERSONAS_CUENTA_LLAVE) y X-Personas-Cuenta-Quien

La App le pide a este proceso lo que una escritura escribiría, SIN escribir, para compararlo con lo que la App manda a NocoDB
(P11-4, `registro/server.py`, `_resultado_de_la_cuenta`). Contrato (el de la App, leído en su código, `panel_reenvio.calcular_personas`):

  entrada  el cuerpo de la escritura MÁS la clave `ruta_de_la_escritura` (la ruta con las ids: las ids van en la RUTA, no en el cuerpo)
  salida   {"ok": true, "estado": "calculado", "escrituras": [{"tabla", "metodo", "enlace": null, "valores": {columna: valor}}, ...],
            "sin_valor": ["<tabla>.<METODO>.<columna>", ...]}
           · `tabla` es el NOMBRE LÓGICO de la App (`personas`, `anotaciones`, `bandeja`, `uniones`, `quitadas`, `asistencias`,
             `mercadeo_envios`), no el id de NocoDB.
           · una fila por registro; `valores` sin la columna `Id` (la App no la compara).
           · `sin_valor` marca lo que la App no puede saber antes: el número que asigna la base a un alta (en la columna que lo lleva,
             `<nueva>`) y las columnas que salen del reloj (`COLUMNAS_DEL_RELOJ`). La App las compara solo por existencia.

Una `una_vez` no se calcula: la App pide el cálculo SOLO cuando va a escribir de verdad (su `escribir_una_vez` no llama a la
escritura ante un reenvío repetido, y el cálculo sale dentro de la escritura). Este cálculo no guarda memoria propia: lo que dice es lo que
la escritura escribiría la primera vez. No tira las memorias de lectura del programa: `resolver` y `reabrir` deciden con la lista
del portal (30 s, `PORTAL_CACHE_SEG` en `personas.py`), que la escritura sí tira antes de leer; con esa lista cargada, el cálculo puede
decir algo distinto de lo que escribiría la escritura. Si la App pidiera el cálculo de un envío repetido, la
comparación saldría `no_comparado la_app_no_escribio` por no haber capturado escrituras, no por este cálculo.

Reglas que valen para TODO cálculo. La prueba `tests/test_calcular_cuenta.py` vigila solo una cosa: que no salga ningún pedido HTTP
a NocoDB (el doble cuenta todos los métodos). No vigila otras escrituras (archivos, procesos ajenos, otros servicios).
  · un cálculo nunca manda a NocoDB un pedido de escritura (POST, PATCH, DELETE o PUT): devuelve la forma de la escritura, sin mandarla;
  · la llave y la identidad las mira `servidor.py` ANTES de leer el cuerpo y antes de NocoDB;
  · el cuerpo que no es un objeto JSON se rechaza con 400 antes de buscar el cálculo, como las rutas hermanas;
  · la ruta de la escritura tiene que ser la de su nombre (`RUTAS`); si no, 400 y no se calcula nada.
"""

import re

import base as _base
import personas
import personas_entrada
import personas_escrituras
import personas_portal_escritura

ERROR_SIN_CALCULO = {"error": "sin cálculo para esa escritura"}
ERROR_PEDIDO_ILEGIBLE = {"error": "pedido ilegible. No se calculó nada."}
ERROR_FALLO_DEL_CALCULO = {"error": "el cálculo falló. No se calculó nada."}
ERROR_SIN_RUTA = {"error": "falta la ruta de la escritura. No se calculó nada."}
ERROR_RUTA_AJENA = {"error": "la ruta no es la de esta escritura. No se calculó nada."}

CLAVE_RUTA = "ruta_de_la_escritura"

# Columnas que salen del reloj (la App y el programa las escriben en momentos distintos): la App las compara solo por existencia.
# La prueba `tests/test_contrato_app_p11.py` comprueba con dos relojes distintos que esta lista cubre todo lo que cambia.
COLUMNAS_DEL_RELOJ = frozenset({"anotaciones.POST.cuando", "anotaciones.POST.dicho_el",
                                # P11-6e: la hora de un borrado, una devolución y una marca de «Por resolver» (la escritura la pone con `_ahora_utc()`)
                                "quitadas.POST.creada_en", "personas.PATCH.quitada_el", "quitadas.PATCH.devuelta_en",
                                "bandeja.POST.resuelto_en", "bandeja.PATCH.resuelto_en",
                                # P11-6f: la hora en que `unir` abre el registro de la unión y la hora en que la marca «unida»
                                "uniones.POST.creada_en", "uniones.PATCH.terminada_en"})

# Nombre de la escritura -> (método, ruta). Los nombres y las rutas son los de `PERSONAS_PORTAL_ESCRITURAS` y
# `PERSONAS_APRENDIZAJE_ESCRITURAS` de la App (`registro/panel_reenvio.py`, `3ffe870` y `cafe2a3`). La prueba de contrato los compara
# con la función de la App `escritura_de_personas_para_cuenta`.
_DIRECCION = r"(\d{1,9})"
_IDENTIDAD = r"(\d+|[A-Za-z]{2}\.[A-Za-z0-9]{1,128})"
RUTAS = {
    "crear": ("POST", re.compile(r"/api/portal-personas")),
    "editar": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/editar")),
    "crear_checkin": ("POST", re.compile(r"/api/personas")),
    "editar_checkin": ("PATCH", re.compile(r"/api/personas/" + _DIRECCION)),
    "editar_aprendizaje": ("POST", re.compile(r"/api/aprendizaje/fichas/" + _IDENTIDAD + r"/editar")),
    "entrada": ("POST", re.compile(r"/api/fichas/entrada")),
    "cara": ("POST", re.compile(r"/api/personas/" + _DIRECCION + r"/cara")),
    "permiso": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/permiso")),
    "baja": ("POST", re.compile(r"/api/servicio/mercadeo/baja")),
    "foto": ("POST", re.compile(r"/api/servicio/mercadeo/foto")),
    "resolver": ("POST", re.compile(r"/api/portal-personas/por-resolver/resolver")),
    "reabrir": ("POST", re.compile(r"/api/portal-personas/por-resolver/reabrir")),
    "borrar": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/borrar")),
    "devolver": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/devolver")),
    "unir": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/unir")),
    "continuar": ("POST", re.compile(r"/api/portal-personas/" + _DIRECCION + r"/unir/continuar")),
}


# ---------- P11-6, grupo (a): las escrituras de la ficha (crear, editar, alta y edición del check-in, aprendizaje) ----------
#
# Cada función llama a la MISMA función de escritura con `solo_contar=True`: la decisión, la validación y los rechazos son los de la
# escritura. Lo que devuelve (`escrituras`, en forma de NocoDB) lo convierte `calcular` al contrato de la App.
# La prueba de pareja (`tests/test_calcular_grupo_a.py`) exige que coincida con lo que la escritura mandó de verdad.


def _envuelto(calcular):
    """Lo que `_responder_de_sesion` hace con los errores de la escritura, para que el cálculo dé lo mismo: `PersonaRechazada` su código
    y datos; `ValueError` 400 con su texto; cualquier otro error 500 SIN su texto (el cálculo no lo saca al cliente)."""
    try:
        return calcular()
    except _base.SoloLectura:
        raise
    except personas_escrituras.PersonaRechazada as e:
        return e.codigo, e.datos
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception:  # noqa: BLE001
        return 500, dict(ERROR_FALLO_DEL_CALCULO)


def _calc_crear(cuerpo, quien, _direccion):
    return _envuelto(lambda: personas.crear_persona_portal(cuerpo, quien, solo_contar=True))


def _calc_editar(cuerpo, quien, direccion):
    pid = int(direccion)
    # La escritura exige `id` en el cuerpo igual a la ficha: lo pone la ruta. Un `id` del cuerpo que no es esa ficha se rechaza.
    if "id" in cuerpo and cuerpo["id"] not in (pid, str(pid)):
        return 400, {"error": "la ficha del cuerpo no es la de la ruta. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    return _envuelto(lambda: personas.editar_persona_portal(pid, dict(cuerpo, id=pid), quien, solo_contar=True))


def _calc_crear_checkin(cuerpo, quien, _direccion):
    return _envuelto(lambda: _calculo_del_checkin(personas_escrituras.crear_persona(cuerpo, solo_contar=True), 201))


def _calc_editar_checkin(cuerpo, quien, direccion):
    pid = int(direccion)
    datos = {k: v for k, v in cuerpo.items() if k != "id"}
    if "id" in cuerpo and cuerpo["id"] not in (pid, str(pid)):
        return 400, {"error": "la ficha del cuerpo no es la de la ruta. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    return _envuelto(lambda: _calculo_del_checkin(personas_escrituras.editar_persona(pid, datos, solo_contar=True), 200))


def _calc_editar_aprendizaje(cuerpo, quien, direccion):
    if not isinstance(direccion, str) or not direccion.strip():
        return 400, {"error": "falta la identidad de la ficha. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    if "identidad" in cuerpo and cuerpo["identidad"] != direccion:
        return 400, {"error": "la identidad del cuerpo no es la de la ruta. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    resto = {k: v for k, v in cuerpo.items() if k != "identidad"}
    return _envuelto(lambda: personas.editar_ficha_cliente(direccion, resto, quien, solo_contar=True))


def _calculo_del_checkin(r, codigo):
    return personas.calculo_de_escrituras(r["_calculo"], codigo)


# ---------- P11-6, grupo (b): la entrada de Natalia (fila 14). El cuerpo es `{"fila": n}`; la App la compara en su modo contar. ----------


def _calc_entrada(cuerpo, quien, _direccion):
    """Lo que la entrada (`entrada_fichas`, modo contar) mandaría a la bandeja: `personas_entrada.entrada_calculada`. Con el modo `escribir`
    del programa no se calcula (escribir en las fichas no se predice aquí)."""
    if set(cuerpo) != {"fila"}:
        return 400, {"error": "pedido_ilegible"}
    fila = cuerpo["fila"]
    if not isinstance(fila, int) or isinstance(fila, bool) or fila < 1:
        return 400, {"error": "pedido_ilegible"}
    if not _base.T_BANDEJA_PERSONAS:
        return 503, {"error": "sin_bandeja"}
    if personas_entrada.entrada_modo() == personas_entrada.ENTRADA_MODO_ESCRIBIR:
        return 409, {"error": "modo_escribir_no_se_calcula"}
    return personas_entrada.entrada_calculada(fila)


# ---------- P11-6, grupo (c): la cara (fila 17). El cuerpo es `{"cara": <base64 de 128 float32>}`; la App la escribe en contar y la compara. ----------


def _calc_cara(cuerpo, quien, direccion):
    """Lo que la escritura de servicio de la cara (`personas_escritura_rutas.cara`) escribiría, sin el PATCH: `personas.cara_calculada`.
    La cara llega en base64, como la manda la App; la ficha, de la ruta. Mismas guardas y mismos textos que la escritura: la prueba
    `tests/test_calcular_grupo_c.py` los compara con ella, y con la escritura de la App no hay más contrato que el de `_contrato`."""
    if set(cuerpo) != {"cara"}:
        return 400, {"ok": False, "error": "El pedido de cara es {persona_id: entero, vec: [números]}."}
    pid = int(direccion)
    if pid < 1:
        return 400, {"ok": False, "error": "El pedido de cara es {persona_id: entero, vec: [números]}."}
    vec = _base._cara_desde_base64(cuerpo["cara"])
    if vec is None:
        return 400, {"ok": False, "error": "vec son %d números." % _base.CARA_DIMS}
    try:
        _ranuras, patch = personas.cara_calculada(pid, vec)
    except (_base.FichaUnida, _base.FichaQuitada):
        return 409, {"ok": False, "error": "La ficha está unida o guardada aparte: no admite cambio de cara. No se guardó."}
    except Exception:  # noqa: BLE001 — como la escritura: cualquier fallo de la base es «no se guardó», sin su texto
        return 502, {"ok": False, "error": "No se guardó. Personas no responde. Inténtalo en un momento."}
    return 200, {"escrituras": [{"tabla": _base.T_PERSONAS, "metodo": "PATCH", "cuerpo": patch}]}


# ---------- P11-6, grupo (d): el permiso, la baja y la foto (filas 3, 15 y 16). Cada escritura va con `solo_contar=True`: la misma decisión y los
# mismos rechazos, y en vez de cada POST, el renglón que mandaría (`personas._planear_renglones`). La baja y la foto recorren las fichas de la
# identidad; el permiso, las del grupo de la ficha. La ruta de la baja y de la foto es la de la App (`/api/servicio/mercadeo/...`).


def _calculo_de_anotacion(r):
    """Lo que contesta la escritura con `solo_contar`: si trae `escrituras` (éxito, 200), es un cálculo; los rechazos pasan tal cual."""
    codigo, datos = r
    if codigo == 200 and isinstance(datos, dict) and "escrituras" in datos:
        return personas.calculo_de_escrituras(datos["escrituras"], 200)
    return codigo, datos


def _calc_permiso(cuerpo, quien, direccion):
    pid = int(direccion)
    return _envuelto(lambda: _calculo_de_anotacion(personas.anotar_permiso(pid, cuerpo, quien, solo_contar=True)))


def _calc_baja(cuerpo, quien, _direccion):
    return _envuelto(lambda: _calculo_de_anotacion(personas.baja_de_natalia(cuerpo, solo_contar=True)))


def _calc_foto(cuerpo, quien, _direccion):
    return _envuelto(lambda: _calculo_de_anotacion(personas.foto_de_natalia(cuerpo, solo_contar=True)))


# ---------- P11-6, grupo (e): resolver y reabrir (la bandeja de «Por resolver', filas 4 y 5), borrar y devolver (filas 9 y 10). Cada función de
# escritura corre con `solo_contar=True` y `planeados`: la decisión y los rechazos son los de la escritura; las escrituras que mandaría quedan
# en `planeados`, en orden, y ninguna sale a NocoDB. Si la escritura contesta 200, el cálculo son esas escrituras; si no, su código y su cuerpo.


def _calculo_de_planeados(funcion):
    planeados = []
    codigo, datos = funcion(planeados)
    if codigo == 200:
        return personas.calculo_de_escrituras(planeados, 200)
    return codigo, datos


def _calc_resolver(cuerpo, quien, _direccion):
    clave = cuerpo.get("clave")
    return _envuelto(lambda: _calculo_de_planeados(
        lambda p: personas.portal_por_resolver_marcar(clave, quien, reabrir=False, solo_contar=True, planeados=p)))


def _calc_reabrir(cuerpo, quien, _direccion):
    clave = cuerpo.get("clave")
    return _envuelto(lambda: _calculo_de_planeados(
        lambda p: personas.portal_por_resolver_marcar(clave, quien, reabrir=True, solo_contar=True, planeados=p)))


def _calc_borrar(cuerpo, quien, direccion):
    pid, clave = int(direccion), cuerpo.get("clave")
    return _envuelto(lambda: _calculo_de_planeados(
        lambda p: personas.quitar_ficha(pid, clave, quien, solo_contar=True, planeados=p)))


def _calc_devolver(cuerpo, quien, direccion):
    pid = int(direccion)
    return _envuelto(lambda: _calculo_de_planeados(
        lambda p: personas.devolver_ficha(pid, quien, solo_contar=True, planeados=p)))


# ---------- P11-6, grupo (f): unir (fila 6) y continuar (fila 7). `deshacer` va en su encargo aparte.
# `unir_fichas` corre con `solo_contar=True` y `planeados`: la decisión, las lecturas y los rechazos son los de la unión; las escrituras
# (la fila del registro, los movimientos de asistencias y de enlaces una persona por pedido, y las dos fichas) quedan en `planeados`, en orden.
# Lo que NO se predice (la base lo decide al escribir): crear una asistencia nueva (su Id es el registro de sus enlaces), una unión que
# había quedado a medias, un aviso de «Por resolver» (marca la bandeja) y una parada o un fallo después de planear. Esos contestan 404
# «sin cálculo», y la App los lee como `sin_calculo`.
# `continuar` (P11-6f, fila 7) usa la misma `_union_correr`: lee el registro en curso y no escribe la fila del registro. Además, si la ficha
# que sobra tiene algo fuera del plan guardado, contesta «sin cálculo» (`plan_incompleto`), porque la unión haría una pasada más.


def _calc_unir(cuerpo, quien, direccion):
    ficha = int(direccion)

    def calcular():
        try:
            return _calculo_de_planeados_de_union(lambda p: personas_portal_escritura._unir(ficha, cuerpo, quien, solo_contar=True, planeados=p))
        except personas.SinCalculoDeUnion:
            return 404, dict(ERROR_SIN_CALCULO)
    return _envuelto(calcular)


def _calc_continuar(cuerpo, quien, direccion):
    ficha = int(direccion)

    def calcular():
        try:
            return _calculo_de_planeados_de_union(lambda p: personas_portal_escritura._continuar(ficha, cuerpo, quien, solo_contar=True, planeados=p))
        except personas.SinCalculoDeUnion:
            return 404, dict(ERROR_SIN_CALCULO)
    return _envuelto(calcular)


def _calculo_de_planeados_de_union(funcion):
    planeados = []
    codigo, datos = funcion(planeados)
    if codigo == 200:
        return personas.calculo_de_escrituras(planeados, 200)
    return codigo, datos


# Cálculos registrados: nombre -> función `(cuerpo, quien, direccion) -> (codigo, cuerpo)`. Los nombres son los de `RUTAS`.
CALCULOS = {
    "unir": _calc_unir,
    "continuar": _calc_continuar,
    "crear": _calc_crear,
    "editar": _calc_editar,
    "crear_checkin": _calc_crear_checkin,
    "editar_checkin": _calc_editar_checkin,
    "editar_aprendizaje": _calc_editar_aprendizaje,
    "cara": _calc_cara,
    "entrada": _calc_entrada,
    "permiso": _calc_permiso,
    "baja": _calc_baja,
    "foto": _calc_foto,
    "resolver": _calc_resolver,
    "reabrir": _calc_reabrir,
    "borrar": _calc_borrar,
    "devolver": _calc_devolver,
}


def _nombre_logico(tabla_id):
    """El nombre que la App usa para una tabla de Personas (`_NOMBRES_DE_TABLAS_DE_PERSONAS` de la App). Una tabla que no está en la lista
    es un error del cálculo: la App la contaría como `escribio_fuera_de_la_captura`, y no hay forma honesta de calcularla."""
    tablas = {_base.T_PERSONAS: "personas", _base.T_PERSONAS_ANOTACIONES: "anotaciones", _base.T_BANDEJA_PERSONAS: "bandeja",
              _base.T_UNIONES_PERSONAS: "uniones", _base.T_PERSONAS_QUITADAS: "quitadas", _base.T_ASISTENCIAS: "asistencias",
              _base.T_MERCADEO_ENVIOS: "mercadeo_envios",
              # P11-6f: solo los enlaces que `unir` escribe desde estas tablas (la App las nombra así en la captura de enlaces)
              _base.T_SESIONES: "sesiones", _base.T_PROYECTOS: "proyectos"}
    nombre = tablas.get(tabla_id) if tabla_id else None
    if nombre is None:
        raise RuntimeError("tabla de Personas sin nombre lógico")
    return nombre


def _en_forma_de_la_app(escrituras):
    """Las escrituras que la escritura mandaría (en forma de NocoDB: tabla con id, método, cuerpo) -> el contrato de la App:
    `(filas, sin_valor)`. Una fila por registro; sin la columna `Id`; el número de una alta y lo que sale del reloj, en `sin_valor`."""
    filas, sin_valor = [], set()
    for e in escrituras:
        tabla, metodo = _nombre_logico(e["tabla"]), str(e["metodo"]).strip().upper()
        if e.get("enlace"):
            # P11-6f: un enlace (`enlace:L_…`) va con UNA fila por pedido, su registro y sus ligados, como lo compara la App (regla única).
            # Sin `Id` en los valores de un registro, sin `sin_valor`: su `registro` es el Id de la ruta, que el cálculo ya conoce.
            filas.append({"tabla": tabla, "metodo": metodo, "enlace": e["enlace"],
                          "valores": {"registro": e["registro"], "ligados": sorted(e["ligados"])}})
            continue
        cuerpo = e.get("cuerpo")
        registros = cuerpo if isinstance(cuerpo, list) else [cuerpo]
        if metodo == "POST":
            sin_valor.add("%s.%s.Id" % (tabla, metodo))         # el número que asigna la base: la App no lo sabe antes
        for reg in registros:
            valores = {k: v for k, v in reg.items() if k != "Id"}
            for columna, valor in valores.items():
                clave = "%s.%s.%s" % (tabla, metodo, columna)
                if (isinstance(valor, str) and personas.CALCULO_FICHA_NUEVA in valor) or clave in COLUMNAS_DEL_RELOJ:
                    sin_valor.add(clave)
            filas.append({"tabla": tabla, "metodo": metodo, "enlace": None, "valores": valores})
    return filas, sorted(sin_valor)


def _contrato(codigo, datos):
    """Lo que `calcular` contesta: si el cálculo dice escrituras, en forma de la App; lo demás (rechazos) tal cual."""
    if codigo in (200, 201) and isinstance(datos, dict) and "escrituras" in datos:
        # Un cálculo exitoso contesta SIEMPRE 200 (es un cálculo, no una creación: el cliente de la App solo lee el 200).
        filas, sin_valor = _en_forma_de_la_app(datos["escrituras"])
        return 200, {"ok": True, "estado": "calculado", "escrituras": filas, "sin_valor": sin_valor}
    return codigo, datos


def calcular(nombre, cuerpo, quien):
    """`POST /calcular/<nombre>` -> `(codigo, cuerpo)`. Ya pasaron la llave y la identidad (las mira `servidor.py`).
    `cuerpo` trae `ruta_de_la_escritura`: de ahí salen las ids (la escritura las pide en el cuerpo, la App no)."""
    if not isinstance(cuerpo, dict):
        return 400, dict(ERROR_PEDIDO_ILEGIBLE)
    funcion = CALCULOS.get(nombre)
    if funcion is None:
        return 404, dict(ERROR_SIN_CALCULO)
    if CLAVE_RUTA not in cuerpo:
        return 400, dict(ERROR_SIN_RUTA)
    ruta = cuerpo[CLAVE_RUTA]
    cuerpo = {k: v for k, v in cuerpo.items() if k != CLAVE_RUTA}
    verbo, patron = RUTAS[nombre]
    m = patron.fullmatch(ruta) if isinstance(ruta, str) else None
    if m is None:
        return 400, dict(ERROR_RUTA_AJENA)
    direccion = m.group(1) if m.groups() else None
    return _contrato(*funcion(cuerpo, quien, direccion))
