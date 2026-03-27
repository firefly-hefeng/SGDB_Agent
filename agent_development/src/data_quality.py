"""
数据质量评估模块
提供数据库质量检查和报告功能
"""

import sqlite3
import pandas as pd
from typing import Dict, List, Any
from datetime import datetime

class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self, db_path='data/scrnaseq.db', table='std'):
        self.db_path = db_path
        self.table = table
        self.conn = sqlite3.connect(db_path)
        self.report = {}
        
    def check_all(self) -> Dict[str, Any]:
        """执行所有质量检查"""
        self.report = {
            'timestamp': datetime.now().isoformat(),
            'database': self.db_path,
            'table': self.table,
            'summary': {},
            'field_quality': {},
            'recommendations': []
        }
        
        # 1. 基本信息
        total = self.conn.execute(f'SELECT COUNT(*) FROM {self.table}').fetchone()[0]
        self.report['summary']['total_records'] = total
        
        # 2. 检查各字段质量
        self._check_field_quality()
        
        # 3. 检查数据一致性
        self._check_consistency()
        
        # 4. 生成建议
        self._generate_recommendations()
        
        return self.report
    
    def _check_field_quality(self):
        """检查字段数据质量"""
        
        # 定义关键字段及其权重
        key_fields = {
            'disease_clean': {'weight': 5, 'type': 'categorical'},
            'tissue_clean': {'weight': 4, 'type': 'categorical'},
            'platform_clean': {'weight': 3, 'type': 'categorical'},
            'source_database': {'weight': 3, 'type': 'categorical'},
            'matrix_open': {'weight': 2, 'type': 'boolean'},
            'title': {'weight': 2, 'type': 'text'},
        }
        
        total = self.report['summary']['total_records']
        
        for field, config in key_fields.items():
            try:
                # 计算完整度
                non_empty = self.conn.execute(
                    f'SELECT COUNT(*) FROM {self.table} WHERE "{field}" IS NOT NULL AND "{field}" != ""'
                ).fetchone()[0]
                
                completeness = non_empty / total if total > 0 else 0
                
                # 计算唯一值数
                unique = self.conn.execute(
                    f'SELECT COUNT(DISTINCT "{field}") FROM {self.table}'
                ).fetchone()[0]
                
                # 质量评分
                quality_score = completeness * config['weight']
                
                self.report['field_quality'][field] = {
                    'completeness': round(completeness * 100, 2),
                    'non_empty': non_empty,
                    'unique_values': unique,
                    'weight': config['weight'],
                    'quality_score': round(quality_score, 2),
                    'status': 'Good' if completeness > 0.8 else 'Fair' if completeness > 0.5 else 'Poor'
                }
            except Exception as e:
                self.report['field_quality'][field] = {
                    'error': str(e),
                    'status': 'Error'
                }
        
        # 计算总体质量分数
        total_score = sum(f.get('quality_score', 0) for f in self.report['field_quality'].values())
        max_score = sum(f['weight'] for f in key_fields.values())
        self.report['summary']['overall_score'] = round((total_score / max_score) * 100, 2) if max_score > 0 else 0
        self.report['summary']['quality_level'] = self._get_quality_level(self.report['summary']['overall_score'])
    
    def _check_consistency(self):
        """检查数据一致性"""
        issues = []
        
        # 检查matrix_open和raw_open的一致性
        try:
            open_both = self.conn.execute(
                f'SELECT COUNT(*) FROM {self.table} WHERE matrix_open=1 AND raw_open=1'
            ).fetchone()[0]
            
            matrix_only = self.conn.execute(
                f'SELECT COUNT(*) FROM {self.table} WHERE matrix_open=1 AND (raw_open=0 OR raw_open IS NULL)'
            ).fetchone()[0]
            
            self.report['summary']['data_availability'] = {
                'matrix_and_raw': open_both,
                'matrix_only': matrix_only
            }
        except:
            pass
        
        # 检查日期格式
        try:
            bad_dates = self.conn.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE publication_date LIKE '%/%'"
            ).fetchone()[0]
            
            if bad_dates > 0:
                issues.append(f"发现{bad_dates}条记录的日期格式不正确（使用/分隔）")
        except:
            pass
        
        self.report['consistency_issues'] = issues
    
    def _generate_recommendations(self):
        """生成改进建议"""
        recommendations = []
        
        # 基于字段质量生成建议
        for field, stats in self.report['field_quality'].items():
            if stats.get('status') == 'Poor':
                completeness = stats.get('completeness', 0)
                if completeness < 20:
                    recommendations.append(f"🔴 {field}: 完整度仅{completeness}%，建议重新生成或填充数据")
                else:
                    recommendations.append(f"🟡 {field}: 完整度{completeness}%，建议补充缺失数据")
            elif stats.get('status') == 'Fair':
                recommendations.append(f"🟢 {field}: 完整度{stats.get('completeness')}%，可以进一步优化")
        
        # 基于总体质量生成建议
        overall = self.report['summary'].get('overall_score', 0)
        if overall < 60:
            recommendations.append("📊 总体数据质量较低，建议优先处理关键字段（疾病、组织、平台）")
        elif overall < 80:
            recommendations.append("📊 数据质量中等，建议完善次要字段信息")
        else:
            recommendations.append("✅ 数据质量良好，可以保持当前水平")
        
        self.report['recommendations'] = recommendations
    
    def _get_quality_level(self, score: float) -> str:
        """根据分数获取质量等级"""
        if score >= 80:
            return 'Excellent'
        elif score >= 60:
            return 'Good'
        elif score >= 40:
            return 'Fair'
        else:
            return 'Poor'
    
    def print_report(self):
        """打印质量报告"""
        print("=" * 80)
        print("📊 数据质量评估报告")
        print("=" * 80)
        
        print(f"\n🗄️  数据库: {self.report['database']}")
        print(f"📋 表: {self.report['table']}")
        print(f"📊 总记录数: {self.report['summary']['total_records']:,}")
        
        print(f"\n⭐ 总体质量评分: {self.report['summary'].get('overall_score', 0)}/100")
        print(f"🏆 质量等级: {self.report['summary'].get('quality_level', 'Unknown')}")
        
        print("\n" + "-" * 80)
        print("📋 字段质量详情")
        print("-" * 80)
        
        for field, stats in self.report['field_quality'].items():
            if 'error' in stats:
                print(f"❌ {field}: 检查失败 - {stats['error']}")
            else:
                status_icon = {'Good': '✅', 'Fair': '🟡', 'Poor': '🔴'}.get(stats['status'], '❓')
                print(f"{status_icon} {field:<25} 完整度: {stats['completeness']:>6}%  "
                      f"唯一值: {stats['unique_values']:>6}  状态: {stats['status']}")
        
        if self.report.get('consistency_issues'):
            print("\n" + "-" * 80)
            print("⚠️  数据一致性问题")
            print("-" * 80)
            for issue in self.report['consistency_issues']:
                print(f"  • {issue}")
        
        print("\n" + "-" * 80)
        print("💡 改进建议")
        print("-" * 80)
        for rec in self.report['recommendations']:
            print(f"  {rec}")
        
        print("\n" + "=" * 80)
    
    def save_report(self, filepath='data/quality_report.json'):
        """保存报告到文件"""
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        print(f"\n📄 报告已保存: {filepath}")
    
    def close(self):
        """关闭连接"""
        self.conn.close()

if __name__ == '__main__':
    checker = DataQualityChecker()
    checker.check_all()
    checker.print_report()
    checker.save_report()
    checker.close()
