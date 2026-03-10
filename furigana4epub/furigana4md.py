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


def _per_kanji_readings(surface: str, reading: str) -> list[str]:
    """
    Dado un surface que puede contener varios kanji (ej. "友達", "ともだち"),
    devuelve una lista con la lectura de cada kanji individual.

    Estrategia: para cada carácter de surface, si es kanji se le pregunta a
    MeCab su lectura; si es hiragana/katakana ya conocemos su valor. Luego
    se consume la lectura global de izquierda a derecha para repartirla.

    Si la alineación falla se devuelve la lectura completa como único elemento.
    """
    # Descomponemos surface en segmentos: kanji vs. no-kanji
    segments: list[tuple[str, str | None]] = []  # (char, lectura_individual o None)
    for ch in surface:
        if _is_kanji(ch):
            # Pedir a MeCab la lectura de este kanji aislado
            tokens_ch = list(yt.yomituki(ch))
            if tokens_ch and isinstance(tokens_ch[0], tuple):
                segments.append((ch, tokens_ch[0][1]))
            else:
                segments.append((ch, None))
        else:
            # Hiragana/katakana: su propia lectura es el carácter en hiragana
            segments.append((ch, yt.kata2hira(ch)))

    # Intentamos consumir `reading` de izquierda a derecha asignando cada
    # segmento a su lectura esperada dentro de la lectura global.
    result: list[str] = []
    pos = 0
    ok = True
    for ch, seg_reading in segments:
        if seg_reading is None:
            ok = False
            break
        if reading[pos:pos + len(seg_reading)] == seg_reading:
            result.append(seg_reading)
            pos += len(seg_reading)
        else:
            ok = False
            break

    if ok and pos == len(reading):
        return result
    # Fallback: lectura completa como un único bloque
    return [reading]


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
_SKIP_PATTERN = re.compile(
    r'(`[^`]*`)'  # código inline
    r'|(\*{1,3}[^*]+\*{1,3})'  # negrita/cursiva *
    r'|(_{1,3}[^_]+_{1,3})'  # negrita/cursiva _
    r'|(!?\[[^]]*]\([^)]*\))'  # enlaces e imágenes
    r'|(<[^>]+>)'  # etiquetas HTML inline
    r'|(\{[^}]+\|[^}]+})'  # furigana ya anotado {x|y}
)


def add_furigana_to_text(text: str) -> str:
    """
    Añade furigana a los segmentos de texto plano de una línea Markdown,
    dejando intactos los tokens especiales (código, enlaces, HTML…).
    """
    result = ''
    last = 0
    for m in _SKIP_PATTERN.finditer(text):
        plain = text[last:m.start()]
        if plain:
            result += _furigana_plain(plain)
        result += m.group(0)
        last = m.end()
    plain = text[last:]
    if plain:
        result += _furigana_plain(plain)
    return result


# ---------------------------------------------------------------------------
# Procesado de bloques Markdown
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r'^(`{3,}|~{3,})')


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
