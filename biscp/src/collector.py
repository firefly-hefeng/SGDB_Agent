#!/usr/bin/env python3
"""
Single Cell Portal Metadata Collector
Collects human single-cell RNA-seq metadata from Broad Institute's Single Cell Portal
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import aiohttp
import backoff

# Configuration
BASE_URL = "https://singlecell.broadinstitute.org/single_cell/api/v1"
RATE_LIMIT = 3
TIMEOUT = 30
MAX_RETRIES = 3
CHECKPOINT_EVERY = 10
VERIFY_SSL = False  # Set True for production

# Setup logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"collector_{datetime.now():%Y%m%d}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Study:
    """Study data model with complete fields"""
    
    def __init__(self, data: Dict):
        # Basic info
        self.accession = data.get("accession", "")
        self.name = data.get("name", "")
        self.description = data.get("description", "")
        self.full_description = data.get("full_description", "")
        self.public = data.get("public", True)
        self.detached = data.get("detached", False)
        
        # Species
        taxon = data.get("taxon") or data.get("species", {})
        if isinstance(taxon, dict):
            self.species = taxon.get("scientific_name", "")
            self.species_common = taxon.get("common_name", "")
        else:
            self.species = ""
            self.species_common = ""
        
        # Statistics
        self.cell_count = data.get("cell_count") or 0
        self.gene_count = data.get("gene_count") or 0
        
        # Related data
        self.study_files = self._parse_files(data.get("study_files") or [])
        self.directory_listings = data.get("directory_listings", [])
        self.external_resources = self._parse_resources(data.get("external_resources") or [])
        self.publications = self._parse_publications(data.get("publications") or [])
    
    def _parse_files(self, files) -> List[Dict]:
        """Parse study files with complete fields"""
        result = []
        if not isinstance(files, list):
            return result
        for f in files:
            if isinstance(f, dict):
                result.append({
                    "name": f.get("name"),
                    "file_type": f.get("file_type"),
                    "description": f.get("description"),
                    "bucket_location": f.get("bucket_location"),
                    "upload_file_size": f.get("upload_file_size"),
                    "download_url": f.get("download_url"),
                    "media_url": f.get("media_url")
                })
        return result
    
    def _parse_resources(self, resources) -> List[Dict]:
        """Parse external resources"""
        result = []
        if not isinstance(resources, list):
            return result
        for r in resources:
            if isinstance(r, dict):
                result.append({
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "description": r.get("description")
                })
        return result
    
    def _parse_publications(self, pubs) -> List[Dict]:
        """Parse publications with core fields"""
        result = []
        if not isinstance(pubs, list):
            return result
        for p in pubs:
            if isinstance(p, dict):
                result.append({
                    "title": p.get("title"),
                    "journal": p.get("journal"),
                    "url": p.get("url"),
                    "pmcid": p.get("pmcid"),
                    "pmid": p.get("pmid"),
                    "doi": p.get("doi"),
                    "citation": p.get("citation"),
                    "preprint": p.get("preprint", False)
                })
        return result
    
    def is_human(self) -> bool:
        """Check if study is human-derived"""
        if self.species:
            return self.species.lower() == "homo sapiens"
        
        text = f"{self.name} {self.description}".lower()
        human_keywords = ['human', 'patient', 'homo sapiens', 'pbmc', 't cell', 'b cell',
                         'cd4', 'cd8', 'tumor', 'cancer', 'melanoma', 'leukemia']
        animal_keywords = ['mouse', 'mice', 'mus musculus', 'rat ', 'rattus',
                          'zebrafish', 'fly', 'drosophila', 'worm', 'c. elegans']
        
        has_human = any(kw in text for kw in human_keywords)
        has_animal = any(kw in text for kw in animal_keywords)
        
        return not has_animal
    
    def to_dict(self) -> Dict:
        """Convert to dictionary with all fields"""
        return {
            "accession": self.accession,
            "name": self.name,
            "description": self.description,
            "full_description": self.full_description,
            "public": self.public,
            "detached": self.detached,
            "species": self.species,
            "species_common": self.species_common,
            "cell_count": self.cell_count,
            "gene_count": self.gene_count,
            "study_files": self.study_files,
            "directory_listings": self.directory_listings,
            "external_resources": self.external_resources,
            "publications": self.publications
        }


class CollectionState:
    """Manage collection state for resume capability"""
    
    def __init__(self):
        self.start_time = datetime.now().isoformat()
        self.total = 0
        self.done = []
        self.human = []
        self.failed = []
        self.errors = []
    
    def save(self, filepath: Path):
        filepath.write_text(json.dumps({
            "start_time": self.start_time,
            "total": self.total,
            "done": self.done,
            "human": self.human,
            "failed": self.failed,
            "errors": self.errors[-50:]
        }, indent=2))
    
    @classmethod
    def load(cls, filepath: Path) -> Optional["CollectionState"]:
        if filepath.exists():
            try:
                data = json.loads(filepath.read_text())
                state = cls()
                state.start_time = data.get("start_time", state.start_time)
                state.total = data.get("total", 0)
                state.done = data.get("done", [])
                state.human = data.get("human", [])
                state.failed = data.get("failed", [])
                state.errors = data.get("errors", [])
                return state
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
        return None


class APIClient:
    """Async API client with retry capability"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.semaphore = asyncio.Semaphore(RATE_LIMIT)
    
    async def __aenter__(self):
        import ssl
        ssl_ctx = ssl.create_default_context()
        if not VERIFY_SSL:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            headers={"Accept": "application/json", "User-Agent": "SCP-Collector/2.0"},
            connector=aiohttp.TCPConnector(ssl=ssl_ctx)
        )
        return self
    
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
    
    @backoff.on_exception(backoff.expo, (aiohttp.ClientError, asyncio.TimeoutError), max_tries=MAX_RETRIES)
    async def get(self, endpoint: str) -> Optional[Dict]:
        if not self.session:
            return None
        
        url = f"{BASE_URL}/{endpoint}"
        async with self.semaphore:
            async with self.session.get(url) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                await asyncio.sleep(1 / RATE_LIMIT)
                return await resp.json()


class Collector:
    """Main collector class"""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = CollectionState.load(state_file) or CollectionState()
        self.client: Optional[APIClient] = None
    
    async def __aenter__(self):
        self.client = APIClient()
        await self.client.__aenter__()
        return self
    
    async def __aexit__(self, *args):
        if self.client:
            await self.client.__aexit__(*args)
        self.state.save(self.state_file)
    
    async def run(self) -> List[Study]:
        """Run collection"""
        logger.info("=" * 60)
        logger.info("Single Cell Portal Collector Started")
        logger.info("=" * 60)
        
        studies_data = await self.client.get("site/studies")
        if not studies_data:
            logger.error("Failed to fetch studies")
            return []
        
        all_accessions = [s["accession"] for s in studies_data if isinstance(s, dict) and s.get("accession")]
        
        if self.state.total == 0:
            self.state.total = len(all_accessions)
        
        todo = [a for a in all_accessions if a not in self.state.done]
        logger.info(f"Total: {len(all_accessions)}, Done: {len(self.state.done)}, Todo: {len(todo)}")
        
        if not todo:
            logger.info("All studies processed!")
            return []
        
        results = []
        for i, accession in enumerate(todo, 1):
            logger.info(f"[{i}/{len(todo)}] Processing {accession}...")
            
            data = await self.client.get(f"site/studies/{accession}")
            if data:
                study = Study(data)
                self.state.done.append(accession)
                
                if study.is_human():
                    self.state.human.append(accession)
                    results.append(study)
                    files_info = f", {len(study.study_files)} files" if study.study_files else ""
                    pubs_info = f", {len(study.publications)} pubs" if study.publications else ""
                    logger.info(f"  ✓ Human [{study.species or 'inferred'}]{files_info}{pubs_info}")
                else:
                    logger.info(f"  ℹ Skip ({study.species or 'non-human'})")
            else:
                self.state.failed.append(accession)
                logger.warning(f"  ✗ Failed")
            
            if i % CHECKPOINT_EVERY == 0:
                self.state.save(self.state_file)
                logger.info(f"Progress: {len(self.state.done)}/{self.state.total}")
        
        self.state.save(self.state_file)
        logger.info("=" * 60)
        logger.info(f"Completed: {len(self.state.done)} processed, {len(self.state.human)} human, {len(self.state.failed)} failed")
        
        return results


def save_results(studies: List[Study], output_dir: Path):
    """Save results in JSON and CSV formats"""
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON
    json_file = output_dir / f"human_studies_{timestamp}.json"
    json_file.write_text(json.dumps({
        "metadata": {
            "source": "Single Cell Portal",
            "url": BASE_URL,
            "collected_at": datetime.now().isoformat(),
            "count": len(studies),
            "version": "2.0"
        },
        "studies": [s.to_dict() for s in studies]
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved JSON: {json_file}")
    
    # CSV
    csv_file = output_dir / f"human_studies_{timestamp}.csv"
    import csv
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        if studies:
            fieldnames = ["accession", "name", "species", "cell_count", "gene_count",
                         "publications_count", "files_count", "description"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in studies:
                writer.writerow({
                    "accession": s.accession,
                    "name": s.name,
                    "species": s.species,
                    "cell_count": s.cell_count,
                    "gene_count": s.gene_count,
                    "publications_count": len(s.publications),
                    "files_count": len(s.study_files),
                    "description": s.description[:200] if s.description else ""
                })
    logger.info(f"Saved CSV: {csv_file}")
    
    return json_file, csv_file


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Single Cell Portal Metadata Collector")
    parser.add_argument("--all", action="store_true", help="Collect all species")
    parser.add_argument("--reset", action="store_true", help="Reset and restart")
    args = parser.parse_args()
    
    state_file = Path(__file__).parent.parent / ".state.json"
    output_dir = Path(__file__).parent.parent / "data" / "processed"
    
    if args.reset and state_file.exists():
        state_file.unlink()
        logger.info("State reset")
    
    async with Collector(state_file) as collector:
        studies = await collector.run()
        if studies:
            save_results(studies, output_dir)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception("Fatal error")
        sys.exit(1)
