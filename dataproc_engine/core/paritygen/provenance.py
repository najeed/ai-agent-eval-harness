import datetime
import json


def provenance_metadata(license_info: str, synthetic: bool = True, note: str = "") -> str:
    """
    Step 5: Document Generation Framework & Compliance.
    Does NOT record restricted source paths to maintain user privacy and legal harbor.
    """
    meta = {
        "license_info": license_info,
        "generation_method": "statistical_sampling",
        "provenance_statement": "This dataset consists of statistical samples generated from user-supplied parameters. It contains no raw records.",  # noqa: E501
        "compliance_disclaimer": "User is responsible for ensuring compliance with any source dataset license.",  # noqa: E501
        "note": note,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "parity_framework": "v2.0 High-Signal Statistical Simulator",
    }
    return json.dumps(meta, indent=2)
