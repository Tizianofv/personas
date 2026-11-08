# -*- coding: utf-8 -*-
"""Saca la foto de las dos rutas de LECTURA del portal que el programa contesta (`contrato/portal_lectura.json` y su
`contrato/SHA256_portal`), desde la App de registro.

Uso:  python3 -B tools/generar_portal_de_la_app.py <carpeta de una copia `git archive` de la App de registro>

Por cada ruta, la App corre en un proceso aparte (desde esa carpeta, con `-I`): se importa su `server` y se llama a su
`Handler.portal_personas_get` con un objeto que solo guarda lo que la App mandaría con `send_json`. Eso ejercita el enrutado y
las funciones REALES de la App (`portal_persona_nueva`, `listar_borradas`). Lo que NO ejercita: la puerta de sesión de
`portal_personas` (el 401 y el 403 de la App); esa no se copia, y el programa no la tiene.
Los datos de NocoDB salen del doble de `tests/doble_nocodb.py`, el mismo que usan las pruebas. Si el doble recibe un pedido
que no conoce, o un pedido que no es GET, la foto NO se guarda.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
import doble_nocodb as doble_mod  # noqa: E402

RUTAS = [("portal_nueva", "/api/portal-personas/nueva"), ("portal_borradas", "/api/portal-personas/borradas")]

# La App, sin `main()`: importa su `server` (que no arranca hilos) y contesta una ruta de lectura del portal a un objeto de prueba.
DRIVER = (
    "import json, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "class Recogida:\n"
    "    enviado = None\n"
    "    def send_json(self, obj, status=200):\n"
    "        self.enviado = (status, obj)\n"
    "r = Recogida()\n"
    "server.Handler.portal_personas_get(r, sys.argv[1], {})\n"
    "codigo, cuerpo = r.enviado\n"
    "sys.stdout.write('\\n' + json.dumps({'status': codigo, 'respuesta': cuerpo}, ensure_ascii=False) + '\\n')\n"
)


def pedir_a_la_app(copia, ruta, url_doble):
    entorno = {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "NOCODB_BASE": url_doble, "NOCODB_TOKEN": "token-de-prueba", "APP_PIN": "pin-de-prueba",
        "NOCODB_T_PERSONAS_QUITADAS": doble_mod.T_QUITADAS,
    }
    salida = subprocess.run([sys.executable, "-I", "-B", "-c", DRIVER, ruta], cwd=str(copia), env=entorno,
                            capture_output=True, text=True, timeout=300)
    if salida.returncode != 0:
        raise SystemExit("la App no contestó «%s»: %s" % (ruta, salida.stderr[-800:]))
    return json.loads(salida.stdout.strip().splitlines()[-1])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_portal_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App con server.py y personas.py")
    pedidos = []
    for nombre, ruta in RUTAS:
        doble = doble_mod.Doble()
        url = doble.arrancar()
        try:
            resultado = pedir_a_la_app(copia, ruta, url)
        finally:
            doble.parar()
        if doble.errores or doble.no_get:
            raise SystemExit("el doble recibió algo que no conoce en «%s»: %s %s" % (ruta, doble.errores, doble.no_get))
        pedidos.append({"nombre": nombre, "ruta": ruta, "status": resultado["status"],
                        "lecturas_a_nocodb": doble.lecturas, "respuesta": resultado["respuesta"]})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 594ec12: server.Handler.portal_personas_get (las dos rutas), con portal_persona_nueva "
                  "y listar_borradas de personas.py. Sin la puerta de sesión de portal_personas. Datos del doble tests/doble_nocodb.py.",
        "escrituras_a_nocodb": 0,
        "pedidos": pedidos,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato" / "portal_lectura.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato" / "SHA256_portal").write_text("%s  portal_lectura.json\n" % sha, encoding="utf-8")
    print("pedidos: %d" % len(pedidos))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
