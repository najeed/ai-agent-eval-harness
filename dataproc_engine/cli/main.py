import click
import asyncio
import sys
import os

# Ensure the parent directory is in the path so we can import dataproc_engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.providers.finance import FinanceProvider

def run_rotational_backup(output_file: str, max_backups: int):
    """
    Archives the existing file and rotates backups to keep only the last N versions.
    """
    import os
    import glob
    from datetime import datetime
    
    if not os.path.exists(output_file):
        return
        
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    archive_name = f"{output_file}.{timestamp}.bak"
    os.rename(output_file, archive_name)
    
    # Prune old backups (Keep only max_backups)
    backups = sorted(glob.glob(f"{output_file}.*.bak"))
    if len(backups) > max_backups:
        excess = len(backups) - max_backups
        for i in range(excess):
            try:
                os.remove(backups[i])
            except Exception:
                pass
    return archive_name

@click.group()
def cli():
    """dataproc-cli: High-Signal Industry Dataset Utility"""
    pass

@cli.command()
@click.option("--industry", default="finance", help="The industry to process.")
@click.option("--limit", default=10, help="Limit the number of records.")
@click.option("--format", default="jsonl", type=click.Choice(["jsonl", "csv"]), help="Output format.")
@click.option("--target-dir", default="output", help="Directory to save output.")
@click.option("--output-name", help="Optional output filename.")
@click.option("--source", type=click.Choice(["api", "file"]), default="api", help="Source type.")
@click.option("--input-uri", help="Path to file/folder or URL for 'file' source.")
@click.option("--llm-provider", help="Cloud LLM provider (gemini, openai, etc.).")
@click.option("--llm-strategy", type=click.Choice(["auto", "cloud", "ollama", "heuristic", "mock"]), default="auto")
@click.option("--model", help="Specific model name.")
@click.option("--ciks", help="Comma-separated list of CIKs (Finance only).")
@click.option("--taxonomy", default="us-gaap", help="Financial reporting taxonomy (us-gaap, ifrs).")
@click.option("--currency", default="USD", help="Reporting currency unit (USD, EUR, etc.).")
@click.option("--series-id", help="EIA Series ID (Energy only).")
@click.option("--overwrite", is_flag=True, help="Overwrite existing output file without prompting.")
@click.option("--max-backups", default=5, help="Maximum number of rolling backups to keep.")
def extract(industry, limit, format, target_dir, output_name, source, input_uri, llm_provider, llm_strategy, model, ciks, taxonomy, currency, series_id, overwrite, max_backups):
    """Run the extraction and transformation pipeline."""
    # 1. Validation: Mandatory Source for file mode
    if source == "file" and not input_uri:
        click.echo("Error: --input-uri (file path or URL) is required for 'file' source.")
        sys.exit(1)

    click.echo(f"Initializing dataproc pipeline for industry: {industry} (Source: {source})")
    
    config = {
        "limit": limit,
        "industry": industry,
        "input_uri": input_uri,
        "target_dir": target_dir,
        "llm_provider": llm_provider,
        "llm_strategy": llm_strategy,
        "model": model,
        "ciks": ciks.split(",") if ciks else None,
        "taxonomy": taxonomy,
        "currency": currency,
        "series_id": series_id
    }
    
    try:
        llm_manager = LLMManager(config)
        engine = DatasetEngine(llm_manager=llm_manager)
        
        if source == "api":
            if industry == "finance":
                provider = FinanceProvider(config, llm_manager=llm_manager)
            elif industry == "energy":
                from dataproc_engine.providers.energy import EnergyProvider
                provider = EnergyProvider(config, llm_manager=llm_manager)
            elif industry == "ecommerce":
                from dataproc_engine.providers.ecommerce import EcommerceProvider
                provider = EcommerceProvider(config, llm_manager=llm_manager)
            elif industry == "healthcare":
                from dataproc_engine.providers.healthcare import HealthcareProvider
                provider = HealthcareProvider(config, llm_manager=llm_manager)
            elif industry == "telecom":
                from dataproc_engine.providers.telecom import TelecomProvider
                provider = TelecomProvider(config, llm_manager=llm_manager)
            elif industry == "agriculture":
                from dataproc_engine.providers.agriculture import AgricultureProvider
                provider = AgricultureProvider(config, llm_manager=llm_manager)
            elif industry == "transportation":
                from dataproc_engine.providers.transportation import TransportationProvider
                provider = TransportationProvider(config, llm_manager=llm_manager)
            else:
                click.echo(f"Error: API Source for '{industry}' not supported.")
                return
            engine.register_provider(industry, provider)
        else:
            from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
            provider = UnstructuredProvider(config, llm_manager=llm_manager)
            engine.register_provider(industry, provider)

        # Run the unified async pipeline
        results = asyncio.run(engine.run_industry_pipeline(industry, target_dir=target_dir))
        
        if results:
            os.makedirs(target_dir, exist_ok=True)
            default_name = f"{industry}_records.{format}"
            output_file = os.path.join(target_dir, output_name or default_name)
            
            # 2. Conflict Handling with Rotational Backup
            if os.path.exists(output_file):
                should_archive = False
                if overwrite:
                    should_archive = True # Automatic safety backup even in CI/CD
                else:
                    if click.confirm(f"File '{output_file}' already exists. Archive the old file?", default=True):
                        should_archive = True
                    else:
                        if not click.confirm(f"Overwrite '{output_file}' without backup?", default=False):
                            click.echo("Operation cancelled by user.")
                            return

                if should_archive:
                    archive_name = run_rotational_backup(output_file, max_backups)
                    if archive_name:
                        click.echo(f"Archived existing file to: {archive_name}")
                        
                        # Show pruning info (optional hardening)
                        import glob
                        total_backups = sorted(glob.glob(f"{output_file}.*.bak"))
                        if len(total_backups) >= max_backups:
                             click.echo(f"Rotation Policy Active: Maintained {max_backups} latest versions.")

            import json
            import pandas as pd
            from dataclasses import asdict
            
            extracted_data = [r.to_dict() for r in results]
            df = pd.DataFrame(extracted_data)
            
            if format == "jsonl":
                df.to_json(output_file, orient="records", lines=True)
            else:
                df.to_csv(output_file, index=False)
            
            click.echo(f"Pipeline completed successfully. {len(results)} records generated.")
            click.echo(f"High-signal dataset saved to: {output_file}")
        else:
            click.echo("Pipeline completed but produced no results.")
            
    except Exception as e:
        click.echo(f"Error: Pipeline failed gracefully. Reason: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    cli()
