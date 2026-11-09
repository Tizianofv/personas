# -*- coding: utf-8 -*-
"""LAS DOS RUTAS DE MERCADEO QUE ANOTAN EN LAS PERSONAS (P7, F5 de `disenos/personas-programa-aparte/UNA-SOLA-PUERTA.md`).

  POST /api/servicio/personas/mercadeo/baja   -> `personas.baja_de_natalia`   (la App: POST /api/servicio/mercadeo/baja, `Handler.mercadeo_baja`)
  POST /api/servicio/personas/mercadeo/foto   -> `personas.foto_de_natalia`    (la App: POST /api/servicio/mercadeo/foto, `Handler.mercadeo_foto`)

Cada función devuelve `(codigo, cuerpo)`, igual que la de la App, y las dos escriben solo la tabla de anotaciones, con `anotar_permiso`
(baja) y `anotar_foto` (foto). La llave (`PERSONAS_MERCADEO_LLAVE`, cabecera `X-Personas-Mercadeo-Llave`) la mira `servidor.py` ANTES de
leer el cuerpo. No es la llave que la App usa con Natalia (`MERCADEO_LLAVE_SERVICIO`): así no hay una segunda puerta de escritura a
Personas que Natalia pueda abrir sola; solo la App, cuando reenvíe, tendrá esta llave.

Que el código de las funciones es el de la App (`8c9d21a`) se comprobó el 9-nov-2026 por `ast.unparse` (sin docstrings, con `S.` y `_base.`
normalizados a los nombres del programa): `baja_de_natalia`, `foto_de_natalia`, `anotar_permiso`, `anotar_foto`, `anotar_origen_al_nacer`
y `_puerta_recibir` quedan iguales salvo el prefijo `S.` (y `_candado_de_ficha` sin prefijo en el programa). Las respuestas y los pedidos a NocoDB están en `contrato_dorado/mercadeo.json` (ver `tests/test_mercadeo_servicio.py`).

Lo que NO está aquí: el reenvío desde la App (otra pieza). Y `anotar_origen_al_nacer` NO tiene ruta: la llama solo `_puerta_recibir`
(`personas.py`), con las altas, así que no hace falta una ruta para él.
"""
import personas


def baja(pedido):
    """`POST .../mercadeo/baja` -> `(codigo, cuerpo)`. Ya pasó la llave. El pedido sin parsear (`None`) lo rechaza `baja_de_natalia` con 400."""
    return personas.baja_de_natalia(pedido)


def foto(pedido):
    """`POST .../mercadeo/foto` -> `(codigo, cuerpo)`. Ya pasó la llave."""
    return personas.foto_de_natalia(pedido)
