# -*- coding: utf-8 -*-
"""LA MEMORIA DE NATALIA HACIA PERSONAS (P8a-1, `disenos/personas-programa-aparte/P8a-memoria-de-natalia.md`).

  POST /api/servicio/personas/memoria   con cabecera X-Personas-Natalia-Llave (PERSONAS_NATALIA_LLAVE) y X-Personas-Natalia-Quien

Cuerpo: `{"id": <Id de la ficha>, "base": {campo: lo que decía al leer}, "cambios": {campo: valor nuevo}}`. Solo los campos de
`MEMORIA_CAMPOS` (los 12 que no son de identidad de la memoria de Natalia). Identidad (`nombre`, `email`, `nombre_whatsapp`) NO va
por aquí: va por la entrada (P5a/P5b). El `quien` lo pone la cabecera; el del cuerpo no se lee.

La llave y la identidad las mira `servidor.py` ANTES de leer el cuerpo y antes de NocoDB. Este módulo solo pasa el pedido al motor.
"""
import personas

# Los 15 campos de la memoria de Natalia (`natalia/natalia/agent/memoria.py`, `CAMPOS`) menos los 3 de identidad. Lo saca
# `tools/generar_memoria_de_la_app.py` de ese archivo y lo guarda en `contrato_dorado/memoria.json` (`campos_natalia`); la prueba M2
# compara esta lista con esa foto. Si Natalia agrega un campo, la prueba se pone roja y hay que decidir si entra.
MEMORIA_CAMPOS = {
    "instagram": personas.PORTAL_EDITABLES["instagram"],
    "instrumento": personas.PORTAL_EDITABLES["instrumento"],
    "genero": personas.PORTAL_EDITABLES["genero"],
    "Cumpleanos": personas.PORTAL_EDITABLES["Cumpleanos"],
    "Tono": personas.PORTAL_EDITABLES["Tono"],
    "Clave": personas.PORTAL_EDITABLES["Clave"],
    "Preferencias_operativas": personas.PORTAL_EDITABLES["Preferencias_operativas"],
    "Comportamiento_reserva": personas.PORTAL_EDITABLES["Comportamiento_reserva"],
    "Sensibilidad_precio": personas.PORTAL_EDITABLES["Sensibilidad_precio"],
    "Riesgo_noshow": personas.PORTAL_EDITABLES["Riesgo_noshow"],
    "Resumen": personas.PORTAL_EDITABLES["Resumen"],
    "notas": personas.PORTAL_EDITABLES["notas"],
}
# La identidad de la memoria de Natalia: no se escribe por esta ruta.
IDENTIDAD_DE_NATALIA = ("nombre", "email", "nombre_whatsapp")


def editar(cuerpo, quien):
    """`POST .../memoria` -> `(codigo, cuerpo)`. Ya pasaron la llave y la identidad."""
    return personas.editar_memoria_de_natalia(cuerpo, quien, MEMORIA_CAMPOS)
