import hashlib
import json
import asyncio
import aiohttp
import datetime
from typing import List, Dict, Any, Optional
from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger

logger = StructuredLogger("MediaProvider")

class MediaProvider(BaseProvider):
    """
    Provider for Media & Entertainment data (IMDb & Spotify symbols).
    """
    def __init__(self, config: Dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.media_mode = config.get("media_mode", "imdb") # imdb, spotify
        self.api_key = config.get("spotify_api_client_id")

    async def extract(self) -> List[RawArtifact]:
        if self.media_mode == "imdb":
            # Gold Standard: IMDb Datasets (Subset)
            # URI: https://datasets.imdbws.com/
            url = "https://datasets.imdbws.com/"
            
            if self.allow_simulation:
                sim_imdb = [
                    {"tconst": "tt0111161", "primaryTitle": "The Shawshank Redemption", "averageRating": 9.3, "numVotes": 2800000},
                    {"tconst": "tt0068646", "primaryTitle": "The Godfather", "averageRating": 9.2, "numVotes": 1900000}
                ]
                return [self.create_simulated_artifact(
                    id="IMDB-RATINGS",
                    content=sim_imdb,
                    source_url=url,
                    metadata={"dataset": "title.ratings"}
                )]
            return []

        # Spotify Web API (Top Tracks / Trends)
        # URI: https://api.spotify.com/v1/browse/new-releases
        url = "https://api.spotify.com/v1/browse/new-releases"
        
        if self.allow_simulation:
            sim_spotify = [
                {"name": "Flowers", "artist": "Miley Cyrus", "popularity": 98, "release_date": "2023-01-13"},
                {"name": "Kill Bill", "artist": "SZA", "popularity": 95, "release_date": "2022-12-09"}
            ]
            return [self.create_simulated_artifact(
                id="SPOTIFY-TRENDS",
                content=sim_spotify,
                source_url=url,
                metadata={"dataset": "new-releases"}
            )]
        return []

    async def transform(self, raw_artifacts: List[RawArtifact]) -> List[StandardSchema]:
        results = []
        
        if self.media_mode == "imdb":
            TARGET_SCHEMA = {"title": "string", "rating": "number", "votes": "integer"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "title": row.get("primaryTitle"),
                        "rating": float(row.get("averageRating", 0)),
                        "votes": int(row.get("numVotes", 0))
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = hashlib.md5(f"IMDB-{row['tconst']}".encode()).hexdigest()[:16]
                        results.append(StandardSchema(
                            id=record_id,
                            industry="media_and_entertainment",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "IMDb"},
                            checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                        ))
            return results

        # Spotify Transformation
        TARGET_SCHEMA = {"track_name": "string", "artist": "string", "popularity_score": "integer"}
        for raw in raw_artifacts:
            for row in raw.content:
                raw_data = {
                    "track_name": row.get("name"),
                    "artist": row.get("artist"),
                    "popularity_score": int(row.get("popularity", 0))
                }
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = hashlib.md5(f"SPOTIFY-{raw_data['track_name']}-{raw_data['artist']}".encode()).hexdigest()[:16]
                    results.append(StandardSchema(
                        id=record_id,
                        industry="media_and_entertainment",
                        data=verified,
                        provenance={"source": raw.source_url, "provider": "Spotify"},
                        checksum=hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()
                    ))
        return results

    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        return all(r.data.get("rating", 0) >= 0 and r.data.get("popularity_score", 0) >= 0 for r in [
            r for r in normalized_data if "rating" in r.data or "popularity_score" in r.data
        ])
