# -*- coding: utf-8 -*-
"""La línea `[PUERTA-FICHAS]` por CADA camino de la puerta que la imprime, recorrido por `recibir` (y `recibir_y_unir`), sin llamar a
`_puerta_registrar` a mano. Es la prueba que faltaba cuando el testigo marcó NO PASA sobre la línea del modo cuenta.

Qué garantiza y con qué prueba:
  R1  el cálculo del check-in (`crear_checkin`, `personas_cuenta.calcular` -> `personas_escrituras.crear_persona(solo_contar=True)` ->
      `recibir`, el camino principal, `personas.py` `recibir`, la llamada al final): en modo cuenta la línea dice `modo=solo_cuenta` y
      `accion=contaria_<acción>`, y el doble de NocoDB recibe cero escrituras.
  R2  la misma escritura de verdad (`personas_escrituras.crear_persona` sin `solo_contar`): la línea dice `modo=escribir` y ninguna acción
      `contaria_`.
  R3  el cálculo de la edición del check-in (`editar_checkin`): igual que R1, para el camino de edición.
  R4  un dato que la puerta no lee (`_puerta_leer_entrada` levanta `_PuertaIlegible`): la línea de la llamada en la rama de rechazo de
      `recibir` dice `modo=solo_cuenta` en modo cuenta y `modo=escribir` en modo escribir.
  R5  un dato de pantalla pasado por `recibir_y_unir` (rechazo `dato_de_pantalla`, `_union_sola_rechazo`): `modo=solo_cuenta` en modo cuenta.
  R6  un dato de sistema válido pasado por `recibir_y_unir` sin aviso de misma persona (`_union_sola_responder` con `solo_contar`):
      `modo=solo_cuenta` en modo cuenta, y cero escrituras.

Qué NO cubre: una unión real entre dos fichas (`_union_sola_decidir` con `solo_contar`, las ramas `unida` y `no_son_la_misma`); ahí la
línea sale por el mismo `_union_sola_responder` que R6, y no se probó con dos fichas que se unen de verdad.
"""
import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_escrituras  # noqa: E402
from test_calcular_grupo_a import Corrida, cuerpo_del_calculo, escribir, QUIEN  # noqa: E402

LINEA = re.compile(r"^\[PUERTA-FICHAS\] .*$", re.M)
CREAR = {"nombre": "Check Recibir", "telefono": "8095550131", "instagram": "@recibir"}
EDITAR = {"id": 2, "instagram": "@recibir2"}
NUEVO_SISTEMA = {"origen": "checkin", "nombre": "Persona Union Prueba", "telefono_dicho": "18095550177"}


def _lineas(fn):
    """Corre `fn` y devuelve su resultado y las líneas `[PUERTA-FICHAS]` que imprimió, reales (sin tocar nada de la puerta)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        resultado = fn()
    return resultado, LINEA.findall(buf.getvalue())


class CaminosDeLaPuerta(unittest.TestCase):

    def test_R1_crear_checkin_en_cuenta_dice_contaria_y_no_escribe(self):
        with Corrida() as c:
            codigo_cuerpo, lineas = _lineas(lambda: personas_cuenta.calcular(
                "crear_checkin", cuerpo_del_calculo("crear_checkin", CREAR), QUIEN))
            self.assertEqual(c.escrituras(), [], "el cálculo no puede escribir")
        self.assertEqual(codigo_cuerpo[0], 200, codigo_cuerpo)
        self.assertEqual(len(lineas), 1, lineas)
        self.assertIn("origen=checkin", lineas[0])
        self.assertIn("modo=solo_cuenta", lineas[0])
        # Un alta en cuenta sale con `accion=no_tocada` (la acción de alta solo se asigna en la rama de escritura, y `ficha_id` es None):
        # eso no afirma escritura. Lo que no puede salir es una acción de escritura sin el prefijo `contaria_`.
        self.assertRegex(lineas[0], r"accion=(contaria_\w+|no_tocada)\b")
        self.assertNotRegex(lineas[0], r"accion=(creada|completada)\b")

    def test_R2_crear_checkin_de_verdad_dice_escribir(self):
        with Corrida() as c:
            _, lineas = _lineas(lambda: escribir("crear_checkin", CREAR))
            self.assertTrue(c.escrituras(), "la escritura de verdad sí escribe")
        self.assertEqual(len(lineas), 1, lineas)
        self.assertIn("modo=escribir", lineas[0])
        self.assertNotIn("solo_cuenta", lineas[0])
        self.assertNotIn("contaria_", lineas[0])

    def test_R3_editar_checkin_en_cuenta_dice_contaria_y_no_escribe(self):
        with Corrida() as c:
            codigo_cuerpo, lineas = _lineas(lambda: personas_cuenta.calcular(
                "editar_checkin", cuerpo_del_calculo("editar_checkin", EDITAR), QUIEN))
            self.assertEqual(c.escrituras(), [], "el cálculo no puede escribir")
        self.assertEqual(codigo_cuerpo[0], 200, codigo_cuerpo)
        self.assertEqual(len(lineas), 1, lineas)
        self.assertIn("modo=solo_cuenta", lineas[0])
        self.assertIn("accion=contaria_completada", lineas[0])

    def test_R4_dato_ilegible_en_recibir_dice_el_modo(self):
        malo = {"origen": "checkin", "clave_que_la_puerta_no_conoce": 1}
        with Corrida():
            r, lineas = _lineas(lambda: personas.recibir(malo, solo_contar=True))
            self.assertEqual(r["estado"], "rechazado")
            self.assertEqual(len(lineas), 1, lineas)
            self.assertIn("modo=solo_cuenta", lineas[0])
            r, lineas = _lineas(lambda: personas.recibir(malo, solo_contar=False))
            self.assertEqual(len(lineas), 1, lineas)
            self.assertIn("modo=escribir", lineas[0])
            self.assertNotIn("solo_cuenta", lineas[0])

    def test_R5_dato_de_pantalla_en_recibir_y_unir_dice_el_modo(self):
        with Corrida():
            r, lineas = _lineas(lambda: personas.recibir_y_unir({"origen": "checkin", "pantalla": True}, solo_contar=True))
            self.assertEqual(r["motivo"], "dato_de_pantalla")
            self.assertEqual(len(lineas), 1, lineas)
            self.assertIn("modo=solo_cuenta", lineas[0])

    def test_R6_dato_de_sistema_en_recibir_y_unir_en_cuenta_no_escribe(self):
        with Corrida() as c:
            r, lineas = _lineas(lambda: personas.recibir_y_unir(NUEVO_SISTEMA, solo_contar=True))
            self.assertEqual(c.escrituras(), [], "la cuenta no escribe ni la ficha ni la bandeja")
        self.assertEqual(len(lineas), 1, lineas)
        self.assertIn("modo=solo_cuenta", lineas[0])


if __name__ == "__main__":
    unittest.main()
