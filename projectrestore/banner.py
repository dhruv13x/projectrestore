# src/create_dump/banner.py

from rich.console import Console
from rich.text import Text
import math
import random
import os

console = Console()

def lerp(a, b, t):
    return a + (b - a) * t

def blend(c1, c2, t):
    # Gemini gamma + wave shaping
    t = t ** 1.47
    t = 0.82 * t + 0.08 * math.sin(3.2 * t)
    r = int(lerp(c1[0], c2[0], t))
    g = int(lerp(c1[1], c2[1], t))
    b = int(lerp(c1[2], c2[2], t))
    return f"#{r:02x}{g:02x}{b:02x}"

def print_logo():
    import os
    import random
    import sys
    import colorsys
    import math
    from rich.console import Console
    from rich.text import Text

    console = Console()

    # --- logo (unchanged) ---
    logo = r"""     
░     
                                   ███                     █████                                █████                               
                                  ░░░                     ░░███                                ░░███                                
 ████████  ████████   ██████      █████  ██████   ██████  ███████   ████████   ██████   █████  ███████    ██████  ████████   ██████ 
░░███░░███░░███░░███ ███░░███    ░░███  ███░░███ ███░░███░░░███░   ░░███░░███ ███░░███ ███░░  ░░░███░    ███░░███░░███░░███ ███░░███
 ░███ ░███ ░███ ░░░ ░███ ░███     ░███ ░███████ ░███ ░░░   ░███     ░███ ░░░ ░███████ ░░█████   ░███    ░███ ░███ ░███ ░░░ ░███████ 
 ░███ ░███ ░███     ░███ ░███     ░███ ░███░░░  ░███  ███  ░███ ███ ░███     ░███░░░   ░░░░███  ░███ ███░███ ░███ ░███     ░███░░░  
 ░███████  █████    ░░██████      ░███ ░░██████ ░░██████   ░░█████  █████    ░░██████  ██████   ░░█████ ░░██████  █████    ░░██████ 
 ░███░░░  ░░░░░      ░░░░░░       ░███  ░░░░░░   ░░░░░░     ░░░░░  ░░░░░      ░░░░░░  ░░░░░░     ░░░░░   ░░░░░░  ░░░░░      ░░░░░░  
 ░███                         ███ ░███                                                                                              
 █████                       ░░██████                                                                                               
░░░░░                         ░░░░░░                                                                                                     
""".strip().split("\n")

    # helper math functions (unchanged)
    def lerp(a, b, t):
        return a + (b - a) * t

    def blend(c1, c2, t):
        # Gemini gamma + wave shaping (unchanged)
        t = t ** 1.47
        t = 0.82 * t + 0.08 * math.sin(3.2 * t)
        r = int(lerp(c1[0], c2[0], t))
        g = int(lerp(c1[1], c2[1], t))
        b = int(lerp(c1[2], c2[2], t))
        return f"#{r:02x}{g:02x}{b:02x}"

    # --- fixed palettes fallback (keeps your original palettes available) ---
    fixed_palettes = [
        [
            (0x2E, 0x7B, 0xEA),
            (0x6C, 0x5B, 0xD8),
            (0xB6, 0x6D, 0xB9),
            (0xE8, 0x8A, 0xA6),
            (0xFF, 0xB6, 0xC1),
        ],
        [
            (0x33, 0xE0, 0xA1),
            (0x19, 0xB6, 0xD8),
            (0x2A, 0xD5, 0x6C),
            (0x15, 0x90, 0xD3),
            (0x0D, 0x75, 0xB4),
        ],
        [
            (0x00, 0xFF, 0xCC),
            (0x00, 0xDD, 0xFF),
            (0x66, 0x99, 0xFF),
            (0xAA, 0x77, 0xFF),
            (0xFF, 0x66, 0xDD),
        ],
        [
            (0x3A, 0x0C, 0xF0),
            (0x66, 0x1B, 0xF6),
            (0x98, 0x2D, 0xFF),
            (0xF2, 0x36, 0xA3),
            (0xFF, 0x73, 0x3F),
        ],
        [
            (0x07, 0x1A, 0x40),
            (0x2E, 0x7B, 0xEA),
            (0x7C, 0x4D, 0xFF),
            (0xFF, 0x6B, 0x6B),
            (0xFF, 0xF1, 0xD6),
        ],
        [
            (0x12, 0xB8, 0xFF),
            (0x2E, 0x7B, 0xEA),
            (0x6C, 0x5B, 0xD8),
            (0xC2, 0x4B, 0xC3),
            (0xFF, 0x88, 0xA8),
        ],
    ]

    # cryptographically-safe RNG (so other random.seed(...) won't affect us)
    _sysrand = random.SystemRandom()

    # If env var is set and numeric -> use fixed palette index (reproducible)
    idx_env = os.getenv("CREATE_DUMP_PALETTE")
    if idx_env is not None:
        try:
            idx = int(idx_env)
            if 0 <= idx < len(fixed_palettes):
                palette = list(fixed_palettes[idx])
                mode = f"fixed[{idx}]"
            else:
                raise ValueError
        except Exception:
            # bad value -> fall through to procedural generation
            palette = None
            mode = "procedural (bad env fallback)"
    else:
        palette = None
        mode = "procedural"

    # If we didn't get a fixed palette, procedurally generate one (practically infinite variations)
    if palette is None:
        # params: how many control colors to generate across gradient
        N = 5

        # choose a "base" hue and spacing; equally spaced hues + small jitter gives wide but harmonious variants
        base_h = _sysrand.random()  # 0..1
        spacing = 1.0 / N

        # choose saturation and value ranges to keep results vivid but not overly bright/dark
        sat_center = 0.72 + (_sysrand.random() - 0.5) * 0.2  # ~0.62..0.82
        val_center = 0.78 + (_sysrand.random() - 0.5) * 0.2  # ~0.68..0.88

        palette = []
        for i in range(N):
            # hue: evenly spaced with slight random jitter
            jitter = (_sysrand.random() - 0.5) * (spacing * 0.6)  # jitter fraction
            h = (base_h + i * spacing + jitter) % 1.0

            # saturation & value with small per-color variation
            s = min(max(sat_center + (_sysrand.random() - 0.5) * 0.18, 0.35), 1.0)
            v = min(max(val_center + (_sysrand.random() - 0.5) * 0.18, 0.35), 1.0)

            # convert HSV -> RGB 0..255
            r_f, g_f, b_f = colorsys.hsv_to_rgb(h, s, v)
            r, g, b = int(round(r_f * 255)), int(round(g_f * 255)), int(round(b_f * 255))

            palette.append((r, g, b))

        # Occasionally bias the palette towards warmer or cooler by adjusting V or S slightly
        if _sysrand.random() < 0.25:
            # shift all values down/up a bit for moody or pastel variants
            delta_v = (_sysrand.random() - 0.5) * 0.18
            new_palette = []
            for (r, g, b) in palette:
                # convert to HSV, adjust v, convert back
                h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                v = min(max(v + delta_v, 0.2), 1.0)
                rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
                new_palette.append((int(round(rr * 255)), int(round(gg * 255)), int(round(bb * 255))))
            palette = new_palette

        mode = "procedural"

    # permute the palette slightly so gradients shift even when endpoints similar
    _sysrand.shuffle(palette)

    # --- print the logo using chosen palette ---
    H = len(logo)
    for i, line in enumerate(logo):
        tline = Text()
        W = len(line)

        for j, ch in enumerate(line):
            raw = (i * 0.72 + j * 0.44)
            t = raw / (H * 0.72 + W * 0.44)

            seg = t * (len(palette) - 1)
            idx = int(seg)
            t2 = seg - idx

            c1 = palette[idx]
            c2 = palette[min(idx + 1, len(palette) - 1)]

            tline.append(ch, style=blend(c1, c2, t2))

        console.print(tline)

    console.print("[dim]🛠️ Secure, atomic, and verified project restoration from snapshots.[/dim]\\n")
