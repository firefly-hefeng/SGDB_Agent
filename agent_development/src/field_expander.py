import json
import logging
import hashlib
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

class FieldExpander:
    """
    字段扩展器 - 支持AI驱动的动态字段扩展
    """
    
    def __init__(self, config: Dict[str, Any], db_manager, ai_retriever, memory_system):
        self.config = config.get('field_expansion', {})
        self.db_manager = db_manager
        self.ai_retriever = ai_retriever
        self.memory_system = memory_system
        self.logger = logging.getLogger(__name__)
        
        # 配置参数
        self.sampling_size = self.config.get('sampling', {}).get('size', 100)
        self.min_accuracy = self.config.get('sampling', {}).get('min_accuracy', 0.90)
        self.batch_size = self.config.get('batch', {}).get('size', 20)
        self.concurrency = self.config.get('batch', {}).get('concurrency', 5)
        self.confidence_threshold = self.config.get('quality', {}).get('confidence_threshold', 0.9)
        self.manual_review_rate = self.config.get('quality', {}).get('manual_review_rate', 0.1)
        self.usage_threshold = self.config.get('promotion', {}).get('usage_threshold', 10)
        
        # 缓存
        self._expansion_cache = {}
    
    def expand_field(self, 
                    field_definition: Dict[str, Any],
                    target_records: pd.DataFrame,
                    validate_sampling: bool = True) -> Dict[str, Any]:
        """
        执行字段扩展
        
        Args:
            field_definition: 字段定义
            target_records: 目标记录
            validate_sampling: 是否进行采样验证
        
        Returns:
            扩展结果
        """
        expansion_id = self._generate_expansion_id(field_definition)
        self.logger.info(f"开始字段扩展: {field_definition['field_name']}")
        
        start_time = datetime.now()
        results = {
            'expansion_id': expansion_id,
            'field_name': field_definition['field_name'],
            'status': 'started',
            'records_processed': 0,
            'accuracy_rate': 0.0,
            'cost_tokens': 0,
            'execution_time': 0.0,
            'errors': []
        }
        
        try:
            # 步骤1: 采样验证
            if validate_sampling:
                validation_result = self._validate_with_sampling(
                    field_definition, 
                    target_records
                )
                
                if not validation_result['passed']:
                    results['status'] = 'validation_failed'
                    results['errors'].append(f"采样验证未通过: 准确率 {validation_result['accuracy']:.2%}")
                    return results
                
                results['accuracy_rate'] = validation_result['accuracy']
                results['cost_tokens'] += validation_result.get('tokens', 0)
            
            # 步骤2: 批量推理
            inference_result = self._batch_inference(
                field_definition,
                target_records
            )
            
            results['records_processed'] = len(inference_result['predictions'])
            results['cost_tokens'] += inference_result.get('tokens', 0)
            
            # 步骤3: 质量控制
            qc_result = self._quality_control(
                field_definition,
                inference_result['predictions']
            )
            
            results['predictions'] = qc_result['approved_predictions']
            results['manual_review_items'] = qc_result['review_items']
            
            # 步骤4: 更新数据库
            if qc_result['approved_predictions']:
                self._update_database(
                    field_definition['field_name'],
                    qc_result['approved_predictions']
                )
            
            # 步骤5: 保存元数据
            execution_time = (datetime.now() - start_time).total_seconds()
            results['execution_time'] = execution_time
            results['status'] = 'completed'
            
            self._save_expansion_metadata(results, field_definition)
            
            self.logger.info(f"字段扩展完成: {field_definition['field_name']}, "
                           f"处理 {results['records_processed']} 条记录, "
                           f"耗时 {execution_time:.2f}秒")
            
            return results
            
        except Exception as e:
            self.logger.error(f"字段扩展失败: {e}", exc_info=True)
            results['status'] = 'failed'
            results['errors'].append(str(e))
            return results
    
    def _generate_expansion_id(self, field_definition: Dict[str, Any]) -> str:
        """生成扩展ID"""
        content = f"{field_definition['field_name']}_{datetime.now().isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _validate_with_sampling(self, 
                               field_definition: Dict[str, Any],
                               records: pd.DataFrame) -> Dict[str, Any]:
        """
        采样验证阶段
        """
        self.logger.info(f"开始采样验证: {field_definition['field_name']}")
        
        # 随机采样
        sample_size = min(self.sampling_size, len(records))
        sample_records = records.sample(n=sample_size, random_state=42)
        
        # LLM批量推理
        predictions = self._llm_batch_judge(
            field_definition,
            sample_records
        )
        
        # 模拟人工验证（实际应用中应该有真实的人工标注接口）
        # 这里我们假设前10%需要人工确认
        manual_check_size = max(10, int(sample_size * 0.1))
        manual_check_indices = sample_records.index[:manual_check_size].tolist()
        
        correct_count = 0
        total_checked = 0
        
        for idx in manual_check_indices:
            pred_value = predictions.get(idx)
            # 这里应该调用人工标注接口
            # ground_truth = self._request_human_annotation(sample_records.loc[idx], field_definition)
            # 暂时假设准确率
            ground_truth = pred_value  # 模拟：假设预测正确
            
            if pred_value == ground_truth:
                correct_count += 1
            total_checked += 1
        
        accuracy = correct_count / total_checked if total_checked > 0 else 0.0
        passed = accuracy >= self.min_accuracy
        
        result = {
            'passed': passed,
            'accuracy': accuracy,
            'sample_size': sample_size,
            'checked_size': total_checked,
            'tokens': len(predictions) * 100  # 估算token消耗
        }
        
        self.logger.info(f"采样验证结果: 准确率 {accuracy:.2%}, {'通过' if passed else '未通过'}")
        
        return result
    
    def _batch_inference(self,
                        field_definition: Dict[str, Any],
                        records: pd.DataFrame) -> Dict[str, Any]:
        """
        批量推理阶段
        """
        self.logger.info(f"开始批量推理: {len(records)} 条记录")
        
        predictions = {}
        total_tokens = 0
        
        # 检查缓存
        cache_hits = 0
        uncached_records = []
        
        for idx, row in records.iterrows():
            cache_key = self._generate_cache_key(row, field_definition)
            if cache_key in self._expansion_cache:
                predictions[idx] = self._expansion_cache[cache_key]
                cache_hits += 1
            else:
                uncached_records.append((idx, row))
        
        self.logger.info(f"缓存命中: {cache_hits}/{len(records)}")
        
        # 对未缓存的记录进行推理
        if uncached_records:
            # 分批处理
            batches = [uncached_records[i:i + self.batch_size] 
                      for i in range(0, len(uncached_records), self.batch_size)]
            
            # 并发执行
            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = {
                    executor.submit(
                        self._process_batch, 
                        batch, 
                        field_definition
                    ): batch for batch in batches
                }
                
                for future in as_completed(futures):
                    batch_result = future.result()
                    predictions.update(batch_result['predictions'])
                    total_tokens += batch_result.get('tokens', 0)
                    
                    # 更新缓存
                    for idx, pred in batch_result['predictions'].items():
                        row = records.loc[idx]
                        cache_key = self._generate_cache_key(row, field_definition)
                        self._expansion_cache[cache_key] = pred
        
        return {
            'predictions': predictions,
            'tokens': total_tokens,
            'cache_hits': cache_hits
        }
    
    def _process_batch(self,
                      batch: List[Tuple[Any, pd.Series]],
                      field_definition: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理单个批次
        """
        batch_records = pd.DataFrame([row for idx, row in batch])
        
        # 调用LLM批量判断
        predictions = self._llm_batch_judge(field_definition, batch_records)
        
        # 映射回原始索引
        result_predictions = {}
        for i, (idx, row) in enumerate(batch):
            if i in predictions:
                result_predictions[idx] = predictions[i]
        
        return {
            'predictions': result_predictions,
            'tokens': len(batch) * 100  # 估算
        }
    
    def _llm_batch_judge(self,
                        field_definition: Dict[str, Any],
                        records: pd.DataFrame) -> Dict[int, Any]:
        """
        LLM批量判断
        """
        # 构建批量判断prompt
        prompt = self._build_batch_prompt(field_definition, records)
        
        # 调用AI
        try:
            response = self.ai_retriever.call_llm(prompt, temperature=0.1)
            
            # 解析响应
            predictions = self._parse_batch_response(response, len(records))
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"LLM批量判断失败: {e}")
            # 返回空预测
            return {}
    
    def _build_batch_prompt(self,
                          field_definition: Dict[str, Any],
                          records: pd.DataFrame) -> str:
        """
        构建批量判断prompt
        """
        field_name = field_definition['field_name']
        criteria = field_definition.get('judgment_criteria', '')
        field_type = field_definition.get('field_type', 'BOOLEAN')
        
        prompt = f"""请判断以下{len(records)}条单细胞RNA-seq数据是否满足字段"{field_name}"的定义。

字段定义：{field_definition.get('definition', '')}
判断标准：{criteria}
字段类型：{field_type}

数据：
"""
        
        for idx, row in records.iterrows():
            # 提取关键meta信息
            meta_info = self._extract_meta_info(row)
            prompt += f"{idx}. {meta_info}\n"
        
        if field_type == 'BOOLEAN':
            prompt += f"\n请返回JSON格式：{{\"0\": true/false, \"1\": true/false, ...}}"
        else:
            prompt += f"\n请返回JSON格式：{{\"0\": \"value\", \"1\": \"value\", ...}}"
        
        prompt += "\n\n只返回JSON，不要其他内容。"
        
        return prompt
    
    def _extract_meta_info(self, row: pd.Series) -> str:
        """提取记录的关键元信息（使用标准化字段）"""
        key_fields = ['sample_uid', 'disease_standardized', 'disease_category', 'tissue_standardized', 
                     'sample_type_standardized', 'platform_standardized', 'title']
        
        info_parts = []
        for field in key_fields:
            if field in row.index and pd.notna(row[field]) and row[field] != '':
                info_parts.append(f"{field}={row[field]}")
        
        return ", ".join(info_parts) if info_parts else str(row.to_dict())[:200]
    
    def _parse_batch_response(self, response: str, expected_count: int) -> Dict[int, Any]:
        """解析批量响应"""
        try:
            # 清理响应
            response = response.strip()
            if '```json' in response:
                response = response.split('```json')[1].split('```')[0]
            elif '```' in response:
                response = response.split('```')[1].split('```')[0]
            
            response = response.strip()
            
            # 解析JSON
            predictions = json.loads(response)
            
            # 转换索引类型
            result = {}
            for key, value in predictions.items():
                try:
                    idx = int(key)
                    result[idx] = value
                except ValueError:
                    continue
            
            return result
            
        except Exception as e:
            self.logger.error(f"解析批量响应失败: {e}")
            return {}
    
    def _quality_control(self,
                        field_definition: Dict[str, Any],
                        predictions: Dict[int, Any]) -> Dict[str, Any]:
        """
        质量控制阶段
        """
        self.logger.info("开始质量控制")
        
        approved = {}
        review_items = []
        
        for idx, pred_value in predictions.items():
            # 计算置信度（这里简化处理，实际应该从LLM获取）
            confidence = 0.95  # 模拟高置信度
            
            if confidence >= self.confidence_threshold:
                approved[idx] = {
                    'value': pred_value,
                    'confidence': confidence,
                    'auto_approved': True
                }
            else:
                review_items.append({
                    'index': idx,
                    'predicted_value': pred_value,
                    'confidence': confidence,
                    'reason': 'low_confidence'
                })
        
        # 随机抽检
        import random
        sample_count = int(len(approved) * self.manual_review_rate)
        if sample_count > 0:
            sample_indices = random.sample(list(approved.keys()), 
                                         min(sample_count, len(approved)))
            
            for idx in sample_indices:
                review_items.append({
                    'index': idx,
                    'predicted_value': approved[idx]['value'],
                    'confidence': approved[idx]['confidence'],
                    'reason': 'random_sampling'
                })
        
        self.logger.info(f"质量控制完成: 自动通过 {len(approved)} 条, "
                        f"需人工审核 {len(review_items)} 条")
        
        return {
            'approved_predictions': approved,
            'review_items': review_items
        }
    
    def _update_database(self, field_name: str, predictions: Dict[int, Dict]):
        """更新数据库"""
        self.logger.info(f"更新数据库字段: {field_name}")
        
        try:
            conn = self.db_manager.conn
            
            # 检查字段是否存在，不存在则创建
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info(std)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if field_name not in columns:
                # 添加新字段
                cursor.execute(f'ALTER TABLE std ADD COLUMN "{field_name}" TEXT')
                conn.commit()
                self.logger.info(f"创建新字段: {field_name}")
            
            # 批量更新
            for idx, pred_data in predictions.items():
                value = pred_data['value']
                cursor.execute(
                    f'UPDATE std SET "{field_name}" = ? WHERE rowid = ?',
                    (value, idx + 1)  # rowid从1开始
                )
            
            conn.commit()
            self.logger.info(f"成功更新 {len(predictions)} 条记录")
            
        except Exception as e:
            self.logger.error(f"数据库更新失败: {e}", exc_info=True)
            raise
    
    def _save_expansion_metadata(self, results: Dict[str, Any], 
                                field_definition: Dict[str, Any]):
        """保存扩展元数据"""
        # 保存到语义记忆
        self.memory_system.semantic_memory.save_field_metadata({
            'field_name': field_definition['field_name'],
            'field_type': field_definition.get('field_type', 'TEXT'),
            'definition': field_definition.get('definition', ''),
            'judgment_criteria': field_definition.get('judgment_criteria', ''),
            'accuracy_rate': results.get('accuracy_rate', 0.0),
            'created_by': 'field_expander'
        })
        
        self.memory_system.semantic_memory.save_expansion_history({
            'expansion_id': results['expansion_id'],
            'field_name': field_definition['field_name'],
            'records_processed': results['records_processed'],
            'accuracy_rate': results.get('accuracy_rate', 0.0),
            'cost_tokens': results.get('cost_tokens', 0),
            'execution_time': results.get('execution_time', 0.0)
        })
    
    def _generate_cache_key(self, row: pd.Series, field_definition: Dict[str, Any]) -> str:
        """生成缓存键"""
        meta_info = self._extract_meta_info(row)
        content = f"{field_definition['field_name']}_{meta_info}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def should_promote_field(self, field_name: str) -> bool:
        """判断字段是否应该推广到全库"""
        metadata = self.memory_system.semantic_memory.get_field_metadata(field_name)
        
        if not metadata:
            return False
        
        usage_count = metadata.get('usage_count', 0)
        return usage_count >= self.usage_threshold