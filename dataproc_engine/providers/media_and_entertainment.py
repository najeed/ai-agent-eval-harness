import json
from typing import Any

from dataproc_engine.core.base_provider import BaseProvider, RawArtifact, StandardSchema
from dataproc_engine.core.logger import StructuredLogger
from eval_runner.utils import crypto

logger = StructuredLogger("MediaProvider")


class MediaProvider(BaseProvider):
    """
    Provider for Media & Entertainment data (IMDb & Spotify symbols).
    """

    def __init__(self, config: dict[str, Any], llm_manager: Any = None):
        super().__init__(config, llm_manager=llm_manager)
        self.media_mode = config.get("media_mode", "imdb")  # imdb, spotify
        self.api_key = config.get("spotify_api_client_id")

    async def extract(self) -> list[RawArtifact]:
        if self.media_mode == "imdb":
            # Gold Standard: IMDb Datasets (Subset)
            # URI: https://datasets.imdbws.com/
            url = "https://datasets.imdbws.com/"

            if self.allow_simulation:
                sim_imdb = [
                    {
                        "tconst": "tt0111161",
                        "primaryTitle": "The Shawshank Redemption",
                        "averageRating": 9.3,
                        "numVotes": 2800000,
                    },
                    {
                        "tconst": "tt0068646",
                        "primaryTitle": "The Godfather",
                        "averageRating": 9.2,
                        "numVotes": 1900000,
                    },
                ]
                return [
                    self.create_simulated_artifact(
                        id="IMDB-RATINGS",
                        content=sim_imdb,
                        source_url=url,
                        metadata={"dataset": "title.ratings"},
                    )
                ]
            return []

        # Spotify Web API (Top Tracks / Trends)
        # URI: https://api.spotify.com/v1/browse/new-releases
        url = "https://api.spotify.com/v1/browse/new-releases"

        if self.allow_simulation:
            sim_spotify = [
                {
                    "name": "Flowers",
                    "artist": "Miley Cyrus",
                    "popularity": 98,
                    "release_date": "2023-01-13",
                },
                {
                    "name": "Kill Bill",
                    "artist": "SZA",
                    "popularity": 95,
                    "release_date": "2022-12-09",
                },
            ]
            return [
                self.create_simulated_artifact(
                    id="SPOTIFY-TRENDS",
                    content=sim_spotify,
                    source_url=url,
                    metadata={"dataset": "new-releases"},
                )
            ]
        return []

    async def transform(self, raw_artifacts: list[RawArtifact]) -> list[StandardSchema]:
        results = []

        if self.media_mode == "imdb":
            TARGET_SCHEMA = {"title": "string", "rating": "number", "votes": "integer"}
            for raw in raw_artifacts:
                for row in raw.content:
                    raw_data = {
                        "title": row.get("primaryTitle"),
                        "rating": float(row.get("averageRating", 0)),
                        "votes": int(row.get("numVotes", 0)),
                    }
                    verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                    if verified:
                        record_id = crypto.record_id(f"IMDB-{row['tconst']}")
                        results.append(
                            StandardSchema(
                                id=record_id,
                                industry="media_and_entertainment",
                                data=verified,
                                provenance={"source": raw.source_url, "provider": "IMDb"},
                                checksum=crypto.checksum(json.dumps(verified, sort_keys=True)),
                            )
                        )
            return results

        # Spotify Transformation
        TARGET_SCHEMA = {"track_name": "string", "artist": "string", "popularity_score": "integer"}
        for raw in raw_artifacts:
            for row in raw.content:
                raw_data = {
                    "track_name": row.get("name"),
                    "artist": row.get("artist"),
                    "popularity_score": int(row.get("popularity", 0)),
                }
                verified = self.llm_manager._verify_schema(raw_data, TARGET_SCHEMA, strict=True)
                if verified:
                    record_id = crypto.record_id(
                        f"SPOTIFY-{raw_data['track_name']}-{raw_data['artist']}"
                    )
                    results.append(
                        StandardSchema(
                            id=record_id,
                            industry="media_and_entertainment",
                            data=verified,
                            provenance={"source": raw.source_url, "provider": "Spotify"},
                            checksum=crypto.checksum(json.dumps(verified, sort_keys=True)),
                        )
                    )
        return results

    def validate(self, normalized_data: list[StandardSchema]) -> bool:
        return all(
            r.data.get("rating", 0) >= 0 and r.data.get("popularity_score", 0) >= 0
            for r in [
                r for r in normalized_data if "rating" in r.data or "popularity_score" in r.data
            ]
        )
