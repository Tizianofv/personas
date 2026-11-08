# -*- coding: utf-8 -*-
"""El doble de Google para la ruta `GET /api/google/contactos/conteo` (parte 8). Lo usan las pruebas (con el servidor del repo, por
`tests/servidor_con_google_falso.py`) y el generador de la foto (con la App de registro en `594ec12`, por su driver).

Sustituye SOLO la llamada HTTP de `google_contactos._pedir` (la que sale a oauth2.googleapis.com y a people.googleapis.com). Todo lo
demás es el código real: las credenciales, el canje del token, la paginación, `_persona` y `contar`.

🔴 Este módulo NO importa nada del programa ni de la App: el driver de la foto lo carga dentro del proceso de la App, con `-I`.

Escenarios (lo que `pedir_falso` contesta a la llamada de token):
  «ok»             token válido, y la libreta de LIBRETA sin más páginas.
  «sin_token»      la respuesta del canje no trae `access_token`: `google_contactos` levanta `ErrorGoogle("token", "sin_token")`.
  «sin_credencial» no es un escenario del doble: no llega a Google, porque faltan las tres variables (`entorno`).

La libreta es una foto inventada, con nombres y números de prueba (`@ejemplo.test`, `Persona de prueba N`). Las fichas que casan salen
de `tests/doble_nocodb.py`: la 1 y la 2 son las que cuenta el conteo (la 3 está quitada y la 4 unida; `personas.ficha_fuera` las saca).
La 3 de la libreta tiene el teléfono de la ficha quitada, y tiene que dar «sin ficha».

Lo que NO imita: los códigos de error de Google (solo el de «sin token»), ni la paginación real (la libreta cabe en una página).
"""

VARIABLES_DE_PRUEBA = {
    "GOOGLE_CONTACTOS_CLIENT_ID": "id-de-prueba",
    "GOOGLE_CONTACTOS_CLIENT_SECRET": "secreto-de-prueba",
    "GOOGLE_CONTACTOS_REFRESH_TOKEN": "refresco-de-prueba",
}
ESCENARIOS = ("ok", "sin_token", "sin_credencial")


def entorno(escenario):
    """Las variables de Google que el proceso recibe en ese escenario. Sin credencial, ninguna (el conteo corta antes de Google)."""
    return {} if escenario == "sin_credencial" else dict(VARIABLES_DE_PRUEBA)


def _contacto(rn, nombre, telefonos=(), correos=(), con_fuente=True):
    persona = {"resourceName": rn, "names": [{"displayName": nombre}]}
    if telefonos:
        persona["phoneNumbers"] = [{"value": t} for t in telefonos]
    if correos:
        persona["emailAddresses"] = [{"value": c} for c in correos]
    if con_fuente:
        persona["metadata"] = {"sources": [{"type": "CONTACT", "etag": "%Etag-" + rn.split("/")[-1]}]}
    return persona


LIBRETA = [
    _contacto("people/c1", "Persona de prueba 1", ["+1 809-777-0001"], ["P1@Ejemplo.test"]),     # casa por los dos con la ficha 1
    _contacto("people/c2", "Persona de prueba 2", ["809 777 0002"], ["otra@ejemplo.test"]),      # casa solo por teléfono con la 2
    _contacto("people/c3", "Nombre distinto", ["(809) 777-0002"]),                               # teléfono de la 2, otro nombre: choca
    _contacto("people/c4", "Sin ficha", ["+1 809 555 0000"]),                                    # ninguna ficha
    _contacto("people/c5", "Sin nada", con_fuente=False),                                        # ni teléfono ni correo
    _contacto("people/c6", "Persona de prueba 3", ["18097770003"]),                              # ficha 3: quitada, no cuenta
]


def pedir_falso(escenario):
    """Una función `pedir(url, datos=None, cabeceras=None, timeout=30)` como la de `google_contactos._pedir`. Con `datos` es el canje
    del token (POST de formulario); sin `datos`, la lectura de la libreta (GET)."""
    if escenario not in ESCENARIOS:
        raise ValueError("escenario de Google no válido para el doble: %r" % (escenario,))

    def pedir(url, datos=None, cabeceras=None, timeout=30):
        if datos is not None:
            return {} if escenario == "sin_token" else {"access_token": "token-de-prueba", "expires_in": 3600}
        return {"connections": LIBRETA}
    return pedir
