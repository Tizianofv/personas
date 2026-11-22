# -*- coding: utf-8 -*-
"""Regenera `constantes_app.json`: los valores que la App de registro tiene en un commit, leídos sin tocar la App.

Uso (desde la raíz de este repo):
  /usr/bin/python3 tools/generar_constantes.py <commit>            # extrae `git archive <commit>` del repo de la App (solo lectura)
  /usr/bin/python3 tools/generar_constantes.py --arbol <carpeta>   # lee una carpeta de la App ya extraída (pruebas de la sala)
  opciones: --app <repo de la App> (por defecto `IA CDS/registro`), --salida <archivo> (por defecto `constantes_app.json`)
  --comparar: no escribe; imprime qué valores cambiarían frente al archivo actual.

Validación: sobre 0b48b5d reproduce la foto anterior sin cambios; sobre a89ce51 cambia solo ENTRADA_ORIGENES.

Qué hace: copia el árbol de la App a una carpeta temporal, corre un proceso con entorno limpio (`env -i`; sin NOCODB_T_*, y las
tres variables de relleno de `ENTORNO_LIMPIO`) que importa `server` de la App y lee cada nombre de `NOMBRES`, y escribe el JSON con la misma normalización que la
prueba `tests/test_constantes_app.py` (tuplas y listas como listas, el sentinela `object()` como `"<sentinela>"`).

Los nombres son los que `base.py` copia de la App. Si base.py copia un nombre nuevo, se agrega aquí.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
APP_POR_DEFECTO = "/Users/controlroom/Documents/IA CDS/registro"
SALIDA_POR_DEFECTO = RAIZ / "constantes_app.json"

# Lo que base.py copia de la App (los nombres de la foto anterior, de 0b48b5d). Si base.py copia un nombre nuevo, va aquí.
NOMBRES = (
    "ALQUILER_DEPOSITO", "ALQUILER_DESDE", "ALQUILER_HASTA", "CAMPOS_DE_UNA_FICHA", "CARA_B64_CHARS", "CARA_BYTES", "CARA_COLUMNA",
    "CARA_DIMS", "CARA_RANURAS", "CARA_SEPARADOR", "CASILLAS_ALQUILER", "ENTRADA_ORIGENES", "ENTRADA_PERMISO_CANAL", "ESTADOS_TERMINALES",
    "LEADS_CASILLAS_DE_TELEFONO", "L_ASIS_PERSONA", "L_ASIS_SESION", "L_MUSICOS", "L_PERSONA_INSCRIPCIONES", "L_PERSONA_PAGOS",
    "L_PERSONA_PROYECTOS", "L_PERSONA_SESIONES", "L_PROY_MIEMBROS", "MERCADEO_ENVIO_ESTADOS", "PORTAL_COLUMNAS_VETADAS",
    "SALTOS_DE_UNION", "SESION_FIELDS", "SESION_FIELDS_LUCY", "TODAS_LAS_COLUMNAS", "TZ", "T_ASISTENCIAS", "T_BANDEJA_PERSONAS",
    "T_CONVERSACIONES", "T_MERCADEO_ENVIOS", "T_PERSONAS", "T_PERSONAS_ANOTACIONES", "T_PERSONAS_QUITADAS", "T_PROYECTOS",
    "T_SESIONES", "T_UNIONES_PERSONAS",
)

# Lo que corre en el proceso de la App: importa `server` y lee cada nombre (con la misma normalización que la prueba).
CODIGO_EN_LA_APP = r'''
import json, sys
sys.path.insert(0, ".")
import server
def norm(v):
    if type(v).__name__ == "object":
        return "<sentinela>"
    if isinstance(v, (tuple, list)):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
nombres = json.loads(sys.argv[1])
salida = {}
for n in nombres:
    salida[n] = norm(getattr(server, n))
print(json.dumps(salida, ensure_ascii=False, sort_keys=True))
'''
# La App exige estas tres variables para importarse (si faltan, no arranca). Son de relleno: ninguna constante copiada depende de su valor.
ENTORNO_LIMPIO = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                  "NOCODB_BASE": "http://invalid.invalid", "NOCODB_TOKEN": "token-de-relleno-del-generador", "APP_PIN": "pin-de-relleno-del-generador"}


def leer_valores(arbol):
    r = subprocess.run(["/usr/bin/python3", "-B", "-c", CODIGO_EN_LA_APP, json.dumps(sorted(NOMBRES))],
                       cwd=str(arbol), env=ENTORNO_LIMPIO, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("la App no se pudo importar o le falta un nombre: " + r.stderr[-600:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("commit", nargs="?", help="commit de la App (se extrae con git archive, solo lectura)")
    ap.add_argument("--arbol", help="carpeta de la App ya extraída (en lugar de un commit)")
    ap.add_argument("--app", default=APP_POR_DEFECTO, help="repo de la App")
    ap.add_argument("--salida", default=str(SALIDA_POR_DEFECTO))
    ap.add_argument("--comparar", action="store_true", help="no escribe: muestra lo que cambiaría")
    a = ap.parse_args()
    if bool(a.commit) == bool(a.arbol):
        sys.exit("pon un commit, o --arbol <carpeta>, y no los dos")

    temporal = None
    if a.arbol:
        arbol = Path(a.arbol).resolve()
        origen = "copia de la App en la carpeta %s (extraída de un commit de la App)" % arbol.name
        commit = None
    else:
        commit = subprocess.run(["git", "-C", a.app, "rev-parse", "--verify", a.commit + "^{commit}"],
                                capture_output=True, text=True)
        if commit.returncode != 0:
            sys.exit("commit de la App no encontrado: " + a.commit)
        commit = commit.stdout.strip()
        temporal = tempfile.mkdtemp(prefix="constantes-app-")
        p = subprocess.run('git -C "%s" archive %s | tar -x -C "%s"' % (a.app, commit, temporal), shell=True,
                           capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit("git archive falló: " + p.stderr[-300:])
        arbol = Path(temporal)
        origen = "App de registro, commit %s (git archive; entorno limpio con NOCODB_BASE, NOCODB_TOKEN y APP_PIN de relleno; NOCODB_T_* sin definir)" % commit

    try:
        valores = leer_valores(arbol)
    finally:
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)

    doc = {
        "comando": "/usr/bin/python3 tools/generar_constantes.py %s" % (commit or "--arbol <carpeta>"),
        "normalizacion": "tuplas y listas como listas; TZ como su texto; el sentinela object() como \"<sentinela>\"",
        "origen": origen,
        "valores": valores,
    }
    actual = json.loads(Path(a.salida).read_text(encoding="utf-8")) if Path(a.salida).exists() else {"valores": {}}
    cambian = sorted(n for n in valores if actual.get("valores", {}).get(n) != valores[n])
    if a.comparar:
        print("cambian %d de %d: %s" % (len(cambian), len(valores), ", ".join(cambian) or "ninguno"))
        return
    Path(a.salida).write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("escrito %s: %d valores; cambian %d: %s" % (a.salida, len(valores), len(cambian), ", ".join(cambian) or "ninguno"))


if __name__ == "__main__":
    main()
