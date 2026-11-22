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
  E4  FRONTERA (lo que el cálculo NO predice, con 409 y sin escribir): una unión (un aviso `misma_persona` con las dos fichas), un alta
      con aviso (la clave de su fila lleva el Id que asigna la base) y dos o más filas procesadas en la misma llamada. En estos casos la
      entrada escribiría con números que la base asigna o vería lo que la primera fila escribió: el cálculo no lo ve, y lo dice.
      CAMBIO DEL 21-nov-2026: los avisos de una ficha que ya existe (`por_resolver` o informativos, p. ej. `ligado_por_dictado`) ya NO son
      frontera: la App los escribe (la fila de aviso en la bandeja, y la fila se queda `por_resolver` o `aplicado`), y el cálculo lo predice
      igual (E1 los cubre como escenarios de pareja). Antes, esa parte de E4 esperaba 409; ahora espera lo que escribe la entrada.
  E7  AVISOS COMO LA APP (21-nov-2026): los escenarios de E1 con aviso (ficha existente) dan la misma pareja que la entrada, y la fila
      queda `por_resolver` cuando la App la deja así. Sin prueba contra la App en vivo aquí: la pareja es programa contra programa; el
      contrato con la App va en `tests/test_contrato_entrada_aviso.py` (la App en vivo, en su proceso, con `PERSONAS_APP_RAMA`).
  E8  Aviso informativo `mismo_nombre` con la otra ficha: la fila y la final llevan `otra_ficha_id` (la App lo escribe).
  E9  Un `por_resolver` sin aviso no informativo: 502 `sin_confirmar` y cero escrituras (como `_entrada_confirmado` de la App).
  E10 La fila toma la ficha de su aviso cuando la puerta no la nombra (como la App, `entrada_procesar`).
  E11 Clave única: la fila de aviso que ya existe no se planea otra vez (como la App: busca la clave antes de escribir).
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
import doble_nocodb  # noqa: E402
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
    # 21-nov-2026: avisos de una ficha que ya existe. La App los apunta en la bandeja y deja la fila `por_resolver` (no informativo) o
    # `aplicado` (informativo); el cálculo tiene que decir lo mismo (E7).
    ("aviso: teléfono de otra ficha con otro nombre (por resolver)", [fila(7, origen="mensaje", telefono_meta="18097770001",
                                                                          nombre="Otra Persona Distinta")], 7),
    ("aviso: número dictado de una ficha (ligado por dictado)", [fila(8, origen="mensaje", telefono_dicho="18097770001",
                                                                     nombre="Persona de prueba 1")], 8),
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
        # (a) Un alta con aviso: la fila nace (ficha nueva) y el aviso `mismo_nombre` trae la ficha de otra persona con ese nombre. La clave de
        # la fila de aviso lleva el Id que asigna la base: el cálculo no la predice, dice 409 y no escribe.
        alta_con_aviso = [fila(1, origen="mensaje", telefono_meta="18097770501", nombre="Persona de prueba 1")]
        with mock.patch.dict(os.environ, MODO), Corrida(alta_con_aviso) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual((codigo, datos), (409, {"error": "no_se_calcula_en_escribir"}))
            self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió con un alta con aviso")
        # (b) Una unión (`misma_persona`): la App une las dos fichas con escrituras que el cálculo no planea. Se fuerza la respuesta de la
        # puerta con ese aviso (el doble no tiene una siembra que lo produzca de forma limpia); lo que se prueba es la guarda de
        # `_recibir_planeado`: 409 y cero escrituras.
        una_union = {"estado": "por_resolver", "motivo": None, "ficha_id": 1, "accion": "no_tocada", "valores": {}, "avisos": [
            {"tipo": "misma_persona", "informativo": False, "ficha_id": 1, "otra_ficha_id": 2, "apuntado": False, "texto": "x"}],
            "releida": None, "union": None}
        with mock.patch.dict(os.environ, MODO), mock.patch.object(personas, "_puerta_recibir", return_value=una_union), \
                Corrida([fila(1, origen="mensaje", telefono_meta="18097770001", nombre="Otra")]) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual((codigo, datos), (409, {"error": "no_se_calcula_en_escribir"}))
            self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió con una unión")
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

    def test_E8_informativo_con_dos_fichas_como_la_App(self):
        # 21-nov-2026: `mismo_nombre` (informativo, con la otra ficha) en una ficha que ya existe; la ficha 2 sin nombre hace que la entrada la
        # complete. La fila de aviso lleva `ficha_id` y `otra_ficha_id`, y la fila final de la bandeja también la `otra_ficha_id` (la App).
        informativo = [fila(1, origen="mensaje", telefono_meta="18097770002", nombre="Persona de prueba 1")]
        with mock.patch.dict(os.environ, MODO), Corrida(informativo) as c:
            for ficha in c.doble.tablas[base.T_PERSONAS]:
                if ficha.get("Id") == 2:
                    ficha["nombre"] = None
            codigo_c, datos_c = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió con un aviso informativo")
        with mock.patch.dict(os.environ, MODO), Corrida(informativo) as w:
            for ficha in w.doble.tablas[base.T_PERSONAS]:
                if ficha.get("Id") == 2:
                    ficha["nombre"] = None
            codigo_w, _ = personas_entrada.entrada_fichas(1)
            filas_reales, _ = escrituras_reales(w)
        self.assertEqual((codigo_w, codigo_c), (200, 200))
        self.assertEqual(sin_reloj(datos_c["escrituras"]), sin_reloj(filas_reales), "E8: el cálculo no dice lo que la entrada escribió")
        final = [e for e in datos_c["escrituras"] if e["tabla"] == "bandeja"][-1]["valores"]
        self.assertIsNotNone(final.get("otra_ficha_id"), "la fila final no lleva la otra ficha del aviso")
        self.assertEqual(final.get("estado"), "aplicado")

    def test_E9_por_resolver_sin_aviso_que_una_persona_mire_da_502(self):
        # Como `_entrada_confirmado` de la App: la fila no queda `por_resolver` si ningún aviso no informativo quedó apuntado. La App contesta
        # 502 `sin_confirmar`; el cálculo, lo mismo (no se da por escrito una fila que la App no confirmaría).
        solo_informativo = {"estado": "por_resolver", "motivo": None, "ficha_id": 1, "accion": "completada", "valores": {}, "avisos": [
            {"tipo": "mismo_nombre", "informativo": True, "ficha_id": 1, "otra_ficha_id": 2, "apuntado": True, "texto": "x"}], "releida": None}
        with mock.patch.dict(os.environ, MODO), mock.patch.object(personas, "recibir_y_unir", return_value=solo_informativo), \
                Corrida([fila(1, origen="mensaje", telefono_meta="18097770001", nombre="Otra")]) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
            self.assertEqual((codigo, datos), (502, {"error": "sin_confirmar"}))
            self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió")

    def test_E10_la_fila_toma_la_ficha_de_su_aviso_como_la_App(self):
        # 21-nov-2026: la puerta no nombra ficha (`ficha_id` None) pero un aviso sí: la App toma la del aviso (`entrada_procesar`, la
        # línea `ficha_id is None and escribe`). El cálculo tiene que escribir lo mismo en la fila.
        con_aviso_sin_ficha = {"estado": "por_resolver", "motivo": None, "ficha_id": None, "accion": "no_tocada", "valores": {}, "avisos": [
            {"tipo": "otro_valor", "informativo": False, "ficha_id": 1, "otra_ficha_id": None, "apuntado": True, "texto": "x"}], "releida": None}
        with mock.patch.dict(os.environ, MODO), mock.patch.object(personas, "recibir_y_unir", return_value=con_aviso_sin_ficha), \
                Corrida([fila(1, origen="mensaje", telefono_meta="18097770001", nombre="Otra")]) as c:
            codigo, datos = personas_cuenta.calcular("entrada", cuerpo_del_calculo(1), QUIEN)
        self.assertEqual(codigo, 200)
        final = datos["escrituras"][-1]["valores"]
        self.assertEqual((final["estado"], final["ficha_id"]), ("por_resolver", 1))
        self.assertEqual(c.escrituras(), [], "E2: el cálculo escribió")

    def test_E11_clave_unica_la_fila_de_aviso_no_se_repite(self):
        # 21-nov-2026: la fila de aviso tiene una clave (huella del aviso). Si la misma entrada ya la escribió, el cálculo de la siguiente
        # fila no la planea otra vez: la App busca la clave antes de escribir (`_puerta_apuntar_en_bandeja`), y el cálculo igual.
        # La fila 2 empieza `contado` para que el barrido de la fila 1 no la procese (el barrido toma todas las pendientes): después
        # se vuelve `pendiente` y se pide su entrada, con el mismo dato que ya dejó su aviso.
        def sembrar():
            return [fila(1, origen="mensaje", telefono_meta="18097770001", nombre="Otra Persona Distinta"),
                    fila(2, origen="mensaje", telefono_meta="18097770001", nombre="Otra Persona Distinta", estado="contado")]

        def volver_pendiente(corrida):
            for f in corrida.doble.tablas[doble_nocodb.T_BANDEJA]:
                if f.get("Id") == 2:
                    f["estado"] = "pendiente"

        with mock.patch.dict(os.environ, MODO), Corrida(sembrar()) as w:
            personas_entrada.entrada_fichas(1)                    # la entrada escribe el primer aviso de verdad
            antes = len(w.escrituras())
            volver_pendiente(w)
            codigo_w, _ = personas_entrada.entrada_fichas(2)      # la segunda fila, mismo dato: la App no repite la fila de aviso
            repetidas_en_real = [e for e in w.escrituras()[antes:] if e["tabla"] == "bandeja" and e["metodo"] == "POST"]
        with mock.patch.dict(os.environ, MODO), Corrida(sembrar()) as c:
            personas_entrada.entrada_fichas(1)
            antes_c = len(c.escrituras())
            volver_pendiente(c)
            codigo_c, datos_c = personas_cuenta.calcular("entrada", cuerpo_del_calculo(2), QUIEN)
            self.assertEqual(len(c.escrituras()), antes_c, "E2: el cálculo escribió")
        self.assertEqual((codigo_w, codigo_c), (200, 200))
        self.assertEqual(repetidas_en_real, [], "la App repitió la fila de aviso (no es lo esperado)")
        self.assertTrue([e for e in datos_c["escrituras"] if e["tabla"] == "bandeja" and e["metodo"] == "PATCH"],
                        "el cálculo no planeó la fila 2: la prueba no compara nada")
        bandeja_nueva = [e for e in datos_c["escrituras"] if e["tabla"] == "bandeja" and e["metodo"] == "POST"]
        self.assertEqual(bandeja_nueva, [], "el cálculo planea otra fila de aviso igual a la que ya existe")


if __name__ == "__main__":
    unittest.main()
