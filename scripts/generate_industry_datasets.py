"""
generate_industry_datasets.py

Utility to generate realistic, synthetic CSV datasets for all 44 supported industries in the harness.
"""

import os
import csv
import random
import uuid
from pathlib import Path
from datetime import datetime, timedelta

INDUSTRIES_DIR = Path("industries")

# Mock data pools for realistic generation
NAMES = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace", "Hank", "Ivy", "Jack", "Karen", "Leo"]
LOCATIONS = ["New York", "London", "Tokyo", "Berlin", "Sydney", "Toronto", "Singapore", "Dubai"]
STATUSES = ["Active", "Pending", "Resolved", "Closed", "In Progress", "Failed", "Requires Action"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]

def get_random_date(start_days_ago=365):
    """Generates a random date in ISO format."""
    now = datetime.utcnow()
    delta = timedelta(days=random.randint(0, start_days_ago), hours=random.randint(0, 23))
    return (now - delta).isoformat() + "Z"

def generate_telecom_dataset(num_rows=100) -> list:
    """Telecom: Network Incidents & Customer Tickets."""
    data = []
    for _ in range(num_rows):
        data.append({
            "ticket_id": f"TKT-{random.randint(1000, 9999)}",
            "customer_name": random.choice(NAMES),
            "issue_type": random.choice(["Billing", "Outage", "Hardware", "Plan Upgrade", "Connectivity"]),
            "status": random.choice(STATUSES),
            "priority": random.choice(PRIORITIES),
            "region": random.choice(LOCATIONS),
            "created_at": get_random_date()
        })
    return data

def generate_healthcare_dataset(num_rows=100) -> list:
    """Healthcare: Patient Appointments & Triage."""
    data = []
    for _ in range(num_rows):
        data.append({
            "patient_id": f"PAT-{uuid.uuid4().hex[:6].upper()}",
            "department": random.choice(["Cardiology", "Neurology", "Pediatrics", "Oncology", "General"]),
            "appointment_type": random.choice(["Routine", "Follow-up", "Urgent", "Surgical Consult"]),
            "status": random.choice(["Scheduled", "Completed", "No-show", "Cancelled"]),
            "insurance_cleared": random.choice(["Yes", "No", "Pending"]),
            "date": get_random_date(30)
        })
    return data

def generate_ecommerce_dataset(num_rows=100) -> list:
    """Ecommerce: Inventory & Orders."""
    data = []
    for _ in range(num_rows):
        data.append({
            "order_id": f"ORD-{random.randint(10000, 99999)}",
            "customer_uuid": str(uuid.uuid4()),
            "item_category": random.choice(["Electronics", "Apparel", "Home Goods", "Books"]),
            "total_value_usd": round(random.uniform(10.0, 1500.0), 2),
            "fulfillment_status": random.choice(["Shipped", "Processing", "Backordered", "Delivered", "Returned"]),
            "shipping_region": random.choice(LOCATIONS),
            "order_date": get_random_date(180)
        })
    return data

def generate_generic_dataset(industry_name: str, num_rows=100) -> list:
    """Fallback generator for other industries."""
    data = []
    for _ in range(num_rows):
        data.append({
            "record_id": f"{industry_name[:3].upper()}-{random.randint(1000, 9999)}",
            "entity_name": random.choice(NAMES) + " Corp",
            "status": random.choice(STATUSES),
            "priority": random.choice(PRIORITIES),
            "assigned_region": random.choice(LOCATIONS),
            "last_updated": get_random_date()
        })
    return data

def save_to_csv(data: list, filepath: Path):
    """Writes a list of dictionaries to a CSV file."""
    if not data:
        return
        
    os.makedirs(filepath.parent, exist_ok=True)
    keys = data[0].keys()
    
    with open(filepath, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)

def main():
    print("Generating synthetic datasets for all industries...")
    
    if not INDUSTRIES_DIR.exists():
        print(f"Error: {INDUSTRIES_DIR} not found. Run from project root.")
        return
        
    count = 0
    for industry_dir in [d for d in INDUSTRIES_DIR.iterdir() if d.is_dir()]:
        industry_name = industry_dir.name
        datasets_dir = industry_dir / "datasets"
        
        # Determine the dataset generator
        if industry_name == "telecom":
            data = generate_telecom_dataset()
            filename = "support_tickets.csv"
        elif industry_name == "healthcare":
            data = generate_healthcare_dataset()
            filename = "appointments.csv"
        elif industry_name == "ecommerce":
            data = generate_ecommerce_dataset()
            filename = "orders.csv"
        else:
            data = generate_generic_dataset(industry_name)
            filename = f"{industry_name}_records.csv"
            
        csv_path = datasets_dir / filename
        save_to_csv(data, csv_path)
        count += 1
        print(f"  [+] Created {csv_path}")

    print(f"\nSuccessfully generated synthetic datasets for {count} industries.")

if __name__ == "__main__":
    main()
