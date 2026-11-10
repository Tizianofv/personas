# -*- coding: utf-8 -*-
"""EL CÁLCULO DEL MODO QUE SOLO CUENTA DE PERSONAS (P11-5, `disenos/personas-programa-aparte/P11-CONTAR.md`, sección 5).

  POST /calcular/<nombre>   cabeceras X-Personas-Cuenta-Llave (PERSONAS_CUENTA_LLAVE) y X-Personas-Cuenta-Quien

La App le pide a este proceso lo que una escritura escribiría, SIN escribir, para compararlo con lo que la App manda a NocoDB
(P11-4). Esta pieza NO calcula nada todavía: `CALCULOS` está vacía, así que cualquier `<nombre>` contesta 404 (el cliente de la App,
`panel_reenvio.calcular_personas`, lo lee como `sin_calculo`). P11-6 registra aquí, uno por uno, los cálculos de cada escritura.

Reglas que valen para TODO cálculo. La prueba `tests/test_calcular_cuenta.py` vigila solo una cosa: que no salga ningún pedido HTTP
a NocoDB (el doble cuenta todos los métodos). No vigila otras escrituras (archivos, procesos ajenos, otros servicios).
  · un cálculo nunca manda a NocoDB un pedido de escritura (POST, PATCH, DELETE o PUT): devuelve la forma de la escritura, sin mandarla;
  · la llave y la identidad las mira `servidor.py` ANTES de leer el cuerpo y antes de NocoDB;
  · el cuerpo que no es un objeto JSON se rechaza con 400 antes de buscar el cálculo, como las rutas hermanas.
"""

# Cálculos registrados: nombre de la escritura -> función `(cuerpo, quien) -> (codigo, cuerpo)`. Vacía hasta P11-6.
CALCULOS = {}

ERROR_SIN_CALCULO = {"error": "sin cálculo para esa escritura"}
ERROR_PEDIDO_ILEGIBLE = {"error": "pedido ilegible. No se calculó nada."}


def calcular(nombre, cuerpo, quien):
    """`POST /calcular/<nombre>` -> `(codigo, cuerpo)`. Ya pasaron la llave y la identidad (las mira `servidor.py`)."""
    if not isinstance(cuerpo, dict):
        return 400, dict(ERROR_PEDIDO_ILEGIBLE)
    funcion = CALCULOS.get(nombre)
    if funcion is None:
        return 404, dict(ERROR_SIN_CALCULO)
    return funcion(cuerpo, quien)
