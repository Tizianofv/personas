# -*- coding: utf-8 -*-
"""Saca la foto de las escrituras de Registro DE LA APP: `contrato_dorado/escrituras.json` y su `contrato_dorado/SHA256_escrituras`.

Uso:  python3 -B tools/generar_escrituras_de_la_app.py <carpeta de una copia `git archive 0b48b5d` de la App de registro>

La App se corre en un proceso aparte, desde esa carpeta, con su `server.Handler` en un puerto. NO se usa su `main()`: lanzaría
hilos que leen y escriben NocoDB al arrancar, y esas llamadas ensuciarían la foto. Contra el mismo doble de
`tests/doble_escrituras.py` y los mismos escenarios de `tests/escenarios_escrituras.py` que usa la prueba del repo.

Si el doble recibe un pedido que no conoce (`errores`), la foto NO se guarda: una foto con un pedido sin contestar no sirve.
Lo que guarda, por paso: el código, la respuesta y los pedidos que llegaron al doble. Nunca la cabecera ni los valores de las llaves.
"""
import hashlib
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
import escenarios_escrituras as escenarios  # noqa: E402

# El servidor de la App, sin `main()`: lo mismo que `server.main()` pero sin los hilos que tocan NocoDB al arrancar.
DRIVER = (
    "import http.server, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "srv = http.server.ThreadingHTTPServer(('127.0.0.1', int(os.environ['PORT'])), server.Handler)\n"
    "sys.stdout.write('listo\\n'); sys.stdout.flush()\n"
    "srv.serve_forever()\n"
)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_escrituras_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas_escritura_rutas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App con personas_escritura_rutas.py")
    comando = [sys.executable, "-I", "-B", "-c", DRIVER]
    escenarios_foto = []
    for escenario in escenarios.ESCENARIOS:
        pasos, errores = escenarios.ejecutar(escenario, comando, cwd=str(copia))
        if errores:
            raise SystemExit("el doble recibió un pedido que no conoce en «%s»: %s" % (escenario["nombre"], errores))
        escenarios_foto.append({"nombre": escenario["nombre"], "pasos": pasos})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 0b48b5d: personas_escritura_rutas.py y server.py (personas_escritura_post, guardar_cara, "
                  "crear_persona, editar_persona, campos_persona)",
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "escrituras.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_escrituras").write_text("%s  escrituras.json\n" % sha, encoding="utf-8")
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
