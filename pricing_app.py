import streamlit as st
import re
import pandas as pd

# ======================================================
# CONFIGURATION & CONSTANTS
# ======================================================

# Material prices (CLP per gram)
material_prices = {
    "PLA": 20,
    "ABS": 13,
    "PETG": 16,
    "TPU": 15
}

# Printer & energy
printer_power_kWh = 0.13        # kW
electricity_price = 200         # CLP per kWh

# Service rates
DESIGN_RATE = 7000              # CLP / hour
HANDWORK_RATE = 3000            # CLP / hour
SIZE_FEES = {
    "small": 3000,
    "medium": 5000,
    "big": 8000
}

delivery_fee = 3500             # CLP

# ======================================================
# HELPER FUNCTIONS
# ======================================================

def parse_time(time_str):
    """
    Converts 'HHhMMm' string to hours as float.
    Example: '02h30m' -> 2.5
    """
    match = re.match(r"(\d+)h(\d+)m", time_str.strip())
    if not match:
        return 0.0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return hours + minutes / 60.0


def calculate_price(
    material,
    grams,
    printing_time_hours,
    hand_work_hours=0,
    design_hours=0,
    service_type="print_only",
    size="small",
    delivery=False
):
    # ----------------------------
    # Base printing cost
    material_cost = grams * material_prices[material]
    electricity_cost = printing_time_hours * printer_power_kWh * electricity_price
    base_print_cost = material_cost + electricity_cost

    # Profit & machine wear factor
    printing_cost = 2 * base_print_cost

    # Other costs
    hand_work_cost = hand_work_hours * HANDWORK_RATE
    design_cost = design_hours * DESIGN_RATE
    delivery_cost = delivery_fee if delivery else 0

    # ----------------------------
    # Service logic
    if service_type == "design":
        total_price = design_cost

    elif service_type == "print_only":
        size_fee = SIZE_FEES.get(size, SIZE_FEES["small"])
        total_price = printing_cost + hand_work_cost + size_fee

    elif service_type == "design_and_print":
        total_price = design_cost + printing_cost + hand_work_cost

    else:
        total_price = 0

    total_price += delivery_cost
    return round(total_price, 0), delivery_cost


# ======================================================
# STREAMLIT UI
# ======================================================

st.set_page_config(page_title="3D Printing Pricing Calculator", page_icon="🖨️")

st.title("🖨️ 3D Printing Pricing Calculator")

client_name = st.text_input("Client Name")

service = st.selectbox(
    "Service Type",
    ["design", "print_only", "design_and_print"],
    format_func=lambda x: {
        "design": "Design only",
        "print_only": "Print only",
        "design_and_print": "Design and Print"
    }[x]
)

design_time = st.text_input("Design Time (00h00m)", "00h00m")
printing_time = st.text_input("Printing Time (00h00m)", "00h00m")
hand_work_time = st.text_input("Post-processing / Hand Work Time (00h00m)", "00h00m")

material = st.selectbox("Material", list(material_prices.keys()))
grams = st.number_input("Material Used (grams)", min_value=0.0, step=1.0)

delivery_needed = st.checkbox("Delivery Required?")

size = "small"
if service == "print_only":
    size = st.selectbox("Print Size", ["small", "medium", "big"])

# ======================================================
# CALCULATION
# ======================================================

if st.button("Calculate Price"):
    total, delivery_cost = calculate_price(
        material=material,
        grams=grams,
        printing_time_hours=parse_time(printing_time),
        hand_work_hours=parse_time(hand_work_time),
        design_hours=parse_time(design_time),
        service_type=service,
        size=size,
        delivery=delivery_needed
    )

    st.success(f"💰 Final Price for {client_name or 'Client'}: {int(total):,} CLP")

    # ----------------------------
    # Export order as CSV
    order_data = {
        "Client": [client_name],
        "Service": [service],
        "Design Hours": [parse_time(design_time)],
        "Printing Hours": [parse_time(printing_time)],
        "Hand Work Hours": [parse_time(hand_work_time)],
        "Material": [material],
        "Grams Used": [grams],
        "Delivery (CLP)": [delivery_cost],
        "Total Price (CLP)": [total]
    }

    df = pd.DataFrame(order_data)

    st.download_button(
        label="📥 Download Order (CSV)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"{client_name or 'order'}_3d_printing_quote.csv",
        mime="text/csv",
    )



