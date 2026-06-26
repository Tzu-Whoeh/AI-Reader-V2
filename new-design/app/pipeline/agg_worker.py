"""后台聚合 worker:单常驻线程 + dirty 标志。

设计目标(并行聚合,不阻塞主分析循环):
  - 主循环每章完成只 mark_dirty(),开销极小,不等待聚合。
  - 单 worker 线程消费:有 dirty 就清标志 → 聚合到临时目录 → 原子切换到 global/。
  - 自动合并(coalesce):聚合进行中来的多次 mark_dirty 合并为"再跑一次",不堆积。
  - 串行:同一时刻只有一个聚合在跑,天然无写冲突。
  - 原子:写 global.tmp 再 os.replace 切换,前端永不读到半成品。
  - 崩溃隔离:聚合异常被吞(记日志),不影响主分析。
"""
import threading, traceback


class AggWorker:
    def __init__(self, store_root, aggregate_fn, storage_mod, poll=1.0):
        self._root = store_root
        self._aggregate = aggregate_fn        # aggregate.aggregate(store)
        self._storage = storage_mod           # storage 模块(用其 Store)
        self._poll = poll
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.last_counts = None
        self.runs = 0

    def start(self):
        if self._thread: return
        self._thread = threading.Thread(target=self._loop, name="agg-worker", daemon=True)
        self._thread.start()

    def mark_dirty(self):
        """主循环每章完成调用:标记需要重新聚合。立即返回,不阻塞。"""
        self._dirty.set()

    def stop(self, final=True):
        """停止 worker。final=True 时确保最后再聚合一次(把最终状态落盘)。
        必须先停后台线程再跑 final,避免与 _loop 并发聚合。"""
        # 1. 先让后台线程退出(不再消费 dirty)
        self._stop.set()
        self._dirty.set()      # 唤醒可能在 wait 的线程让它检查 _stop
        if self._thread:
            self._thread.join(timeout=15)
            self._thread=None
        # 2. 线程已停,此时独占,安全地同步跑最后一次聚合
        if final:
            self._run_once()

    def _loop(self):
        while not self._stop.is_set():
            # 等到有 dirty 或被唤醒
            triggered = self._dirty.wait(timeout=self._poll)
            if self._stop.is_set(): break
            if not triggered: continue
            self._run_once()

    def _run_once(self):
        # 清标志(在聚合前清:聚合期间新来的 mark_dirty 会再次置位 → 下轮再跑)
        self._dirty.clear()
        try:
            # 写临时目录,完成后原子切换
            store = self._storage.Store(self._root, global_subdir="global.tmp")
            idx = self._aggregate(store)
            store.commit_global()
            self.last_counts = idx.get("counts", {}) if isinstance(idx, dict) else None
            self.runs += 1
        except Exception as e:
            print(f"[agg-worker] 聚合失败(忽略,不影响主分析): {e}")
            traceback.print_exc()
