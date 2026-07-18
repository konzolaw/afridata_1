"""
Recommendation service — the single orchestration entry point that wires
candidate generation and hybrid scoring together for callers outside the
domain layer (Celery tasks, API views).

CollaborativeEngine and ContentBasedEngine are expensive to load (model
weights / TF-IDF matrix held in memory), so they are loaded once per
process and cached as module-level singletons, then reused across every
call to get_recommendations_for_user().
"""

from __future__ import annotations

import logging

from recommendations.domain.engines.candidate_generation import CandidateGenerator
from recommendations.domain.engines.collaborative import CollaborativeEngine
from recommendations.domain.engines.content_based import ContentBasedEngine
from recommendations.domain.engines.hybrid import WeightedHybridEngine
from recommendations.domain.schemas import EngineConfig, RankedList
from recommendations.infrastructure.persistence import (
    get_item_popularities,
    get_user_interactions,
)

logger = logging.getLogger(__name__)

_cf_engine: CollaborativeEngine | None = None
_cbf_engine: ContentBasedEngine | None = None
_hybrid_engine: WeightedHybridEngine | None = None


def _get_hybrid_engine() -> WeightedHybridEngine:
    """Lazily load and cache the CF/CBF/hybrid engine singletons for this process."""
    global _cf_engine, _cbf_engine, _hybrid_engine

    if _hybrid_engine is None:
        _cf_engine = CollaborativeEngine()
        _cf_engine.load()
        _cbf_engine = ContentBasedEngine()
        _cbf_engine.load()
        _hybrid_engine = WeightedHybridEngine(_cf_engine, _cbf_engine)
        logger.info("services._get_hybrid_engine: engines loaded and cached")

    return _hybrid_engine


def get_recommendations_for_user(
    user_id: int,
    top_n: int = 10,
    alpha: float = 0.5,
) -> RankedList:
    """
    Run the full candidate-generation + hybrid-scoring pipeline for one user.

    Parameters
    ----------
    user_id:
        Primary key of the requesting user.
    top_n:
        Maximum number of recommendations to return.
    alpha:
        Initial CF/CBF blend weight (overridden to 0.0 automatically on
        cold-start, per EngineConfig.auto_cold_start).

    Returns
    -------
    RankedList

    Raises
    ------
    ModelNotLoadedError
        If the collaborative model has not been trained yet.
    ContentEngineError
        If the content-based TF-IDF matrix has not been trained yet.
    """
    item_popularities = get_item_popularities()
    interactions = get_user_interactions(user_id)

    config = EngineConfig(
        alpha=alpha,
        top_n=top_n,
        item_popularities=item_popularities,
        interacted_item_ids=[i.dataset_id for i in interactions],
        interaction_weights=[i.implicit_weight for i in interactions],
    )

    candidate_set = CandidateGenerator().generate(
        user_id=user_id,
        config=config,
        item_popularities=item_popularities,
    )

    engine = _get_hybrid_engine()
    return engine.recommend(candidate_set, config)
