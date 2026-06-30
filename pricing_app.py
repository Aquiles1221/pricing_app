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
from reportlab.lib.enums import TA_RIGHT, TA_LEFT

# ======================================================
# CONFIGURACIÓN Y CONSTANTES
# ======================================================
# Todas las tarifas en CLP. Ajusta estos valores en un solo lugar.

# Precio de material (CLP por gramo) — costo real del filamento
MATERIAL_PRICES = {
    "PLA": 20,
    "ABS": 13,
    "PETG": 16,
    "TPU": 25,   # TPU es más caro y más difícil de imprimir; corregido al alza
}

# Energía
PRINTER_POWER_KW = 0.13       # consumo medio Ender 3 V3 SE
ELECTRICITY_PRICE = 200       # CLP por kWh

# --- Tarifas de servicio (modelo corregido) ---
# Diseño: TARIFA FIJA POR PIEZA, no por hora.
# Razón: cobrar por hora castiga tu eficiencia y subvalora el entregable
# (un archivo CAD que el cliente puede usar para producción en serie).
DESIGN_FIXED = {
    "Pieza simple (1 cuerpo, geometría básica)": 18000,
    "Pieza con plano técnico de fabricación": 25000,
    "Transferencia de archivos CAD nativos": 12000,
}

# Post-procesado / trabajo manual (lijado, ensamblaje, acabado)
HANDWORK_RATE = 5000          # CLP / hora  (antes 3000 — subvalorado)

# Tarifa por tamaño de impresión = TU MARGEN REAL.
# El material cuesta ~$1.000; el valor lo pones acá.
SIZE_FEES = {
    "Pequeña (< 50 g)": 3000,
    "Mediana (50–150 g)": 5000,
    "Grande (> 150 g)": 8000,
}

DELIVERY_FEE = 4000           # CLP

# --- Reparto de pagos entre colaboradores ---
# Fondo operacional: sale primero, financia materiales/mantención/contador.
FONDO_OPERACIONAL = 0.08      # 8% del total cobrado

# Gestión: porcentaje variable según el nivel de trabajo del gestor.
# Sale segundo, después del fondo. Por defecto el gestor eres tú.
GESTION_TIERS = {
    "Cliente conseguido + reunión técnica (12%)": 0.12,
    "Cliente referido directo, gestión media (5%)": 0.05,
    "Trabajo recurrente, sin gestión activa (3%)": 0.03,
}
GESTOR_DEFAULT = "Aquiles"    # editable: nombre del gestor por defecto

# ======================================================
# FUNCIONES AUXILIARES
# ======================================================

def parse_time(time_str):
    """Convierte 'HHhMMm' a horas decimales. '01h35m' -> 1.583"""
    match = re.match(r"(\d+)h(\d+)m", time_str.strip())
    if not match:
        return 0.0
    return int(match.group(1)) + int(match.group(2)) / 60.0


def print_cost_single(material, grams, time_hours, size_label):
    """Costo de UNA pieza impresa: material + energía + margen por tamaño."""
    material_cost = grams * MATERIAL_PRICES[material]
    energy_cost = time_hours * PRINTER_POWER_KW * ELECTRICITY_PRICE
    size_fee = SIZE_FEES.get(size_label, 0)
    return {
        "material": round(material_cost),
        "energy": round(energy_cost),
        "size_fee": size_fee,
        "subtotal": round(material_cost + energy_cost + size_fee),
    }


def clp(n):
    """Formatea un entero como CLP: 25000 -> '$25.000'."""
    return f"${n:,.0f}".replace(",", ".")


def build_report_pdf(data):
    """Genera el reporte técnico de cotización como PDF profesional."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#6b6b6b")
    line = colors.HexColor("#d9d9d9")
    accent = colors.HexColor("#2b2b2b")

    styles = getSampleStyleSheet()
    h_company = ParagraphStyle(
        "company", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=16, textColor=ink, spaceAfter=2, leading=19,
    )
    h_sub = ParagraphStyle(
        "sub", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.5, textColor=muted, spaceAfter=2, leading=12,
    )
    doc_title = ParagraphStyle(
        "doctitle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=10, textColor=muted, alignment=TA_RIGHT, leading=13,
    )
    section = ParagraphStyle(
        "section", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10.5, textColor=accent, spaceBefore=14, spaceAfter=6, leading=13,
    )
    body = ParagraphStyle(
        "body", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.5, textColor=ink, leading=14,
    )
    note = ParagraphStyle(
        "note", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8.5, textColor=muted, leading=12,
    )

    story = []

    # --- Encabezado ---
    header_tbl = Table(
        [[
            Paragraph("Cotizador Piezas 3D", h_company),
            Paragraph("COTIZACIÓN", doc_title),
        ],
        [
            Paragraph("Diseño CAD y Manufactura Aditiva", h_sub),
            Paragraph(data["fecha"], doc_title),
        ]],
        colWidths=[100 * mm, 66 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6))
    story.append(Table([[""]], colWidths=[166 * mm], style=TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, accent),
    ])))
    story.append(Spacer(1, 10))

    # --- Datos del cliente ---
    info_rows = [
        ["Cliente", data["cliente"] or "—"],
        ["Tipo de cliente", data["tipo_cliente"]],
        ["Servicio", data["servicio"]],
        ["Documento", data["doc_legal"]],
    ]
    info_tbl = Table(
        [[Paragraph(f"<font color='#6b6b6b'>{k}</font>", body),
          Paragraph(v, body)] for k, v in info_rows],
        colWidths=[40 * mm, 126 * mm],
    )
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(info_tbl)

    def items_table(rows, header):
        t = Table([header] + rows, colWidths=col_widths)
        style = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 1), (-1, -1), ink),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, line),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, line),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]
        t.setStyle(TableStyle(style))
        return t

    # --- Diseño ---
    if data["design_items"]:
        story.append(Paragraph("Ingeniería y diseño CAD", section))
        col_widths = [126 * mm, 40 * mm]
        rows = [[Paragraph(name, body), clp(val)] for name, val in data["design_items"]]
        rows.append([Paragraph("<b>Subtotal diseño</b>", body),
                     Paragraph(f"<b>{clp(data['design_total'])}</b>", body)])
        story.append(items_table(rows, ["Concepto", "Valor"]))

    # --- Impresión ---
    if data["print_items"]:
        story.append(Paragraph("Manufactura aditiva", section))
        story.append(Paragraph(f"Equipo: {data['printer']}", note))
        story.append(Spacer(1, 4))
        col_widths = [22 * mm, 30 * mm, 24 * mm, 30 * mm, 60 * mm]
        rows = []
        for p in data["print_items"]:
            rows.append([
                Paragraph(p["label"], body),
                Paragraph(p["material"], body),
                Paragraph(f"{p['grams']} g", body),
                Paragraph(p["time"], body),
                clp(p["subtotal"]),
            ])
        rows.append([Paragraph("<b>Subtotal manufactura</b>", body), "", "", "",
                     Paragraph(f"<b>{clp(data['print_total'])}</b>", body)])
        t = items_table(rows, ["Pieza", "Material", "Masa", "Tiempo", "Subtotal"])
        t.setStyle(TableStyle([("SPAN", (0, -1), (3, -1))]))
        story.append(t)

    # --- Extras ---
    extras = []
    if data["handwork_total"] > 0:
        extras.append([Paragraph("Post-procesado / trabajo manual", body), clp(data["handwork_total"])])
    if data["delivery_total"] > 0:
        extras.append([Paragraph("Despacho", body), clp(data["delivery_total"])])
    if extras:
        story.append(Paragraph("Servicios adicionales", section))
        col_widths = [126 * mm, 40 * mm]
        story.append(items_table(extras, ["Concepto", "Valor"]))

    # --- Total ---
    story.append(Spacer(1, 14))
    total_tbl = Table(
        [[Paragraph("<b>TOTAL</b>", ParagraphStyle("tl", parent=body, fontSize=12)),
          Paragraph(f"<b>{clp(data['total'])}</b>",
                    ParagraphStyle("tr", parent=body, fontSize=12, alignment=TA_RIGHT))]],
        colWidths=[126 * mm, 40 * mm],
    )
    total_tbl.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1, accent),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(total_tbl)
    story.append(Paragraph(data["iva_nota"], note))

    # --- Nota de producción ---
    if data["nota_produccion"]:
        story.append(Spacer(1, 16))
        story.append(Paragraph("Nota sobre producción posterior", section))
        story.append(Paragraph(
            "Esta cotización cubre el diseño y los prototipos de validación. La "
            "producción en serie se cotiza por separado, con tarifa unitaria por "
            "volumen, y se entiende que la fabricación se realiza con el mismo "
            "proveedor salvo acuerdo en contrario.", note))

    # --- Pie ---
    story.append(Spacer(1, 22))
    story.append(Paragraph(
        "Cotización válida por 15 días. Precios en pesos chilenos (CLP).", note))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ======================================================
# UI PRINCIPAL
# ======================================================

st.set_page_config(page_title="Cotizador Piezas 3D", page_icon="🛠️", layout="centered")

tab_cot, tab_liq, tab_tutorial = st.tabs(["🛠️ Cotizar", "💸 Liquidación", "📘 Tutorial"])

# ------------------------------------------------------
# PESTAÑA: COTIZAR
# ------------------------------------------------------
with tab_cot:
    st.title("🛠️ Cotizador Piezas 3D")
    st.caption("Diseño CAD + Manufactura aditiva")

    cliente = st.text_input("Nombre del cliente")
    tipo_cliente = st.selectbox("Tipo de cliente", ["Particular", "Empresa"])

    servicio = st.selectbox(
        "Tipo de servicio",
        ["Solo diseño", "Solo impresión", "Diseño + impresión"],
    )

    # --- Sección diseño ---
    design_items = []
    if servicio in ("Solo diseño", "Diseño + impresión"):
        st.subheader("Diseño CAD")
        st.caption("Tarifa fija por entregable (no por hora).")
        for name, val in DESIGN_FIXED.items():
            if st.checkbox(f"{name} — ${val:,}", key=f"d_{name}"):
                design_items.append((name, val))

    # --- Sección impresión ---
    print_items = []
    if servicio in ("Solo impresión", "Diseño + impresión"):
        st.subheader("Piezas a imprimir")
        n_pieces = st.number_input("¿Cuántas piezas distintas?", min_value=0, max_value=20, value=1, step=1)
        for i in range(int(n_pieces)):
            with st.expander(f"Pieza {i+1}", expanded=(i == 0)):
                material = st.selectbox("Material", list(MATERIAL_PRICES.keys()), key=f"mat_{i}")
                grams = st.number_input("Gramos", min_value=0.0, step=1.0, key=f"g_{i}")
                ptime = st.text_input("Tiempo de impresión (00h00m)", "00h00m", key=f"t_{i}")
                size = st.selectbox("Tamaño", list(SIZE_FEES.keys()), key=f"s_{i}")
                qty = st.number_input("Cantidad de esta pieza", min_value=1, value=1, step=1, key=f"q_{i}")

                if grams > 0:
                    c = print_cost_single(material, grams, parse_time(ptime), size)
                    for _ in range(int(qty)):
                        print_items.append({
                            "label": f"P{i+1}",
                            "material": material,
                            "grams": grams,
                            "time": ptime,
                            "subtotal": c["subtotal"],
                        })
                    st.caption(
                        f"Material ${c['material']:,} + energía ${c['energy']:,} "
                        f"+ tamaño ${c['size_fee']:,} = ${c['subtotal']:,} c/u × {int(qty)}"
                    )

    # --- Post-procesado y despacho ---
    st.subheader("Extras")
    handwork_time = st.text_input("Post-procesado / trabajo manual (00h00m)", "00h00m")
    delivery = st.checkbox("Requiere despacho")

    # --- Cálculo ---
    if st.button("Calcular cotización", type="primary"):
        design_total = sum(v for _, v in design_items)
        print_total = sum(p["subtotal"] for p in print_items)
        handwork_total = round(parse_time(handwork_time) * HANDWORK_RATE)
        delivery_total = DELIVERY_FEE if delivery else 0
        total = design_total + print_total + handwork_total + delivery_total

        if tipo_cliente == "Empresa":
            iva_nota = "Aplica al formalizar SpA (factura + 19%). Como persona natural, no aplica."
        else:
            iva_nota = "No aplica (boleta de honorarios, persona natural)."

        report_data = {
            "fecha": date.today().strftime("%d-%m-%Y"),
            "cliente": cliente,
            "tipo_cliente": tipo_cliente,
            "servicio": servicio,
            "doc_legal": "Boleta de honorarios electrónica",
            "design_items": design_items,
            "design_total": design_total,
            "print_items": print_items,
            "print_total": print_total,
            "printer": "Ender 3 V3 SE",
            "handwork_total": handwork_total,
            "delivery_total": delivery_total,
            "total": total,
            "iva_nota": iva_nota,
            "nota_produccion": bool(design_items),
        }

        st.success(f"💰 Total: {int(total):,} CLP")

        # Desglose visible
        if design_total:
            st.write(f"Diseño: ${design_total:,}")
        if print_total:
            st.write(f"Impresión: ${print_total:,}")
        if handwork_total:
            st.write(f"Post-procesado: ${handwork_total:,}")
        if delivery_total:
            st.write(f"Despacho: ${delivery_total:,}")

        # --- Reporte técnico descargable (PDF) ---
        report_pdf = build_report_pdf(report_data)
        st.download_button(
            label="📄 Descargar cotización (.pdf)",
            data=report_pdf,
            file_name=f"cotizacion_{(cliente or 'cliente').replace(' ', '_')}.pdf",
            mime="application/pdf",
        )

        st.divider()

        # --- Botón de contabilidad (PRE-HECHO, sin desarrollar) ---
        st.caption("Cuando el trabajo esté cerrado y pagado:")
        if st.button("✅ Registrar en libro contable (próximamente)"):
            # TODO: implementar a futuro.
            # Esta función debe agregar una fila al libro contable Excel con:
            #   - Fecha de emisión de boleta
            #   - N° de boleta de honorarios
            #   - Cliente y RUT
            #   - Monto bruto
            #   - Retención 13,75% (si cliente es empresa)
            #   - Monto líquido recibido
            #   - Categoría de ingreso (diseño / impresión / mixto)
            # Servirá para la Operación Renta anual y eventual contabilidad SpA.
            st.info(
                "Función pendiente de desarrollo. Registrará la cotización en el "
                "libro contable (monto, retención, boleta, RUT) para uso tributario."
            )


# ------------------------------------------------------
# PESTAÑA: LIQUIDACIÓN (reparto entre colaboradores)
# ------------------------------------------------------
with tab_liq:
    st.title("💸 Liquidación por rol")
    st.caption("Reparto justo según el valor que aporta cada colaborador.")

    st.markdown(
        "Ingresa el valor cobrado al cliente por cada componente del trabajo. "
        "El reparto se calcula sobre el **total cobrado**: primero sale el fondo "
        "operacional, luego la gestión, y lo restante se divide entre los roles "
        "según el valor que cada uno generó."
    )

    st.subheader("Valor por componente (CLP)")
    col1, col2 = st.columns(2)
    with col1:
        liq_design = st.number_input("Diseño CAD", min_value=0, step=1000, value=0, key="liq_d")
        liq_print = st.number_input("Impresión", min_value=0, step=1000, value=0, key="liq_p")
    with col2:
        liq_handwork = st.number_input("Post-procesado", min_value=0, step=1000, value=0, key="liq_h")
        liq_delivery = st.number_input("Despacho", min_value=0, step=1000, value=0, key="liq_del")

    st.subheader("Personas por rol")
    cc1, cc2 = st.columns(2)
    with cc1:
        n_design = st.number_input("Diseñadores", min_value=0, max_value=10, value=1, step=1, key="n_d")
        n_print = st.number_input("Operadores de impresión", min_value=0, max_value=10, value=1, step=1, key="n_p")
    with cc2:
        n_handwork = st.number_input("Post-procesado", min_value=0, max_value=10, value=0, step=1, key="n_h")
        n_delivery = st.number_input("Despacho", min_value=0, max_value=10, value=0, step=1, key="n_del")

    st.subheader("Gestión")
    gestor = st.text_input("Nombre del gestor (quien trajo al cliente)", value=GESTOR_DEFAULT)
    gestion_tier = st.selectbox("Nivel de gestión", list(GESTION_TIERS.keys()))

    if st.button("Calcular liquidación", type="primary", key="btn_liq"):
        total_cobrado = liq_design + liq_print + liq_handwork + liq_delivery

        if total_cobrado == 0:
            st.warning("Ingresa al menos un valor para calcular la liquidación.")
        else:
            # 1. Fondo operacional (sale primero)
            fondo = round(total_cobrado * FONDO_OPERACIONAL)
            # 2. Gestión (sale segundo)
            gestion_pct = GESTION_TIERS[gestion_tier]
            gestion = round(total_cobrado * gestion_pct)
            # 3. Restante a repartir entre roles
            disponible = total_cobrado - fondo - gestion

            # Cada rol recibe en proporción al valor que generó.
            roles = [
                ("Diseño", liq_design, n_design),
                ("Impresión", liq_print, n_print),
                ("Post-procesado", liq_handwork, n_handwork),
                ("Despacho", liq_delivery, n_delivery),
            ]
            valor_total_roles = sum(v for _, v, _ in roles)

            st.success(f"💰 Total cobrado al cliente: ${total_cobrado:,}")

            st.markdown("#### Descuentos previos")
            st.write(f"Fondo operacional ({int(FONDO_OPERACIONAL*100)}%): ${fondo:,}")
            st.write(f"Gestión — {gestor} ({int(gestion_pct*100)}%): ${gestion:,}")
            st.write(f"**Disponible para roles: ${disponible:,}**")

            st.markdown("#### Pago por colaborador")
            resumen = []
            for nombre, valor, n_personas in roles:
                if valor == 0 or n_personas == 0:
                    continue
                # proporción del valor de este rol sobre el total de roles
                share_rol = round(disponible * (valor / valor_total_roles))
                por_persona = round(share_rol / n_personas)
                if n_personas == 1:
                    st.write(f"{nombre}: ${share_rol:,}")
                else:
                    st.write(
                        f"{nombre}: ${share_rol:,} → ${por_persona:,} c/u "
                        f"({n_personas} personas, 50/50)"
                    )
                resumen.append((nombre, share_rol, n_personas, por_persona))

            # Verificación de cuadre
            repartido = sum(r[1] for r in resumen)
            descuadre = disponible - repartido
            if abs(descuadre) > 0:
                st.caption(
                    f"Ajuste por redondeo: ${descuadre:,} "
                    "(se suma al fondo operacional)."
                )

            st.divider()
            st.caption(
                "El gestor cobra su porcentaje aunque también haya hecho un rol; "
                "en ese caso suma ambos montos. Nadie cobra hasta que el cliente "
                "haya pagado."
            )


# ------------------------------------------------------
# PESTAÑA: TUTORIAL
# ------------------------------------------------------
with tab_tutorial:
    st.title("📘 Cómo usar el cotizador")

    st.markdown(
        """
### Idea general
La herramienta calcula el precio de un trabajo separando tres componentes
independientes: **diseño**, **impresión** y **trabajo manual**. Cada uno
responde a una lógica de costo distinta, por lo que se cotizan por separado
y no bajo una única tarifa horaria.

---

### 1. Diseño — tarifa fija por entregable
El diseño se cobra por **entregable**, no por el tiempo invertido. El valor de
un archivo CAD no depende de cuánto se tardó en producirlo, sino del resultado
que recibe el cliente: un archivo reutilizable que puede emplear en producción.

- Pieza simple: $18.000
- Pieza con plano técnico de fabricación: $25.000
- Transferencia de archivos CAD nativos: $12.000

Cuando un diseño servirá de base para producción en serie, constituye un activo
para el cliente. La tarifa debe reflejar ese valor, no únicamente las horas de
modelado.

---

### 2. Impresión — material, energía y tamaño
El costo del filamento por pieza es bajo (aproximadamente $1.000 para una pieza
mediana). El margen del servicio se asigna mediante la **tarifa por tamaño**,
que cubre desgaste de equipo, tiempo de operación y utilidad:

- Pequeña (< 50 g): $3.000
- Mediana (50–150 g): $5.000
- Grande (> 150 g): $8.000

Indica cuántas piezas distintas incluye el trabajo; cada una admite su propio
material, gramaje, tiempo y cantidad.

---

### 3. Post-procesado y despacho
- Trabajo manual (lijado, ensamblaje, acabado): $5.000/hora.
- Despacho: $4.000 (tarifa fija).

---

### 4. Reporte técnico
Al calcular, la herramienta genera un archivo **.txt** con el desglose por ítem,
listo para enviar al cliente como cotización formal.

---

### 5. Registro contable (en desarrollo)
El botón de registro contable dejará la cotización preparada para la **Operación
Renta** anual y la contabilidad de la SpA. Actualmente está pre-implementado, sin
función activa.

---

### Formato de tiempo
Usa siempre el formato `HHhMMm`. Ejemplos: `01h35m`, `00h45m`, `02h00m`.

---

### Modelo de costos

El precio total es la suma de los tres componentes más los extras:

$$
P_{total} = C_{diseño} + C_{impresión} + C_{manual} + C_{despacho}
$$

**Diseño** — suma de las tarifas fijas de los entregables seleccionados:

$$
C_{diseño} = \\sum_{i=1}^{n} D_i
$$

**Impresión** — para cada pieza, material más energía más tarifa de tamaño,
multiplicado por la cantidad:

$$
C_{impresión} = \\sum_{j=1}^{m} q_j \\left( g_j \\cdot p_{m_j} + t_j \\cdot W \\cdot E + F_{s_j} \\right)
$$

**Trabajo manual** — horas por la tarifa horaria:

$$
C_{manual} = h \\cdot R_{manual}
$$

**Despacho** — tarifa fija si aplica:

$$
C_{despacho} = \\begin{cases} F_{despacho} & \\text{si requiere despacho} \\\\ 0 & \\text{en caso contrario} \\end{cases}
$$

---

#### Variables

| Símbolo | Variable | Unidad |
|---|---|---|
| $P_{total}$ | Precio total de la cotización | CLP |
| $D_i$ | Tarifa fija del entregable de diseño $i$ | CLP |
| $n$ | Número de entregables de diseño | — |
| $q_j$ | Cantidad de la pieza $j$ | unidades |
| $g_j$ | Masa de material de la pieza $j$ | g |
| $p_{m_j}$ | Precio del material de la pieza $j$ | CLP/g |
| $t_j$ | Tiempo de impresión de la pieza $j$ | h |
| $W$ | Potencia de la impresora | kW |
| $E$ | Precio de la electricidad | CLP/kWh |
| $F_{s_j}$ | Tarifa por tamaño de la pieza $j$ | CLP |
| $m$ | Número de piezas distintas | — |
| $h$ | Horas de trabajo manual | h |
| $R_{manual}$ | Tarifa de trabajo manual | CLP/h |
| $F_{despacho}$ | Tarifa fija de despacho | CLP |

---

#### Valores actuales de los parámetros

| Parámetro | Símbolo | Valor |
|---|---|---|
| Potencia de impresora | $W$ | 0,13 kW |
| Precio electricidad | $E$ | 200 CLP/kWh |
| Material PLA | $p_m$ | 20 CLP/g |
| Material ABS | $p_m$ | 13 CLP/g |
| Material PETG | $p_m$ | 16 CLP/g |
| Material TPU | $p_m$ | 25 CLP/g |
| Tarifa manual | $R_{manual}$ | 5.000 CLP/h |
| Despacho | $F_{despacho}$ | 4.000 CLP |

---

### Liquidación: reparto entre colaboradores

El pago a cada colaborador se calcula sobre el **total cobrado al cliente**, no
por porcentajes fijos de rol. La lógica: cada quien cobra en proporción al valor
que aportó en esa cotización específica.

El orden de los descuentos es:

$$
\\text{Disponible} = T - (T \\cdot f) - (T \\cdot g)
$$

donde $T$ es el total cobrado, $f$ el fondo operacional (8%) y $g$ el porcentaje
de gestión (variable). Lo disponible se reparte entre roles:

$$
\\text{Pago}_{rol} = \\text{Disponible} \\cdot \\frac{V_{rol}}{\\sum V_{rol}}
$$

Si un rol lo realizan varias personas, el pago de ese rol se divide en partes
iguales (50/50 si son dos). El gestor cobra su porcentaje aparte; si además hizo
un rol, suma ambos montos.

**Regla firme:** nadie cobra hasta que el cliente haya pagado.
"""
    )
