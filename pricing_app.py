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
    # --- Rates ---
    DESIGN_RATE = 7000          # CLP / hour
    HANDWORK_RATE = 3000        # CLP / hour
    SIZE_FEES = {"small": 3000, "medium": 5000, "big": 8000}

    # --- Base costs ---
    material_cost = grams * material_prices[material]
    electricity_cost = printing_time_hours * printer_power_kWh * electricity_price
    base_print_cost = material_cost + electricity_cost

    # Apply profit & machine wear
    printing_cost = 2 * base_print_cost

    hand_work_cost = hand_work_hours * HANDWORK_RATE
    design_cost = design_hours * DESIGN_RATE
    delivery_cost = delivery_fee if delivery else 0

    # --- Service logic ---
    if service_type == "design":
        total_price = design_cost

    elif service_type == "print_only":
        size_fee = SIZE_FEES.get(size, 3000)
        total_price = printing_cost + hand_work_cost + size_fee

    elif service_type == "design_and_print":
        total_price = design_cost + printing_cost + hand_work_cost

    else:
        total_price = 0

    total_price += delivery_cost
    return round(total_price, 0), delivery_cost

