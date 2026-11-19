"""Pasa el texto de un proyecto a los campos de un borrador de cotización."""
from __future__ import annotations

import re
import unicodedata

_UNIDADES = {
    "m2": "m2",
    "m²": "m2",
    "m3": "m3",
    "m³": "m3",
    "ml": "ml",
    "m": "m",
    "un": "un",
    "und": "un",
    "unidad": "un",
    "unidades": "un",
    "kg": "kg",
    "gl": "gl",
    "ha": "ha",
    "hr": "hr",
    "hrs": "hr",
    "h": "hr",
    "dia": "día",
    "dias": "día",
    "días": "día",
}

_CLAVES = {
    "cliente": "cliente",
    "razon social": "cliente",
    "proyecto": "proyecto",
    "obra": "proyecto",
    "asunto": "asunto",
    "titulo": "titulo",
    "iva": "iva",
    "gg": "gg",
    "gastos generales": "gg",
    "utilidad": "utilidad",
    "notas": "notas",
    "condiciones": "notas",
    "notas y condiciones": "notas",
}

_PRECIO_FINAL = re.compile(
    r"^(?P<pre>.*?)(?:\s+|,\s*)\$?\s*(?P<num>\d{1,3}(?:\.\d{3})+|\d{4,})"
    r"(?:[.,](?P<dec>\d{1,2}))?\s*$"
)
_CANT_FINAL = re.compile(
    r"^(?P<desc>.*?)(?:\s+|,\s*)(?P<cant>\d+(?:[.,]\d+)?)\s*(?P<und>[A-Za-zÁÉÍÓÚáéíóú0-9²³]+)?\s*$"
)


def _fold(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "")
    plano = "".join(ch for ch in base if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", plano).strip().lower()


def _num_cl(raw: str) -> float:
    s = (raw or "").strip().replace("$", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", s):
        entero, dec = s.rsplit(",", 1)
        return float(entero.replace(".", "") + "." + dec)
    return float(s.replace(",", "."))


def _precio_de(num: str, dec: str | None) -> float:
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
        entero = num.replace(".", "")
    else:
        entero = num
    if dec:
        return float(f"{entero}.{dec}")
    return float(entero)


def _encabezado(linea: str):
    m = re.match(r"^([^:]{2,40}?)\s*[:\-]\s*(.*)$", linea.strip())
    if not m:
        suelto = re.match(r"^(sin iva|iva\s+\d+(?:[.,]\d+)?\s*%?)$", _fold(linea))
        if suelto:
            return "iva", linea.strip()
        libre = re.match(
            r"^(cliente|proyecto|obra|asunto|título|titulo)\s+(.+)$",
            linea.strip(),
            re.I,
        )
        if libre:
            clave = _CLAVES.get(_fold(libre.group(1)))
            if clave:
                return clave, libre.group(2).strip()
        return None
    clave = _CLAVES.get(_fold(m.group(1)))
    if not clave:
        return None
    return clave, m.group(2).strip()


def _porcentaje(valor: str) -> float | None:
    plano = _fold(valor)
    if plano in {"sin", "no", "exento", "sin iva"} or "sin iva" in plano:
        return 0.0
    m = re.search(r"\d+(?:[.,]\d+)?", valor or "")
    if not m:
        return None
    return float(m.group(0).replace(",", "."))


def _cliente_en_texto(texto: str, clientes) -> tuple[int | None, str]:
    plano = _fold(texto)
    mejor = None
    for cli in clientes:
        nombre = str(cli["razon_social"] or "").strip()
        if len(_fold(nombre)) < 4:
            continue
        if _fold(nombre) in plano:
            if mejor is None or len(nombre) > len(mejor["razon_social"]):
                mejor = cli
    if not mejor:
        return None, ""
    return int(mejor["id"]), str(mejor["razon_social"])


def _partida(linea: str) -> dict | None:
    texto = linea.strip().strip("-").strip()
    if not texto:
        return None
    precio = 0.0
    resto = texto
    hallado = _PRECIO_FINAL.match(texto)
    if hallado and hallado.group("pre").strip():
        precio = _precio_de(hallado.group("num"), hallado.group("dec"))
        resto = hallado.group("pre").strip(" ,")
    desc = resto
    cantidad = 1.0
    unidad = "un"
    cant = _CANT_FINAL.match(resto)
    if cant and (cant.group("desc") or "").strip():
        und = _fold(cant.group("und") or "")
        if und in _UNIDADES or not cant.group("und"):
            desc = cant.group("desc").strip(" ,")
            cantidad = float(cant.group("cant").replace(",", "."))
            unidad = _UNIDADES.get(und, "un")
    if not desc:
        return None
    return {
        "descripcion": desc,
        "unidad": unidad,
        "cantidad": cantidad,
        "precio_unitario": precio,
        "total": round(cantidad * precio, 2),
    }


def interpretar_proyecto(texto: str, clientes) -> dict:
    """Lee el texto libre y devuelve cliente, proyecto, asunto y partidas."""
    crudo = (texto or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not crudo:
        return {"ok": False, "error": "Escriba el proyecto."}

    campos = {
        "cliente": "",
        "proyecto": "",
        "asunto": "",
        "titulo": "",
        "iva": None,
        "gg": None,
        "utilidad": None,
        "notas": "",
    }
    partidas: list[dict] = []
    en_notas = False
    for linea in crudo.split("\n"):
        limpia = linea.strip()
        if not limpia:
            en_notas = False
            continue
        enc = _encabezado(limpia)
        if enc:
            clave, valor = enc
            en_notas = clave == "notas"
            if clave in {"iva", "gg", "utilidad"}:
                campos[clave] = _porcentaje(valor or limpia)
            elif clave == "notas":
                campos["notas"] = valor
            else:
                campos[clave] = valor
            continue
        if en_notas:
            campos["notas"] = (campos["notas"] + "\n" + limpia).strip()
            continue
        item = _partida(limpia)
        if item:
            partidas.append(item)

    cliente_id, cliente_nombre = _cliente_en_texto(campos["cliente"] or crudo, clientes)
    if campos["cliente"] and not cliente_id:
        return {
            "ok": False,
            "error": f"No encontré al cliente «{campos['cliente']}». Escríbalo como está en Clientes.",
        }
    if not cliente_id:
        return {
            "ok": False,
            "error": "Indique el cliente, por ejemplo «Cliente: Salvador Garcés Bernales».",
        }
    if not partidas:
        return {
            "ok": False,
            "error": "Agregue al menos una partida con su precio, por ejemplo «MO, 1 un, 450000».",
        }

    proyecto = campos["proyecto"] or campos["asunto"] or partidas[0]["descripcion"]
    asunto = campos["asunto"] or proyecto
    return {
        "ok": True,
        "error": "",
        "cliente_id": cliente_id,
        "cliente_nombre": cliente_nombre,
        "proyecto": proyecto,
        "asunto": asunto,
        "titulo": campos["titulo"] or cliente_nombre.upper(),
        "gg_pct": campos["gg"],
        "utilidad_pct": campos["utilidad"],
        "iva_pct": campos["iva"],
        "notas": campos["notas"].strip(),
        "items": partidas,
    }
