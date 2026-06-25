import streamlit as st
import re
from datetime import date

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


def build_report(data):
    """Genera el reporte técnico en texto plano."""
    lines = []
    lines.append("=" * 58)
    lines.append("   REPORTE TÉCNICO DE COTIZACIÓN")
    lines.append("   Fragua — Diseño CAD y Manufactura Aditiva")
    lines.append("=" * 58)
    lines.append("")
    lines.append(f"Fecha           : {data['fecha']}")
    lines.append(f"Cliente         : {data['cliente'] or '[Particular]'}")
    lines.append(f"Tipo de cliente : {data['tipo_cliente']}")
    lines.append(f"Servicio        : {data['servicio']}")
    lines.append(f"Documento legal : {data['doc_legal']}")
    lines.append("")

    if data["design_items"]:
        lines.append("-" * 58)
        lines.append("1. INGENIERÍA Y DISEÑO CAD")
        lines.append("-" * 58)
        for name, val in data["design_items"]:
            lines.append(f"  - {name:<48} {val:>7,} CLP")
        lines.append(f"  {'Subtotal diseño':<50} {data['design_total']:>7,} CLP")
        lines.append("")

    if data["print_items"]:
        lines.append("-" * 58)
        lines.append("2. MANUFACTURA ADITIVA")
        lines.append("-" * 58)
        lines.append(f"  Equipo: {data['printer']}")
        lines.append("")
        lines.append(f"  {'Pieza':<10}{'Mat.':<7}{'Masa':<7}{'Tiempo':<9}{'Subtotal':>9}")
        for p in data["print_items"]:
            lines.append(
                f"  {p['label']:<10}{p['material']:<7}{str(p['grams'])+'g':<7}"
                f"{p['time']:<9}{p['subtotal']:>7,} CLP"
            )
        lines.append(f"  {'Subtotal manufactura':<50} {data['print_total']:>7,} CLP")
        lines.append("")

    if data["handwork_total"] > 0:
        lines.append("-" * 58)
        lines.append("3. POST-PROCESADO")
        lines.append("-" * 58)
        lines.append(f"  {'Trabajo manual / acabado':<50} {data['handwork_total']:>7,} CLP")
        lines.append("")

    if data["delivery_total"] > 0:
        lines.append(f"  {'Despacho':<50} {data['delivery_total']:>7,} CLP")
        lines.append("")

    lines.append("-" * 58)
    lines.append("RESUMEN")
    lines.append("-" * 58)
    lines.append(f"  {'TOTAL SERVICIO':<50} {data['total']:>7,} CLP")
    lines.append(f"  IVA: {data['iva_nota']}")
    lines.append("")

    if data["nota_produccion"]:
        lines.append("-" * 58)
        lines.append("NOTA SOBRE PRODUCCIÓN POSTERIOR")
        lines.append("-" * 58)
        lines.append("  Esta cotización cubre diseño y prototipos de validación.")
        lines.append("  La producción en serie se cotiza por separado, con tarifa")
        lines.append("  unitaria por volumen, y se entiende que la fabricación se")
        lines.append("  realiza con el mismo proveedor salvo acuerdo en contrario.")
        lines.append("")

    lines.append("=" * 58)
    return "\n".join(lines)


# ======================================================
# UI PRINCIPAL
# ======================================================

st.set_page_config(page_title="Fragua — Cotizador", page_icon="🛠️", layout="centered")

tab_cot, tab_tutorial = st.tabs(["🛠️ Cotizar", "📘 Tutorial"])

# ------------------------------------------------------
# PESTAÑA: COTIZAR
# ------------------------------------------------------
with tab_cot:
    st.title("🛠️ Cotizador Fragua")
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

        # --- Reporte técnico descargable ---
        report_txt = build_report(report_data)
        st.download_button(
            label="📄 Descargar reporte técnico (.txt)",
            data=report_txt.encode("utf-8"),
            file_name=f"cotizacion_{(cliente or 'cliente').replace(' ', '_')}.txt",
            mime="text/plain",
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
# PESTAÑA: TUTORIAL
# ------------------------------------------------------
with tab_tutorial:
    st.title("📘 Cómo usar el cotizador")

    st.markdown(
        """
### Idea general
La app calcula un precio justo separando **tres cosas distintas**:
diseño, impresión y trabajo manual. No mezcles las tres en "una tarifa por hora".

---

### 1. Diseño — tarifa fija, no por hora
El diseño se cobra **por entregable**, no por el tiempo que tardaste.
Un archivo CAD vale lo mismo si lo hiciste en 30 min o en 3 horas, porque el
cliente paga por el **resultado** (un archivo que puede reutilizar).

- Pieza simple: $18.000
- Pieza con plano técnico: $25.000
- Transferencia de archivos nativos: $12.000

> Si el cliente va a producir en serie con tus archivos, eso es un activo.
> No lo regales cobrando "media hora".

---

### 2. Impresión — material + energía + tamaño
El costo del filamento es bajo (~$1.000 por pieza mediana). Tu **margen real**
está en la **tarifa por tamaño**:

- Pequeña (< 50 g): $3.000
- Mediana (50–150 g): $5.000
- Grande (> 150 g): $8.000

Ingresa cuántas piezas distintas hay; cada una puede tener material, gramaje,
tiempo y cantidad propios.

---

### 3. Post-procesado y despacho
- Trabajo manual (lijado, ensamblaje): $5.000/hora.
- Despacho: $4.000 fijo.

---

### 4. Reporte técnico
Al calcular, descarga un **.txt** limpio para enviar al cliente. Un solo
documento, precio por ítem, sin desglose de horas que invite a negociar.

---

### 5. Registro contable (a futuro)
El botón verde dejará todo listo para la **Operación Renta** y la contabilidad
de la SpA cuando formalicemos. Por ahora está pre-hecho, sin función activa.

---

### Formato de tiempo
Siempre `HHhMMm`. Ejemplos: `01h35m`, `00h45m`, `02h00m`.
"""
    )
