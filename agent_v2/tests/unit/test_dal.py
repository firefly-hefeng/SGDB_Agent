"""
Unit Tests — Database Abstraction Layer

Tests: ConnectionPool, DAL initialization, query execution, ID detection,
entity lookup, schema inspection.
"""
import sqlite3
import tempfile
import os
import pytest

from src.core.exceptions import DatabaseNotFoundError, DatabaseError
from src.core.models import QueryFilters
from src.dal.database import ConnectionPool, DatabaseAbstractionLayer, SchemaInspector


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with test schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE unified_projects (
            pk INTEGER PRIMARY KEY,
            project_id TEXT,
            source_database TEXT,
            title TEXT,
            pmid TEXT,
            doi TEXT,
            citation_count INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE unified_samples (
            pk INTEGER PRIMARY KEY,
            sample_id TEXT,
            project_pk INTEGER,
            series_pk INTEGER,
            source_database TEXT,
            tissue TEXT,
            disease TEXT,
            sex TEXT,
            organism TEXT,
            n_cells INTEGER,
            biological_identity_hash TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE unified_series (
            pk INTEGER PRIMARY KEY,
            series_id TEXT,
            project_pk INTEGER,
            source_database TEXT,
            assay TEXT,
            series_title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE unified_celltypes (
            pk INTEGER PRIMARY KEY,
            sample_pk INTEGER,
            cell_type_name TEXT,
            cell_type_ontology_term_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE entity_links (
            pk INTEGER PRIMARY KEY,
            source_pk INTEGER,
            target_pk INTEGER,
            source_entity_type TEXT,
            target_entity_type TEXT,
            relationship_type TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE id_mappings (
            pk INTEGER PRIMARY KEY,
            id_value TEXT,
            entity_type TEXT,
            entity_pk INTEGER
        )
    """)

    # Insert test data
    conn.executemany(
        "INSERT INTO unified_projects (pk, project_id, source_database, title, pmid) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "GSE149614", "geo", "COVID-19 PBMC", "32587976"),
            (2, "PRJNA12345", "ncbi", "Brain Atlas", None),
        ],
    )
    conn.executemany(
        "INSERT INTO unified_samples (pk, sample_id, project_pk, source_database, tissue, disease, organism) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "GSM1234", 1, "geo", "blood", "COVID-19", "Homo sapiens"),
            (2, "GSM5678", 1, "geo", "lung", "COVID-19", "Homo sapiens"),
            (3, "SAMN9999", 2, "ncbi", "brain", "normal", "Homo sapiens"),
        ],
    )
    conn.commit()
    conn.close()

    yield path

    os.unlink(path)


class TestConnectionPool:
    """Test connection pool lifecycle."""

    def test_acquire_and_release(self, tmp_db):
        pool = ConnectionPool(tmp_db, read_only=True, max_size=4)
        conn = pool.acquire()
        assert conn is not None
        pool.release(conn)
        pool.close_all()

    def test_connection_reuse(self, tmp_db):
        pool = ConnectionPool(tmp_db, read_only=True, max_size=4)
        conn1 = pool.acquire()
        pool.release(conn1)
        conn2 = pool.acquire()
        assert conn1 is conn2  # Should reuse
        pool.release(conn2)
        pool.close_all()

    def test_multiple_concurrent(self, tmp_db):
        pool = ConnectionPool(tmp_db, read_only=True, max_size=4)
        conns = [pool.acquire() for _ in range(4)]
        assert len(conns) == 4
        for c in conns:
            pool.release(c)
        pool.close_all()

    def test_close_all(self, tmp_db):
        pool = ConnectionPool(tmp_db, read_only=True, max_size=4)
        pool.acquire()
        pool.close_all()


class TestDALInitialization:
    """Test DAL initialization."""

    def test_successful_init(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        assert dal.db_path == tmp_db

    def test_missing_db_raises(self):
        with pytest.raises(DatabaseNotFoundError):
            DatabaseAbstractionLayer("/nonexistent/path.db")


class TestDALExecute:
    """Test raw SQL execution."""

    def test_basic_query(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        result = dal.execute("SELECT COUNT(*) as cnt FROM unified_samples")
        assert result.rows[0]["cnt"] == 3

    def test_parameterized_query(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        result = dal.execute(
            "SELECT * FROM unified_samples WHERE tissue = ?",
            ["blood"],
        )
        assert len(result.rows) == 1
        assert result.rows[0]["tissue"] == "blood"

    def test_execution_time_tracked(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        result = dal.execute("SELECT 1")
        assert result.execution_time_ms >= 0

    def test_columns_returned(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        result = dal.execute("SELECT pk, tissue FROM unified_samples LIMIT 1")
        assert "pk" in result.columns
        assert "tissue" in result.columns


class TestDALEntityLookup:
    """Test ID auto-detection and entity lookup."""

    def test_gse_lookup(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        entity = dal.get_entity_by_id("GSE149614")
        assert entity is not None
        assert entity["project_id"] == "GSE149614"

    def test_prjna_lookup(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        entity = dal.get_entity_by_id("PRJNA12345")
        assert entity is not None
        assert entity["project_id"] == "PRJNA12345"

    def test_pmid_lookup(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        entity = dal.get_entity_by_id("PMID:32587976")
        assert entity is not None
        assert entity["pmid"] == "32587976"

    def test_unknown_id(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        entity = dal.get_entity_by_id("UNKNOWN_99999")
        assert entity is None


class TestSchemaInspector:
    """Test schema introspection."""

    def test_analyze(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        schema = dal.schema_inspector.analyze()
        assert "unified_samples" in schema["tables"]
        assert "unified_projects" in schema["tables"]
        assert schema["tables"]["unified_samples"]["record_count"] == 3

    def test_get_summary(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        summary = dal.get_schema_summary()
        assert "tables" in summary
        assert "stats" in summary
        assert summary["stats"]["total_samples"] == 3

    def test_get_field_stats(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        stats = dal.get_field_stats("unified_samples", "tissue")
        assert stats.total_count == 3
        assert stats.distinct_count == 3  # blood, lung, brain
        assert stats.non_null_count == 3

    def test_ddl_summary(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        ddl = dal.schema_inspector.get_ddl_summary()
        assert "unified_samples" in ddl
        assert "CREATE TABLE" in ddl

    def test_schema_cached(self, tmp_db):
        dal = DatabaseAbstractionLayer(tmp_db)
        s1 = dal.schema_inspector.analyze()
        s2 = dal.schema_inspector.analyze()
        assert s1 is s2  # Should be same object
