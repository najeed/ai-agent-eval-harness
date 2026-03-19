import re
from typing import List, Set

def extract_numbers(text: str) -> List[float]:
    """
    Extracts all numbers (integers and floats) from a string.
    Handles commas as thousands separators and periods as decimal points.
    """
    if not text:
        return []
    # Remove commas used as thousands separators
    clean_text = text.replace(",", "")
    # Find all matches for numbers: 1.23, 123, -1.23, etc.
    pattern = r"[-+]?\d*\.\d+|\d+"
    matches = re.findall(pattern, clean_text)
    return [float(m) for m in matches]

def compare_numerics(expected: float, actual: float, tolerance: float = 0.01) -> bool:
    """Checks if two numbers are within a specified tolerance."""
    return abs(expected - actual) <= tolerance

def calculate_jaccard(text1: str, text2: str) -> float:
    """Calculates Jaccard similarity between two strings based on token sets."""
    def get_tokens(text):
        return set(str(text).lower().split())

    set_a = get_tokens(text1)
    set_b = get_tokens(text2)
    
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    
    return intersection / union if union > 0 else 0.0
