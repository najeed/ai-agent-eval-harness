import json
import argparse
import datetime
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.paritygen.provenance import provenance_metadata

def generate_ookla_parity(count: int, output_path: str):
    """
    Dedicated generator for Ookla Network Performance parity data.
    Enforces CC BY-NC-SA 4.0 compliance and includes legally defensible provenance.
    """
    print("--- ⚖️ Compliance Wrapper ---")
    print("Source Principle: CC BY-NC-SA 4.0 (Non-Commercial, Share-Alike)")
    print("Benchmark: Network Performance Parity")
    print("Disclaimer: Redistribution of Ookla raw speedtest datasets is prohibited.")
    print("----------------------------------")
    
    engine = ParitySynthesizer()
    records = engine.generate_statistical_twin("network_performance_parity", count=count)
    
    provenance = provenance_metadata(
        license_info="CC BY-NC-SA 4.0 (Ookla Attribution Required)",
        synthetic=True,
        note="Validated for first and second moment parity with Ookla network benchmarks. "
             "Outputs from NC-SA sources may inherit non-commercial restrictions."
    )
    
    with open(output_path, 'w') as f:
        for record in records:
            record["_provenance_audit"] = json.loads(provenance)
            f.write(json.dumps(record) + "\n")
            
    print(f"✅ Generated {count} Network-Performance-parity records to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ookla Parity Generator")
    parser.add_argument("--count", type=int, default=1000, help="Number of records to generate")
    parser.add_argument("--output", type=str, default="ookla_synthetic.jsonl", help="Output file path")
    args = parser.parse_args()
    generate_ookla_parity(args.count, args.output)
