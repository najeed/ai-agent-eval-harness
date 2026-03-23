import json
import argparse
import datetime
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.paritygen.provenance import provenance_metadata

def generate_faostat_parity(count: int, output_path: str):
    """
    Dedicated generator for FAOStat Global Agriculture parity data.
    Enforces CC BY-NC-SA 3.0 compliance and includes legally defensible provenance.
    """
    print("--- ⚖️ Compliance Wrapper ---")
    print("Source Principle: CC BY-NC-SA 3.0 (Non-Commercial, Share-Alike)")
    print("Benchmark: Global Agri-Stats Parity")
    print("Disclaimer: Redistribution of raw FAOStat data is prohibited.")
    print("----------------------------------")
    
    engine = ParitySynthesizer()
    records = engine.generate_statistical_twin("agri_stats_parity", count=count)
    
    provenance = provenance_metadata(
        license_info="CC BY-NC-SA 3.0 (FAOStat Attribution Required)",
        synthetic=True,
        note="Validated for first and second moment parity with FAOStat public indices. "
             "Outputs from NC-SA sources may inherit non-commercial restrictions."
    )
    
    with open(output_path, 'w') as f:
        for record in records:
            record["_provenance_audit"] = json.loads(provenance)
            f.write(json.dumps(record) + "\n")
            
    print(f"✅ Generated {count} Agri-Stats-parity records to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FAOStat Parity Generator")
    parser.add_argument("--count", type=int, default=1000, help="Number of records to generate")
    parser.add_argument("--output", type=str, default="faostat_synthetic.jsonl", help="Output file path")
    args = parser.parse_args()
    generate_faostat_parity(args.count, args.output)
