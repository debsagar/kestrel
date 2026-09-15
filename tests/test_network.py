from kestrel import network as net

def test_products_and_bom():
    assert set(net.PRODUCTS) == {"EB-STD", "EB-PRO", "SPK-1"}
    assert net.PRODUCTS["SPK-1"].bom == {"BAT": 2, "SOC": 1, "DRV": 1, "CASE": 1, "PKG": 1}
    assert net.PRODUCTS["EB-PRO"].bom["CHG"] == 1 and net.PRODUCTS["SPK-1"].eq_units == 2

def test_price_breaks_and_moq():
    assert net.price_for("S-BAT", "BAT", 5000) == 1.80
    assert net.price_for("S-BAT", "BAT", 25000) == 1.65
    assert net.price_for("S-SOC", "SOC", 30000) == 5.60
    assert net.SUPPLIERS["S-DRV"].moq["DRV"] == 10000
    assert net.SUPPLIERS["S-BRK"].qualified is False and net.SUPPLIERS["S-BRK"].deposit_pct == 1.0

def test_component_cost():
    assert round(net.component_cost("EB-STD"), 2) == 14.05   # 1.80+6.50+2*0.90+1.40+2.20+0.35
    assert round(net.component_cost("SPK-1"), 2) == 12.75    # 2*1.80+6.50+0.90+1.40+0.35

def test_customers_sum_to_one():
    assert abs(sum(c.share for c in net.CUSTOMERS.values()) - 1.0) < 1e-9
    assert net.CUSTOMERS["C-WEB"].backorder_days is None and net.CUSTOMERS["C-BIGBOX"].order_weekday == 0

def test_legs_and_packing():
    assert net.LEGS[("PLANT", "DC-NL", "ocean_suez")]["mean"] == 30
    assert net.LEGS[("DC-NL", "DC-PL", "rail")]["mean"] == 3
    assert net.pallets("EB-STD", 800) == 2 and net.pallets("SPK-1", 61) == 2
    assert net.containers({"EB-STD": 8000, "SPK-1": 2500}) == 2
