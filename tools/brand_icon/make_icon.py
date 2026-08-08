"""Generate the SmartHomeSec brand icon shipped in custom_components/smarthomesec/brand/.

Home Assistant 2026.3+ serves brand images straight out of a custom
integration's brand/ folder, ahead of the brands CDN – so this needs no PR to
home-assistant/brands. See tools/brand_icon/README.txt.

Original artwork (shield + house): no vendor logo is redistributed. Drawn at 4x
and downscaled, because PIL's polygon fill has no antialiasing.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent

# Light theme: a medium navy-blue that still reads on HA's near-white cards.
# Dark theme: the same hue lifted, so the shield doesn't sink into the card.
NAVY = (23, 84, 126, 255)
NAVY_DARK = (56, 141, 198, 255)
WHITE = (255, 255, 255, 255)  # house
AMBER = (255, 176, 32, 255)   # "armed" indicator

SS = 4  # supersampling factor


def quad_bezier(p0, p1, p2, steps=60):
    """Points along a quadratic bezier – used for the shield's tapered sides."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return out


def shield_points(size):
    """Classic shield: flat rounded top, sides tapering to a point at the bottom."""
    m = size * 0.02          # margin – keep it tight, the icon must be trimmed
    w = size - 2 * m
    h = size - 2 * m
    left, right = m, m + w
    top, bottom = m, m + h
    r = w * 0.10             # top corner radius
    shoulder = top + h * 0.38  # where the straight sides end and the taper starts
    # Control point high on the side keeps the taper straight for longer, so the
    # silhouette reads as a shield and not as a rounded badge.
    ctrl_y = bottom - h * 0.30

    pts = [(left + r, top)]
    pts += [(right - r, top)]
    # top-right corner
    pts += quad_bezier((right - r, top), (right, top), (right, top + r), 12)
    pts += [(right, shoulder)]
    # right taper to the bottom point
    pts += quad_bezier((right, shoulder), (right, ctrl_y), (size / 2, bottom), 48)
    # left taper back up
    pts += quad_bezier((size / 2, bottom), (left, ctrl_y), (left, shoulder), 48)
    pts += [(left, top + r)]
    # top-left corner
    pts += quad_bezier((left, top + r), (left, top), (left + r, top), 12)
    return pts


def house_points(size):
    """Roof polygon + body rect + door rect, sitting in the shield's upper half."""
    cx = size / 2
    roof_w = size * 0.44
    roof_top = size * 0.21
    roof_bottom = size * 0.42
    body_w = size * 0.30
    body_bottom = size * 0.60

    roof = [
        (cx, roof_top),
        (cx + roof_w / 2, roof_bottom),
        (cx - roof_w / 2, roof_bottom),
    ]
    body = [
        cx - body_w / 2,
        roof_bottom - size * 0.012,
        cx + body_w / 2,
        body_bottom,
    ]
    door_w = size * 0.10
    door = [cx - door_w / 2, body_bottom - size * 0.15, cx + door_w / 2, body_bottom]
    return roof, body, door


def draw_icon(size: int, shield=NAVY) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.polygon(shield_points(big), fill=shield)

    roof, body, door = house_points(big)
    d.polygon(roof, fill=WHITE)
    d.rectangle(body, fill=WHITE)
    d.rectangle(door, fill=shield)

    # "armed" indicator under the house, in the shield's taper
    dot_r = big * 0.052
    cy = big * 0.735
    d.ellipse(
        [big / 2 - dot_r, cy - dot_r, big / 2 + dot_r, cy + dot_r],
        fill=AMBER,
    )

    return img.resize((size, size), Image.LANCZOS)


def preview(light: Image.Image, dark: Image.Image) -> Image.Image:
    """How it actually reads: on HA's light card, and the dark variant on dark."""
    w, h = 780, 260
    img = Image.new("RGBA", (w, h), (250, 250, 250, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([w // 2, 0, w, h], fill=(17, 20, 23, 255))  # HA dark theme card

    for x_off, icon in ((0, light), (w // 2, dark)):
        img.alpha_composite(icon.resize((140, 140), Image.LANCZOS), (x_off + 24, 60))
        img.alpha_composite(icon.resize((64, 64), Image.LANCZOS), (x_off + 190, 60))
        img.alpha_composite(icon.resize((40, 40), Image.LANCZOS), (x_off + 270, 72))
        img.alpha_composite(icon.resize((32, 32), Image.LANCZOS), (x_off + 322, 76))
        img.alpha_composite(icon.resize((24, 24), Image.LANCZOS), (x_off + 362, 80))
        # the size HA actually uses in the integrations list, in situ
        d.rounded_rectangle(
            [x_off + 190, 140, x_off + 370, 200],
            radius=10,
            fill=(255, 255, 255, 255) if x_off == 0 else (36, 41, 46, 255),
        )
        img.alpha_composite(icon.resize((40, 40), Image.LANCZOS), (x_off + 202, 150))
        d.text(
            (x_off + 252, 163),
            "SmartHomeSec",
            fill=(30, 30, 30) if x_off == 0 else (235, 235, 235),
        )
    return img


if __name__ == "__main__":
    icon = draw_icon(256)
    icon.save(OUT / "icon.png", optimize=True)
    draw_icon(512).save(OUT / "icon@2x.png", optimize=True)

    dark = draw_icon(256, NAVY_DARK)
    dark.save(OUT / "dark_icon.png", optimize=True)
    draw_icon(512, NAVY_DARK).save(OUT / "dark_icon@2x.png", optimize=True)

    preview(icon, dark).convert("RGB").save(OUT / "preview.png", optimize=True)
    print("wrote icon.png, icon@2x.png, dark_icon.png, dark_icon@2x.png, preview.png")
