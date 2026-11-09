# -*- coding: utf-8 -*-
"""Los escenarios de la ficha del Aprendizaje (P6): `POST /api/aprendizaje/fichas/<identidad>/editar`, los mismos pedidos contra la App
y contra el programa.

  lado `app`:      `server.Handler.do_POST` de la App (copia `git archive 8c9d21a`), en su propio servidor HTTP. El driver de
                   `tools/generar_aprendizaje_de_la_app.py` da por buena la sesión (`entra_aprendizaje` = True) y pone como `quien` la
                   cabecera `X-Personas-Portal-Quien` (la identidad que la App pondría con `firma_escrita`).
  lado `programa`: `servidor.py` con `PERSONAS_PORTAL_LLAVE` (la llave del portal), `X-Personas-Portal-Quien` (el `quien`) y
                   `X-Personas-Portal-Tipo` = `C`.

Solo los escenarios DORADOS entran en la foto (`contrato_dorado/aprendizaje.json`): llave del portal, `quien` no vacío y tipo `C`. Ahí la
App y el programa contestan lo mismo. Lo que es guarda del programa (llave mala, identidad mala) se prueba en `tests/test_aprendizaje.py`
con el programa solo.

Frontera declarada:
  · El doble no guarda `quien` en esta ruta (la edición deja su rastro en el log, no en NocoDB). Por eso `quien` del cuerpo se prueba con
    un espía en el proceso (`test_aprendizaje.py`), no con la foto.
  · Cambiar el teléfono de la ficha lee `sesiones` y `conversaciones`, que el doble no tiene: no está en la foto.
  · El BSUID de una ficha real no está en el doble: la rama de BSUID se prueba solo con una identidad sin ficha (404).
  · La sesión de Aprendizaje (`entra_aprendizaje`) la mira la App antes de reenviar: no se prueba aquí.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import escenarios_portal_escrituras as esc  # noqa: E402  (entorno, cabeceras, `ejecutar` y la normalización de la foto del portal)

RUTA = "/api/aprendizaje/fichas/%s/editar"
DOS = "18097770002"             # la persona 2 del doble: un teléfono, una sola ficha
CLAVE = "aprendizaje-clave-0001"        # formato válido para `clave_envio`
CLAVE_FALLIDA = "aprendizaje-clave-0002"
CLAVE_DISTINTA = "aprendizaje-clave-0003"


def _paso(identidad, cuerpo=None, crudo=None, llave="portal", quien=esc.QUIEN_DORADO, tipo="C"):
    return esc._p(RUTA % identidad, cuerpo=cuerpo, crudo=crudo, llave=llave, quien=quien, tipo=tipo, metodo="POST")


def _cuerpo(cambios=None, base=None, idd=2, **extra):
    """Un cuerpo de la pantalla: `id` (la ficha que vio), `cambios` y `base` (lo que vio al abrir). `extra` agrega claves al cuerpo."""
    datos = {"id": idd,
             "cambios": {"nombre": "Persona Aprendizaje Dos"} if cambios is None else cambios,
             "base": {"nombre": "Persona de prueba 2"} if base is None else base}
    datos.update(extra)
    return datos


# Dorados: los que la foto guarda. Llave del portal, quien y tipo «C» (como los manda la App).
ESCENARIOS = [
    {"nombre": "editar_ok", "pasos": [_paso(DOS, _cuerpo())]},
    {"nombre": "editar_sin_ficha", "pasos": [_paso("18090009999", _cuerpo())]},
    {"nombre": "editar_duplicada", "pasos": [_paso("18097770001", _cuerpo())]},
    {"nombre": "editar_identidad_bsuid_sin_ficha", "pasos": [_paso("AB.abc123", _cuerpo())]},
    {"nombre": "editar_identidad_con_forma_que_no_es_nada", "pasos": [_paso("ab.abc123", _cuerpo())]},
    {"nombre": "editar_campo_no_editable", "pasos": [_paso(DOS, _cuerpo(cambios={"credito": "5"}, base={"credito": "0"}))]},
    {"nombre": "editar_sin_cambios", "pasos": [_paso(DOS, _cuerpo(cambios={}))]},
    {"nombre": "editar_valor_no_texto", "pasos": [_paso(DOS, _cuerpo(cambios={"nombre": 5}))]},
    {"nombre": "editar_sin_id", "pasos": [_paso(DOS, {"cambios": {"nombre": "Persona Aprendizaje Dos"}, "base": {"nombre": "Persona de prueba 2"}})]},
    {"nombre": "editar_id_de_otra_ficha", "pasos": [_paso(DOS, _cuerpo(idd=3))]},
    {"nombre": "editar_cuerpo_ilegible", "pasos": [_paso(DOS, crudo="esto no es json")]},
    {"nombre": "editar_cuerpo_que_no_es_objeto", "pasos": [_paso(DOS, crudo="[1, 2]")]},
    {"nombre": "editar_repetido_ya_guardado", "pasos": [_paso(DOS, _cuerpo(clave_envio=CLAVE)), _paso(DOS, _cuerpo(clave_envio=CLAVE))]},
    # Hermanos de `una_vez` (regla de la sala): con la misma llave pero otro cuerpo, la App escribe otra vez y no dice `ya_guardado`.
    # El segundo `base` es lo que quedó tras el primero, así la ficha no da 409 por cambio ajeno.
    {"nombre": "editar_cuerpo_distinto", "pasos": [
        _paso(DOS, _cuerpo(clave_envio=CLAVE_DISTINTA)),
        _paso(DOS, _cuerpo(clave_envio=CLAVE_DISTINTA, cambios={"nombre": "Persona Aprendizaje Tres"},
                           base={"nombre": "Persona Aprendizaje Dos"}))]},
    {"nombre": "editar_reintento_tras_fallo", "caidas_una_vez": ["PATCH"],
     "pasos": [_paso(DOS, _cuerpo(clave_envio=CLAVE_FALLIDA)), _paso(DOS, _cuerpo(clave_envio=CLAVE_FALLIDA))]},
    {"nombre": "editar_lectura_caida", "caidas": ["GET"], "pasos": [_paso(DOS, _cuerpo())]},
    {"nombre": "editar_escritura_caida", "caidas": ["PATCH"], "pasos": [_paso(DOS, _cuerpo())]},
    {"nombre": "editar_quien_del_cuerpo_no_cuenta", "pasos": [_paso(DOS, _cuerpo(quien="Otra Persona"))]},
]

# Guardas del programa (sin la App): la llave se mira antes que el cuerpo y que NocoDB; la identidad, antes que el cuerpo.
GUARDA = [
    {"nombre": "llave_mala", "pasos": [_paso(DOS, _cuerpo(), llave="mala")]},
    {"nombre": "llave_vacia", "pasos": [_paso(DOS, _cuerpo(), llave="vacia")]},
    {"nombre": "llave_ausente", "pasos": [_paso(DOS, _cuerpo(), llave=None)]},
    # Variable vacía: la ruta nace cerrada. Con la variable vacía, ni una cabecera vacía abre (la pareja de «llave_vacia»).
    {"nombre": "llave_vacia_con_la_variable_vacia", "entorno": {"PERSONAS_PORTAL_LLAVE": ""},
     "pasos": [_paso(DOS, _cuerpo(), llave="vacia"), _paso(DOS, _cuerpo(), llave="portal")]},
    {"nombre": "identidad_tipo_a", "pasos": [_paso(DOS, _cuerpo(), tipo="A")]},
    {"nombre": "identidad_sin_tipo", "pasos": [_paso(DOS, _cuerpo(), tipo=None)]},
    {"nombre": "identidad_quien_vacio", "pasos": [_paso(DOS, _cuerpo(), quien="")]},
    {"nombre": "identidad_sin_quien", "pasos": [_paso(DOS, _cuerpo(), quien=None)]},
]
