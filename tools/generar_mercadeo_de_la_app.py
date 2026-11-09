# -*- coding: utf-8 -*-
"""Saca la foto de la baja y la foto de Mercadeo DE LA APP: `contrato_dorado/mercadeo.json` y `contrato_dorado/SHA256_mercadeo`.

Uso:  python3 -B tools/generar_mercadeo_de_la_app.py <carpeta de una copia `git archive 8c9d21a` de la App de registro>

Salen de la App, con los pedidos de `tests/escenarios_mercadeo.py` (solo los dorados, con la llave buena):
  1. `rutas_de_la_app`: las constantes `MERCADEO_BAJA_RUTA` y `MERCADEO_FOTO_RUTA` de `server.py` de la App, leídas con AST.
  2. `escenarios`: lo que contesta `server.Handler.mercadeo_baja` y `mercadeo_foto` de la App a cada paso, con los pedidos que llegaron al
     doble en ese paso.

La App se corre en UN proceso por escenario, con su servidor HTTP (`server.Handler`, con cuatro guardas de `do_POST` apagadas porque son
de la sala y no de esta ruta; la llave de Mercadeo se mira en la propia App, sin tocar) y el doble de `tests/doble_escrituras.py`.
El día de hoy se fija igual que en el programa (`tests/reloj.py`).

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
import escenarios_mercadeo as escenarios  # noqa: E402
import escenarios_portal_escrituras as esc  # noqa: E402  (`normalizar`: el mismo que usa la prueba del programa)
import reloj  # noqa: E402

# El servidor de la App con sus stubs de prueba. Sin `main()`: lanzaría hilos que tocan NocoDB al arrancar.
DRIVER = (
    "import http.server, os, sys, types\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "import personas\n"
    "sys.path.insert(0, '@TESTS@')\n"
    "import reloj\n"
    "reloj.fijar('@DIA@', server, personas)\n"
    "server.puerta = types.SimpleNamespace(buscar=lambda *a, **k: None)\n"
    "class Pedido(server.Handler):\n"
    "    def cuerpo_rechazado(self, path):\n"
    "        return False\n"
    "    def frenado(self, path):\n"
    "        return False\n"
    "    def fuera_de_alcance(self, path, metodo):\n"
    "        return False\n"
    "    def falta_el_conteo(self, path, metodo):\n"
    "        return False\n"
    "srv = http.server.ThreadingHTTPServer(('127.0.0.1', int(os.environ['PORT'])), Pedido)\n"
    "sys.stdout.write('listo\\n'); sys.stdout.flush()\n"
    "srv.serve_forever()\n"
)
DRIVER = DRIVER.replace("@DIA@", reloj.DIA_FIJO).replace("@TESTS@", str(RAIZ / "tests"))


def rutas_de_la_app(copia):
    """Las dos constantes de ruta de la App (AST: asignaciones a nivel de módulo `MERCADEO_BAJA_RUTA` y `MERCADEO_FOTO_RUTA`)."""
    arbol = ast.parse((copia / "server.py").read_text(encoding="utf-8"))
    valores = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            if nodo.targets[0].id in ("MERCADEO_BAJA_RUTA", "MERCADEO_FOTO_RUTA") and isinstance(nodo.value, ast.Constant):
                valores[nodo.targets[0].id] = nodo.value.value
    if set(valores) != {"MERCADEO_BAJA_RUTA", "MERCADEO_FOTO_RUTA"}:
        raise SystemExit("la App debe definir MERCADEO_BAJA_RUTA y MERCADEO_FOTO_RUTA como texto; halló %s" % sorted(valores))
    return {"@baja": valores["MERCADEO_BAJA_RUTA"], "@foto": valores["MERCADEO_FOTO_RUTA"]}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_mercadeo_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App de registro")
    rutas = rutas_de_la_app(copia)
    if rutas != escenarios.RUTAS["app"]:
        raise SystemExit("las rutas de la App no son las que tienen los escenarios: %s" % rutas)
    comando = [sys.executable, "-I", "-B", "-c", DRIVER]
    escenarios_foto = []
    for escenario in escenarios.ESCENARIOS:
        pasos, errores = escenarios.ejecutar(escenario, "app", comando, cwd=str(copia))
        if errores:
            raise SystemExit("el doble recibió un pedido que no conoce en «%s»: %s" % (escenario["nombre"], errores))
        escenarios_foto.append({"nombre": escenario["nombre"], "pasos": [esc.normalizar(p) for p in pasos]})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 8c9d21a: server.py (Handler.mercadeo_baja y Handler.mercadeo_foto, con sus rutas "
                  "MERCADEO_BAJA_RUTA y MERCADEO_FOTO_RUTA) y personas.py (baja_de_natalia, foto_de_natalia, anotar_permiso, anotar_foto)",
        "rutas_de_la_app": rutas,
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "mercadeo.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_mercadeo").write_text("%s  mercadeo.json\n" % sha, encoding="utf-8")
    print("rutas de la App: %s" % rutas)
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
