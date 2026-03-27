"""
Collections收集模块
==================

从CellxGene API收集所有Collections的元数据。
"""

import requests
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class CollectionCollector:
    """CellxGene Collections收集器"""
    
    API_URL = "https://api.cellxgene.cziscience.com/curation/v1/collections"
    
    def __init__(self, output_dir: str = "data/raw"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        
    def fetch_all_collections(self) -> List[Dict]:
        """
        获取所有Collections
        
        Returns:
            List[Dict]: Collections列表
        """
        self.logger.info("Fetching all collections from CellxGene API...")
        
        all_collections = []
        page = 1
        
        while True:
            try:
                response = self.session.get(
                    self.API_URL,
                    params={'page': page},
                    timeout=60
                )
                response.raise_for_status()
                
                data = response.json()
                collections = data.get('collections', [])
                
                if not collections:
                    break
                
                all_collections.extend(collections)
                self.logger.info(f"  Page {page}: {len(collections)} collections")
                
                if len(collections) < 20:
                    break
                
                page += 1
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"Error on page {page}: {e}")
                break
        
        self.logger.info(f"Total collections fetched: {len(all_collections)}")
        return all_collections
    
    def process_collection(self, collection: Dict) -> Dict:
        """
        处理单个Collection，提取关键字段
        """
        pm = collection.get('publisher_metadata', {})
        authors = pm.get('authors', [])
        
        return {
            'collection_id': collection.get('collection_id'),
            'collection_url': collection.get('collection_url'),
            'name': collection.get('name'),
            'description': collection.get('description'),
            'doi': collection.get('doi'),
            'visibility': collection.get('visibility'),
            'created_at': collection.get('created_at'),
            'published_at': collection.get('published_at'),
            'contact_name': collection.get('contact_name'),
            'contact_email': collection.get('contact_email'),
            'curator_name': collection.get('curator_name'),
            'pm_journal': pm.get('journal'),
            'pm_published_year': pm.get('published_year'),
            'pm_published_month': pm.get('published_month'),
            'pm_is_preprint': pm.get('is_preprint'),
            'pm_authors': '; '.join([
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in authors
            ]),
            'pm_author_count': len(authors),
            'dataset_count': len(collection.get('datasets', [])),
        }
    
    def save_raw(self, collections: List[Dict]):
        """保存原始数据"""
        output_file = self.output_dir / "collections_raw.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(collections, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Raw data saved to: {output_file}")
    
    def collect(self) -> List[Dict]:
        """执行完整收集流程"""
        self.logger.info("=" * 60)
        self.logger.info("Starting Collections Collection")
        self.logger.info("=" * 60)
        
        # 获取原始数据
        collections = self.fetch_all_collections()
        self.save_raw(collections)
        
        # 处理数据
        processed = [self.process_collection(c) for c in collections]
        
        self.logger.info(f"Collection complete: {len(processed)} collections")
        return processed


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.utils import setup_logging
    
    logger = setup_logging()
    collector = CollectionCollector()
    collections = collector.collect()
    
    print(f"\nCollected {len(collections)} collections")
    print(f"Output: data/raw/collections_raw.json")
