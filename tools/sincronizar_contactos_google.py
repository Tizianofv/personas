#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SINCRONIZAR LOS CONTACTOS DE GOOGLE A LAS FICHAS (P3 de contactos de Google). Lo corre la sala, así:

    railway run -s registro-cds python3 tools/sincronizar_contactos_google.py

QUÉ HACE, EN ORDEN:
  1. Lee la libreta de Google (solo lectura) con las tres credenciales de Railway.
  2. Pasa cada contacto por la PUERTA de fichas (`personas.recibir`, origen `google`, sin `recibir_y_unir`:
     nunca une dos fichas sola). Primero SOLO CUENTA: lo que haría, sin escribir nada.
  3. SOLO CUENTA, siempre. Este guion NO escribe, aunque `CONTACTOS_GOOGLE_MODO` valga `escribir`: fuerza `contar` en
     su copia del entorno (decisión de la sala). No escribe en NocoDB (la puerta solo recibe el conteo) ni en Google
     (P4 solo arma el plan). Lo que sí escribe es el reloj de la App (P6, `google_contactos.reloj`), y solo si
     `CONTACTOS_GOOGLE_RELOJ` vale `encendido` y `CONTACTOS_GOOGLE_MODO` vale `escribir`. Este guion no lee el reloj.
     Lo que el reloj escribiría en NocoDB y en Google se ve aquí solo como cifras (`contar`, `desde_fichas`, `p4.cuentas`).

LO QUE NO HACE, A PROPÓSITO:
  · No borra nada en ningún lado, ni en Google ni en NocoDB.
  · No imprime nombres, teléfonos ni correos. La puerta sí imprime una línea `[PUERTA-FICHAS]` por contacto, con el
    `ficha_id` (el número de la ficha, no un dato de la persona); el JSON del final es solo cifras.
  · No arranca el servidor: importar `server` no corre `main()`.

SALIDA: un JSON con `modo` (siempre `contar`), `contar` (lo que haría), `escrito` (siempre `null`: este guion no escribe),
`sin_pasar` (segundos teléfonos y correos que la puerta no recibe), `desde_fichas` (P2) y `p4` (P4: cifras del plan).
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import google_contactos  # noqa: E402
import personas  # noqa: E402
import server  # noqa: E402,F401  (pone `personas.S`, sin el cual la puerta no sabe hablar con NocoDB)


def main():
    # SOLO CUENTA (decisión de la sala): la copia del entorno que recibe `sincronizar` fuerza `contar`, aunque
    # `CONTACTOS_GOOGLE_MODO` valga `escribir`. Así este guion no llega a ninguna escritura de NocoDB ni de Google.
    entorno = dict(os.environ)
    entorno[google_contactos.VARIABLE_MODO] = "contar"
    try:
        resultado = google_contactos.sincronizar(entorno, personas.recibir)
    except google_contactos.SinCredencial as e:
        print("Faltan credenciales de Google (solo sus nombres): " + ", ".join(e.faltan))
        return 2
    except google_contactos.ErrorGoogle as e:
        print(f"Google no contestó como se esperaba: {e.etapa} ({e.codigo})")
        return 1
    print(json.dumps(resultado, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
