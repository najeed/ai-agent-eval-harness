import argparse
import pandas as pd
import sys
import os
import json

# Ensure parent directory is in path for relative imports if run as script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from dataproc_engine.core.paritygen.profiling import profile_data
from dataproc_engine.core.paritygen.modeling import fit_multivariate_model
from dataproc_engine.core.paritygen.sampling import generate_synthetic
from dataproc_engine.core.paritygen.validation import validate_parity
from dataproc_engine.core.paritygen.provenance import provenance_metadata

def main():
    parser = argparse.ArgumentParser(description="V2.0 Parity Synthetic Generator CLI")
    parser.add_argument("--input", required=True, help="Path to original dataset (CSV)")
    parser.add_argument("--output", required=True, help="Path to synthetic dataset (CSV)")
    parser.add_argument("--license", default="Restricted", help="License of the source dataset")
    parser.add_argument("--n-samples", type=int, default=1000, help="Number of records to generate")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    print(f"Initializing Parity Generator for: {args.input}")
    df = pd.read_csv(args.input)
    
    # 1. Profiling
    print("Profiling data...")
    profile = profile_data(df)
    
    # 2. Modeling
    print("Fitting multivariate model (Mean, Variance, Correlation)...")
    model = fit_multivariate_model(df)
    
    # 3. Sampling
    print(f"Sampling {args.n_samples} records...")
    synthetic_df = generate_synthetic(model, n_samples=args.n_samples)
    
    # 4. Validation
    print("Performing Parity Audit (KS-Test)...")
    validation = validate_parity(df, synthetic_df)
    
    # 5. Output and Provenance
    print(f"Saving statistical samples to: {args.output}")
    synthetic_df.to_csv(args.output, index=False)
    
    meta = provenance_metadata(args.license)
    provenance_file = args.output + ".metadata.json"
    with open(provenance_file, "w") as f:
        f.write(meta)
    
    print("\nParity Synthesis Complete.")
    print(f"Validation Report: {json.dumps(validation, indent=2)}")
    print(f"Provenance Meta saved to: {provenance_file}")

if __name__ == "__main__":
    main()
