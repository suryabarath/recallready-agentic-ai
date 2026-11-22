"""FDA-only Qdrant Cloud Inference boundary; exact evidence stays in SQLite."""

from dataclasses import dataclass
import json
import math
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi

from embedding_inputs import EmbeddingInput, load_embedding_inputs
from fda_store import FDAStore, StoreError


COLLECTION = "recallready_fda_food_a1_v1"
MODEL = "sentence-transformers/all-minilm-l6-v2"
DIMENSIONS = 384
FILTER_FIELDS = ("recall_number", "snapshot_id")


class QdrantA1Error(ValueError):
    """Cloud setup or retrieved evidence failed validation."""


class _RejectRedirects(HTTPRedirectHandler):
    """Keep credentials on the configured endpoint by refusing redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class EvidenceHit:
    evidence_id: str
    recall_number: str
    event_id: str
    snapshot_id: str
    field_name: str
    original_text: str
    point_id: str
    similarity_score: float


def collection_config() -> dict:
    return {"vectors": {"size": DIMENSIONS, "distance": "Cosine"}}


def cloud_point(item: EmbeddingInput) -> dict:
    """Send source-checked text for hosted MiniLM, never a fabricated vector."""
    return {
        "id": item.point_id,
        "vector": {"text": item.text_for_embedding, "model": MODEL},
        "payload": {
            "source_system": "openFDA_food_enforcement",
            "snapshot_id": item.snapshot_id,
            "evidence_id": item.evidence_id,
            "recall_number": item.recall_number,
            "event_id": item.event_id,
            "field_name": item.field_name,
        },
    }


class QdrantA1:
    """Explicit new-collection operations and source-checked retrieval."""

    def __init__(self, url: str, api_key: str, store: FDAStore, *, transport=None):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise QdrantA1Error("Qdrant URL must be an HTTPS cluster root")
        if not api_key:
            raise QdrantA1Error("Qdrant API key is required")
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.store = store
        self._transport = transport or self._request

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.url + path, data=data, method=method,
                          headers={"api-key": self.api_key,
                                   "Content-Type": "application/json"})
        try:
            tls_context = ssl.create_default_context(cafile=certifi.where())
            opener = build_opener(HTTPSHandler(context=tls_context), _RejectRedirects())
            with opener.open(request, timeout=30) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise QdrantA1Error("Qdrant request failed; inspect cluster status privately") from exc

    def _call(self, method: str, path: str, body: dict | None) -> dict:
        response = self._transport(method, path, body)
        if not isinstance(response, dict):
            raise QdrantA1Error("Qdrant returned an invalid response object")
        return response

    def create_new_collection(self) -> None:
        """Refuse a name collision; never replace or delete a collection."""
        path = "/collections/" + quote(COLLECTION, safe="")
        exists = self._call("GET", path + "/exists", None)
        result = exists.get("result")
        if not isinstance(result, dict) or result.get("exists") is not False:
            raise QdrantA1Error("FDA A1 collection already exists or existence is uncertain")
        created = self._call("PUT", path, collection_config())
        if created.get("result") is not True:
            raise QdrantA1Error("Qdrant did not confirm collection creation")
        self.create_filter_indexes()

    def create_filter_indexes(self) -> None:
        """Create the keyword indexes required by exact context filters."""
        path = "/collections/" + quote(COLLECTION, safe="") + "/index?wait=true"
        for field_name in FILTER_FIELDS:
            result = self._call("PUT", path, {
                "field_name": field_name,
                "field_schema": "keyword",
            })
            if result.get("status") != "ok":
                raise QdrantA1Error("Qdrant did not confirm FDA filter index creation")

    def upsert_verified(self) -> None:
        """Upload only the complete verified 72-point staging set."""
        inputs = load_embedding_inputs(self.store)
        if len(inputs) != 72 or len({x.point_id for x in inputs}) != 72:
            raise QdrantA1Error("Expected 72 unique FDA points")
        for item in inputs:
            try:
                exact = self.store.resolve(item.evidence_id, recall_number=item.recall_number,
                                           event_id=item.event_id, snapshot_id=item.snapshot_id)
            except StoreError as exc:
                raise QdrantA1Error("Staging evidence differs from SQLite") from exc
            if (item.point_id, item.field_name) != (exact.point_id, exact.field_name):
                raise QdrantA1Error("Staging point identity differs from SQLite")
        path = "/collections/" + quote(COLLECTION, safe="") + "/points?wait=true"
        for start in range(0, 72, 16):
            result = self._call("PUT", path, {"points": [cloud_point(x) for x in inputs[start:start + 16]]})
            if result.get("status") != "ok":
                raise QdrantA1Error("Qdrant did not confirm FDA point upload")

    def query(self, text: str, *, recall_number: str, snapshot_id: str,
              top_k: int = 8) -> tuple[EvidenceHit, ...]:
        """Rank within one exact recall/snapshot; verify every hit in SQLite."""
        if (not isinstance(text, str) or not text.strip()
                or not isinstance(top_k, int) or isinstance(top_k, bool)
                or not 1 <= top_k <= 8):
            raise QdrantA1Error("Query text or top_k is invalid")
        record = self.store.lookup(recall_number, snapshot_id=snapshot_id)
        body = {
            "query": {"text": text, "model": MODEL},
            "filter": {"must": [
                {"key": "recall_number", "match": {"value": recall_number}},
                {"key": "snapshot_id", "match": {"value": snapshot_id}},
            ]},
            "with_payload": True, "limit": top_k,
        }
        path = "/collections/" + quote(COLLECTION, safe="") + "/points/query"
        response = self._call("POST", path, body)
        result = response.get("result")
        if not isinstance(result, dict):
            raise QdrantA1Error("Qdrant returned an invalid query result")
        points = result.get("points")
        if not isinstance(points, list) or len(points) > top_k:
            raise QdrantA1Error("Qdrant returned no valid point list")
        hits = []
        seen = set()
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("payload"), dict):
                raise QdrantA1Error("Qdrant returned an invalid point or payload")
            payload = point["payload"]
            evidence_id = payload.get("evidence_id")
            try:
                exact = self.store.resolve(evidence_id, recall_number=recall_number,
                                           event_id=record["event_id"], snapshot_id=snapshot_id)
            except (StoreError, TypeError) as exc:
                raise QdrantA1Error("Qdrant hit has unknown or cross-context evidence") from exc
            if (point.get("id") != exact.point_id or evidence_id in seen
                    or payload.get("recall_number") != recall_number
                    or payload.get("event_id") != exact.event_id
                    or payload.get("snapshot_id") != snapshot_id
                    or payload.get("field_name") != exact.field_name
                    or payload.get("source_system") != "openFDA_food_enforcement"):
                raise QdrantA1Error("Qdrant hit metadata differs from SQLite")
            score = point.get("score")
            if (not isinstance(score, (int, float)) or isinstance(score, bool)
                    or not math.isfinite(score)):
                raise QdrantA1Error("Qdrant score is invalid")
            seen.add(evidence_id)
            hits.append(EvidenceHit(evidence_id=exact.evidence_id,
                                    recall_number=recall_number, event_id=exact.event_id,
                                    snapshot_id=snapshot_id, field_name=exact.field_name,
                                    original_text=exact.original_text, point_id=exact.point_id,
                                    similarity_score=float(score)))
        return tuple(hits)
