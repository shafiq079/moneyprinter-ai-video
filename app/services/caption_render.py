"""Plain-text color ranges rendered without HTML or subtitle markup injection."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip


def colored_text_clip(text, spans, params, font_path, max_width):
    font = ImageFont.truetype(font_path, int(params.font_size))
    stroke = int(params.stroke_width)
    padding = max(8, int(params.font_size * .6), stroke * 2)
    available = max(1, int(max_width) - padding * 2)
    lines, line, indices = [], '', []
    for index, char in enumerate(text):
        if char == '\n':
            lines.append((line, indices))
            line, indices = '', []
            continue
        if line and font.getlength(line + char) > available:
            # Prefer word boundaries, while keeping exact source character IDs.
            split = line.rfind(' ')
            if split > 0:
                lines.append((line[:split], indices[:split]))
                line, indices = line[split + 1:], indices[split + 1:]
            else:
                lines.append((line, indices))
                line, indices = '', []
        line += char
        indices.append(index)
    lines.append((line, indices))
    ascent, descent = font.getmetrics()
    height = ascent + descent + int(params.font_size * .25) + stroke * 2
    width = min(int(max_width), max(1, int(max(font.getlength(line) for line, _ in lines))) + padding * 2)
    image = Image.new('RGBA', (width, height * len(lines) + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    background = params.text_background_color
    if background:
        color = '#000000' if background is True else background
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        rounded = params.rounded_subtitle_background
        draw.rounded_rectangle((0, 0, image.width - 1, image.height - 1),
                               radius=int(params.font_size * .4) if rounded else 0,
                               fill=(*rgb, 140 if rounded else 255))
    for row, (line, indices) in enumerate(lines):
        x = (width - font.getlength(line)) / 2
        y = padding + row * height + stroke + ascent
        for offset, (char, index) in enumerate(zip(line, indices)):
            color = next((span['color'] for span in spans if span['start'] <= index < span['end']), params.text_fore_color)
            draw.text((x + font.getlength(line[:offset]), y), char, font=font, anchor='ls',
                      fill=color, stroke_width=stroke, stroke_fill=params.stroke_color)
    return ImageClip(np.array(image))
