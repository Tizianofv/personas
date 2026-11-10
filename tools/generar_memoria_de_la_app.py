# -*- coding: utf-8 -*-
"""Saca la foto de la MEMORIA DE NATALIA (`contrato_dorado/memoria.json` y `contrato_dorado/SHA256_memoria`).

Uso:  python3 -B tools/generar_memoria_de_la_app.py <copia `git archive 142d45f` de la App> <carpeta del repo natalia>

Dos cosas salen de fuera del programa:
  1. `campos_natalia`: las claves de `CAMPOS` en `natalia/agent/memoria.py` (AST, solo lectura del repo de Natalia), menos la identidad
     (`nombre`, `email`, `nombre_whatsapp`). La prueba M2 compara `personas_memoria.MEMORIA_CAMPOS` con esta lista.
  2. `escenarios`: lo que contesta la App al `editar` de su portal (`Handler.portal_personas_post` -> `editar_persona_portal`) con los
     DORADOS de `tests/escenarios_memoria.py`. La memoria de Natalia es la misma puerta, así que la App es la fuente de la respuesta.
     Corre con el driver del generador de escrituras del portal (`generar_portal_escrituras_de_la_app.correr_escenario`): un proceso
     por escenario, el día fijado (`tests/reloj.py`), el doble de `tests/doble_escrituras.py`.

Si el doble recibe un pedido que no conoce, o la App no contesta, la foto NO se guarda.
"""
import ast
import hashlib
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ / "tools"))
import escenarios_memoria as em  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`normalizar`, el mismo que usa la prueba)
import generar_portal_escrituras_de_la_app as gpe  # noqa: E402  (`correr_escenario`: el driver de la App)

IDENTIDAD = ("nombre", "email", "nombre_whatsapp")


def campos_de_natalia(carpeta):
    """Las claves de `CAMPOS` de `natalia/agent/memoria.py` (dict literal), sin la identidad. Falla si falta alguna de la identidad."""
    arbol = ast.parse((carpeta / "natalia" / "agent" / "memoria.py").read_text(encoding="utf-8"))
    claves = None
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CAMPOS" for t in nodo.targets):
            if not isinstance(nodo.value, ast.Dict):
                raise SystemExit("CAMPOS de Natalia no es un dict literal")
            claves = [k.value for k in nodo.value.keys if isinstance(k, ast.Constant)]
    if claves is None:
        raise SystemExit("no se encontró CAMPOS en natalia/agent/memoria.py")
    if not set(IDENTIDAD) <= set(claves):
        raise SystemExit("CAMPOS de Natalia no tiene toda la identidad %s" % (IDENTIDAD,))
    return [c for c in claves if c not in IDENTIDAD]


def pasos_de_la_app(escenario):
    """Cada paso dorado como lo recibe la App: su `editar` del portal con el `id` del cuerpo."""
    return [{"ruta": em.RUTA_APP % p["cuerpo"]["id"], "quien": em.QUIEN, "metodo": "POST", "cuerpo": p["cuerpo"]}
            for p in escenario["pasos"]]


def main():
    if len(sys.argv) != 3:
        raise SystemExit("uso: generar_memoria_de_la_app.py <copia de la App> <carpeta del repo natalia>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    natalia = pathlib.Path(sys.argv[2]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App con server.py y personas.py")
    campos = campos_de_natalia(natalia)
    escenarios_foto = []
    for escenario in em.DORADOS:
        pasos = pasos_de_la_app(escenario)
        resultados = gpe.correr_escenario(copia, pasos, escenario.get("caidas", ()), escenario.get("caidas_una_vez", ()),
                                          columnas_personas=em.COLUMNAS_MEMORIA, caidas_fila=escenario.get("caidas_fila", ()))
        escenarios_foto.append({"nombre": escenario["nombre"], "caidas": list(escenario.get("caidas", ())), "pasos": [
            dict({"cuerpo": p["cuerpo"], "llave": "natalia", "quien": em.QUIEN}, **r) for p, r in zip(escenario["pasos"], resultados)]})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 142d45f: Handler.portal_personas_post con ruta /api/portal-personas/<id>/editar "
                  "(personas.editar_persona_portal, sin clave_envio). Campos: CAMPOS de natalia/agent/memoria.py menos la identidad. "
                  "Datos del doble tests/doble_nocodb.py y tests/doble_escrituras.py.",
        "campos_natalia": campos,
        "identidad_natalia": list(IDENTIDAD),
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "memoria.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_memoria").write_text("%s  memoria.json\n" % sha, encoding="utf-8")
    print("campos de Natalia (sin identidad): %d: %s" % (len(campos), ", ".join(campos)))
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
