#!/usr/bin/env python3
"""
パフォーマンス最適化モジュール
Discordボットの並列処理とリソース管理を効率化
"""

import asyncio
import logging
import time
import psutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Callable, Awaitable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class TaskPriority(Enum):
    """タスクの優先度"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class TaskInfo:
    """タスク情報"""
    id: str
    name: str
    priority: TaskPriority
    created_at: datetime
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3

class PerformanceMonitor:
    """パフォーマンス監視クラス"""
    
    def __init__(self, monitoring_interval: float = 30.0):
        self.monitoring_interval = monitoring_interval
        self.metrics = {
            'cpu_usage': [],
            'memory_usage': [],
            'task_completion_times': [],
            'error_counts': {},
            'active_tasks': 0
        }
        self.start_time = datetime.now()
        self.is_monitoring = False
        self.monitor_task = None
    
    def start_monitoring(self):
        """監視を開始"""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("パフォーマンス監視を開始しました")
    
    def stop_monitoring(self):
        """監視を停止"""
        self.is_monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
        logger.info("パフォーマンス監視を停止しました")
    
    async def _monitor_loop(self):
        """監視ループ"""
        while self.is_monitoring:
            try:
                # システムメトリクスを収集
                cpu_percent = psutil.cpu_percent(interval=1)
                memory_info = psutil.virtual_memory()
                
                # メトリクスを記録
                self.metrics['cpu_usage'].append({
                    'timestamp': datetime.now(),
                    'value': cpu_percent
                })
                
                self.metrics['memory_usage'].append({
                    'timestamp': datetime.now(),
                    'value': memory_info.percent
                })
                
                # 古いメトリクスを削除（最新1時間分のみ保持）
                cutoff_time = datetime.now() - timedelta(hours=1)
                self.metrics['cpu_usage'] = [
                    m for m in self.metrics['cpu_usage'] 
                    if m['timestamp'] > cutoff_time
                ]
                self.metrics['memory_usage'] = [
                    m for m in self.metrics['memory_usage'] 
                    if m['timestamp'] > cutoff_time
                ]
                
                # 警告レベルの監視
                if cpu_percent > 80:
                    logger.warning(f"CPU使用率が高くなっています: {cpu_percent}%")
                
                if memory_info.percent > 85:
                    logger.warning(f"メモリ使用率が高くなっています: {memory_info.percent}%")
                
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"パフォーマンス監視エラー: {e}")
                await asyncio.sleep(5)
    
    def record_task_completion(self, task_name: str, execution_time: float):
        """タスク完了時間を記録"""
        self.metrics['task_completion_times'].append({
            'task_name': task_name,
            'execution_time': execution_time,
            'timestamp': datetime.now()
        })
    
    def record_error(self, error_type: str):
        """エラーを記録"""
        if error_type not in self.metrics['error_counts']:
            self.metrics['error_counts'][error_type] = 0
        self.metrics['error_counts'][error_type] += 1
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """パフォーマンスサマリーを取得"""
        now = datetime.now()
        uptime = now - self.start_time
        
        # 平均CPU・メモリ使用率
        avg_cpu = 0
        avg_memory = 0
        
        if self.metrics['cpu_usage']:
            avg_cpu = sum(m['value'] for m in self.metrics['cpu_usage']) / len(self.metrics['cpu_usage'])
        
        if self.metrics['memory_usage']:
            avg_memory = sum(m['value'] for m in self.metrics['memory_usage']) / len(self.metrics['memory_usage'])
        
        # タスク実行時間の統計
        task_times = [t['execution_time'] for t in self.metrics['task_completion_times']]
        avg_task_time = sum(task_times) / len(task_times) if task_times else 0
        
        return {
            'uptime_seconds': uptime.total_seconds(),
            'avg_cpu_usage': round(avg_cpu, 2),
            'avg_memory_usage': round(avg_memory, 2),
            'avg_task_execution_time': round(avg_task_time, 3),
            'total_tasks_completed': len(self.metrics['task_completion_times']),
            'active_tasks': self.metrics['active_tasks'],
            'error_counts': self.metrics['error_counts'].copy()
        }

class AsyncTaskManager:
    """非同期タスク管理クラス"""
    
    def __init__(self, max_concurrent_tasks: int = 10, thread_pool_size: int = 4):
        self.max_concurrent_tasks = max_concurrent_tasks
        self.thread_pool = ThreadPoolExecutor(max_workers=thread_pool_size)
        self.active_tasks: Dict[str, TaskInfo] = {}
        self.task_queue = asyncio.PriorityQueue()
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self.performance_monitor = PerformanceMonitor()
        self.is_running = False
        self.worker_task = None
        
        logger.info(f"TaskManager初期化: 最大同時実行数={max_concurrent_tasks}, スレッドプール={thread_pool_size}")
    
    def start(self):
        """タスクマネージャーを開始"""
        if self.is_running:
            return
        
        self.is_running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        self.performance_monitor.start_monitoring()
        logger.info("AsyncTaskManagerを開始しました")
    
    def stop(self):
        """タスクマネージャーを停止"""
        self.is_running = False
        if self.worker_task:
            self.worker_task.cancel()
        self.performance_monitor.stop_monitoring()
        self.thread_pool.shutdown(wait=True)
        logger.info("AsyncTaskManagerを停止しました")
    
    async def submit_task(
        self,
        task_func: Callable,
        task_name: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        *args, **kwargs
    ) -> str:
        """タスクを投入"""
        task_id = f"{task_name}_{int(time.time() * 1000)}"
        task_info = TaskInfo(
            id=task_id,
            name=task_name,
            priority=priority,
            created_at=datetime.now(),
            timeout=timeout
        )
        
        # 優先度の逆順でキューに追加（数値が大きいほど優先度が高い）
        priority_value = -priority.value
        await self.task_queue.put((priority_value, task_id, task_func, args, kwargs, task_info))
        
        logger.debug(f"タスクを投入しました: {task_name} (ID: {task_id}, 優先度: {priority.name})")
        return task_id
    
    async def _worker_loop(self):
        """ワーカーループ"""
        while self.is_running:
            try:
                # タスクを取得
                try:
                    item = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                    priority_value, task_id, task_func, args, kwargs, task_info = item
                except asyncio.TimeoutError:
                    continue
                
                # セマフォを取得してタスクを実行
                async with self.semaphore:
                    await self._execute_task(task_id, task_func, args, kwargs, task_info)
                
            except Exception as e:
                logger.error(f"ワーカーループエラー: {e}")
                await asyncio.sleep(1)
    
    async def _execute_task(self, task_id: str, task_func: Callable, args: tuple, kwargs: dict, task_info: TaskInfo):
        """タスクを実行"""
        start_time = time.time()
        self.active_tasks[task_id] = task_info
        self.performance_monitor.metrics['active_tasks'] += 1
        
        try:
            logger.debug(f"タスク実行開始: {task_info.name} (ID: {task_id})")
            
            # タイムアウト設定
            timeout = task_info.timeout or 30.0
            
            # 非同期関数か同期関数かを判定
            if asyncio.iscoroutinefunction(task_func):
                result = await asyncio.wait_for(task_func(*args, **kwargs), timeout=timeout)
            else:
                # 同期関数は別スレッドで実行
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(self.thread_pool, task_func, *args, **kwargs),
                    timeout=timeout
                )
            
            execution_time = time.time() - start_time
            self.performance_monitor.record_task_completion(task_info.name, execution_time)
            
            logger.debug(f"タスク完了: {task_info.name} (実行時間: {execution_time:.3f}秒)")
            
        except asyncio.TimeoutError:
            logger.warning(f"タスクタイムアウト: {task_info.name} (制限時間: {timeout}秒)")
            self.performance_monitor.record_error('timeout')
            
            # リトライ処理
            if task_info.retry_count < task_info.max_retries:
                task_info.retry_count += 1
                logger.info(f"タスクをリトライします: {task_info.name} (試行回数: {task_info.retry_count})")
                await self.task_queue.put((-task_info.priority.value, task_id, task_func, args, kwargs, task_info))
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"タスク実行エラー: {task_info.name} - {e}")
            self.performance_monitor.record_error('execution_error')
            
        finally:
            # クリーンアップ
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
            self.performance_monitor.metrics['active_tasks'] -= 1
    
    def get_status(self) -> Dict[str, Any]:
        """現在の状態を取得"""
        return {
            'is_running': self.is_running,
            'queue_size': self.task_queue.qsize(),
            'active_tasks': len(self.active_tasks),
            'max_concurrent_tasks': self.max_concurrent_tasks,
            'performance_summary': self.performance_monitor.get_performance_summary()
        }
    
    def get_active_tasks(self) -> List[Dict[str, Any]]:
        """実行中のタスク一覧を取得"""
        return [
            {
                'id': task_info.id,
                'name': task_info.name,
                'priority': task_info.priority.name,
                'created_at': task_info.created_at.isoformat(),
                'running_time': (datetime.now() - task_info.created_at).total_seconds()
            }
            for task_info in self.active_tasks.values()
        ]

class OptimizedBot:
    """最適化されたボット基底クラス"""
    
    def __init__(self, max_concurrent_tasks: int = 15):
        self.task_manager = AsyncTaskManager(max_concurrent_tasks)
        self.start_time = datetime.now()
        
    async def start_optimization_systems(self):
        """最適化システムを開始"""
        self.task_manager.start()
        logger.info("最適化システムが開始されました")
    
    async def stop_optimization_systems(self):
        """最適化システムを停止"""
        self.task_manager.stop()
        logger.info("最適化システムが停止されました")
    
    async def submit_background_task(
        self,
        task_func: Callable,
        task_name: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        *args, **kwargs
    ) -> str:
        """バックグラウンドタスクを投入"""
        return await self.task_manager.submit_task(
            task_func, task_name, priority, timeout, *args, **kwargs
        )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """パフォーマンス統計を取得"""
        uptime = datetime.now() - self.start_time
        base_stats = {
            'uptime_seconds': uptime.total_seconds(),
            'start_time': self.start_time.isoformat()
        }
        
        task_manager_stats = self.task_manager.get_status()
        base_stats.update(task_manager_stats)
        
        return base_stats
