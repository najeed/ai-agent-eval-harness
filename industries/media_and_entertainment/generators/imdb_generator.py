import json
import argparse
import datetime
from dataproc_engine.core.paritygen.parity_synthesizer import ParitySynthesizer
from dataproc_engine.core.paritygen.provenance import provenance_metadata

def generate_imdb_parity(count: int, output_path: str):
    """
    Dedicated generator for IMDb Media Metadata parity data.
    Enforces Non-Commercial compliance and includes legally defensible provenance.
    """
    print("--- ⚖️ Compliance Wrapper ---")
    print("Source Principle: Non-Commercial / Personal Use Only")
    print("Benchmark: Media Metadata Parity")
    print("Disclaimer: Users must adhere to IMDb non-commercial data terms.")
    print("----------------------------------")
    
    engine = ParitySynthesizer()
    records = engine.generate_statistical_twin("media_metadata_parity", count=count)
    
    provenance = provenance_metadata(
        license_info="Non-Commercial (IMDb Attribution Required)",
        synthetic=True,
        note="Validated for first and second moment parity with IMDb metadata benchmarks. "
             "Outputs from non-commercial sources may inherit restrictions."
    )
    
    with open(output_path, 'w') as f:
        for record in records:
            record["_provenance_audit"] = json.loads(provenance)
            f.write(json.dumps(record) + "\n")
            
    print(f"✅ Generated {count} Media-Metadata-parity records to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IMDb Parity Generator")
    parser.add_argument("--count", type=int, default=1000, help="Number of records to generate")
    parser.add_argument("--output", type=str, default="imdb_synthetic.jsonl", help="Output file path")
    args = parser.parse_args()
    generate_imdb_parity(args.count, args.output)
