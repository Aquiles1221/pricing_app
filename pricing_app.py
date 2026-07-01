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

# --- Materiales de impresión (CLP por gramo) ---
MATERIAL_PRICES = {
    "PLA": 20,
    "ABS": 13,
    "PETG": 16,
    "TPU": 25,
}

# --- Energía (componente menor, transparencia) ---
PRINTER_POWER_KW = 0.13
ELECTRICITY_PRICE = 200

# --- Impresión: la hora-impresora es el driver principal ---
TARIFA_IMPRESORA_HORA = 2000     # CLP/h — desgaste, atención, riesgo, oportunidad
COMPLEXITY_FEES = {
    "Simple (sin soportes, imprime sola)": 0,
    "Media (algunos soportes / vigilancia)": 1500,
    "Compleja (muchos soportes / alto riesgo)": 3000,
}
MINIMUM_PRINT_FEE = 4000         # piso por pieza impresa

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

# --- Reparto entre colaboradores ---
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


def print_piece_cost(material, grams, time_hours, complexity_label):
    """Costo de una pieza impresa (hora-impresora + material + complejidad, con piso)."""
    material_cost = grams * MATERIAL_PRICES[material]
    energy_cost = time_hours * PRINTER_POWER_KW * ELECTRICITY_PRICE
    printer_cost = time_hours * TARIFA_IMPRESORA_HORA
    complexity_fee = COMPLEXITY_FEES.get(complexity_label, 0)
    raw = material_cost + energy_cost + printer_cost + complexity_fee
    return round(max(raw, MINIMUM_PRINT_FEE))


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
        [Paragraph("Cotizador Piezas 3D", s["company"]), Paragraph(doc_label, s["title"])],
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

st.set_page_config(page_title="Cotizador Piezas 3D", page_icon="🛠️", layout="centered")
tab_cot, tab_tutorial = st.tabs(["🛠️ Cotizar", "📘 Tutorial"])

with tab_cot:
    st.title("🛠️ Cotizador Piezas 3D")
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
                material = st.selectbox("Material", list(MATERIAL_PRICES.keys()), key=f"mat_{i}")
                grams = st.number_input("Gramos", min_value=0.0, step=1.0, key=f"g_{i}")
                ptime = st.text_input("Tiempo de impresión (00h00m)", "00h00m", key=f"t_{i}")
                cx = st.selectbox("Complejidad", list(COMPLEXITY_FEES.keys()), key=f"cx_{i}")
                qty = st.number_input("Cantidad", min_value=1, value=1, step=1, key=f"q_{i}")
                unit = print_piece_cost(material, grams, parse_time(ptime), cx)
                value = unit * int(qty)
                sections["Manufactura aditiva (impresión)"].append(
                    (f"Pieza impresa {material} {grams:.0f}g × {int(qty)}", value))
                if grams > 0:
                    st.caption(f"${unit:,} c/u × {int(qty)} = ${value:,}")

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
    st.subheader("Reparto entre colaboradores")
    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        n_diseno = st.number_input("Diseñadores", min_value=0, max_value=10, value=1, step=1)
        n_impr = st.number_input("Impresión", min_value=0, max_value=10, value=1, step=1)
    with pc2:
        n_subcon = st.number_input("Subcontratación", min_value=0, max_value=10, value=0, step=1)
        n_post = st.number_input("Post-procesado", min_value=0, max_value=10, value=0, step=1)
    with pc3:
        n_desp = st.number_input("Despacho", min_value=0, max_value=10, value=0, step=1)
    gestor = st.text_input("Gestor (quien trajo al cliente)", value=GESTOR_DEFAULT)
    gestion_tier = st.selectbox("Nivel de gestión", list(GESTION_TIERS.keys()))

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

            # Escala proporcional de role_values para que la liquidación
            # refleje el dinero realmente cobrado, no el precio de lista.
            factor = (subtotal_propio - descuento_monto) / subtotal_propio if subtotal_propio > 0 else 1
            role_values_final = {r: round(v * factor) for r, v in role_values.items()}

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
            st.subheader("💸 Liquidación entre colaboradores")
            people = {"Diseño": n_diseno, "Impresión": n_impr, "Subcontratación": n_subcon,
                      "Post-procesado": n_post, "Despacho": n_desp}
            liq = compute_liquidation(
                role_values=role_values_final, people=people, terceros=terceros_cost,
                gestion_pct=GESTION_TIERS[gestion_tier], gestor=gestor,
            )
            if descuento_monto:
                st.caption(
                    f"El descuento de ${descuento_monto:,} se descontó de tu valor agregado "
                    "antes del reparto. El costo de terceros no se vio afectado."
                )
            st.write(f"Base de reparto (sin costo de terceros): ${liq['base']:,}")
            st.write(f"Fondo operacional ({int(FONDO_OPERACIONAL*100)}%): ${liq['fondo']:,}")
            st.write(f"Gestión — {liq['gestor']} ({int(liq['gestion_pct']*100)}%): ${liq['gestion']:,}")
            st.write(f"**Disponible para roles: ${liq['disponible']:,}**")
            for p in liq["pagos"]:
                if p["personas"] == 1:
                    st.write(f"{p['rol']}: ${p['total_rol']:,}")
                else:
                    st.write(f"{p['rol']}: ${p['total_rol']:,} → ${p['por_persona']:,} c/u "
                             f"({p['personas']} personas)")
            if liq["terceros"] > 0:
                st.caption(f"Costo de terceros (pagado a proveedores externos, no se reparte): ${liq['terceros']:,}")

            st.download_button(
                "📄 Descargar liquidación interna (.pdf)",
                data=build_liquidation_pdf(liq, cliente, quote_data["fecha"]),
                file_name=f"liquidacion_{(cliente or 'cliente').replace(' ', '_')}.pdf",
                mime="application/pdf",
            )


with tab_tutorial:
    st.title("📘 Cómo usar el cotizador")
    st.markdown(
        """
### Modelo de ítems
Cada trabajo es una lista de **ítems independientes**. Agregas los que
necesites, de cualquier tipo, en cualquier combinación. Esto permite cotizar
un plano solo, una pieza impresa sin plano, o una pieza que no fabricas tú
pero sí diseñas.

**Tipos de ítem disponibles:**
- **Diseño CAD** — tarifa fija por entregable, no por hora
- **Plano técnico** — entregable independiente; lo cobras aunque otro fabrique la pieza
- **Transferencia CAD** — derecho sobre los archivos nativos
- **Pieza impresa 3D** — modelo hora-impresora (material + tiempo × tarifa + complejidad)
- **Pieza subcontratada** — la fabrica un taller externo; ingresas su costo + markup opcional
- **Material / insumo** — cilindros de acero, insertos, tornillería; costo + markup opcional
- **Terminación** — menú de acabados (lijado, primer+pintura, resina UV, premium)
- **Ensamblaje / manual** — tu tiempo de trabajo a mano
- **Despacho** — tarifa fija

---

### Subcontratación y material: markup
Cuando marcas "aplicar markup 25%", el costo del taller o del insumo se
multiplica por 1,25 en el precio al cliente. El **markup se queda en la empresa**
y se reparte entre colaboradores; el **costo base se paga al proveedor externo**
y NO entra al reparto.

Ejemplo: taller cobra $8.000 por cilindros de acero. Con markup, el cliente paga
$10.000. Los $8.000 van al taller; los $2.000 de markup entran a la base de reparto.

---

### Terminación (menú plano)
- Lijado básico: $2.000
- Lijado fino + imprimación: $5.000
- Primer + pintura: $9.000
- Recubrimiento resina UV: $7.000
- Pintura + resina UV (premium): $14.000

---

### Impresión — hora-impresora
$$
\\text{costo} = \\text{material} + \\text{energía} + (\\text{horas} \\times R_{imp}) + \\text{complejidad}
$$
- Tarifa hora-impresora: $2.000/h
- Complejidad: $0 / $1.500 / $3.000 (soportes, vigilancia, riesgo)
- Tarifa mínima por pieza: $4.000

---

### Descuento manual
El descuento se aplica **solo sobre tu valor agregado** (diseño, impresión,
terminación, tu markup) — nunca sobre el costo de terceros (taller, material
comprado). Ese costo es fijo, se lo debes al proveedor externo tal cual, con o
sin descuento al cliente.

$$
V_{propio} = \\sum \\text{valor de rol (sin costo de terceros)}
$$

$$
\\text{Descuento (CLP)} = V_{propio} \\times \\frac{\\%\\text{descuento}}{100}
$$

$$
\\text{Total final} = (\\text{Total bruto}) - \\text{Descuento (CLP)}
$$

El PDF de cotización muestra el subtotal, el descuento y el total por separado
— nunca se oculta. La liquidación entre colaboradores se recalcula con el valor
ya descontado, para que el reparto refleje el dinero real que entra, no el
precio de lista. El costo de terceros no cambia.

**Uso previsto:** este campo es para exploración/calibración, no para negociar
a la baja por costumbre. Un descuento usado como reflejo entrena al cliente a
desconfiar del precio inicial.

---

### Liquidación
El reparto se calcula sobre la **base** (total menos costo de terceros, y menos
el descuento si se aplicó). Primero sale el fondo operacional (8%), luego la
gestión (%), y lo restante se divide entre roles según el valor que cada uno
generó. Si un rol lo hacen varias personas, se divide en partes iguales.

**Regla firme:** nadie cobra hasta que el cliente haya pagado. El costo de
terceros se paga al proveedor externo, no se reparte.

---

### Formato de tiempo
Usa `HHhMMm`. Ejemplos: `01h35m`, `00h45m`, `02h00m`.
"""
    )
