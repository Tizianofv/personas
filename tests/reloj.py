# -*- coding: utf-8 -*-
"""El día de hoy, FIJADO, para las pruebas y los generadores de las fotos (la trampa de la fecha, 9-nov-2026).

Dos sitios leen el día de hoy en hora de Santo Domingo y lo escriben o lo usan para decidir:
  · `base.hoy_str()`: la fecha `dicho_el` de la anotación de origen de una ficha (`personas.py`, al crear o unir). La App lo hace igual
    (`S.hoy_str()` en su `personas.py`).
  · `personas._fecha_hora.now(TZ)`: el día que decide qué sesiones cuentan como «por venir» al borrar (`_borrar_reservas`). La App
    tiene el mismo código.
La foto se sacó el 8-nov-2026 con `dicho_el` = «2026-11-08»; corrida el 9-nov, el programa escribía «2026-11-09» y 12 pruebas se
ponían rojas sin cambio de código. El código de producción hace lo que debe (el día de Santo Domingo); lo que cambiaba era la foto.

Aquí el día se FIJA: el programa (y la App, en el generador de la foto) corre con esos dos sitios devolviendo `DIA` en vez del
reloj. `cuando` sigue siendo la hora real y se normaliza como antes (`<ahora>` y `<hora>`).
Frontera declarada: solo esos dos sitios. Cualquier otra lectura del reloj en el programa se comprueba con
`grep -n "date.today\\|datetime.now\\|_fecha_hora.now\\|hoy_str" personas*.py base.py servidor.py`.

Lo que compara la prueba: en la foto y en la comparación, un `dicho_el` igual al día fijado de la corrida se cambia por «<hoy>».
Otro día se queda tal cual, así que si el programa escribe otra fecha, la comparación lo ve (ver la mutación M1 en el reporte).

Uso como lanzador (lo usan las pruebas): `python3 -B tests/reloj.py AAAA-MM-DD` corre `servidor.py` del programa con el día fijado.
"""
import datetime as _datetime
import runpy
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIA_FIJO = "2026-11-08"        # el día en que se sacó la foto; cualquier fecha sirve, pero debe ser ≥ las fechas que mandan los pasos
MARCA_DIA = "<hoy>"


def comando_programa(dia=DIA_FIJO):
    """El comando que arranca `servidor.py` del programa con el día fijado (este mismo archivo como lanzador)."""
    return [sys.executable, "-B", str(Path(__file__).resolve()), dia]


def normalizar_dia(valor, dia=DIA_FIJO):
    """Un `dicho_el` igual al día fijado de esa corrida se cambia por «<hoy>», en los dos lados (la foto y la comparación).
    Cualquier otro valor se deja como está."""
    if isinstance(valor, dict):
        return {k: (MARCA_DIA if k == "dicho_el" and v == dia else normalizar_dia(v, dia)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [normalizar_dia(v, dia) for v in valor]
    return valor


def fijar(dia, *modulos):
    """Hace que `hoy_str` y el `now` de la fecha devuelvan `dia` en los módulos dados (los que tengan esos nombres).
    Solo cambia esos nombres de módulo; el resto del proceso sigue con el reloj real."""
    anio, mes, dd = (int(x) for x in dia.split("-"))

    class _Fija(_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(anio, mes, dd, 12, 0, tzinfo=tz)

    for modulo in modulos:
        if hasattr(modulo, "hoy_str"):
            modulo.hoy_str = lambda: dia
        if hasattr(modulo, "_fecha_hora"):
            modulo._fecha_hora = _Fija


if __name__ == "__main__":
    dia = sys.argv[1]
    sys.path.insert(0, str(RAIZ))
    import base
    import personas
    fijar(dia, base, personas)
    sys.argv = [str(RAIZ / "servidor.py")]
    runpy.run_path(str(RAIZ / "servidor.py"), run_name="__main__")
