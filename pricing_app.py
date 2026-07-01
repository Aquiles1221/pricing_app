import streamlit as st
import re
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.lib.enums import TA_RIGHT

# ======================================================
# CONFIGURACIÓN Y CONSTANTES  (todo en CLP)
# ======================================================

# --- Materiales de impresión (CLP por gramo) — valores validar contra proveedor ---
MATERIAL_PRICES = {
    "PLA": 20,
    "PETG": 22,
    "ABS": 24,
    "ASA": 29,    # material CORE para piezas T1 (resiste vibración y calor)
    "TPU": 31,
}

# --- Energía y máquinas ---
ELECTRICITY_PRICE = 200          # CLP por kWh

# Cada máquina tiene su propia potencia y tarifa hora-impresora.
# La tarifa refleja: costo de máquina amortizado, velocidad, capacidad de
# material técnico, tasa de falla, y ocupación del recurso.
PRINTERS = {
    "Ender 3":         {"W": 0.13, "R_imp": 1500, "apta_tecnico": False},
    "Ender 3 V3 SE":   {"W": 0.13, "R_imp": 2000, "apta_tecnico": False},
    "K1C (encerrada)": {"W": 0.35, "R_imp": 4000, "apta_tecnico": True},
}
MATERIALES_TECNICOS = {"ASA", "ABS"}   # requieren máquina apta

# --- Impresión: complejidad y piso ---
COMPLEXITY_FEES = {
    "Simple (sin soportes, imprime sola)": 0,
    "Media (algunos soportes / vigilancia)": 1500,
    "Compleja (muchos soportes / alto riesgo)": 3000,
}
MINIMUM_PRINT_FEE = 4000

# --- T1 (import-substitution): value-based override ---
# El precio ancla captura una fracción del import evitado; el resto es
# el incentivo del cliente por comprar local y rápido.
T1_CAPTURE_FACTOR = 0.65         # validar entre 0.60 y 0.75
# En piezas T1 NUEVAS, la merma cubre reimpresiones y ajuste dimensional.
MERMA_T1_NUEVA = 1.5

# --- Diseño CAD (tarifa fija por entregable) ---
DESIGN_FIXED = {
    "Pieza simple (1 cuerpo, geometría básica)": 18000,
    "Pieza compleja / ensamblaje": 28000,
}

# --- Plano técnico (entregable independiente del diseño) ---
PLANO_FIXED = {
    "Plano básico (1 vista + cotas)": 8000,
    "Plano de fabricación completo (vistas + tolerancias)": 15000,
}

# --- Transferencia de archivos CAD nativos ---
CAD_TRANSFER_FEE = 12000

# --- Terminación / acabado (menú plano) ---
FINISH_MENU = {
    "Lijado básico": 2000,
    "Lijado fino + imprimación (primer)": 5000,
    "Primer + pintura": 9000,
    "Recubrimiento resina UV": 7000,
    "Pintura + resina UV (premium)": 14000,
}

# --- Trabajo manual / ensamblaje (por hora) ---
HANDWORK_RATE = 5000

# --- Subcontratación y material comprado ---
SUBCON_MARKUP = 0.25             # 25% si se activa el markup
DELIVERY_FEE = 4000

# --- Reparto entre colaboradores — INACTIVO (un solo dueño hoy) ---
# Se conserva para el futuro cuando el negocio se formalice como SpA con socios.
# Hoy, el pago a ingenieros externos es COSTO DIRECTO del trabajo, no reparto
# proporcional. Ver "Mano de obra externa" en la UI.
FONDO_OPERACIONAL = 0.08
GESTION_TIERS = {
    "Cliente conseguido + reunión técnica (12%)": 0.12,
    "Cliente referido directo, gestión media (5%)": 0.05,
    "Trabajo recurrente, sin gestión activa (3%)": 0.03,
}
GESTOR_DEFAULT = "Aquiles"

# Mapeo de tipo de ítem -> rol de liquidación
ITEM_ROLE = {
    "Diseño CAD": "Diseño",
    "Plano técnico": "Diseño",
    "Transferencia CAD": "Diseño",
    "Pieza impresa 3D": "Impresión",
    "Pieza subcontratada": "Subcontratación",
    "Material / insumo": "Subcontratación",
    "Terminación": "Post-procesado",
    "Ensamblaje / manual": "Post-procesado",
    "Despacho": "Despacho",
}


# ======================================================
# FUNCIONES AUXILIARES
# ======================================================

def parse_time(time_str):
    """'01h35m' -> 1.583 horas."""
    match = re.match(r"(\d+)h(\d+)m", time_str.strip())
    if not match:
        return 0.0
    return int(match.group(1)) + int(match.group(2)) / 60.0


def clp(n):
    return f"${n:,.0f}".replace(",", ".")


def print_piece_cost(material, grams, time_hours, complexity_label,
                     machine, es_T1=False, repite_diseno=False,
                     precio_import_landed=0):
    """
    Costo de una pieza impresa.
    - Piso cost-plus siempre aplica: material + energía + hora-máquina + K, con F_min.
    - Si es T1 con precio_import_landed conocido, aplica el ancla value-based:
      precio = max(cost_plus, import × factor).
    - Merma T1 solo aplica a piezas T1 nuevas (repite_diseno = False).
    """
    W = PRINTERS[machine]["W"]
    R_imp = PRINTERS[machine]["R_imp"]

    merma = MERMA_T1_NUEVA if (es_T1 and not repite_diseno) else 1.0
    grams_facturables = grams * merma

    material_cost = grams_facturables * MATERIAL_PRICES[material]
    energy_cost = time_hours * W * ELECTRICITY_PRICE
    printer_cost = time_hours * R_imp
    complexity_fee = COMPLEXITY_FEES.get(complexity_label, 0)
    raw = material_cost + energy_cost + printer_cost + complexity_fee
    cost_plus = max(raw, MINIMUM_PRINT_FEE)

    if es_T1 and precio_import_landed > 0:
        ancla = precio_import_landed * T1_CAPTURE_FACTOR
        return round(max(cost_plus, ancla))
    return round(cost_plus)


def subcon_client_price(cost, apply_markup):
    """Precio al cliente de un ítem subcontratado o material comprado."""
    return round(cost * (1 + SUBCON_MARKUP)) if apply_markup else round(cost)


# ======================================================
# GENERACIÓN DE PDF
# ======================================================

def _pdf_styles():
    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#6b6b6b")
    line = colors.HexColor("#d9d9d9")
    accent = colors.HexColor("#2b2b2b")
    base = getSampleStyleSheet()["Normal"]
    return {
        "ink": ink, "muted": muted, "line": line, "accent": accent,
        "company": ParagraphStyle("company", parent=base, fontName="Helvetica-Bold",
                                   fontSize=16, textColor=ink, spaceAfter=2, leading=19),
        "sub": ParagraphStyle("sub", parent=base, fontName="Helvetica",
                               fontSize=9.5, textColor=muted, leading=12),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica",
                                 fontSize=10, textColor=muted, alignment=TA_RIGHT, leading=13),
        "section": ParagraphStyle("section", parent=base, fontName="Helvetica-Bold",
                                   fontSize=10.5, textColor=accent, spaceBefore=14, spaceAfter=6, leading=13),
        "body": ParagraphStyle("body", parent=base, fontName="Helvetica",
                               fontSize=9.5, textColor=ink, leading=14),
        "note": ParagraphStyle("note", parent=base, fontName="Helvetica",
                               fontSize=8.5, textColor=muted, leading=12),
    }


def _header(story, s, subtitle, fecha, doc_label):
    header = Table([
        [Paragraph("DFP Ingeniería — Cotizador", s["company"]), Paragraph(doc_label, s["title"])],
        [Paragraph(subtitle, s["sub"]), Paragraph(fecha, s["title"])],
    ], colWidths=[100 * mm, 66 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 6))
    story.append(Table([[""]], colWidths=[166 * mm],
                       style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, s["accent"])])))
    story.append(Spacer(1, 10))


def build_quote_pdf(data):
    """Cotización para el cliente, agrupada por sección."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    s = _pdf_styles()
    story = []
    _header(story, s, "Diseño CAD, manufactura y fabricación", data["fecha"], "COTIZACIÓN")

    for k, v in [("Cliente", data["cliente"] or "—"), ("Tipo de cliente", data["tipo_cliente"]),
                 ("Documento", data["doc_legal"])]:
        story.append(Paragraph(f"<font color='#6b6b6b'>{k}:</font> {v}", s["body"]))

    for sec_name, items in data["sections"]:
        if not items:
            continue
        story.append(Paragraph(sec_name, s["section"]))
        rows = [["Detalle", "Valor"]]
        for label, val in items:
            rows.append([Paragraph(label, s["body"]), clp(val)])
        t = Table(rows, colWidths=[126 * mm, 40 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), s["accent"]),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, s["line"]),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, s["line"]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(t)

    story.append(Spacer(1, 14))
    if data.get("descuento_monto", 0) > 0:
        pre_tbl = Table([
            [Paragraph("Subtotal", s["body"]), clp(data["total_bruto"])],
            [Paragraph(f"Descuento ({data['descuento_pct']:.0f}%)", s["body"]),
             f"-{clp(data['descuento_monto'])}"],
        ], colWidths=[126 * mm, 40 * mm])
        pre_tbl.setStyle(TableStyle([
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(pre_tbl)

    total_tbl = Table([[
        Paragraph("<b>TOTAL</b>", ParagraphStyle("tl", parent=s["body"], fontSize=12)),
        Paragraph(f"<b>{clp(data['total'])}</b>",
                  ParagraphStyle("tr", parent=s["body"], fontSize=12, alignment=TA_RIGHT)),
    ]], colWidths=[126 * mm, 40 * mm])
    total_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, s["accent"]),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(total_tbl)
    story.append(Paragraph(data["iva_nota"], s["note"]))

    if data["nota_produccion"]:
        story.append(Spacer(1, 16))
        story.append(Paragraph("Nota sobre producción posterior", s["section"]))
        story.append(Paragraph(
            "Esta cotización cubre el diseño y los prototipos de validación. La "
            "producción en serie se cotiza por separado, con tarifa unitaria por "
            "volumen, y se entiende que la fabricación se realiza con el mismo "
            "proveedor salvo acuerdo en contrario.", s["note"]))

    story.append(Spacer(1, 22))
    story.append(Paragraph("Cotización válida por 15 días. Precios en pesos chilenos (CLP).", s["note"]))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def build_liquidation_pdf(liq, cliente, fecha):
    """Liquidación interna entre colaboradores."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    s = _pdf_styles()
    story = []
    _header(story, s, "Reparto entre colaboradores", fecha, "LIQUIDACIÓN INTERNA")

    story.append(Paragraph(f"<font color='#6b6b6b'>Cliente:</font> {cliente or '—'}", s["body"]))
    story.append(Paragraph(f"<font color='#6b6b6b'>Base de reparto:</font> {clp(liq['base'])} "
                           f"(total menos costos de terceros)", s["body"]))

    story.append(Paragraph("Descuentos previos", s["section"]))
    desc = Table([
        [Paragraph(f"Fondo operacional ({int(FONDO_OPERACIONAL*100)}%)", s["body"]), clp(liq["fondo"])],
        [Paragraph(f"Gestión — {liq['gestor']} ({int(liq['gestion_pct']*100)}%)", s["body"]), clp(liq["gestion"])],
        [Paragraph("<b>Disponible para roles</b>", s["body"]),
         Paragraph(f"<b>{clp(liq['disponible'])}</b>", s["body"])],
    ], colWidths=[126 * mm, 40 * mm])
    desc.setStyle(TableStyle([
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, s["line"]),
    ]))
    story.append(desc)

    story.append(Paragraph("Pago por rol", s["section"]))
    rows = [["Rol", "Personas", "Pago c/u", "Total rol"]]
    for p in liq["pagos"]:
        rows.append([Paragraph(p["rol"], s["body"]), str(p["personas"]),
                     clp(p["por_persona"]), clp(p["total_rol"])])
    pago_tbl = Table(rows, colWidths=[70 * mm, 28 * mm, 34 * mm, 34 * mm])
    pago_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), s["accent"]),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, s["line"]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, s["line"]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(pago_tbl)

    if liq["terceros"] > 0:
        story.append(Spacer(1, 10))
        story.append(Paragraph(
            f"Costos de terceros (subcontratación / material): {clp(liq['terceros'])}. "
            "No entran al reparto — se pagan al proveedor externo. El markup sí queda "
            "en la empresa y se reparte como parte de la base.", s["note"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Documento interno, no se entrega al cliente. El gestor cobra su porcentaje "
        "aparte; si además realizó un rol, suma ambos montos. Nadie cobra hasta que "
        "el cliente haya pagado.", s["note"]))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def compute_liquidation(role_values, people, terceros, gestion_pct, gestor):
    """
    role_values: dict rol -> valor generado (excluye costo de terceros, incluye markup)
    people: dict rol -> nº personas
    terceros: costo pagado a proveedores externos (no se reparte)
    Base de reparto = suma de valores de rol (ya sin costo de terceros).
    """
    base = sum(role_values.values())
    fondo = round(base * FONDO_OPERACIONAL)
    gestion = round(base * gestion_pct)
    disponible = base - fondo - gestion
    valor_total = sum(role_values.values()) or 1

    pagos = []
    for rol, valor in role_values.items():
        n = people.get(rol, 0)
        if valor <= 0 or n <= 0:
            continue
        share = round(disponible * (valor / valor_total))
        pagos.append({"rol": rol, "total_rol": share, "personas": n,
                      "por_persona": round(share / n)})

    return {"base": base, "fondo": fondo, "gestion": gestion, "gestion_pct": gestion_pct,
            "gestor": gestor, "disponible": disponible, "pagos": pagos, "terceros": terceros}


# ======================================================
# UI PRINCIPAL
# ======================================================

st.set_page_config(page_title="DFP Ingeniería — Cotizador", page_icon="🛠️", layout="centered")
tab_cot, tab_tutorial = st.tabs(["🛠️ Cotizar", "📘 Tutorial"])

with tab_cot:
    st.title("🛠️ DFP Ingeniería — Cotizador")
    st.caption("Diseño CAD · impresión · fabricación subcontratada · terminación")

    cliente = st.text_input("Nombre del cliente")
    tipo_cliente = st.selectbox("Tipo de cliente", ["Particular", "Empresa"])

    st.divider()
    st.subheader("Ítems del trabajo")
    st.caption(
        "Agrega los ítems que necesites, de cualquier tipo y en cualquier "
        "combinación. Puedes cotizar solo un plano, una pieza impresa sin plano, "
        "o una pieza que no fabricas tú pero sí diseñas."
    )

    n_items = st.number_input("¿Cuántos ítems tiene el trabajo?",
                              min_value=1, max_value=30, value=1, step=1)

    sections = {
        "Diseño e ingeniería": [],
        "Manufactura aditiva (impresión)": [],
        "Fabricación subcontratada y material": [],
        "Terminación y ensamblaje": [],
        "Despacho": [],
    }
    role_values = {"Diseño": 0, "Impresión": 0, "Subcontratación": 0,
                   "Post-procesado": 0, "Despacho": 0}
    terceros_cost = 0   # costo pagado a proveedores externos (passthrough, no se reparte)

    ITEM_TYPES = [
        "Diseño CAD", "Plano técnico", "Transferencia CAD",
        "Pieza impresa 3D", "Pieza subcontratada", "Material / insumo",
        "Terminación", "Ensamblaje / manual", "Despacho",
    ]

    for i in range(int(n_items)):
        with st.expander(f"Ítem {i+1}", expanded=(i == 0)):
            itype = st.selectbox("Tipo de ítem", ITEM_TYPES, key=f"type_{i}")
            role = ITEM_ROLE[itype]
            value = 0          # precio al cliente
            role_add = None    # cuánto entra al reparto (por defecto = value)

            if itype == "Diseño CAD":
                tier = st.selectbox("Complejidad del diseño", list(DESIGN_FIXED.keys()), key=f"d_{i}")
                value = DESIGN_FIXED[tier]
                sections["Diseño e ingeniería"].append(
                    (f"Diseño CAD — {tier.split('(')[0].strip()}", value))

            elif itype == "Plano técnico":
                tier = st.selectbox("Tipo de plano", list(PLANO_FIXED.keys()), key=f"pl_{i}")
                value = PLANO_FIXED[tier]
                sections["Diseño e ingeniería"].append(
                    (f"Plano técnico — {tier.split('(')[0].strip()}", value))

            elif itype == "Transferencia CAD":
                value = CAD_TRANSFER_FEE
                sections["Diseño e ingeniería"].append(
                    ("Transferencia de archivos CAD nativos", value))

            elif itype == "Pieza impresa 3D":
                es_T1 = st.checkbox(
                    "Pieza T1 (sustitución de importación)",
                    value=False, key=f"t1_{i}",
                    help=("Marca esto si la pieza reemplaza una que el cliente "
                          "importaría desde el extranjero. Aplica precio "
                          "value-based ancla al import."))
                repite_diseno = False
                precio_import_landed = 0
                if es_T1:
                    repite_diseno = st.checkbox(
                        "Es repetición de un diseño ya validado",
                        value=False, key=f"rep_{i}",
                        help=("Salta merma y no cobra diseño CAD aparte "
                              "(el diseño se subsume en el ancla T1)."))
                    precio_import_landed = st.number_input(
                        "Precio de la alternativa importada puesta en Chile (CLP)",
                        min_value=0, step=5000, key=f"imp_{i}",
                        help="Precio USD + envío + aduana. Base del cálculo ancla.")

                material_options = list(MATERIAL_PRICES.keys())
                material = st.selectbox("Material", material_options, key=f"mat_{i}")

                # Filtro de máquina: si el material es técnico (ASA/ABS), forzar máquina apta.
                # Además, en T1 forzamos K1C explícitamente.
                if es_T1:
                    machine_options = ["K1C (encerrada)"]
                elif material in MATERIALES_TECNICOS:
                    machine_options = [m for m, p in PRINTERS.items() if p["apta_tecnico"]]
                else:
                    machine_options = list(PRINTERS.keys())
                machine = st.selectbox("Máquina", machine_options, key=f"mch_{i}")

                grams = st.number_input("Gramos planeados", min_value=0.0, step=1.0, key=f"g_{i}")
                ptime = st.text_input("Tiempo de impresión (00h00m)", "00h00m", key=f"t_{i}")
                cx = st.selectbox("Complejidad", list(COMPLEXITY_FEES.keys()), key=f"cx_{i}")
                qty = st.number_input("Cantidad", min_value=1, value=1, step=1, key=f"q_{i}")

                unit = print_piece_cost(
                    material, grams, parse_time(ptime), cx, machine,
                    es_T1=es_T1, repite_diseno=repite_diseno,
                    precio_import_landed=precio_import_landed,
                )
                value = unit * int(qty)
                tag = " [T1]" if es_T1 else ""
                sections["Manufactura aditiva (impresión)"].append(
                    (f"Pieza impresa {material} {grams:.0f}g × {int(qty)}{tag}", value))
                if grams > 0:
                    modo = ("ancla T1" if (es_T1 and precio_import_landed *
                            T1_CAPTURE_FACTOR > unit * 0.99) else "cost-plus")
                    st.caption(f"${unit:,} c/u ({modo}) × {int(qty)} = ${value:,}")

            elif itype == "Pieza subcontratada":
                desc = st.text_input("Descripción (ej: cilindro acero 18mm × 50mm)", key=f"sd_{i}")
                cost = st.number_input("Costo que te cobra el taller (CLP)", min_value=0, step=500, key=f"sc_{i}")
                qty = st.number_input("Cantidad", min_value=1, value=1, step=1, key=f"sq_{i}")
                markup = st.checkbox("Aplicar markup 25%", value=True, key=f"sm_{i}")
                unit = subcon_client_price(cost, markup)
                value = unit * int(qty)
                terceros_cost += cost * int(qty)
                role_add = value - cost * int(qty)   # solo el markup entra al reparto
                sections["Fabricación subcontratada y material"].append(
                    (f"Pieza subcontratada — {desc or 'sin descripción'} × {int(qty)}", value))
                if cost > 0:
                    st.caption(f"${unit:,} c/u{' (con markup)' if markup else ' (a costo)'} × {int(qty)} = ${value:,}")

            elif itype == "Material / insumo":
                desc = st.text_input("Descripción (ej: inserto roscado M4, tornillería)", key=f"md_{i}")
                cost = st.number_input("Costo de compra (CLP)", min_value=0, step=500, key=f"mc_{i}")
                qty = st.number_input("Cantidad", min_value=1, value=1, step=1, key=f"mq_{i}")
                markup = st.checkbox("Aplicar markup 25%", value=True, key=f"mm_{i}")
                unit = subcon_client_price(cost, markup)
                value = unit * int(qty)
                terceros_cost += cost * int(qty)
                role_add = value - cost * int(qty)   # solo el markup entra al reparto
                sections["Fabricación subcontratada y material"].append(
                    (f"Material — {desc or 'sin descripción'} × {int(qty)}", value))
                if cost > 0:
                    st.caption(f"${unit:,} c/u{' (con markup)' if markup else ' (a costo)'} × {int(qty)} = ${value:,}")

            elif itype == "Terminación":
                finish = st.selectbox("Tipo de acabado", list(FINISH_MENU.keys()), key=f"f_{i}")
                qty = st.number_input("Cantidad de piezas a terminar", min_value=1, value=1, step=1, key=f"fq_{i}")
                value = FINISH_MENU[finish] * int(qty)
                sections["Terminación y ensamblaje"].append(
                    (f"Terminación — {finish} × {int(qty)}", value))

            elif itype == "Ensamblaje / manual":
                htime = st.text_input("Tiempo de trabajo manual (00h00m)", "00h00m", key=f"h_{i}")
                value = round(parse_time(htime) * HANDWORK_RATE)
                sections["Terminación y ensamblaje"].append(
                    ("Ensamblaje / trabajo manual", value))

            elif itype == "Despacho":
                value = DELIVERY_FEE
                sections["Despacho"].append(("Despacho", value))

            role_values[role] += value if role_add is None else role_add

    st.divider()
    st.subheader("Mano de obra externa")
    st.caption(
        "Cuando un ingeniero externo ejecuta parte del trabajo, su pago es "
        "**costo directo del trabajo** — no participación en utilidades. Se "
        "resta del valor propio antes de calcular tu utilidad final. La "
        "sección de reparto por rol está inactiva mientras haya un solo dueño."
    )
    costo_mano_obra_externa = st.number_input(
        "Costo total pagado a ingenieros/colaboradores externos (CLP)",
        min_value=0, step=5000, value=0,
    )

    st.divider()
    st.subheader("Descuento manual")
    st.caption(
        "Se aplica solo sobre tu valor agregado (diseño, impresión, terminación, "
        "tu markup). Nunca reduce lo que le debes a un tercero por subcontratación "
        "o material — ese costo es fijo y no es tuyo para descontar."
    )
    descuento_pct = st.number_input(
        "Descuento (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0
    )

    if st.button("Calcular cotización", type="primary"):
        total_bruto = sum(v for items in sections.values() for _, v in items)
        subtotal_propio = sum(role_values.values())  # excluye costo de terceros

        if total_bruto == 0:
            st.warning("Agrega al menos un ítem con valor para cotizar.")
        else:
            descuento_monto = round(subtotal_propio * (descuento_pct / 100))
            total = total_bruto - descuento_monto

            iva_nota = ("No aplica (boleta de honorarios, persona natural)."
                        if tipo_cliente == "Particular"
                        else "Aplica al formalizar SpA (factura + 19%). Como persona natural, no aplica.")

            quote_data = {
                "fecha": date.today().strftime("%d-%m-%Y"),
                "cliente": cliente, "tipo_cliente": tipo_cliente,
                "doc_legal": "Boleta de honorarios electrónica",
                "sections": list(sections.items()),
                "total_bruto": total_bruto,
                "descuento_pct": descuento_pct, "descuento_monto": descuento_monto,
                "total": total, "iva_nota": iva_nota,
                "nota_produccion": bool(sections["Diseño e ingeniería"]),
            }

            st.success(f"💰 Total: ${total:,}" + (f"  (bruto ${total_bruto:,} − descuento ${descuento_monto:,})" if descuento_monto else ""))
            for sec_name, items in sections.items():
                if items:
                    sub = sum(v for _, v in items)
                    st.write(f"**{sec_name}: ${sub:,}**")
                    for lbl, v in items:
                        st.caption(f"· {lbl}: ${v:,}")

            st.download_button(
                "📄 Descargar cotización (.pdf)",
                data=build_quote_pdf(quote_data),
                file_name=f"cotizacion_{(cliente or 'cliente').replace(' ', '_')}.pdf",
                mime="application/pdf",
            )

            st.divider()
            st.subheader("💰 Resumen económico")
            valor_propio = total_bruto - terceros_cost
            utilidad_dueno = valor_propio - descuento_monto - costo_mano_obra_externa
            st.write(f"Total al cliente: ${total:,}")
            st.write(f"Costo de terceros (pagado al taller/proveedor): ${terceros_cost:,}")
            if costo_mano_obra_externa > 0:
                st.write(f"Mano de obra externa: ${costo_mano_obra_externa:,}")
            if descuento_monto > 0:
                st.write(f"Descuento otorgado al cliente: ${descuento_monto:,}")
            st.write(f"**Utilidad del dueño: ${utilidad_dueno:,}**")
            st.caption(
                "Utilidad = valor propio − descuento − mano de obra externa. "
                "No incluye impuestos ni costos fijos (contador, arriendo, etc.)."
            )


with tab_tutorial:
    st.title("📘 Cómo usar el cotizador")
    st.markdown(
        """
### Modelo de ítems
Cada trabajo es una lista de **ítems independientes**. Agregas los que
necesites, de cualquier tipo, en cualquier combinación.

**Tipos de ítem disponibles:**
- **Diseño CAD** — tarifa fija por entregable (no aplica a T1 nuevos, ver abajo)
- **Plano técnico** — entregable independiente; se cobra aunque otro fabrique la pieza
- **Transferencia CAD** — derecho sobre los archivos nativos
- **Pieza impresa 3D** — modelo hora-máquina + T1 opcional
- **Pieza subcontratada** — la fabrica un taller externo; costo + markup opcional
- **Material / insumo** — insumos comprados; costo + markup opcional
- **Terminación** — menú de acabados
- **Ensamblaje / manual** — tiempo de trabajo a mano
- **Despacho** — tarifa fija

---

### Piezas T1 (import-substitution) — el corazón del negocio
Una pieza **T1** es una pieza de ingeniería que sustituye una que el cliente
importaría del extranjero (típicamente mounts de ECU, dashes, adaptadores
automotrices). Su valor NO es el costo de fabricar — es la alternativa que el
cliente evita.

Cuando marcas un ítem como T1 e ingresas el precio del import:

$$
\\text{precio}_{T1} = \\max(\\text{cost-plus}, \\text{precio\\_import} \\times \\text{factor})
$$

Donde `factor = 0.65` (capturas 65% del import, el resto es el incentivo del
cliente por comprar local y rápido).

**En T1 el diseño CAD no se cobra aparte** — se subsume en el precio ancla,
porque cobrarlo a $28.000 por 10 horas equivale a $2.800/h, muy bajo para un
ingeniero mecatrónico. El ancla ya incluye el valor del diseño profesional.

**Repetición:** si activas "repite_diseño", saltas el diseño y desactivas la
merma. Es el motor económico del negocio T1: el diseño es costo one-time,
las siguientes ventas del mismo diseño tienen margen ~90%+.

---

### Materiales e impresora
- Materiales técnicos (**ASA, ABS**) requieren máquina apta con enclosure
  (**K1C**); el selector filtra automáticamente.
- Piezas T1 se costean siempre con tarifa K1C.
- **Merma T1 nueva:** los gramos se multiplican por 1,5 para cubrir prints
  de prueba y ajuste dimensional. En repeticiones, merma = 1,0.

| Máquina | Tarifa hora | Materiales técnicos |
|---|---|---|
| Ender 3 | $1.500/h | No |
| Ender 3 V3 SE | $2.000/h | No |
| K1C (encerrada) | $4.000/h | Sí (ASA, ABS) |

---

### Impresión — fórmula cost-plus (piso)
$$
\\text{costo} = (g \\times \\text{merma}) \\times p_m + t \\times W \\times E + t \\times R_{imp} + K
$$

Con piso mínimo por pieza: $4.000. Si el ítem es T1, este número es solo el
piso — el precio final es `max(cost-plus, ancla_T1)`.

---

### Subcontratación y material: markup 25%
El costo base se paga al proveedor externo (pass-through, no es tuyo). El
markup (25% si activado) queda en la empresa. El descuento manual solo se
aplica sobre tu valor agregado, nunca sobre el costo pass-through.

---

### Terminación (menú plano)
- Lijado básico: $2.000
- Lijado fino + imprimación: $5.000
- Primer + pintura: $9.000
- Recubrimiento resina UV: $7.000
- Pintura + resina UV (premium): $14.000

---

### Descuento manual
Se aplica solo sobre el **valor propio** (total menos costo de terceros).
El PDF muestra `subtotal → descuento → total` como líneas separadas.

---

### Mano de obra externa (reemplaza reparto por rol)
Cuando un ingeniero externo ejecuta parte del trabajo, su pago es **costo
directo** del trabajo, no participación en utilidades. Se resta del valor
propio para calcular la utilidad del dueño:

$$
\\text{utilidad} = \\text{valor propio} - \\text{descuento} - \\text{mano obra externa}
$$

La sección anterior de "reparto por rol" está inactiva mientras haya un solo
dueño. Se reactivará si el negocio se formaliza como SpA con socios.

---

### Formato de tiempo
Usa `HHhMMm`. Ejemplos: `01h35m`, `00h45m`, `02h00m`.
"""
    )
