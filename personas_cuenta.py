# -*- coding: utf-8 -*-
"""EL CÁLCULO DEL MODO QUE SOLO CUENTA DE PERSONAS (P11-5, `disenos/personas-programa-aparte/P11-CONTAR.md`, sección 5).

  POST /calcular/<nombre>   cabeceras X-Personas-Cuenta-Llave (PERSONAS_CUENTA_LLAVE) y X-Personas-Cuenta-Quien

La App le pide a este proceso lo que una escritura escribiría, SIN escribir, para compararlo con lo que la App manda a NocoDB
(P11-4). `CALCULOS` tiene el grupo (a) de P11-6 (crear, editar, alta y edición del check-in, aprendizaje); cualquier otro `<nombre>`
contesta 404 (el cliente de la App, `panel_reenvio.calcular_personas`, lo lee como `sin_calculo`). Los demás grupos se registran aquí, uno
por uno, cada uno con su prueba de pareja.

Reglas que valen para TODO cálculo. La prueba `tests/test_calcular_cuenta.py` vigila solo una cosa: que no salga ningún pedido HTTP
a NocoDB (el doble cuenta todos los métodos). No vigila otras escrituras (archivos, procesos ajenos, otros servicios).
  · un cálculo nunca manda a NocoDB un pedido de escritura (POST, PATCH, DELETE o PUT): devuelve la forma de la escritura, sin mandarla;
  · la llave y la identidad las mira `servidor.py` ANTES de leer el cuerpo y antes de NocoDB;
  · el cuerpo que no es un objeto JSON se rechaza con 400 antes de buscar el cálculo, como las rutas hermanas.
"""

import base as _base
import personas
import personas_escrituras

ERROR_SIN_CALCULO = {"error": "sin cálculo para esa escritura"}
ERROR_PEDIDO_ILEGIBLE = {"error": "pedido ilegible. No se calculó nada."}
ERROR_FALLO_DEL_CALCULO = {"error": "el cálculo falló. No se calculó nada."}


# ---------- P11-6, grupo (a): las escrituras de la ficha (crear, editar, alta y edición del check-in, aprendizaje) ----------
#
# Cada función llama a la MISMA función de escritura con `solo_contar=True`: la decisión, la validación y los rechazos son los de la
# escritura, y lo que se devuelve en `escrituras` es lo que la escritura mandaría a NocoDB (tabla, método y cuerpo), sin mandarlo.
# La prueba de pareja (`tests/test_calcular_grupo_a.py`) exige que coincida con lo que la escritura mandó de verdad.
#
# Nombres: los de `PERSONAS_PORTAL_ESCRITURAS` y `PERSONAS_APRENDIZAJE_ESCRITURAS` de la App (`registro/panel_reenvio.py`):
#   crear           POST /api/portal-personas              (y la fila 1 de P11-6)
#   editar          POST /api/portal-personas/<id>/editar  (fila 2; la fila 18, precio de Proveedores, va por esta misma ruta)
#   crear_checkin   POST /api/personas                     (fila 11)
#   editar_checkin  PATCH /api/personas/<id>               (fila 12)
#   editar_aprendizaje  POST /api/aprendizaje/fichas/<identidad>/editar   (fila 13)
# La dirección (`<id>` o `<identidad>`) no va en el cuerpo de la escritura: el cálculo la lee del cuerpo como `id` o `identidad`, y
# `personas_cuenta` la quita antes de pasar el resto. La App tiene que mandarla así (ver `P11-6` en el mapa del programa).


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


def _id_de(cuerpo):
    """El `Id` que el cálculo lee del cuerpo (`None` si no es un entero de verdad)."""
    pid = cuerpo.get("id")
    return None if isinstance(pid, bool) or not isinstance(pid, int) else pid


def _calc_crear(cuerpo, quien):
    return _envuelto(lambda: personas.crear_persona_portal(cuerpo, quien, solo_contar=True))


def _calc_editar(cuerpo, quien):
    pid = _id_de(cuerpo)
    if pid is None:
        return 400, {"error": "falta el número de la ficha. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    return _envuelto(lambda: personas.editar_persona_portal(pid, cuerpo, quien, solo_contar=True))


def _calc_crear_checkin(cuerpo, quien):
    def calcular():
        r = personas_escrituras.crear_persona(cuerpo, solo_contar=True)
        return personas.calculo_de_escrituras(r["_calculo"], 201)
    return _envuelto(calcular)


def _calc_editar_checkin(cuerpo, quien):
    pid = _id_de(cuerpo)
    if pid is None:
        return 400, {"error": "falta el número de la ficha. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    datos = {k: v for k, v in cuerpo.items() if k != "id"}

    def calcular():
        r = personas_escrituras.editar_persona(pid, datos, solo_contar=True)
        return personas.calculo_de_escrituras(r["_calculo"], 200)
    return _envuelto(calcular)


def _calc_editar_aprendizaje(cuerpo, quien):
    identidad = cuerpo.get("identidad")
    if not isinstance(identidad, str) or not identidad.strip():
        return 400, {"error": "falta la identidad de la ficha. " + personas.FICHA_ERROR_SIN_ESCRIBIR}
    resto = {k: v for k, v in cuerpo.items() if k != "identidad"}
    return _envuelto(lambda: personas.editar_ficha_cliente(identidad, resto, quien, solo_contar=True))


# Cálculos registrados: nombre de la escritura -> función `(cuerpo, quien) -> (codigo, cuerpo)`. Grupo (a) de P11-6; los demás
# grupos (b) a (f) se registran aquí, uno por uno, cada uno con su prueba de pareja.
CALCULOS = {
    "crear": _calc_crear,
    "editar": _calc_editar,
    "crear_checkin": _calc_crear_checkin,
    "editar_checkin": _calc_editar_checkin,
    "editar_aprendizaje": _calc_editar_aprendizaje,
}


def calcular(nombre, cuerpo, quien):
    """`POST /calcular/<nombre>` -> `(codigo, cuerpo)`. Ya pasaron la llave y la identidad (las mira `servidor.py`)."""
    if not isinstance(cuerpo, dict):
        return 400, dict(ERROR_PEDIDO_ILEGIBLE)
    funcion = CALCULOS.get(nombre)
    if funcion is None:
        return 404, dict(ERROR_SIN_CALCULO)
    return funcion(cuerpo, quien)
