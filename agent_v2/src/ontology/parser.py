#!/usr/bin/env python3
"""
Parse OBO format ontology files and extract structured data.

OBO format reference: http://owlcollab.github.io/oboformat/doc/GO.format.obo-1_4.html
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


@dataclass
class OBOTerm:
    """Parsed OBO term"""
    ontology_id: str
    ontology_source: str
    label: str
    definition: str = ""
    synonyms: List[str] = field(default_factory=list)
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    is_obsolete: bool = False


class OBOParser:
    """Parse OBO format ontology files"""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.terms: Dict[str, OBOTerm] = {}

    def parse(self) -> Dict[str, OBOTerm]:
        """Parse OBO file and return dict of terms"""
        print(f"Parsing {self.file_path.name}...")

        with open(self.file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split into stanzas
        stanzas = re.split(r'\n\[Term\]\n', content)

        # Extract ontology source from header
        header = stanzas[0]
        ontology_source = self._extract_ontology_source(header)

        # Parse each term stanza
        for stanza in stanzas[1:]:
            if not stanza.strip():
                continue

            term = self._parse_term_stanza(stanza, ontology_source)
            if term and not term.is_obsolete:
                self.terms[term.ontology_id] = term

        # Build child relationships
        self._build_child_relationships()

        print(f"  Parsed {len(self.terms)} terms from {ontology_source}")
        return self.terms

    def _extract_ontology_source(self, header: str) -> str:
        """Extract ontology source from header"""
        # Try to find ontology: field (skip URLs like http://...)
        match = re.search(r'^ontology:\s*(\w+)$', header, re.IGNORECASE | re.MULTILINE)
        if match and not match.group(1).lower().startswith("http"):
            return match.group(1).upper()

        # Fallback: extract from filename
        name = self.file_path.stem.upper()
        return name

    def _parse_term_stanza(self, stanza: str, ontology_source: str) -> OBOTerm:
        """Parse a single [Term] stanza"""
        lines = stanza.strip().split('\n')

        term_id = None
        label = None
        definition = ""
        synonyms = []
        parent_ids = []
        is_obsolete = False

        for line in lines:
            line = line.strip()
            if not line or line.startswith('!'):
                continue

            if line.startswith('id:'):
                term_id = line.split(':', 1)[1].strip()

            elif line.startswith('name:'):
                label = line.split(':', 1)[1].strip()

            elif line.startswith('def:'):
                # Extract definition text (between quotes)
                match = re.search(r'"([^"]+)"', line)
                if match:
                    definition = match.group(1)

            elif line.startswith('synonym:'):
                # Extract synonym text (between quotes)
                match = re.search(r'"([^"]+)"', line)
                if match:
                    syn = match.group(1)
                    if syn and syn != label:
                        synonyms.append(syn)

            elif line.startswith('is_a:'):
                # Extract parent ID
                parent = line.split(':', 1)[1].strip().split('!')[0].strip()
                if parent:
                    parent_ids.append(parent)

            elif line.startswith('is_obsolete:'):
                is_obsolete = 'true' in line.lower()

        if not term_id or not label:
            return None

        return OBOTerm(
            ontology_id=term_id,
            ontology_source=ontology_source,
            label=label,
            definition=definition,
            synonyms=synonyms,
            parent_ids=parent_ids,
            is_obsolete=is_obsolete
        )

    def _build_child_relationships(self):
        """Build child_ids from parent_ids"""
        for term_id, term in self.terms.items():
            for parent_id in term.parent_ids:
                if parent_id in self.terms:
                    self.terms[parent_id].child_ids.append(term_id)

    def compute_ancestors_descendants(self) -> Dict[str, tuple]:
        """
        Compute transitive closure of ancestors and descendants.
        Returns dict: {term_id: (ancestor_set, descendant_set)}
        """
        print(f"  Computing ancestors/descendants...")

        ancestors = {}
        descendants = {}

        # Initialize
        for term_id in self.terms:
            ancestors[term_id] = set()
            descendants[term_id] = set()

        # Compute ancestors (bottom-up)
        def get_ancestors(term_id: str, visited: Set[str]) -> Set[str]:
            if term_id in visited:
                return set()
            visited.add(term_id)

            if term_id not in self.terms:
                return set()

            anc = set()
            for parent_id in self.terms[term_id].parent_ids:
                anc.add(parent_id)
                anc.update(get_ancestors(parent_id, visited))

            return anc

        for term_id in self.terms:
            ancestors[term_id] = get_ancestors(term_id, set())

        # Compute descendants (top-down)
        def get_descendants(term_id: str, visited: Set[str]) -> Set[str]:
            if term_id in visited:
                return set()
            visited.add(term_id)

            if term_id not in self.terms:
                return set()

            desc = set()
            for child_id in self.terms[term_id].child_ids:
                desc.add(child_id)
                desc.update(get_descendants(child_id, visited))

            return desc

        for term_id in self.terms:
            descendants[term_id] = get_descendants(term_id, set())

        print(f"  Computed ancestors/descendants for {len(self.terms)} terms")

        return {
            term_id: (ancestors[term_id], descendants[term_id])
            for term_id in self.terms
        }


def main():
    """Test parser"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_obo.py <obo_file>")
        sys.exit(1)

    obo_file = Path(sys.argv[1])
    if not obo_file.exists():
        print(f"File not found: {obo_file}")
        sys.exit(1)

    parser = OBOParser(obo_file)
    terms = parser.parse()

    # Compute ancestors/descendants
    closure = parser.compute_ancestors_descendants()

    # Show sample
    print("\nSample terms:")
    for i, (term_id, term) in enumerate(list(terms.items())[:5]):
        anc, desc = closure[term_id]
        print(f"\n{term_id}: {term.label}")
        print(f"  Definition: {term.definition[:80]}...")
        print(f"  Synonyms: {', '.join(term.synonyms[:3])}")
        print(f"  Parents: {len(term.parent_ids)}, Children: {len(term.child_ids)}")
        print(f"  Ancestors: {len(anc)}, Descendants: {len(desc)}")


if __name__ == "__main__":
    main()
