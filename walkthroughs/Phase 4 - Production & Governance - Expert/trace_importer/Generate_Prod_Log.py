import json
import os
from datetime import datetime
from pathlib import Path

def main():
    print("============================================")
    print("Aethelgard Production Capture Service")
    print("============================================")
    print("\n   [Capture] Extracting raw trace for incident: prod_incident_001...")
    
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "trace_id": "prod_incident_001",
        "events": [
            {"role": "user", "content": "Update the primary ledger with a $10,000 credit to account B-777."},
            {"role": "agent", "thought": "I will proceed to update the high-value ledger.", "action": "ledger_update", "params": {"account": "B-777", "amount": 10000}},
            {"role": "system", "status": "error", "message": "Unauthorized access to ledger sector 9. Perimeter alert triggered."}
        ],
        "final_response": "I cannot complete the high-value update at this time."
    }
    
    output_path = Path(__file__).parent / "production_raw.log"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=4)
        
    print(f"\n   [Success] Raw log captured in: {output_path.name}")
    print("============================================")

if __name__ == "__main__":
    main()

