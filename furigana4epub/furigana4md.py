#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
furigana4md.py – Añade furigana a un fichero Markdown en japonés
y muestra el resultado por pantalla (stdout).

Formato de salida:
  {曲|ま}がる        (un kanji con hiragana trailing fuera del bloque)
  {友達|とも|だち}   (varios kanji, una lectura por kanji dentro del bloque)

El hiragana/katakana puro queda fuera de las llaves.
"""

import re
import sys

import yomituki as yt


# ---------------------------------------------------------------------------
# Formato de furigana
# ---------------------------------------------------------------------------

def _is_kanji(ch: str) -> bool:
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or  # CJK Unified Ideographs
            0x3400 <= cp <= 0x4DBF or  # CJK Extension A
            0x20000 <= cp <= 0x2A6DF or  # CJK Extension B
            0xF900 <= cp <= 0xFAFF or  # CJK Compatibility Ideographs
            0x2F800 <= cp <= 0x2FA1F)  # CJK Compatibility Supplement


# Tagger N-best para consultar múltiples lecturas de un kanji aislado
_tagger_nbest = yt.Tagger('-N 10')

# Caracteres hiragana/katakana pequeños que NO son mora independiente:
# se fusionan con la mora anterior (ぁぃぅぇぉっゃゅょゎ y sus equivalentes katakana)
_SMALL_KANA = frozenset(
    'ぁぃぅぇぉっゃゅょゎゕゖ'
    'ァィゥェォッャュョヮヵヶ'
)


def _mora_len(s: str) -> int:
    """Cuenta el número de moras fonéticas de una cadena hiragana/katakana.
    Los caracteres pequeños (ょ, ゃ, っ, etc.) no cuentan como mora propia."""
    return sum(1 for ch in s if ch not in _SMALL_KANA)


def _all_readings_for_char(ch: str) -> dict[str, int]:
    """
    Devuelve un diccionario {lectura_hiragana: coste} para un carácter.
    El coste es la posición en el N-best (0 = más probable), de modo que
    lecturas más frecuentes tienen coste más bajo.

    Para hiragana/katakana devuelve {forma_hiragana: 0}.
    """
    if not _is_kanji(ch):
        return {yt.kata2hira(ch): 0}

    readings: dict[str, int] = {}
    for i, word in enumerate(_tagger_nbest(ch)):
        kana = word.feature.kana
        if kana and kana not in ('*', ''):
            hira = yt.kata2hira(str(kana))
            if hira not in readings:
                readings[hira] = i  # primer índice = coste más bajo
    # Fallback si N-best no devuelve nada
    if not readings:
        for token in yt.yomituki(ch):
            if isinstance(token, tuple):
                readings[token[1]] = 0
    return readings if readings else {ch: 0}


def _per_kanji_readings(surface: str, reading: str) -> list[str]:
    """
    Dado un surface (ej. "希望") y su lectura global de MeCab (ej. "きぼう"),
    devuelve la lista de lecturas por carácter (ej. ["き", "ぼう"]).

    Función de coste por segmento:
      dev_moras   = (moras(seg) - ideal_moras)²        ← criterio principal
      dev_chars   = (chars(seg) - ideal_chars)² / 100  ← desempate fino
      dict_pen    = 0 si seg ∈ N-best kanji, 1000 si no
      small_pen   = 500 si seg empieza por kana pequeño (imposible fonético)
      ctx_pen     = 0 si seg == lectura 1-best kanji aislado, 1.0 si no
                    (solo cuando esa lectura es alcanzable en la posición actual)

    Se itera de menor a mayor longitud; ctx_pen rompe empates favoreciendo
    la lectura más probable del kanji aislado según MeCab.
    """
    n = len(surface)
    if n == 1:
        return [reading]

    r_len = len(reading)
    if r_len < n:
        return [reading]

    ideal_moras = _mora_len(reading) / n
    ideal_chars = r_len / n

    valid: list[dict[str, int]] = [_all_readings_for_char(ch) for ch in surface]

    def _solo_reading(char_idx: int) -> str | None:
        ch = surface[char_idx]
        if not _is_kanji(ch):
            return yt.kata2hira(ch)
        tokens = list(yt.tagger(ch))
        if tokens:
            kana = tokens[0].feature.kana
            if kana and kana not in ('*', ''):
                return yt.kata2hira(str(kana))
        return None

    solo = [_solo_reading(i) for i in range(n)]

    best: list[str] | None = None
    best_cost: float = float('inf')

    def search(char_idx: int, pos: int, segments: list[str], cost: float) -> None:
        nonlocal best, best_cost
        if cost >= best_cost:
            return
        if char_idx == n:
            if pos == r_len and cost < best_cost:
                best_cost = cost
                best = segments[:]
            return
        remaining = n - char_idx - 1
        max_end = r_len - remaining
        char_valid = valid[char_idx]
        ctx_read = solo[char_idx]
        ctx_reachable = (
                ctx_read is not None
                and pos + len(ctx_read) <= max_end
                and reading[pos:pos + len(ctx_read)] == ctx_read
        )

        for end in range(pos + 1, max_end + 1):  # menor a mayor
            segment = reading[pos:end]
            # Corte fonéticamente imposible: kana pequeño al inicio
            if segment[0] in _SMALL_KANA:
                continue
            in_dict = segment in char_valid
            dev_moras = (_mora_len(segment) - ideal_moras) ** 2
            dev_chars = (len(segment) - ideal_chars) ** 2 / 100.0
            dict_pen = 0.0 if in_dict else 1000.0
            ctx_pen = (0.0 if segment == ctx_read else 1.0) if ctx_reachable else 0.0
            seg_cost = dev_moras + dev_chars + dict_pen + ctx_pen
            segments.append(segment)
            search(char_idx + 1, end, segments, cost + seg_cost)
            segments.pop()

    search(0, 0, [], 0.0)
    return best if best is not None else [reading]


def _build_ruby_block(surface: str, reading: str) -> str:
    """
    Construye {kanji1kanji2...|lec1|lec2...} dividiendo la lectura
    kanji a kanji cuando es posible.
    """
    per_kanji = _per_kanji_readings(surface, reading)
    return '{' + surface + '|' + '|'.join(per_kanji) + '}'


def _furigana_plain(text: str) -> str:
    """
    Procesa texto plano japonés con yomituki y devuelve el texto
    con furigana en el formato {kanji|lec1|lec2...}.

    yomituki() devuelve:
      - str            → texto sin furigana (hiragana/katakana/puntuación…)
      - (str, str)     → (segmento_kanji, lectura_hiragana)
    """
    if not text.strip():
        return text

    result = ''
    for token in yt.yomituki(text):
        if isinstance(token, tuple):
            surface, reading = token
            result += _build_ruby_block(surface, reading)
        else:
            result += token

    return result


# ---------------------------------------------------------------------------
# Procesado de una línea de Markdown
# ---------------------------------------------------------------------------

# Patrones inline que NO deben ser procesados por MeCab:
#   - código inline:  `...`
#   - negrita/cursiva: **...**  *...*  __...__  _..._
#   - enlaces:  [texto](url)  /  ![alt](url)
#   - HTML inline ya existente: <...>
#   - furigana ya existente: {…|…}
#   - numerales circulados y caracteres especiales no japoneses (①②…㊿, ㍉, etc.)
#   - secuencias de caracteres ASCII/no-CJK (preserva espacios, puntuación, etc.)
_SKIP_PATTERN = re.compile(
    r'(`[^`]*`)'  # código inline
    r'|(\*{1,3}[^*]+\*{1,3})'  # negrita/cursiva *
    r'|(_{1,3}[^_]+_{1,3})'  # negrita/cursiva _
    r'|(!?\[[^]]*]\([^)]*\))'  # enlaces e imágenes
    r'|(<[^>]+>)'  # etiquetas HTML inline
    r'|(\{[^}]+\|[^}]+})'  # furigana ya anotado {x|y}
    r'|([\u2460-\u2473\u3251-\u32BF\u24B6-\u24E9\u3200-\u3247\u1F100-\u1F10C]+)'  # numerales/letras circuladas
    r'|(\d+)'  # dígitos ASCII: siempre como token propio para preservar contexto MeCab
    r'|([^\u3000-\u9FFF\uF900-\uFAFF\U0002F800-\U0002FA1F\u3400-\u4DBF\U00020000-\U0002A6DF\uFF00-\uFFEF0-9]+)'
    # no-japonés sin dígitos (espacios, puntuación ASCII, etc.)
)

# Detecta secuencias de dígitos ASCII puros (p. ej. "40", "2026", "22")
_DIGITS_ONLY_RE = re.compile(r'^\d+$')


def add_furigana_to_text(text: str) -> str:
    """
    Añade furigana a los segmentos de texto plano de una línea Markdown,
    dejando intactos los tokens especiales (código, enlaces, HTML…).

    Los dígitos (ASCII o de ancho completo intercalados en texto japonés)
    se acumulan en el mismo buffer que el texto japonés y se envían juntos
    a MeCab como un único bloque, de modo que el analizador morfológico
    dispone del contexto numérico completo para asignar la lectura correcta
    a los contadores:
      40歳     → 40{歳|さい}
      8月22日  → 8{月|がつ}22{日|にち}
      ３月17日 → ３{月|がつ}17{日|にち}

    El buffer se vuelca únicamente al encontrar un token no numérico
    (código inline, negrita, enlace, HTML, etc.).
    """
    result = ''
    last = 0
    japanese_buffer = ''  # acumula texto japonés + dígitos intercalados

    for m in _SKIP_PATTERN.finditer(text):
        plain = text[last:m.start()]
        if plain:
            japanese_buffer += plain

        skip_text = m.group(0)
        if _DIGITS_ONLY_RE.match(skip_text):
            # Dígito ASCII: se incluye en el buffer para dar contexto numérico
            japanese_buffer += skip_text
        else:
            # Token no numérico: volcar el buffer japonés acumulado
            if japanese_buffer:
                result += _furigana_plain(japanese_buffer)
                japanese_buffer = ''
            result += skip_text
        last = m.end()

    plain = text[last:]
    if plain:
        japanese_buffer += plain
    if japanese_buffer:
        result += _furigana_plain(japanese_buffer)

    return result


# ---------------------------------------------------------------------------
# Procesado de bloques Markdown
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r'^(`{3,}|~{3,})')

# Prefijos estructurales de Markdown que deben preservarse intactos
# (headings, blockquotes, listas, reglas horizontales, etc.)
_MD_PREFIX_RE = re.compile(
    r'^(#{1,6}\s+|>\s*|-\s+|\*\s+|\+\s+|\d+\.\s+|={3,}|-{3,}|\*{3,}|_{3,})'
)


def process_markdown(source: str) -> str:
    """
    Recorre línea a línea el Markdown, aplica furigana al texto
    y deja intactos los bloques de código.
    """
    lines = source.splitlines(keepends=True)
    output_lines = []
    in_code_block = False
    fence_marker = ''

    for line in lines:
        m = _FENCE_RE.match(line)
        if m:
            if not in_code_block:
                in_code_block = True
                fence_marker = m.group(1)
                output_lines.append(line)
            elif line.strip().startswith(fence_marker):
                in_code_block = False
                fence_marker = ''
                output_lines.append(line)
            else:
                output_lines.append(line)
            continue

        if in_code_block:
            output_lines.append(line)
        else:
            eol = ''
            stripped = line
            if line.endswith('\r\n'):
                eol = '\r\n'
                stripped = line[:-2]
            elif line.endswith('\n'):
                eol = '\n'
                stripped = line[:-1]
            elif line.endswith('\r'):
                eol = '\r'
                stripped = line[:-1]
            # Extraer prefijo estructural de Markdown para preservarlo intacto
            pm = _MD_PREFIX_RE.match(stripped)
            if pm:
                prefix = pm.group(0)
                content = stripped[pm.end():]
                output_lines.append(prefix + add_furigana_to_text(content) + eol)
            else:
                output_lines.append(add_furigana_to_text(stripped) + eol)

    return ''.join(output_lines)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Añade furigana a un fichero Markdown en japonés '
                    'y muestra el resultado por stdout.'
    )
    parser.add_argument(
        'file',
        type=str,
        help='Ruta al fichero Markdown de entrada (.md)'
    )
    args = parser.parse_args()

    try:
        with open(args.file, encoding='utf-8') as f:
            source = f.read()
    except FileNotFoundError:
        print(f'Error: no se encuentra el fichero "{args.file}"', file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f'Error al leer el fichero: {e}', file=sys.stderr)
        sys.exit(1)

    result = process_markdown(source)
    print(result, end='')


if __name__ == '__main__':
    main()
