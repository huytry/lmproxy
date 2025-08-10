import asyncio
import json
import logging
import uuid
import re
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
import signal
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse
import typing
import os
import traceback
from datetime import datetime, timedelta
from collections import defaultdict, deque
import threading
from pathlib import Path
import aiohttp  # 如果用于发送HTTP告警，需要先 pip install aiohttp
import gzip
import shutil
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# --- Configuration ---
# 配置项集中管理
class Config:
    # 日志配置
    LOG_DIR = Path("logs")
    REQUEST_LOG_FILE = "requests.jsonl"
    ERROR_LOG_FILE = "errors.jsonl"
    MAX_LOG_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_LOG_FILES = 50  # 保留最多10个历史日志文件
    
    # 服务器配置
    HOST = "0.0.0.0"
    PORT = 9080
    
    # 请求配置
    BACKPRESSURE_QUEUE_SIZE = 5
    REQUEST_TIMEOUT_SECONDS = 180
    MAX_CONCURRENT_REQUESTS = 20  # 最大并发请求数
    
    # 监控配置
    STATS_UPDATE_INTERVAL = 5  # 统计更新间隔（秒）
    CLEANUP_INTERVAL = 300  # 清理间隔（秒）
    
    # 内存限制
    MAX_ACTIVE_REQUESTS = 100
    MAX_LOG_MEMORY_ITEMS = 1000  # 内存中保留的最大日志条目
    MAX_REQUEST_DETAILS = 500  # 保留的请求详情数量

    # 网络配置
    MANUAL_IP = None  # 手动指定IP地址，如 "192.168.0.1"

# 确保日志目录存在
Config.LOG_DIR.mkdir(exist_ok=True)

# --- 动态配置管理 ---
class ConfigManager:
    """管理可动态修改的配置"""

    def __init__(self):
        self.config_file = Config.LOG_DIR / "config.json"
        self.dynamic_config = {
            "network": {
                "manual_ip": Config.MANUAL_IP,
                "port": Config.PORT,
                "auto_detect_ip": True
            },
            "request": {
                "timeout_seconds": Config.REQUEST_TIMEOUT_SECONDS,
                "max_concurrent_requests": Config.MAX_CONCURRENT_REQUESTS,
                "backpressure_queue_size": Config.BACKPRESSURE_QUEUE_SIZE
            },
            "monitoring": {
                "error_rate_threshold": 0.1,
                "response_time_threshold": 30,
                "active_requests_threshold": 50,
                "cleanup_interval": Config.CLEANUP_INTERVAL
            },
            "quick_links": [
                {"name": "监控面板", "url": "/monitor", "icon": "📊"},
                {"name": "健康检查", "url": "/api/health/detailed", "icon": "🏥"},
                {"name": "Prometheus", "url": "/metrics", "icon": "📈"},
                {"name": "API文档", "url": "/monitor#api-docs", "icon": "📚"}
            ]
        }
        self.load_config()

    def load_config(self):
        """从文件加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    # 深度合并配置
                    self._deep_merge(self.dynamic_config, saved_config)
                    logging.info("已加载保存的配置")
            except Exception as e:
                logging.error(f"加载配置文件失败: {e}")

    def save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.dynamic_config, f, ensure_ascii=False, indent=2)
            logging.info("配置已保存")
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")

    def _deep_merge(self, target, source):
        """深度合并字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def get(self, path: str, default=None):
        """获取配置值，支持点号路径如 'network.manual_ip'"""
        keys = path.split('.')
        value = self.dynamic_config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, path: str, value):
        """设置配置值"""
        keys = path.split('.')
        target = self.dynamic_config
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value
        self.save_config()

    def get_display_ip(self):
        """获取显示用的IP地址"""
        if self.get('network.manual_ip'):
            return self.get('network.manual_ip')
        elif self.get('network.auto_detect_ip', True):
            return get_local_ip()
        else:
            return "localhost"


# 创建全局配置管理器
config_manager = ConfigManager()


def get_local_ip():
    """获取本机局域网IP地址"""
    import socket
    import platform

    # 检查是否有config_manager并且有手动配置的IP
    if 'config_manager' in globals():
        manual_ip = config_manager.get('network.manual_ip')
        if manual_ip:
            return manual_ip

    # 获取所有可能的IP地址
    ips = []

    try:
        # 方法1：获取所有网络接口的IP
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]

        # 过滤出局域网IP（排除虚拟网卡）
        for ip in all_ips:
            # 排除回环地址和Clash虚拟网卡地址
            if not ip.startswith('127.') and not ip.startswith('198.18.'):
                # 检查是否是私有IP地址
                parts = ip.split('.')
                if len(parts) == 4:
                    first_octet = int(parts[0])
                    second_octet = int(parts[1])

                    # 检查是否是私有IP范围
                    # 10.0.0.0 - 10.255.255.255
                    # 172.16.0.0 - 172.31.255.255
                    # 192.168.0.0 - 192.168.255.255
                    if (first_octet == 10 or
                            (first_octet == 172 and 16 <= second_octet <= 31) or
                            (first_octet == 192 and second_octet == 168)):
                        ips.append(ip)

        # 如果找到了局域网IP，返回第一个（通常是最主要的）
        if ips:
            # 优先返回192.168开头的地址
            for ip in ips:
                if ip.startswith('192.168.'):
                    return ip
            return ips[0]

        # 方法2：如果上面的方法失败，尝试连接外部服务器的方法
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))  # 使用阿里DNS而不是Google
        local_ip = s.getsockname()[0]
        s.close()

        # 再次检查是否是Clash地址
        if not local_ip.startswith('198.18.'):
            return local_ip

    except Exception as e:
        logging.warning(f"获取IP地址失败: {e}")

    # 如果所有方法都失败，返回localhost
    return "127.0.0.1"

# 配置Python日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        logging.FileHandler(Config.LOG_DIR / "server.log", encoding='utf-8')  # 文件输出
    ]
)

# --- Prometheus Metrics ---
# 请求计数器
request_count = Counter(
    'lmarena_requests_total', 
    'Total number of requests',
    ['model', 'status', 'type']
)

# 请求持续时间直方图
request_duration = Histogram(
    'lmarena_request_duration_seconds',
    'Request duration in seconds',
    ['model', 'type'],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf"))
)

# 活跃请求数量
active_requests_gauge = Gauge(
    'lmarena_active_requests',
    'Number of active requests'
)

# Token使用计数器
token_usage = Counter(
    'lmarena_tokens_total',
    'Total number of tokens used',
    ['model', 'token_type']  # token_type: input/output
)

# WebSocket连接状态
websocket_status = Gauge(
    'lmarena_websocket_connected',
    'WebSocket connection status (1=connected, 0=disconnected)'
)

# 错误计数器
error_count = Counter(
    'lmarena_errors_total',
    'Total number of errors',
    ['error_type', 'model']
)

# 模型注册数量
model_registry_gauge = Gauge(
    'lmarena_models_registered',
    'Number of registered models'
)

# --- Request Details Storage ---
@dataclass
class RequestDetails:
    """存储请求的详细信息"""
    request_id: str
    timestamp: float
    model: str
    status: str
    duration: float
    input_tokens: int
    output_tokens: int
    error: Optional[str]
    request_params: dict
    request_messages: list
    response_content: str
    headers: dict
    
class RequestDetailsStorage:
    """管理请求详情的存储"""
    def __init__(self, max_size: int = Config.MAX_REQUEST_DETAILS):
        self.details: Dict[str, RequestDetails] = {}
        self.order: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()
    
    def add(self, details: RequestDetails):
        """添加请求详情"""
        with self._lock:
            if details.request_id in self.details:
                return
            
            # 如果达到最大容量，删除最旧的
            if len(self.order) >= self.order.maxlen:
                oldest_id = self.order[0]
                if oldest_id in self.details:
                    del self.details[oldest_id]
            
            self.details[details.request_id] = details
            self.order.append(details.request_id)
    
    def get(self, request_id: str) -> Optional[RequestDetails]:
        """获取请求详情"""
        with self._lock:
            return self.details.get(request_id)
    
    def get_recent(self, limit: int = 100) -> list:
        """获取最近的请求详情"""
        with self._lock:
            recent_ids = list(self.order)[-limit:]
            return [self.details[id] for id in reversed(recent_ids) if id in self.details]

# 创建请求详情存储
request_details_storage = RequestDetailsStorage()

# --- 日志管理器 ---
class LogManager:
    """管理JSON Lines格式的日志文件"""
    
    def __init__(self):
        self.request_log_path = Config.LOG_DIR / Config.REQUEST_LOG_FILE
        self.error_log_path = Config.LOG_DIR / Config.ERROR_LOG_FILE
        self._lock = threading.Lock()
        self._check_and_rotate()
    
    def _check_and_rotate(self):
        """检查并轮转日志文件"""
        for log_path in [self.request_log_path, self.error_log_path]:
            if log_path.exists() and log_path.stat().st_size > Config.MAX_LOG_SIZE:
                self._rotate_log(log_path)
    
    def _rotate_log(self, log_path: Path):
        """轮转日志文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rotated_path = log_path.with_suffix(f".{timestamp}.jsonl")
        
        # 移动当前日志文件
        shutil.move(log_path, rotated_path)
        
        # 压缩旧日志
        with open(rotated_path, 'rb') as f_in:
            with gzip.open(f"{rotated_path}.gz", 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # 删除未压缩的文件
        rotated_path.unlink()
        
        # 清理旧日志文件
        self._cleanup_old_logs()
    
    def _cleanup_old_logs(self):
        """清理旧的日志文件"""
        log_files = sorted(Config.LOG_DIR.glob("*.jsonl.gz"), key=lambda x: x.stat().st_mtime)
        
        # 保留最新的N个文件
        while len(log_files) > Config.MAX_LOG_FILES:
            oldest_file = log_files.pop(0)
            oldest_file.unlink()
            logging.info(f"删除旧日志文件: {oldest_file}")
    
    def write_request_log(self, log_entry: dict):
        """写入请求日志"""
        with self._lock:
            self._check_and_rotate()
            with open(self.request_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def write_error_log(self, log_entry: dict):
        """写入错误日志"""
        with self._lock:
            self._check_and_rotate()
            with open(self.error_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def read_request_logs(self, limit: int = 100, offset: int = 0, model: str = None) -> list:
        """读取请求日志"""
        logs = []
        
        # 读取当前日志文件
        if self.request_log_path.exists():
            with open(self.request_log_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                
                # 反向读取（最新的在前）
                for line in reversed(all_lines):
                    try:
                        log = json.loads(line.strip())
                        if log.get('type') == 'request_end':  # 只返回完成的请求
                            if model and log.get('model') != model:
                                continue
                            logs.append(log)
                            if len(logs) >= limit + offset:
                                break
                    except json.JSONDecodeError:
                        continue
        
        # 返回指定范围的日志
        return logs[offset:offset + limit]
    
    def read_error_logs(self, limit: int = 50) -> list:
        """读取错误日志"""
        logs = []
        
        if self.error_log_path.exists():
            with open(self.error_log_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                
                # 反向读取（最新的在前）
                for line in reversed(all_lines[-limit:]):
                    try:
                        log = json.loads(line.strip())
                        logs.append(log)
                    except json.JSONDecodeError:
                        continue
        
        return logs

# 创建全局日志管理器
log_manager = LogManager()

# --- 性能监控 ---
class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.request_times = deque(maxlen=1000)  # 最近1000个请求的响应时间
        self.model_performance = defaultdict(lambda: {
            'count': 0,
            'total_time': 0,
            'errors': 0,
            'last_hour_requests': deque(maxlen=3600)  # 最近一小时的请求
        })
    
    def record_request(self, model: str, duration: float, success: bool):
        """记录请求性能"""
        self.request_times.append(duration)
        
        perf = self.model_performance[model]
        perf['count'] += 1
        perf['total_time'] += duration
        if not success:
            perf['errors'] += 1
        
        # 记录时间戳用于计算QPS
        perf['last_hour_requests'].append(time.time())
    
    def get_stats(self) -> dict:
        """获取性能统计"""
        if not self.request_times:
            return {
                'avg_response_time': 0,
                'p50_response_time': 0,
                'p95_response_time': 0,
                'p99_response_time': 0,
                'qps': 0
            }
        
        sorted_times = sorted(self.request_times)
        n = len(sorted_times)
        
        # 计算当前QPS
        current_time = time.time()
        recent_requests = sum(1 for t in self.request_times if current_time - t < 60)
        
        return {
            'avg_response_time': sum(sorted_times) / n,
            'p50_response_time': sorted_times[n // 2],
            'p95_response_time': sorted_times[int(n * 0.95)],
            'p99_response_time': sorted_times[int(n * 0.99)],
            'qps': recent_requests / 60.0
        }
    
    def get_model_stats(self) -> dict:
        """获取模型统计"""
        stats = {}
        current_time = time.time()
        
        for model, perf in self.model_performance.items():
            # 计算最近一小时的QPS
            recent_count = sum(1 for t in perf['last_hour_requests'] 
                             if current_time - t < 3600)
            
            stats[model] = {
                'total_requests': perf['count'],
                'avg_response_time': perf['total_time'] / max(1, perf['count']),
                'error_rate': perf['errors'] / max(1, perf['count']),
                'qps': recent_count / 3600.0
            }
        
        return stats

# 创建性能监控器
performance_monitor = PerformanceMonitor()

# --- WebSocket心跳管理 ---
class WebSocketHeartbeat:
    def __init__(self, interval: int = 30):
        self.interval = interval
        self.last_ping = time.time()
        self.last_pong = time.time()
        self.missed_pongs = 0
        self.max_missed_pongs = 3

    async def start_heartbeat(self, ws: WebSocket):
        """启动心跳任务"""
        while not SHUTTING_DOWN and ws:
            try:
                current_time = time.time()

                # 检查是否收到pong响应
                if current_time - self.last_pong > self.interval * 2:
                    self.missed_pongs += 1
                    if self.missed_pongs >= self.max_missed_pongs:
                        logging.warning("心跳超时，浏览器可能已断线")
                        await self.notify_disconnect()
                        break

                # 发送ping
                await ws.send_text(json.dumps({"type": "ping", "timestamp": current_time}))
                self.last_ping = current_time

                await asyncio.sleep(self.interval)

            except Exception as e:
                logging.error(f"心跳发送失败: {e}")
                break

    def handle_pong(self):
        """处理pong响应"""
        self.last_pong = time.time()
        self.missed_pongs = 0

    async def notify_disconnect(self):
        """通知监控面板连接断开"""
        await broadcast_to_monitors({
            "type": "alert",
            "severity": "warning",
            "message": "浏览器WebSocket心跳超时",
            "timestamp": time.time()
        })


# --- 监控告警系统 ---
class MonitoringAlerts:
    def __init__(self):
        self.alert_history = deque(maxlen=100)
        self.alert_thresholds = {
            "error_rate": 0.1,  # 10%错误率
            "response_time_p95": 30,  # 30秒
            "active_requests": 50,  # 50个并发请求
            "websocket_disconnect_time": 300  # 5分钟
        }
        self.last_check = time.time()
        self.last_disconnect_time = 0

    async def check_system_health(self):
        """定期检查系统健康状况"""
        while not SHUTTING_DOWN:
            try:
                await asyncio.sleep(30)  # 每30秒检查一次

                alerts = []

                # 检查错误率
                error_rate = self.calculate_error_rate()
                if error_rate > self.alert_thresholds["error_rate"]:
                    alerts.append({
                        "type": "high_error_rate",
                        "severity": "warning",
                        "message": f"错误率过高: {error_rate:.1%}",
                        "value": error_rate
                    })

                # 检查响应时间
                perf_stats = performance_monitor.get_stats()
                p95_time = perf_stats.get("p95_response_time", 0)
                if p95_time > self.alert_thresholds["response_time_p95"]:
                    alerts.append({
                        "type": "slow_response",
                        "severity": "warning",
                        "message": f"P95响应时间过慢: {p95_time:.1f}秒",
                        "value": p95_time
                    })

                # 检查活跃请求数
                active_count = len(realtime_stats.active_requests)
                if active_count > self.alert_thresholds["active_requests"]:
                    alerts.append({
                        "type": "high_load",
                        "severity": "warning",
                        "message": f"活跃请求过多: {active_count}",
                        "value": active_count
                    })

                # 检查WebSocket连接
                if not browser_ws:
                    if self.last_disconnect_time == 0:
                        self.last_disconnect_time = time.time()
                    disconnect_time = time.time() - self.last_disconnect_time
                    if disconnect_time > self.alert_thresholds["websocket_disconnect_time"]:
                        alerts.append({
                            "type": "browser_disconnected",
                            "severity": "critical",
                            "message": f"浏览器已断线 {int(disconnect_time / 60)} 分钟",
                            "value": disconnect_time
                        })
                else:
                    self.last_disconnect_time = 0

                # 发送告警到监控面板
                for alert in alerts:
                    await self.send_alert(alert)

            except Exception as e:
                logging.error(f"健康检查失败: {e}")

    def calculate_error_rate(self) -> float:
        """计算最近5分钟的错误率"""
        current_time = time.time()
        recent_requests = [
            req for req in realtime_stats.recent_requests
            if current_time - req.get('end_time', 0) < 300  # 5分钟内
        ]

        if not recent_requests:
            return 0.0

        failed = sum(1 for req in recent_requests if req.get('status') == 'failed')
        return failed / len(recent_requests)

    async def send_alert(self, alert: dict):
        """发送告警到监控面板"""
        alert["timestamp"] = time.time()
        self.alert_history.append(alert)

        # 广播到所有监控客户端
        await broadcast_to_monitors({
            "type": "alert",
            "alert": alert
        })

        logging.warning(f"系统告警: {alert['message']}")


# 创建实例
heartbeat = WebSocketHeartbeat()
monitoring_alerts = MonitoringAlerts()


# --- 实时统计数据结构 ---
@dataclass
class RealtimeStats:
    active_requests: Dict[str, dict] = field(default_factory=dict)
    recent_requests: deque = field(default_factory=lambda: deque(maxlen=Config.MAX_LOG_MEMORY_ITEMS))
    recent_errors: deque = field(default_factory=lambda: deque(maxlen=50))
    model_usage: Dict[str, dict] = field(default_factory=lambda: defaultdict(lambda: {
        'requests': 0, 'tokens': 0, 'errors': 0, 'avg_duration': 0
    }))
    
    def cleanup_old_requests(self):
        """清理超时的活跃请求"""
        current_time = time.time()
        timeout_requests = []
        
        for req_id, req in self.active_requests.items():
            if current_time - req['start_time'] > Config.REQUEST_TIMEOUT_SECONDS:
                timeout_requests.append(req_id)
        
        for req_id in timeout_requests:
            logging.warning(f"清理超时请求: {req_id}")
            del self.active_requests[req_id]

realtime_stats = RealtimeStats()

# --- 清理任务 ---
async def periodic_cleanup():
    """定期清理任务"""
    while not SHUTTING_DOWN:
        try:
            # 清理超时的活跃请求
            realtime_stats.cleanup_old_requests()
            
            # 触发日志轮转检查
            log_manager._check_and_rotate()
            
            # 更新Prometheus指标
            active_requests_gauge.set(len(realtime_stats.active_requests))
            model_registry_gauge.set(len(MODEL_REGISTRY))
            
            logging.info(f"清理任务执行完成. 活跃请求: {len(realtime_stats.active_requests)}")
            
        except Exception as e:
            logging.error(f"清理任务出错: {e}")
        
        await asyncio.sleep(Config.CLEANUP_INTERVAL)

# --- Custom Streaming Response with Immediate Flush ---
class ImmediateStreamingResponse(StreamingResponse):
    """Custom streaming response that forces immediate flushing of chunks"""

    async def stream_response(self, send: typing.Callable) -> None:
        await send({
            "type": "http.response.start",
            "status": self.status_code,
            "headers": self.raw_headers,
        })

        async for chunk in self.body_iterator:
            if chunk:
                # Send the chunk immediately
                await send({
                    "type": "http.response.body",
                    "body": chunk.encode(self.charset) if isinstance(chunk, str) else chunk,
                    "more_body": True,
                })
                # Force a small delay to ensure the chunk is sent
                await asyncio.sleep(0)

        # Send final empty chunk to close the stream
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        })


# --- Request State Management ---
class RequestStatus(Enum):
    PENDING = "pending"
    SENT_TO_BROWSER = "sent_to_browser"
    PROCESSING = "processing"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class PersistentRequest:
    request_id: str
    openai_request: dict
    response_queue: asyncio.Queue
    status: RequestStatus = RequestStatus.PENDING
    created_at: float = field(default_factory=time.time)
    sent_to_browser_at: Optional[float] = None
    last_activity_at: Optional[float] = None
    model_name: str = ""
    is_streaming: bool = True
    accumulated_response: str = ""  # 存储响应内容


class PersistentRequestManager:
    def __init__(self):
        self.active_requests: Dict[str, PersistentRequest] = {}
        self._lock = asyncio.Lock()

    async def add_request(self, request_id: str, openai_request: dict, response_queue: asyncio.Queue,
                    model_name: str, is_streaming: bool) -> PersistentRequest:
        """Add a new request to be tracked"""
        async with self._lock:
            # 检查是否超过最大并发数
            if len(self.active_requests) >= Config.MAX_CONCURRENT_REQUESTS:
                raise HTTPException(status_code=503, detail="Too many concurrent requests")
            
            persistent_req = PersistentRequest(
                request_id=request_id,
                openai_request=openai_request,
                response_queue=response_queue,
                model_name=model_name,
                is_streaming=is_streaming
            )
            self.active_requests[request_id] = persistent_req
            
            # 更新Prometheus指标
            active_requests_gauge.inc()
            
            logging.info(f"REQUEST_MGR: Added request {request_id} for tracking")
            return persistent_req

    def get_request(self, request_id: str) -> Optional[PersistentRequest]:
        """Get a request by ID"""
        return self.active_requests.get(request_id)

    def update_status(self, request_id: str, status: RequestStatus):
        """Update request status"""
        if request_id in self.active_requests:
            self.active_requests[request_id].status = status
            self.active_requests[request_id].last_activity_at = time.time()
            logging.debug(f"REQUEST_MGR: Updated request {request_id} status to {status.value}")

    def mark_sent_to_browser(self, request_id: str):
        """Mark request as sent to browser"""
        if request_id in self.active_requests:
            self.active_requests[request_id].sent_to_browser_at = time.time()
            self.update_status(request_id, RequestStatus.SENT_TO_BROWSER)

    async def timeout_request(self, request_id: str):
        """Timeout a request and send error to client"""
        if request_id in self.active_requests:
            req = self.active_requests[request_id]
            req.status = RequestStatus.TIMEOUT

            # Send timeout error to client
            try:
                await req.response_queue.put({
                    "error": f"Request timed out after {Config.REQUEST_TIMEOUT_SECONDS} seconds. Browser may have disconnected during Cloudflare challenge."
                })
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logging.error(f"REQUEST_MGR: Error sending timeout to queue for {request_id}: {e}")

            # Remove from active requests
            del self.active_requests[request_id]
            active_requests_gauge.dec()
            logging.warning(f"REQUEST_MGR: Request {request_id} timed out and removed")

    def complete_request(self, request_id: str):
        """Mark request as completed and remove from tracking"""
        if request_id in self.active_requests:
            self.active_requests[request_id].status = RequestStatus.COMPLETED
            del self.active_requests[request_id]
            active_requests_gauge.dec()
            logging.info(f"REQUEST_MGR: Request {request_id} completed and removed")

    def get_pending_requests(self) -> Dict[str, PersistentRequest]:
        """Get all requests that were sent to browser but not completed"""
        return {
            req_id: req for req_id, req in self.active_requests.items()
            if req.status in [RequestStatus.SENT_TO_BROWSER, RequestStatus.PROCESSING]
        }

    async def request_timeout_watcher(self, requests_to_watch: Dict[str, PersistentRequest]):
        """A background task to watch for and time out disconnected requests."""
        try:
            await asyncio.sleep(Config.REQUEST_TIMEOUT_SECONDS)

            logging.info(f"WATCHER: Timeout reached. Checking {len(requests_to_watch)} requests.")
            for request_id, req in requests_to_watch.items():
                # Check if the request is still pending (i.e., not completed by a reconnect)
                if self.get_request(request_id) and req.status in [RequestStatus.SENT_TO_BROWSER,
                                                                   RequestStatus.PROCESSING]:
                    logging.warning(f"WATCHER: Request {request_id} timed out after browser disconnect.")
                    await self.timeout_request(request_id)
        except asyncio.CancelledError:
            logging.info("WATCHER: Request timeout watcher was cancelled, likely due to server shutdown.")
        except Exception as e:
            logging.error(f"WATCHER: Error in request timeout watcher: {e}", exc_info=True)

    async def handle_browser_disconnect(self):
        """Handle browser WebSocket disconnect - spawn timeout watchers for pending requests."""
        pending_requests = self.get_pending_requests()
        if not pending_requests:
            return

        logging.warning(f"REQUEST_MGR: Browser disconnected with {len(pending_requests)} pending requests.")

        # Check if we're shutting down
        global SHUTTING_DOWN
        if SHUTTING_DOWN:
            # During shutdown, timeout immediately to avoid hanging
            logging.info("REQUEST_MGR: Server shutting down, timing out all pending requests immediately.")
            for request_id in list(pending_requests.keys()):
                logging.info(f"REQUEST_MGR: Timing out request {request_id} due to shutdown.")
                await self.timeout_request(request_id)
        else:
            # During normal operation, spawn a watcher task for the timeout
            logging.info(f"REQUEST_MGR: Spawning timeout watcher for {len(pending_requests)} pending requests.")
            watcher_task = asyncio.create_task(self.request_timeout_watcher(pending_requests.copy()))
            background_tasks.add(watcher_task)
            watcher_task.add_done_callback(background_tasks.discard)


# --- Logging Functions ---
def log_request_start(request_id: str, model: str, params: dict, messages: list = None):
    """记录请求开始"""
    request_info = {
        'id': request_id,
        'model': model,
        'start_time': time.time(),
        'status': 'active',
        'params': params,
        'messages': messages or []
    }
    
    realtime_stats.active_requests[request_id] = request_info
    
    # 写入日志文件
    log_entry = {
        'type': 'request_start',
        'timestamp': time.time(),
        'request_id': request_id,
        'model': model,
        'params': params
    }
    log_manager.write_request_log(log_entry)
    
def log_request_end(request_id: str, success: bool, input_tokens: int = 0, 
                   output_tokens: int = 0, error: str = None, response_content: str = ""):
    """记录请求结束"""
    if request_id not in realtime_stats.active_requests:
        return
        
    req = realtime_stats.active_requests[request_id]
    duration = time.time() - req['start_time']
    
    # 更新实时统计
    req['status'] = 'success' if success else 'failed'
    req['duration'] = duration
    req['input_tokens'] = input_tokens
    req['output_tokens'] = output_tokens
    req['error'] = error
    req['end_time'] = time.time()
    req['response_content'] = response_content
    
    # 添加到最近请求列表
    realtime_stats.recent_requests.append(req.copy())
    
    # 更新模型统计
    model = req['model']
    stats = realtime_stats.model_usage[model]
    stats['requests'] += 1
    if success:
        stats['tokens'] += input_tokens + output_tokens
    else:
        stats['errors'] += 1
    
    # 记录性能
    performance_monitor.record_request(model, duration, success)
    
    # 更新Prometheus指标
    request_count.labels(model=model, status='success' if success else 'failed', type='chat').inc()
    request_duration.labels(model=model, type='chat').observe(duration)
    token_usage.labels(model=model, token_type='input').inc(input_tokens)
    token_usage.labels(model=model, token_type='output').inc(output_tokens)
    
    # 保存请求详情
    details = RequestDetails(
        request_id=request_id,
        timestamp=req['start_time'],
        model=model,
        status='success' if success else 'failed',
        duration=duration,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=error,
        request_params=req.get('params', {}),
        request_messages=req.get('messages', []),
        response_content=response_content[:5000],  # 限制长度
        headers={}
    )
    request_details_storage.add(details)
    
    # 写入日志文件
    log_entry = {
        'type': 'request_end',
        'timestamp': time.time(),
        'request_id': request_id,
        'model': model,
        'status': 'success' if success else 'failed',
        'duration': duration,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'error': error,
        'params': req.get('params', {})
    }
    log_manager.write_request_log(log_entry)
    
    # 从活动请求中移除
    del realtime_stats.active_requests[request_id]

def log_error(request_id: str, error_type: str, error_message: str, stack_trace: str = ""):
    """记录错误日志"""
    error_data = {
        'timestamp': time.time(),
        'request_id': request_id,
        'error_type': error_type,
        'error_message': error_message,
        'stack_trace': stack_trace
    }
    
    realtime_stats.recent_errors.append(error_data)
    
    # 更新Prometheus指标
    model = realtime_stats.active_requests.get(request_id, {}).get('model', 'unknown')
    error_count.labels(error_type=error_type, model=model).inc()
    
    # 写入错误日志文件
    log_manager.write_error_log(error_data)

# --- Model Registry ---
MODEL_REGISTRY = {}  # Will be populated dynamically


def update_model_registry(models_data: dict) -> None:
    """Update the model registry with data from browser, inferring type from capabilities."""
    global MODEL_REGISTRY

    try:
        if not models_data or not isinstance(models_data, dict):
            logging.warning(f"Received empty or invalid model data: {models_data}")
            return

        new_registry = {}
        for public_name, model_info in models_data.items():
            if not isinstance(model_info, dict):
                continue

            # Determine type from outputCapabilities
            model_type = "chat"  # Default
            capabilities = model_info.get("capabilities", {})
            if isinstance(capabilities, dict):
                output_caps = capabilities.get("outputCapabilities", {})
                if isinstance(output_caps, dict):
                    if "image" in output_caps:
                        model_type = "image"
                    elif "video" in output_caps:
                        model_type = "video"

            # Store the processed model info with the determined type
            processed_info = model_info.copy()
            processed_info["type"] = model_type
            new_registry[public_name] = processed_info

        MODEL_REGISTRY = new_registry
        model_registry_gauge.set(len(MODEL_REGISTRY))
        logging.info(f"Updated and processed model registry with {len(MODEL_REGISTRY)} models.")

    except KeyboardInterrupt:
        raise
    except Exception as e:
        logging.error(f"Error updating model registry: {e}", exc_info=True)


def get_fallback_registry():
    """Fallback registry in case dynamic fetching fails."""
    return {
        "qwq-32b": {"id": "885976d3-d178-48f5-a3f4-6e13e0718872", "type": "chat"},
        "qwen3-30b-a3b": {"id": "9a066f6a-7205-4325-8d0b-d81cc4b049c0", "type": "chat"},
        "qwen-max-2025-01-25": {"id": "fe8003fc-2e5d-4a3f-8f07-c1cff7ba0159", "type": "chat"},
        "qwen3-235b-a22b": {"id": "2595a594-fa54-4299-97cd-2d7380d21c80", "type": "chat"},
        "qwen3-235b-a22b-no-thinking": {"id": "1a400d9a-f61c-4bc2-89b4-a9b7e77dff12", "type": "chat"},
        "amazon.nova-pro-v1:0": {"id": "a14546b5-d78d-4cf6-bb61-ab5b8510a9d6", "type": "chat"},
        "amazon-nova-experimental-chat-05-14": {"id": "d799a034-0ab6-48c1-817a-62e591143f39", "type": "chat"},
        "claude-3-5-sonnet-20241022": {"id": "f44e280a-7914-43ca-a25d-ecfcc5d48d09", "type": "chat"},
        "claude-opus-4-20250514": {"id": "ee116d12-64d6-48a8-88e5-b2d06325cdd2", "type": "chat"},
        "claude-3-7-sonnet-20250219-thinking-32k": {"id": "be98fcfd-345c-4ae1-9a82-a19123ebf1d2", "type": "chat"},
        "claude-3-5-haiku-20241022": {"id": "f6fbf06c-532c-4c8a-89c7-f3ddcfb34bd1", "type": "chat"},
        "claude-sonnet-4-20250514": {"id": "ac44dd10-0666-451c-b824-386ccfea7bcc", "type": "chat"},
        "claude-3-7-sonnet-20250219": {"id": "c5a11495-081a-4dc6-8d9a-64a4fd6f7bbc", "type": "chat"},
        "claude-sonnet-4-20250514-thinking-32k": {"id": "4653dded-a46b-442a-a8fe-9bb9730e2453", "type": "chat"},
        "claude-opus-4-20250514-thinking-16k": {"id": "3b5e9593-3dc0-4492-a3da-19784c4bde75", "type": "chat"},
        "command-a-03-2025": {"id": "0f785ba1-efcb-472d-961e-69f7b251c7e3", "type": "chat"},
        "deepseek-r1-0528": {"id": "30ab90f5-e020-4f83-aff5-f750d2e78769", "type": "chat"},
        "deepseek-v3-0324": {"id": "2f5253e4-75be-473c-bcfc-baeb3df0f8ad", "type": "chat"},
        "gemini-2.5-flash": {"id": "ce2092c1-28d4-4d42-a1e0-6b061dfe0b20", "type": "chat"},
        "gemma-3-27b-it": {"id": "789e245f-eafe-4c72-b563-d135e93988fc", "type": "chat"},
        "gemini-2.5-flash-lite-preview-06-17-thinking": {"id": "04ec9a17-c597-49df-acf0-963da275c246", "type": "chat"},
        "gemini-2.5-pro": {"id": "e2d9d353-6dbe-4414-bf87-bd289d523726", "type": "chat"},
        "gemma-3n-e4b-it": {"id": "896a3848-ae03-4651-963b-7d8f54b61ae8", "type": "chat"},
        "gemini-2.5-flash-preview-04-17": {"id": "e5128acd-32f5-4cb5-a6c1-32fbf2cb281b", "type": "chat"},
        "gemini-2.0-flash-001": {"id": "7a55108b-b997-4cff-a72f-5aa83beee918", "type": "chat"},
        "ideogram-v2": {"id": "34ee5a83-8d85-4d8b-b2c1-3b3413e9ed98", "type": "chat"},
        "photon": {"id": "17e31227-36d7-4a7a-943a-7ebffa3a00eb", "type": "chat"},
        "llama-4-scout-17b-16e-instruct": {"id": "c28823c1-40fd-4eaf-9825-e28f11d1f8b2", "type": "chat"},
        "llama-4-maverick-03-26-experimental": {"id": "49bd7403-c7fd-4d91-9829-90a91906ad6c", "type": "chat"},
        "llama-4-maverick-17b-128e-instruct": {"id": "b5ad3ab7-fc56-4ecd-8921-bd56b55c1159", "type": "chat"},
        "llama-3.3-70b-instruct": {"id": "dcbd7897-5a37-4a34-93f1-76a24c7bb028", "type": "chat"},
        "minimax-m1": {"id": "87e8d160-049e-4b4e-adc4-7f2511348539", "type": "chat"},
        "mistral-small-3.1-24b-instruct-2503": {"id": "69f5d38a-45f5-4d3a-9320-b866a4035ed9", "type": "chat"},
        "mistral-medium-2505": {"id": "27b9f8c6-3ee1-464a-9479-a8b3c2a48fd4", "type": "chat"},
        "magistral-medium-2506": {"id": "6337f479-2fc8-4311-a76b-8c957765cd68", "type": "chat"},
        "mistral-small-2506": {"id": "bbad1d17-6aa5-4321-949c-d11fb6289241", "type": "chat"},
        "chatgpt-4o-latest-20250326": {"id": "9513524d-882e-4350-b31e-e4584440c2c8", "type": "chat"},
        "gpt-4.1-2025-04-14": {"id": "14e9311c-94d2-40c2-8c54-273947e208b0", "type": "chat"},
        "gpt-4.1-mini-2025-04-14": {"id": "6a5437a7-c786-467b-b701-17b0bc8c8231", "type": "chat"},
        "o3-mini": {"id": "c680645e-efac-4a81-b0af-da16902b2541", "type": "chat"},
        "o3-2025-04-16": {"id": "cb0f1e24-e8e9-4745-aabc-b926ffde7475", "type": "chat"},
        "o4-mini-2025-04-16": {"id": "f1102bbf-34ca-468f-a9fc-14bcf63f315b", "type": "chat"},
        "grok-3-preview-02-24": {"id": "bd2c8278-af7a-4ec3-84db-0a426c785564", "type": "chat"},
        "grok-3-mini-beta": {"id": "7699c8d4-0742-42f9-a117-d10e84688dab", "type": "chat"},
        "grok-3-mini-high": {"id": "149619f1-f1d5-45fd-a53e-7d790f156f20", "type": "chat"},
        "grok-4-0709": {"id": "774bcb6c-9787-4d7e-981d-b06ddfa1c3e7", "type": "chat"},
        "grok-3-search": {"id": "33453cd6-8704-4b82-a7c0-12e8042ef1e3", "type": "chat"},
        "hunyuan-turbos-20250416": {"id": "2e1af1cb-8443-4f3e-8d60-113992bfb491", "type": "chat"},
        "hunyuan-large-vision": {"id": "20ba260d-509a-422d-a35d-9b0bd8bcc258", "type": "chat"},
        "steve": {"id": "0caa771f-682f-484b-a7ad-70f7cb1f4183", "type": "chat"},
        "X-preview": {"id": "68e498cb-a1b3-45fa-ae84-1b746d48652f", "type": "chat"},
        "stephen-v2": {"id": "39b185cb-aba9-4232-99ea-074883a5ccd4", "type": "chat"},
        "flamesong": {"id": "cdb8b113-1cea-4689-81ff-38beabd80b6f", "type": "chat"},
        "glm-4-air-250414": {"id": "5b5ad048-73b6-4cc2-a27f-2d2c2c2379a7", "type": "chat"},
        "stonebloom": {"id": "0bbd24e1-d18e-42fb-a87e-016e835acb08", "type": "chat"},
        "step-1o-turbo-202506": {"id": "2820a312-8ff0-4b22-8271-c040efd83761", "type": "chat"},
        "kraken-250610-1": {"id": "a0d1a461-0991-4f80-bcd9-900d3665ba11", "type": "chat"},
        "stephen-vision-csfix": {"id": "e3c9ea42-5f42-496b-bc80-c7e8ee5653cc", "type": "chat"},
        "wolfstride": {"id": "849f6833-8598-4329-b7a6-e765eb2a0c0d", "type": "chat"},
        "ernie-x1-turbo-32k-preview": {"id": "1efdf1f1-8879-493b-8e4a-14b61e978847","type": "chat"},
        "seededit-3.0": {"id": "e2969ebb-6450-4bc4-87c9-bbdcf95840da","type": "image"},
        "flux-1-kontext-pro": {"id": "43390b9c-cf16-4e4e-a1be-3355bb5b6d5e", "type": "image"},
        "flux-1-kontext-max": {"id": "0633b1ef-289f-49d4-a834-3d475a25e46b", "type": "image"},
        "flux-1.1-pro": {"id": "9e8525b7-fe50-4e50-bf7f-ad1d3d205d3c", "type": "image"},
        "flux-1-kontext-dev": {"id": "eb90ae46-a73a-4f27-be8b-40f090592c9a", "type": "image"},
        "bagel": {"id": "c9ef2f9e-5410-4d3b-b65e-b5af317c9afd", "type": "image"},
        "seedream-3": {"id": "0dde746c-3dbc-42be-b8f5-f38bd1595baa", "type": "image"},
        "anonymous-bot-0514": {"id": "eb5da04f-9b28-406b-bf06-4539158c66ef","type": "image"},
        "gemini-2.0-flash-preview-image-generation": {"id": "69bbf7d4-9f44-447e-a868-abc4f7a31810", "type": "image"},
        "imagen-3.0-generate-002": {"id": "51ad1d79-61e2-414c-99e3-faeb64bb6b1b", "type": "image"},
        "imagen-4.0-ultra-generate-preview-06-06": {"id": "f31bd225-2eee-4ba7-bd1e-15fe104b9b1c", "type": "image"},
        "imagen-4.0-generate-preview-06-06": {"id": "dd5e7509-3249-43b7-b3bf-6e158c97b1c1", "type": "image"},
        "dall-e-3": {"id": "bb97bc68-131c-4ea4-a59e-03a6252de0d2", "type": "image"},
        "gpt-image-1": {"id": "6e855f13-55d7-4127-8656-9168a9f4dcc0", "type": "image"},
        "recraft-v3": {"id": "b70ab012-18e7-4d6f-a887-574e05de6c20", "type": "image"},
        "step1x-edit": {"id": "44882393-edb8-468f-9a39-d13d961ae364", "type": "image"},
        "ideogram-v3-quality": {"id": "f7e2ed7a-f0b9-40ef-853a-20036e747232", "type": "image"},
        "pika-2.2": {"id": "db141cc1-227f-4074-aeb9-d49db03329bc", "type": "video"},
        "hailuo-02-standard": {"id": "e652c45e-8699-4392-94f0-7834e7464137", "type": "video"},
        "veo3": {"id": "1fab3f3c-bb6d-4219-b1fa-969535f4f22b", "type": "video"},
        "veo2": {"id": "2e354090-7df5-4578-9de8-85617481695e", "type": "video"},
        "kling-2.1-master": {"id": "4f65970e-c258-4200-a424-bc2d158a0ee3", "type": "video"},
        "kling-2-master-image-to-video": {"id": "0888fb9f-6f1e-42ea-81d6-340f9541510a", "type": "video"},
        "seedance-1-lite-image-to-video": {"id": "e413081f-b7c7-4212-8a21-5c8dbf865c21", "type": "video"},
        "seedance-1-lite-text-to-video": {"id": "e059dc1c-fdd1-4776-9671-ea65138eeda5", "type": "video"},
    }


# --- Global State ---
browser_ws: WebSocket | None = None
response_channels: dict[str, asyncio.Queue] = {}  # Keep for backward compatibility
request_manager = PersistentRequestManager()
background_tasks: Set[asyncio.Task] = set()
SHUTTING_DOWN = False
monitor_clients: Set[WebSocket] = set()  # 监控客户端连接
startup_time = time.time()  # 服务器启动时间

# --- Helper Functions for Monitoring ---
async def broadcast_to_monitors(data: dict):
    """向所有监控客户端广播数据"""
    if not monitor_clients:
        return
        
    disconnected = []
    for client in monitor_clients:
        try:
            await client.send_json(data)
        except:
            disconnected.append(client)
    
    # 清理断开的连接
    for client in disconnected:
        monitor_clients.discard(client)

# --- FastAPI App and Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL_REGISTRY, request_manager, startup_time
    logging.info(f"服务器正在启动...")
    startup_time = time.time()

    # 显示访问地址
    local_ip = get_local_ip()
    logging.info(f"🌐 Server access URLs:")
    logging.info(f"  - Local: http://localhost:{Config.PORT}")
    logging.info(f"  - Network: http://{local_ip}:{Config.PORT}")
    logging.info(f"📱 Use the Network URL to access from your phone on the same WiFi")

    # === 添加详细的端点说明 ===
    logging.info(f"\n📋 Available Endpoints:")
    logging.info(f"  🖥️  Monitor Dashboard: http://{local_ip}:{Config.PORT}/monitor")
    logging.info(f"     实时监控面板，查看系统状态、请求日志、性能指标")

    logging.info(f"\n  📊 Metrics & Health:")
    logging.info(f"     - Prometheus Metrics: http://{local_ip}:{Config.PORT}/metrics")
    logging.info(f"       Prometheus格式的性能指标，可接入Grafana")
    logging.info(f"     - Health Check: http://{local_ip}:{Config.PORT}/health")
    logging.info(f"       基础健康检查")
    logging.info(f"     - Detailed Health: http://{local_ip}:{Config.PORT}/api/health/detailed")
    logging.info(f"       详细健康状态，包含评分和建议")

    logging.info(f"\n  🤖 AI API:")
    logging.info(f"     - Chat Completions: POST http://{local_ip}:{Config.PORT}/v1/chat/completions")
    logging.info(f"       OpenAI兼容的聊天API")
    logging.info(f"     - List Models: GET http://{local_ip}:{Config.PORT}/v1/models")
    logging.info(f"       获取可用模型列表")
    logging.info(f"     - Refresh Models: POST http://{local_ip}:{Config.PORT}/v1/refresh-models")
    logging.info(f"       刷新模型列表")

    logging.info(f"\n  📈 Statistics:")
    logging.info(f"     - Stats Summary: http://{local_ip}:{Config.PORT}/api/stats/summary")
    logging.info(f"       24小时统计摘要")
    logging.info(f"     - Request Logs: http://{local_ip}:{Config.PORT}/api/logs/requests")
    logging.info(f"       请求日志API")
    logging.info(f"     - Error Logs: http://{local_ip}:{Config.PORT}/api/logs/errors")
    logging.info(f"       错误日志API")
    logging.info(f"     - Alerts: http://{local_ip}:{Config.PORT}/api/alerts")
    logging.info(f"       系统告警历史")

    logging.info(f"\n  🛠️  OpenAI Client Config:")
    logging.info(f"     base_url='http://{local_ip}:{Config.PORT}/v1'")
    logging.info(f"     api_key='sk-any-string-you-like'")
    logging.info(f"\n{'=' * 60}\n")
    # === 结束添加 ===

    # Use fallback registry on startup - models will be updated by browser script
    MODEL_REGISTRY = get_fallback_registry()
    logging.info(f"已加载 {len(MODEL_REGISTRY)} 个备用模型")

    # 启动清理任务
    cleanup_task = asyncio.create_task(periodic_cleanup())
    background_tasks.add(cleanup_task)
    # 启动健康检查任务
    health_check_task = asyncio.create_task(monitoring_alerts.check_system_health())
    background_tasks.add(health_check_task)

    logging.info("服务器启动完成")

    try:
        yield
    finally:
        global SHUTTING_DOWN
        SHUTTING_DOWN = True
        logging.info(f"生命周期: 服务器正在关闭。正在取消 {len(background_tasks)} 个后台任务...")

        # Cancel all background tasks
        cancelled_tasks = []
        for task in list(background_tasks):
            if not task.done():
                logging.info(f"生命周期: 正在取消任务: {task}")
                task.cancel()
                cancelled_tasks.append(task)

        # Wait for cancelled tasks to finish
        if cancelled_tasks:
            logging.info(f"生命周期: 等待 {len(cancelled_tasks)} 个已取消的任务完成...")
            results = await asyncio.gather(*cancelled_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.info(f"生命周期: 任务 {i} 完成，结果: {type(result).__name__}")
                else:
                    logging.info(f"生命周期: 任务 {i} 正常完成")

        logging.info("生命周期: 所有后台任务已取消。关闭完成。")


app = FastAPI(lifespan=lifespan)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境可以用*，生产环境建议改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- WebSocket Handler (Producer) ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global browser_ws, request_manager
    await websocket.accept()
    logging.info("✅ 浏览器WebSocket已连接")
    browser_ws = websocket
    websocket_status.set(1)
    # 重置断线时间
    monitoring_alerts.last_disconnect_time = 0

    # 启动心跳任务
    heartbeat_task = asyncio.create_task(heartbeat.start_heartbeat(websocket))
    background_tasks.add(heartbeat_task)

    # Handle reconnection - check for pending requests
    pending_requests = request_manager.get_pending_requests()
    if pending_requests:
        logging.info(f"🔄 浏览器重连，有 {len(pending_requests)} 个待处理请求")

        # Send reconnection acknowledgment with pending request IDs
        await websocket.send_text(json.dumps({
            "type": "reconnection_ack",
            "pending_request_ids": list(pending_requests.keys()),
            "message": f"已重连。发现 {len(pending_requests)} 个待处理请求。"
        }))

    try:
        while True:
            message_str = await websocket.receive_text()
            message = json.loads(message_str)
            # 处理pong响应
            if message.get("type") == "pong":
                heartbeat.handle_pong()
                continue


            # Handle reconnection handshake from browser
            if message.get("type") == "reconnection_handshake":
                browser_pending_ids = message.get("pending_request_ids", [])
                logging.info(f"🤝 收到重连握手，浏览器有 {len(browser_pending_ids)} 个待处理请求")

                # Restore request channels for matching requests
                restored_count = 0
                for request_id in browser_pending_ids:
                    persistent_req = request_manager.get_request(request_id)
                    if persistent_req:
                        # Restore the response channel
                        response_channels[request_id] = persistent_req.response_queue
                        request_manager.update_status(request_id, RequestStatus.PROCESSING)
                        restored_count += 1
                        logging.info(f"🔄 已恢复请求通道: {request_id}")

                # Send restoration acknowledgment
                await websocket.send_text(json.dumps({
                    "type": "restoration_ack",
                    "restored_count": restored_count,
                    "message": f"已恢复 {restored_count} 个请求通道"
                }))
                continue

            # Handle model registry updates
            if message.get("type") == "model_registry":
                models_data = message.get("models", {})
                update_model_registry(models_data)

                # Send acknowledgment
                await websocket.send_text(json.dumps({
                    "type": "model_registry_ack",
                    "count": len(MODEL_REGISTRY)
                }))
                continue

            # Handle regular chat requests
            request_id = message.get("request_id")
            data = message.get("data")
            logging.debug(f"⬅️ 浏览器 [ID: {request_id}]: 收到数据: {data}")

            # Update request status to processing when we receive data
            if request_id:
                request_manager.update_status(request_id, RequestStatus.PROCESSING)

            # Handle both old and new request tracking systems
            if request_id in response_channels:
                queue = response_channels[request_id]
                logging.debug(f"浏览器 [ID: {request_id}]: 放入队列前大小: {queue.qsize()}")
                await queue.put(data)
                logging.debug(f"浏览器 [ID: {request_id}]: 数据已放入队列。新大小: {queue.qsize()}")

                # Check if this is the end of the request
                if data == "[DONE]":
                    request_manager.complete_request(request_id)

            else:
                # Check if this is a persistent request
                persistent_req = request_manager.get_request(request_id)
                if persistent_req:
                    logging.info(f"🔄 正在恢复持久请求的队列: {request_id}")
                    response_channels[request_id] = persistent_req.response_queue
                    await persistent_req.response_queue.put(data)
                    request_manager.update_status(request_id, RequestStatus.PROCESSING)

                    if data == "[DONE]":
                        request_manager.complete_request(request_id)
                else:
                    logging.warning(f"⚠️ 浏览器: 收到未知/已关闭的请求消息: {request_id}")

    except WebSocketDisconnect:
        logging.warning("❌ 浏览器客户端已断开连接")
    finally:
        browser_ws = None
        websocket_status.set(0)

        # Handle browser disconnect - keep persistent requests alive
        await request_manager.handle_browser_disconnect()

        # Only send errors to non-persistent requests
        for request_id, queue in response_channels.items():
            persistent_req = request_manager.get_request(request_id)
            if not persistent_req:  # Only error out non-persistent requests
                try:
                    await queue.put({"error": "Browser disconnected"})
                except KeyboardInterrupt:
                    raise
                except:
                    pass

        response_channels.clear()
        logging.info("WebSocket cleaned up. Persistent requests kept alive.")

# --- Monitor WebSocket ---
@app.websocket("/ws/monitor")
async def monitor_websocket(websocket: WebSocket):
    """监控面板的WebSocket连接"""
    await websocket.accept()
    monitor_clients.add(websocket)
    
    try:
        # 发送初始数据
        await websocket.send_json({
            "type": "initial_data",
            "active_requests": dict(realtime_stats.active_requests),
            "recent_requests": list(realtime_stats.recent_requests),
            "recent_errors": list(realtime_stats.recent_errors),
            "model_usage": dict(realtime_stats.model_usage)
        })
        
        while True:
            # 保持连接
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        monitor_clients.remove(websocket)

# --- API Handler ---
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    global request_manager

    if not browser_ws:
        raise HTTPException(status_code=503, detail="Browser client not connected.")

    openai_req = await request.json()
    request_id = str(uuid.uuid4())
    is_streaming = openai_req.get("stream", True)
    model_name = openai_req.get("model")

    model_info = MODEL_REGISTRY.get(model_name)
    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found.")
    model_type = model_info.get("type", "chat")

    # 添加请求开始日志
    request_params = {
        "temperature": openai_req.get("temperature"),
        "top_p": openai_req.get("top_p"),
        "max_tokens": openai_req.get("max_tokens"),
        "streaming": is_streaming
    }
    messages = openai_req.get("messages", [])
    log_request_start(request_id, model_name, request_params, messages)
    
    # 广播到监控客户端
    await broadcast_to_monitors({
        "type": "request_start",
        "request_id": request_id,
        "model": model_name,
        "timestamp": time.time()
    })

    # Create response queue and add to both systems for compatibility
    response_queue = asyncio.Queue(maxsize=Config.BACKPRESSURE_QUEUE_SIZE)
    response_channels[request_id] = response_queue

    # Add to persistent request manager
    try:
        persistent_req = await request_manager.add_request(
            request_id=request_id,
            openai_request=openai_req,
            response_queue=response_queue,
            model_name=model_name,
            is_streaming=is_streaming
        )
    except HTTPException:
        # 并发限制
        log_request_end(request_id, False, 0, 0, "Too many concurrent requests")
        raise

    logging.info(f"API [ID: {request_id}]: Created persistent request for model type '{model_type}'.")

    try:
        task = asyncio.create_task(send_to_browser_task(request_id, openai_req))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        media_type = "text/event-stream" if is_streaming else "application/json"
        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked"
        } if is_streaming else {}

        logging.info(f"API [ID: {request_id}]: Returning {media_type} response to client.")

        if is_streaming:
            # Use custom streaming response for immediate flush
            return ImmediateStreamingResponse(
                stream_generator(request_id, model_name, is_streaming=is_streaming, model_type=model_type),
                media_type=media_type,
                headers=headers
            )
        else:
            # Use regular response for non-streaming
            return StreamingResponse(
                stream_generator(request_id, model_name, is_streaming=is_streaming, model_type=model_type),
                media_type=media_type,
                headers=headers
            )
    except KeyboardInterrupt:
        # Clean up on keyboard interrupt
        if request_id in response_channels:
            del response_channels[request_id]
        request_manager.complete_request(request_id)
        raise
    except Exception as e:
        # Clean up both tracking systems
        if request_id in response_channels:
            del response_channels[request_id]
        request_manager.complete_request(request_id)
        logging.error(f"API [ID: {request_id}]: Exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def send_to_browser_task(request_id: str, openai_req: dict):
    """This task runs in the background, sending the request to the browser."""
    global request_manager

    if not browser_ws:
        logging.error(f"TASK [ID: {request_id}]: Cannot send, browser disconnected.")
        # Mark request as error if browser is not connected
        persistent_req = request_manager.get_request(request_id)
        if persistent_req:
            await persistent_req.response_queue.put({"error": "Browser not connected"})
        return

    try:
        lmarena_payload, files_to_upload = create_lmarena_request_body(openai_req)

        message_to_browser = {
            "request_id": request_id,
            "payload": lmarena_payload,
            "files_to_upload": files_to_upload
        }

        logging.info(f"TASK [ID: {request_id}]: Sending payload and {len(files_to_upload)} file(s) to browser.")
        await browser_ws.send_text(json.dumps(message_to_browser))

        # Mark as sent to browser in persistent request manager
        request_manager.mark_sent_to_browser(request_id)
        logging.info(f"TASK [ID: {request_id}]: Payload sent and marked as sent to browser.")

    except KeyboardInterrupt:
        raise
    except Exception as e:
        logging.error(f"Error creating or sending request body: {e}", exc_info=True)

        # Send error to both tracking systems
        if request_id in response_channels:
            await response_channels[request_id].put({"error": f"Failed to process request: {e}"})

        persistent_req = request_manager.get_request(request_id)
        if persistent_req:
            await persistent_req.response_queue.put({"error": f"Failed to process request: {e}"})
            request_manager.update_status(request_id, RequestStatus.ERROR)


# Simple token estimation function
def estimateTokens(text: str) -> int:
    """简单的token估算函数"""
    if not text:
        return 0
    # 粗略估算：平均每个token约4个字符
    return len(str(text)) // 4


# --- Stream Consumer ---
async def stream_generator(request_id: str, model: str, is_streaming: bool, model_type: str):
    global request_manager, browser_ws
    start_time = time.time()  # 添加开始时间记录

    # Get queue from either response_channels or persistent request
    queue = response_channels.get(request_id)
    persistent_req = request_manager.get_request(request_id)

    if not queue and persistent_req:
        queue = persistent_req.response_queue
        # Restore to response_channels for compatibility
        response_channels[request_id] = queue

    if not queue:
        logging.error(f"STREAMER [ID: {request_id}]: Queue not found!")
        return

    logging.info(f"STREAMER [ID: {request_id}]: Generator started for model type '{model_type}'.")
    await asyncio.sleep(0)

    response_id = f"chatcmpl-{uuid.uuid4()}"

    try:
        accumulated_content = ""
        media_urls = []
        finish_reason = None

        # Buffer for streaming chunks (minimum 50 chars)
        streaming_buffer = ""
        MIN_CHUNK_SIZE = 40
        last_chunk_time = time.time()
        MAX_BUFFER_TIME = 0.5  # Max 500ms before forcing flush

        while True:
            # Try to get data with a timeout to check buffer periodically
            try:
                raw_data = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                # No new data, but check if we should flush buffer
                if is_streaming and model_type == "chat" and streaming_buffer:
                    current_time = time.time()
                    if current_time - last_chunk_time >= MAX_BUFFER_TIME:
                        chunk = {
                            "id": response_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": streaming_buffer
                                },
                                "finish_reason": None
                            }],
                            "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
                        }
                        chunk_data = f"data: {json.dumps(chunk)}\n\n"
                        yield chunk_data
                        streaming_buffer = ""
                        last_chunk_time = current_time
                continue

            if raw_data == "[DONE]":
                break

            # Handle error dictionary from timeout or browser disconnect
            if isinstance(raw_data, dict) and "error" in raw_data:
                logging.error(f"STREAMER [ID: {request_id}]: Received error: {raw_data}")

                # Format error for OpenAI response
                openai_error = {
                    "error": {
                        "message": str(raw_data.get("error", "Unknown error")),
                        "type": "server_error",
                        "code": None
                    }
                }

                if is_streaming:
                    yield f"data: {json.dumps(openai_error)}\n\ndata: [DONE]\n\n"
                else:
                    yield json.dumps(openai_error)
                return

            # First, try to detect if this is a JSON error response from the server
            if isinstance(raw_data, str) and raw_data.strip().startswith('{'):
                try:
                    error_data = json.loads(raw_data.strip())
                    if "error" in error_data:
                        logging.error(f"STREAMER [ID: {request_id}]: Server returned error: {error_data}")

                        # Parse the actual error structure from the server
                        server_error = error_data["error"]

                        # If the server error is already in OpenAI format, use it directly
                        if isinstance(server_error, dict) and "message" in server_error:
                            openai_error = {"error": server_error}
                        else:
                            # If it's just a string, wrap it in OpenAI format
                            openai_error = {
                                "error": {
                                    "message": str(server_error),
                                    "type": "server_error",
                                    "code": None
                                }
                            }

                        if is_streaming:
                            yield f"data: {json.dumps(openai_error)}\n\ndata: [DONE]\n\n"
                        else:
                            yield json.dumps(openai_error)
                        return
                except json.JSONDecodeError:
                    pass  # Not a JSON error, continue with normal parsing

            # Skip processing if raw_data is not a string (e.g., error dict)
            if not isinstance(raw_data, str):
                logging.warning(f"STREAMER [ID: {request_id}]: Skipping non-string data: {type(raw_data)}")
                continue

            try:
                prefix, content = raw_data.split(":", 1)

                if model_type in ["image", "video"] and prefix == "a2":
                    media_data_list = json.loads(content)
                    for item in media_data_list:
                        url = item.get("image") if model_type == "image" else item.get("url")
                        if url:
                            logging.info(f"MEDIA [ID: {request_id}]: Found {model_type} URL: {url}")
                            media_urls.append(url)

                elif model_type == "chat" and prefix == "a0":
                    delta = json.loads(content)
                    if is_streaming:
                        # Add to buffer instead of sending immediately
                        streaming_buffer += delta

                        # Check if we should send: either buffer is full or timeout reached
                        current_time = time.time()
                        time_since_last = current_time - last_chunk_time

                        if len(streaming_buffer) >= MIN_CHUNK_SIZE or (
                                streaming_buffer and time_since_last >= MAX_BUFFER_TIME):
                            chunk = {
                                "id": response_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": streaming_buffer
                                    },
                                    "finish_reason": None
                                }],
                                "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
                            }
                            chunk_data = f"data: {json.dumps(chunk)}\n\n"
                            yield chunk_data
                            
                            # 累积内容用于请求详情
                            accumulated_content += streaming_buffer
                            
                            # Clear buffer and update time after sending
                            streaming_buffer = ""
                            last_chunk_time = current_time
                    else:
                        accumulated_content += delta

                elif prefix == "ad":
                    finish_data = json.loads(content)
                    finish_reason = finish_data.get("finishReason", "stop")

            except (ValueError, json.JSONDecodeError):
                logging.warning(f"STREAMER [ID: {request_id}]: Could not parse data: {raw_data}")
                continue

            # Yield control to event loop after processing
            if is_streaming and model_type == "chat":
                await asyncio.sleep(0.001)  # Small delay to help with network flush
            else:
                await asyncio.sleep(0)

        # --- Final Response Generation ---

        # Flush any remaining buffer content for streaming chat
        if is_streaming and model_type == "chat" and streaming_buffer:
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": streaming_buffer
                    },
                    "finish_reason": None
                }],
                "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            accumulated_content += streaming_buffer
            streaming_buffer = ""

        if model_type in ["image", "video"]:
            logging.info(f"MEDIA [ID: {request_id}]: Found {len(media_urls)} media file(s). Returning URLs directly.")
            # Format the URLs based on their type
            if model_type == "video":
                accumulated_content = "\n".join(media_urls)  # Return raw URLs for videos
            else:  # Default to image handling
                accumulated_content = "\n".join([f"![Generated Image]({url})" for url in media_urls])

        if is_streaming:
            if model_type in ["image", "video"]:
                chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": accumulated_content
                        },
                        "finish_reason": finish_reason or "stop"
                    }],
                    "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            # Send final chunk with finish_reason for chat models
            if model_type == "chat":
                final_chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason or "stop"
                    }],
                    "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"

            # Send [DONE] immediately
            yield "data: [DONE]\n\n"
        else:
            # For non-streaming, send the complete JSON object with the URL content
            complete_response = {
                "id": response_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": accumulated_content
                    },
                    "finish_reason": finish_reason or "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                },
                "system_fingerprint": f"fp_{uuid.uuid4().hex[:8]}"
            }
            yield json.dumps(complete_response)

        # 记录请求成功
        input_tokens = estimateTokens(str(persistent_req.openai_request if persistent_req else {}))
        output_tokens = estimateTokens(accumulated_content)
        log_request_end(request_id, True, input_tokens, output_tokens, response_content=accumulated_content)
        
        # 广播到监控客户端
        await broadcast_to_monitors({
            "type": "request_end",
            "request_id": request_id,
            "success": True,
            "duration": time.time() - start_time
        })

    except asyncio.CancelledError:
        logging.warning(f"GENERATOR [ID: {request_id}]: Client disconnected.")

        # Send abort message to browser if WebSocket is connected
        if browser_ws:
            try:
                await browser_ws.send_text(json.dumps({
                    "type": "abort_request",
                    "request_id": request_id
                }))
                logging.info(f"GENERATOR [ID: {request_id}]: Sent abort message to browser")
            except Exception as e:
                logging.error(f"GENERATOR [ID: {request_id}]: Failed to send abort message: {e}")

        # Re-raise to properly handle the cancellation
        raise

    except KeyboardInterrupt:
        logging.info(f"GENERATOR [ID: {request_id}]: Keyboard interrupt received, cleaning up...")
        raise
    except Exception as e:
        logging.error(f"GENERATOR [ID: {request_id}]: Error: {e}", exc_info=True)
        
        # 记录错误
        log_error(request_id, type(e).__name__, str(e), traceback.format_exc())
        log_request_end(request_id, False, 0, 0, str(e))
        
        # 广播错误到监控客户端
        await broadcast_to_monitors({
            "type": "request_error",
            "request_id": request_id,
            "error": str(e),
            "timestamp": time.time()
        })
        
    finally:
        # Clean up both tracking systems
        if request_id in response_channels:
            del response_channels[request_id]
            logging.info(f"GENERATOR [ID: {request_id}]: Cleaned up response channel.")

        # Mark request as completed in persistent manager
        request_manager.complete_request(request_id)


def create_lmarena_request_body(openai_req: dict) -> (dict, list):
    model_name = openai_req["model"]

    if model_name not in MODEL_REGISTRY:
        raise ValueError(f"Model '{model_name}' not found in registry. Available models: {list(MODEL_REGISTRY.keys())}")

    model_info = MODEL_REGISTRY[model_name]
    model_id = model_info.get("id", model_name)
    modality = model_info.get("type", "chat")
    evaluation_id = str(uuid.uuid4())

    files_to_upload = []
    processed_messages = []

    # Process messages to extract files and clean content
    for msg in openai_req['messages']:
        content = msg.get("content", "")
        new_msg = msg.copy()

        if isinstance(content, list):
            # Handle official multimodal content array
            text_parts = []
            for part in content:
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {}).get("url", "")
                    match = re.match(r"data:(image/\w+);base64,(.*)", image_url)
                    if match:
                        mime_type, base64_data = match.groups()
                        file_ext = mime_type.split('/')
                        filename = f"upload-{uuid.uuid4()}.{file_ext}"
                        files_to_upload.append({"fileName": filename, "contentType": mime_type, "data": base64_data})
            new_msg["content"] = "\n".join(text_parts)
            processed_messages.append(new_msg)

        elif isinstance(content, str):
            # Handle simple string content that might contain data URLs
            text_content = content
            matches = re.findall(r"data:(image/\w+);base64,([a-zA-Z0-9+/=]+)", content)
            if matches:
                logging.info(f"Found {len(matches)} data URL(s) in string content.")
                for mime_type, base64_data in matches:
                    file_ext = mime_type.split('/')
                    filename = f"upload-{uuid.uuid4()}.{file_ext}"
                    files_to_upload.append({"fileName": filename, "contentType": mime_type, "data": base64_data})
                # Remove all found data URLs from the text to be sent
                text_content = re.sub(r"data:image/\w+;base64,[a-zA-Z0-9+/=]+", "", text_content).strip()

            new_msg["content"] = text_content
            processed_messages.append(new_msg)

        else:
            # If content is not a list or string, just pass it through
            processed_messages.append(msg)

    # Find the last user message index
    last_user_message_index = -1
    for i in range(len(processed_messages) - 1, -1, -1):
        if processed_messages[i].get("role") == "user":
            last_user_message_index = i
            break

    # Insert empty user message after the last user message (only for chat models)
    if modality == "chat" and last_user_message_index != -1:
        # Insert empty user message after the last user message
        insert_index = last_user_message_index + 1
        empty_user_message = {"role": "user", "content": " "}
        processed_messages.insert(insert_index, empty_user_message)
        logging.info(
            f"Added empty user message after last user message at index {last_user_message_index} for chat model")

    # Build Arena-formatted messages
    arena_messages = []
    message_ids = [str(uuid.uuid4()) for _ in processed_messages]
    for i, msg in enumerate(processed_messages):
        parent_message_ids = [message_ids[i - 1]] if i > 0 else []

        original_role = msg.get("role")
        role = "user" if original_role not in ["user", "assistant", "data"] else original_role

        arena_messages.append({
            "id": message_ids[i], "role": role, "content": msg['content'],
            "experimental_attachments": [], "parentMessageIds": parent_message_ids,
            "participantPosition": "a", "modelId": model_id if role == 'assistant' else None,
            "evaluationSessionId": evaluation_id, "status": "pending", "failureReason": None,
        })

    user_message_id = message_ids[-1] if message_ids else str(uuid.uuid4())
    model_a_message_id = str(uuid.uuid4())
    arena_messages.append({
        "id": model_a_message_id, "role": "assistant", "content": "",
        "experimental_attachments": [], "parentMessageIds": [user_message_id],
        "participantPosition": "a", "modelId": model_id,
        "evaluationSessionId": evaluation_id, "status": "pending", "failureReason": None,
    })

    payload = {
        "id": evaluation_id, "mode": "direct", "modelAId": model_id,
        "userMessageId": user_message_id, "modelAMessageId": model_a_message_id,
        "messages": arena_messages, "modality": modality,
    }

    return payload, files_to_upload


@app.get("/v1/models")
async def get_models():
    """Lists all available models in an OpenAI-compatible format."""
    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": int(asyncio.get_event_loop().time()),
                "owned_by": "lmarena",
                "type": model_info.get("type", "chat")
            }
            for model_name, model_info in MODEL_REGISTRY.items()
        ],
    }


@app.post("/v1/refresh-models")
async def refresh_models():
    """Request model registry refresh from browser script."""
    if browser_ws:
        try:
            # Send refresh request to browser
            await browser_ws.send_text(json.dumps({
                "type": "refresh_models"
            }))

            return {
                "success": True,
                "message": "Model refresh request sent to browser",
                "models": list(MODEL_REGISTRY.keys())
            }
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logging.error(f"Failed to send refresh request: {e}")
            return {
                "success": False,
                "message": "Failed to send refresh request to browser",
                "models": list(MODEL_REGISTRY.keys())
            }
    else:
        return {
            "success": False,
            "message": "No browser connection available",
            "models": list(MODEL_REGISTRY.keys())
        }

# --- Prometheus Metrics Endpoint ---
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# --- 监控相关API端点 ---
@app.get("/api/stats/summary")
async def get_stats_summary():
    """获取统计摘要"""
    # 从日志文件计算统计
    recent_logs = log_manager.read_request_logs(limit=10000)  # 读取最近的日志
    
    # 计算24小时内的统计
    current_time = time.time()
    day_ago = current_time - 86400
    
    recent_24h_logs = [log for log in recent_logs if log.get('timestamp', 0) > day_ago]
    
    total_requests = len(recent_24h_logs)
    successful = sum(1 for log in recent_24h_logs if log.get('status') == 'success')
    failed = total_requests - successful
    
    total_input_tokens = sum(log.get('input_tokens', 0) for log in recent_24h_logs)
    total_output_tokens = sum(log.get('output_tokens', 0) for log in recent_24h_logs)
    
    durations = [log.get('duration', 0) for log in recent_24h_logs if log.get('duration', 0) > 0]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    # 获取性能统计
    perf_stats = performance_monitor.get_stats()
    model_perf = performance_monitor.get_model_stats()
    
    # 构建模型统计
    model_stats = []
    for model_name, usage in realtime_stats.model_usage.items():
        perf = model_perf.get(model_name, {})
        model_stats.append({
            "model": model_name,
            "total_requests": usage['requests'],
            "successful_requests": usage['requests'] - usage['errors'],
            "failed_requests": usage['errors'],
            "total_input_tokens": usage.get('tokens', 0) // 2,  # 粗略估算
            "total_output_tokens": usage.get('tokens', 0) // 2,
            "avg_duration": perf.get('avg_response_time', 0),
            "qps": perf.get('qps', 0),
            "error_rate": perf.get('error_rate', 0)
        })
    
    return {
        "summary": {
            "total_requests": total_requests,
            "successful": successful,
            "failed": failed,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "avg_duration": avg_duration,
            "success_rate": (successful / total_requests * 100) if total_requests > 0 else 0
        },
        "performance": perf_stats,
        "model_stats": sorted(model_stats, key=lambda x: x['total_requests'], reverse=True),
        "active_requests": len(realtime_stats.active_requests),
        "browser_connected": browser_ws is not None,
        "monitor_clients": len(monitor_clients),
        "uptime": time.time() - startup_time
    }

@app.get("/api/logs/requests")
async def get_request_logs(limit: int = 100, offset: int = 0, model: str = None):
    """获取请求日志"""
    logs = log_manager.read_request_logs(limit, offset, model)
    return logs

@app.get("/api/logs/errors")
async def get_error_logs(limit: int = 50):
    """获取错误日志"""
    logs = log_manager.read_error_logs(limit)
    return logs

@app.get("/api/logs/download")
async def download_logs(log_type: str = "requests"):
    """下载日志文件"""
    if log_type == "requests":
        file_path = log_manager.request_log_path
        filename = "requests.jsonl"
    elif log_type == "errors":
        file_path = log_manager.error_log_path
        filename = "errors.jsonl"
    else:
        raise HTTPException(status_code=400, detail="Invalid log type")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    return StreamingResponse(
        open(file_path, 'rb'),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/request/{request_id}")
async def get_request_details(request_id: str):
    """获取请求详情"""
    details = request_details_storage.get(request_id)
    if not details:
        raise HTTPException(status_code=404, detail="Request details not found")
    
    return {
        "request_id": details.request_id,
        "timestamp": details.timestamp,
        "model": details.model,
        "status": details.status,
        "duration": details.duration,
        "input_tokens": details.input_tokens,
        "output_tokens": details.output_tokens,
        "error": details.error,
        "request_params": details.request_params,
        "request_messages": details.request_messages,
        "response_content": details.response_content,
        "headers": details.headers
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "browser_connected": browser_ws is not None,
        "active_requests": len(request_manager.active_requests),
        "uptime": time.time() - startup_time,
        "models_loaded": len(MODEL_REGISTRY),
        "monitor_clients": len(monitor_clients),
        "log_files": {
            "requests": str(log_manager.request_log_path),
            "errors": str(log_manager.error_log_path)
        }
    }


# --- 新增告警相关API ---
@app.get("/api/alerts")
async def get_alerts(limit: int = 50):
    """获取最近的告警"""
    return list(monitoring_alerts.alert_history)[-limit:]


# --- 配置管理API ---
@app.get("/api/config")
async def get_config():
    """获取当前配置"""
    return config_manager.dynamic_config


@app.post("/api/config")
async def update_config(request: Request):
    """更新配置"""
    try:
        config_data = await request.json()

        # 更新配置
        config_manager._deep_merge(config_manager.dynamic_config, config_data)
        config_manager.save_config()

        # 应用某些配置的即时更改
        if 'request' in config_data:
            if 'timeout_seconds' in config_data['request']:
                Config.REQUEST_TIMEOUT_SECONDS = config_data['request']['timeout_seconds']
            if 'max_concurrent_requests' in config_data['request']:
                Config.MAX_CONCURRENT_REQUESTS = config_data['request']['max_concurrent_requests']

        if 'monitoring' in config_data:
            if 'error_rate_threshold' in config_data['monitoring']:
                monitoring_alerts.alert_thresholds["error_rate"] = config_data['monitoring']['error_rate_threshold']
            if 'response_time_threshold' in config_data['monitoring']:
                monitoring_alerts.alert_thresholds["response_time_p95"] = config_data['monitoring'][
                    'response_time_threshold']

        return {"status": "success", "message": "配置已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/config/quick-links")
async def update_quick_links(request: Request):
    """更新快速链接"""
    try:
        links = await request.json()
        config_manager.set('quick_links', links)
        return {"status": "success", "message": "快速链接已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/system/info")
async def get_system_info():
    """获取系统信息"""
    display_ip = config_manager.get_display_ip()
    port = config_manager.get('network.port', Config.PORT)

    return {
        "server_urls": {
            "local": f"http://localhost:{port}",
            "network": f"http://{display_ip}:{port}",
            "monitor": f"http://{display_ip}:{port}/monitor",
            "metrics": f"http://{display_ip}:{port}/metrics",
            "health": f"http://{display_ip}:{port}/api/health/detailed"
        },
        "detected_ips": get_all_local_ips(),
        "current_ip": display_ip,
        "auto_detect": config_manager.get('network.auto_detect_ip', True)
    }


def get_all_local_ips():
    """获取所有本地IP地址"""
    import socket
    ips = []
    try:
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in all_ips:
            if not ip.startswith('127.') and not ip.startswith('198.18.'):
                ips.append(ip)
    except:
        pass
    return ips


@app.get("/api/health/detailed")
async def get_detailed_health():
    """获取详细的健康状态"""
    error_rate = monitoring_alerts.calculate_error_rate()
    perf_stats = performance_monitor.get_stats()

    # === 新增健康评分系统 ===
    # 添加更多健康指标
    health_score = 100.0
    issues = []

    # 检查错误率（错误率超过10%扣20分）
    if error_rate > 0.1:
        health_score -= 20
        issues.append(f"High error rate: {error_rate:.1%}")
    elif error_rate > 0.05:  # 5-10%之间扣10分
        health_score -= 10
        issues.append(f"Moderate error rate: {error_rate:.1%}")

    # 检查响应时间（P95超过30秒扣15分）
    p95_time = perf_stats.get("p95_response_time", 0)
    if p95_time > 30:
        health_score -= 15
        issues.append(f"Slow P95 response time: {p95_time:.1f}s")
    elif p95_time > 15:  # 15-30秒之间扣7分
        health_score -= 7
        issues.append(f"Moderate P95 response time: {p95_time:.1f}s")

    # 检查浏览器连接（断线扣30分）
    if not browser_ws:
        health_score -= 30
        issues.append("Browser WebSocket disconnected")

    # 检查活跃请求数（超过80%容量扣10分）
    active_count = len(realtime_stats.active_requests)
    capacity_usage = active_count / Config.MAX_CONCURRENT_REQUESTS
    if capacity_usage > 0.8:
        health_score -= 10
        issues.append(f"High active requests: {active_count}/{Config.MAX_CONCURRENT_REQUESTS} ({capacity_usage:.0%})")
    elif capacity_usage > 0.6:  # 60-80%之间扣5分
        health_score -= 5
        issues.append(
            f"Moderate active requests: {active_count}/{Config.MAX_CONCURRENT_REQUESTS} ({capacity_usage:.0%})")

    # 检查监控客户端（没有监控客户端扣5分）
    if len(monitor_clients) == 0:
        health_score -= 5
        issues.append("No monitoring clients connected")

    # 确保分数在0-100之间
    health_score = max(0, min(100, health_score))

    # 决定健康状态
    if health_score >= 70:
        status = "healthy"
        status_emoji = "✅"
    elif health_score >= 40:
        status = "degraded"
        status_emoji = "⚠️"
    else:
        status = "unhealthy"
        status_emoji = "❌"

    # === 评分系统结束 ===

    return {
        "status": status,
        "status_emoji": status_emoji,
        "health_score": health_score,
        "issues": issues,
        "recommendations": get_health_recommendations(issues),  # 新增建议
        "metrics": {
            "error_rate": error_rate,
            "error_rate_percent": f"{error_rate:.1%}",
            "response_time_p50": perf_stats.get("p50_response_time", 0),
            "response_time_p95": perf_stats.get("p95_response_time", 0),
            "response_time_p99": perf_stats.get("p99_response_time", 0),
            "qps": perf_stats.get("qps", 0),
            "active_requests": active_count,
            "capacity_usage": f"{capacity_usage:.0%}",
            "browser_connected": browser_ws is not None,
            "monitor_clients": len(monitor_clients),
            "uptime": time.time() - startup_time,
            "uptime_hours": (time.time() - startup_time) / 3600
        },
        "thresholds": monitoring_alerts.alert_thresholds
    }


def get_health_recommendations(issues):
    """根据问题提供建议"""
    recommendations = []

    for issue in issues:
        if "error rate" in issue.lower():
            recommendations.append("Check server logs for error patterns")
        elif "response time" in issue.lower():
            recommendations.append("Consider reducing concurrent requests or optimizing model selection")
        elif "browser" in issue.lower():
            recommendations.append("Ensure browser extension is running and connected")
        elif "active requests" in issue.lower():
            recommendations.append("Consider increasing MAX_CONCURRENT_REQUESTS if server can handle it")
        elif "monitoring" in issue.lower():
            recommendations.append("Open /monitor in a browser to track system health")

    return recommendations


# --- 监控面板HTML (优化版) ---
@app.get("/monitor", response_class=HTMLResponse)
async def monitor_dashboard():
    """监控面板"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LMArena 监控面板</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f3f4f6;
            color: #111827;
        }
        
        .header {
            background: white;
            padding: 16px 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: 24px;
            font-weight: 600;
        }
        
        .header-info {
            display: flex;
            align-items: center;
            gap: 24px;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: #f3f4f6;
            border-radius: 20px;
            font-size: 14px;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #dc2626;
        }
        
        .status-dot.connected {
            background: #10b981;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .stat-card h3 {
            font-size: 14px;
            color: #6b7280;
            margin-bottom: 8px;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: 600;
            color: #111827;
        }
        
        .stat-subtitle {
            font-size: 12px;
            color: #9ca3af;
            margin-top: 4px;
        }
        
        .stat-change {
            font-size: 14px;
            margin-top: 4px;
        }
        
        .stat-change.positive {
            color: #10b981;
        }
        
        .stat-change.negative {
            color: #dc2626;
        }
        
        .section {
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 24px;
            overflow: hidden;
        }
        
        .section-header {
            padding: 16px 20px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .section-title {
            font-size: 18px;
            font-weight: 600;
        }
        
        .tabs {
            display: flex;
            border-bottom: 1px solid #e5e7eb;
        }
        
        .tab {
            padding: 12px 24px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: #6b7280;
            border-bottom: 2px solid transparent;
            transition: all 0.2s;
        }
        
        .tab:hover {
            color: #111827;
        }
        
        .tab.active {
            color: #4f46e5;
            border-bottom-color: #4f46e5;
        }
        
        .table-container {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #f9fafb;
            padding: 12px 16px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        td {
            padding: 12px 16px;
            border-top: 1px solid #e5e7eb;
            font-size: 14px;
        }
        
        tr:hover {
            background: #f9fafb;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .status-badge.success {
            background: #d1fae5;
            color: #059669;
        }
        
        .status-badge.failed {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .status-badge.active {
            background: #dbeafe;
            color: #2563eb;
        }
        
        .active-request {
            padding: 16px;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .active-request:last-child {
            border-bottom: none;
        }
        
        .request-info {
            flex: 1;
        }
        
        .request-id {
            font-family: monospace;
            font-size: 12px;
            color: #6b7280;
        }
        
        .request-model {
            font-weight: 500;
            margin-top: 4px;
        }
        
        .request-duration {
            font-size: 14px;
            color: #6b7280;
        }
        
        .empty-state {
            text-align: center;
            padding: 48px;
            color: #6b7280;
        }
        
        .refresh-btn {
            padding: 8px 16px;
            background: #4f46e5;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .refresh-btn:hover {
            background: #4338ca;
        }
        
        .download-btn {
            padding: 6px 12px;
            background: #059669;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            transition: background 0.2s;
            text-decoration: none;
            display: inline-block;
        }
        
        .download-btn:hover {
            background: #047857;
        }
        
        .error-log {
            padding: 12px;
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 6px;
            margin-bottom: 8px;
        }
        
        .error-type {
            font-weight: 600;
            color: #dc2626;
            margin-bottom: 4px;
        }
        
        .error-message {
            font-size: 14px;
            color: #991b1b;
            word-break: break-word;
        }
        
        .error-time {
            font-size: 12px;
            color: #b91c1c;
            margin-top: 4px;
        }
        
        .model-card {
            padding: 16px;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            margin-bottom: 12px;
        }
        
        .model-name {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
        }
        
        .model-stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            font-size: 14px;
        }
        
        .model-stat-label {
            color: #6b7280;
        }
        
        .model-stat-value {
            font-weight: 500;
        }
        
        .performance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 16px;
            padding: 16px;
        }
        
        .perf-item {
            text-align: center;
        }
        
        .perf-value {
            font-size: 24px;
            font-weight: 600;
            color: #4f46e5;
        }
        
        .perf-label {
            font-size: 12px;
            color: #6b7280;
            margin-top: 4px;
        }
        
        .info-text {
            font-size: 12px;
            color: #6b7280;
            margin: 8px 0;
        }
        
        .detail-btn {
            padding: 4px 8px;
            background: #f3f4f6;
            border: none;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .detail-btn:hover {
            background: #e5e7eb;
        }
        
        /* 模态框样式 */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        
        .modal-content {
            position: relative;
            background-color: white;
            margin: 5% auto;
            padding: 20px;
            width: 80%;
            max-width: 800px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            max-height: 80vh;
            overflow-y: auto;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .modal-title {
            font-size: 20px;
            font-weight: 600;
        }
        
        .close {
            font-size: 28px;
            font-weight: bold;
            color: #aaa;
            cursor: pointer;
            transition: color 0.2s;
        }
        
        .close:hover {
            color: #000;
        }
        
        .detail-section {
            margin-bottom: 20px;
        }
        
        .detail-section h3 {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
            color: #374151;
        }
        
        .detail-item {
            display: flex;
            margin-bottom: 8px;
            font-size: 14px;
        }
        
        .detail-label {
            font-weight: 500;
            color: #6b7280;
            min-width: 120px;
        }
        
        .detail-value {
            color: #111827;
            word-break: break-word;
        }
        
        .message-box {
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 8px;
        }
        
        .message-role {
            font-weight: 600;
            color: #4f46e5;
            margin-bottom: 4px;
        }
        
        .message-content {
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .response-content {
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 12px;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .metrics-link {
            margin-left: 16px;
            padding: 8px 16px;
            background: #f3f4f6;
            color: #374151;
            text-decoration: none;
            border-radius: 6px;
            font-size: 14px;
            transition: background 0.2s;
        }
        
        .metrics-link:hover {
            background: #e5e7eb;
        }
        /* 告警样式 */
        .alert-section {
            position: relative;
        }
        
        .alert-item {
            padding: 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
 
        .alert-item.warning {
            background: #fef3c7;
            border: 1px solid #f59e0b;
        }
 
        .alert-item.critical {
            background: #fee2e2;
            border: 1px solid #dc2626;
        }
 
        .alert-message {
            font-weight: 500;
            color: #374151;
        }
 
        .alert-time {
            font-size: 12px;
            color: #6b7280;
            margin-top: 4px;
        }
 
        .badge {
            background: #ef4444;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-left: 8px;
            font-weight: 600;
        }
        /* API文档样式 */
        .api-category {
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
        }

        .api-item {
            margin-bottom: 16px;
            padding-bottom: 16px;
            border-bottom: 1px solid #e5e7eb;
        }

        .api-item:last-child {
            margin-bottom: 0;
            padding-bottom: 0;
            border-bottom: none;
        }

        .api-endpoint {
            font-family: monospace;
            font-size: 14px;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 4px;
        }

        .api-description {
            font-size: 13px;
            color: #6b7280;
            line-height: 1.5;
        }
        /* 设置面板样式 */
        .settings-group {
            background: #f9fafb;
            padding: 20px;
            border-radius: 8px;
        }

        .setting-item {
            margin-bottom: 16px;
        }

        .setting-item label {
            display: inline-block;
            font-weight: 500;
            color: #374151;
            margin-bottom: 4px;
            min-width: 200px;
        }

        .save-btn {
            padding: 6px 16px;
            background: #10b981;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
            transition: background 0.2s;
        }

        .save-btn:hover {
            background: #059669;
        }

    </style>
</head>
<body>
    <header class="header">
        <h1>LMArena 监控面板</h1>
        <div class="header-info">
            <a href="/metrics" class="metrics-link" target="_blank">Prometheus Metrics</a>
            <div class="info-text" id="server-info">正在连接...</div>
            <div class="status-indicator">
                <span class="status-dot" id="ws-status"></span>
                <span id="ws-status-text">未连接</span>
            </div>
        </div>
    </header>
    
    <div class="container">
    <!-- 在 <div class="container"> 内部，统计卡片之前添加 -->

        <!-- API 端点说明 -->
        <!-- 系统设置 -->
<div class="section" id="settings-section">
    <div class="section-header">
        <h2 class="section-title">⚙️ 系统设置</h2>
        <button class="refresh-btn" onclick="toggleSettings()">显示/隐藏</button>
    </div>
    <div id="settings-content" style="padding: 20px; display: none;">
        <!-- 网络设置 -->
        <div class="settings-group">
            <h3 style="margin-bottom: 16px; color: #4f46e5;">🌐 网络设置</h3>
            <div class="setting-item">
                <label>IP地址设置:</label>
                <div style="margin-top: 8px;">
                    <label style="margin-right: 20px;">
                        <input type="radio" name="ip-mode" id="auto-ip" checked onchange="toggleIpMode()">
                        自动检测
                    </label>
                    <label>
                        <input type="radio" name="ip-mode" id="manual-ip" onchange="toggleIpMode()">
                        手动设置
                    </label>
                </div>
                <div id="manual-ip-input" style="display: none; margin-top: 8px;">
                    <input type="text" id="manual-ip-value" placeholder="例如: 192.168.0.15" 
                           style="padding: 6px 12px; border: 1px solid #e5e7eb; border-radius: 4px;">
                    <button class="save-btn" onclick="saveNetworkSettings()">保存</button>
                </div>
                <div id="detected-ips" style="margin-top: 8px; font-size: 12px; color: #6b7280;"></div>
            </div>
        </div>

        <!-- 请求设置 -->
        <div class="settings-group" style="margin-top: 24px;">
            <h3 style="margin-bottom: 16px; color: #10b981;">📡 请求设置</h3>
            <div class="setting-item">
                <label>请求超时时间 (秒):</label>
                <input type="number" id="timeout-seconds" min="30" max="600" 
                       style="width: 100px; padding: 6px 12px; border: 1px solid #e5e7eb; border-radius: 4px;">
            </div>
            <div class="setting-item" style="margin-top: 12px;">
                <label>最大并发请求数:</label>
                <input type="number" id="max-concurrent" min="1" max="100" 
                       style="width: 100px; padding: 6px 12px; border: 1px solid #e5e7eb; border-radius: 4px;">
            </div>
            <button class="save-btn" style="margin-top: 12px;" onclick="saveRequestSettings()">保存请求设置</button>
        </div>

        <!-- 监控告警设置 -->
        <div class="settings-group" style="margin-top: 24px;">
            <h3 style="margin-bottom: 16px; color: #f59e0b;">🚨 告警阈值</h3>
            <div class="setting-item">
                <label>错误率告警阈值 (%):</label>
                <input type="number" id="error-threshold" min="1" max="100" step="1"
                       style="width: 100px; padding: 6px 12px; border: 1px solid #e5e7eb; border-radius: 4px;">
            </div>
            <div class="setting-item" style="margin-top: 12px;">
                <label>响应时间告警阈值 (秒):</label>
                <input type="number" id="response-threshold" min="1" max="300" 
                       style="width: 100px; padding: 6px 12px; border: 1px solid #e5e7eb; border-radius: 4px;">
            </div>
            <button class="save-btn" style="margin-top: 12px;" onclick="saveMonitoringSettings()">保存告警设置</button>
        </div>

        <!-- 当前访问地址 -->
        <div class="settings-group" style="margin-top: 24px; background: #f9fafb; padding: 16px; border-radius: 8px;">
            <h3 style="margin-bottom: 16px;">📍 当前访问地址</h3>
            <div id="current-urls" style="font-family: monospace; font-size: 14px; line-height: 1.8;"></div>
        </div>
    </div>
</div>

        <div class="section" id="api-docs-section">
            <div class="section-header">
                <h2 class="section-title">API 端点说明</h2>
                <button class="refresh-btn" onclick="toggleApiDocs()">显示/隐藏</button>
            </div>
            <div id="api-docs-content" style="padding: 20px; display: none;">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px;">
                    <!-- AI API -->
                    <div class="api-category">
                        <h3 style="color: #4f46e5; margin-bottom: 12px;">🤖 AI API</h3>
                        <div class="api-item">
                            <div class="api-endpoint">POST /v1/chat/completions</div>
                            <div class="api-description">OpenAI兼容的聊天API，支持流式输出</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /v1/models</div>
                            <div class="api-description">获取所有可用的AI模型列表</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">POST /v1/refresh-models</div>
                            <div class="api-description">手动刷新模型列表</div>
                        </div>
                    </div>
                    
                    <!-- 监控与健康 -->
                    <div class="api-category">
                        <h3 style="color: #10b981; margin-bottom: 12px;">📊 监控与健康</h3>
                        <div class="api-item">
                            <div class="api-endpoint">GET /monitor</div>
                            <div class="api-description">实时监控面板（当前页面）</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /metrics</div>
                            <div class="api-description">Prometheus格式的性能指标</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /health</div>
                            <div class="api-description">基础健康检查</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/health/detailed</div>
                            <div class="api-description">详细健康状态，包含0-100分的健康评分</div>
                        </div>
                    </div>
                    
                    <!-- 统计与日志 -->
                    <div class="api-category">
                        <h3 style="color: #f59e0b; margin-bottom: 12px;">📈 统计与日志</h3>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/stats/summary</div>
                            <div class="api-description">24小时内的统计摘要</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/logs/requests?limit=100</div>
                            <div class="api-description">获取请求日志（支持分页）</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/logs/errors?limit=50</div>
                            <div class="api-description">获取错误日志</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/logs/download?log_type=requests</div>
                            <div class="api-description">下载日志文件（requests/errors）</div>
                        </div>
                    </div>
                    
                    <!-- 其他功能 -->
                    <div class="api-category">
                        <h3 style="color: #dc2626; margin-bottom: 12px;">🔍 其他功能</h3>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/request/{request_id}</div>
                            <div class="api-description">获取特定请求的详细信息</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">GET /api/alerts?limit=50</div>
                            <div class="api-description">获取系统告警历史</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">WS /ws</div>
                            <div class="api-description">浏览器WebSocket连接端点</div>
                        </div>
                        <div class="api-item">
                            <div class="api-endpoint">WS /ws/monitor</div>
                            <div class="api-description">监控面板WebSocket连接</div>
                        </div>
                    </div>
                </div>
                
                <!-- 使用示例 -->
                <div style="margin-top: 30px; padding: 20px; background: #f9fafb; border-radius: 8px;">
                    <h3 style="margin-bottom: 12px;">💡 快速使用示例</h3>
                    <div style="font-family: monospace; background: #1f2937; color: #10b981; padding: 16px; border-radius: 6px; overflow-x: auto;">
                        <div># Python 示例</div>
                        <div>from openai import OpenAI</div>
                        <div></div>
                        <div>client = OpenAI(</div>
                        <div>    base_url="http://${window.location.hostname}:${window.location.port}/v1",</div>
                        <div>    api_key="sk-any-string-you-like"</div>
                        <div>)</div>
                        <div></div>
                        <div>response = client.chat.completions.create(</div>
                        <div>    model="claude-3-5-sonnet-20241022",</div>
                        <div>    messages=[{"role": "user", "content": "Hello!"}],</div>
                        <div>    stream=True</div>
                        <div>)</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="stat-card">
                <h3>活跃请求</h3>
                <div class="stat-value" id="active-requests">0</div>
                <div class="stat-subtitle" id="browser-status">浏览器未连接</div>
            </div>
            <div class="stat-card">
                <h3>总请求数（24h）</h3>
                <div class="stat-value" id="total-requests">0</div>
                <div class="stat-subtitle" id="success-rate-text">成功率: 0%</div>
            </div>
            <div class="stat-card">
                <h3>平均响应时间</h3>
                <div class="stat-value" id="avg-duration">0s</div>
                <div class="stat-subtitle">P95: <span id="p95-duration">0s</span></div>
            </div>
            <div class="stat-card">
                <h3>QPS</h3>
                <div class="stat-value" id="qps">0</div>
                <div class="stat-subtitle">每秒请求数</div>
            </div>
            <div class="stat-card">
                <h3>总Token数（24h）</h3>
                <div class="stat-value" id="total-tokens">0</div>
                <div class="stat-subtitle">输入+输出</div>
            </div>
            <div class="stat-card">
                <h3>监控客户端</h3>
                <div class="stat-value" id="monitor-clients">0</div>
                <div class="stat-subtitle">在线监控数</div>
            </div>
        </div>
        
        <!-- 性能指标 -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">性能指标</h2>
            </div>
            <div class="performance-grid" id="performance-metrics">
                <div class="perf-item">
                    <div class="perf-value" id="p50-time">0ms</div>
                    <div class="perf-label">P50 响应时间</div>
                </div>
                <div class="perf-item">
                    <div class="perf-value" id="p95-time">0ms</div>
                    <div class="perf-label">P95 响应时间</div>
                </div>
                <div class="perf-item">
                    <div class="perf-value" id="p99-time">0ms</div>
                    <div class="perf-label">P99 响应时间</div>
                </div>
                <div class="perf-item">
                    <div class="perf-value" id="uptime">0h</div>
                    <div class="perf-label">运行时间</div>
                </div>
            </div>
        </div>
                <!-- 系统告警 -->
        <div class="section alert-section">
            <div class="section-header">
                <h2 class="section-title">
                    系统告警
                    <span id="alert-count" class="badge" style="display: none;">0</span>
                </h2>
                <button class="refresh-btn" onclick="loadAlerts()">刷新告警</button>
            </div>
            <div id="alerts-container" style="padding: 20px; max-height: 300px; overflow-y: auto;">
                <div class="empty-state">暂无告警</div>
            </div>
        </div>
        <!-- 活跃请求 -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">活跃请求</h2>
                <button class="refresh-btn" onclick="refreshData()">刷新</button>
            </div>
            <div id="active-requests-list">
                <div class="empty-state">暂无活跃请求</div>
            </div>
        </div>
        
        <!-- 模型使用统计 -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">模型使用统计</h2>
            </div>
            <div style="padding: 20px;">
                <div id="model-stats-list">
                    <div class="empty-state">加载中...</div>
                </div>
            </div>
        </div>
        
        <!-- 请求日志 -->
        <div class="section">
            <div class="section-header">
                <h2 class="section-title">日志</h2>
                <div>
                    <a href="/api/logs/download?log_type=requests" class="download-btn">下载请求日志</a>
                    <a href="/api/logs/download?log_type=errors" class="download-btn" style="margin-left: 8px;">下载错误日志</a>
                </div>
            </div>
            <div class="tabs">
                <div class="tab active" onclick="switchTab('requests')">请求日志</div>
                <div class="tab" onclick="switchTab('errors')">错误日志</div>
            </div>
            
            <div id="requests-tab" class="tab-content">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>时间</th>
                                <th>请求ID</th>
                                <th>模型</th>
                                <th>状态</th>
                                <th>输入/输出 Tokens</th>
                                <th>耗时</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody id="request-logs">
                            <tr><td colspan="7" style="text-align: center;">加载中...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="errors-tab" class="tab-content" style="display: none;">
                <div style="padding: 20px;" id="error-logs">
                    <div class="empty-state">暂无错误日志</div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- 请求详情模态框 -->
    <div id="detailModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title">请求详情</h2>
                <span class="close" onclick="closeModal()">&times;</span>
            </div>
            <div id="modalBody">
                <div class="empty-state">加载中...</div>
            </div>
        </div>
    </div>
    
    <script>
        let ws = null;
        let currentTab = 'requests';
        let stats = {};
        
        // 切换API文档显示
        function toggleApiDocs() {
            const content = document.getElementById('api-docs-content');
            if (content.style.display === 'none') {
                content.style.display = 'block';
            } else {
                content.style.display = 'none';
            }
        }

        // 连接WebSocket
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/monitor`);
            
            ws.onopen = () => {
                console.log('监控WebSocket已连接');
                updateConnectionStatus(true);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
            
            ws.onclose = () => {
                console.log('监控WebSocket已断开');
                updateConnectionStatus(false);
                // 5秒后重连
                setTimeout(connectWebSocket, 5000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket错误:', error);
            };
        }
        
        // 处理WebSocket消息
        function handleWebSocketMessage(data) {
            switch(data.type) {
                case 'initial_data':
                    updateAllData(data);
                    break;
                case 'request_start':
                    addActiveRequest(data);
                    break;
                case 'request_end':
                    removeActiveRequest(data.request_id);
                    refreshLogs();
                    break;
                case 'stats_update':
                    updateStats(data.stats);
                    break;
                case 'alert':
                    handleAlert(data.alert);
                    break;
            }
        }
        
        // 更新连接状态
        function updateConnectionStatus(connected) {
            const dot = document.getElementById('ws-status');
            const text = document.getElementById('ws-status-text');
            
            if (connected) {
                dot.classList.add('connected');
                text.textContent = '已连接';
            } else {
                dot.classList.remove('connected');
                text.textContent = '未连接';
            }
        }
        
        // 更新所有数据
        function updateAllData(data) {
            // 更新活跃请求
            updateActiveRequests(data.active_requests);
            
            // 更新统计
            refreshStats();
            
            // 更新日志
            refreshLogs();
        }
        
        // 格式化时间
        function formatDuration(seconds) {
            if (seconds < 1) return (seconds * 1000).toFixed(0) + 'ms';
            if (seconds < 60) return seconds.toFixed(1) + 's';
            if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
            return Math.floor(seconds / 3600) + 'h';
        }
        
        // 格式化大数字
        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }
        
        // 更新活跃请求列表
        function updateActiveRequests(requests) {
            const container = document.getElementById('active-requests-list');
            const count = Object.keys(requests).length;
            
            document.getElementById('active-requests').textContent = count;
            
            if (count === 0) {
                container.innerHTML = '<div class="empty-state">暂无活跃请求</div>';
                return;
            }
            
            container.innerHTML = Object.entries(requests).map(([id, req]) => {
                const duration = ((Date.now() / 1000) - req.start_time).toFixed(1);
                return `
                    <div class="active-request">
                        <div class="request-info">
                            <div class="request-id">${id}</div>
                            <div class="request-model">${req.model}</div>
                        </div>
                        <div class="request-duration">${duration}s</div>
                        <span class="status-badge active">处理中</span>
                    </div>
                `;
            }).join('');
        }
        
        // 添加活跃请求
        function addActiveRequest(data) {
            const count = parseInt(document.getElementById('active-requests').textContent) + 1;
            document.getElementById('active-requests').textContent = count;
            refreshActiveRequests();
        }
        
        // 移除活跃请求
        function removeActiveRequest(requestId) {
            const count = Math.max(0, parseInt(document.getElementById('active-requests').textContent) - 1);
            document.getElementById('active-requests').textContent = count;
            refreshActiveRequests();
        }
        
        // 刷新统计数据
        async function refreshStats() {
            try {
                const response = await fetch('/api/stats/summary');
                const data = await response.json();
                
                // 更新基础统计
                document.getElementById('total-requests').textContent = formatNumber(data.summary.total_requests || 0);
                document.getElementById('success-rate-text').textContent = `成功率: ${data.summary.success_rate?.toFixed(1) || 0}%`;
                document.getElementById('avg-duration').textContent = formatDuration(data.summary.avg_duration || 0);
                document.getElementById('total-tokens').textContent = formatNumber((data.summary.total_input_tokens || 0) + (data.summary.total_output_tokens || 0));
                
                // 更新性能指标
                if (data.performance) {
                    document.getElementById('qps').textContent = data.performance.qps?.toFixed(2) || '0';
                    document.getElementById('p50-time').textContent = formatDuration(data.performance.p50_response_time || 0);
                    document.getElementById('p95-time').textContent = formatDuration(data.performance.p95_response_time || 0);
                    document.getElementById('p95-duration').textContent = formatDuration(data.performance.p95_response_time || 0);
                    document.getElementById('p99-time').textContent = formatDuration(data.performance.p99_response_time || 0);
                }
                
                // 更新服务器信息
                document.getElementById('browser-status').textContent = data.browser_connected ? '浏览器已连接' : '浏览器未连接';
                document.getElementById('monitor-clients').textContent = data.monitor_clients || 0;
                
                if (data.uptime) {
                    document.getElementById('uptime').textContent = formatDuration(data.uptime);
                    document.getElementById('server-info').textContent = `服务器运行时间: ${formatDuration(data.uptime)} | 已加载 ${data.models_loaded || 0} 个模型`;
                }
                
                // 更新模型统计
                updateModelStats(data.model_stats);
                
            } catch (error) {
                console.error('获取统计数据失败:', error);
            }
        }
        
        // 更新模型统计
        function updateModelStats(modelStats) {
            const container = document.getElementById('model-stats-list');
            
            if (!modelStats || modelStats.length === 0) {
                container.innerHTML = '<div class="empty-state">暂无模型使用数据</div>';
                return;
            }
            
            container.innerHTML = modelStats.map(stat => {
                const successRate = stat.total_requests > 0 
                    ? ((stat.successful_requests / stat.total_requests) * 100).toFixed(1)
                    : 0;
                
                const errorRate = (stat.error_rate * 100).toFixed(1);
                    
                return `
                    <div class="model-card">
                        <div class="model-name">${stat.model}</div>
                        <div class="model-stats">
                            <div>
                                <span class="model-stat-label">总请求:</span>
                                <span class="model-stat-value">${formatNumber(stat.total_requests)}</span>
                            </div>
                            <div>
                                <span class="model-stat-label">成功率:</span>
                                <span class="model-stat-value">${successRate}%</span>
                            </div>
                            <div>
                                <span class="model-stat-label">平均耗时:</span>
                                <span class="model-stat-value">${formatDuration(stat.avg_duration)}</span>
                            </div>
                            <div>
                                <span class="model-stat-label">QPS:</span>
                                <span class="model-stat-value">${stat.qps?.toFixed(3) || 0}</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        // 刷新日志
        async function refreshLogs() {
            if (currentTab === 'requests') {
                await refreshRequestLogs();
            } else {
                await refreshErrorLogs();
            }
        }
        
        // 刷新请求日志
        async function refreshRequestLogs() {
            try {
                const response = await fetch('/api/logs/requests?limit=50');
                const logs = await response.json();
                
                const tbody = document.getElementById('request-logs');
                
                if (logs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center;">暂无请求日志</td></tr>';
                    return;
                }
                
                tbody.innerHTML = logs.map(log => {
                    const time = new Date(log.timestamp * 1000).toLocaleString();
                    const statusClass = log.status === 'success' ? 'success' : 'failed';
                    const duration = log.duration ? formatDuration(log.duration) : '-';
                    
                    return `
                        <tr>
                            <td>${time}</td>
                            <td style="font-family: monospace; font-size: 12px;" title="${log.request_id}">${log.request_id.substring(0, 8)}...</td>
                            <td>${log.model}</td>
                            <td><span class="status-badge ${statusClass}">${log.status}</span></td>
                            <td>${log.input_tokens || 0} / ${log.output_tokens || 0}</td>
                            <td>${duration}</td>
                            <td>
                                <button class="detail-btn" onclick="viewRequestDetails('${log.request_id}')">详情</button>
                            </td>
                        </tr>
                    `;
                }).join('');
                
            } catch (error) {
                console.error('获取请求日志失败:', error);
            }
        }
        
        // 刷新错误日志
        async function refreshErrorLogs() {
            try {
                const response = await fetch('/api/logs/errors?limit=30');
                const logs = await response.json();
                
                const container = document.getElementById('error-logs');
                
                if (logs.length === 0) {
                    container.innerHTML = '<div class="empty-state">暂无错误日志</div>';
                    return;
                }
                
                container.innerHTML = logs.map(log => {
                    const time = new Date(log.timestamp * 1000).toLocaleString();
                    
                    return `
                        <div class="error-log">
                            <div class="error-type">${log.error_type}</div>
                            <div class="error-message">${log.error_message}</div>
                            <div class="error-time">${time} - 请求ID: ${log.request_id || 'N/A'}</div>
                        </div>
                    `;
                }).join('');
                
            } catch (error) {
                console.error('获取错误日志失败:', error);
            }
        }
        
        // 刷新活跃请求
        async function refreshActiveRequests() {
            // 这里可以调用API获取最新的活跃请求
            // 暂时通过WebSocket更新
        }
        
        // 切换标签页
        function switchTab(tab) {
            currentTab = tab;
            
            // 更新标签样式
            document.querySelectorAll('.tab').forEach(t => {
                t.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // 切换内容
            document.getElementById('requests-tab').style.display = tab === 'requests' ? 'block' : 'none';
            document.getElementById('errors-tab').style.display = tab === 'errors' ? 'block' : 'none';
            
            refreshLogs();
        }
        
        // 查看请求详情
        async function viewRequestDetails(requestId) {
            const modal = document.getElementById('detailModal');
            const modalBody = document.getElementById('modalBody');
            
            modal.style.display = 'block';
            modalBody.innerHTML = '<div class="empty-state">加载中...</div>';
            
            try {
                const response = await fetch(`/api/request/${requestId}`);
                if (!response.ok) {
                    throw new Error('请求详情不存在');
                }
                
                const details = await response.json();
                
                modalBody.innerHTML = `
                    <div class="detail-section">
                        <h3>基本信息</h3>
                        <div class="detail-item">
                            <div class="detail-label">请求ID:</div>
                            <div class="detail-value">${details.request_id}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">时间:</div>
                            <div class="detail-value">${new Date(details.timestamp * 1000).toLocaleString()}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">模型:</div>
                            <div class="detail-value">${details.model}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">状态:</div>
                            <div class="detail-value"><span class="status-badge ${details.status === 'success' ? 'success' : 'failed'}">${details.status}</span></div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">耗时:</div>
                            <div class="detail-value">${formatDuration(details.duration)}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">Token使用:</div>
                            <div class="detail-value">输入: ${details.input_tokens}, 输出: ${details.output_tokens}</div>
                        </div>
                        ${details.error ? `
                        <div class="detail-item">
                            <div class="detail-label">错误:</div>
                            <div class="detail-value" style="color: #dc2626;">${details.error}</div>
                        </div>
                        ` : ''}
                    </div>
                    
                    <div class="detail-section">
                        <h3>请求参数</h3>
                        <div class="detail-item">
                            <div class="detail-label">Temperature:</div>
                            <div class="detail-value">${details.request_params.temperature || 'N/A'}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">Top P:</div>
                            <div class="detail-value">${details.request_params.top_p || 'N/A'}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">Max Tokens:</div>
                            <div class="detail-value">${details.request_params.max_tokens || 'N/A'}</div>
                        </div>
                        <div class="detail-item">
                            <div class="detail-label">流式输出:</div>
                            <div class="detail-value">${details.request_params.streaming ? '是' : '否'}</div>
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h3>请求消息</h3>
                        ${details.request_messages.map(msg => `
                            <div class="message-box">
                                <div class="message-role">${msg.role}</div>
                                <div class="message-content">${msg.content}</div>
                            </div>
                        `).join('')}
                    </div>
                    
                    <div class="detail-section">
                        <h3>响应内容</h3>
                        <div class="response-content">${details.response_content || '(无响应内容)'}</div>
                    </div>
                `;
                
            } catch (error) {
                modalBody.innerHTML = `<div class="empty-state">加载失败: ${error.message}</div>`;
            }
        }
        
        // 关闭模态框
        function closeModal() {
            document.getElementById('detailModal').style.display = 'none';
        }
        
        // 点击模态框外部关闭
        window.onclick = function(event) {
            const modal = document.getElementById('detailModal');
            if (event.target == modal) {
                modal.style.display = 'none';
            }
        }
                // 处理告警消息
        function handleAlert(alert) {
            const container = document.getElementById('alerts-container');
            const alertElement = document.createElement('div');
            alertElement.className = `alert-item ${alert.severity}`;
            alertElement.innerHTML = `
                <div style="flex: 1;">
                    <div class="alert-message">${alert.message}</div>
                    <div class="alert-time">${new Date(alert.timestamp * 1000).toLocaleTimeString()}</div>
                </div>
            `;
            
            // 如果是第一个告警，清空"暂无告警"
            if (container.querySelector('.empty-state')) {
                container.innerHTML = '';
            }
            
            // 添加到顶部
            container.insertBefore(alertElement, container.firstChild);
            
            // 更新告警计数
            const count = container.children.length;
            const badge = document.getElementById('alert-count');
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-block' : 'none';
            
            // 只保留最近20个告警
            while (container.children.length > 20) {
                container.removeChild(container.lastChild);
            }
            
            // 如果是严重告警，可以添加声音提示
            if (alert.severity === 'critical') {
                // 可选：播放提示音
                // const audio = new Audio('alert.mp3');
                // audio.play();
            }
        }
        
        // 加载历史告警
        async function loadAlerts() {
            try {
                const response = await fetch('/api/alerts');
                const alerts = await response.json();
                
                const container = document.getElementById('alerts-container');
                if (alerts.length === 0) {
                    container.innerHTML = '<div class="empty-state">暂无告警</div>';
                    document.getElementById('alert-count').style.display = 'none';
                } else {
                    container.innerHTML = '';
                    // 反向遍历，最新的在前
                    alerts.reverse().forEach(alert => handleAlert(alert));
                }
            } catch (error) {
                console.error('加载告警失败:', error);
            }
        }
        // 刷新数据
        function refreshData() {
            refreshStats();
            refreshLogs();
            refreshActiveRequests();
        }
        
        // 定时刷新
        setInterval(() => {
            refreshStats();
        }, 5000); // 每5秒刷新统计
        
        setInterval(() => {
            if (currentTab === 'requests') {
                refreshRequestLogs();
            }
        }, 10000); // 每10秒刷新日志
        
        setInterval(() => {
            // 不需要频繁刷新告警，因为有WebSocket推送
            // loadAlerts();
        }, 30000); // 每30秒刷新一次告警历史
        // === 设置管理功能 ===
let currentConfig = {};

// 切换设置显示
function toggleSettings() {
    const content = document.getElementById('settings-content');
    if (content.style.display === 'none') {
        content.style.display = 'block';
        loadSettings();
    } else {
        content.style.display = 'none';
    }
}

// 加载设置
async function loadSettings() {
    try {
        // 获取配置
        const configResponse = await fetch('/api/config');
        currentConfig = await configResponse.json();
        
        // 获取系统信息
        const infoResponse = await fetch('/api/system/info');
        const systemInfo = await infoResponse.json();
        
        // 填充网络设置
        document.getElementById('auto-ip').checked = currentConfig.network.auto_detect_ip !== false;
        document.getElementById('manual-ip').checked = currentConfig.network.auto_detect_ip === false;
        document.getElementById('manual-ip-value').value = currentConfig.network.manual_ip || '';
        toggleIpMode();
        
        // 显示检测到的IP
        const detectedIps = systemInfo.detected_ips || [];
        document.getElementById('detected-ips').innerHTML = 
            `检测到的IP地址: ${detectedIps.join(', ') || '无'}`;
        
        // 填充请求设置
        document.getElementById('timeout-seconds').value = currentConfig.request.timeout_seconds;
        document.getElementById('max-concurrent').value = currentConfig.request.max_concurrent_requests;
        
        // 填充监控设置
        document.getElementById('error-threshold').value = (currentConfig.monitoring.error_rate_threshold * 100).toFixed(0);
        document.getElementById('response-threshold').value = currentConfig.monitoring.response_time_threshold;
        
        // 显示当前访问地址
        displayCurrentUrls(systemInfo.server_urls);
        
    } catch (error) {
        console.error('加载设置失败:', error);
        alert('加载设置失败: ' + error.message);
    }
}

// 切换IP模式
function toggleIpMode() {
    const isManual = document.getElementById('manual-ip').checked;
    document.getElementById('manual-ip-input').style.display = isManual ? 'block' : 'none';
}

// 保存网络设置
async function saveNetworkSettings() {
    try {
        const isManual = document.getElementById('manual-ip').checked;
        const manualIp = document.getElementById('manual-ip-value').value.trim();
        
        if (isManual && !manualIp) {
            alert('请输入IP地址');
            return;
        }
        
        const config = {
            network: {
                auto_detect_ip: !isManual,
                manual_ip: isManual ? manualIp : null
            }
        };
        
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        
        if (response.ok) {
            alert('网络设置已保存，刷新页面后生效');
            loadSettings();
        } else {
            throw new Error('保存失败');
        }
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

// 保存请求设置
async function saveRequestSettings() {
    try {
        const config = {
            request: {
                timeout_seconds: parseInt(document.getElementById('timeout-seconds').value),
                max_concurrent_requests: parseInt(document.getElementById('max-concurrent').value)
            }
        };
        
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        
        if (response.ok) {
            alert('请求设置已保存');
            loadSettings();
        } else {
            throw new Error('保存失败');
        }
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

// 保存监控设置
async function saveMonitoringSettings() {
    try {
        const config = {
            monitoring: {
                error_rate_threshold: parseInt(document.getElementById('error-threshold').value) / 100,
                response_time_threshold: parseInt(document.getElementById('response-threshold').value)
            }
        };
        
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        
        if (response.ok) {
            alert('告警设置已保存');
            loadSettings();
        } else {
            throw new Error('保存失败');
        }
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

// 显示当前访问地址
function displayCurrentUrls(urls) {
    const container = document.getElementById('current-urls');
    container.innerHTML = `
        <div>📍 本地访问: <a href="${urls.local}" target="_blank">${urls.local}</a></div>
        <div>🌐 局域网访问: <a href="${urls.network}" target="_blank">${urls.network}</a></div>
        <div>📊 监控面板: <a href="${urls.monitor}" target="_blank">${urls.monitor}</a></div>
        <div>📈 Prometheus: <a href="${urls.metrics}" target="_blank">${urls.metrics}</a></div>
        <div>🏥 健康检查: <a href="${urls.health}" target="_blank">${urls.health}</a></div>
    `;
}

        // 初始化
        connectWebSocket();
        refreshData();
        loadAlerts();  // 加载历史告警
        
    </script>
</body>
</html>
"""
print("\n" + "="*60)
print("🚀 LMArena 反向代理服务器")
print("="*60)
print(f"📍 本地访问: http://localhost:{Config.PORT}")
print(f"📍 局域网访问: http://{get_local_ip()}:{Config.PORT}")
print(f"📊 监控面板: http://{get_local_ip()}:{Config.PORT}/monitor")
print("="*60)
print("💡 提示: 请确保浏览器扩展已安装并启用")
print("💡 如果使用代理软件，局域网IP可能不准确")
print("💡 如果局域网IP不准确可以在此文件中修改，将MANUAL_IP = None  修改为MANUAL_IP = 你指定的IP地址如：192.168.0.1")
print("="*60 + "\n")
if __name__ == "__main__":
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)

