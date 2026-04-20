"""
path_resolver.py

Industrial JSONPath-lite utility for resolving nested property paths
in mixed dictionary/list structures. Supports dot notation and bracket indexing.
"""

import re
from typing import Any


class PathResolver:
    """
    Authoritative state resolution engine.
    Supports:
        - Dot notation: root.property.subproperty
        - Bracket indexing: root['property'][0].field
        - Mixed access: data.tables['users'][0].email
    """

    @staticmethod
    def resolve(data: Any, path: str) -> Any:
        """
        Resolves a property path from the provided data structure.
        Returns None if any part of the path is unreachable.
        """
        if not path or data is None:
            return data

        # Tokenize the path into parts (properties or indices)
        # Regex explanation:
        # \.(\w+)             -> Matches .property
        # \[['"]?([^'"]+)['"]?\] -> Matches ['key'], ["key"], or [0]
        # ^(\w+)              -> Matches the initial property if it doesn't start with [

        # Normalized start: ensure root property is treatable like a dot-match
        current = data

        # We use a state-machine or a simpler iterative approach to handle the mixed string
        # To handle complex mixed cases like data.tables['users'][0].email
        # we first normalize the path to a stream of tokens.

        tokens = PathResolver._tokenize(path)

        for token in tokens:
            try:
                if isinstance(current, dict):
                    # Check if token is a key
                    current = current.get(token)
                elif isinstance(current, list):
                    # Try to treat token as an integer index
                    try:
                        idx = int(token)
                        if 0 <= idx < len(current):
                            current = current[idx]
                        else:
                            return None
                    except ValueError:
                        # List cannot be indexed by a string key
                        return None
                else:
                    # Leaf node reached but path continues
                    return None

                if current is None:
                    return None
            except Exception:
                return None

        return current

    @staticmethod
    def _tokenize(path: str) -> list[str]:
        """
        Parses the path string into a list of normalized property/index tokens.
        Example: "tables['users'][0].email" -> ["tables", "users", "0", "email"]
        """
        tokens = []
        # Pattern to extract segments:
        # Match dot-notation segments or bracket-notation segments
        # Segment 1: (\w+)  (initial or after dot)
        # Segment 2: \.(\w+)
        # Segment 3: \[['"]?([^'"]+?)['"]?\]

        pattern = re.compile(r"(\w+)|\[['\"]?([^'\"\]]+?)['\"]?\]")
        matches = pattern.finditer(path)

        for match in matches:
            # Group 1 is for dot-property, Group 2 is for bracket-index
            val = match.group(1) or match.group(2)
            if val is not None:
                tokens.append(val)

        return tokens
