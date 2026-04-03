import click
import asyncio
import sys
import os
from dotenv import load_dotenv

# Load .env variables at start
load_dotenv()

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
    import datetime
    
    if not os.path.exists(output_file):
        return
        
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
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
@click.option("--industry", default="finance", help="The industrial sector to process (e.g., finance, healthcare, agriculture).")
@click.option("--limit", default=10, help="Limit the number of records to generate/transform.")
@click.option("--format", default="jsonl", type=click.Choice(["jsonl", "csv"]), help="Target output format (JSON Lines or CSV).")
@click.option("--target-dir", default="output", help="Directory for the generated high-signal datasets.")
@click.option("--output-name", help="Override the default industry-specific filename.")
@click.option("--source", type=click.Choice(["api", "file"]), default="api", help="Data acquisition source (Live API or Local/Remote Files).")
@click.option("--input-uri", help="Path to file/folder or URL for 'file' source ingestion.")
@click.option("--llm-provider", help="Cloud LLM provider identifier (gemini, openai, anthropic).")
@click.option("--llm-strategy", type=click.Choice(["auto", "cloud", "ollama", "heuristic", "mock"]), default="auto", help="Execution strategy for transformation (auto, cloud, ollama, heuristic, mock).")
@click.option("--model", help="Specific model identifier for the selected LLM provider (e.g., gemini-1.5-pro).")
@click.option("--ciks", help="Comma-separated list of CIK identifiers (Finance industry only).")
@click.option("--taxonomy", default="us-gaap", help="Financial reporting taxonomy (us-gaap, ifrs).")
@click.option("--currency", default="USD", help="Reporting currency unit (USD, EUR, etc.).")
@click.option("--series-id", help="EIA Series ID (Energy only).")
@click.option("--overwrite", is_flag=True, help="Force overwrite of existing output files without confirmation.")
@click.option("--max-backups", default=int(os.environ.get("DATAPROC_MAX_BACKUPS", 5)), help="Maximum number of rolling rotational backups to maintain.")
@click.option("--allow-simulation", is_flag=True, default=True, help="Mandatory V2.0 fallback: allows high-fidelity simulation if data acquisition fails.")
@click.option("--schema-type", help="Industry-specific schema variant (e.g., standard, global_population).")
def extract(industry, limit, format, target_dir, output_name, source, input_uri, llm_provider, llm_strategy, model, ciks, taxonomy, currency, series_id, overwrite, max_backups, allow_simulation, schema_type):
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
        "series_id": series_id,
        "allow_simulation": allow_simulation,
        "schema_type": schema_type
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
            elif industry == "demographics":
                from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
                provider = DemographicsProvider(config, llm_manager=llm_manager)
            elif industry == "labor":
                from dataproc_engine.providers.public_sector.labor import LaborProvider
                provider = LaborProvider(config, llm_manager=llm_manager)
            elif industry == "environment":
                from dataproc_engine.providers.public_sector.environment import EnvironmentProvider
                provider = EnvironmentProvider(config, llm_manager=llm_manager)
            elif industry == "housing":
                from dataproc_engine.providers.public_sector.housing import HousingProvider
                provider = HousingProvider(config, llm_manager=llm_manager)
            elif industry == "manufacturing":
                from dataproc_engine.providers.manufacturing import ManufacturingProvider
                provider = ManufacturingProvider(config, llm_manager=llm_manager)
            elif industry == "media_and_entertainment":
                from dataproc_engine.providers.media_and_entertainment import MediaProvider
                provider = MediaProvider(config, llm_manager=llm_manager)
            elif industry == "decision_support":
                from dataproc_engine.providers.decision_support import DecisionSupportProvider
                provider = DecisionSupportProvider(config, llm_manager=llm_manager)
            elif industry == "education":
                from dataproc_engine.providers.education import EducationProvider
                provider = EducationProvider(config, llm_manager=llm_manager)
            else:
                click.echo(f"Error: API Source for '{industry}' not supported.")
                sys.exit(1)
            engine.register_provider(industry, provider)
        else:
            from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
            provider = UnstructuredProvider(config, llm_manager=llm_manager)
            engine.register_provider(industry, provider)

        # Run the unified async pipeline
        results = asyncio.run(engine.run_industry_pipeline(industry, target_dir=target_dir))
        
        if results:
            # Dynamic default: If target_dir is 'output', relocate to industries/{industry}/datasets
            effective_target_dir = target_dir
            if target_dir == "output":
                effective_target_dir = os.path.join("industries", industry, "datasets")
            
            os.makedirs(effective_target_dir, exist_ok=True)
            
            # Dynamic filename: Match documentation parity (kb.jsonl or records.csv)
            if format == "jsonl":
                default_name = f"{industry}_kb.jsonl"
            else:
                default_name = f"{industry}_records.csv"
                
            output_file = os.path.join(effective_target_dir, output_name or default_name)
            
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


