#!/usr/bin/env python3
"""Helper standalone que transcribe UN chunk de audio.

Se ejecuta como subprocess para poder ser matado por timeout si mlx-whisper
se cuelga (no se puede interrumpir desde un thread Python).

Uso: transcribe_chunk.py <audio_path> <model> <language> <backend> <out_path>
"""

import os
import sys

# Asegurar que se importan los modulos del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backends.whisper import _transcribe_single


def main():
    if len(sys.argv) != 6:
        print("Uso: transcribe_chunk.py <audio> <model> <language> <backend> <out>",
              file=sys.stderr)
        sys.exit(2)

    audio_path = sys.argv[1]
    model = sys.argv[2]
    language = sys.argv[3]
    backend = sys.argv[4]
    out_path = sys.argv[5]

    text = _transcribe_single(audio_path, model, language, backend)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
