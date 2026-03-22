import csv
import random
from datetime import datetime, timedelta

def generate_ag_data():
    path = "industries/agriculture/datasets/commodity_prices.csv"
    commodities = ["CORN", "WHEAT", "SOYBEANS", "COTTON", "OATS"]
    states = ["IA", "IL", "KS", "MN", "ND", "NE", "TX", "SD"]
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["commodity_desc", "year", "Value", "unit_desc", "state_alpha"])
        for _ in range(100):
            writer.writerow([
                random.choice(commodities),
                random.randint(2020, 2023),
                round(random.uniform(30.0, 200.0), 1),
                "BU / ACRE",
                random.choice(states)
            ])
    print(f"Generated 100 Ag records at {path}")

def generate_transp_data():
    path = "industries/logistics/datasets/airline_performance.csv"
    carriers = ["Delta", "United", "American", "Southwest", "JetBlue", "Alaska", "Spirit", "Frontier"]
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["carrier", "on_time_pct", "canceled_pct", "period"])
        for year in [2023, 2024]:
            for month in range(1, 13):
                period = f"{year}-{month:02d}"
                for carrier in carriers:
                    writer.writerow([
                        carrier,
                        round(random.uniform(65.0, 92.0), 1),
                        round(random.uniform(0.5, 8.0), 1),
                        period
                    ])
    print(f"Generated {len(carriers) * 24} Transp records at {path}")

if __name__ == "__main__":
    generate_ag_data()
    generate_transp_data()
