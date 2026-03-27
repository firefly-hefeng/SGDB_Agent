"""
SCDB-Agent Web服务
提供RESTful API和WebSocket支持
"""

import os
import sys
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime
from functools import wraps
from threading import Thread

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 切换到项目根目录（确保数据库路径正确）
os.chdir(project_root)

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from src.config_manager import ConfigManager
from src.query_engine import QueryEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建Flask应用
app = Flask(__name__, 
    template_folder='templates',
    static_folder='static'
)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['JSON_AS_ASCII'] = False

# 启用CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# 初始化SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局查询引擎实例
query_engine = None


def get_query_engine():
    """获取或初始化查询引擎"""
    global query_engine
    if query_engine is None:
        config_path = project_root / 'config' / 'config.yaml'
        config = ConfigManager(str(config_path))
        query_engine = QueryEngine(config)
        query_engine.initialize()
        logger.info("查询引擎初始化完成")
    return query_engine


# ==================== API路由 ====================

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'version': '2.0.0'
    })


@app.route('/api/schema')
def get_schema():
    """获取数据库Schema"""
    try:
        engine = get_query_engine()
        schema = engine.db_manager.get_schema_info()
        
        # 获取字段类型信息
        field_types = engine.db_manager.field_types
        
        return jsonify({
            'success': True,
            'data': {
                'fields': schema,
                'field_types': field_types,
                'total_fields': len(field_types)
            }
        })
    except Exception as e:
        logger.error(f"获取Schema失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/query', methods=['POST'])
def execute_query():
    """执行查询"""
    try:
        data = request.get_json()
        query_text = data.get('query', '').strip()
        session_id = data.get('session_id') or str(uuid.uuid4())
        limit = data.get('limit', 20)
        offset = data.get('offset', 0)
        use_ai = data.get('use_ai', True)
        
        if not query_text:
            return jsonify({'success': False, 'error': '查询内容不能为空'}), 400
        
        # 限制单次最大返回数，避免内存问题
        if limit > 1000:
            limit = 1000
        
        engine = get_query_engine()
        
        # 执行查询
        result = engine.execute_query(
            query_text,
            session_id=session_id,
            limit=limit,
            offset=offset,
            use_ai=use_ai
        )
        
        # 转换结果为JSON可序列化格式
        response_data = {
            'success': True,
            'data': {
                'query': result['query'],
                'session_id': session_id,
                'total_count': result['total_count'],
                'returned_count': result['returned_count'],
                'limit': limit,
                'offset': offset,
                'has_more': result['total_count'] > (offset + limit),
                'execution_time': result['execution_time'],
                'intent': result.get('intent', ''),
                'keywords': result.get('keywords', []),
                'explanation': result.get('explanation', ''),
                'suggestions': result.get('suggestions', []),
                'filters': result.get('filters', {}),
                'results': result['results'].to_dict('records') if not result['results'].empty else [],
                'columns': list(result['results'].columns) if not result['results'].empty else []
            }
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"查询执行失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/query/history', methods=['GET'])
def get_query_history():
    """获取查询历史"""
    try:
        session_id = request.args.get('session_id')
        if not session_id:
            return jsonify({'success': False, 'error': '缺少session_id'}), 400
        
        engine = get_query_engine()
        context = engine.get_session_context(session_id)
        
        return jsonify({
            'success': True,
            'data': {
                'session_id': session_id,
                'recent_queries': context.get('recent_queries', []),
                'has_current_results': context.get('has_current_results', False)
            }
        })
    except Exception as e:
        logger.error(f"获取查询历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/statistics/<field>')
def get_statistics(field):
    """获取字段统计"""
    try:
        top_n = request.args.get('top_n', 20, type=int)
        
        engine = get_query_engine()
        stats = engine.get_statistics(field, top_n=top_n)
        
        return jsonify({
            'success': True,
            'data': {
                'field': field,
                'statistics': stats.to_dict('records') if not stats.empty else [],
                'total_unique': len(stats) if not stats.empty else 0
            }
        })
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 下载相关API ====================

@app.route('/api/download/preview', methods=['POST'])
def download_preview():
    """预览可下载数据"""
    try:
        data = request.get_json()
        records = data.get('records', [])
        
        if not records:
            return jsonify({'success': False, 'error': '没有记录数据'}), 400
        
        import pandas as pd
        df = pd.DataFrame(records)
        
        engine = get_query_engine()
        preview = engine.get_download_preview(df, max_preview=10)
        
        return jsonify({
            'success': True,
            'data': preview
        })
    except Exception as e:
        logger.error(f"预览失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download/tasks', methods=['POST'])
def create_download_tasks():
    """创建下载任务"""
    try:
        data = request.get_json()
        records = data.get('records', [])
        file_types = data.get('file_types', ['matrix'])
        output_dir = data.get('output_dir')
        
        if not records:
            return jsonify({'success': False, 'error': '没有记录数据'}), 400
        
        import pandas as pd
        df = pd.DataFrame(records)
        
        engine = get_query_engine()
        tasks = engine.create_download_tasks(df, file_types, output_dir)
        
        return jsonify({
            'success': True,
            'data': {
                'total_tasks': len(tasks),
                'tasks': [t.to_dict() for t in tasks]
            }
        })
    except Exception as e:
        logger.error(f"创建任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download/start', methods=['POST'])
def start_download():
    """开始下载"""
    try:
        data = request.get_json()
        task_ids = data.get('task_ids', [])
        
        if not task_ids:
            return jsonify({'success': False, 'error': '没有指定任务'}), 400
        
        engine = get_query_engine()
        
        # 获取任务
        tasks = []
        for task_id in task_ids:
            task = engine.data_downloader.get_task_status(task_id)
            if task:
                tasks.append(task)
        
        if not tasks:
            return jsonify({'success': False, 'error': '找不到指定任务'}), 404
        
        # 在后台线程中执行下载
        def download_progress_callback(task_id, progress, speed):
            socketio.emit('download_progress', {
                'task_id': task_id,
                'progress': progress,
                'speed': speed
            })
        
        def download_completion_callback(task_id, success):
            socketio.emit('download_complete', {
                'task_id': task_id,
                'success': success
            })
        
        # 启动下载（异步）
        def do_download():
            stats = engine.start_download(tasks, download_progress_callback)
            socketio.emit('download_batch_complete', {
                'stats': stats
            })
        
        thread = Thread(target=do_download)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'data': {
                'message': '下载已启动',
                'total_tasks': len(tasks)
            }
        })
    except Exception as e:
        logger.error(f"启动下载失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download/script', methods=['POST'])
def generate_download_script():
    """生成下载脚本"""
    try:
        data = request.get_json()
        records = data.get('records', [])
        file_types = data.get('file_types', ['matrix'])
        
        if not records:
            return jsonify({'success': False, 'error': '没有记录数据'}), 400
        
        import pandas as pd
        df = pd.DataFrame(records)
        
        engine = get_query_engine()
        script_path = engine.generate_download_script(df, file_types)
        
        # 读取脚本内容
        script_content = Path(script_path).read_text()
        
        return jsonify({
            'success': True,
            'data': {
                'script_path': str(script_path),
                'script_content': script_content,
                'filename': Path(script_path).name
            }
        })
    except Exception as e:
        logger.error(f"生成脚本失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download/tasks')
def get_download_tasks():
    """获取所有下载任务"""
    try:
        engine = get_query_engine()
        tasks = engine.data_downloader.get_all_tasks()
        
        return jsonify({
            'success': True,
            'data': {
                'tasks': [t.to_dict() for t in tasks],
                'total': len(tasks)
            }
        })
    except Exception as e:
        logger.error(f"获取任务失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/export/results', methods=['POST'])
def export_query_results():
    """导出查询结果为CSV/Excel"""
    try:
        data = request.get_json()
        query_filters = data.get('filters', {})
        format_type = data.get('format', 'csv')  # csv, excel, json
        max_records = data.get('max_records', 10000)  # 默认最多导出1万条
        
        engine = get_query_engine()
        
        # 限制导出数量，避免内存问题
        if max_records > 50000:
            max_records = 50000
        
        # 执行查询获取所有结果
        results = engine.db_manager.search(query_filters, limit=max_records, offset=0)
        
        if results.empty:
            return jsonify({'success': False, 'error': '没有数据可导出'}), 400
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"query_results_{timestamp}"
        
        if format_type == 'csv':
            # 导出为CSV
            output_path = Path('results') / f"{filename}.csv"
            output_path.parent.mkdir(exist_ok=True)
            results.to_csv(output_path, index=False, encoding='utf-8-sig')
            
            return jsonify({
                'success': True,
                'data': {
                    'filename': f"{filename}.csv",
                    'filepath': str(output_path),
                    'record_count': len(results),
                    'format': 'csv',
                    'download_url': f'/api/download/file?path={output_path}'
                }
            })
            
        elif format_type == 'excel':
            # 导出为Excel
            output_path = Path('results') / f"{filename}.xlsx"
            output_path.parent.mkdir(exist_ok=True)
            
            # 如果数据量大，需要分批写入
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                results.to_excel(writer, index=False, sheet_name='Results')
            
            return jsonify({
                'success': True,
                'data': {
                    'filename': f"{filename}.xlsx",
                    'filepath': str(output_path),
                    'record_count': len(results),
                    'format': 'excel'
                }
            })
            
        elif format_type == 'json':
            # 返回JSON格式数据
            return jsonify({
                'success': True,
                'data': {
                    'records': results.to_dict('records'),
                    'record_count': len(results),
                    'format': 'json'
                }
            })
        else:
            return jsonify({'success': False, 'error': '不支持的格式'}), 400
            
    except Exception as e:
        logger.error(f"导出失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/query/count', methods=['POST'])
def get_query_count():
    """仅获取查询结果数量（用于大数据量预览）"""
    try:
        data = request.get_json()
        query_filters = data.get('filters', {})
        
        engine = get_query_engine()
        count = engine.db_manager.count_results(query_filters)
        
        return jsonify({
            'success': True,
            'data': {
                'count': count,
                'formatted': f"{count:,}"
            }
        })
    except Exception as e:
        logger.error(f"计数失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== 字段扩展API ====================

@app.route('/api/field/expand', methods=['POST'])
def expand_field():
    """扩展字段"""
    try:
        data = request.get_json()
        field_name = data.get('field_name')
        definition = data.get('definition')
        criteria = data.get('criteria')
        session_id = data.get('session_id')
        
        if not field_name or not definition:
            return jsonify({'success': False, 'error': '字段名和定义不能为空'}), 400
        
        engine = get_query_engine()
        
        # 构建字段定义
        field_definition = {
            'field_name': field_name,
            'field_type': 'BOOLEAN',
            'definition': definition,
            'judgment_criteria': criteria or definition
        }
        
        # 获取当前会话的过滤条件
        context = engine.get_session_context(session_id) if session_id else {}
        
        # 这里简化处理，实际应该获取历史filters
        filters = {}
        
        # 执行字段扩展
        result = engine.expand_field_for_query(field_definition, filters)
        
        return jsonify({
            'success': result['status'] == 'completed',
            'data': result
        })
    except Exception as e:
        logger.error(f"字段扩展失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== WebSocket事件 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    logger.info(f"客户端已连接: {request.sid}")
    emit('connected', {'message': '连接成功', 'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    logger.info(f"客户端已断开: {request.sid}")


@socketio.on('query_stream')
def handle_query_stream(data):
    """流式查询"""
    try:
        query_text = data.get('query', '')
        session_id = data.get('session_id') or str(uuid.uuid4())
        
        engine = get_query_engine()
        
        # 发送开始事件
        emit('query_start', {'session_id': session_id})
        
        # 执行查询
        result = engine.execute_query(
            query_text,
            session_id=session_id,
            limit=20
        )
        
        # 发送结果
        emit('query_result', {
            'session_id': session_id,
            'total_count': result['total_count'],
            'execution_time': result['execution_time'],
            'results': result['results'].to_dict('records') if not result['results'].empty else []
        })
        
    except Exception as e:
        emit('query_error', {'error': str(e)})


# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': '资源不存在'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': '服务器内部错误'}), 500


# ==================== 应用启动 ====================

def init_app():
    """初始化应用"""
    global query_engine
    try:
        # 预初始化查询引擎
        query_engine = get_query_engine()
        logger.info("Web服务初始化完成")
    except Exception as e:
        logger.error(f"初始化失败: {e}")
        raise


if __name__ == '__main__':
    init_app()
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=False
    )
