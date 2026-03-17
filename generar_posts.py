#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Float Chile — Generador de 50 posts para Instagram
Usa Claude API para copies y Playwright para renderizar HTML como PNG 1080×1080.

Uso:
    export ANTHROPIC_API_KEY="tu_clave"
    pip install anthropic playwright
    playwright install chromium
    python3 generar_posts.py
"""

import os
import sys
import json
import base64
import html as html_module
from pathlib import Path
from collections import Counter

try:
    import anthropic
except ImportError:
    print("Instalando anthropic...")
    os.system(f"{sys.executable} -m pip install anthropic -q")
    import anthropic

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Instalando playwright...")
    os.system(f"{sys.executable} -m pip install playwright -q")
    os.system("playwright install chromium")
    from playwright.sync_api import sync_playwright

# ─── RUTAS ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
FOTOS_DIR = BASE_DIR / "Fotos Float"
OUTPUT_DIR = BASE_DIR / "output" / "float_posts"
LOGO_PATH = FOTOS_DIR / "Logo.svg"

# ─── MARCA ────────────────────────────────────────────────────────────────────

BRAND_COLORS = ["#0db6c7", "#472172", "#19a1b3", "#f2bba0"]

CATEGORIES = {
    "flotacion": {
        "count": 15,
        "label": "flotación",
        "benefits": (
            "desconexión total, silencio, ausencia de gravedad, "
            "reducción de cortisol, sueño profundo, reseteo mental"
        ),
    },
    "masajes": {
        "count": 15,
        "label": "masajes y recuperación corporal",
        "benefits": (
            "relajación muscular profunda, presencia corporal, "
            "recuperación activa, cuidado consciente del cuerpo"
        ),
    },
    "mindfulness": {
        "count": 10,
        "label": "mindfulness",
        "benefits": (
            "regulación emocional, atención plena, pausa activa, "
            "herramienta cotidiana no esotérica"
        ),
    },
    "fire_ice": {
        "count": 10,
        "label": "fire & ice (contraste térmico)",
        "benefits": (
            "activación del sistema nervioso, vitalidad, circulación, "
            "claridad mental, ritual de contraste calor-frío"
        ),
    },
}

COPY_SYSTEM_PROMPT = (
    "Eres copywriter de Float Chile, centro de bienestar premium en Santiago.\n"
    "Escribes en español, tuteo, tono sereno y sofisticado.\n"
    "Sin clichés de wellness, sin exclamaciones, sin frases motivacionales vacías.\n"
    "El copy debe sentirse humano, específico y verdadero.\n"
    "El cliente ideal es un profesional urbano 30-45 años, estresado, "
    "que busca desconexión real, no relajación superficial.\n"
    "Frase principal: máximo 7 palabras, impactante, sin punto final.\n"
    "Frase secundaria: máximo 15 palabras, más descriptiva, opcional."
)

MODEL = "claude-sonnet-4-20250514"

# ─── FOTOS ────────────────────────────────────────────────────────────────────

def listar_fotos() -> list[Path]:
    exts = {".jpg", ".jpeg", ".png"}
    return sorted(
        p for p in FOTOS_DIR.iterdir()
        if p.suffix.lower() in exts and "logo" not in p.name.lower()
    )


def a_data_uri(path: Path) -> str:
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
    mime = mime_map.get(path.suffix.lower().lstrip("."), "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def svg_a_data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/svg+xml;base64,{data}"


def asignar_fotos(fotos: list[Path], posts: list[dict]) -> None:
    """Asigna fotos a posts de forma temática y rotativa."""
    flotacion_kw = {"camara", "cámara", "pod", "float15", "float16", "float20", "float21"}
    fire_kw = {"sauna", "fuego", "fire", "ice", "hielo", "agua"}

    pools: dict[str, list[Path]] = {"flotacion": [], "fire_ice": [], "general": []}
    for p in fotos:
        name = p.name.lower()
        if any(k in name for k in flotacion_kw):
            pools["flotacion"].append(p)
        elif any(k in name for k in fire_kw):
            pools["fire_ice"].append(p)
        else:
            pools["general"].append(p)

    counters: dict[str, int] = {}
    for post in posts:
        cat = post["category"]
        pool = pools.get(cat, []) or pools["general"] or fotos
        if not pool:
            pool = fotos
        idx = counters.get(cat, 0) % len(pool)
        counters[cat] = idx + 1
        post["foto"] = pool[idx]


# ─── COPIES ───────────────────────────────────────────────────────────────────

def generar_copies(client: anthropic.Anthropic, posts: list[dict]) -> None:
    """Genera copies para todos los posts en lotes de 25."""
    print(f"\nGenerando copies para {len(posts)} posts...")

    def procesar_lote(lote: list[dict]) -> list[dict]:
        items = "\n".join(
            f'{i+1}. Tema: {p["label"]} | Beneficios: {p["benefits"]}'
            for i, p in enumerate(lote)
        )
        mensaje = (
            f"Genera copies para {len(lote)} posts de Instagram.\n"
            f"Para cada uno devuelve JSON con 'principal' y 'secundaria'.\n"
            f"Responde ÚNICAMENTE con un JSON array de {len(lote)} objetos.\n\n"
            f"Posts:\n{items}\n\n"
            f'Formato: [{{"principal": "...", "secundaria": "..."}}, ...]'
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=COPY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje}],
        )
        texto = resp.content[0].text.strip()
        # Limpiar bloque markdown si existe
        if "```" in texto:
            partes = texto.split("```")
            for parte in partes:
                parte = parte.strip()
                if parte.startswith("json"):
                    parte = parte[4:].strip()
                if parte.startswith("["):
                    texto = parte
                    break
        # Encontrar el array JSON
        inicio = texto.find("[")
        fin = texto.rfind("]") + 1
        if inicio >= 0 and fin > inicio:
            texto = texto[inicio:fin]
        return json.loads(texto)

    lote_size = 25
    for i in range(0, len(posts), lote_size):
        lote = posts[i : i + lote_size]
        tries = 0
        while tries < 3:
            try:
                copies = procesar_lote(lote)
                for post, copy in zip(lote, copies):
                    post["principal"] = copy.get("principal", "El silencio también descansa")
                    post["secundaria"] = copy.get("secundaria") or ""
                print(f"  ✓ Lote {i//lote_size + 1}: {len(copies)} copies")
                break
            except Exception as e:
                tries += 1
                print(f"  ✗ Error lote {i//lote_size + 1} (intento {tries}): {e}")
                if tries == 3:
                    # Fallback copies
                    for post in lote:
                        post["principal"] = f"Float Chile — {post['label']}"
                        post["secundaria"] = post["benefits"].split(",")[0].strip().capitalize()


# ─── LAYOUTS HTML ─────────────────────────────────────────────────────────────

FONT_IMPORT = '@import url("https://fonts.googleapis.com/css2?family=Josefin+Sans:ital,wght@0,300;0,400;0,700&display=swap");'


def _h(text: str) -> str:
    """Escapa caracteres HTML especiales."""
    return html_module.escape(str(text))


def layout_1(foto: str, logo: str, principal: str, secundaria: str, color: str) -> str:
    """Foto full + overlay oscuro + texto centrado + logo esquina inferior derecha."""
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT_IMPORT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.ov{{position:absolute;inset:0;background:rgba(0,0,0,.50)}}
.ct{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
     justify-content:center;padding:100px;text-align:center;color:#fff}}
.pr{{font-size:52px;font-weight:700;line-height:1.2;margin-bottom:24px;
     text-shadow:2px 2px 10px rgba(0,0,0,.85)}}
.sec{{font-size:24px;font-weight:300;line-height:1.55;max-width:720px;
      text-shadow:2px 2px 8px rgba(0,0,0,.8)}}
.logo{{position:absolute;bottom:44px;right:48px;width:110px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="bg"></div><div class="ov"></div>
<div class="ct"><p class="pr">{_h(principal)}</p>{sec}</div>
<img class="logo" src="{logo}" alt="Float Chile">
</body></html>"""


def layout_2(foto: str, logo: str, principal: str, secundaria: str, color: str) -> str:
    """Foto full + gradiente lateral desde color de marca + texto izquierda."""
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    # color hex → agregar opacidad con 8-digit hex (soportado en Chromium)
    c80 = color + "cc"   # 80% opacidad
    c50 = color + "80"   # 50% opacidad
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT_IMPORT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.gr{{position:absolute;inset:0;
     background:linear-gradient(to right,{c80} 0%,{c50} 45%,transparent 72%)}}
.ct{{position:absolute;inset:0;display:flex;flex-direction:column;
     align-items:flex-start;justify-content:center;padding:80px;color:#fff;max-width:580px}}
.pr{{font-size:48px;font-weight:700;line-height:1.2;margin-bottom:20px;
     text-shadow:2px 2px 10px rgba(0,0,0,.8)}}
.sec{{font-size:22px;font-weight:300;line-height:1.55;
      text-shadow:2px 2px 8px rgba(0,0,0,.8)}}
.logo{{position:absolute;bottom:44px;left:48px;width:100px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="bg"></div><div class="gr"></div>
<div class="ct"><p class="pr">{_h(principal)}</p>{sec}</div>
<img class="logo" src="{logo}" alt="Float Chile">
</body></html>"""


def layout_3(foto: str, logo: str, principal: str, secundaria: str, color: str) -> str:
    """Split: mitad izquierda color sólido + mitad derecha foto."""
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT_IMPORT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;display:flex}}
.izq{{width:50%;height:100%;background:{color};display:flex;flex-direction:column;
      justify-content:center;align-items:flex-start;padding:64px;position:relative}}
.der{{width:50%;height:100%;background:url('{foto}') center/cover no-repeat}}
.pr{{font-size:44px;font-weight:700;color:#f2bba0;line-height:1.25;margin-bottom:20px;
     text-shadow:1px 1px 6px rgba(0,0,0,.6)}}
.sec{{font-size:20px;font-weight:300;color:#fff;line-height:1.55;
      text-shadow:1px 1px 4px rgba(0,0,0,.6)}}
.logo{{position:absolute;bottom:40px;left:64px;width:90px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="izq">
  <p class="pr">{_h(principal)}</p>{sec}
  <img class="logo" src="{logo}" alt="Float Chile">
</div>
<div class="der"></div>
</body></html>"""


def layout_4(foto: str, logo: str, principal: str, secundaria: str, color: str) -> str:
    """Foto full sin overlay general + caja semitransparente centrada con borde de marca."""
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT_IMPORT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.caja{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
       width:780px;background:rgba(0,0,0,.70);border:1.5px solid {color};
       padding:72px 64px;text-align:center;color:#fff}}
.pr{{font-size:46px;font-weight:700;line-height:1.2;margin-bottom:22px;
     text-shadow:2px 2px 10px rgba(0,0,0,.85)}}
.sec{{font-size:21px;font-weight:300;line-height:1.55;
      text-shadow:2px 2px 8px rgba(0,0,0,.8)}}
.logo{{display:block;margin:32px auto 0;width:95px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="bg"></div>
<div class="caja">
  <p class="pr">{_h(principal)}</p>{sec}
  <img class="logo" src="{logo}" alt="Float Chile">
</div>
</body></html>"""


LAYOUTS = [layout_1, layout_2, layout_3, layout_4]


# ─── RENDERIZADO ──────────────────────────────────────────────────────────────

def renderizar_posts(posts: list[dict]) -> tuple[int, Counter, Counter]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not LOGO_PATH.exists():
        print(f"ADVERTENCIA: Logo no encontrado en {LOGO_PATH}")
        logo_uri = ""
    else:
        logo_uri = svg_a_data_uri(LOGO_PATH)

    generados = 0
    cat_counter: Counter = Counter()
    fotos_counter: Counter = Counter()

    print(f"\nRenderizando posts en {OUTPUT_DIR} ...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1080})

        for post in posts:
            filename = post["filename"]
            try:
                foto_path: Path = post["foto"]
                foto_uri = a_data_uri(foto_path)
                layout_fn = LAYOUTS[post["layout_idx"]]

                html_content = layout_fn(
                    foto=foto_uri,
                    logo=logo_uri,
                    principal=post.get("principal", "Float Chile"),
                    secundaria=post.get("secundaria", ""),
                    color=post["color"],
                )

                page.set_content(html_content, wait_until="networkidle", timeout=15000)
                out_path = OUTPUT_DIR / filename
                page.screenshot(
                    path=str(out_path),
                    clip={"x": 0, "y": 0, "width": 1080, "height": 1080},
                )

                generados += 1
                cat_counter[post["category"]] += 1
                fotos_counter[foto_path.name] += 1
                print(f"  ✓ {filename}")

            except Exception as e:
                print(f"  ✗ {filename}: {e}")

        browser.close()

    return generados, cat_counter, fotos_counter


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Validar assets
    fotos = listar_fotos()
    if not fotos:
        print(f"ERROR: No se encontraron fotos en {FOTOS_DIR}")
        sys.exit(1)
    print(f"Fotos disponibles: {len(fotos)}")
    for f in fotos:
        print(f"  • {f.name}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nERROR: Configura ANTHROPIC_API_KEY antes de ejecutar el script.")
        sys.exit(1)

    # 2. Construir plan de posts
    posts: list[dict] = []
    layout_idx = 0
    color_idx = 0

    for category, cfg in CATEGORIES.items():
        for i in range(cfg["count"]):
            posts.append(
                {
                    "category": category,
                    "label": cfg["label"],
                    "benefits": cfg["benefits"],
                    "filename": f"{category}_{i+1:02d}.png",
                    "layout_idx": layout_idx % 4,
                    "color": BRAND_COLORS[color_idx % len(BRAND_COLORS)],
                    "principal": "",
                    "secundaria": "",
                    "foto": None,
                }
            )
            layout_idx += 1
            color_idx += 1

    print(f"\nPlan: {len(posts)} posts")
    for cat, cfg in CATEGORIES.items():
        print(f"  {cat}: {cfg['count']} posts")

    # 3. Asignar fotos
    asignar_fotos(fotos, posts)

    # 4. Generar copies
    client = anthropic.Anthropic(api_key=api_key)
    generar_copies(client, posts)

    # 5. Renderizar
    generados, cat_counter, fotos_counter = renderizar_posts(posts)

    # 6. Resumen
    print("\n" + "=" * 52)
    print("  RESUMEN")
    print("=" * 52)
    print(f"  Posts generados: {generados} / {len(posts)}")
    print("\n  Por categoría:")
    for cat, count in cat_counter.items():
        print(f"    {cat}: {count}")
    print("\n  Fotos más usadas:")
    for nombre, veces in fotos_counter.most_common():
        print(f"    {nombre}: {veces}x")
    print(f"\n  Output: {OUTPUT_DIR}")
    print("=" * 52)


if __name__ == "__main__":
    main()
