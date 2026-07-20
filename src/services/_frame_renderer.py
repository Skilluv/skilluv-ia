"""Rendu des frames de code en images PNG via Pillow.

Chaque frame est une image 1280x720 avec :
- Fond sombre (Forge theme : #1c1917)
- Code source en police monospace (JetBrains Mono ou fallback)
- Numéros de ligne à gauche
- Barre de stats en bas (durée, keystrokes, tests, fragments)
- Curseur clignotant simulé sur la dernière position
"""

import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from src.utils.logging import get_logger

logger = get_logger("frame_renderer")

# Dimensions
WIDTH = 1280
HEIGHT = 720
PADDING_X = 24
PADDING_Y = 20
LINE_NUMBER_WIDTH = 48
STATS_BAR_HEIGHT = 40

# Couleurs (Forge theme)
BG_COLOR = (28, 25, 23)           # #1c1917
TEXT_COLOR = (231, 229, 228)      # #e7e5e4
LINE_NUM_COLOR = (120, 113, 108)  # #78716c
STATS_BG_COLOR = (12, 10, 9)     # #0c0a09
STATS_TEXT_COLOR = (168, 162, 158)  # #a8a29e
CURSOR_COLOR = (234, 88, 12)     # #ea580c (Burnt Orange)
ACCENT_COLOR = (37, 99, 235)     # #2563eb (Electric Blue)

# Syntaxe basique — mots-clés colorés
KEYWORD_COLOR = (96, 165, 250)    # #60a5fa blue-400
STRING_COLOR = (74, 222, 128)     # #4ade80 green-400
COMMENT_COLOR = (120, 113, 108)   # #78716c stone-500
NUMBER_COLOR = (251, 191, 36)     # #fbbf24 amber-400

KEYWORDS = {
    "def", "class", "import", "from", "return", "if", "else", "elif",
    "for", "while", "try", "except", "finally", "with", "as", "yield",
    "async", "await", "raise", "pass", "break", "continue", "lambda",
    "and", "or", "not", "in", "is", "True", "False", "None",
    "function", "const", "let", "var", "export", "default", "new",
    "fn", "mut", "pub", "struct", "impl", "use", "mod",
    "func", "package", "type", "interface", "map", "range", "defer",
    "public", "private", "static", "void", "int", "String", "boolean",
}

_font_code = None
_font_stats = None
_font_loaded = False


def _load_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    """Charge les polices. Fallback sur la police par défaut si JetBrains Mono n'est pas trouvée."""
    global _font_code, _font_stats, _font_loaded

    if _font_loaded:
        return _font_code, _font_stats

    _font_loaded = True

    # Essayer JetBrains Mono, puis des polices monospace courantes
    font_candidates = [
        "JetBrainsMono-Regular.ttf",
        "JetBrains Mono Regular Nerd Font Complete.ttf",
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "DejaVuSansMono.ttf",
        "Consolas",
        "Courier New",
    ]

    for font_name in font_candidates:
        try:
            _font_code = ImageFont.truetype(font_name, 14)
            _font_stats = ImageFont.truetype(font_name, 12)
            logger.info("font_loaded", font=font_name)
            return _font_code, _font_stats
        except OSError:
            continue

    # Fallback absolu
    _font_code = ImageFont.load_default()
    _font_stats = ImageFont.load_default()
    logger.warning("using_default_font")
    return _font_code, _font_stats


def _tokenize_line(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Tokenize une ligne de code pour la coloration syntaxique basique."""
    tokens: list[tuple[str, tuple[int, int, int]]] = []

    i = 0
    while i < len(line):
        char = line[i]

        # Commentaires
        if line[i:].startswith("//") or line[i:].startswith("#"):
            tokens.append((line[i:], COMMENT_COLOR))
            break

        # Strings
        if char in ('"', "'", '`'):
            quote = char
            end = line.find(quote, i + 1)
            if end == -1:
                end = len(line) - 1
            token = line[i : end + 1]
            tokens.append((token, STRING_COLOR))
            i = end + 1
            continue

        # Nombres
        if char.isdigit():
            j = i
            while j < len(line) and (line[j].isdigit() or line[j] == "."):
                j += 1
            tokens.append((line[i:j], NUMBER_COLOR))
            i = j
            continue

        # Mots (identifiants / mots-clés)
        if char.isalpha() or char == "_":
            j = i
            while j < len(line) and (line[j].isalnum() or line[j] == "_"):
                j += 1
            word = line[i:j]
            color = KEYWORD_COLOR if word in KEYWORDS else TEXT_COLOR
            tokens.append((word, color))
            i = j
            continue

        # Whitespace et symboles
        tokens.append((char, TEXT_COLOR))
        i += 1

    return tokens


def render_frame(
    code: str,
    frame_index: int,
    total_frames: int,
    stats_text: str | None = None,
) -> bytes:
    """Rend une frame de code en image PNG.

    Retourne les bytes PNG de l'image.
    """
    font_code, font_stats = _load_fonts()

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Zone de code
    code_area_top = PADDING_Y
    code_area_bottom = HEIGHT - STATS_BAR_HEIGHT - 4
    code_area_height = code_area_bottom - code_area_top

    lines = code.split("\n")
    line_height = 18
    max_visible_lines = code_area_height // line_height

    # Scroll : montrer les dernières lignes si le code dépasse
    if len(lines) > max_visible_lines:
        visible_lines = lines[-max_visible_lines:]
        start_line_num = len(lines) - max_visible_lines + 1
    else:
        visible_lines = lines
        start_line_num = 1

    # Dessiner chaque ligne
    for i, line in enumerate(visible_lines):
        y = code_area_top + i * line_height
        line_num = start_line_num + i

        # Numéro de ligne
        draw.text(
            (PADDING_X, y),
            f"{line_num:>3}",
            fill=LINE_NUM_COLOR,
            font=font_code,
        )

        # Séparateur
        sep_x = PADDING_X + LINE_NUMBER_WIDTH - 8
        draw.line([(sep_x, code_area_top), (sep_x, code_area_bottom)], fill=(50, 46, 43), width=1)

        # Code avec coloration syntaxique
        x = PADDING_X + LINE_NUMBER_WIDTH
        tokens = _tokenize_line(line)
        for token_text, color in tokens:
            draw.text((x, y), token_text, fill=color, font=font_code)
            bbox = (
                font_code.getbbox(token_text)
                if hasattr(font_code, "getbbox")
                else (0, 0, len(token_text) * 8, 14)
            )
            x += bbox[2] - bbox[0]

    # Curseur sur la dernière ligne
    if lines:
        last_visible_idx = min(len(visible_lines) - 1, max_visible_lines - 1)
        cursor_y = code_area_top + last_visible_idx * line_height
        last_line = visible_lines[-1] if visible_lines else ""
        cursor_x = PADDING_X + LINE_NUMBER_WIDTH
        if last_line:
            bbox = (
                font_code.getbbox(last_line)
                if hasattr(font_code, "getbbox")
                else (0, 0, len(last_line) * 8, 14)
            )
            cursor_x += bbox[2] - bbox[0]
        # Curseur bloc orange
        if frame_index % 2 == 0:  # Clignotement simulé
            draw.rectangle(
                [cursor_x, cursor_y, cursor_x + 8, cursor_y + line_height - 2],
                fill=CURSOR_COLOR,
            )

    # Barre de stats en bas
    stats_y = HEIGHT - STATS_BAR_HEIGHT
    draw.rectangle([(0, stats_y), (WIDTH, HEIGHT)], fill=STATS_BG_COLOR)

    # Barre de progression
    progress = (frame_index + 1) / max(total_frames, 1)
    progress_width = int(WIDTH * progress)
    draw.rectangle([(0, stats_y), (progress_width, stats_y + 2)], fill=ACCENT_COLOR)

    # Texte stats
    if stats_text:
        draw.text(
            (PADDING_X, stats_y + 12),
            stats_text,
            fill=STATS_TEXT_COLOR,
            font=font_stats,
        )

    # Indicateur de progression à droite
    progress_text = f"{int(progress * 100)}%"
    draw.text(
        (WIDTH - PADDING_X - 40, stats_y + 12),
        progress_text,
        fill=STATS_TEXT_COLOR,
        font=font_stats,
    )

    # Exporter en PNG
    buffer = BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_frames_to_dir(
    events: list[dict],
    output_dir: str,
    stats_text: str | None = None,
) -> int:
    """Rend tous les événements en images PNG dans le répertoire donné.

    Retourne le nombre de frames générées.
    """
    code_state = ""
    frame_count = 0

    for event in events:
        event_type = event.get("type", "")
        content = event.get("content", "")

        if event_type == "insert":
            code_state += content
        elif event_type == "delete":
            delete_count = event.get("count", len(content))
            code_state = code_state[:-delete_count] if delete_count else code_state
        elif event_type == "replace" or event_type == "snapshot":
            code_state = content

        # Rendre la frame en image
        png_data = render_frame(
            code=code_state,
            frame_index=frame_count,
            total_frames=len(events),
            stats_text=stats_text,
        )

        frame_path = os.path.join(output_dir, f"frame_{frame_count:06d}.png")
        with open(frame_path, "wb") as f:
            f.write(png_data)

        frame_count += 1

    return frame_count
