"""
Unit Tests — Cross-DB Fusion Engine

Tests: single-record wrapping, UnionFind grouping, identity hash merge,
multi-source aggregation, quality scoring.
"""
import pytest

from src.core.models import FusedRecord
from src.fusion.engine import (
    CrossDBFusionEngine,
    SOURCE_QUALITY_RANK,
    QUALITY_FIELDS,
    UnionFind,
)


class TestUnionFind:
    """Test Union-Find data structure."""

    def test_single_element(self):
        uf = UnionFind()
        assert uf.find(1) == 1

    def test_union_two(self):
        uf = UnionFind()
        uf.union(1, 2)
        assert uf.find(1) == uf.find(2)

    def test_union_chain(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(2, 3)
        assert uf.find(1) == uf.find(3)

    def test_disjoint_sets(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(3, 4)
        assert uf.find(1) != uf.find(3)

    def test_path_compression(self):
        uf = UnionFind()
        for i in range(1, 100):
            uf.union(i, i + 1)
        # After path compression, all should point to same root
        root = uf.find(1)
        assert uf.find(100) == root


class TestFusionEngineSingleSource:
    """Test fusion with single-source results (no dedup needed)."""

    @pytest.fixture
    def engine(self, mocker):
        dal = mocker.MagicMock()
        dal.execute.return_value = mocker.MagicMock(rows=[])
        return CrossDBFusionEngine(dal=dal)

    def test_empty_results(self, engine):
        assert engine.fuse([]) == []

    def test_single_record(self, engine):
        rows = [{"pk": 1, "tissue": "liver", "source_database": "geo"}]
        fused = engine.fuse(rows)
        assert len(fused) == 1
        assert fused[0].sources == ["geo"]
        assert fused[0].source_count == 1
        assert fused[0].data["tissue"] == "liver"

    def test_all_same_source(self, engine):
        rows = [
            {"pk": 1, "tissue": "liver", "source_database": "geo"},
            {"pk": 2, "tissue": "brain", "source_database": "geo"},
        ]
        fused = engine.fuse(rows)
        assert len(fused) == 2


class TestFusionEngineMultiSource:
    """Test fusion with multi-source results."""

    @pytest.fixture
    def engine(self, mocker):
        dal = mocker.MagicMock()
        # Simulate no entity_links (no hard links to merge)
        from src.core.models import QueryResult
        dal.execute.return_value = QueryResult(rows=[])
        return CrossDBFusionEngine(dal=dal)

    def test_multi_source_no_merge(self, engine):
        """Different sources, different PKs, no hash → no merge."""
        rows = [
            {"pk": 1, "tissue": "liver", "source_database": "geo"},
            {"pk": 2, "tissue": "liver", "source_database": "cellxgene"},
        ]
        fused = engine.fuse(rows)
        # Without hash or link match, each stays separate
        assert len(fused) == 2

    def test_hash_based_merge(self, engine):
        """Same identity hash → merged."""
        rows = [
            {"pk": 1, "tissue": "liver", "source_database": "geo",
             "biological_identity_hash": "abc123"},
            {"pk": 2, "tissue": "liver", "source_database": "cellxgene",
             "biological_identity_hash": "abc123"},
        ]
        fused = engine.fuse(rows)
        assert len(fused) == 1
        assert fused[0].records_merged == 2
        assert fused[0].source_count == 2


class TestQualityScoring:
    """Test quality score computation."""

    @pytest.fixture
    def engine(self, mocker):
        dal = mocker.MagicMock()
        dal.execute.return_value = mocker.MagicMock(rows=[])
        return CrossDBFusionEngine(dal=dal)

    def test_quality_score_range(self, engine):
        rows = [{"pk": 1, "tissue": "liver", "source_database": "cellxgene"}]
        fused = engine.fuse(rows)
        assert 0 <= fused[0].quality_score <= 100

    def test_cellxgene_higher_than_geo(self, engine):
        """CellXGene should score higher than GEO (rank 1 vs 4)."""
        rows = [
            {"pk": 1, "tissue": "liver", "disease": "normal",
             "source_database": "cellxgene", "organism": "human"},
            {"pk": 2, "tissue": "liver",
             "source_database": "geo"},
        ]
        fused = engine.fuse(rows)
        cxg = next(r for r in fused if "cellxgene" in r.sources)
        geo = next(r for r in fused if "geo" in r.sources)
        assert cxg.quality_score >= geo.quality_score

    def test_more_fields_higher_score(self, engine):
        """Records with more metadata fields score higher."""
        rows = [
            {"pk": 1, "tissue": "liver", "disease": "normal", "sex": "male",
             "organism": "human", "assay": "10x", "source_database": "cellxgene"},
            {"pk": 2, "tissue": "liver", "source_database": "geo"},
        ]
        fused = engine.fuse(rows)
        rich = next(r for r in fused if r.data.get("sex") == "male")
        sparse = next(r for r in fused if not r.data.get("sex"))
        assert rich.quality_score > sparse.quality_score

    def test_source_quality_rank(self):
        assert SOURCE_QUALITY_RANK["cellxgene"] < SOURCE_QUALITY_RANK["geo"]
        assert SOURCE_QUALITY_RANK["ebi"] < SOURCE_QUALITY_RANK["ncbi"]
