# -*- coding: utf-8 -*-
"""P11-entrada-escribir: el cálculo de la ENTRADA con el modo `escribir` del programa (`personas_entrada.entrada_calculada_escribir`).

La App compara la entrada en su modo `escribir` (`POST /api/fichas/entrada` con `FICHAS_ENTRADA_MODO=escribir`) contra lo que el
programa calcula. En `escribir`, la entrada escribe de verdad, por este orden: la marca `escribiendo` de la fila, lo que la puerta
escribe (el POST o el PATCH de la ficha; y si nace, su renglón de origen en `anotaciones`) y el PATCH final de la fila con `aplicado`
o `descartado`. Antes, el cálculo contestaba 409 `modo_escribir_no_se_calcula` (P11-6, grupo b). Este archivo cubre lo que ahora dice.

Qué garantiza y con qué prueba:
  E1  PAREJA en `escribir`: en cada escenario de `ESCENARIOS_ESCRIBIR`, lo que el cálculo dice (`escrituras`, en forma de la App) es lo que la
      entrada escribió de verdad en el doble, en orden. El id que asigna la base a una ficha nueva se compara como `<nueva>` (el mismo
      marcador que usa el cálculo); las columnas del reloj (`cuando`) no se comparan.
  E2  CERO ESCRITURAS al calcular, en cada escenario de E1 (y en los rechazos).
  E3  RECHAZOS en `escribir`: fila inexistente, igual que la entrada (404), sin escribir.
  E4  FRONTERA (lo que el cálculo NO predice, con 409 y sin escribir): una unión (un aviso `misma_persona` con las dos fichas) y dos o más
      filas procesadas en la misma llamada. En estos casos la entrada escribiría con números que la base asigna o vería lo que la primera
      fila escribió: el cálculo no lo ve, y lo dice.
  E5  FIJADO A MANO: el alta por mensaje de la fila 1, con lo que escribe la entrada escrito a mano en esta prueba (sin llamar al cálculo para
      armar lo esperado): la marca, el POST de la ficha, el renglón de origen con su marcador, y el PATCH final con su `resultado`.
  E6  REGISTRO: el cálculo de `entrada` sigue en `CALCULOS` y su 409 viejo (`modo_escribir_no_se_calcula`) ya no existe en el programa.

Lo que NO ve (declarado, sin medir contra NocoDB real): el cursor de la App (su proceso), las fallas de la base a mitad de la escritura
(el cálculo da por escrito lo que planea), y la rama de unión en `escribir` (E4 la declara como 409, no la predice).
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import base  # noqa: E402
import personas  # noqa: E402
import personas_cuenta  # noqa: E402
import personas_entrada  # noqa: E402
from test_calcular_grupo_b import Corrida, QUIEN, cuerpo_del_calculo, fila  # noqa: E402

MODO = {"FICHAS_ENTRADA_MODO": "escribir"}
MARCADOR = personas.CALCULO_FICHA_NUEVA      # "<nueva>": el número que asigna la base a una ficha que nace
RELOJ = ("cuando",)     # columnas de la hora de escritura: el cálculo y la entrada las escriben con su propio reloj (no se comparan)

# (etiqueta, filas de la bandeja, fila pedida). Todas escriben en `escribir` lo que la entrada escribe de verdad.
ESCENARIOS_ESCRIBIR = [
    ("alta por mensaje pendiente", [fila(1, origen="mensaje", telefono_meta="18095550201", nombre="Entrada Uno")], 1),
    ("origen desconocido (se descarta)", [fila(3, origen="raro", telefono_meta="18095550204", nombre="Entrada Cuatro")], 3),
    ("fila ya contada (no escribe nada)", [fila(4, estado="contado", origen="mensaje", telefono_meta="18095550205")], 4),
    ("escribiendo a medias (se reanuda sin marca)", [fila(5, estado="escribiendo", origen="mensaje", telefono_meta="18095550206",
                                                          nombre="Entrada Seis")], 5),
    ("ficha que ya existe, mismo teléfono", [fila(6, origen="mensaje", telefono_meta="18097770001", nombre_perfil="Persona de prueba 1")], 6),
]
# Rechazo que escribe lo mismo en los dos lados: fila inexistente.
RECHAZOS_ESCRIBIR = [("fila inexistente", [], 9, 404)]


def escrituras_reales(w):
    """Lo que la entrada escribió de verdad, en la forma que el cálculo usa (tabla, método, cuerpo), con el id de la ficha nueva en `<nueva>`."""
    ficha_nueva = max([f.get("Id") or 0 for f in w.doble.tablas[base.T_PERSONAS]] + [0])
    planeadas = []
    for p in w.doble.pedidos:
        if p["metodo"] not in ("POST", "PATCH", "PUT", "DELETE"):
            continue
        cuerpo = copy.deepcopy(p["cuerpo"])
        if isinstance(cuerpo, dict) and cuerpo.get("ficha_id") == ficha_nueva and ficha_nueva:
            cuerpo["ficha_id"] = MARCADOR
        planeadas.append({"tabla": p["ruta"].split("/api/v2/tables/")[1].split("/")[0], "metodo": p["metodo"], "cuerpo": cuerpo})
    filas, sin_valor = personas_cuenta._en_forma_de_la_app(planeadas)
    return filas, sin_valor


def sin_reloj(filas):
    """Las filas del contrato de la App sin las columnas del reloj (lo que el cálculo y la entrada escriben con su propia hora)."""
    return [dict(f, valores={k: v for k, v in f["valores"].items() if k not in RELOJ}) for f in filas]


class EntradaEscribir(unittest.TestCase):

    def test_E1_pareja_en_escribir(self):
        for etiqueta, filas, n in ESCENARIOS_ESCRIBIR:
            with self.subTest(escenario=etiqueta):
                with mock.patch.dict(os.environ, MODO), Corrida(filas) as w:
                    codigo_w, _ = personas_entrada.entrada_fichas(n)
                    filas_reales, sin_valor_reales = escrituras_reales(w)
                with mock.patch.dict(os.environ, MODO), Corrida(filas) as c:
                    codigo_c, datos_c = personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
                    self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió (%s)" % etiqueta)
                self.assertEqual((codigo_w, codigo_c), (200, 200), etiqueta)
                self.assertEqual(sin_reloj(datos_c["escrituras"]), sin_reloj(filas_reales), "E1: el cálculo no dice lo que la entrada escribió (%s)" % etiqueta)
                self.assertEqual(sorted(datos_c["sin_valor"]), sorted(sin_valor_reales), "E1: sin_valor distinto (%s)" % etiqueta)

    def test_E2_cero_escrituras_al_calcular_y_rechazos(self):
        for etiqueta, filas, n in ESCENARIOS_ESCRIBIR:
            with self.subTest(escenario=etiqueta):
                with mock.patch.dict(os.environ, MODO), Corrida(filas) as c:
                    personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
                    self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió")

    def test_E3_rechazo_igual_que_la_entrada_y_sin_escribir(self):
        for etiqueta, filas, n, esperado in RECHAZOS_ESCRIBIR:
            with self.subTest(escenario=etiqueta):
                with mock.patch.dict(os.environ, MODO), Corrida(filas) as w:
                    codigo_w, _ = personas_entrada.entrada_fichas(n)
                    self.assertEqual(w.escrituras(), [], "la entrada escribió en un rechazo")
                with mock.patch.dict(os.environ, MODO), Corrida(filas) as c:
                    codigo_c, _ = personas_cuenta.calcular("entrada", cuerpo_del_calculo(n), QUIEN)
                    self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió")
                self.assertEqual((codigo_w, codigo_c), (esperado, esperado))

    def test_E4_frontera_se_dice_409_y_no_escribe(self):
        # Un aviso: el teléfono ya es de otra ficha con otro nombre. La entrada escribe una fila de aviso en la bandeja (un POST, medido con
        # el doble: `telefono_meta:sin_cambios` con `por_resolver`); el cálculo no predice esa fila y contesta 409, sin escribir.
        # La unión de dos fichas (`misma_persona`) no la alcanza esta siembra: la misma guarda de `_recibir_planeado` la cubre por código.
        # (Medido con el doble: con la siembra sin unión, `a` da `otro_valor` en la ficha 1 y escribe la fila de aviso; con la siembra de unión,
        # `b` da `otro_valor` en la ficha 11. Con `union=True` el teléfono de `a` no existe: es un alta, y ahí el cálculo SÍ coincide, E1.)
        for etiqueta, telefono, nombre, siembra_union in (("aviso, mismo teléfono y otro nombre", "18097770001", "Otra Persona Distinta", False),
                                                          ("aviso, teléfono de la siembra de unión", "18090001101", "Union Dos", True)):
            with self.subTest(escenario=etiqueta):
                aviso = [fila(1, origen="mensaje", telefono_meta=telefono, nombre=nombre)]
                with mock.patch.dict(os.environ, MODO), Corrida(aviso, union=siembra_union) as c:
                    codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
                    self.assertEqual((codigo, datos), (409, {"error": "no_se_calcula_en_escribir"}))
                    self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió con un aviso")
        # Dos filas que procesa la misma llamada: la segunda vería lo que la primera escribió.
        dos = [fila(1, origen="mensaje", telefono_meta="18095550211", nombre="Entrada Once"),
               fila(2, origen="mensaje", telefono_meta="18095550212", nombre="Entrada Doce")]
        with mock.patch.dict(os.environ, MODO), Corrida(dos) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(2), QUIEN)
            self.assertEqual((codigo, datos), (409, {"error": "varias_filas_no_se_calculan"}))
            self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió con dos filas")

    def test_E5_alta_fijada_a_mano(self):
        # Lo que escribe la entrada en `escribir` para el alta de la fila 1 (`Entrada Uno`, mensaje), escrito a mano:
        #   1) la marca de la fila; 2) la ficha nueva (nombre y teléfono dicho); 3) su origen (`mensaje`, quien `sistema`, con la ficha
        #   nueva); 4) el PATCH final de la fila: `aplicado`, con la ficha y el `resultado` de la entrada en `escribir`.
        filas = [fila(1, origen="mensaje", telefono_meta="18095550201", nombre="Entrada Uno")]
        with mock.patch.dict(os.environ, MODO), Corrida(filas) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
        self.assertEqual(codigo, 200)
        esc = datos["escrituras"]
        self.assertEqual([(e["tabla"], e["metodo"]) for e in esc],
                         [("bandeja", "PATCH"), ("personas", "POST"), ("anotaciones", "POST"), ("bandeja", "PATCH")])
        self.assertEqual(esc[0]["valores"], {"estado": "escribiendo"})
        self.assertEqual(esc[1]["valores"]["nombre"], "Entrada Uno")
        self.assertEqual(esc[1]["valores"]["telefono"], "18095550201")
        self.assertEqual((esc[2]["valores"]["clase"], esc[2]["valores"]["valor"], esc[2]["valores"]["quien"]), ("origen", "mensaje", "sistema"))
        self.assertEqual(esc[2]["valores"]["ficha_id"], MARCADOR)
        final = esc[3]["valores"]
        self.assertEqual((final["estado"], final["ficha_id"]), ("aplicado", MARCADOR))
        resultado = json.loads(final["resultado"])
        self.assertEqual((resultado["modo"], resultado["estado"], resultado["accion"], resultado["caso"]), ("escribir", "aplicado", "creada", "ninguna:crea"))
        self.assertIs(resultado["crearia"], False)
        self.assertIsNone(resultado["union"])
        self.assertEqual({k: v["resultado"] for k, v in resultado["valores"].items()}, {"nombre": "guardado", "telefono": "guardado"})
        # Lo que la App no puede saber antes, escrito a mano según `_en_forma_de_la_app` (personas_cuenta.py 402-425): el `Id` de cada POST;
        # el marcador `<nueva>` en la ficha del origen y en la de la bandeja; y las columnas del reloj del origen (`COLUMNAS_DEL_RELOJ`).
        self.assertEqual(datos["sin_valor"], ["anotaciones.POST.Id", "anotaciones.POST.cuando", "anotaciones.POST.dicho_el",
                                              "anotaciones.POST.ficha_id", "bandeja.PATCH.ficha_id", "personas.POST.Id"])

    def test_E6_registro_y_sin_el_409_viejo(self):
        self.assertIn("entrada", personas_cuenta.CALCULOS)
        self.assertFalse(hasattr(personas_entrada, "modo_escribir_no_se_calcula"))
        with open(personas_cuenta.__file__, encoding="utf-8") as f:
            self.assertNotIn("modo_escribir_no_se_calcula", f.read())


if __name__ == "__main__":
    unittest.main()
