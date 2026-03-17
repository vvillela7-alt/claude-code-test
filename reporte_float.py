#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Float Chile — Meta Ads Performance Report 2025
================================================
Genera: reporte_float_2025.html  (dashboard interactivo)
        reporte_float_2025.csv   (datos crudos)
        Resumen ejecutivo en consola

Uso:
    export META_TOKEN="tu_access_token_aqui"
    python3 reporte_float.py
"""

import os, sys, json, csv, math, textwrap
from datetime import datetime, date, timedelta
from collections import defaultdict

# ─── Validar token antes de todo ──────────────────────────────────────────
ACCESS_TOKEN = os.environ.get("META_TOKEN", "").strip()
if not ACCESS_TOKEN:
    print("═" * 60)
    print("  ERROR: Variable de entorno META_TOKEN no encontrada.")
    print("  Ejecuta primero:")
    print("    export META_TOKEN='tu_access_token'")
    print("═" * 60)
    sys.exit(1)

AD_ACCOUNT_ID = "act_833148738871119"
DATE_START    = "2025-01-01"
DATE_END      = "2025-12-31"

# ─── Instalar dependencias si faltan ──────────────────────────────────────
def ensure_deps():
    try:
        import facebook_business  # noqa
    except ImportError:
        print("📦 Instalando facebook-business...")
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "facebook-business", "-q"]
        )

ensure_deps()

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.exceptions import FacebookRequestError

# ─── Configuración de eventos estacionales ────────────────────────────────
# Formato: (nombre, fecha_inicio, fecha_fin)  # rangos de hasta 1 día = punto
SEASONAL_EVENTS = [
    ("Vacaciones Verano",       "2025-01-01", "2025-02-28"),
    ("Año Nuevo",               "2025-01-01", "2025-01-01"),
    ("San Valentín",            "2025-02-14", "2025-02-14"),
    ("Día de la Mujer",         "2025-03-08", "2025-03-08"),
    ("Inicio Clases Univ.",     "2025-03-10", "2025-03-14"),
    ("Día Mundial Salud",       "2025-04-07", "2025-04-07"),
    ("Semana Santa",            "2025-04-13", "2025-04-20"),
    ("Día del Trabajador",      "2025-05-01", "2025-05-01"),
    ("Día de la Madre",         "2025-05-11", "2025-05-11"),
    ("CyberDay Chile (May)",    "2025-05-26", "2025-05-28"),
    ("Día del Padre",           "2025-06-23", "2025-06-23"),
    ("Vacaciones Invierno",     "2025-07-14", "2025-07-27"),
    ("Fiestas Patrias",         "2025-09-17", "2025-09-19"),
    ("Día Salud Mental",        "2025-10-10", "2025-10-10"),
    ("CyberDay Chile (Oct)",    "2025-10-20", "2025-10-22"),
    ("Halloween",               "2025-10-31", "2025-10-31"),
    ("Fin Año Corporativo",     "2025-11-03", "2025-11-21"),
    ("Black Friday",            "2025-11-28", "2025-11-28"),
    ("Cyber Monday",            "2025-12-01", "2025-12-01"),
    ("Navidad",                 "2025-12-24", "2025-12-25"),
]

# Colores para los eventos en el gráfico (rotados)
EVENT_COLORS = [
    "#F59E0B", "#3B82F6", "#EC4899", "#10B981",
    "#8B5CF6", "#EF4444", "#06B6D4", "#84CC16",
    "#F97316", "#6366F1", "#14B8A6", "#F43F5E",
    "#A78BFA", "#FB923C", "#22D3EE", "#4ADE80",
    "#FACC15", "#F472B6", "#60A5FA", "#34D399",
]

# ─── Utilidades de formato ────────────────────────────────────────────────
def fmt_cl(n, dec=0):
    """Formato numérico chileno: punto miles, coma decimal. Ej: 1.234.567,89"""
    if n is None:
        return "N/A"
    try:
        n = float(n)
        if dec == 0:
            s = f"{n:,.0f}"
        else:
            s = f"{n:,.{dec}f}"
        # . → miles,  , → decimal  (intercambio via placeholder)
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "N/A"

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def safe_div(a, b, default=None):
    try:
        a, b = float(a), float(b)
        return a / b if b != 0 else default
    except (TypeError, ValueError):
        return default

def parse_actions(actions_list, action_type):
    """Extrae valor de una lista de acciones por tipo."""
    if not actions_list:
        return None
    for a in actions_list:
        if isinstance(a, dict) and a.get("action_type") == action_type:
            return safe_float(a.get("value", 0))
    return None

def extract_roas(row):
    """
    Intenta obtener ROAS desde purchase_roas.
    Si no existe, intenta calcularlo desde action_values / spend.
    Devuelve float o None.
    """
    # 1. Campo purchase_roas directo
    pr = row.get("purchase_roas")
    if pr:
        if isinstance(pr, list):
            for item in pr:
                if isinstance(item, dict) and "value" in item:
                    return safe_float(item["value"])
        elif isinstance(pr, (int, float, str)):
            return safe_float(pr)

    # 2. Calcular desde action_values (omni_purchase) / spend
    av = row.get("action_values")
    spend = safe_float(row.get("spend", 0))
    if av and spend > 0:
        purch_val = None
        for item in (av if isinstance(av, list) else []):
            if isinstance(item, dict) and item.get("action_type") in (
                "omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"
            ):
                purch_val = safe_float(item.get("value", 0))
                break
        if purch_val is not None:
            return safe_div(purch_val, spend)

    return None

def extract_conversions(row):
    """Devuelve número de conversiones (purchases o resultado principal)."""
    actions = row.get("actions")
    if not actions:
        return None
    # Intentar en orden de prioridad
    for atype in (
        "omni_purchase", "purchase",
        "offsite_conversion.fb_pixel_purchase",
        "lead", "complete_registration",
    ):
        val = parse_actions(actions, atype)
        if val is not None:
            return val
    return None

def extract_conv_value(row):
    """Devuelve valor total de conversiones."""
    av = row.get("action_values")
    if not av:
        return None
    for atype in (
        "omni_purchase", "purchase",
        "offsite_conversion.fb_pixel_purchase",
    ):
        val = parse_actions(av if isinstance(av, list) else [], atype)
        if val is not None:
            return val
    return None

def cost_per_result(row):
    """Costo por resultado: spend / conversiones."""
    spend = safe_float(row.get("spend", 0))
    convs = extract_conversions(row)
    if convs and convs > 0 and spend > 0:
        return spend / convs
    return None

def week_label(date_str):
    """Convierte '2025-03-17' en 'S11 Mar' (semana ISO + mes)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"S{d.isocalendar()[1]:02d} {d.strftime('%b')}"
    except Exception:
        return date_str[:7]

def month_label(date_str):
    """Convierte '2025-03-01' en 'Mar 25'."""
    MESES = {
        "Jan": "Ene", "Feb": "Feb", "Mar": "Mar", "Apr": "Abr",
        "May": "May", "Jun": "Jun", "Jul": "Jul", "Aug": "Ago",
        "Sep": "Sep", "Oct": "Oct", "Nov": "Nov", "Dec": "Dic",
    }
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        eng = d.strftime("%b")
        return MESES.get(eng, eng) + " " + d.strftime("%y")
    except Exception:
        return date_str[:7]

# ─── Inicializar API ──────────────────────────────────────────────────────
def init_api():
    FacebookAdsApi.init(access_token=ACCESS_TOKEN)
    print("✓ Conectado a Meta Marketing API")

# ─── Campos a solicitar ───────────────────────────────────────────────────
INSIGHT_FIELDS = [
    "campaign_name", "campaign_id",
    "adset_name", "adset_id",
    "impressions", "reach", "clicks",
    "ctr", "cpm", "cpc",
    "spend", "frequency",
    "actions", "action_values",
    "cost_per_action_type",
    "purchase_roas",
    "date_start", "date_stop",
]

# ─── Obtener insights de la API ───────────────────────────────────────────
def fetch_insights(time_increment, level="adset"):
    """
    time_increment: 'monthly' | 'weekly'
    level: 'adset' | 'campaign'
    """
    account = AdAccount(AD_ACCOUNT_ID)
    params = {
        "time_range": {"since": DATE_START, "until": DATE_END},
        "time_increment": time_increment,
        "level": level,
        "fields": INSIGHT_FIELDS,
        "filtering": [],
        "limit": 500,
    }

    label = f"{level}/{time_increment}"
    print(f"  → Solicitando datos {label}...", end=" ", flush=True)

    rows = []
    try:
        cursor = account.get_insights(fields=INSIGHT_FIELDS, params=params)
        for row in cursor:
            rows.append(dict(row))
        print(f"{len(rows)} registros")
    except FacebookRequestError as e:
        msg = str(e)
        if "Token" in msg or "token" in msg or "190" in msg:
            print(f"\n✗ Token expirado o inválido: {msg[:120]}")
        else:
            print(f"\n⚠ Error API ({label}): {msg[:120]}")
    except Exception as e:
        print(f"\n⚠ Error inesperado ({label}): {str(e)[:120]}")

    return rows

# ─── Procesar fila cruda de la API ────────────────────────────────────────
def process_row(r):
    spend     = safe_float(r.get("spend", 0))
    impr      = safe_float(r.get("impressions", 0))
    clicks    = safe_float(r.get("clicks", 0))
    reach     = safe_float(r.get("reach", 0))
    freq      = safe_float(r.get("frequency", 0))
    ctr       = safe_float(r.get("ctr", 0))
    cpm       = safe_float(r.get("cpm", 0))
    cpc_raw   = safe_float(r.get("cpc", 0))
    roas      = extract_roas(r)
    convs     = extract_conversions(r)
    conv_val  = extract_conv_value(r)
    cpr       = cost_per_result(r)

    return {
        "campaign_name": r.get("campaign_name", "N/A"),
        "campaign_id":   r.get("campaign_id", ""),
        "adset_name":    r.get("adset_name", "N/A"),
        "adset_id":      r.get("adset_id", ""),
        "date_start":    r.get("date_start", ""),
        "date_stop":     r.get("date_stop", ""),
        "spend":         spend,
        "impressions":   impr,
        "reach":         reach,
        "clicks":        clicks,
        "ctr":           ctr,
        "cpm":           cpm,
        "cpc":           cpc_raw,
        "frequency":     freq,
        "roas":          roas,
        "conversions":   convs,
        "conv_value":    conv_val,
        "cpr":           cpr,
    }

def process_all(raw_rows):
    return [process_row(r) for r in raw_rows]

# ─── Agregar por ad set (suma / promedio ponderado) ───────────────────────
def aggregate_by_adset(rows):
    buckets = defaultdict(list)
    for r in rows:
        key = (r["campaign_name"], r["adset_name"])
        buckets[key].append(r)

    result = []
    for (camp, adset), rlist in buckets.items():
        total_spend  = sum(r["spend"] for r in rlist)
        total_impr   = sum(r["impressions"] for r in rlist)
        total_clicks = sum(r["clicks"] for r in rlist)
        total_reach  = sum(r["reach"] for r in rlist)
        total_convs_raw = [r["conversions"] for r in rlist if r["conversions"] is not None]
        total_cv_raw    = [r["conv_value"]   for r in rlist if r["conv_value"]   is not None]

        total_convs = sum(total_convs_raw) if total_convs_raw else None
        total_cv    = sum(total_cv_raw)    if total_cv_raw    else None

        ctr_w  = safe_div(total_clicks, total_impr, 0) * 100
        cpm_w  = safe_div(total_spend, total_impr, 0) * 1000
        cpc_w  = safe_div(total_spend, total_clicks)
        freq_w = safe_div(total_impr, total_reach)
        roas_w = safe_div(total_cv, total_spend) if total_cv is not None else None
        cpr_w  = safe_div(total_spend, total_convs) if total_convs and total_convs > 0 else None

        result.append({
            "campaign_name": camp,
            "adset_name":    adset,
            "spend":         total_spend,
            "impressions":   total_impr,
            "reach":         total_reach,
            "clicks":        total_clicks,
            "ctr":           ctr_w,
            "cpm":           cpm_w,
            "cpc":           cpc_w,
            "frequency":     freq_w,
            "roas":          roas_w,
            "conversions":   total_convs,
            "conv_value":    total_cv,
            "cpr":           cpr_w,
        })
    return result

# ─── Agregar por semana para serie temporal ────────────────────────────────
def aggregate_by_week(rows):
    buckets = defaultdict(lambda: defaultdict(float))
    counts  = defaultdict(int)
    has_conv = defaultdict(bool)

    for r in rows:
        wk = r["date_start"][:10]
        buckets[wk]["spend"]       += r["spend"]
        buckets[wk]["impressions"] += r["impressions"]
        buckets[wk]["clicks"]      += r["clicks"]
        if r["conv_value"] is not None:
            buckets[wk]["conv_value"] += r["conv_value"]
            has_conv[wk] = True
        counts[wk] += 1

    series = []
    for wk in sorted(buckets.keys()):
        b = buckets[wk]
        spend = b["spend"]
        impr  = b["impressions"]
        clicks= b["clicks"]
        ctr   = safe_div(clicks, impr, 0) * 100
        cpm   = safe_div(spend, impr, 0) * 1000
        cv    = b.get("conv_value", 0) if has_conv[wk] else None
        roas  = safe_div(cv, spend) if cv is not None and spend > 0 else None

        series.append({
            "week":     wk,
            "label":    week_label(wk),
            "spend":    spend,
            "impressions": impr,
            "clicks":   clicks,
            "ctr":      ctr,
            "cpm":      cpm,
            "roas":     roas,
        })
    return series

def aggregate_by_month(rows):
    buckets = defaultdict(lambda: defaultdict(float))
    has_conv = defaultdict(bool)

    for r in rows:
        mo = r["date_start"][:7]  # "2025-03"
        date_key = mo + "-01"
        buckets[date_key]["spend"]       += r["spend"]
        buckets[date_key]["impressions"] += r["impressions"]
        buckets[date_key]["clicks"]      += r["clicks"]
        if r["conv_value"] is not None:
            buckets[date_key]["conv_value"] += r["conv_value"]
            has_conv[date_key] = True

    series = []
    for dk in sorted(buckets.keys()):
        b = buckets[dk]
        spend = b["spend"]
        impr  = b["impressions"]
        clicks= b["clicks"]
        ctr   = safe_div(clicks, impr, 0) * 100
        cpm   = safe_div(spend, impr, 0) * 1000
        cpc   = safe_div(spend, clicks)
        cv    = b.get("conv_value", 0) if has_conv[dk] else None
        roas  = safe_div(cv, spend) if cv is not None and spend > 0 else None

        series.append({
            "month":   dk,
            "label":   month_label(dk),
            "spend":   spend,
            "impressions": impr,
            "clicks":  clicks,
            "ctr":     ctr,
            "cpm":     cpm,
            "cpc":     cpc,
            "roas":    roas,
        })
    return series

# ─── Análisis de estacionalidad ───────────────────────────────────────────
def seasonality_analysis(weekly_series, adset_aggregated):
    """
    Para cada evento, compara métricas de ese período vs promedio anual.
    Clasifica como OPORTUNIDAD / RUIDO / SIN_DATOS.
    """
    # Promedios anuales
    total_spend   = sum(w["spend"] for w in weekly_series) or 1
    weeks_with_data = [w for w in weekly_series if w["spend"] > 0]
    n = len(weeks_with_data) or 1
    avg_spend  = total_spend / n
    avg_ctr    = sum(w["ctr"]  for w in weeks_with_data) / n
    avg_cpm    = sum(w["cpm"]  for w in weeks_with_data) / n
    roas_weeks = [w for w in weeks_with_data if w["roas"] is not None]
    avg_roas   = (sum(w["roas"] for w in roas_weeks) / len(roas_weeks)) if roas_weeks else None

    results = []
    for (name, start_s, end_s) in SEASONAL_EVENTS:
        start = datetime.strptime(start_s, "%Y-%m-%d").date()
        end   = datetime.strptime(end_s,   "%Y-%m-%d").date()

        # Semanas que se solapan con el evento
        ev_weeks = []
        for w in weekly_series:
            ws = datetime.strptime(w["week"], "%Y-%m-%d").date()
            we = ws + timedelta(days=6)
            if ws <= end and we >= start:  # solapamiento
                ev_weeks.append(w)

        if not ev_weeks or all(w["spend"] == 0 for w in ev_weeks):
            results.append({
                "name": name, "start": start_s, "end": end_s,
                "spend_sum": None, "ctr_avg": None, "cpm_avg": None,
                "roas_avg": None, "classification": "SIN_DATOS",
                "notes": "Sin datos publicitarios en este período",
            })
            continue

        ev_spend = sum(w["spend"] for w in ev_weeks)
        ev_n     = len([w for w in ev_weeks if w["spend"] > 0]) or 1
        ev_ctr   = sum(w["ctr"]  for w in ev_weeks if w["spend"] > 0) / ev_n
        ev_cpm   = sum(w["cpm"]  for w in ev_weeks if w["spend"] > 0) / ev_n
        ev_roas_raw = [w["roas"] for w in ev_weeks if w["roas"] is not None]
        ev_roas  = (sum(ev_roas_raw) / len(ev_roas_raw)) if ev_roas_raw else None

        # Clasificación
        spend_ratio = safe_div(ev_spend / ev_n, avg_spend, 1.0)
        ctr_ratio   = safe_div(ev_ctr, avg_ctr, 1.0) if avg_ctr > 0 else 1.0
        roas_ratio  = safe_div(ev_roas, avg_roas, 1.0) if (ev_roas and avg_roas) else None

        notes = []
        if spend_ratio > 1.15:
            notes.append(f"Gasto {(spend_ratio-1)*100:.0f}% sobre promedio")
        elif spend_ratio < 0.85:
            notes.append(f"Gasto {(1-spend_ratio)*100:.0f}% bajo promedio")

        if ctr_ratio > 1.1:
            notes.append(f"CTR {(ctr_ratio-1)*100:.0f}% sobre promedio")
        elif ctr_ratio < 0.9:
            notes.append(f"CTR {(1-ctr_ratio)*100:.0f}% bajo promedio")

        if roas_ratio is not None:
            if roas_ratio > 1.2:
                notes.append(f"ROAS {(roas_ratio-1)*100:.0f}% sobre promedio")
            elif roas_ratio < 0.8:
                notes.append(f"ROAS {(1-roas_ratio)*100:.0f}% bajo promedio")

        # Clasificar
        if roas_ratio is not None and roas_ratio >= 1.2:
            cls = "OPORTUNIDAD"
        elif roas_ratio is not None and roas_ratio <= 0.8:
            cls = "RUIDO"
        elif ctr_ratio >= 1.15 and spend_ratio >= 1.1:
            cls = "OPORTUNIDAD"
        elif abs(spend_ratio - 1) < 0.1 and abs(ctr_ratio - 1) < 0.1:
            cls = "RUIDO"
        else:
            cls = "POTENCIAL" if ctr_ratio >= 1.05 else "RUIDO"

        results.append({
            "name": name, "start": start_s, "end": end_s,
            "spend_sum": ev_spend, "spend_ratio": spend_ratio,
            "ctr_avg": ev_ctr, "ctr_ratio": ctr_ratio,
            "cpm_avg": ev_cpm,
            "roas_avg": ev_roas, "roas_ratio": roas_ratio,
            "classification": cls,
            "notes": " · ".join(notes) if notes else "Sin variación notable",
        })

    return results, {
        "avg_spend_weekly": avg_spend,
        "avg_ctr": avg_ctr,
        "avg_cpm": avg_cpm,
        "avg_roas": avg_roas,
    }

# ─── Análisis de KPIs globales ────────────────────────────────────────────
def global_kpis(adset_rows, monthly_series):
    total_spend  = sum(r["spend"] for r in adset_rows)
    total_impr   = sum(r["impressions"] for r in adset_rows)
    total_clicks = sum(r["clicks"] for r in adset_rows)
    total_convs_raw = [r["conversions"] for r in adset_rows if r["conversions"] is not None]
    total_cv_raw    = [r["conv_value"]   for r in adset_rows if r["conv_value"]   is not None]

    total_convs = sum(total_convs_raw) if total_convs_raw else None
    total_cv    = sum(total_cv_raw)    if total_cv_raw    else None

    avg_ctr = safe_div(total_clicks, total_impr, 0) * 100
    avg_cpm = safe_div(total_spend, total_impr, 0) * 1000
    avg_cpc = safe_div(total_spend, total_clicks)
    roas    = safe_div(total_cv, total_spend)
    cpr     = safe_div(total_spend, total_convs) if total_convs and total_convs > 0 else None

    # Mejor / peor mes por ROAS
    mo_roas = [(m["label"], m["roas"]) for m in monthly_series if m["roas"] is not None]
    best_mo  = max(mo_roas, key=lambda x: x[1], default=(None, None))
    worst_mo = min(mo_roas, key=lambda x: x[1], default=(None, None))

    pixel_ok = total_cv is not None

    return {
        "total_spend":    total_spend,
        "total_impr":     total_impr,
        "total_clicks":   total_clicks,
        "total_convs":    total_convs,
        "total_cv":       total_cv,
        "avg_ctr":        avg_ctr,
        "avg_cpm":        avg_cpm,
        "avg_cpc":        avg_cpc,
        "roas":           roas,
        "cpr":            cpr,
        "best_month":     best_mo,
        "worst_month":    worst_mo,
        "pixel_ok":       pixel_ok,
    }

# ─── Generar resumen ejecutivo ────────────────────────────────────────────
def executive_summary(kpis, adset_agg, seasonality, avgs):
    adsets_sorted = sorted(
        [a for a in adset_agg if a["cpr"] is not None],
        key=lambda x: x["cpr"]
    )
    top3    = adsets_sorted[:3]
    bottom3 = adsets_sorted[-3:] if len(adsets_sorted) >= 3 else []

    avg_ctr = avgs["avg_ctr"]
    low_ctr = [a for a in adset_agg if a["ctr"] < avg_ctr * 0.8 and a["spend"] > 0]
    burnout = [a for a in adset_agg if a["frequency"] and a["frequency"] > 3.5]

    spend_sorted  = sorted(adset_agg, key=lambda x: x["spend"], reverse=True)
    total_spend_s = sum(a["spend"] for a in adset_agg) or 1
    cum, pareto_sets = 0, []
    for a in spend_sorted:
        cum += a["spend"]
        pareto_sets.append(a["adset_name"])
        if cum / total_spend_s >= 0.80:
            break

    opps = [e for e in seasonality if e["classification"] == "OPORTUNIDAD"]

    lines = [
        "═" * 70,
        "  RESUMEN EJECUTIVO — FLOAT CHILE · META ADS 2025",
        "═" * 70,
        "",
        f"  INVERSIÓN TOTAL:      ${fmt_cl(kpis['total_spend'])} CLP",
        f"  ROAS GENERAL:         {fmt_cl(kpis['roas'], 2) if kpis['roas'] else 'N/A (sin datos píxel)'}",
        f"  CTR PROMEDIO:         {fmt_cl(kpis['avg_ctr'], 2)}%",
        f"  CPM PROMEDIO:         ${fmt_cl(kpis['avg_cpm'], 2)} CLP",
        f"  COSTO POR RESULTADO:  ${fmt_cl(kpis['cpr'], 0)} CLP" if kpis['cpr'] else "  COSTO POR RESULTADO:  N/A",
        "",
    ]

    if not kpis["pixel_ok"]:
        lines += [
            "  ⚠️  NOTA PÍXEL: No se encontraron eventos de conversión (purchase)",
            "      en la cuenta. ROAS y Costo por Resultado se muestran como N/A.",
            "      Verifica que el píxel esté configurado con eventos de compra.",
            "",
        ]

    if top3:
        lines += ["  ✅ MEJORES AD SETS (por costo por resultado):"]
        for a in top3:
            lines.append(f"     • {a['adset_name'][:45]} — CPR ${fmt_cl(a['cpr'], 0)}")
        lines.append("")

    if bottom3:
        lines += ["  ❌ PEORES AD SETS (mayor costo por resultado):"]
        for a in reversed(bottom3):
            lines.append(f"     • {a['adset_name'][:45]} — CPR ${fmt_cl(a['cpr'], 0)}")
        lines.append("")

    if low_ctr:
        lines += [f"  ⚠️  CTR BAJO EL PROMEDIO ({fmt_cl(avg_ctr, 2)}%):"]
        for a in low_ctr[:5]:
            lines.append(f"     • {a['adset_name'][:45]} — CTR {fmt_cl(a['ctr'], 2)}%")
        lines.append("")

    if burnout:
        lines += ["  🔥 AUDIENCIAS CON POSIBLE SATURACIÓN (Frecuencia > 3,5):"]
        for a in burnout:
            lines.append(f"     • {a['adset_name'][:45]} — Freq {fmt_cl(a['frequency'], 1)}")
        lines.append("")

    lines += [f"  💸 80% DEL GASTO SE CONCENTRA EN:"]
    for name in pareto_sets:
        lines.append(f"     • {name[:60]}")
    lines.append("")

    if opps:
        lines += ["  📅 OPORTUNIDADES ESTACIONALES IDENTIFICADAS:"]
        for e in opps:
            lines.append(f"     • {e['name']}: {e.get('notes', '')}")
        lines.append("")

    lines += [
        f"  📆 MEJOR MES:  {kpis['best_month'][0] if kpis['best_month'][0] else 'N/A'}" +
        (f" — ROAS {fmt_cl(kpis['best_month'][1], 2)}" if kpis['best_month'][1] else ""),
        f"  📆 PEOR MES:   {kpis['worst_month'][0] if kpis['worst_month'][0] else 'N/A'}" +
        (f" — ROAS {fmt_cl(kpis['worst_month'][1], 2)}" if kpis['worst_month'][1] else ""),
        "",
        "═" * 70,
    ]

    return "\n".join(lines)

# ─── Exportar CSV ─────────────────────────────────────────────────────────
def export_csv(adset_rows, filename="reporte_float_2025.csv"):
    if not adset_rows:
        print("  ⚠ Sin datos para exportar CSV")
        return
    fields = ["campaign_name", "adset_name", "spend", "impressions", "reach",
              "clicks", "ctr", "cpm", "cpc", "frequency",
              "roas", "conversions", "conv_value", "cpr"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in adset_rows:
            out = {}
            for k in fields:
                v = row.get(k)
                if isinstance(v, float):
                    out[k] = f"{v:.4f}".replace(".", ",")
                elif v is None:
                    out[k] = "N/A"
                else:
                    out[k] = str(v)
            writer.writerow(out)
    print(f"  ✓ CSV exportado → {filename}")

# ─── Generar HTML ─────────────────────────────────────────────────────────
def generate_html(kpis, adset_agg, monthly_series, weekly_series,
                  seasonality, avgs, filename="reporte_float_2025.html"):

    pixel_note = "" if kpis["pixel_ok"] else (
        "<div class='note-pixel'>⚠️ Nota: El píxel de Float no tiene eventos de compra "
        "registrados en el período analizado. ROAS y Costo por Resultado se muestran como N/A. "
        "Verifica la configuración del píxel en el Administrador de Eventos de Meta.</div>"
    )

    # ── Preparar datos para gráficos ─────────────────────────────────────
    mo_labels  = json.dumps([m["label"]  for m in monthly_series])
    mo_spend   = json.dumps([round(m["spend"], 2)  for m in monthly_series])
    mo_ctr     = json.dumps([round(m["ctr"], 3)    for m in monthly_series])
    mo_cpm     = json.dumps([round(m["cpm"], 2)    for m in monthly_series])
    mo_roas    = json.dumps([round(m["roas"], 3) if m["roas"] is not None else None for m in monthly_series])

    wk_labels  = json.dumps([w["label"]  for w in weekly_series])
    wk_spend   = json.dumps([round(w["spend"], 2)  for w in weekly_series])
    wk_ctr     = json.dumps([round(w["ctr"], 3)    for w in weekly_series])
    wk_roas    = json.dumps([round(w["roas"], 3) if w["roas"] is not None else None for w in weekly_series])

    avg_roas_val = json.dumps(round(avgs["avg_roas"], 3) if avgs["avg_roas"] else None)

    # Ad sets table
    adset_sorted_spend = sorted(adset_agg, key=lambda x: x["spend"], reverse=True)
    adset_sorted_cpr   = sorted(
        [a for a in adset_agg if a["cpr"] is not None],
        key=lambda x: x["cpr"]
    ) + [a for a in adset_agg if a["cpr"] is None]

    def cell(v, dec=2, prefix="", suffix="", red_low=None, green_high=None):
        if v is None:
            return '<td class="na">N/A</td>'
        txt = f"{prefix}{fmt_cl(v, dec)}{suffix}"
        cls = ""
        if red_low is not None and v < red_low:
            cls = ' class="bad"'
        elif green_high is not None and v > green_high:
            cls = ' class="good"'
        return f"<td{cls}>{txt}</td>"

    rows_html = ""
    for a in adset_sorted_spend:
        freq_cls = ' class="bad"' if (a["frequency"] and a["frequency"] > 3.5) else ""
        roas_cls = ""
        if a["roas"] is not None:
            roas_cls = ' class="good"' if a["roas"] >= 2.0 else (' class="bad"' if a["roas"] < 1.5 else "")
        rows_html += f"""<tr>
            <td class="tdcamp">{a['campaign_name']}</td>
            <td class="tdname">{a['adset_name']}</td>
            {cell(a['spend'],        0, '$', ' CLP')}
            {cell(a['impressions'],  0)}
            {cell(a['clicks'],       0)}
            {cell(a['ctr'],          2, '', '%', red_low=avgs['avg_ctr']*0.8)}
            {cell(a['cpm'],          2, '$')}
            {cell(a['cpc'],          2, '$')}
            <td{freq_cls}>{fmt_cl(a['frequency'], 1) if a['frequency'] else 'N/A'}</td>
            <td{roas_cls}>{fmt_cl(a['roas'], 2) if a['roas'] is not None else 'N/A'}</td>
            {cell(a['cpr'],          0, '$', ' CLP') if a['cpr'] is not None else '<td class="na">N/A</td>'}
        </tr>"""

    # Top ad sets ranking for chart (CPR)
    top_adsets = adset_sorted_cpr[:15]
    rank_labels = json.dumps([f"{a['campaign_name'][:20]}…/{a['adset_name'][:22]}" for a in top_adsets])
    rank_cpr    = json.dumps([round(a["cpr"], 2) for a in top_adsets])

    # Seasonality section
    cls_colors = {
        "OPORTUNIDAD": "#22c55e",
        "POTENCIAL":   "#F59E0B",
        "RUIDO":       "#64748b",
        "SIN_DATOS":   "#374151",
    }
    cls_icons = {
        "OPORTUNIDAD": "🟢",
        "POTENCIAL":   "🟡",
        "RUIDO":       "⚪",
        "SIN_DATOS":   "⚫",
    }

    seas_html = ""
    for ev in seasonality:
        c = cls_colors.get(ev["classification"], "#374151")
        icon = cls_icons.get(ev["classification"], "⚪")
        duration = ""
        if ev["start"] != ev["end"]:
            s = datetime.strptime(ev["start"], "%Y-%m-%d")
            e = datetime.strptime(ev["end"],   "%Y-%m-%d")
            duration = f" ({(e-s).days + 1} días)"
        roas_txt = fmt_cl(ev.get("roas_avg"), 2) if ev.get("roas_avg") is not None else "N/A"
        ctr_txt  = fmt_cl(ev.get("ctr_avg"),  2) if ev.get("ctr_avg")  is not None else "N/A"
        spend_txt= fmt_cl(ev.get("spend_sum"), 0) if ev.get("spend_sum") is not None else "N/A"
        seas_html += f"""
        <div class="seas-card" style="border-left:3px solid {c}">
          <div class="seas-header">
            <span class="seas-icon">{icon}</span>
            <span class="seas-name">{ev['name']}</span>
            <span class="seas-cls" style="color:{c}">{ev['classification']}</span>
          </div>
          <div class="seas-dates">{ev['start']} → {ev['end']}{duration}</div>
          <div class="seas-metrics">
            <span>💰 Gasto: ${spend_txt}</span>
            <span>📊 CTR: {ctr_txt}%</span>
            <span>🎯 ROAS: {roas_txt}</span>
          </div>
          <div class="seas-notes">{ev.get('notes','')}</div>
        </div>"""

    # Oportunidades 2026
    opps_2026 = [e for e in seasonality if e["classification"] in ("OPORTUNIDAD", "POTENCIAL")]
    opps_html = ""
    for ev in opps_2026:
        roas_txt = fmt_cl(ev.get("roas_avg"), 2) if ev.get("roas_avg") is not None else "N/A"
        opps_html += f"""<tr>
            <td>{ev['name']}</td>
            <td>{ev['start'][5:]} al {ev['end'][5:]}</td>
            <td class="good">{ev['classification']}</td>
            <td>ROAS: {roas_txt} · {ev.get('notes','')}</td>
        </tr>"""
    if not opps_html:
        opps_html = "<tr><td colspan='4' style='text-align:center;color:#64748b'>Sin suficientes datos para recomendaciones (verificar píxel)</td></tr>"

    # KPI cards data
    roas_color = "#ef4444" if (kpis["roas"] and kpis["roas"] < 1.5) else "#F59E0B"
    roas_alert = "⚠️ ROAS < 1.5" if (kpis["roas"] and kpis["roas"] < 1.5) else ""

    # Build annotation objects for Chart.js
    # Map weekly labels to indices for annotations
    wk_label_list = [w["label"] for w in weekly_series]
    mo_label_list = [m["label"] for m in monthly_series]

    def find_week_idx(date_str):
        """Find closest weekly label index for a given date string."""
        if not weekly_series:
            return -1
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        best_i, best_d = 0, 99999
        for i, w in enumerate(weekly_series):
            ws = datetime.strptime(w["week"], "%Y-%m-%d").date()
            diff = abs((target - ws).days)
            if diff < best_d:
                best_d, best_i = diff, i
        return best_i

    # Build annotations JSON for weekly spend chart
    ann_list = []
    for idx_e, (name, start_s, end_s) in enumerate(SEASONAL_EVENTS):
        color = EVENT_COLORS[idx_e % len(EVENT_COLORS)]
        si = find_week_idx(start_s)
        ei = find_week_idx(end_s)
        is_range = (start_s != end_s) and (abs(ei - si) >= 1)
        if is_range:
            ann_list.append(json.dumps({
                "type": "box",
                "xMin": si, "xMax": ei,
                "backgroundColor": color + "18",
                "borderColor": color + "55",
                "borderWidth": 1,
                "label": {"content": name, "display": True,
                          "color": color, "font": {"size": 9},
                          "position": "start", "rotation": 90}
            }))
        else:
            ann_list.append(json.dumps({
                "type": "line",
                "xMin": si, "xMax": si,
                "borderColor": color + "99",
                "borderWidth": 1.5,
                "borderDash": [4, 4],
                "label": {"content": name, "display": True,
                          "color": color, "font": {"size": 9},
                          "position": "start", "rotation": 90}
            }))

    annotations_js = "{" + ",".join(f"'ev{i}':{a}" for i, a in enumerate(ann_list)) + "}"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Float Chile — Meta Ads Report 2025</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0e18;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;font-size:14px}}
header{{text-align:center;padding:2.5rem 1rem 1.5rem;border-bottom:1px solid #1e2235}}
header h1{{font-size:1.9rem;font-weight:300;letter-spacing:6px;color:#F59E0B;text-transform:uppercase}}
header p{{color:#64748b;font-size:.78rem;letter-spacing:2px;margin-top:.4rem;text-transform:uppercase}}
.note-pixel{{background:#1e1a0e;border:1px solid #F59E0B55;border-radius:8px;padding:1rem 1.3rem;margin:1rem 1.5rem;color:#F59E0B;font-size:.82rem;line-height:1.6}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem;padding:1.5rem;max-width:1400px;margin:0 auto}}
.kpi{{background:#161722;border:1px solid #1e2235;border-radius:10px;padding:1.2rem 1rem;text-align:center}}
.kpi:hover{{border-color:#F59E0B44}}
.kpi-label{{font-size:.67rem;color:#64748b;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:.4rem}}
.kpi-value{{font-size:1.4rem;font-weight:600;color:#F59E0B}}
.kpi-sub{{font-size:.68rem;color:#475569;margin-top:.25rem}}
.kpi-alert{{font-size:.7rem;color:#ef4444;margin-top:.3rem;font-weight:600}}
.charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.2rem;padding:0 1.5rem 1.2rem;max-width:1400px;margin:0 auto}}
@media(max-width:900px){{.charts-grid{{grid-template-columns:1fr}}}}
.chart-card{{background:#161722;border:1px solid #1e2235;border-radius:10px;padding:1.2rem}}
.chart-card h2{{font-size:.72rem;color:#94a3b8;letter-spacing:2px;text-transform:uppercase;margin-bottom:1rem}}
.chart-full{{grid-column:1/-1}}
.section-title{{font-size:.72rem;color:#94a3b8;letter-spacing:2px;text-transform:uppercase;padding:1.5rem 1.5rem .8rem;max-width:1400px;margin:0 auto}}
/* TABLE */
.table-wrap{{overflow-x:auto;padding:0 1.5rem 1.5rem;max-width:1400px;margin:0 auto}}
.filter-bar{{display:flex;gap:.8rem;margin-bottom:.8rem;flex-wrap:wrap}}
.filter-bar input{{background:#161722;border:1px solid #2a2b3d;border-radius:6px;color:#e2e8f0;padding:.4rem .8rem;font-size:.8rem;width:280px}}
.filter-bar input:focus{{outline:none;border-color:#F59E0B}}
table{{width:100%;border-collapse:collapse;font-size:.77rem}}
th{{background:#0f1020;color:#94a3b8;padding:.6rem .8rem;text-align:left;position:sticky;top:0;cursor:pointer;white-space:nowrap;letter-spacing:.5px;border-bottom:1px solid #1e2235}}
th:hover{{color:#F59E0B}}
td{{padding:.55rem .8rem;border-bottom:1px solid #1e2235;white-space:nowrap}}
tr:hover td{{background:#1a1b2e}}
td.tdcamp{{color:#94a3b8;max-width:200px;overflow:hidden;text-overflow:ellipsis}}
td.tdname{{color:#e2e8f0;font-weight:500;max-width:220px;overflow:hidden;text-overflow:ellipsis}}
td.na{{color:#374151}}
td.bad{{color:#ef4444}}
td.good{{color:#22c55e}}
/* SEASONALITY */
.seas-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.8rem;padding:0 1.5rem 1.5rem;max-width:1400px;margin:0 auto}}
.seas-card{{background:#161722;border-radius:8px;padding:.9rem 1rem;transition:all .2s}}
.seas-header{{display:flex;align-items:center;gap:.5rem;margin-bottom:.3rem}}
.seas-icon{{font-size:1rem}}
.seas-name{{font-weight:600;font-size:.85rem;flex:1}}
.seas-cls{{font-size:.7rem;font-weight:700;letter-spacing:1px}}
.seas-dates{{font-size:.68rem;color:#64748b;margin-bottom:.4rem}}
.seas-metrics{{display:flex;gap:1rem;font-size:.72rem;color:#94a3b8;margin-bottom:.3rem;flex-wrap:wrap}}
.seas-notes{{font-size:.7rem;color:#64748b}}
/* 2026 TABLE */
.opps-wrap{{padding:0 1.5rem 3rem;max-width:1400px;margin:0 auto}}
.opps-wrap table th{{background:#0a1a0a}}
footer{{text-align:center;padding:2rem;color:#334155;font-size:.7rem;letter-spacing:1px}}
</style>
</head>
<body>
<header>
  <h1>Float Chile</h1>
  <p>Meta Ads · Dashboard de Rendimiento 2025 · {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
</header>

{pixel_note}

<!-- KPI CARDS -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-label">Gasto Total 2025</div>
    <div class="kpi-value">${fmt_cl(kpis['total_spend'], 0)}</div>
    <div class="kpi-sub">CLP</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">ROAS General</div>
    <div class="kpi-value" style="color:{roas_color}">{fmt_cl(kpis['roas'], 2) if kpis['roas'] else 'N/A'}</div>
    <div class="kpi-alert">{roas_alert}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">CTR Promedio</div>
    <div class="kpi-value">{fmt_cl(kpis['avg_ctr'], 2)}%</div>
    <div class="kpi-sub">Tasa de clics</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">CPM Promedio</div>
    <div class="kpi-value">${fmt_cl(kpis['avg_cpm'], 2)}</div>
    <div class="kpi-sub">CLP por 1.000 impresiones</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Costo por Resultado</div>
    <div class="kpi-value">{('$' + fmt_cl(kpis['cpr'], 0)) if kpis['cpr'] else 'N/A'}</div>
    <div class="kpi-sub">CLP por conversión</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Mejor Mes · ROAS</div>
    <div class="kpi-value" style="color:#22c55e">{kpis['best_month'][0] if kpis['best_month'][0] else 'N/A'}</div>
    <div class="kpi-sub">{('ROAS ' + fmt_cl(kpis['best_month'][1], 2)) if kpis['best_month'][1] else ''}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Peor Mes · ROAS</div>
    <div class="kpi-value" style="color:#ef4444">{kpis['worst_month'][0] if kpis['worst_month'][0] else 'N/A'}</div>
    <div class="kpi-sub">{('ROAS ' + fmt_cl(kpis['worst_month'][1], 2)) if kpis['worst_month'][1] else ''}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Impresiones Totales</div>
    <div class="kpi-value">{fmt_cl(kpis['total_impr'], 0)}</div>
    <div class="kpi-sub">Alcance acumulado</div>
  </div>
</div>

<!-- CHART 1: Gasto semanal + eventos -->
<div style="max-width:1400px;margin:0 auto;padding:0 1.5rem 1.2rem">
  <div class="chart-card">
    <h2>Gasto Semanal con Eventos Estacionales</h2>
    <canvas id="weeklySpend" height="110"></canvas>
  </div>
</div>

<!-- CHART 2+3: CTR/CPM mensual + ROAS mensual -->
<div class="charts-grid">
  <div class="chart-card">
    <h2>CTR y CPM Mensual</h2>
    <canvas id="ctrCpm" height="220"></canvas>
  </div>
  <div class="chart-card">
    <h2>Evolución ROAS Mensual · Umbral 1,5</h2>
    <canvas id="roasEvol" height="220"></canvas>
  </div>
</div>

<!-- CHART 4: Ranking ad sets por CPR -->
<div style="max-width:1400px;margin:0 auto;padding:0 1.5rem 1.2rem">
  <div class="chart-card">
    <h2>Ranking de Ad Sets por Costo por Resultado (mejor → peor)</h2>
    <canvas id="rankingCpr" height="80"></canvas>
  </div>
</div>

<!-- TABLA AD SETS -->
<div class="section-title">Tabla Completa de Ad Sets</div>
<div class="table-wrap">
  <div class="filter-bar">
    <input type="text" id="tableSearch" placeholder="🔍 Buscar campaña o ad set..." oninput="filterTable()">
  </div>
  <table id="adsetTable">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Campaña ↕</th>
        <th onclick="sortTable(1)">Ad Set ↕</th>
        <th onclick="sortTable(2)">Gasto ↕</th>
        <th onclick="sortTable(3)">Impresiones ↕</th>
        <th onclick="sortTable(4)">Clics ↕</th>
        <th onclick="sortTable(5)">CTR ↕</th>
        <th onclick="sortTable(6)">CPM ↕</th>
        <th onclick="sortTable(7)">CPC ↕</th>
        <th onclick="sortTable(8)">Frecuencia ↕</th>
        <th onclick="sortTable(9)">ROAS ↕</th>
        <th onclick="sortTable(10)">Costo/Resultado ↕</th>
      </tr>
    </thead>
    <tbody id="adsetBody">
      {rows_html}
    </tbody>
  </table>
</div>

<!-- ESTACIONALIDAD -->
<div class="section-title">Análisis de Estacionalidad</div>
<div class="seas-grid">
  {seas_html}
</div>

<!-- RECOMENDACIONES 2026 -->
<div class="section-title">Calendario de Oportunidades Recomendadas 2026</div>
<div class="opps-wrap">
  <table>
    <thead>
      <tr><th>Evento</th><th>Fecha 2026 (ref.)</th><th>Clasificación</th><th>Justificación</th></tr>
    </thead>
    <tbody>{opps_html}</tbody>
  </table>
</div>

<footer>Float Chile · Meta Ads Performance Report 2025 · Generado con datos de Meta Marketing API · Encoding UTF-8</footer>

<script>
Chart.defaults.color = '#64748b';
Chart.defaults.font.family = 'Segoe UI, system-ui, sans-serif';
Chart.defaults.font.size = 11;
const grid = {{color:'#1e2235',lineWidth:1}};

// ── 1. Gasto semanal + eventos ─────────────────────────────────────────
new Chart(document.getElementById('weeklySpend'), {{
  type: 'line',
  data: {{
    labels: {wk_labels},
    datasets: [{{
      label: 'Gasto semanal (CLP)',
      data: {wk_spend},
      borderColor: '#F59E0B',
      backgroundColor: '#F59E0B22',
      fill: true,
      tension: 0.35,
      pointRadius: 2,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{display: false}},
      annotation: {{annotations: {annotations_js}}},
      tooltip: {{callbacks: {{label: c => ' $' + Number(c.raw).toLocaleString('es-CL')}}}}
    }},
    scales: {{
      x: {{grid, ticks: {{maxRotation: 45, font: {{size: 9}}}}}},
      y: {{grid, ticks: {{callback: v => '$' + (v/1000).toFixed(0) + 'k'}},
           title: {{display: true, text: 'CLP'}}}}
    }}
  }}
}});

// ── 2. CTR y CPM mensual ─────────────────────────────────────────────
new Chart(document.getElementById('ctrCpm'), {{
  type: 'line',
  data: {{
    labels: {mo_labels},
    datasets: [
      {{label:'CTR (%)', data:{mo_ctr}, borderColor:'#3B82F6', yAxisID:'y',
        tension:.35, pointRadius:3, fill:false}},
      {{label:'CPM (CLP)', data:{mo_cpm}, borderColor:'#EC4899', yAxisID:'y2',
        tension:.35, pointRadius:3, fill:false, borderDash:[5,3]}}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{legend: {{position:'top', labels: {{color:'#94a3b8', boxWidth:12}}}}}},
    scales: {{
      x: {{grid}},
      y:  {{grid, position:'left',  title:{{display:true,text:'CTR %'}}}},
      y2: {{grid: {{display:false}}, position:'right', title:{{display:true,text:'CPM CLP'}}}}
    }}
  }}
}});

// ── 3. ROAS mensual + umbral ───────────────────────────────────────────
const avgRoas = {avg_roas_val};
const roasData = {mo_roas};
new Chart(document.getElementById('roasEvol'), {{
  type: 'line',
  data: {{
    labels: {mo_labels},
    datasets: [
      {{
        label: 'ROAS Mensual',
        data: roasData,
        borderColor: '#10B981',
        backgroundColor: ctx => {{
          const g = ctx.chart.ctx.createLinearGradient(0,0,0,200);
          g.addColorStop(0,'#10B98133'); g.addColorStop(1,'#10B98100');
          return g;
        }},
        fill: true, tension: .35, pointRadius: 4,
        pointBackgroundColor: roasData.map(v => v !== null && v < 1.5 ? '#ef4444' : '#10B981'),
      }},
      {{
        label: 'Umbral mínimo (1,5)',
        data: Array(__N_MONTHS__).fill(1.5),
        borderColor: '#ef444477',
        borderWidth: 1.5,
        borderDash: [6,4],
        pointRadius: 0,
        fill: false,
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{position:'top', labels:{{color:'#94a3b8',boxWidth:12}}}},
      tooltip: {{callbacks: {{label: c => ' ROAS: ' + (c.raw ? c.raw.toFixed(2).replace('.',',') : 'N/A')}}}}
    }},
    scales: {{
      x: {{grid}},
      y: {{grid, min: 0, title: {{display:true,text:'ROAS'}}}}
    }}
  }}
}});

// ── 4. Ranking CPR ────────────────────────────────────────────────────
new Chart(document.getElementById('rankingCpr'), {{
  type: 'bar',
  data: {{
    labels: {rank_labels},
    datasets: [{{
      label: 'Costo por Resultado (CLP)',
      data: {rank_cpr},
      backgroundColor: {rank_cpr}.map((v,i) => i < 3 ? '#22c55e99' : i >= __N_TOP__ - 3 ? '#ef444499' : '#F59E0B66'),
      borderColor:     {rank_cpr}.map((v,i) => i < 3 ? '#22c55e'   : i >= __N_TOP__ - 3 ? '#ef4444'   : '#F59E0B'),
      borderWidth: 1,
      borderRadius: 3,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    plugins: {{
      legend: {{display:false}},
      tooltip: {{callbacks: {{label: c => ' $' + Number(c.raw).toLocaleString('es-CL')}}}}
    }},
    scales: {{
      x: {{grid, title:{{display:true,text:'CLP'}}}},
      y: {{grid:{{display:false}}, ticks:{{font:{{size:10}}}}}}
    }}
  }}
}});

// ── Tabla interactiva ─────────────────────────────────────────────────
let sortDir = 1;
function sortTable(col) {{
  const tbody = document.getElementById('adsetBody');
  const rows = Array.from(tbody.rows);
  rows.sort((a, b) => {{
    const av = a.cells[col].textContent.replace(/[$.%\s\.,]/g,'').replace(',','.');
    const bv = b.cells[col].textContent.replace(/[$.%\s\.,]/g,'').replace(',','.');
    const an = parseFloat(av) || av;
    const bn = parseFloat(bv) || bv;
    return (an < bn ? -1 : an > bn ? 1 : 0) * sortDir;
  }});
  sortDir *= -1;
  rows.forEach(r => tbody.appendChild(r));
}}

function filterTable() {{
  const q = document.getElementById('tableSearch').value.toLowerCase();
  document.querySelectorAll('#adsetBody tr').forEach(r => {{
    const txt = r.textContent.toLowerCase();
    r.style.display = txt.includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
""".replace("__N_MONTHS__", str(len(monthly_series))).replace("__N_TOP__", str(len(top_adsets)))

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ HTML exportado → {filename}")

# ─── MAIN ─────────────────────────────────────────────────────────────────
def main():
    print("\n" + "═" * 60)
    print("  FLOAT CHILE — META ADS REPORT 2025")
    print(f"  Período: {DATE_START} → {DATE_END}")
    print("═" * 60)

    # 1. Init API
    try:
        init_api()
    except Exception as e:
        print(f"✗ Error al inicializar API: {e}")
        sys.exit(1)

    print("\n📡 Descargando insights...")

    # 2. Fetch data
    raw_monthly  = fetch_insights("monthly",  "adset")
    raw_weekly   = fetch_insights(7,           "adset")   # 7 días = semanal
    raw_campaign = fetch_insights("monthly",  "campaign")

    if not raw_monthly and not raw_weekly:
        print("\n⚠ No se obtuvieron datos de la API. Posibles causas:")
        print("  • Token expirado o sin permisos ads_read")
        print("  • Sin campañas activas en el período")
        print("  • ID de cuenta incorrecto")
        sys.exit(1)

    # 3. Process
    print("\n⚙️  Procesando datos...")
    monthly_rows = process_all(raw_monthly)
    weekly_rows  = process_all(raw_weekly)

    adset_agg      = aggregate_by_adset(monthly_rows)
    monthly_series = aggregate_by_month(monthly_rows)
    weekly_series  = aggregate_by_week(weekly_rows)

    if not adset_agg:
        print("⚠ No se pudieron agregar datos por ad set.")
        adset_agg = []
    if not monthly_series:
        monthly_series = []
    if not weekly_series:
        weekly_series = []

    # 4. KPIs globales
    kpis = global_kpis(adset_agg, monthly_series)

    # 5. Estacionalidad
    seasonality, avgs = seasonality_analysis(weekly_series, adset_agg)

    # 6. Exportar CSV
    print("\n💾 Exportando datos...")
    export_csv(monthly_rows, "reporte_float_2025.csv")

    # 7. Generar HTML
    generate_html(
        kpis, adset_agg, monthly_series, weekly_series,
        seasonality, avgs,
        "reporte_float_2025.html"
    )

    # 8. Resumen ejecutivo en consola
    summary = executive_summary(kpis, adset_agg, seasonality, avgs)
    print("\n" + summary)

    # Alertas finales
    burnout = [a for a in adset_agg if a["frequency"] and a["frequency"] > 3.5]
    if burnout:
        print(f"\n  🔥 ATENCIÓN: {len(burnout)} ad set(s) con frecuencia > 3.5")
        for a in burnout:
            print(f"     • {a['adset_name']} — freq {fmt_cl(a['frequency'], 1)}")

    if kpis["roas"] and kpis["roas"] < 1.5:
        print(f"\n  ⚠️  ALERTA CRÍTICA: ROAS general ({fmt_cl(kpis['roas'], 2)}) está bajo el umbral de 1,5")

    print("\n  ✅ Listo. Archivos generados:")
    print("     → reporte_float_2025.html")
    print("     → reporte_float_2025.csv")
    print()

if __name__ == "__main__":
    main()
