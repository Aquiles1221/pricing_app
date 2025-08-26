import streamlit as st
import re
import pandas as pd

# ----------------------------
# Material prices (CLP per gram)
material_prices = {
    "PLA": 20,
    "ABS": 13,
    "PETG": 16,
    "TPU": 15
}

printer_power_kWh = 0.13  
electricity_price = 200  
hand_work_price = 5000  
design_price = 8000  
delivery_fee = 3500  

# ----------------------------
def parse_time(time_str):
    match = re.match(r"(\d+)h(\d+)m", time_str.strip())
    if not match:
        return 0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return hours + minutes / 60.0

def calculate_price(material, grams, printing_time_hours,
                    hand_work_hours=0, design_hours=0,
                    service_type="print_only", size="small",
                    delivery=False):
    material_cost = grams * material_prices[material]
    electricity_cost = printing_time_hours * printer_power_kWh * electricity_price
    printing_cost = (material_cost + electricity_cost) * 2
    hand_work_cost = hand_work_hours * hand_work_price

    if service_type == "print_only":
        service_cost = {"small":3000,"medium":5000,"big":8000}.get(size,3000)
    elif service_type == "design":
        service_cost = design_hours * design_price
    elif service_type == "design_and_print":
        service_cost = design_hours * design_price + printing_cost
    else:
        service_cost = 0

    delivery_cost = delivery_fee if delivery else 0
    total_price = printing_cost + hand_work_cost + service_cost + delivery_cost
    return round(total_price, 0), delivery_cost

# ----------------------------
st.title("🖨️ 3D Printing Pricing Calculator")

client_name = st.text_input("Client Name")
service = st.selectbox("Service", ["print_only", "design", "design_and_print"])
design_time = st.text_input("Design Time (00h00m)", "00h00m")
printing_time = st.text_input("Printing Time (00h00m)", "00h00m")
material = st.selectbox("Material", list(material_prices.keys()))
grams = st.number_input("Grams of material used", min_value=0.0, step=1.0)
hand_work_time = st.text_input("Hand Work Time (00h00m)", "00h00m")
delivery_needed = st.checkbox("Delivery Required?")

size = "small"
if service == "print_only":
    size = st.selectbox("Print Size", ["small", "medium", "big"])

if st.button("Calculate Price"):
    total, delivery_cost = calculate_price(
        material,
        grams,
        parse_time(printing_time),
        parse_time(hand_work_time),
        parse_time(design_time),
        service_type=service,
        size=size,
        delivery=delivery_needed
    )

    st.success(f"💰 Final Price for {client_name}: {total} CLP")

    # Save to "Excel-like" file (CSV for download)
    order_data = {
        "Client": [client_name],
        "Service": [service],
        "Design Hours": [parse_time(design_time)],
        "Printing Time": [parse_time(printing_time)],
        "Material": [material],
        "Grams": [grams],
        "Hand Work Hours": [parse_time(hand_work_time)],
        "Delivery (CLP)": [delivery_cost],
        "Total Price (CLP)": [total]
    }
    df = pd.DataFrame(order_data)

    st.download_button(
        label="📥 Download Order as Excel",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"{client_name}_order.csv",
        mime="text/csv",
    )
