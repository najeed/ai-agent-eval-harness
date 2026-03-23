import os
import json
import argparse
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.paritygen.provenance import provenance_metadata

def generate_olist_parity(count: int, output_path: str):
    """
    Dedicated generator for Olist E-Commerce parity data.
    Enforces CC BY-NC-SA 4.0 compliance and includes legally defensible provenance.
    """
    print("--- ⚖️ Compliance Wrapper ---")
    print("Source Principle: CC BY-NC-SA 4.0 (Non-Commercial, Share-Alike)")
    print("Benchmark: E-Commerce Transaction Parity")
    print("Disclaimer: Users must not use these statistical samples for commercial competition.")
    print("----------------------------------")
    
    engine = ParitySynthesizer()
    records = engine.generate_statistical_twin("ecommerce_transaction_parity", count=count)
    
    # Inject e-commerce provenance metadata
    provenance = provenance_metadata(
        license_info="CC BY-NC-SA 4.0 (E-Commerce Attribution Required)",
        synthetic=True,
        note="Validated for first and second moment parity with e-commerce public benchmarks. "
             "Outputs from NC-SA sources may inherit non-commercial restrictions."
    )
    
    with open(output_path, 'w') as f:
        for record in records:
            record["_provenance_audit"] = json.loads(provenance)
            f.write(json.dumps(record) + "\n")
            
    print(f"✅ Generated {count} E-Commerce-parity records to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Olist Parity Generator")
    parser.add_argument("--count", type=int, default=1000, help="Number of records to generate")
    parser.add_argument("--output", type=str, default="olist_synthetic.jsonl", help="Output file path")
    args = parser.parse_args()
    
    generate_olist_parity(args.count, args.output)
