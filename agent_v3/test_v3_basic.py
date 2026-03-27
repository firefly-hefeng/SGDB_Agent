"""Quick test for agent_v3 basic functionality."""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.understanding.v1_parser import V1QueryParser
from src.core.models import SessionContext


class MockLLM:
    """Mock LLM for testing."""
    async def chat(self, prompt, temperature=0.1, max_tokens=2048):
        # Return a simple mock response
        return type('obj', (object,), {
            'content': '{"intent": "SEARCH", "organisms": ["Homo sapiens"], "tissues": [], "diseases": [], "assays": [], "free_text": "单细胞数据", "confidence": 0.9}'
        })()


async def test_v1_parser():
    """Test V1Parser basic functionality."""
    print("Testing V1Parser...")

    llm = MockLLM()
    parser = V1QueryParser(llm=llm, schema_knowledge=None)

    # Test query
    query = "所有人源单细胞数据"
    result = await parser.parse(query, SessionContext(session_id="test"))

    print(f"Query: {query}")
    print(f"Intent: {result.intent}")
    print(f"Organisms: {result.filters.organisms}")
    print(f"Confidence: {result.confidence}")
    print(f"Parse method: {result.parse_method}")

    assert result.filters.organisms == ["Homo sapiens"], "Should extract Homo sapiens"
    print("✓ V1Parser test passed!")


if __name__ == "__main__":
    asyncio.run(test_v1_parser())
