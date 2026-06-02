from pathlib import Path
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup
import markdown


ROOT = Path(__file__).resolve().parent.parent
MD_FILE = ROOT /  "assets" /"help.md"
OUT_FILE = ROOT / "assets" / "help.png"

WIDTH = 1200
PADDING = 48
LINE_HEIGHT = 34
TITLE_HEIGHT = 54
SECTION_HEIGHT = 44
TABLE_CELL_PADDING_X = 16
TABLE_CELL_PADDING_Y = 10

BG = (248, 250, 252)
CARD_BG = (255, 255, 255)
TEXT = (30, 41, 59)
MUTED = (100, 116, 139)
BORDER = (226, 232, 240)


def load_font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


FONT_TITLE = load_font(34, True)
FONT_H2 = load_font(26, True)
FONT_TEXT = load_font(21)
FONT_SMALL = load_font(19)
FONT_TABLE_HEAD = load_font(20, True)
FONT_TABLE = load_font(19)


def text_size(draw: ImageDraw.ImageDraw, text: str, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width):
    if not text:
        return [""]

    lines = []
    current = ""

    for char in text:
        test = current + char
        w, _ = text_size(draw, test, font)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = char

    if current:
        lines.append(current)

    return lines


def parse_markdown():
    html = markdown.markdown(MD_FILE.read_text(encoding="utf-8"), extensions=["tables"])
    soup = BeautifulSoup(html, "html.parser")
    blocks = []

    for el in soup.children:
        if not getattr(el, "name", None):
            continue

        if el.name == "h1":
            blocks.append(("h1", el.get_text(strip=True)))
        elif el.name == "h2":
            blocks.append(("h2", el.get_text(strip=True)))
        elif el.name == "p":
            blocks.append(("p", el.get_text(strip=True)))
        elif el.name == "ul":
            items = [li.get_text(strip=True) for li in el.find_all("li")]
            blocks.append(("ul", items))
        elif el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            blocks.append(("table", rows))

    return blocks


def estimate_height(blocks):
    dummy = Image.new("RGB", (WIDTH, 100), BG)
    draw = ImageDraw.Draw(dummy)
    y = PADDING

    for kind, content in blocks:
        if kind == "h1":
            y += TITLE_HEIGHT + 18
        elif kind == "h2":
            y += SECTION_HEIGHT + 12
        elif kind == "p":
            lines = wrap_text(draw, content, FONT_TEXT, WIDTH - PADDING * 2)
            y += len(lines) * LINE_HEIGHT + 16
        elif kind == "ul":
            for item in content:
                lines = wrap_text(draw, "• " + item, FONT_TEXT, WIDTH - PADDING * 2)
                y += len(lines) * LINE_HEIGHT
            y += 18
        elif kind == "table":
            if not content:
                continue

            col_count = len(content[0])
            usable_width = WIDTH - PADDING * 2
            col_widths = [usable_width // col_count] * col_count

            for row in content:
                max_lines = 1
                for i, cell in enumerate(row):
                    font = FONT_TABLE_HEAD if row == content[0] else FONT_TABLE
                    lines = wrap_text(draw, cell, font, col_widths[i] - TABLE_CELL_PADDING_X * 2)
                    max_lines = max(max_lines, len(lines))
                y += max_lines * 28 + TABLE_CELL_PADDING_Y * 2
            y += 20

    return y + PADDING


def draw_table(draw, x, y, rows):
    if not rows:
        return y

    col_count = len(rows[0])
    usable_width = WIDTH - PADDING * 2

    if col_count == 3:
        col_widths = [220, 560, usable_width - 220 - 560]
    else:
        col_widths = [usable_width // col_count] * col_count

    for row_idx, row in enumerate(rows):
        font = FONT_TABLE_HEAD if row_idx == 0 else FONT_TABLE

        wrapped_cells = []
        max_lines = 1

        for i, cell in enumerate(row):
            lines = wrap_text(draw, cell, font, col_widths[i] - TABLE_CELL_PADDING_X * 2)
            wrapped_cells.append(lines)
            max_lines = max(max_lines, len(lines))

        row_height = max_lines * 28 + TABLE_CELL_PADDING_Y * 2

        bg = (241, 245, 249) if row_idx == 0 else CARD_BG
        draw.rectangle([x, y, x + usable_width, y + row_height], fill=bg, outline=BORDER)

        cx = x
        for i, lines in enumerate(wrapped_cells):
            draw.rectangle([cx, y, cx + col_widths[i], y + row_height], outline=BORDER)

            ty = y + TABLE_CELL_PADDING_Y
            for line in lines:
                draw.text(
                    (cx + TABLE_CELL_PADDING_X, ty),
                    line,
                    font=font,
                    fill=TEXT if row_idx == 0 else MUTED,
                )
                ty += 28

            cx += col_widths[i]

        y += row_height

    return y + 20


def render():
    blocks = parse_markdown()
    height = estimate_height(blocks)

    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    y = PADDING

    for kind, content in blocks:
        if kind == "h1":
            draw.text((PADDING, y), content, font=FONT_TITLE, fill=TEXT)
            y += TITLE_HEIGHT + 18

        elif kind == "h2":
            draw.text((PADDING, y), content, font=FONT_H2, fill=TEXT)
            y += SECTION_HEIGHT + 12

        elif kind == "p":
            lines = wrap_text(draw, content, FONT_TEXT, WIDTH - PADDING * 2)
            for line in lines:
                draw.text((PADDING, y), line, font=FONT_TEXT, fill=MUTED)
                y += LINE_HEIGHT
            y += 16

        elif kind == "ul":
            for item in content:
                lines = wrap_text(draw, "• " + item, FONT_TEXT, WIDTH - PADDING * 2)
                for line in lines:
                    draw.text((PADDING, y), line, font=FONT_TEXT, fill=MUTED)
                    y += LINE_HEIGHT
            y += 18

        elif kind == "table":
            y = draw_table(draw, PADDING, y, content)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_FILE)
    print(f"generated: {OUT_FILE}")


if __name__ == "__main__":
    render()