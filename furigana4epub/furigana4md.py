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


def _build_ruby_block(pairs: list[tuple]) -> str:
    """
    Recibe una lista de (kanji_char_o_grupo, lectura) y construye el bloque
    {kanji1kanji2...|lec1|lec2...}
    """
    kanji_part = ''.join(k for k, _ in pairs)
    readings = [r for _, r in pairs]
    return '{' + kanji_part + '|' + '|'.join(readings) + '}'


def _furigana_plain(text: str) -> str:
    """
    Procesa texto plano japonés con yomituki y devuelve el texto
    con furigana en el formato {kanji|lectura}.

    yomituki() devuelve:
      - str            → texto sin furigana (hiragana/katakana/puntuación…)
      - (str, str)     → (segmento_kanji, lectura_hiragana)
    """
    if not text.strip():
        return text

    result = ''
    tokens = list(yt.yomituki(text))

    # Agrupamos tuplas (kanji, lectura) consecutivas en un único bloque.
    # Las cadenas str se emiten directamente.
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, tuple):
            # Acumular tuplas contiguas
            block = [token]
            i += 1
            while i < len(tokens) and isinstance(tokens[i], tuple):
                block.append(tokens[i])
                i += 1
            result += _build_ruby_block(block)
        else:
            result += token
            i += 1

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
