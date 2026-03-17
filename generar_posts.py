#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Float Chile — Generador de 50 posts para Instagram
Usa Claude API para copies y Playwright para renderizar HTML como PNG 1080×1080.

Uso:
    export ANTHROPIC_API_KEY="tu_clave"
    pip install anthropic playwright && playwright install chromium
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
    os.system(f"{sys.executable} -m pip install anthropic -q")
    import anthropic

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    os.system(f"{sys.executable} -m pip install playwright -q")
    os.system("playwright install chromium")
    from playwright.sync_api import sync_playwright

# ─── RUTAS ────────────────────────────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent
FOTOS_DIR = BASE_DIR / "Fotos Float"
OUTPUT_DIR = BASE_DIR / "output" / "float_posts"
LOGO_PATH  = FOTOS_DIR / "Logo.svg"

# ─── MARCA ────────────────────────────────────────────────────────────────────

BRAND_COLORS = ["#0db6c7", "#472172", "#19a1b3", "#0db6c7"]  # sin salmon para overlay

CATEGORIES = {
    "flotacion": {
        "count": 15,
        "label": "flotación en cápsula sensorial",
        "benefits": "desconexión total, silencio absoluto, ausencia de gravedad, reducción de cortisol, sueño profundo, reseteo mental",
    },
    "masajes": {
        "count": 15,
        "label": "masajes y recuperación corporal",
        "benefits": "relajación muscular profunda, presencia corporal, recuperación activa, cuidado consciente, alivio de tensión acumulada",
    },
    "mindfulness": {
        "count": 10,
        "label": "mindfulness y atención plena",
        "benefits": "regulación emocional, atención plena, pausa activa, herramienta cotidiana no esotérica, claridad mental",
    },
    "fire_ice": {
        "count": 10,
        "label": "fire & ice — contraste térmico sauna y frío",
        "benefits": "activación del sistema nervioso, vitalidad, circulación, claridad mental, ritual de contraste calor-frío",
    },
}

# ─── COPIES ───────────────────────────────────────────────────────────────────

# Tres estilos que se alternan en los posts
ESTILOS = {
    "A": (
        "ESTILO A — PREGUNTA COMO HOOK:\n"
        "Una pregunta que hace que el lector se reconozca en ella.\n"
        "Debe incomodar levemente — tocar el nervio del estrés o la desconexión.\n"
        "Ejemplos del tono correcto:\n"
        "  '¿Cuándo fue la última vez que tu mente estuvo en silencio?'\n"
        "  '¿Y si tu cuerpo solo necesita que pares?'\n"
        "  '¿Qué pasa cuando eliminas todo el ruido?'\n"
        "La pregunta no vende el servicio — hace que el lector sienta la necesidad."
    ),
    "B": (
        "ESTILO B — AFIRMACIÓN DE BENEFICIO ESPECÍFICO:\n"
        "Describe lo que siente el cliente DESPUÉS de la sesión, no el servicio en sí.\n"
        "Específico, no genérico. Que suene a algo que solo Float puede ofrecer.\n"
        "Ejemplos del tono correcto:\n"
        "  'Sales sabiendo exactamente qué necesitabas'\n"
        "  'Tu sistema nervioso lleva meses esperando esto'\n"
        "  'No es relajación. Es un reseteo completo'\n"
        "Evitar adjetivos vacíos como 'increíble', 'único', 'especial'."
    ),
    "C": (
        "ESTILO C — TENSIÓN O CONTRASTE:\n"
        "Jugar con la paradoja entre el mundo acelerado y lo que Float ofrece.\n"
        "Ejemplos del tono correcto:\n"
        "  'El mundo no va a parar. Tú sí puedes'\n"
        "  'Mientras todo apura, aquí el tiempo funciona distinto'\n"
        "  'No necesitas más fuerza de voluntad. Necesitas flotar'\n"
        "La tensión debe sentirse real, no forzada."
    ),
}

COPY_SYSTEM_PROMPT = (
    "Eres copywriter de Float Chile, centro de bienestar premium en Santiago.\n"
    "Escribes en español, tuteo, tono sereno y sofisticado.\n"
    "Sin clichés de wellness. Sin exclamaciones. Sin frases motivacionales vacías.\n"
    "Sin mencionar 'Float Chile' ni el nombre del servicio en la frase principal.\n"
    "El cliente ideal: profesional urbano 30-45 años, estresado, que busca "
    "desconexión real — no relajación superficial.\n\n"
    "FRASE PRINCIPAL: máximo 7 palabras. Sin punto final. Alta carga emocional.\n"
    "FRASE SECUNDARIA: máximo 15 palabras. Más descriptiva y específica. Puede ser null.\n\n"
    "REGLA CRÍTICA: Cada frase principal debe ser única. Nunca repetir una frase usada antes."
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
    """Asigna fotos temáticamente y rota para evitar repeticiones seguidas."""
    flotacion_kw = {"camara", "cámara", "pod", "float15", "float16", "float20", "float21"}
    fire_kw      = {"sauna", "fuego", "fire", "ice", "hielo", "agua"}

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
        cat  = post["category"]
        pool = pools.get(cat) or pools["general"] or fotos
        if not pool:
            pool = fotos
        idx = counters.get(cat, 0) % len(pool)
        counters[cat] = idx + 1
        post["foto"] = pool[idx]


# ─── GENERACIÓN DE COPIES ─────────────────────────────────────────────────────

def generar_copies(client: anthropic.Anthropic, posts: list[dict]) -> None:
    """Genera copies con 3 estilos alternados, en lotes de 25."""
    print(f"\nGenerando copies para {len(posts)} posts...")

    estilos_lista = list(ESTILOS.keys())

    def procesar_lote(lote: list[dict]) -> list[dict]:
        items = []
        for i, p in enumerate(lote):
            estilo_key = estilos_lista[p["estilo_idx"] % 3]
            estilo_desc = ESTILOS[estilo_key]
            items.append(
                f"{i+1}. [{estilo_key}] Tema: {p['label']} | Beneficios: {p['benefits']}\n"
                f"   {estilo_desc}\n"
            )

        mensaje = (
            f"Genera copies para {len(lote)} posts de Instagram de Float Chile.\n\n"
            f"Cada post tiene un ESTILO asignado (A, B o C). Respeta el estilo indicado.\n\n"
            + "\n".join(items)
            + f"\nResponde ÚNICAMENTE con un JSON array de {len(lote)} objetos:\n"
            f'[{{"principal": "...", "secundaria": "..."}}, ...]\n'
            f"Las frases principales deben ser todas distintas entre sí."
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=COPY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mensaje}],
        )
        texto = resp.content[0].text.strip()
        if "```" in texto:
            for parte in texto.split("```"):
                parte = parte.lstrip("json").strip()
                if parte.startswith("["):
                    texto = parte
                    break
        inicio = texto.find("[")
        fin    = texto.rfind("]") + 1
        if inicio >= 0 and fin > inicio:
            texto = texto[inicio:fin]
        return json.loads(texto)

    lote_size = 25
    for i in range(0, len(posts), lote_size):
        lote  = posts[i : i + lote_size]
        tries = 0
        while tries < 3:
            try:
                copies = procesar_lote(lote)
                for post, copy in zip(lote, copies):
                    post["principal"]  = copy.get("principal", "El silencio también descansa")
                    post["secundaria"] = copy.get("secundaria") or ""
                print(f"  ✓ Lote {i // lote_size + 1}: {len(copies)} copies")
                break
            except Exception as e:
                tries += 1
                print(f"  ✗ Error lote {i // lote_size + 1} (intento {tries}): {e}")
                if tries == 3:
                    fallbacks_por_cat = {
                        "flotacion": {
                            "A": "¿Cuándo fue la última vez que tu mente paró?",
                            "B": "Sales sin saber exactamente qué pasó",
                            "C": "El mundo no para. Aquí, tú sí",
                        },
                        "masajes": {
                            "A": "¿Y si tu cuerpo solo necesita que pares?",
                            "B": "La tensión acumulada tiene solución específica",
                            "C": "Meses de estrés. Una hora para resetear",
                        },
                        "mindfulness": {
                            "A": "¿Qué pasa cuando eliminas todo el ruido?",
                            "B": "Presencia plena no es meditación. Es práctica",
                            "C": "Mientras todo apura, aquí el tiempo funciona distinto",
                        },
                        "fire_ice": {
                            "A": "¿Cuánto tiempo llevas sin sentir tu cuerpo?",
                            "B": "Tu sistema nervioso lleva meses esperando esto",
                            "C": "Calor. Frío. Claridad que no llega de otra forma",
                        },
                    }
                    for j, post in enumerate(lote):
                        ek  = estilos_lista[post["estilo_idx"] % 3]
                        cat = post["category"]
                        post["principal"]  = fallbacks_por_cat.get(cat, {}).get(ek, "El silencio también descansa")
                        post["secundaria"] = post["benefits"].split(",")[0].strip().capitalize()


def mostrar_ejemplos(posts: list[dict]) -> None:
    """Imprime 3 ejemplos de copies para validar el tono antes de renderizar."""
    print("\n" + "─" * 52)
    print("  EJEMPLOS DE COPIES GENERADOS (verificar tono)")
    print("─" * 52)
    indices = [0, len(posts) // 3, (len(posts) * 2) // 3]
    for idx in indices:
        p = posts[idx]
        estilo = list(ESTILOS.keys())[p["estilo_idx"] % 3]
        print(f"\n  [{p['category'].upper()} — Estilo {estilo}]")
        print(f"  Principal : {p.get('principal', '—')}")
        if p.get("secundaria"):
            print(f"  Secundaria: {p['secundaria']}")
    print("\n" + "─" * 52)
    try:
        input("  Presiona ENTER para renderizar todos los posts... ")
    except EOFError:
        print("  (continuando automáticamente...)")


# ─── LAYOUTS HTML ─────────────────────────────────────────────────────────────

FONT = '@import url("https://fonts.googleapis.com/css2?family=Josefin+Sans:wght@300;400;700&display=swap");'


def _h(text: str) -> str:
    return html_module.escape(str(text))


def _sec_css() -> str:
    """CSS compartido para la frase secundaria: mayúsculas espaciadas."""
    return (
        ".sec{font-size:14px;font-weight:300;line-height:1.8;"
        "letter-spacing:3px;text-transform:uppercase;"
        "text-shadow:2px 2px 8px rgba(0,0,0,.8)}"
    )


def layout_1(foto: str, logo: str, principal: str, secundaria: str,
             color: str, variante: int) -> str:
    """
    Foto full + overlay oscuro + texto centrado.
    variante 0: sin línea decorativa
    variante 1: línea fina sobre el texto principal
    variante 2: línea fina bajo el texto principal
    """
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""

    linea_arriba = f'<div class="linea"></div>' if variante == 1 else ""
    linea_abajo  = f'<div class="linea"></div>' if variante == 2 else ""

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.ov{{position:absolute;inset:0;background:rgba(0,0,0,.52)}}
.ct{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
     justify-content:center;padding:100px;text-align:center;color:#fff}}
.pr{{font-size:52px;font-weight:700;line-height:1.2;margin-bottom:22px;
     text-shadow:2px 2px 10px rgba(0,0,0,.85)}}
.linea{{width:60px;height:2px;background:{color};margin:0 auto 22px;flex-shrink:0}}
{_sec_css()}
.logo{{position:absolute;bottom:44px;right:48px;width:110px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="bg"></div><div class="ov"></div>
<div class="ct">
  {linea_arriba}
  <p class="pr">{_h(principal)}</p>
  {linea_abajo}
  {sec}
</div>
<img class="logo" src="{logo}" alt="Float Chile">
</body></html>"""


def layout_2(foto: str, logo: str, principal: str, secundaria: str,
             color: str, variante: int) -> str:
    """
    Foto full + gradiente desde color de marca.
    variante 0: gradiente lateral (izquierda → derecha)
    variante 1: gradiente desde abajo hacia arriba
    """
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    c80 = color + "cc"
    c50 = color + "80"

    if variante == 0:
        gradiente = f"linear-gradient(to right,{c80} 0%,{c50} 45%,transparent 72%)"
        ct_css = ("position:absolute;inset:0;display:flex;flex-direction:column;"
                  "align-items:flex-start;justify-content:center;"
                  "padding:80px;color:#fff;max-width:580px")
        logo_pos = "position:absolute;bottom:44px;left:48px;width:100px;filter:brightness(0) invert(1)"
    else:
        gradiente = f"linear-gradient(to top,{c80} 0%,{c50} 45%,transparent 72%)"
        ct_css = ("position:absolute;inset:0;display:flex;flex-direction:column;"
                  "align-items:flex-start;justify-content:flex-end;"
                  "padding:80px;color:#fff;max-width:640px")
        logo_pos = "position:absolute;top:44px;left:48px;width:100px;filter:brightness(0) invert(1)"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.gr{{position:absolute;inset:0;background:{gradiente}}}
.ct{{{ct_css}}}
.pr{{font-size:48px;font-weight:700;line-height:1.2;margin-bottom:20px;
     text-shadow:2px 2px 10px rgba(0,0,0,.8)}}
{_sec_css()}
.logo{{{logo_pos}}}
</style></head><body>
<div class="bg"></div><div class="gr"></div>
<div class="ct"><p class="pr">{_h(principal)}</p>{sec}</div>
<img class="logo" src="{logo}" alt="Float Chile">
</body></html>"""


def layout_4(foto: str, logo: str, principal: str, secundaria: str,
             color: str, variante: int) -> str:
    """
    Foto full + caja semitransparente centrada.
    variante 0: bordes rectos, borde del color asignado
    variante 1: border-radius 12px, borde siempre #0db6c7
    """
    sec = f'<p class="sec">{_h(secundaria)}</p>' if secundaria else ""
    if variante == 0:
        caja_css = (f"border:1.5px solid {color};border-radius:0")
    else:
        caja_css = "border:1.5px solid #0db6c7;border-radius:12px"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{FONT}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:1080px;height:1080px;overflow:hidden;font-family:'Josefin Sans',sans-serif;position:relative}}
.bg{{position:absolute;inset:0;background:url('{foto}') center/cover no-repeat}}
.caja{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
       width:780px;background:rgba(0,0,0,.70);{caja_css};
       padding:72px 64px;text-align:center;color:#fff}}
.pr{{font-size:46px;font-weight:700;line-height:1.2;margin-bottom:22px;
     text-shadow:2px 2px 10px rgba(0,0,0,.85)}}
{_sec_css()}
.logo{{display:block;margin:32px auto 0;width:95px;filter:brightness(0) invert(1)}}
</style></head><body>
<div class="bg"></div>
<div class="caja">
  <p class="pr">{_h(principal)}</p>
  {sec}
  <img class="logo" src="{logo}" alt="Float Chile">
</div>
</body></html>"""


# Mapa de renderizado: layout_id → función
LAYOUT_FNS = {1: layout_1, 2: layout_2, 4: layout_4}

# Secuencia de layouts sin el 3, 50 posts distribuidos entre 1, 2, 4
LAYOUT_CYCLE = [1, 2, 4]  # ~17, 17, 16


# ─── RENDERIZADO ──────────────────────────────────────────────────────────────

def renderizar_posts(posts: list[dict]) -> tuple[int, Counter, Counter]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logo_uri = svg_a_data_uri(LOGO_PATH) if LOGO_PATH.exists() else ""
    generados = 0
    cat_counter:   Counter = Counter()
    fotos_counter: Counter = Counter()

    print(f"\nRenderizando {len(posts)} posts...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page(viewport={"width": 1080, "height": 1080})

        for post in posts:
            filename = post["filename"]
            try:
                foto_uri  = a_data_uri(post["foto"])
                layout_id = post["layout_id"]
                variante  = post["variante"]
                fn        = LAYOUT_FNS[layout_id]

                html_str = fn(
                    foto      = foto_uri,
                    logo      = logo_uri,
                    principal = post.get("principal", "Float Chile"),
                    secundaria= post.get("secundaria", ""),
                    color     = post["color"],
                    variante  = variante,
                )

                page.set_content(html_str, wait_until="networkidle", timeout=15000)
                out_path = OUTPUT_DIR / filename
                page.screenshot(
                    path=str(out_path),
                    clip={"x": 0, "y": 0, "width": 1080, "height": 1080},
                )

                generados += 1
                cat_counter[post["category"]]     += 1
                fotos_counter[post["foto"].name]  += 1
                print(f"  ✓ {filename}  [L{layout_id}·v{variante}]")

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
    # Layouts: ciclo [1, 2, 4] — sin layout 3
    # Variantes por layout:
    #   L1 → 0 (sin línea) / 1 (línea arriba) / 2 (línea abajo)
    #   L2 → 0 (gradiente lateral) / 1 (gradiente abajo)
    #   L4 → 0 (bordes rectos) / 1 (bordes redondeados cyan)
    # Estilos de copy: A / B / C alternando

    posts: list[dict] = []
    global_idx = 0

    for category, cfg in CATEGORIES.items():
        for i in range(cfg["count"]):
            layout_id  = LAYOUT_CYCLE[global_idx % 3]
            variante   = global_idx % (3 if layout_id == 1 else 2)
            estilo_idx = global_idx % 3
            color      = BRAND_COLORS[global_idx % len(BRAND_COLORS)]

            posts.append({
                "category":   category,
                "label":      cfg["label"],
                "benefits":   cfg["benefits"],
                "filename":   f"{category}_{i+1:02d}.png",
                "layout_id":  layout_id,
                "variante":   variante,
                "estilo_idx": estilo_idx,
                "color":      color,
                "principal":  "",
                "secundaria": "",
                "foto":       None,
            })
            global_idx += 1

    print(f"\nPlan: {len(posts)} posts")
    layout_dist: Counter = Counter(p["layout_id"] for p in posts)
    for lid, cnt in sorted(layout_dist.items()):
        print(f"  Layout {lid}: {cnt} posts")

    # 3. Asignar fotos
    asignar_fotos(fotos, posts)

    # 4. Generar copies con Claude
    client = anthropic.Anthropic(api_key=api_key)
    generar_copies(client, posts)

    # 5. Mostrar 3 ejemplos y pedir confirmación
    mostrar_ejemplos(posts)

    # 6. Renderizar
    generados, cat_counter, fotos_counter = renderizar_posts(posts)

    # 7. Resumen final
    print("\n" + "=" * 52)
    print("  RESUMEN FINAL")
    print("=" * 52)
    print(f"  Posts generados: {generados} / {len(posts)}")
    print("\n  Por categoría:")
    for cat, count in cat_counter.items():
        print(f"    {cat}: {count}")
    print("\n  Por layout:")
    for lid in [1, 2, 4]:
        cnt = sum(1 for p in posts if p["layout_id"] == lid)
        print(f"    Layout {lid}: {cnt}")
    print("\n  Fotos más usadas:")
    for nombre, veces in fotos_counter.most_common():
        print(f"    {nombre}: {veces}x")
    print(f"\n  Output: {OUTPUT_DIR}")
    print("=" * 52)


if __name__ == "__main__":
    main()
