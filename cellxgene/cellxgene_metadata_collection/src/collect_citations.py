"""
Citations收集模块
================

通过DOI查询OpenAlex API收集论文引用数据。
"""

import pandas as pd
import requests
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple


class CitationCollector:
    """论文引用数据收集器 (OpenAlex API)"""
    
    def __init__(self, cache_file: str = "data/cache/citation_cache.json"):
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache = self._load_cache()
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CellxGeneCitationCollector/1.0'
        })
        self.last_request_time = 0
        self.min_delay = 0.15  # 150ms between requests
        
    def _load_cache(self) -> Dict:
        """加载缓存"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load cache: {e}")
        return {}
    
    def save_cache(self):
        """保存缓存"""
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)
    
    def _rate_limit(self):
        """控制请求速率"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_time = time.time()
    
    def get_citation_by_doi(self, doi: str, max_retries: int = 3) -> Tuple[Optional[int], str]:
        """
        通过DOI获取引用次数
        
        Returns:
            Tuple[Optional[int], str]: (引用数, 来源/错误信息)
        """
        if not doi or not isinstance(doi, str):
            return None, "invalid_doi"
        
        doi = doi.strip()
        if not doi.startswith('10.'):
            return None, "not_doi_format"
        
        cache_key = f"doi:{doi}"
        
        # 检查缓存 (7天有效期)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            cached_time = datetime.fromisoformat(cached.get('timestamp', '2000-01-01'))
            if datetime.now() - cached_time < timedelta(days=7):
                return cached.get('cited_by_count'), "doi_cached"
        
        # API请求
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                
                url = f"https://api.openalex.org/works/doi:{doi}"
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    count = data.get('cited_by_count')
                    
                    # 更新缓存
                    self.cache[cache_key] = {
                        'cited_by_count': count,
                        'timestamp': datetime.now().isoformat(),
                        'title': data.get('display_name', '')[:200],
                        'openalex_id': data.get('id', '')
                    }
                    
                    if len(self.cache) % 50 == 0:
                        self.save_cache()
                    
                    return count, "openalex_doi"
                    
                elif response.status_code == 429:
                    self.logger.warning(f"Rate limited, waiting {5 * (attempt + 1)}s...")
                    time.sleep(5 * (attempt + 1))
                    continue
                    
                elif response.status_code == 404:
                    self.cache[cache_key] = {
                        'cited_by_count': None,
                        'timestamp': datetime.now().isoformat(),
                        'error': 'not_found'
                    }
                    return None, "not_found"
                    
                else:
                    return None, f"api_error_{response.status_code}"
                    
            except Exception as e:
                self.logger.error(f"Error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
        
        return None, "max_retries_exceeded"
    
    def collect(self, datasets: pd.DataFrame, collections: pd.DataFrame) -> pd.DataFrame:
        """
        为所有Datasets收集引用数据
        
        Args:
            datasets: Datasets DataFrame
            collections: Collections DataFrame (包含DOI)
        
        Returns:
            pd.DataFrame: 带有引用数据的Datasets
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Citations Collection")
        self.logger.info("=" * 60)
        
        # 创建collection_id到DOI的映射
        doi_map = {}
        for _, row in collections.iterrows():
            coll_id = row['collection_id']
            doi = row.get('doi', '')
            if pd.notna(doi) and str(doi).strip().startswith('10.'):
                doi_map[coll_id] = str(doi).strip()
        
        self.logger.info(f"Collections with DOI: {len(doi_map)}")
        
        # 准备结果列
        df = datasets.copy()
        df['citation_count'] = None
        df['citation_source'] = None
        
        # 统计
        total = len(df)
        found = 0
        no_doi = 0
        not_found = 0
        errors = 0
        
        for idx, row in df.iterrows():
            coll_id = row['collection_id']
            doi = doi_map.get(coll_id)
            
            if not doi:
                no_doi += 1
                df.at[idx, 'citation_source'] = 'no_doi_available'
                continue
            
            # 查询引用
            count, source = self.get_citation_by_doi(doi)
            
            if count is not None:
                df.at[idx, 'citation_count'] = count
                df.at[idx, 'citation_source'] = source
                found += 1
            else:
                if source == "not_found":
                    not_found += 1
                else:
                    errors += 1
                df.at[idx, 'citation_source'] = source
            
            # 进度报告
            if (idx + 1) % 50 == 0 or idx == total - 1:
                progress = (idx + 1) / total * 100
                self.logger.info(
                    f"Progress: {idx + 1}/{total} ({progress:.1f}%) | "
                    f"Found: {found} | No DOI: {no_doi} | Not found: {not_found} | Errors: {errors}"
                )
        
        # 最终保存缓存
        self.save_cache()
        
        self.logger.info("=" * 60)
        self.logger.info("Citation Collection Complete!")
        self.logger.info(f"  Total: {total}")
        self.logger.info(f"  Found: {found}")
        self.logger.info(f"  No DOI: {no_doi}")
        self.logger.info(f"  Not found: {not_found}")
        self.logger.info("=" * 60)
        
        return df


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.utils import setup_logging
    
    logger = setup_logging()
    
    # 加载数据
    datasets = pd.read_csv("data/processed/datasets.csv")
    collections = pd.read_csv("data/processed/collections.csv")
    
    # 收集引用
    collector = CitationCollector()
    datasets_with_citations = collector.collect(datasets, collections)
    
    # 保存
    datasets_with_citations.to_csv(
        "data/processed/datasets_with_citations.csv", 
        index=False, 
        encoding='utf-8-sig'
    )
    
    print(f"\nCollected citations for {datasets_with_citations['citation_count'].notna().sum()} datasets")
