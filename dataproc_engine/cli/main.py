import click
import asyncio
import sys
import os

# Ensure the parent directory is in the path so we can import dataproc_engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.providers.finance import FinanceProvider

@click.group()
def cli():
    """dataproc-cli: High-Signal Industry Dataset Utility"""
    pass

@cli.command()
@click.option("--industry", default="finance", help="The industry to process.")
@click.option("--limit", default=10, help="Limit the number of records.")
@click.option("--format", default="jsonl", type=click.Choice(["jsonl", "csv"]), help="Output format.")
@click.option("--target-dir", default="output", help="Directory to save output.")
def extract(industry, limit, format, target_dir):
    """Run the extraction and transformation pipeline."""
    click.echo(f"Initializing dataproc pipeline for industry: {industry}")
    
    config = {"limit": limit}
    engine = DatasetEngine()
    
    if industry == "finance":
        provider = FinanceProvider(config)
        engine.register_provider("finance", provider)
    else:
        click.echo(f"Error: Industry '{industry}' not supported.")
        return

    results = asyncio.run(engine.run_industry_pipeline(industry))
    
    if results:
        os.makedirs(target_dir, exist_ok=True)
        output_file = os.path.join(target_dir, f"{industry}_records.{format}")
        
        import json
        import pandas as pd
        from dataclasses import asdict
        
        extracted_data = [asdict(r)["data"] for r in results]
        df = pd.DataFrame(extracted_data)
        
        if format == "jsonl":
            df.to_json(output_file, orient="records", lines=True)
        else:
            df.to_csv(output_file, index=False)
        
        click.echo(f"Pipeline completed successfully. {len(results)} records generated.")
        click.echo(f"High-signal dataset saved to: {output_file}")
    else:
        click.echo("Pipeline failed or produced no results.")

if __name__ == "__main__":
    cli()
