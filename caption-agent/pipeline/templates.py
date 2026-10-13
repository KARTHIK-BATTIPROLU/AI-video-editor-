"""The four caption templates (MASTER_PROMPT §5).

These param objects are written into props.json and consumed by Captions.tsx.
``defaultPosY`` is the fallback vertical placement used by layout_captions when
no safe zone covers a page; it is NOT sent inside the props ``template`` block.
"""

TEMPLATES = {
    "punch":   {"font": "Anton",         "sizePx": 46, "weight": 400, "upper": True,
                "perPage": 3, "anim": "pop",    "baseColor": "#ffffff",
                "activeColor": "#d8ff3e", "enterMs": 320, "defaultPosY": 0.62},
    "karaoke": {"font": "Archivo",       "sizePx": 30, "weight": 900, "upper": False,
                "perPage": 5, "anim": "fill",   "baseColor": "rgba(255,255,255,.55)",
                "activeColor": "#46e8ff", "enterMs": 320, "defaultPosY": 0.78},
    "flyin":   {"font": "Archivo Black", "sizePx": 38, "weight": 400, "upper": False,
                "perPage": 3, "anim": "fly",    "baseColor": "#ffffff",
                "activeColor": "#ff4d8d", "enterMs": 320, "defaultPosY": 0.50},
    "glitch":  {"font": "JetBrains Mono", "sizePx": 30, "weight": 800, "upper": True,
                "perPage": 2, "anim": "glitch", "baseColor": "#eafff0",
                "activeColor": "#7fffa0", "enterMs": 320, "defaultPosY": 0.40},
}

# Keys that belong in the props.json ``template`` block (the rest are layout hints).
TEMPLATE_PROPS_KEYS = (
    "font", "sizePx", "weight", "upper", "anim", "baseColor", "activeColor", "enterMs",
)


def template_props(template_id: str) -> dict:
    """Return the §6 ``template`` block for a given template id."""
    t = TEMPLATES[template_id]
    block = {"id": template_id}
    block.update({k: t[k] for k in TEMPLATE_PROPS_KEYS})
    return block
