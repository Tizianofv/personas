# -*- coding: utf-8 -*-
"""Saca la foto de la entrada de Natalia DE LA APP: `contrato_dorado/entrada.json` y `contrato_dorado/SHA256_entrada`.

Uso:  python3 -B tools/generar_entrada_de_la_app.py <carpeta de una copia `git archive 8c9d21a` de la App de registro>

La App se corre en un proceso aparte, desde esa carpeta, con su `server.Handler` en un puerto. NO se usa su `main()`: lanzaría
hilos que leen y escriben NocoDB al arrancar (la barredura de la bandeja), y esas llamadas ensuciarían la foto. Contra el mismo doble
de `tests/doble_escrituras.py` y los mismos escenarios de `tests/escenarios_entrada.py` que usa la prueba del repo.

Si el doble recibe un pedido que no conoce (`errores`), la foto NO se guarda. Lo que guarda, por paso: el código, la respuesta y los
pedidos que llegaron al doble. Nunca la cabecera ni el valor de la llave.
"""
import hashlib
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))
sys.path.insert(0, str(RAIZ))      # el doble del modo de unión lee las columnas de `personas` del programa
import escenarios_entrada as escenarios  # noqa: E402

# El servidor de la App, sin `main()`: lo mismo que `server.main()` pero sin los hilos que tocan NocoDB al arrancar.
DRIVER = (
    "import http.server, os, sys\n"
    "sys.path.insert(0, os.getcwd())\n"
    "import server\n"
    "import personas\n"
    "sys.path.insert(0, '@TESTS@')\n"
    "import reloj\n"
    "reloj.fijar('@DIA@', server, personas)\n"   # el día de hoy de la App, fijado igual que el del programa (tests/reloj.py)
    "srv = http.server.ThreadingHTTPServer(('127.0.0.1', int(os.environ['PORT'])), server.Handler)\n"
    "sys.stdout.write('listo\\n'); sys.stdout.flush()\n"
    "srv.serve_forever()\n"
)
DRIVER = DRIVER.replace("@DIA@", escenarios.reloj.DIA_FIJO).replace("@TESTS@", str(RAIZ / "tests"))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("uso: generar_entrada_de_la_app.py <carpeta de la copia de la App>")
    copia = pathlib.Path(sys.argv[1]).resolve()
    if not (copia / "server.py").is_file() or not (copia / "personas.py").is_file():
        raise SystemExit("esa carpeta no es una copia de la App de registro")
    comando = [sys.executable, "-I", "-B", "-c", DRIVER]
    escenarios_foto = []
    for escenario in escenarios.ESCENARIOS:
        pasos, errores = escenarios.ejecutar(escenario, "app", comando, cwd=str(copia))
        if errores:
            raise SystemExit("el doble recibió un pedido que no conoce en «%s»: %s" % (escenario["nombre"], errores))
        if any(not escenarios._HORA.fullmatch(h) for h in escenarios.horas_de_los_pedidos(pasos)):
            raise SystemExit("una hora de `cuando` no es ISO en «%s»" % escenario["nombre"])
        escenarios.normalizar_horas(pasos)
        escenarios_foto.append({"nombre": escenario["nombre"], "pasos": pasos})
    foto = {
        "version": 1,
        "fuente": "App de registro, commit 8c9d21a: server.py (Handler.entrada_fichas, entrada_fichas, entrada_procesar, entrada_barrer, "
                  "_entrada_resumen, _entrada_cuerpo, _entrada_leer_resultado, _entrada_confirmado) y personas.py (recibir_y_unir)",
        "escenarios": escenarios_foto,
    }
    texto = json.dumps(foto, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destino = RAIZ / "contrato_dorado" / "entrada.json"
    destino.write_text(texto, encoding="utf-8")
    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
    (RAIZ / "contrato_dorado" / "SHA256_entrada").write_text("%s  entrada.json\n" % sha, encoding="utf-8")
    print("escenarios: %d, pasos: %d" % (len(escenarios_foto), sum(len(e["pasos"]) for e in escenarios_foto)))
    print("sha256: %s" % sha)


if __name__ == "__main__":
    main()
